#python3
"""
    File: tests/test_step_duration.py
    Tests de la durée du pas indépendante de la résolution (Phase 7 étape
    10b1, docs/DESIGN.md § 10a1 D1) : un temps dure 60/bpm quel que soit
    _num_steps ; step_duration recalculé par set_bpm, load_pattern,
    l'enchaînement du song, Redimensionner et Nouveau ; métronome et Note
    Repeat suivent.
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx
from unittest.mock import patch

from pattern import Pattern
from metronome import Metronome
from player.drum_player import DrumPlayer
from ui.mw_patterns import PatternMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _SilentSoundManager:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


def _make_player(bpm=120, num_steps=16):
    pl = DrumPlayer(_SilentSoundManager())
    pl._pattern.new_pattern(1, num_steps)
    pl.set_bpm(bpm)
    pl._wakeup.clear()   # posé par set_bpm : _on_measure_end ne déciderait rien
    return pl


def _beat_secs(pl):
    """Durée d'un temps (num_steps // num_beats pas) en secondes."""
    pat = pl._pattern
    return pl.step_duration * pat._num_steps / pat._num_beats


def _past_measure(pl):
    measure_secs = pl._pattern._num_steps * pl.step_duration
    return time.perf_counter() - 2 * measure_secs, measure_secs


def _make_song_player(specs, looping=False):
    """specs : [(bpm, num_steps), …] — un pattern du song par entrée."""
    bpm0, steps0 = specs[0]
    pl = _make_player(bpm0, steps0)
    patterns = []
    for bpm, steps in specs:
        p = Pattern()
        p.new_pattern(1, steps)
        p._bpm = bpm
        patterns.append(p)
    pl._pattern_list_ref = patterns
    pl._song_sequence    = list(range(len(patterns)))
    pl._song_pos         = 0
    pl._song_mode        = True
    pl._song_looping     = looping
    pl._pattern._looping = False
    pl.playing           = True
    pl._on_song_advance_cb = lambda idx: None
    return pl


# ---------------------------------------------------------------------------
# Formule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("num_steps", [16, 32, 64, 128])
def test_beat_lasts_60_over_bpm_whatever_the_resolution(num_steps):
    pl = _make_player(120, num_steps)
    assert pl.step_duration == pytest.approx(60.0 * 4 / (120 * num_steps))
    assert _beat_secs(pl) == pytest.approx(0.5)
    assert pl.step_duration * num_steps == pytest.approx(2.0)   # mesure 4/4
    print(f"  {num_steps} pas à 120 BPM : temps = 0,5 s, mesure = 2 s : OK")

@pytest.mark.parametrize("bpm", [60, 100, 120, 137])
def test_16_steps_unchanged(bpm):
    pl = _make_player(bpm, 16)
    assert pl.step_duration == pytest.approx(60.0 / bpm / 4)
    print(f"  16 pas à {bpm} BPM : 60/bpm/4 inchangé : OK")

def test_default_player_is_16_steps_100_bpm():
    pl = DrumPlayer(_SilentSoundManager())
    assert pl.step_duration == pytest.approx(0.15)
    print("  DrumPlayer neuf : 0,15 s par pas (100 BPM, 16 pas) : OK")


# ---------------------------------------------------------------------------
# Recalculs
# ---------------------------------------------------------------------------

def test_set_bpm_uses_pattern_resolution():
    pl = _make_player(100, 32)
    pl.set_bpm(150)
    assert _beat_secs(pl) == pytest.approx(60.0 / 150)
    print("  set_bpm sur 32 pas : temps = 60/bpm : OK")

def test_set_bpm_out_of_range_changes_nothing():
    pl = _make_player(100, 32)
    before = pl.step_duration
    pl.set_bpm(0)
    assert pl.step_duration == before
    print("  set_bpm hors plage : durée du pas inchangée : OK")

def test_load_pattern_dense_matrix_updates_step_duration():
    pl = _make_player(120, 16)
    dense = [[[[0] * 64 for _ in range(1)] for _ in range(16)] for _ in range(8)]
    pl.load_pattern(dense)
    assert pl._pattern._num_steps == 64
    assert _beat_secs(pl) == pytest.approx(0.5)
    print("  load_pattern (64 pas) : durée du pas recalculée : OK")

def test_song_advance_same_bpm_other_resolution():
    pl = _make_song_player([(120, 16), (120, 32)])
    ms, secs = _past_measure(pl)
    pl._on_measure_end(ms, secs, 0)
    assert pl._song_pos == 1 and pl._pattern._num_steps == 32
    assert pl.step_duration == pytest.approx(60.0 * 4 / (120 * 32))
    print("  song : BPM égal, 16 → 32 pas : durée du pas recalculée : OK")

