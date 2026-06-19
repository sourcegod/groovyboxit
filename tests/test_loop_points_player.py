#python3
"""
    File: tests/test_loop_points_player.py
    Tests unitaires de la fenêtre de boucle dans DrumPlayer :
    _cur_lp_start, _cur_loop_steps, _loop_remaining, use_window.
    Date: Fri, 20/06/2026
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
    def stop_all(self):            pass
    def play_sound(self, *a):      pass
    def play_metronome(self, *a):  pass
    def play_note(self, *a):       pass


def _make_player(num_bars=1, num_steps=16):
    p = DrumPlayer(_FakeSoundManager())
    p._pattern._num_bars  = num_bars
    p._pattern._num_steps = num_steps
    p._quant_in_recording = False
    return p


def _start_and_wait(p, ms=60):
    """Démarre la lecture et attend que _run_thread initialise la fenêtre."""
    p.play_pattern()
    time.sleep(ms / 1000.0)


def _stop(p):
    p.stop_all()


# ---------------------------------------------------------------------------
# Valeurs initiales avant play
# ---------------------------------------------------------------------------

def test_loop_remaining_initial_zero():
    p = _make_player()
    assert p._loop_remaining == 0
    print("  _loop_remaining initial = 0 : OK")


def test_cur_lp_start_initial_zero():
    p = _make_player()
    assert p._cur_lp_start == 0
    print("  _cur_lp_start initial = 0 : OK")


def test_cur_loop_steps_initial_zero():
    p = _make_player()
    assert p._cur_loop_steps == 0
    print("  _cur_loop_steps initial = 0 : OK")


# ---------------------------------------------------------------------------
# play_pattern — initialise _loop_remaining
# ---------------------------------------------------------------------------

def test_play_pattern_sets_loop_remaining_from_count():
    p = _make_player()
    p._pattern._loop_count = 3
    _start_and_wait(p)
    assert p._loop_remaining == 3
    _stop(p)
    print("  play_pattern : _loop_remaining = loop_count (3) : OK")


def test_play_pattern_loop_count_zero_stays_zero():
    p = _make_player()
    p._pattern._loop_count = 0
    _start_and_wait(p)
    assert p._loop_remaining == 0
    _stop(p)
    print("  play_pattern : _loop_remaining = 0 (infini) : OK")


# ---------------------------------------------------------------------------
# Sans fenêtre (looping=True, pas de points définis)
# ---------------------------------------------------------------------------

def test_no_loop_points_cur_lp_start_zero():
    """Sans points de boucle, la fenêtre couvre tout le pattern."""
    p = _make_player()
    p._pattern._looping    = True
    p._pattern._loop_start = None
    p._pattern._loop_end   = None
    _start_and_wait(p)
    assert p._cur_lp_start == 0
    _stop(p)
    print("  sans points : _cur_lp_start = 0 : OK")


def test_no_loop_points_cur_loop_steps_zero():
    """Fenêtre désactivée → _cur_loop_steps = 0 (pas de restriction)."""
    p = _make_player()
    p._pattern._looping    = True
    p._pattern._loop_start = None
    p._pattern._loop_end   = None
    _start_and_wait(p)
    assert p._cur_loop_steps == 0
    _stop(p)
    print("  sans points : _cur_loop_steps = 0 : OK")


# ---------------------------------------------------------------------------
# Fenêtre désactivée par looping=False
# ---------------------------------------------------------------------------

def test_looping_false_disables_window():
    """Même avec des points définis, looping=False désactive la fenêtre."""
    p = _make_player()
    p._pattern._looping    = False
    p._pattern._loop_start = 4
    p._pattern._loop_end   = 11
    _start_and_wait(p)
    assert p._cur_lp_start   == 0
    assert p._cur_loop_steps == 0
    _stop(p)
    print("  looping=False : fenêtre désactivée (_cur_lp_start=0, steps=0) : OK")


# ---------------------------------------------------------------------------
# Fenêtre active — points de début et fin explicites
# ---------------------------------------------------------------------------

def test_window_active_cur_lp_start():
    p = _make_player()
    p._pattern._looping    = True
    p._pattern._loop_start = 4
    p._pattern._loop_end   = 11
    _start_and_wait(p)
    assert p._cur_lp_start == 4
    _stop(p)
    print("  fenêtre active : _cur_lp_start = 4 : OK")


def test_window_active_cur_loop_steps():
    p = _make_player()
    p._pattern._looping    = True
    p._pattern._loop_start = 4
    p._pattern._loop_end   = 11   # 11 - 4 + 1 = 8 pas
    _start_and_wait(p)
    assert p._cur_loop_steps == 8
    _stop(p)
    print("  fenêtre active : _cur_loop_steps = 8 : OK")


def test_window_single_step():
    """Fenêtre réduite à 1 seul pas."""
    p = _make_player()
    p._pattern._looping    = True
    p._pattern._loop_start = 5
    p._pattern._loop_end   = 5
    _start_and_wait(p)
    assert p._cur_lp_start   == 5
    assert p._cur_loop_steps == 1
    _stop(p)
    print("  fenêtre 1 pas : _cur_lp_start=5, steps=1 : OK")


# ---------------------------------------------------------------------------
# Fenêtre avec un seul point défini
# ---------------------------------------------------------------------------

def test_window_loop_start_only():
    """loop_start défini, loop_end=None → end implicite = dernier pas."""
    p = _make_player(num_bars=1, num_steps=16)   # total = 16 pas
    p._pattern._looping    = True
    p._pattern._loop_start = 8
    p._pattern._loop_end   = None
    _start_and_wait(p)
    assert p._cur_lp_start   == 8
    assert p._cur_loop_steps == 8    # 15 - 8 + 1 = 8
    _stop(p)
    print("  loop_start=8 seul : steps = 8 (jusqu'à la fin) : OK")


def test_window_loop_end_only():
    """loop_end défini, loop_start=None → start implicite = 0."""
    p = _make_player(num_bars=1, num_steps=16)
    p._pattern._looping    = True
    p._pattern._loop_start = None
    p._pattern._loop_end   = 7
    _start_and_wait(p)
    assert p._cur_lp_start   == 0
    assert p._cur_loop_steps == 8    # 7 - 0 + 1 = 8
    _stop(p)
    print("  loop_end=7 seul : _cur_lp_start=0, steps=8 : OK")


# ---------------------------------------------------------------------------
# Bornes — clamping des points hors pattern
# ---------------------------------------------------------------------------

def test_loop_start_clamped_to_zero():
    """loop_start négatif → clampé à 0."""
    p = _make_player(num_bars=1, num_steps=16)
    p._pattern._looping    = True
    p._pattern._loop_start = -5
    p._pattern._loop_end   = 7
    _start_and_wait(p)
    assert p._cur_lp_start == 0
    _stop(p)
    print("  loop_start=-5 clampé à 0 : OK")


def test_loop_end_clamped_to_last_step():
    """loop_end au-delà du pattern → clampé au dernier pas."""
    p = _make_player(num_bars=1, num_steps=16)  # total = 16, dernier = 15
    p._pattern._looping    = True
    p._pattern._loop_start = 0
    p._pattern._loop_end   = 100
    _start_and_wait(p)
    assert p._cur_lp_start   == 0
    assert p._cur_loop_steps == 16   # 15 - 0 + 1 = 16
    _stop(p)
    print("  loop_end=100 clampé au dernier pas : steps=16 : OK")


def test_loop_end_below_loop_start_clamped():
    """loop_end < loop_start → clampé à loop_start (fenêtre = 1 pas)."""
    p = _make_player(num_bars=1, num_steps=16)
    p._pattern._looping    = True
    p._pattern._loop_start = 8
    p._pattern._loop_end   = 3   # incohérent
    _start_and_wait(p)
    assert p._cur_lp_start   == 8
    assert p._cur_loop_steps == 1   # end clampé à start → 8-8+1 = 1
    _stop(p)
    print("  loop_end < loop_start → fenêtre = 1 pas : OK")


# ---------------------------------------------------------------------------
# Pattern multi-mesures
# ---------------------------------------------------------------------------

def test_multibar_window_active():
    """Pattern 4 mesures × 16 pas = 64 pas. Fenêtre [16..47] = 32 pas."""
    p = _make_player(num_bars=4, num_steps=16)
    p._pattern._looping    = True
    p._pattern._loop_start = 16
    p._pattern._loop_end   = 47
    _start_and_wait(p)
    assert p._cur_lp_start   == 16
    assert p._cur_loop_steps == 32
    _stop(p)
    print("  multi-mesures : lp_start=16, steps=32 : OK")


def test_multibar_no_window():
    """Pattern 4 mesures sans fenêtre → _cur_loop_steps = 0."""
    p = _make_player(num_bars=4, num_steps=16)
    p._pattern._looping    = True
    p._pattern._loop_start = None
    p._pattern._loop_end   = None
    _start_and_wait(p)
    assert p._cur_lp_start   == 0
    assert p._cur_loop_steps == 0
    _stop(p)
    print("  multi-mesures sans points : steps = 0 : OK")


def test_multibar_looping_false_disables_window():
    p = _make_player(num_bars=4, num_steps=16)
    p._pattern._looping    = False
    p._pattern._loop_start = 8
    p._pattern._loop_end   = 20
    _start_and_wait(p)
    assert p._cur_lp_start   == 0
    assert p._cur_loop_steps == 0
    _stop(p)
    print("  multi-mesures looping=False : fenêtre désactivée : OK")


# ---------------------------------------------------------------------------
# _loop_remaining — décompte cohérent après play_pattern
# ---------------------------------------------------------------------------

def test_loop_remaining_matches_loop_count_after_play():
    p = _make_player()
    p._pattern._loop_count = 7
    _start_and_wait(p)
    assert p._loop_remaining == 7
    _stop(p)
    print("  _loop_remaining = 7 après play_pattern : OK")


def test_loop_remaining_zero_means_infinite():
    p = _make_player()
    p._pattern._loop_count = 0
    _start_and_wait(p)
    assert p._loop_remaining == 0
    _stop(p)
    print("  _loop_remaining = 0 = répétition infinie : OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            print(f"[RUN] {fn.__name__}")
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"Résultat : {passed} OK, {failed} FAIL")
