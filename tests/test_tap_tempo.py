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


# ──────────────────────────────────────────────────────────────────────────────
# Cas de base
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_single_returns_none(metro):
    """Une seule frappe ne suffit pas à calculer un BPM."""
    assert metro.tap(t=0.0) is None


def test_tap_two_taps_120bpm(metro):
    """Deux frappes à 0.5 s d'intervalle → 120 BPM."""
    metro.tap(t=0.0)
    assert metro.tap(t=0.5) == 120


def test_tap_two_taps_60bpm(metro):
    metro.tap(t=0.0)
    assert metro.tap(t=1.0) == 60


def test_tap_two_taps_200bpm(metro):
    metro.tap(t=0.0)
    assert metro.tap(t=0.3) == 200


# ──────────────────────────────────────────────────────────────────────────────
# Moyenne sur plusieurs frappes
# ──────────────────────────────────────────────────────────────────────────────

def test_tap_average_four_taps(metro):
    """Quatre frappes régulières à 120 BPM → 120."""
    bpm = None
    for i in range(4):
        bpm = metro.tap(t=i * 0.5)
    assert bpm == 120


def test_tap_average_smooths_jitter(metro):
    """Légère irrégularité : la moyenne reste proche du tempo cible (±3 BPM)."""
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
    metro.tap(t=0.0)
    metro.tap(t=0.5)
    result = metro.tap(t=0.5 + Metronome.TAP_RESET_DELAY + 0.1)
    assert result is None


def test_tap_reset_then_new_sequence(metro):
    """Après reset, une nouvelle séquence calcule correctement le BPM."""
    metro.tap(t=0.0)
    metro.tap(t=0.5)
    base = 0.5 + Metronome.TAP_RESET_DELAY + 0.1
    metro.tap(t=base)
    assert metro.tap(t=base + 0.5) == 120


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
    """Intervalle très court → BPM clampé à BPM_MAX."""
    metro.tap(t=0.0)
    assert metro.tap(t=0.01) == Metronome.BPM_MAX


def test_tap_clamp_min_extreme(metro):
    """Intervalle long (TAP_RESET_DELAY élargi) → BPM clampé à BPM_MIN."""
    old_delay = Metronome.TAP_RESET_DELAY
    Metronome.TAP_RESET_DELAY = 10.0
    try:
        metro.tap(t=0.0)
        assert metro.tap(t=5.0) == Metronome.BPM_MIN
    finally:
        Metronome.TAP_RESET_DELAY = old_delay


# ──────────────────────────────────────────────────────────────────────────────
# reset_tap()
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_tap_clears_sequence(metro):
    """reset_tap() efface la séquence : la frappe suivante retourne None."""
    metro.tap(t=0.0)
    metro.tap(t=0.5)
    metro.reset_tap()
    assert metro.tap(t=1.0) is None


# ──────────────────────────────────────────────────────────────────────────────
# is_fresh_sequence() — logique undo
# ──────────────────────────────────────────────────────────────────────────────

def test_is_fresh_sequence_initially_true(metro):
    """Sans aucune frappe, is_fresh_sequence() est vrai."""
    assert metro.is_fresh_sequence(t=0.0) is True


def test_is_fresh_sequence_false_after_tap(metro):
    """Après une frappe récente, is_fresh_sequence() est faux."""
    metro.tap(t=0.0)
    assert metro.is_fresh_sequence(t=0.1) is False


def test_is_fresh_sequence_true_after_timeout(metro):
    """Après TAP_RESET_DELAY, is_fresh_sequence() redevient vrai."""
    metro.tap(t=0.0)
    assert metro.is_fresh_sequence(t=Metronome.TAP_RESET_DELAY + 0.1) is True


def test_is_fresh_sequence_after_reset_tap(metro):
    """Après reset_tap(), is_fresh_sequence() est vrai."""
    metro.tap(t=0.0)
    metro.tap(t=0.5)
    metro.reset_tap()
    assert metro.is_fresh_sequence(t=0.6) is True


def test_undo_saved_once_per_sequence(metro):
    """Simulation : is_fresh_sequence() ne renvoie True qu'à la 1re frappe d'une séquence."""
    undo_calls = []

    def fake_add_undo():
        if metro.is_fresh_sequence():
            undo_calls.append(1)
        metro.tap(t=len(undo_calls) * 0.5 + sum(
            i * 0.5 for i in range(len(undo_calls))
        ))

    # Séquence 1 : 3 frappes → 1 undo
    t = 0.0
    for i in range(3):
        if metro.is_fresh_sequence(t=t):
            undo_calls.append(1)
        metro.tap(t=t)
        t += 0.5

    assert len(undo_calls) == 1

    # Séquence 2 (après reset) : 2 frappes → 1 undo supplémentaire
    t += Metronome.TAP_RESET_DELAY + 0.1
    for i in range(2):
        if metro.is_fresh_sequence(t=t):
            undo_calls.append(1)
        metro.tap(t=t)
        t += 0.5

    assert len(undo_calls) == 2
