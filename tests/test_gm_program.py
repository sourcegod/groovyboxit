#python3
"""
    File: tests/test_gm_program.py
    Tests du Program Change par slot (Phase 7 étape 10h3, docs/DESIGN.md
    § 10h2 D11-D13) : guess_gm_program (instruments GM, kits GM2),
    InstrumentSlot.gm_program / set_gm_program (config jamais modifiée en
    place : partagée avec les instantanés d'Undo), program_change au tick 0
    de l'export, et propriétés de piste (aperçu, Annuler, Undo).
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mido
import wx
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pattern import Pattern, TapeEvent, ETYPE_PATCH, ETYPE_PGM
from rack import Rack, InstrumentSlot, InstrumentType
from midi.midi_constants import (GM_PATCH_NAMES, GM2_DRUMKIT_NAMES, GM2_DRUMKITS,
                                 guess_gm_program, _name_words)
from midi.midi_export import build_pattern_midi
from track_router import TrackRouter
from ui.mw_tracks import TrackMixin


# ---------------------------------------------------------------------------
# guess_gm_program
# ---------------------------------------------------------------------------

def test_each_gm_name_maps_to_a_program_with_same_words():
    """Chiffres ignorés : « Electric Piano 1/2 » donnent le premier des deux."""
    for program, name in enumerate(GM_PATCH_NAMES):
        guess = guess_gm_program(name)
        assert _name_words(GM_PATCH_NAMES[guess]) == _name_words(name), name
        assert guess <= program, name
    print("  128 noms GM : déduction sur le nom GM aux mêmes mots : OK")

def test_existing_patch_names():
    cases = {"Piano 1": 0, "Yamaha_Grand_Piano": 0, "Acoustic Guitar 1": 24,
             "DrawbarOrgan": 16, "organ_b3_basic_fast": 16, "Percussive_Organ": 17,
             "Rock_Organ": 18, "Church_Organ": 19, "Reed_Organ": 20}
    for name, program in cases.items():
        assert guess_gm_program(name) == program, name
    print("  patches existants : programmes du plan 10h2 : OK")

def test_digits_ignored_and_unknown_gives_zero():
    assert guess_gm_program("Piano 1") == 0            # pas Electric Piano 1
    assert guess_gm_program("Electric Piano 1") == 4   # nom exact : pas Electric Grand Piano
    assert guess_gm_program("Zzz 42") == 0
    assert guess_gm_program("") == 0 and guess_gm_program(None) == 0
    print("  chiffres ignorés, nom inconnu ou vide → 0 : OK")

def test_drum_kits():
    assert [p for p, _ in GM2_DRUMKITS] == [0, 8, 16, 24, 25, 32, 40, 48, 56]
    assert all(GM2_DRUMKIT_NAMES[p] == n for p, n in GM2_DRUMKITS)
    cases = {"TR-707": 25, "GM (FluidR3)": 0, "Jazz Kit": 32, "Brushes": 0,
             "My 808": 0, "Orchestra": 48, "Electronic Drums": 24}
    for name, program in cases.items():
        assert guess_gm_program(name, drums=True) == program, name
    print("  kits GM2 : 9 kits, déduction (TR-707 → TR-808 Kit) : OK")


# ---------------------------------------------------------------------------
# InstrumentSlot.gm_program / set_gm_program
# ---------------------------------------------------------------------------

def _slot(kind, name, config=None):
    s = InstrumentSlot(1)
    s.type, s.name, s.config = kind, name, dict(config or {})
    return s

def test_slot_program_from_config_or_guess():
    assert _slot(InstrumentType.SYNTH, "Piano 1").gm_program() == 0
    assert _slot(InstrumentType.SYNTH, "Piano 1", {"gm_program": 40}).gm_program() == 40
    assert _slot(InstrumentType.KIT, "TR-707").gm_program() == 25
    assert _slot(InstrumentType.KIT, "TR-707", {"gm_program": 32}).gm_program() == 32
    print("  gm_program : config réglée, sinon déduction (synthé ou kit) : OK")

def test_slot_program_invalid_config_falls_back_to_guess():
    for bad in (128, -1, "16", None, 3.0):
        assert _slot(InstrumentType.SYNTH, "Rock_Organ", {"gm_program": bad}).gm_program() == 18
    print("  gm_program : valeur invalide → déduction : OK")

def test_slot_program_none_for_other_types():
    assert InstrumentSlot(0).gm_program() is None
    for kind in (InstrumentType.LOOP, InstrumentType.AUDIO, InstrumentType.MIDI_FILE):
        assert _slot(kind, "Piano").gm_program() is None
    print("  gm_program : None pour un slot vide ou d'un autre type : OK")

def test_set_gm_program_replaces_config_and_clamps():
    s = _slot(InstrumentType.SYNTH, "Piano 1", {"patch": "p.json"})
    old = s.config
    s.set_gm_program(200)
    assert s.config is not old and old == {"patch": "p.json"}
    assert s.config == {"patch": "p.json", "gm_program": 127}
    s.set_gm_program(-5)
    assert s.gm_program() == 0
    print("  set_gm_program : nouveau dict (ancien intact), borné à 0..127 : OK")

def test_undo_snapshot_not_altered_by_set_gm_program():
    rack = Rack()
    rack.set_slot(2, InstrumentType.SYNTH, "Piano 1", {"patch": "p.json"})
    snapshot = rack.to_dict()                     # comme _capture_state
    rack.get_slot(2).set_gm_program(16)
    assert "gm_program" not in snapshot["slots"][2]["config"]
    rack2 = Rack()
    rack2.from_dict(rack.to_dict())
    assert rack2.get_slot(2).gm_program() == 16
    print("  instantané d'Undo intact ; gm_program sérialisé avec le Rack : OK")


# ---------------------------------------------------------------------------
# Export : program_change au tick 0
# ---------------------------------------------------------------------------

def _export(pattern, programs, channels=None):
    n = pattern._num_tracks
    return build_pattern_midi(
        pattern, name="P", bpm=120,
        track_channels=channels or [Pattern.default_channel(t) for t in range(n)],
        track_is_synth=[True] * n, track_names=[""] * n, kit_pad_notes=list(range(36, 52)),
        synth_grid_notes=list(range(60, 76)), voice_durations=[500] * 16,
        track_programs=programs)

def _pattern_with_notes():
    p = Pattern()
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 60, "vel": 90}, time=0.0))
    p._tape[9].append(TapeEvent(ETYPE_PATCH, dur=200, payload={"note": 38, "vel": 90}, time=4.0))
    return p

def test_program_change_first_at_tick_0_on_track_channel():
    p = _pattern_with_notes()
    programs = [None] * 16
    programs[0], programs[9] = 16, 25
    mid = _export(p, programs)
    for smf, ch, prog in ((mid.tracks[1], 0, 16), (mid.tracks[2], 9, 25)):
        assert smf[1].type == "program_change"
        assert (smf[1].time, smf[1].channel, smf[1].program) == (0, ch, prog)
    print("  program_change : premier message, tick 0, canal de la piste : OK")

def test_none_or_missing_programs_write_nothing():
    p = _pattern_with_notes()
    for programs in (None, [None] * 16):
        mid = _export(p, programs)
        assert not any(m.type == "program_change" for tr in mid.tracks for m in tr)
    print("  track_programs None ou pistes à None : aucun program_change : OK")

def test_captured_pgm_at_tick_0_comes_after_slot_program():
    p = _pattern_with_notes()
    p._tape[0].insert(0, TapeEvent(ETYPE_PGM, payload={"program": 40}, time=0.0))
    programs = [16] + [None] * 15
    mid = _export(p, programs)
    pcs = [m.program for m in mid.tracks[1] if m.type == "program_change"]
    assert pcs == [16, 40]
    print("  ETYPE_PGM capturé au tick 0 : écrit après, donc l'emporte : OK")

def test_program_clamped():
    p = _pattern_with_notes()
    mid = _export(p, [300] + [None] * 15)
    assert mid.tracks[1][1].program == 127
    print("  programme borné à 127 : OK")


# ---------------------------------------------------------------------------
# Propriétés de piste (mw_tracks) : programme du slot
# ---------------------------------------------------------------------------

KIT, PIANO, ORGAN, EMPTY = 0, 1, 3, 5

class _FakeSoundManager:
    def play_sound(self, *a): pass
    def stop_all(self):       pass

class _FakeTrackWindow(TrackMixin):
    def __init__(self, cur_track=2, modified=False):
        rack = Rack()
        rack.set_slot(KIT,   InstrumentType.KIT,   "TR-707",       {"kit": "k.json"})
        rack.set_slot(PIANO, InstrumentType.SYNTH, "Piano 1",      {"patch": "p.json"})
        rack.set_slot(ORGAN, InstrumentType.SYNTH, "DrawbarOrgan", {"patch": "o.json"})
        self._router = TrackRouter(rack, "/fake", _FakeSoundManager(), lambda m: None)
        self._router._ensure_slot_synth = lambda slot_idx: None
        self._router.assign_slot(cur_track, PIANO)
        self._rack             = rack
        self._player           = SimpleNamespace(_cur_track=cur_track)
        self._cur_slot         = PIANO
        self._slot_choice      = MagicMock()
        self._project_modified = modified
        self.calls             = []
    def _refresh_track_list(self):  pass
    def _show_status(self, msg):    self.calls.append(('status', msg))
    def _play_toggle(self):         pass
    def _add_undo(self, title):
        self.calls.append(('_add_undo', title)); self._project_modified = True
    def _pop_last_undo(self):       self.calls.append('_pop_last_undo')
    def _update_title(self):        pass


def _scripted_dialog(result, script, seen):
    """Dialog factice : script(on_change, kw) simule les choix de
    l'utilisateur (aperçu) ; les valeurs finales sont les dernières
    transmises à on_change, ou les initiales."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            seen.update(kw)
            init = (slot, vol, pan, mute, solo, kw["channel"], kw["slot_program"](slot)[1])
            self._v = init
            def on_change(*values):
                self._v = values
                kw["on_change"](*values)
            script(on_change, kw, init)
        def ShowModal(self):    return result
        def get_slot_idx(self): return self._v[0]
        def get_volume(self):   return self._v[1]
        def get_pan(self):      return self._v[2]
        def get_mute(self):     return self._v[3]
        def get_solo(self):     return self._v[4]
        def get_channel(self):  return self._v[5]
        def get_program(self):  return self._v[6]
        def Destroy(self):      pass
    return FakeDlg

