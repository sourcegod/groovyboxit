#python3
"""
    File: src/engines/sfizz_engine.py
    Moteur SFZ : libsfizz liée par ctypes (Phase 8 étape 7b1, docs/DESIGN.md
    § 7a2 Z8, Z9 ; compilation : docs/sfizz_build.md), derrière l'interface
    BankEngine.

    - « Emplacement » = indice du slot du Rack (0..15) : load(slot, source)
      lit la source de programmes du slot (Phase 8 étape 7f1, § 7a3 Z16-Z22 :
      .sfz, .bank.xml de Sforzando, dossier, banque SFZ JSON ; voir
      sfz_sources.py) ; select(canal, slot, banque, programme) donne au
      canal le .sfz de ce programme (banque ignorée).
    - Instances sfizz par canal (Z5, Z19, Z22) : une instance sfizz n'a pas
      de canal MIDI ; chaque canal a la sienne (son volume CC7, son pan
      CC10), plus des instances préparées pour les programmes que le
      pattern demandera (prefetch) et des instances en extinction, qui
      finissent leurs notes après un Program Change.
    - sfizz n'est appelé que depuis le callback audio (Z9) : les appels de
      l'UI, des threading.Timer et du séquenceur déposent des événements
      dans une file (collections.deque, ajout atomique), vidée par render()
      avant le rendu. Le chargement d'un .sfz (bloquant) se fait dans un
      fil, sur une instance neuve, mise en place par un événement
      « échange » ; les instances qui ne servent plus sont libérées hors du
      callback.
    - Hors temps réel (render_copy, rendu de l'export WAV) : realtime=False,
      les événements sont appliqués aussitôt et le chargement est bloquant.

    Prototype Python, cible C/C++ : file d'événements et échange d'instance
    se transposent tels quels (file sans verrou en C/C++).
    Date: Wed, 04/11/2026
    Author: Coolbrother
"""

import collections
import ctypes
import ctypes.util
import os
import threading

import numpy as np

from engines.bank_engine import BankEngine
from sfz_sources import read_source


class SfizzUnavailable(RuntimeError):
    """libsfizz introuvable ou inutilisable."""


# ~/.local/lib n'est pas dans le chemin de ldconfig : chemin complet d'abord
# (docs/sfizz_build.md § 7), puis le système.
_LIB_NAMES = (os.path.expanduser("~/.local/lib/libsfizz.so.1"),
              "libsfizz.so.1", "libsfizz.so")
_lib = None


def _declare(lib):
    """Signatures des fonctions utilisées (argtypes / restype)."""
    vp, ci, cf, cb, cc = (ctypes.c_void_p, ctypes.c_int, ctypes.c_float,
                          ctypes.c_bool, ctypes.c_char_p)
    fpp = ctypes.POINTER(ctypes.POINTER(cf))
    sigs = {
        "sfizz_create_synth":          ([], vp),
        "sfizz_free":                  ([vp], None),
        "sfizz_load_file":             ([vp, cc], cb),
        "sfizz_set_sample_rate":       ([vp, cf], None),
        "sfizz_set_samples_per_block": ([vp, ci], None),
        "sfizz_send_note_on":          ([vp, ci, ci, ci], None),
        "sfizz_send_note_off":         ([vp, ci, ci, ci], None),
        "sfizz_send_cc":               ([vp, ci, ci, ci], None),
        "sfizz_send_pitch_wheel":      ([vp, ci, ci], None),
        "sfizz_render_block":          ([vp, fpp, ci, ci], None),
        "sfizz_get_num_regions":       ([vp], ci),
        "sfizz_get_num_active_voices": ([vp], ci),
        "sfizz_all_sound_off":         ([vp], None),
        "sfizz_add_external_definitions": ([vp, cc, cc], None),
    }
    for name, (args, res) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype  = res


