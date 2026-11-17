#python3
"""
    File: tests/test_record_mpc.py
    Mode MPC « Remplacer puis Overdub » (Phase 8 étape 16d1, docs/DESIGN.md
    § Phase 8 étape 16a, O8) et Undo de la boucle (correctif 16d2) :
    lecteur (drapeau, passage en Overdub au retour de boucle seulement, pas
    au décompte ni sans boucle, arrêts, Remplacer simple inchangé, piste qui
    rejoue après le premier passage) ; touches (R, Ctrl+R, Shift+R) ;
    prise audio (premier passage qui remplace puis rejoué, suivants
    superposés, Stop pendant ou juste après le premier passage, sans
    boucle) ; L et Shift+L avec Undo (fenêtre principale, transport
    partagé de l'éditeur MIDI et de la fenêtre Songs).
    Date: Tue, 17/11/2026
    Author: Coolbrother
"""
import sys
import os
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

from pattern import TapeEvent, ETYPE_AUDIO, ETYPE_GRID, ETYPE_PATCH, clip_payload
from player.drum_player import DrumPlayer
from ui.key_manager import KeyManager
from test_key_manager import FakeWindow, FakeEvent
from test_audio_loop_recording import LoopWin, TAKE, _old_clip

SR = 44100


class _S:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _player(looping=True):
    p = DrumPlayer(_S())
    p.start_thread = p.stop_thread = lambda: None
    p._pattern._looping = looping
    p.calls = []
    p._on_mpc_overdub_cb = lambda: p.calls.append("mpc_overdub")
    return p


def _measure_end(p):
    """Fin de fenêtre déjà passée : pas d'attente."""
    secs = p._pattern._num_bars * p._pattern._num_steps * p.step_duration
    p._play_stopped = lambda: None
    p._on_count_in_done_cb = None
    return p._on_measure_end(time.perf_counter() - secs - 0.01, secs, 0)


# ---------------------------------------------------------------------------
# Lecteur
# ---------------------------------------------------------------------------

def test_mpc_flag_set_by_replace_recording():
    p = _player()
    p.start_replace_recording(then_overdub=True)
    assert p.recording and p.replace_recording and p._replace_then_overdub
    p2 = _player()
    p2.start_replace_recording()
    assert p2.replace_recording and not p2._replace_then_overdub      # Remplacer simple


@pytest.mark.parametrize("replace, then_overdub, flag", [
    (True, True, True), (True, False, False), (False, True, False)])
def test_mpc_flag_with_count_in(replace, then_overdub, flag):
    p = _player()
    p.record_pattern_with_count_in(2, replace=replace, then_overdub=then_overdub)
    assert p._replace_then_overdub is flag
    p0 = _player()
    p0.record_pattern_with_count_in(0, replace=replace, then_overdub=then_overdub)
    assert p0._replace_then_overdub is flag


@pytest.mark.parametrize("stop", ["stop_record", "stop_pattern", "stop_all"])
def test_stops_reset_the_mpc_flag(stop):
    p = _player()
    p.start_replace_recording(then_overdub=True)
    getattr(p, stop)()
    assert not p._replace_then_overdub and not p.replace_recording


def test_mpc_pass_done_switches_to_overdub_once():
    p = _player()
    p.start_replace_recording(then_overdub=True)
    assert p._mpc_pass_done() is True
    assert p.recording and not p.replace_recording and not p._replace_then_overdub
    assert p.calls == ["mpc_overdub"]
    assert p._mpc_pass_done() is False
    assert p.calls == ["mpc_overdub"]


@pytest.mark.parametrize("case", ["no_loop", "plain_replace", "not_recording"])
def test_mpc_pass_done_does_nothing(case):
    p = _player(looping=case != "no_loop")
    p.start_replace_recording(then_overdub=case != "plain_replace")
    if case == "not_recording":
        p.recording = False
    assert p._mpc_pass_done() is False
    assert p.replace_recording is True and p.calls == []


def test_loop_end_switches_mpc_to_overdub():
    p = _player()
    p.playing = True
    p.start_replace_recording(then_overdub=True)
    _measure_end(p)
    assert p.recording and not p.replace_recording and p.calls == ["mpc_overdub"]


def test_end_of_count_in_is_not_a_loop_pass():
    """Le décompte fini lance le premier passage : toujours en Remplacer."""
    p = _player()
    p.record_pattern_with_count_in(1, replace=True, then_overdub=True)
    _measure_end(p)
    assert p.recording and p.replace_recording and p.calls == []
    _measure_end(p)                                   # fin du premier passage
    assert not p.replace_recording and p.calls == ["mpc_overdub"]


def test_without_loop_mpc_stays_replace():
    p = _player(looping=False)
    p.playing = True
    p.start_replace_recording(then_overdub=True)
    _measure_end(p)
    assert p.replace_recording and p.calls == []