def _run(win, result, script):
    seen = {}
    with patch("ui.mw_tracks.TrackPropertiesDialog", _scripted_dialog(result, script, seen)):
        win._track_properties_dialog()
    return seen

def test_slot_program_callback_kinds():
    win = _FakeTrackWindow()
    seen = _run(win, wx.ID_CANCEL, lambda on_change, kw, init: None)
    sp = seen["slot_program"]
    assert sp(PIANO) == ("synth", 0)
    assert sp(ORGAN) == ("synth", 16)
    assert sp(KIT) == ("kit", 25)
    assert sp(EMPTY) == (None, None)
    print("  slot_program : synth / kit / None et programme du slot : OK")

def test_ok_with_new_program_sets_slot_config_and_keeps_undo():
    win = _FakeTrackWindow()
    def script(on_change, kw, init):
        on_change(*init[:6], 4)                     # Electric Piano 1
    _run(win, wx.ID_OK, script)
    assert win._rack.get_slot(PIANO).config == {"patch": "p.json", "gm_program": 4}
    assert '_pop_last_undo' not in win.calls
    print("  Ok avec un autre programme : config du slot réglée, Undo gardé : OK")

def test_cancel_restores_original_config_objects():
    win = _FakeTrackWindow()
    piano_cfg, organ_cfg = win._rack.get_slot(PIANO).config, win._rack.get_slot(ORGAN).config
    def script(on_change, kw, init):
        on_change(*init[:6], 4)                     # programme du piano changé
        on_change(ORGAN, *init[1:6], 19)            # puis orgue choisi, programme changé
    _run(win, wx.ID_CANCEL, script)
    assert win._rack.get_slot(PIANO).config is piano_cfg
    assert win._rack.get_slot(ORGAN).config is organ_cfg
    assert win._router.slot_for_track(2) == PIANO
    assert '_pop_last_undo' in win.calls
    print("  Annuler : config d'origine de chaque slot touché rétablie : OK")