def load_library():
    """Charge libsfizz une seule fois ; SfizzUnavailable sinon."""
    global _lib
    if _lib is not None:
        return _lib
    for name in _LIB_NAMES + (ctypes.util.find_library("sfizz"),):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            _declare(lib)
        except (OSError, AttributeError):
            continue
        _lib = lib
        return lib
    raise SfizzUnavailable("libsfizz introuvable (voir docs/sfizz_build.md)")


def sfizz_available():
    try:
        load_library()
        return True
    except SfizzUnavailable:
        return False


# Types d'événements de la file (entiers : transposables en C/C++)
EV_NOTE_ON, EV_NOTE_OFF, EV_CC, EV_BEND, EV_SOUNDS_OFF, EV_SWAP, EV_DROP = range(7)


class SfzEngine(BankEngine):
    """BankEngine sur des instances sfizz : par canal, une instance
    courante, des instances préparées (programmes que le pattern
    demandera, Z19) et des instances en extinction (remplacées par un
    Program Change, elles finissent leurs notes, Z22).

    Partage des rôles entre les fils (Z9, Z22) :
    - fils de l'UI, des minuteries, du séquenceur et du chargement : ils
      tiennent le registre des instances de chaque canal (_owned, sous
      _lock) et déposent des événements dans la file ;
    - callback audio : seul à appeler sfizz pour le jeu et le rendu ; seul
      juge de ce qu'il tient (instance courante _inst, en extinction
      _fading). Une instance qui ne sert plus lui est confiée par EV_DROP ;
      il la met dans _freeq quand il ne la tient plus, et elle est libérée
      hors du callback (_free_pending)."""

    NUM_BANK_SLOTS = 16     # emplacement = slot du Rack (Z8)
    MAX_BLOCK      = 1024   # taille de bloc donnée à sfizz ; un bloc plus long est découpé
    # Gain appliqué au rendu : à 1.0, les instruments d'essai sortent un peu
    # moins fort que FluidR3 réglé à 0.4 (Phase 8 étape 7b1) ; 1.5, un peu
    # plus fort mais plus agréable et plus clair (essai de 7d1) ; réglable
    # par la clé "sfizz_gain".
    GAIN           = 1.5

    def __init__(self, samplerate=44100, gain=GAIN, realtime=True, status_cb=None):
        """realtime : True = file d'événements vidée par render() et
        chargements dans un fil (écoute) ; False = appels directs et
        chargements bloquants (rendu hors temps réel). status_cb(str) :
        message de fin de chargement ou d'erreur, appelé depuis le fil de
        chargement (doit être thread-safe)."""
        super().__init__("gs")
        self._lib        = load_library()
        self._samplerate = samplerate
        self.gain        = gain
        self._realtime   = realtime
        self.status_cb   = status_cb
        n = self.NUM_CHANNELS
        self._paths      = [None] * self.NUM_BANK_SLOTS   # source de chaque slot
        self._sources    = [None] * self.NUM_BANK_SLOTS   # SfzSource lue
        # Registre (fils hors callback, sous _lock)
        self._target     = [None] * n      # clé (fichier, définitions) du programme voulu
        self._target_name = [None] * n
        self._wanted     = [set() for _ in range(n)]      # clés préparées (Z19)
        self._owned      = [dict() for _ in range(n)]     # clé → instance vivante
        self._loading    = [set() for _ in range(n)]
        # Callback
        self._inst       = [None] * n      # (instance, clé) courante
        self._fading     = [[] for _ in range(n)]         # instances en extinction
        self._drop       = set()           # instances à libérer dès qu'elles se taisent
        self._busy       = [False] * n     # événement reçu depuis le dernier rendu
        # État des contrôleurs de chaque canal, rejoué sur l'instance qui
        # devient courante
        self._ccs        = [dict() for _ in range(n)]
        self._bend       = [0] * n
        self._queue      = collections.deque()
        self._freeq      = collections.deque()   # instances à libérer hors callback
        self._lock       = threading.RLock()
        self._threads    = []
        self._L = np.zeros(self.MAX_BLOCK, np.float32)
        self._R = np.zeros(self.MAX_BLOCK, np.float32)
        p = ctypes.POINTER(ctypes.c_float)
        self._chans = (p * 2)(self._L.ctypes.data_as(p), self._R.ctypes.data_as(p))

    # -- banques (emplacement = slot du Rack, source de programmes) --------

    def load(self, slot, path):
        """Lit la source de programmes du slot (Z20) : .sfz, .bank.xml,
        dossier ou banque SFZ JSON. Les .sfz eux-mêmes sont lus par sfizz à
        la sélection d'un canal (en arrière-plan). Retourne False si le slot
        est invalide ou si la source n'a aucun programme ; les messages de
        la source (fichier introuvable…) passent par status_cb."""
        if not 0 <= slot < self.NUM_BANK_SLOTS or not path:
            return False
        source = read_source(path)
        for msg in source.messages:
            self._status(f"SFZ {source.name} : {msg}")
        if not source.programs:
            return False
        self._paths[slot]   = path
        self._sources[slot] = source
        return True

    def unload(self, slot):
        if 0 <= slot < self.NUM_BANK_SLOTS:
            self._paths[slot]   = None
            self._sources[slot] = None

    def loaded_path(self, slot):
        return self._paths[slot] if 0 <= slot < self.NUM_BANK_SLOTS else None

    def source(self, slot):
        return self._sources[slot] if 0 <= slot < self.NUM_BANK_SLOTS else None

    def presets(self, slot):
        """[(0, programme, nom)] de la source du slot (Z22)."""
        source = self.source(slot)
        if source is None:
            return []
        return [(0, p.program, p.name) for p in source.programs]

    # -- canaux ----------------------------------------------------------

    def select(self, channel, slot, bank, program):
        """Programme du canal : le .sfz numéro program de la source du slot
        (banque ignorée). Bascule aussitôt sur une instance déjà prête
        (préparée ou en extinction), sinon la charge (dans un fil en temps
        réel). Retourne False si le slot n'a pas de source ou pas ce
        programme."""
        source = self.source(slot)
        prog = source.program(program) if source is not None else None
        if prog is None:
            return False
        key = prog.key
        with self._lock:
            if self._target[channel] == key:
                return True
            self._target[channel] = key
            self._target_name[channel] = prog.name
            synth = self._owned[channel].get(key)
            if synth is not None:
                self._push(EV_SWAP, channel, synth, key)
            else:
                self._start_load(channel, prog, announce=True)
        self._collect()
        return True

    def prefetch(self, channel, slot, programs):
        """Prépare les programmes que le pattern demandera sur ce canal (Z19)
        : une instance chargée pour chacun (en arrière-plan en temps réel) ;
        les instances préparées qui ne figurent plus dans la liste (ni
        comme programme courant) sont abandonnées."""
        source = self.source(slot)
        keys, progs = set(), []
        if source is not None:
            for number in programs:
                prog = source.program(number)
                if prog is not None and prog.key not in keys:
                    keys.add(prog.key)
                    progs.append(prog)
        with self._lock:
            self._wanted[channel] = keys
            for prog in progs:
                if prog.key not in self._owned[channel]:
                    self._start_load(channel, prog, announce=False)
        self._collect()

    def release_channel(self, channel):
        """Plus aucune piste SFZ ne joue ce canal : ses instances sont
        abandonnées (la courante finit ses notes), la mémoire rendue."""
        with self._lock:
            self._target[channel] = None
            self._target_name[channel] = None
            self._wanted[channel] = set()
        self._collect()

    def channel_path(self, channel):
        """Fichier .sfz du programme voulu sur le canal, ou None."""
        key = self._target[channel]
        return key[0] if key else None

    def channel_ready(self, channel):
        """Vrai si l'instance courante du canal est celle du programme voulu."""
        inst = self._inst[channel]
        return inst is not None and self._target[channel] is not None \
            and inst[1] == self._target[channel]

    def wait_loaded(self):
        """Attend la fin des chargements en cours (tests, démarrage)."""
        while True:
            threads = [t for t in self._threads if t.is_alive()]
            if not threads:
                break
            for t in threads:
                t.join()
        self._threads = []

    def _start_load(self, channel, prog, announce):
        """Charge prog pour le canal (sous _lock), sauf s'il l'est déjà."""
        if prog.key in self._loading[channel]:
            return
        self._loading[channel].add(prog.key)
        if self._realtime:
            t = threading.Thread(target=self._load_instance,
                                 args=(channel, prog, announce), daemon=True)
            self._threads.append(t)
            t.start()
        else:
            self._load_instance(channel, prog, announce)

    def _load_instance(self, channel, prog, announce):
        """Crée et charge une instance neuve ; la garde si son programme est
        encore voulu (courant ou préparé), et la met en place s'il est le
        programme courant."""
        lib = self._lib
        synth = lib.sfizz_create_synth()
        lib.sfizz_set_sample_rate(synth, float(self._samplerate))
        lib.sfizz_set_samples_per_block(synth, self.MAX_BLOCK)
        for name, value in prog.defines:
            lib.sfizz_add_external_definitions(synth, name.encode(), value.encode())
        ok = lib.sfizz_load_file(synth, os.fsencode(prog.path)) \
            and lib.sfizz_get_num_regions(synth) > 0
        with self._lock:
            self._loading[channel].discard(prog.key)
            if not ok:
                lib.sfizz_free(synth)
                is_target = self._target[channel] == prog.key
            else:
                current = self._target[channel] == prog.key
                if current or prog.key in self._wanted[channel]:
                    self._owned[channel][prog.key] = synth
                    if current:
                        self._push(EV_SWAP, channel, synth, prog.key)
                else:
                    lib.sfizz_free(synth)      # plus voulu entre-temps
                    current = False
        if not ok:
            self._status(f"SFZ refusé : {prog.name}")
            return
        self._free_pending()
        if current and announce:
            self._status(f"SFZ prêt : {prog.name} (canal {channel + 1})")

    def _status(self, msg):
        if self.status_cb is not None:
            try:
                self.status_cb(msg)
            except Exception:
                pass

    def note_on(self, channel, note, velocity):
        self._push(EV_NOTE_ON, channel, note, velocity)

    def note_off(self, channel, note):
        self._push(EV_NOTE_OFF, channel, note, 0)

    def cc(self, channel, num, value):
        if num not in (120, 121, 123):       # messages de mode : pas un état à rejouer
            self._ccs[channel][num] = value
        elif num == 121:                     # Reset All Controllers
            self._ccs[channel].clear()
            self._bend[channel] = 0
        self._push(EV_CC, channel, num, value)

    def pitch_bend(self, channel, value):
        value = max(-8192, min(8191, int(value)))
        self._bend[channel] = value
        self._push(EV_BEND, channel, value, 0)

    def program_change(self, channel, program):
        """Sans effet ici : le routeur choisit le programme d'un canal par
        select (canal, slot, banque, programme), comme pour une banque."""

    def all_notes_off(self):
        for ch in range(self.NUM_CHANNELS):
            self.cc(ch, 123, 0)

    def all_sounds_off(self):
        for ch in range(self.NUM_CHANNELS):
            self.channel_sounds_off(ch)

    def channel_sounds_off(self, channel):
        """Coupe net les sons du canal, instances en extinction comprises,
        notes tenues par la pédale comprises (sfizz_all_sound_off)."""
        self._push(EV_SOUNDS_OFF, channel, 0, 0)

    def reset_controllers(self):
        for ch in range(self.NUM_CHANNELS):
            self.cc(ch, 121, 0)

    def active_voices(self):
        lib, n = self._lib, 0
        for ch in range(self.NUM_CHANNELS):
            inst = self._inst[ch]
            for synth in ([inst[0]] if inst is not None else []) + list(self._fading[ch]):
                n += max(0, lib.sfizz_get_num_active_voices(synth))
        return n

    # -- file d'événements -------------------------------------------------

    def _push(self, kind, channel, a, b):
        ev = (kind, channel, a, b)
        if self._realtime:
            self._queue.append(ev)
        else:
            self._apply(ev)
            self._free_pending()

    def _held(self, ch):
        """Instances que le callback fait sonner sur le canal."""
        inst = self._inst[ch]
        return ([inst[0]] if inst is not None else []) + self._fading[ch]

    def _apply(self, ev):
        """Applique un événement (dans le callback en temps réel)."""
        kind, ch, a, b = ev
        lib = self._lib
        if kind == EV_SWAP:
            self._apply_swap(ch, a, b)
            return
        if kind == EV_DROP:
            if a in self._held(ch):
                self._drop.add(a)              # libérée quand elle se taira
            else:
                self._freeq.append(a)
            return
        inst = self._inst[ch]
        if kind == EV_NOTE_ON:
            if inst is not None:
                lib.sfizz_send_note_on(inst[0], 0, a, b)
        else:
            # Fin de note, contrôleurs et coupures : aussi aux instances en
            # extinction (une note commencée avant un Program Change doit
            # recevoir sa fin, la pédale son relâchement)
            for synth in self._held(ch):
                if kind == EV_NOTE_OFF:
                    lib.sfizz_send_note_off(synth, 0, a, 0)
                elif kind == EV_CC:
                    lib.sfizz_send_cc(synth, 0, a, b)
                elif kind == EV_BEND:
                    lib.sfizz_send_pitch_wheel(synth, 0, a)
                elif kind == EV_SOUNDS_OFF:
                    lib.sfizz_all_sound_off(synth)
        self._busy[ch] = True

    def _apply_swap(self, ch, synth, key):
        """L'instance synth devient la courante du canal (si son programme est
        toujours le voulu) ; l'ancienne s'éteint, ou se repose si elle est
        déjà muette."""
        if key != self._target[ch]:
            return                             # dépassé : l'instance reste au registre
        old = self._inst[ch]
        if old is not None and old[0] == synth:
            return
        if synth in self._fading[ch]:
            self._fading[ch].remove(synth)
        self._inst[ch] = (synth, key)
        lib = self._lib
        lib.sfizz_send_cc(synth, 0, 121, 0)    # état propre, puis celui du canal
        for num, value in self._ccs[ch].items():
            lib.sfizz_send_cc(synth, 0, num, value)
        lib.sfizz_send_pitch_wheel(synth, 0, self._bend[ch])
        self._busy[ch] = True
        if old is not None:
            if lib.sfizz_get_num_active_voices(old[0]) > 0:
                self._fading[ch].append(old[0])
            elif old[0] in self._drop:
                self._drop.discard(old[0])
                self._freeq.append(old[0])

    def _collect(self):
        """Abandonne les instances qui ne sont plus voulues (ni courantes ni
        préparées) : confiées au callback par EV_DROP ; puis libère celles
        qu'il a rendues."""
        with self._lock:
            for ch in range(self.NUM_CHANNELS):
                keep = self._wanted[ch] | {self._target[ch]}
                for key in [k for k in self._owned[ch] if k not in keep]:
                    self._push(EV_DROP, ch, self._owned[ch].pop(key), 0)
        self._free_pending()

    def _free_pending(self):
        """Libère les instances rendues par le callback (hors callback)."""
        while self._freeq:
            try:
                synth = self._freeq.popleft()
            except IndexError:
                break
            self._lib.sfizz_free(synth)

    # -- rendu -----------------------------------------------------------

    def render(self, out):
        """Vide la file, puis ajoute le rendu de chaque instance qui sonne
        (courante, en extinction) dans out (float32 (frames, 2)), par blocs
        d'au plus MAX_BLOCK."""
        queue = self._queue
        while queue:
            try:
                ev = queue.popleft()
            except IndexError:
                break
            self._apply(ev)
        lib = self._lib
        for ch in range(self.NUM_CHANNELS):
            inst = self._inst[ch]
            if inst is not None and (self._busy[ch]
                                     or lib.sfizz_get_num_active_voices(inst[0]) > 0):
                self._render_into(inst[0], out)
            self._busy[ch] = False
            fading = self._fading[ch]
            for synth in list(fading):
                self._render_into(synth, out)
                if lib.sfizz_get_num_active_voices(synth) <= 0:
                    fading.remove(synth)       # éteinte
                    if synth in self._drop:
                        self._drop.discard(synth)
                        self._freeq.append(synth)

    def _render_into(self, synth, out):
        lib, L, R, gain = self._lib, self._L, self._R, self.gain
        pos, frames = 0, len(out)
        while pos < frames:
            n = min(self.MAX_BLOCK, frames - pos)
            lib.sfizz_render_block(synth, self._chans, 2, n)
            out[pos:pos + n, 0] += L[:n] * gain
            out[pos:pos + n, 1] += R[:n] * gain
            pos += n

    def render_copy(self):
        """Moteur neuf hors temps réel (chargements bloquants, appels
        directs), aux mêmes réglages et avec les mêmes sources de slots ;
        les canaux se chargent à leur sélection (export WAV, Phase 8)."""
        copy = SfzEngine(self._samplerate, self.gain, realtime=False)
        copy._paths   = list(self._paths)
        copy._sources = list(self._sources)
        return copy

    def close(self):
        """Libère toutes les instances (le callback ne doit plus tourner)."""
        self.wait_loaded()
        synths = set()
        with self._lock:
            for ch in range(self.NUM_CHANNELS):
                synths.update(self._owned[ch].values())
                self._owned[ch].clear()
                self._wanted[ch] = set()
                self._target[ch] = None
                inst = self._inst[ch]
                if inst is not None:
                    synths.add(inst[0])
                self._inst[ch] = None
                synths.update(self._fading[ch])
                self._fading[ch] = []
            while self._queue:
                ev = self._queue.popleft()
                if ev[0] in (EV_SWAP, EV_DROP):
                    synths.add(ev[2])
            while self._freeq:
                synths.add(self._freeq.popleft())
            self._drop.clear()
        for synth in synths:
            self._lib.sfizz_free(synth)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


