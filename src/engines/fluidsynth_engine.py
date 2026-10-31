#python3
"""
    File: src/engines/fluidsynth_engine.py
    Moteur de banque FluidSynth (SF2/SF3) lié par ctypes à libfluidsynth
    (Phase 7 étape 17b1, docs/DESIGN.md § 17a1 D2) : une seule instance
    fluid_synth, 16 canaux, sans pilote audio propre — le rendu est tiré
    par le callback de SoundDeviceDriver (fluid_synth_write_float).

    L'API de FluidSynth est protégée par son propre verrou
    (synth.threadsafe-api, actif par défaut) : pas de verrou ici.
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""

import ctypes
import ctypes.util
import os

import numpy as np

from engines.bank_engine import BankEngine


class FluidSynthUnavailable(RuntimeError):
    """libfluidsynth introuvable ou inutilisable."""


_LIB_NAMES = ("libfluidsynth.so.3", "libfluidsynth.so.2", "libfluidsynth.so")
_lib = None


def _declare(lib):
    """Signatures des fonctions utilisées (argtypes / restype)."""
    vp, c_int, c_double, c_char_p = (ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_double, ctypes.c_char_p)
    sigs = {
        "new_fluid_settings":            ([], vp),
        "delete_fluid_settings":         ([vp], None),
        "fluid_settings_setnum":         ([vp, c_char_p, c_double], c_int),
        "fluid_settings_setint":         ([vp, c_char_p, c_int], c_int),
        "fluid_settings_setstr":         ([vp, c_char_p, c_char_p], c_int),
        "new_fluid_synth":               ([vp], vp),
        "delete_fluid_synth":            ([vp], None),
        "fluid_synth_sfload":            ([vp, c_char_p, c_int], c_int),
        "fluid_synth_sfunload":          ([vp, c_int, c_int], c_int),
        "fluid_synth_get_sfont_by_id":   ([vp, c_int], vp),
        "fluid_sfont_iteration_start":   ([vp], None),
        "fluid_sfont_iteration_next":    ([vp], vp),
        "fluid_preset_get_name":         ([vp], c_char_p),
        "fluid_preset_get_banknum":      ([vp], c_int),
        "fluid_preset_get_num":          ([vp], c_int),
        "fluid_synth_program_select":    ([vp, c_int, c_int, c_int, c_int], c_int),
        "fluid_synth_noteon":            ([vp, c_int, c_int, c_int], c_int),
        "fluid_synth_noteoff":           ([vp, c_int, c_int], c_int),
        "fluid_synth_cc":                ([vp, c_int, c_int, c_int], c_int),
        "fluid_synth_pitch_bend":        ([vp, c_int, c_int], c_int),
        "fluid_synth_program_change":    ([vp, c_int, c_int], c_int),
        "fluid_synth_all_notes_off":     ([vp, c_int], c_int),
        "fluid_synth_all_sounds_off":    ([vp, c_int], c_int),
        "fluid_synth_write_float":       ([vp, c_int, vp, c_int, c_int,
                                           vp, c_int, c_int], c_int),
    }
    for name, (args, res) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype  = res


def load_library():
    """Charge libfluidsynth une seule fois ; FluidSynthUnavailable sinon."""
    global _lib
    if _lib is not None:
        return _lib
    names = [ctypes.util.find_library("fluidsynth")] + list(_LIB_NAMES)
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            _declare(lib)
        except (OSError, AttributeError):
            continue
        _lib = lib
        return lib
    raise FluidSynthUnavailable("libfluidsynth introuvable")


def fluidsynth_available():
    try:
        load_library()
        return True
    except FluidSynthUnavailable:
        return False


class FluidSynthEngine(BankEngine):
    """BankEngine sur une instance FluidSynth."""

    FLUID_FAILED = -1
    # synth.gain : 0.2 chez FluidSynth, trop faible à côté de nos pads WAV
    # normalisés (crête 1.0) ; 1.0 (17b1) écrêtait un orchestre GM de dix
    # pistes (crête 2,95) : 0.4 (Phase 7 étape 18d4) ; réglable par la clé
    # "fluidsynth_gain".
    GAIN         = 0.4

    def __init__(self, samplerate=44100, bank_select="gs", gain=GAIN):
        super().__init__(bank_select)
        self._samplerate = samplerate
        self._gain       = gain
        self._lib = load_library()
        self._settings = self._lib.new_fluid_settings()
        if not self._settings:
            raise FluidSynthUnavailable("new_fluid_settings a échoué")
        s = self._settings
        self._lib.fluid_settings_setnum(s, b"synth.sample-rate", float(samplerate))
        self._lib.fluid_settings_setnum(s, b"synth.gain", float(gain))
        self._lib.fluid_settings_setint(s, b"synth.midi-channels", self.NUM_CHANNELS)
        # Réverbération et chorus laissés à 0, comme l'export (§ 17a1, portée).
        self._lib.fluid_settings_setint(s, b"synth.reverb.active", 0)
        self._lib.fluid_settings_setint(s, b"synth.chorus.active", 0)
        self._lib.fluid_settings_setstr(s, b"synth.midi-bank-select",
                                        self.bank_select.encode())
        self._synth = self._lib.new_fluid_synth(s)
        if not self._synth:
            self._lib.delete_fluid_settings(s)
            self._settings = None
            raise FluidSynthUnavailable("new_fluid_synth a échoué")
        self._sfont_ids = [None] * self.NUM_BANK_SLOTS
        self._paths     = [None] * self.NUM_BANK_SLOTS
        self._buf       = np.zeros((0, 2), dtype=np.float32)

    # -- banques ---------------------------------------------------------

    def load(self, slot, path):
        if not 0 <= slot < self.NUM_BANK_SLOTS or not os.path.isfile(path):
            return False
        sfont_id = self._lib.fluid_synth_sfload(self._synth, os.fsencode(path), 0)
        if sfont_id == self.FLUID_FAILED:
            return False
        self.unload(slot)
        self._sfont_ids[slot] = sfont_id
        self._paths[slot]     = path
        return True

    def unload(self, slot):
        sfont_id = self._sfont_ids[slot]
        if sfont_id is None:
            return
        self._lib.fluid_synth_sfunload(self._synth, sfont_id, 1)
        self._sfont_ids[slot] = None
        self._paths[slot]     = None

    def loaded_path(self, slot):
        return self._paths[slot]

    def presets(self, slot):
        sfont_id = self._sfont_ids[slot]
        if sfont_id is None:
            return []
        sfont = self._lib.fluid_synth_get_sfont_by_id(self._synth, sfont_id)
        if not sfont:
            return []
        out = []
        self._lib.fluid_sfont_iteration_start(sfont)
        while True:
            preset = self._lib.fluid_sfont_iteration_next(sfont)
            if not preset:
                break
            name = self._lib.fluid_preset_get_name(preset) or b""
            out.append((self._lib.fluid_preset_get_banknum(preset),
                        self._lib.fluid_preset_get_num(preset),
                        name.decode("latin-1").strip()))
        return sorted(out)

    # -- canaux ----------------------------------------------------------

    def select(self, channel, slot, bank, program):
        sfont_id = self._sfont_ids[slot]
        if sfont_id is None:
            return False
        return self._lib.fluid_synth_program_select(
            self._synth, channel, sfont_id, bank, program) != self.FLUID_FAILED

    def note_on(self, channel, note, velocity):
        self._lib.fluid_synth_noteon(self._synth, channel, note, velocity)

    def note_off(self, channel, note):
        self._lib.fluid_synth_noteoff(self._synth, channel, note)

    def cc(self, channel, num, value):
        self._lib.fluid_synth_cc(self._synth, channel, num, value)

    def pitch_bend(self, channel, value):
        value = max(0, min(16383, value + 8192))
        self._lib.fluid_synth_pitch_bend(self._synth, channel, value)

    def program_change(self, channel, program):
        self._lib.fluid_synth_program_change(self._synth, channel, program)

    def all_notes_off(self):
        self._lib.fluid_synth_all_notes_off(self._synth, -1)

    def all_sounds_off(self):
        self._lib.fluid_synth_all_sounds_off(self._synth, -1)

    def reset_controllers(self):
        for ch in range(self.NUM_CHANNELS):
            self._lib.fluid_synth_cc(self._synth, ch, 121, 0)

    # -- rendu -----------------------------------------------------------

    def render(self, out):
        frames = len(out)
        if self._buf.shape[0] != frames:
            self._buf = np.zeros((frames, 2), dtype=np.float32)
        ptr = self._buf.ctypes.data
        # Entrelacé : gauche à l'indice 0, droite à 1, pas de 2.
        self._lib.fluid_synth_write_float(self._synth, frames, ptr, 0, 2, ptr, 1, 2)
        out += self._buf

    def render_copy(self):
        return FluidSynthEngine(self._samplerate, self.bank_select, self._gain)

    def close(self):
        if self._synth:
            self._lib.delete_fluid_synth(self._synth)
            self._synth = None
        if self._settings:
            self._lib.delete_fluid_settings(self._settings)
            self._settings = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


#=========================================

if __name__ == "__main__":
    # Essai à l'écoute : gamme de piano puis rythme de batterie au canal 10,
    # rendus par le callback de SoundDeviceDriver. Depuis src/ :
    #   python3 -m engines.fluidsynth_engine [fichier.sf2]
    import sys
    import time
    from sound_device_driver import SoundDeviceDriver

    path = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/sounds/sf2/FluidR3_GM.sf2"
    drv = SoundDeviceDriver()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app_config import AppConfig
    cfg = AppConfig(os.path.dirname(sys.path[0]))
    eng = FluidSynthEngine(samplerate=drv.samplerate, gain=cfg.fluidsynth_gain)
    print("Gain :", cfg.fluidsynth_gain)
    print("Chargement", path, "…")
    if not eng.load(0, path):
        sys.exit("Banque refusée")
    print(len(eng.presets(0)), "presets ; premiers :", eng.presets(0)[:3])
    drv.add_render_source(eng.render)
    eng.select(0, 0, 0, 0)                 # piano
    for note in (60, 62, 64, 65, 67, 69, 71, 72):
        eng.note_on(0, note, 100)
        time.sleep(0.3)
        eng.note_off(0, note)
    eng.select(9, 0, 128, 0)               # batterie standard
    for note in (36, 42, 38, 42) * 2:
        eng.note_on(9, note, 110)
        time.sleep(0.25)
    time.sleep(1.0)
    drv.remove_render_source(eng.render)
    eng.close()
    drv.close()
