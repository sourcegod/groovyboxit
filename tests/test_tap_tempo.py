#python3
"""
    File: test_tap_tempo.py
    Tests du Tap Tempo (Metronome.tap() / is_fresh_sequence()).
    Date: Thu, 25/06/2026
    Author: Coolbrother
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from metronome import Metronome


@pytest.fixture
def metro():
    return Metronome()


def _tap_seq(metro, interval, count, t0=0.0):
    """Tape `count` fois à `interval` secondes depuis t0, retourne le dernier BPM."""
    bpm = None
    for i in range(count):
        bpm = metro.tap(t=t0 + i * interval)
    return bpm


# ──────────────────────────────────────────────────────────────────────────────
# Cas de base — retourne None avant TAP_MIN_TAPS frappes
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_single_returns_none(metro):
    assert metro.tap(t=0.0) is None


def test_tap_two_taps_returns_none(metro):
    """2 frappes < TAP_MIN_TAPS=4 → pas encore de BPM."""
    metro.tap(t=0.0)
    assert metro.tap(t=0.5) is None


def test_tap_three_taps_returns_none(metro):
    """3 frappes < TAP_MIN_TAPS=4 → pas encore de BPM."""
    assert _tap_seq(metro, 0.5, 3) is None


def test_tap_four_taps_returns_bpm(metro):
    """4 frappes = TAP_MIN_TAPS → premier BPM émis."""
    assert _tap_seq(metro, 0.5, 4) == 120


# ──────────────────────────────────────────────────────────────────────────────
# BPM calculé à partir de 4 frappes
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_120bpm(metro):
    assert _tap_seq(metro, 0.5, 4) == 120


def test_tap_60bpm(metro):
    assert _tap_seq(metro, 1.0, 4) == 60


def test_tap_200bpm(metro):
    assert _tap_seq(metro, 0.3, 4) == 200


# ──────────────────────────────────────────────────────────────────────────────
# Moyenne sur plusieurs frappes
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_average_four_taps(metro):
    """Quatre frappes régulières à 120 BPM → 120."""
    assert _tap_seq(metro, 0.5, 4) == 120


def test_tap_average_smooths_jitter(metro):
    """Légère irrégularité sur 5 frappes : résultat proche de 100 BPM (±3)."""
    times = [0.0, 0.59, 1.21, 1.80, 2.41]   # ~100 BPM avec jitter
    bpm = None
    for t in times:
        bpm = metro.tap(t=t)
    assert bpm is not None
    assert abs(bpm - 100) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# Réinitialisation après timeout
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_reset_after_delay(metro):
    """Silence > TAP_RESET_DELAY → la frappe suivante repart de zéro (None)."""
    _tap_seq(metro, 0.5, 4)   # séquence établie
    result = metro.tap(t=4 * 0.5 + Metronome.TAP_RESET_DELAY + 0.1)
    assert result is None


def test_tap_reset_then_new_sequence(metro):
    """Après reset, une nouvelle séquence de 4 frappes calcule correctement le BPM."""
    _tap_seq(metro, 0.5, 4)
    base = 4 * 0.5 + Metronome.TAP_RESET_DELAY + 0.1
    assert _tap_seq(metro, 0.5, 4, t0=base) == 120


# ──────────────────────────────────────────────────────────────────────────────
# Fenêtre glissante TAP_MAX_TAPS
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_max_taps_window(metro):
    """Après TAP_MAX_TAPS+1 frappes, les plus anciennes sont oubliées."""
    t = 0.0
    for _ in range(12):          # 12 frappes à 120 BPM
        metro.tap(t=t)
        t += 0.5
    # Deux frappes lentes (< reset) tirent le BPM vers le bas
    metro.tap(t=t)
    t += 1.0
    bpm = metro.tap(t=t)
    assert bpm is not None
    assert bpm < 120


# ──────────────────────────────────────────────────────────────────────────────
# Clampage BPM_MIN / BPM_MAX
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_clamp_max(metro):
    """Intervalles très courts → BPM clampé à BPM_MAX."""
    assert _tap_seq(metro, 0.001, 4) == Metronome.BPM_MAX


def test_tap_clamp_min_extreme(metro):
    """Intervalles longs (TAP_RESET_DELAY élargi) → BPM clampé à BPM_MIN."""
    old_delay = Metronome.TAP_RESET_DELAY
    Metronome.TAP_RESET_DELAY = 30.0
    try:
        assert _tap_seq(metro, 5.0, 4) == Metronome.BPM_MIN
    finally:
        Metronome.TAP_RESET_DELAY = old_delay


# ──────────────────────────────────────────────────────────────────────────────
# reset_tap()
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_tap_clears_sequence(metro):
    """reset_tap() efface la séquence : la frappe suivante retourne None."""
    _tap_seq(metro, 0.5, 4)
    metro.reset_tap()
    assert metro.tap(t=3.0) is None


# ──────────────────────────────────────────────────────────────────────────────
# is_fresh_sequence() — logique undo
# ──────────────────────────────────────────────────────────────────────────────

def test_is_fresh_sequence_initially_true(metro):
    assert metro.is_fresh_sequence(t=0.0) is True


def test_is_fresh_sequence_false_after_tap(metro):
    metro.tap(t=0.0)
    assert metro.is_fresh_sequence(t=0.1) is False


def test_is_fresh_sequence_true_after_timeout(metro):
    metro.tap(t=0.0)
    assert metro.is_fresh_sequence(t=Metronome.TAP_RESET_DELAY + 0.1) is True


def test_is_fresh_sequence_after_reset_tap(metro):
    _tap_seq(metro, 0.5, 4)
    metro.reset_tap()
    assert metro.is_fresh_sequence(t=3.0) is True


def test_undo_saved_once_per_sequence(metro):
    """is_fresh_sequence() ne renvoie True qu'à la 1re frappe de chaque séquence."""
    undo_calls = []

    # Séquence 1 : 5 frappes → 1 seul undo
    t = 0.0
    for _ in range(5):
        if metro.is_fresh_sequence(t=t):
            undo_calls.append(1)
        metro.tap(t=t)
        t += 0.5

    assert len(undo_calls) == 1

    # Séquence 2 (après reset) : 4 frappes → 1 undo supplémentaire
    t += Metronome.TAP_RESET_DELAY + 0.1
    for _ in range(4):
        if metro.is_fresh_sequence(t=t):
            undo_calls.append(1)
        metro.tap(t=t)
        t += 0.5

    assert len(undo_calls) == 2