def test_plain_replace_stays_replace_after_the_loop():
    p = _player()
    p.playing = True
    p.start_replace_recording()
    _measure_end(p)
    assert p.replace_recording and p.calls == []


def test_track_plays_again_after_the_first_pass():
    """Premier passage : note de la piste effacée sans être jouée ; ensuite
    (Overdub), une note de la piste joue et reste."""
    p = _player()
    got = []
    p._on_patch_tape_cb = lambda t, n, *a: got.append((t, n))
    p._pattern._tape[0] += [TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 60, "vel": 90},
                                      time=3),
                            TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 64, "vel": 90},
                                      time=5)]
    p.start_replace_recording(then_overdub=True)
    p._dispatch_event(DrumPlayer.PATCH_TAPE_EVENT, (0, 60, 100), 90, 3 * p.step_duration)
    assert got == [] and [e.payload["note"] for e in p._pattern._tape[0]] == [64]
    p._mpc_pass_done()
    p._dispatch_event(DrumPlayer.PATCH_TAPE_EVENT, (0, 64, 100), 90, 5 * p.step_duration)
    assert got == [(0, 64)] and len(p._pattern._tape[0]) == 1


# ---------------------------------------------------------------------------
# Touches
# ---------------------------------------------------------------------------

def _km(mode):
    win = FakeWindow()                   # wx.App de la session (conftest)
    win.record_mode_id = mode
    return win, KeyManager(win)


@pytest.mark.parametrize("mode, then_overdub", [("mpc", True), ("replace", False)])
def test_r_passes_the_mpc_mode(mode, then_overdub):
    win, km = _km(mode)
    km.handle(FakeEvent(key=ord('R')))
    assert win._player.then_overdub is then_overdub


@pytest.mark.parametrize("mode, replace, mpc", [("mpc", True, True), ("replace", True, False),
                                                ("overdub", False, False)])
def test_r_on_an_audio_track_passes_the_mpc_mode(mode, replace, mpc):
    win, km = _km(mode)
    win.audio_track = True
    km.handle(FakeEvent(key=ord('R')))
    assert (win.audio_replace, win.audio_mpc) == (replace, mpc)


@pytest.mark.parametrize("mode, then_overdub", [("mpc", True), ("replace", False),
                                                ("overdub", False)])
def test_ctrl_r_passes_the_mpc_mode(mode, then_overdub):
    win, km = _km(mode)
    km.handle(FakeEvent(key=ord('R'), ctrl=True))
    assert win._player.then_overdub is then_overdub


def test_shift_r_is_a_plain_replace_even_in_mpc_mode():
    win, km = _km("mpc")
    km.handle(FakeEvent(key=ord('R'), shift=True))
    assert 'start_replace_recording' in win._player.calls
    assert win._player.then_overdub is False


# ---------------------------------------------------------------------------
# Prise audio en Mode MPC
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _sync(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))


def test_prepare_mpc_flag(tmp_path):
    win = LoopWin(tmp_path)
    assert win._audio_rec_prepare(replace=True, mpc=True)
    assert win._audio_rec["replace"] and win._audio_rec["mpc"]
    win2 = LoopWin(tmp_path / "b")
    os.makedirs(tmp_path / "b", exist_ok=True)
    win2._audio_rec_prepare(replace=False, mpc=True)
    assert win2._audio_rec["mpc"] is False                 # MPC sans Remplacer : sans objet


@pytest.mark.parametrize("replace, mpc, expected", [
    (True, False, [True, True, True]), (True, True, [True, False, False]),
    (False, False, [False, False, False])])
def test_pass_replaces(replace, mpc, expected):
    rec = {"replace": replace, "mpc": mpc}
    assert [LoopWin._pass_replaces(rec, k) for k in range(3)] == expected


def test_mpc_first_pass_silences_then_is_played(tmp_path):
    win = LoopWin(tmp_path, frames=5 * SR)
    _old_clip(win)                                        # ancien clip sur toute la boucle
    win.open_take(replace=True)
    win._audio_rec["mpc"] = True
    assert win.clips() == []                              # premier passage : la piste se tait
    win._on_audio_wrap(102.0)
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR)]        # deuxième : le premier passage joue
    win._on_audio_wrap(104.0)
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR), (0.0, TAKE, 2 * SR, 2 * SR)]   # superposé


