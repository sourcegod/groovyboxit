#python3
"""
    File: tests/test_transport.py
    Tests unitaires du transport : pause_pattern, goto_start, goto_end.
    Date: Sat, 07/06/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSoundManager:
    def stop_all(self):       pass
    def play_sound(self, *a): pass
    def play_metronome(self, *a): pass
    def play_note(self, *a):  pass


def _make_player():
    p = DrumPlayer(_FakeSoundManager())
    p._quant_in_recording = False
    return p


def _make_player_cfg(num_bars=8, num_steps=16, num_beats=4):
    p = _make_player()
    p._pattern._num_bars  = num_bars
    p._pattern._num_steps = num_steps
    p._pattern._num_beats = num_beats
    return p


# ---------------------------------------------------------------------------
# pause_pattern — machine d'états
# ---------------------------------------------------------------------------

def test_pause_when_not_playing_does_nothing():
    p = _make_player()
    p._resume_offset = None
    p.pause_pattern()
    assert p._resume_offset is None
    print("  pause quand arrêté : ne modifie pas _resume_offset : OK")


def test_pause_clears_playing():
    p = _make_player()
    p.playing = True
    p._measure_start = time.perf_counter()
    p.pause_pattern()
    assert p.playing is False
    print("  pause_pattern : playing passe à False : OK")


def test_pause_saves_resume_offset():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p.playing = True
    # Simuler une position au milieu du pattern
    p._measure_start = time.perf_counter() - (total // 2) * p.step_duration
    p.pause_pattern()
    assert p._resume_offset is not None
    assert 0.0 <= p._resume_offset < total
    print(f"  pause_pattern : _resume_offset sauvegardé ({p._resume_offset:.2f} pas) : OK")


def test_pause_resume_offset_near_middle():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    half  = total / 2.0
    p.playing = True
    p._measure_start = time.perf_counter() - half * p.step_duration
    p.pause_pattern()
    # Tolérance de ±1 pas (latence mesure)
    assert abs(p._resume_offset - half) <= 1.0
    print(f"  pause au milieu : offset ≈ {half:.1f}, obtenu {p._resume_offset:.2f} : OK")


def test_pause_clears_count_in():
    p = _make_player()
    p.playing    = True
    p._count_in  = 2
    p._measure_start = time.perf_counter()
    p.pause_pattern()
    assert p._count_in == 0
    print("  pause_pattern : _count_in remis à 0 : OK")


def test_pause_preserves_recording_state():
    p = _make_player()
    p.playing   = True
    p.recording = True
    p._measure_start = time.perf_counter()
    p.pause_pattern()
    assert p.recording is True
    print("  pause_pattern : recording préservé : OK")


# ---------------------------------------------------------------------------
# stop_pattern — efface _resume_offset
# ---------------------------------------------------------------------------

def test_stop_pattern_clears_resume_offset():
    p = _make_player()
    p._resume_offset = 8.0
    p.stop_pattern()
    assert p._resume_offset is None
    print("  stop_pattern : _resume_offset effacé : OK")


def test_stop_pattern_clears_playing():
    p = _make_player()
    p.playing = True
    p._resume_offset = 4.0
    p.stop_pattern()
    assert p.playing is False
    assert p._resume_offset is None
    print("  stop_pattern : playing=False + _resume_offset=None : OK")


# ---------------------------------------------------------------------------
# goto_start
# ---------------------------------------------------------------------------

def test_goto_start_while_stopped_clears_resume_offset():
    p = _make_player()
    p._resume_offset = 8.0
    p.goto_start()
    assert p._resume_offset is None
    print("  goto_start (arrêté) : _resume_offset → None : OK")


def test_goto_start_while_playing_preserves_playing_state():
    p = _make_player()
    p.playing = True
    p.start_thread()
    time.sleep(0.02)
    p.goto_start()
    assert p.playing is True
    assert p._resume_offset is None
    p.stop_all()
    print("  goto_start (lecture) : playing préservé, offset = None : OK")


def test_goto_start_while_clicking_preserves_clicking():
    p = _make_player()
    p.clicking = True
    p.start_thread()
    time.sleep(0.02)
    p.goto_start()
    assert p.clicking is True
    assert p._resume_offset is None
    p.stop_all()
    print("  goto_start (click) : clicking préservé, offset = None : OK")


# ---------------------------------------------------------------------------
# goto_end
# ---------------------------------------------------------------------------

def test_goto_end_while_stopped_sets_resume_offset_to_last():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p.goto_end()
    assert p._resume_offset == float(total - 1)
    print(f"  goto_end (arrêté) : _resume_offset = {total - 1} : OK")


def test_goto_end_while_playing_sets_resume_offset_to_last():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p.playing = True
    p.start_thread()
    time.sleep(0.02)
    p.goto_end()
    assert p.playing is True
    assert p._resume_offset is None   # consommé par le thread redémarré
    p.stop_all()
    print(f"  goto_end (lecture) : playing préservé, offset consommé : OK")


def test_goto_end_reflects_num_bars():
    p = _make_player()
    p._pattern.double_bars()
    total = p._pattern._num_bars * p._pattern._num_steps
    p.goto_end()
    assert p._resume_offset == float(total - 1)
    print(f"  goto_end après double : last_step = {total - 1} : OK")


# ---------------------------------------------------------------------------
# _run_thread — utilise _resume_offset au démarrage
# ---------------------------------------------------------------------------

def test_run_thread_consumes_resume_offset():
    """_run_thread démarre et efface _resume_offset."""
    p = _make_player()
    p._resume_offset = 4.0
    p.clicking = True       # thread tourne pour le click
    p.start_thread()
    time.sleep(0.05)
    assert p._resume_offset is None, "_resume_offset doit être consommé par _run_thread"
    p.stop_all()
    print("  _run_thread : _resume_offset consommé au démarrage : OK")


def test_goto_start_thread_restarts_and_runs():
    """goto_start pendant la lecture : thread redémarre effectivement."""
    p = _make_player()
    p.playing = True
    p.start_thread()
    time.sleep(0.02)
    p.goto_start()
    time.sleep(0.02)
    assert p._play_thread is not None and p._play_thread.is_alive()
    p.stop_all()
    print("  goto_start : thread redémarré et vivant : OK")


# ---------------------------------------------------------------------------
# _current_offset
# ---------------------------------------------------------------------------

def test_current_offset_stopped_no_resume():
    p = _make_player()
    assert p._current_offset() == 0.0
    print("  _current_offset (arrêté, pas de resume) = 0.0 : OK")


def test_current_offset_stopped_with_resume():
    p = _make_player()
    p._resume_offset = 6.0
    assert p._current_offset() == 6.0
    print("  _current_offset (arrêté, resume=6) = 6.0 : OK")


def test_current_offset_from_measure_start():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    half  = total / 2.0
    p.clicking = True   # branch "actif" sans démarrer le thread
    p._measure_start = time.perf_counter() - half * p.step_duration
    off = p._current_offset()
    assert abs(off - half) <= 1.0
    p.clicking = False
    print(f"  _current_offset (actif) ≈ {half:.1f}, obtenu {off:.2f} : OK")


# ---------------------------------------------------------------------------
# move_by_ticks
# ---------------------------------------------------------------------------

def test_move_by_ticks_forward():
    p = _make_player()
    p._resume_offset = 4.0
    p.move_by_ticks(1)
    assert p._resume_offset == 5.0
    print("  move_by_ticks(+1) depuis 4 → 5 : OK")


def test_move_by_ticks_backward():
    p = _make_player()
    p._resume_offset = 4.0
    p.move_by_ticks(-1)
    assert p._resume_offset == 3.0
    print("  move_by_ticks(-1) depuis 4 → 3 : OK")


def test_move_by_ticks_clamp_forward():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p._resume_offset = float(total - 1)
    p.move_by_ticks(1)
    assert p._resume_offset == float(total - 1)
    print(f"  move_by_ticks(+1) depuis {total - 1} → clamp {total - 1} : OK")


def test_move_by_ticks_clamp_backward():
    p = _make_player()
    p._resume_offset = 0.0
    p.move_by_ticks(-1)
    assert p._resume_offset == 0.0
    print("  move_by_ticks(-1) depuis 0 → clamp 0 : OK")


# ---------------------------------------------------------------------------
# move_by_beats
# ---------------------------------------------------------------------------

def test_move_by_beats_forward():
    p = _make_player()
    # défaut: num_steps=16, num_beats=4 → steps_per_beat=4
    p._resume_offset = 0.0
    p.move_by_beats(1)
    assert p._resume_offset == 4.0
    print("  move_by_beats(+1) depuis 0 → 4 : OK")


def test_move_by_beats_backward():
    p = _make_player()
    p._resume_offset = 4.0
    p.move_by_beats(-1)
    assert p._resume_offset == 0.0
    print("  move_by_beats(-1) depuis 4 → 0 : OK")


def test_move_by_beats_clamp_backward():
    p = _make_player()
    p._resume_offset = 0.0
    p.move_by_beats(-1)
    assert p._resume_offset == 0.0
    print("  move_by_beats(-1) depuis 0 → clamp 0 : OK")


# ---------------------------------------------------------------------------
# navigate_bar — style DAW, sans wrap
# ---------------------------------------------------------------------------

def test_navigate_bar_up_from_middle_goes_to_bar_start():
    p = _make_player()
    p._resume_offset = 6.0          # milieu de la mesure 0 (steps 0-15)
    p.navigate_bar(-1)
    assert p._resume_offset == 0.0
    print("  navigate_bar(-1) depuis 6 → début mesure 0 : OK")


def test_navigate_bar_up_from_bar_start_goes_to_previous():
    p = _make_player()
    p._pattern.double_bars()        # 2 mesures, num_steps=16
    p._resume_offset = 16.0         # début exact de la mesure 1
    p.navigate_bar(-1)
    assert p._resume_offset == 0.0
    print("  navigate_bar(-1) depuis début mesure 1 → début mesure 0 : OK")


def test_navigate_bar_up_from_bar0_stays_at_zero():
    p = _make_player()
    p._resume_offset = 0.0
    p.navigate_bar(-1)
    assert p._resume_offset == 0.0
    print("  navigate_bar(-1) depuis 0 → reste à 0 (pas de wrap) : OK")


def test_navigate_bar_down_from_middle_goes_to_next_bar():
    p = _make_player()
    p._pattern.double_bars()        # 2 mesures
    p._resume_offset = 6.0          # milieu de la mesure 0
    p.navigate_bar(+1)
    assert p._resume_offset == 16.0
    print("  navigate_bar(+1) depuis 6 → début mesure 1 : OK")


def test_navigate_bar_down_from_last_bar_goes_to_last_tick():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps   # 16
    p._resume_offset = 0.0          # mesure 0 = seule mesure = dernière mesure
    p.navigate_bar(+1)
    assert p._resume_offset == float(total - 1)
    print(f"  navigate_bar(+1) depuis dernière mesure → dernier tick {total - 1} : OK")


def test_navigate_bar_down_from_last_tick_stays():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p._resume_offset = float(total - 1)
    p.navigate_bar(+1)
    assert p._resume_offset == float(total - 1)
    print(f"  navigate_bar(+1) depuis dernier tick → reste {total - 1} : OK")


def test_navigate_bar_up_from_middle_of_bar1():
    p = _make_player()
    p._pattern.double_bars()        # mesure 0: 0-15, mesure 1: 16-31
    p._resume_offset = 20.0         # milieu de la mesure 1
    p.navigate_bar(-1)
    assert p._resume_offset == 16.0
    print("  navigate_bar(-1) depuis 20 → début mesure 1 (pas mesure 0) : OK")


def test_navigate_bar_up_twice_quick_skips_bar_start():
    """Deux PageUp rapides : le second passe directement à la mesure précédente."""
    p = _make_player()
    p._pattern.double_bars()        # mesures 0 et 1
    p._resume_offset = 20.0         # milieu mesure 1
    p.navigate_bar(-1)              # → début mesure 1 (16.0)
    # Simuler un 2e appui immédiat : _last_nav_time vient d'être mis à jour,
    # et le playhead a légèrement avancé (simulé par un offset légèrement > 16)
    p._resume_offset = 16.05        # playhead avancé de 0.05 pas en < 100 ms
    p.navigate_bar(-1)              # fenêtre active → doit aller en mesure 0
    assert p._resume_offset == 0.0
    print("  2e PageUp rapide depuis 16.05 → mesure 0 grâce à la fenêtre : OK")


def test_navigate_bar_up_after_window_goes_to_bar_start():
    """PageUp hors fenêtre (> 100 ms) : revient au début de la mesure courante."""
    p = _make_player()
    p._pattern.double_bars()
    p._resume_offset = 16.05        # légèrement dans la mesure 1
    p._last_nav_time = time.perf_counter() - 0.2   # fenêtre expirée
    p.navigate_bar(-1)              # hors fenêtre → doit aller au début mesure 1
    assert p._resume_offset == 16.0
    print("  PageUp hors fenêtre depuis 16.05 → début mesure 1 : OK")


# ---------------------------------------------------------------------------
# move_by_seconds
# ---------------------------------------------------------------------------

def test_move_by_seconds_forward():
    p = _make_player()
    # 100 BPM → step_duration = 0.15 s → 1 s ≈ 6.667 pas
    p._resume_offset = 0.0
    p.move_by_seconds(1)
    expected = 1.0 / p.step_duration
    assert abs(p._resume_offset - expected) < 0.01
    print(f"  move_by_seconds(+1) depuis 0 → {p._resume_offset:.3f} pas : OK")


def test_move_by_seconds_backward():
    p = _make_player()
    p._resume_offset = 10.0
    p.move_by_seconds(-1)
    expected = 10.0 - 1.0 / p.step_duration
    assert abs(p._resume_offset - expected) < 0.01
    print(f"  move_by_seconds(-1) depuis 10 → {p._resume_offset:.3f} pas : OK")


def test_move_by_seconds_clamp_backward():
    p = _make_player()
    p._resume_offset = 0.0
    p.move_by_seconds(-1)
    assert p._resume_offset == 0.0
    print("  move_by_seconds(-1) depuis 0 → clamp 0 : OK")


def test_move_by_seconds_clamp_forward():
    p = _make_player()
    total = p._pattern._num_bars * p._pattern._num_steps
    p._resume_offset = float(total - 1)
    p.move_by_seconds(1)
    assert p._resume_offset == float(total - 1)
    print(f"  move_by_seconds(+1) depuis {total - 1} → clamp {total - 1} : OK")


# ---------------------------------------------------------------------------
# move_by_bars
# ---------------------------------------------------------------------------

def test_move_by_bars_forward_two_bars():
    p = _make_player()
    p._pattern.double_bars()           # num_bars=2, total=32
    p._resume_offset = 0.0
    p.move_by_bars(1)
    assert p._resume_offset == float(p._pattern._num_steps)
    print(f"  move_by_bars(+1) depuis 0 → {p._pattern._num_steps} : OK")


def test_move_by_bars_backward_two_bars():
    p = _make_player()
    p._pattern.double_bars()
    p._resume_offset = float(p._pattern._num_steps)
    p.move_by_bars(-1)
    assert p._resume_offset == 0.0
    print("  move_by_bars(-1) depuis mesure 2 → 0 : OK")


def test_move_by_bars_wrap_backward():
    p = _make_player()
    p._pattern.double_bars()           # total=32, num_steps=16
    total = p._pattern._num_bars * p._pattern._num_steps
    p._resume_offset = 0.0
    p.move_by_bars(-1)
    assert p._resume_offset == float(total - p._pattern._num_steps)
    print(f"  move_by_bars(-1) depuis 0 → {total - p._pattern._num_steps} (wrap) : OK")


def test_move_by_bars_single_bar_wraps():
    p = _make_player()                 # num_bars=1, total=16
    p._resume_offset = 0.0
    p.move_by_bars(1)
    assert p._resume_offset == 0.0    # 16 % 16 = 0
    print("  move_by_bars(+1) sur 1 seule mesure → wrap 0 : OK")


# ---------------------------------------------------------------------------
# position_str
# ---------------------------------------------------------------------------

def test_position_str_start():
    p = _make_player_cfg(num_bars=8, num_steps=16, num_beats=4)
    p._resume_offset = 0.0
    s = p.position_str()
    assert s == "1:1:1 / 8:4:4", f"attendu '1:1:1 / 8:4:4', obtenu '{s}'"
    print(f"  position_str début : {s} OK")


def test_position_str_end():
    p = _make_player_cfg(num_bars=8, num_steps=16, num_beats=4)
    p._resume_offset = float(8 * 16 - 1)   # 127
    s = p.position_str()
    assert s == "8:4:4 / 8:4:4", f"attendu '8:4:4 / 8:4:4', obtenu '{s}'"
    print(f"  position_str fin : {s} OK")


def test_position_str_middle():
    # Step 20 : bar=1 (0-based) → 2, rem=4, beat=1 (0-based) → 2, tick=0 → 1
    p = _make_player_cfg(num_bars=8, num_steps=16, num_beats=4)
    p._resume_offset = 20.0
    s = p.position_str()
    assert s == "2:2:1 / 8:4:4", f"attendu '2:2:1 / 8:4:4', obtenu '{s}'"
    print(f"  position_str milieu (step 20) : {s} OK")


def test_position_str_one_bar():
    # 1 bar, 4 steps, 4 beats → steps_per_beat=1 → total "1:4:1"
    p = _make_player_cfg(num_bars=1, num_steps=4, num_beats=4)
    p._resume_offset = 3.0   # last step
    s = p.position_str()
    assert s == "1:4:1 / 1:4:1", f"attendu '1:4:1 / 1:4:1', obtenu '{s}'"
    print(f"  position_str 1 bar 4 steps : {s} OK")


def test_position_str_playing():
    p = _make_player_cfg(num_bars=2, num_steps=16, num_beats=4)
    p.playing = True
    step_dur = p.step_duration
    # _measure_start tel que le playhead soit à step 16 (début bar 2)
    p._measure_start = time.perf_counter() - 16 * step_dur
    s = p.position_str()
    # bar 2 (1-based), beat 1, tick 1 → "2:1:1 / 2:4:4"
    assert s.startswith("2:1:"), f"attendu début '2:1:', obtenu '{s}'"
    print(f"  position_str en lecture (step~16) : {s} OK")
    p.playing = False


# ---------------------------------------------------------------------------
# etype_discriminates (régression Phase 4)
# ---------------------------------------------------------------------------

def test_etype_discriminates_k_vs_p():
    from pattern import TapeEvent
    ev_k = TapeEvent("K", 36, 100, 0, 0)
    ev_p = TapeEvent("P", 36, 100, 200, 0)
    assert ev_k.etype == "K"
    assert ev_p.etype == "P"
    assert ev_k != ev_p
    print("  TapeEvent etype K≠P pour même note : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = fail = 0
    for fn in tests:
        try:
            print(f"\n[{fn.__name__}]")
            fn()
            ok += 1
        except Exception as exc:
            print(f"  ECHEC : {exc}")
            fail += 1
    print(f"\n{'='*50}")
    print(f"Résultat : {ok} OK, {fail} ECHEC sur {ok + fail} tests")
