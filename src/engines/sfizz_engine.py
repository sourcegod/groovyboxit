#python3
"""
    File: src/engines/sfizz_engine.py
    Moteur SFZ : libsfizz liée par ctypes (Phase 8 étape 7b1, docs/DESIGN.md
    § 7a2 Z8, Z9 ; compilation : docs/sfizz_build.md), derrière l'interface
    BankEngine.

    - « Emplacement » = indice du slot du Rack (0..15) : load(slot, path)
      retient le fichier .sfz du slot ; select(canal, slot, …) lie le canal
      à ce fichier. Banque et programme sont ignorés (un .sfz = un
      instrument).
    - Une instance sfizz par canal (Z5) : une instance sfizz n'a pas de
      canal MIDI ; chaque canal a la sienne, donc son volume (CC7) et son
      pan (CC10).
    - sfizz n'est appelé que depuis le callback audio (Z9) : les appels de
      l'UI, des threading.Timer et du séquenceur déposent des événements
      dans une file (collections.deque, ajout atomique), vidée par render()
      avant le rendu. Le chargement d'un .sfz (bloquant) se fait dans un
      fil, sur une instance neuve, mise en place par un événement
      « échange » ; l'ancienne instance est libérée hors du callback.
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
EV_NOTE_ON, EV_NOTE_OFF, EV_CC, EV_BEND, EV_SOUNDS_OFF, EV_SWAP = range(6)


class SfzEngine(BankEngine):
    """BankEngine sur une instance sfizz par canal."""

    NUM_BANK_SLOTS = 16     # emplacement = slot du Rack (Z8)
    MAX_BLOCK      = 1024   # taille de bloc donnée à sfizz ; un bloc plus long est découpé
    # Gain appliqué au rendu : à 1.0, les instruments d'essai sortent à peu
    # près au niveau de FluidR3 réglé à 0.4 (Phase 8 étape 7b1) ; réglable
    # par la clé "sfizz_gain".
    GAIN           = 1.0

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
        self._paths      = [None] * self.NUM_BANK_SLOTS   # fichier de chaque slot
        self._chan_path  = [None] * n      # fichier voulu pour chaque canal
        self._gen        = [0] * n         # génération du chargement voulu
        self._inst       = [None] * n      # instance en place (callback seul)
        self._busy       = [False] * n     # événement reçu depuis le dernier rendu
        # État des contrôleurs de chaque canal, rejoué sur une instance neuve
        self._ccs        = [dict() for _ in range(n)]
        self._bend       = [0] * n
        self._queue      = collections.deque()
        self._retired    = collections.deque()   # instances à libérer hors callback
        self._lock       = threading.Lock()      # chargements / libérations (hors callback)
        self._threads    = []
        self._L = np.zeros(self.MAX_BLOCK, np.float32)
        self._R = np.zeros(self.MAX_BLOCK, np.float32)
        p = ctypes.POINTER(ctypes.c_float)
        self._chans = (p * 2)(self._L.ctypes.data_as(p), self._R.ctypes.data_as(p))

    # -- banques (emplacement = slot du Rack) ----------------------------

    def load(self, slot, path):
        """Retient le fichier .sfz du slot. Le fichier est lu par sfizz à
        la sélection d'un canal (select), en arrière-plan : un fichier
        refusé n'est signalé qu'alors (status_cb), le canal restant muet.
        Retourne False si slot est invalide ou si le fichier n'existe pas."""
        if not 0 <= slot < self.NUM_BANK_SLOTS or not path or not os.path.isfile(path):
            return False
        self._paths[slot] = path
        return True

    def unload(self, slot):
        if 0 <= slot < self.NUM_BANK_SLOTS:
            self._paths[slot] = None

    def loaded_path(self, slot):
        return self._paths[slot] if 0 <= slot < self.NUM_BANK_SLOTS else None

    def presets(self, slot):
        """Un seul « preset » : l'instrument du fichier (banque et programme
        sans objet)."""
        path = self.loaded_path(slot)
        if path is None:
            return []
        return [(0, 0, os.path.splitext(os.path.basename(path))[0])]

    # -- canaux ----------------------------------------------------------

    def select(self, channel, slot, bank, program):
        """Lie le canal au fichier du slot ; le charge si le canal jouait
        un autre fichier (dans un fil en temps réel). Retourne False si le
        slot n'a pas de fichier."""
        path = self.loaded_path(slot)
        if path is None:
            return False
        if self._chan_path[channel] == path:
            return True
        self._chan_path[channel] = path
        self._gen[channel] += 1
        gen = self._gen[channel]
        if self._realtime:
            t = threading.Thread(target=self._load_instance,
                                 args=(channel, path, gen), daemon=True)
            self._threads.append(t)
            t.start()
        else:
            self._load_instance(channel, path, gen)
        return True

    def channel_path(self, channel):
        """Fichier voulu pour le canal (chargé ou en cours), ou None."""
        return self._chan_path[channel]

    def channel_ready(self, channel):
        """Vrai si l'instance du canal est en place et à jour."""
        inst = self._inst[channel]
        return inst is not None and inst[1] == self._gen[channel]

    def wait_loaded(self):
        """Attend la fin des chargements en cours (tests, démarrage)."""
        for t in list(self._threads):
            t.join()
        self._threads = [t for t in self._threads if t.is_alive()]

    def _load_instance(self, channel, path, gen):
        """Crée et charge une instance neuve, puis la met en place (par un
        événement d'échange en temps réel)."""
        lib = self._lib
        synth = lib.sfizz_create_synth()
        lib.sfizz_set_sample_rate(synth, float(self._samplerate))
        lib.sfizz_set_samples_per_block(synth, self.MAX_BLOCK)
        ok = lib.sfizz_load_file(synth, os.fsencode(path)) \
            and lib.sfizz_get_num_regions(synth) > 0
        name = os.path.splitext(os.path.basename(path))[0]
        if not ok:
            lib.sfizz_free(synth)
            self._status(f"SFZ refusé : {name}")
            return
        if gen != self._gen[channel]:        # un autre fichier a été demandé entre-temps
            lib.sfizz_free(synth)
            return
        self._push(EV_SWAP, channel, synth, gen)
        self._free_retired()
        self._status(f"SFZ prêt : {name} (canal {channel + 1})")

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
        """Sans effet : un .sfz est un seul instrument (Z11)."""

    def all_notes_off(self):
        for ch in range(self.NUM_CHANNELS):
            self.cc(ch, 123, 0)

    def all_sounds_off(self):
        for ch in range(self.NUM_CHANNELS):
            self.channel_sounds_off(ch)

    def channel_sounds_off(self, channel):
        """Coupe net les sons du canal, notes tenues par la pédale comprises
        (sfizz_all_sound_off)."""
        self._push(EV_SOUNDS_OFF, channel, 0, 0)

    def reset_controllers(self):
        for ch in range(self.NUM_CHANNELS):
            self.cc(ch, 121, 0)

    def active_voices(self):
        lib, n = self._lib, 0
        for inst in list(self._inst):
            if inst is not None:
                n += max(0, lib.sfizz_get_num_active_voices(inst[0]))
        return n

    # -- file d'événements -------------------------------------------------

    def _push(self, kind, channel, a, b):
        ev = (kind, channel, a, b)
        if self._realtime:
            self._queue.append(ev)
        else:
            self._apply(ev)

    def _apply(self, ev):
        """Applique un événement (dans le callback en temps réel)."""
        kind, ch, a, b = ev
        lib = self._lib
        if kind == EV_SWAP:
            synth, gen = a, b
            if gen != self._gen[ch]:         # dépassé par un chargement plus récent
                self._retired.append(synth)
                return
            old = self._inst[ch]
            self._inst[ch] = (synth, gen)
            if old is not None:
                self._retired.append(old[0])
            for num, value in self._ccs[ch].items():    # état du canal rejoué
                lib.sfizz_send_cc(synth, 0, num, value)
            if self._bend[ch]:
                lib.sfizz_send_pitch_wheel(synth, 0, self._bend[ch])
            self._busy[ch] = True
            return
        inst = self._inst[ch]
        if inst is None:
            return
        synth = inst[0]
        if kind == EV_NOTE_ON:
            lib.sfizz_send_note_on(synth, 0, a, b)
        elif kind == EV_NOTE_OFF:
            lib.sfizz_send_note_off(synth, 0, a, 0)
        elif kind == EV_CC:
            lib.sfizz_send_cc(synth, 0, a, b)
        elif kind == EV_BEND:
            lib.sfizz_send_pitch_wheel(synth, 0, a)
        elif kind == EV_SOUNDS_OFF:
            lib.sfizz_all_sound_off(synth)
        self._busy[ch] = True

    def _free_retired(self):
        """Libère les instances remplacées (hors callback)."""
        with self._lock:
            while self._retired:
                try:
                    synth = self._retired.popleft()
                except IndexError:
                    break
                self._lib.sfizz_free(synth)

    # -- rendu -----------------------------------------------------------

    def render(self, out):
        """Vide la file, puis ajoute le rendu de chaque canal actif dans out
        (float32 (frames, 2)), par blocs d'au plus MAX_BLOCK."""
        queue = self._queue
        while queue:
            try:
                ev = queue.popleft()
            except IndexError:
                break
            self._apply(ev)
        lib, L, R, gain = self._lib, self._L, self._R, self.gain
        for ch in range(self.NUM_CHANNELS):
            inst = self._inst[ch]
            if inst is None:
                continue
            synth = inst[0]
            if not self._busy[ch] and lib.sfizz_get_num_active_voices(synth) <= 0:
                continue                      # instance au repos : rien à rendre
            self._busy[ch] = False
            pos, frames = 0, len(out)
            while pos < frames:
                n = min(self.MAX_BLOCK, frames - pos)
                lib.sfizz_render_block(synth, self._chans, 2, n)
                out[pos:pos + n, 0] += L[:n] * gain
                out[pos:pos + n, 1] += R[:n] * gain
                pos += n

    def render_copy(self):
        """Moteur neuf hors temps réel (chargements bloquants, appels
        directs), aux mêmes réglages et avec les mêmes fichiers de slots ;
        les canaux se chargent à leur sélection (export WAV, Phase 8)."""
        copy = SfzEngine(self._samplerate, self.gain, realtime=False)
        copy._paths = list(self._paths)
        return copy

    def close(self):
        self.wait_loaded()
        for ch in range(self.NUM_CHANNELS):
            inst = self._inst[ch]
            self._inst[ch] = None
            if inst is not None:
                self._retired.append(inst[0])
        while self._queue:                   # instances jamais mises en place
            ev = self._queue.popleft()
            if ev[0] == EV_SWAP:
                self._retired.append(ev[2])
        self._free_retired()

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