def test_mpc_stop_keeps_every_pass_and_the_first_replaces(tmp_path):
    win = LoopWin(tmp_path, frames=5 * SR)
    _old_clip(win)
    win.open_take(replace=True)
    win._audio_rec["mpc"] = True
    first = win._on_audio_wrap(102.0)
    second = win._on_audio_wrap(104.0)
    win.stop()
    assert win.clips() == [(0.0, TAKE, 0, 2 * SR), (0.0, TAKE, 2 * SR, 2 * SR),
                           (0.0, TAKE, 4 * SR, SR)]
    tape = [e for e in win._player._pattern._tape[2] if e.etype == ETYPE_AUDIO]
    assert tape[0] is first and tape[1] is second          # voix qui sonnent : pas relancées
    assert win.statuses[-1].endswith("3 passages (le premier remplace)")


def test_mpc_first_pass_from_the_middle_keeps_the_head(tmp_path):
    win = LoopWin(tmp_path, frames=3 * SR, t0=101.0)       # captée dès 101 s
    _old_clip(win)
    win.open_take(replace=True, t_start=101.0)             # pas 8
    win._audio_rec["mpc"] = True
    assert win.clips() == [(0.0, "old.wav", 0, SR)]        # tête gardée, fin muette
    win._on_audio_wrap(102.0)
    assert sorted(win.clips()) == [(0.0, "old.wav", 0, SR), (8.0, TAKE, 0, SR)]


def test_mpc_stop_during_the_first_pass(tmp_path):
    """Stop au premier passage : comme Remplacer, la fin non enregistrée revient."""
    win = LoopWin(tmp_path, frames=SR)
    _old_clip(win)
    win.open_take(replace=True)
    win._audio_rec["mpc"] = True
    win.stop()
    assert sorted(win.clips()) == [(0.0, TAKE, 0, SR), (8.0, "old.wav", SR, SR)]


def test_mpc_stop_just_after_the_first_pass_was_posed(tmp_path):
    win = LoopWin(tmp_path, frames=int(1.5 * SR))
    _old_clip(win)
    win.open_take(replace=True)
    win._audio_rec["mpc"] = True
    win._on_audio_wrap(102.0)                              # passage 0 posé en entier…
    win.stop()                                             # … mais Stop à 1,5 s
    assert sorted(win.clips()) == [(0.0, TAKE, 0, int(1.5 * SR)),
                                   (12.0, "old.wav", int(1.5 * SR), SR // 2)]


def test_mpc_without_loop_is_replace(tmp_path):
    win = LoopWin(tmp_path, frames=SR, t0=101.0, looping=False, bars=4)
    _old_clip(win, length=4 * SR)
    win.open_take(replace=True, t_start=101.0, window_end=None)
    win._audio_rec["mpc"] = True
    win.stop()
    assert sorted(win.clips()) == [(0.0, "old.wav", 0, SR), (8.0, TAKE, 0, SR),
                                   (16.0, "old.wav", 2 * SR, 2 * SR)]


# ---------------------------------------------------------------------------
# Undo de la boucle (correctif 16d2)
# ---------------------------------------------------------------------------

def _loop_win(looping=True, loop_end=None):
    win = FakeWindow()
    pat = win._player._pattern
    pat._looping, pat._loop_end = looping, loop_end
    win._pattern_list = [SimpleNamespace(_loop_end=loop_end)]
    win._cur_pattern_idx = 0
    return win, KeyManager(win), pat


@pytest.mark.parametrize("looping, title", [(True, "Boucle: Off"), (False, "Boucle: On")])
def test_l_toggles_the_loop_with_undo_main_window(looping, title):
    win, km, pat = _loop_win(looping)
    km.handle(FakeEvent(key=ord('L')))
    assert pat._looping is (not looping)
    assert ('_add_undo', title) in win.calls
    i = win.calls.index(('_add_undo', title))
    assert ('_show_status', f"Boucle: {'Off' if looping else 'On'}") in win.calls[i:]


@pytest.mark.parametrize("looping, title", [(True, "Boucle: Off"), (False, "Boucle: On")])
def test_l_toggles_the_loop_with_undo_shared_transport(looping, title):
    win, km, pat = _loop_win(looping)
    assert km.handle_transport(FakeEvent(key=ord('L'))) is True
    assert pat._looping is (not looping)
    assert ('_add_undo', title) in win.calls


def test_shift_l_shared_transport_undo_and_store():
    win, km, pat = _loop_win(loop_end=None)
    win._player._current_offset = lambda: 5.0
    km.handle_transport(FakeEvent(key=ord('L'), shift=True))
    assert pat._loop_end == 5 and win._pattern_list[0]._loop_end == 5
    assert ('_add_undo', "Fin de boucle: 1:1:1") in win.calls


def test_shift_l_shared_transport_unchanged_end_no_undo():
    win, km, pat = _loop_win(loop_end=5)
    win._player._current_offset = lambda: 5.0
    km.handle_transport(FakeEvent(key=ord('L'), shift=True))
    assert not any(isinstance(c, tuple) and c[0] == '_add_undo' for c in win.calls)
