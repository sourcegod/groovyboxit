#python3
"""
    File: tests/test_fluidsynth_engine.py
    Moteur de banque (Phase 7 étape 17c1, docs/DESIGN.md § 17a1 D1, D2, D4,
    D6, D14, D17) : BankEngine (numéro de banque GS/MMA, contrat), et
    FluidSynthEngine sur FluidR3_GM.sf2, la soundfont par défaut de l'appli
    (TimGM6mb.sf2 si FluidR3 est introuvable) : chargement dans les
    4 emplacements, presets lus dans la soundfont, choix de l'instrument
    d'un canal, rendu ajouté au mixage, note off, batterie au canal 10,
    coupures, gain, fermeture. Les tests FluidSynth sont sautés si
    libfluidsynth ou les deux soundfonts sont absentes.
    Branchement dans MainWindow : création du moteur, branchement au
    pilote, absence de libfluidsynth.
    Date: Mon, 26/10/2026
    Author: Coolbrother
"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest

import ui.main_window as main_window
from engines.bank_engine import BankEngine
from engines.fluidsynth_engine import (FluidSynthEngine, FluidSynthUnavailable,
                                       fluidsynth_available)
from ui.main_window import MainWindow

# Soundfont par défaut de l'appli (D7), sinon la petite TimGM6mb.
_SF2_CANDIDATES = ("/usr/share/sounds/sf2/FluidR3_GM.sf2",
                   "/usr/share/sounds/sf2/TimGM6mb.sf2")
SF2 = next((p for p in _SF2_CANDIDATES if os.path.isfile(p)), None)

needs_fluidsynth = pytest.mark.skipif(
    not (fluidsynth_available() and SF2),
    reason="libfluidsynth absente, ou ni FluidR3_GM.sf2 ni TimGM6mb.sf2")


# Seuil « du son sort », indépendant de la soundfont et du preset (sous
# FluidR3, certains presets attaquent vers 0,003 au premier bloc).
AUDIBLE = 1e-4


def _block(frames=512, fill=0.0):
    return np.full((frames, 2), fill, dtype=np.float32)


def _render(eng, frames=512):
    out = _block(frames)
    eng.render(out)
    return out


def _peak(eng, frames=512):
    return float(np.abs(_render(eng, frames)).max())


@pytest.fixture
def eng():
    e = FluidSynthEngine()
    assert e.load(0, SF2)
    yield e
    e.close()


# ---------------------------------------------------------------------------
# BankEngine : numéro de banque (D17) et contrat
# ---------------------------------------------------------------------------

def test_bank_number_gs_uses_msb_only():
    b = BankEngine("gs")
    assert b.bank_number(8, 0) == 8
    assert b.bank_number(8, 5) == 8              # LSB sans effet en mode GS
    assert b.bank_number(128 + 3, 0) == 3        # 7 bits


def test_bank_number_mma_combines_msb_and_lsb():
    b = BankEngine("mma")
    assert b.bank_number(1, 2) == 130
    assert b.bank_number(0, 8) == 8


def test_unknown_bank_select_mode_falls_back_to_gs():
    assert BankEngine("xg").bank_select == "gs"


def test_constants():
    assert (BankEngine.NUM_BANK_SLOTS, BankEngine.NUM_CHANNELS) == (4, 16)


@pytest.mark.parametrize("call", [
    lambda b: b.load(0, "x.sf2"), lambda b: b.presets(0),
    lambda b: b.select(0, 0, 0, 0), lambda b: b.note_on(0, 60, 100),
    lambda b: b.render(_block()), lambda b: b.close(),
])
def test_base_class_methods_are_abstract(call):
    with pytest.raises(NotImplementedError):
        call(BankEngine())


# ---------------------------------------------------------------------------
# FluidSynthEngine : banques et emplacements (D4, D6)
# ---------------------------------------------------------------------------

@needs_fluidsynth
def test_load_records_path(eng):
    assert eng.loaded_path(0) == SF2
    assert eng.loaded_path(1) is None


@needs_fluidsynth
@pytest.mark.parametrize("slot", [-1, 4])
def test_load_refuses_slot_out_of_range(slot):
    e = FluidSynthEngine()
    assert e.load(slot, SF2) is False
    e.close()


@needs_fluidsynth
def test_load_refuses_missing_file_and_keeps_previous(eng, tmp_path):
    assert eng.load(0, str(tmp_path / "absente.sf2")) is False
    assert eng.loaded_path(0) == SF2


@needs_fluidsynth
def test_load_refuses_sfz_and_keeps_previous(eng, tmp_path):
    (tmp_path / "kick.sfz").write_text("<region> sample=kick.wav key=36\n")
    assert eng.load(0, str(tmp_path / "kick.sfz")) is False      # D1 : pas de SFZ
    assert eng.loaded_path(0) == SF2


@needs_fluidsynth
def test_four_slots_load_independently(eng):
    for slot in (1, 2, 3):
        assert eng.load(slot, SF2)
    assert [eng.loaded_path(s) for s in range(4)] == [SF2] * 4
    assert all(eng.presets(s) for s in range(4))


@needs_fluidsynth
def test_reload_replaces_slot_content(eng):
    first = eng._sfont_ids[0]
    assert eng.load(0, SF2)
    assert eng._sfont_ids[0] != first
    assert eng.presets(0)


@needs_fluidsynth
def test_unload_empties_slot(eng):
    eng.unload(0)
    assert eng.loaded_path(0) is None
    assert eng.presets(0) == []
    assert eng.select(0, 0, 0, 0) is False
    eng.unload(0)                                # déjà vide : sans erreur


@needs_fluidsynth
def test_presets_read_from_soundfont_sorted(eng):
    presets = eng.presets(0)
    assert presets == sorted(presets)
    assert all(isinstance(b, int) and isinstance(p, int) and isinstance(n, str)
               for b, p, n in presets)
    names = {(b, p): n for b, p, n in presets}
    assert names.get((0, 0))                     # piano GM, nommé par la soundfont
    assert names.get((128, 0)) == "Standard"     # batterie


@needs_fluidsynth
def test_presets_of_empty_slot():
    e = FluidSynthEngine()
    assert e.presets(2) == []
    e.close()


# ---------------------------------------------------------------------------
# Canaux et rendu (D2, D14)
# ---------------------------------------------------------------------------

@needs_fluidsynth
def test_select_existing_missing_and_empty_slot(eng):
    assert eng.select(0, 0, 0, 0) is True
    assert eng.select(0, 0, 99, 127) is False    # preset absent
    assert eng.select(0, 2, 0, 0) is False       # emplacement vide


@needs_fluidsynth
def test_render_is_silent_without_notes(eng):
    assert _peak(eng) == 0.0


@needs_fluidsynth
def test_note_on_renders_sound(eng):
    eng.select(0, 0, 0, 0)
    eng.note_on(0, 60, 100)
    assert _peak(eng) > AUDIBLE


@needs_fluidsynth
def test_render_adds_to_existing_mix(eng):
    out = _block(fill=0.25)                      # autres voix déjà mixées
    eng.render(out)                              # silence : rien ne change
    assert np.all(out == 0.25)
    eng.select(0, 0, 0, 0)
    eng.note_on(0, 60, 100)
    out = _block(fill=0.25)
    eng.render(out)
    assert np.abs(out - 0.25).max() > AUDIBLE


@needs_fluidsynth
def test_note_off_releases_to_silence(eng):
    eng.select(0, 0, 0, 0)
    eng.note_on(0, 60, 100)
    for _ in range(4):
        _render(eng)
    eng.note_off(0, 60)
    levels = [_peak(eng) for _ in range(200)]    # ≈ 2,3 s à 44,1 kHz
    assert levels[0] > AUDIBLE
    assert levels[-1] == 0.0


@needs_fluidsynth
def test_drums_on_channel_10(eng):
    assert eng.select(9, 0, 128, 0)
    eng.note_on(9, 36, 110)                      # grosse caisse
    assert _peak(eng) > AUDIBLE


@needs_fluidsynth
def test_channels_are_independent(eng):
    eng.select(0, 0, 0, 0)
    eng.select(1, 0, 0, 40)
    eng.note_on(1, 60, 100)
    _render(eng)
    eng.all_notes_off()
    eng.note_on(0, 60, 100)
    assert _peak(eng) > AUDIBLE


@needs_fluidsynth
def test_channel_can_use_another_bank_slot(eng):
    assert eng.load(1, SF2)
    assert eng.select(3, 1, 0, 19)
    eng.note_on(3, 60, 100)
    assert _peak(eng) > AUDIBLE


@needs_fluidsynth
def test_all_sounds_off_cuts_immediately(eng):
    eng.select(0, 0, 0, 0)
    eng.note_on(0, 60, 100)
    _render(eng)
    eng.all_sounds_off()
    assert _peak(eng) == 0.0


@needs_fluidsynth
def test_controllers_and_bend_accept_full_ranges(eng):
    eng.select(0, 0, 0, 0)
    for value in (-8192, 0, 8191, -20000, 20000):     # bornés à 0..16383
        eng.pitch_bend(0, value)
    eng.cc(0, 7, 127)
    eng.cc(0, 0, 8)
    eng.cc(0, 32, 0)
    eng.program_change(0, 40)
    eng.reset_controllers()
    eng.note_on(0, 60, 100)
    assert _peak(eng) > AUDIBLE


@needs_fluidsynth
def test_render_follows_block_size(eng):
    for frames in (256, 512, 1024, 256):
        assert _render(eng, frames).shape == (frames, 2)


@needs_fluidsynth
def test_gain_zero_is_silent():
    e = FluidSynthEngine(gain=0.0)
    assert e.load(0, SF2)
    e.select(0, 0, 0, 0)
    e.note_on(0, 60, 100)
    assert _peak(e) < 1e-6                       # résidu interne de FluidSynth ≈ 1e-10
    e.close()


@needs_fluidsynth
def test_default_gain_is_1():
    assert FluidSynthEngine.GAIN == 1.0


@needs_fluidsynth
@pytest.mark.parametrize("mode", ["gs", "mma"])
def test_bank_select_mode_is_kept(mode):
    e = FluidSynthEngine(bank_select=mode)
    assert e.bank_select == mode
    e.close()


@needs_fluidsynth
def test_close_twice_is_harmless(eng):
    eng.close()
    eng.close()
    assert eng._synth is None and eng._settings is None


# ---------------------------------------------------------------------------
# MainWindow : création et branchement du moteur (17b1)
# ---------------------------------------------------------------------------

class _FakeDriver:
    samplerate = 48000
    def __init__(self):
        self.sources = []
    def add_render_source(self, fn):
        self.sources.append(fn)


class _FakeEngine:
    def __init__(self, samplerate, bank_select, gain):
        self.args = (samplerate, bank_select, gain)
    def render(self, out):
        pass


def _cfg(**kw):
    base = dict(midi_bank_select="gs", fluidsynth_gain=1.0)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_init_bank_engine_plugs_render_into_driver(monkeypatch):
    monkeypatch.setattr(main_window, "FluidSynthEngine", _FakeEngine)
    win = types.SimpleNamespace(_audio_driver=_FakeDriver())
    MainWindow._init_bank_engine(win, _cfg(midi_bank_select="mma", fluidsynth_gain=0.5))
    assert win._bank_engine.args == (48000, "mma", 0.5)
    assert win._audio_driver.sources == [win._bank_engine.render]


def test_init_bank_engine_without_libfluidsynth(monkeypatch):
    def unavailable(**kw):
        raise FluidSynthUnavailable("absente")
    monkeypatch.setattr(main_window, "FluidSynthEngine", unavailable)
    win = types.SimpleNamespace(_audio_driver=_FakeDriver())
    MainWindow._init_bank_engine(win, _cfg())
    assert win._bank_engine is None
    assert win._audio_driver.sources == []