def test_song_loop_back_same_bpm_other_resolution():
    pl = _make_song_player([(120, 16), (120, 64)], looping=True)
    pl._song_pos = 1
    pl._pattern.new_pattern(1, 64)
    pl._update_step_duration()
    ms, secs = _past_measure(pl)
    pl._on_measure_end(ms, secs, 0)
    assert pl._song_pos == 0 and pl._pattern._num_steps == 16
    assert pl.step_duration == pytest.approx(60.0 / 120 / 4)
    print("  song en boucle : retour 64 → 16 pas, durée du pas recalculée : OK")

def test_song_advance_new_bpm_and_resolution():
    pl = _make_song_player([(100, 16), (140, 128)])
    ms, secs = _past_measure(pl)
    pl._on_measure_end(ms, secs, 0)
    assert pl.bpm == 140
    assert _beat_secs(pl) == pytest.approx(60.0 / 140)
    print("  song : BPM et résolution changent ensemble : OK")


# ---------------------------------------------------------------------------
# Propriétés du pattern (mw_patterns) : Redimensionner et Nouveau
# ---------------------------------------------------------------------------

class _FakePatternWindow(PatternMixin):
    def __init__(self, num_steps=16):
        self._cur_pattern_idx = 0
        self._pattern_list    = [Pattern() for _ in range(2)]
        self._player          = _make_player(120, num_steps)
        self._pattern_list[0].copy_from(self._player._pattern)
        self.calls            = []

    def _add_undo(self, title):          self.calls.append(('_add_undo', title))
    def _refresh_grid(self):             self.calls.append('_refresh_grid')
    def _refresh_pattern_listbox(self):  self.calls.append('_refresh_pattern_listbox')
    def _show_status(self, msg):         self.calls.append(('_show_status', msg))
    def _play_toggle(self):              pass


def _fake_properties_dialog(action, num_steps, num_bars=1):
    class FakeDlg:
        def __init__(self, *a, **kw): pass
        def ShowModal(self):     return wx.ID_OK
        def get_name(self):      return ""
        def get_start_bar(self): return 0
        def get_num_bars(self):  return num_bars
        def get_num_steps(self): return num_steps
        def get_looping(self):   return True
        def get_action(self):    return action
        def Destroy(self):       pass
    return FakeDlg

def test_resize_live_pattern_updates_step_duration():
    win = _FakePatternWindow(16)
    win._resize_live_pattern(2, 32)
    assert win._player._pattern._num_steps == 32
    assert _beat_secs(win._player) == pytest.approx(0.5)
    print("  _resize_live_pattern (16 → 32 pas) : durée du pas recalculée : OK")

@pytest.mark.parametrize("action", ["Courant", "Nouveau"])
def test_properties_dialog_resolution_change_updates_step_duration(action):
    win = _FakePatternWindow(16)
    with patch("ui.mw_patterns.PatternPropertiesDialog", _fake_properties_dialog(action, 128)):
        win._pattern_properties_dialog()
    assert win._player._pattern._num_steps == 128
    assert win._player.step_duration == pytest.approx(60.0 * 4 / (120 * 128))
    print(f"  propriétés du pattern, action {action} (16 → 128 pas) : durée du pas recalculée : OK")


# ---------------------------------------------------------------------------
# Métronome et Note Repeat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("num_steps", [16, 32, 128])
def test_metronome_clicks_every_60_over_bpm(num_steps):
    pl = _make_player(120, num_steps)
    pl.clicking = True
    events = pl._build_measure_events(0, num_steps - 1, num_steps, 1, 0.0)
    clicks = [e[0] for e in events if e[1] == Metronome.METRO_EVENT]
    assert clicks == pytest.approx([0.0, 0.5, 1.0, 1.5])
    print(f"  métronome sur {num_steps} pas : un clic toutes les 0,5 s à 120 BPM : OK")

@pytest.mark.parametrize("num_steps", [16, 32, 64])
def test_note_repeat_rate_is_a_fraction_of_the_bar(num_steps):
    pl = _make_player(120, num_steps)
    pl._note_repeat_active = True
    pl._nr_quant_idx = Pattern.QUANT_LIST.index("1/16")
    events = pl._build_measure_events(0, num_steps - 1, num_steps, 1, 0.0)
    times = [e[0] for e in events if e[1] == DrumPlayer.NR_EVENT]
    assert len(times) == 16
    assert times == pytest.approx([i * 0.125 for i in range(16)])   # double croche à 120 BPM
    print(f"  Note Repeat 1/16 sur {num_steps} pas : 16 doubles croches par mesure : OK")