def test_ok_unchanged_program_pops_undo():
    win = _FakeTrackWindow()
    cfg = win._rack.get_slot(PIANO).config
    _run(win, wx.ID_OK, lambda on_change, kw, init: None)
    assert '_pop_last_undo' in win.calls
    assert win._rack.get_slot(PIANO).config is cfg      # rien n'est écrit
    print("  Ok sans changement : Undo retiré, config intacte : OK")

def test_reverting_program_counts_as_unchanged_and_restores():
    win = _FakeTrackWindow()
    cfg = win._rack.get_slot(PIANO).config
    def script(on_change, kw, init):
        on_change(*init[:6], 4)
        on_change(*init)                            # retour au programme d'origine
    _run(win, wx.ID_OK, script)
    assert '_pop_last_undo' in win.calls
    assert win._rack.get_slot(PIANO).config is cfg
    print("  programme changé puis rétabli, Ok : traité comme inchangé : OK")

def test_kit_program_change_on_kit_slot():
    win = _FakeTrackWindow()
    def script(on_change, kw, init):
        on_change(KIT, *init[1:5], 9, 32)           # kit choisi, Jazz Kit
    _run(win, wx.ID_OK, script)
    assert win._rack.get_slot(KIT).gm_program() == 32
    assert win._router.slot_for_track(2) == KIT
    print("  slot kit : kit GM2 choisi enregistré sur le slot : OK")