#=========================================

if __name__ == "__main__":
    # Essai à l'écoute : quelques notes d'un .sfz, rendues par le callback de
    # SoundDeviceDriver, sur deux canaux (volume et pan différents). Depuis src/ :
    #   python3 -m engines.sfizz_engine [fichier.sfz] [note de départ]
    import sys
    import time
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sound_device_driver import SoundDeviceDriver
    from app_config import AppConfig

    cfg  = AppConfig(os.path.dirname(sys.path[0]))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        cfg.sfz_dir, "BengtNilsson.HeadroomPiano", "Headroom Piano.sfz")
    base = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    drv  = SoundDeviceDriver()
    eng  = SfzEngine(samplerate=drv.samplerate, gain=cfg.sfizz_gain, status_cb=print)
    print("Gain :", cfg.sfizz_gain)
    drv.add_render_source(eng.render)
    if not eng.load(0, path):
        sys.exit(f"Fichier introuvable : {path}")
    eng.select(0, 0, 0, 0)
    eng.wait_loaded()
    if not eng.channel_ready(0):
        time.sleep(0.2)                       # échange fait au prochain callback
    print("Gamme, canal 1")
    for step in (0, 2, 4, 5, 7, 9, 11, 12):
        eng.note_on(0, base + step, 100)
        time.sleep(0.3)
        eng.note_off(0, base + step)
    print("Accord, canal 2 : volume 60, pan à gauche")
    eng.select(1, 0, 0, 0)
    eng.wait_loaded()
    time.sleep(0.2)
    eng.cc(1, 7, 60)
    eng.cc(1, 10, 0)
    for note in (base, base + 4, base + 7):
        eng.note_on(1, note, 100)
    time.sleep(1.5)
    for note in (base, base + 4, base + 7):
        eng.note_off(1, note)
    time.sleep(1.5)
    print("Voix actives :", eng.active_voices())
    drv.remove_render_source(eng.render)
    eng.close()
    drv.close()
