#python3
"""
    File: tests/test_sixteen_tracks.py
    Tests des 16 pistes par pattern (Phase 7 étape 10d1, docs/DESIGN.md
    § 10a1 D2) : valeurs par défaut, migration des presets à 8 pistes
    (format tape_v2 et ancien format curpattern) par Pattern._extend_tracks,
    aller-retour de sérialisation, piste 16 utilisable, sélection jusqu'à la
    piste 16.
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import sys
import os
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_KIT, ETYPE_PATCH
from track_router import TrackRouter
from track_editor import TrackEditor


N = Pattern.DEFAULT_NUM_TRACKS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _old_tape_v2_preset():
    """Preset sauvé avant 10d1 : 8 pistes, réglages non par défaut."""
    tape = [[] for _ in range(8)]
    tape[0].append([0.0, "GRID", 0, 0, {"pad": 2, "vel": 100}])
    tape[7].append([4.0, ETYPE_KIT, 0, 9, {"note": 38, "vel": 90}])
    return {
        "name": "Old", "bpm": 110, "num_bars": 1, "num_steps": 16,
        "num_tracks": 8, "num_pads": 16,
        "track_slots":   [1, 2, 3, 4, 5, 6, 7, 8],
        "track_mutes":   [False, True] + [False] * 6,
        "track_solos":   [False] * 7 + [True],
        "track_volumes": [90, 80, 70, 60, 50, 40, 30, 20],
        "track_pans":    [-10, 10, 0, 0, 0, 0, 0, 25],
        "tape_v2": tape,
    }


def _old_curpattern_preset():
    """Ancien format (curpattern dense, 8 pistes), comme les project_0N.gvp."""
    dense = [[[[0] * 16] for _ in range(16)] for _ in range(8)]
    dense[5][1][0][3] = 100
    return {
        "name": "Older", "bpm": 100, "num_bars": 1, "num_steps": 16,
        "curpattern": dense,
        "kit_tape":   [[6, 0, 8, 36, 100]],
        "patch_tape": [[7, 0, 12, 60, 80, 250]],
        "track_slots": [0, 0, 0, 0, 0, 3, 0, 0],
    }


def _assert_sixteen(p):
    assert p._num_tracks == N
    assert len(p._tape) == N
    assert len(p._tracks) == N
    for name in ("_track_slots", "_track_mutes", "_track_solos",
                 "_track_volumes", "_track_pans"):
        assert len(getattr(p, name)) == N, name


# ---------------------------------------------------------------------------
# Valeurs par défaut
# ---------------------------------------------------------------------------

def test_default_is_sixteen_tracks():
    assert N == 16
    assert TrackRouter.NUM_TRACKS == N
    _assert_sixteen(Pattern())
    print("  nouveau pattern : 16 pistes, router aligné : OK")


# ---------------------------------------------------------------------------
# Migration des presets à 8 pistes
# ---------------------------------------------------------------------------

def test_tape_v2_preset_extended_first_tracks_unchanged():
    d = _old_tape_v2_preset()
    p = Pattern()
    p.from_dict(d)
    _assert_sixteen(p)
    assert p._track_slots[:8]   == d["track_slots"]
    assert p._track_mutes[:8]   == d["track_mutes"]
    assert p._track_solos[:8]   == d["track_solos"]
    assert p._track_volumes[:8] == d["track_volumes"]
    assert p._track_pans[:8]    == d["track_pans"]
    assert p.get_cell(0, 2, 0, 0) == 100
    ev = p._tape[7][0]
    assert (ev.etype, ev.time, ev.channel, ev.payload) == (ETYPE_KIT, 4.0, 9, {"note": 38, "vel": 90})
    print("  preset tape_v2 à 8 pistes : 8 premières pistes inchangées : OK")

def test_added_tracks_are_empty_with_defaults():
    p = Pattern()
    p.from_dict(_old_tape_v2_preset())
    assert all(not p._tape[t] for t in range(8, N))
    assert p._track_slots[8:]   == [0]     * (N - 8)
    assert p._track_mutes[8:]   == [False] * (N - 8)
    assert p._track_solos[8:]   == [False] * (N - 8)
    assert p._track_volumes[8:] == [100]   * (N - 8)
    assert p._track_pans[8:]    == [0]     * (N - 8)
    print("  pistes 9 à 16 ajoutées : vides, réglages par défaut : OK")

def test_curpattern_preset_extended():
    p = Pattern()
    p.from_dict(_old_curpattern_preset())
    _assert_sixteen(p)
    assert p.get_cell(5, 1, 0, 3) == 100
    assert [ev.etype for ev in p._tape[6]] == [ETYPE_KIT]
    assert [ev.etype for ev in p._tape[7]] == [ETYPE_PATCH]
    assert p._track_slots[5] == 3
    assert all(not p._tape[t] for t in range(8, N))
    print("  ancien format curpattern à 8 pistes : complété à 16 : OK")

def test_missing_track_fields_give_sixteen_defaults():
    p = Pattern()
    p.from_dict({"curpattern": [[[[0] * 16] for _ in range(16)] for _ in range(8)]})
    _assert_sixteen(p)
    assert p._track_volumes == [100] * N
    print("  preset sans track_* : 16 valeurs par défaut : OK")

def test_migration_does_not_touch_caller_dict():
    """Les listes peuvent venir du cache d'undo : jamais étendues en place."""
    d = _old_tape_v2_preset()
    before = copy.deepcopy(d)
    p = Pattern()
    p.from_dict(d)
    assert d == before
    p._track_slots[0] = 15
    assert d["track_slots"][0] == 1
    print("  migration : dict de l'appelant intact, listes non partagées : OK")

def test_sixteen_track_preset_unchanged():
    src = Pattern()
    src._track_volumes = list(range(N))
    src._tape[15].append(TapeEvent(ETYPE_KIT, payload={"note": 40, "vel": 70}, time=2.0))
    p = Pattern()
    p.from_dict(src.to_dict())
    _assert_sixteen(p)
    assert p._track_volumes == list(range(N))
    assert len(p._tape[15]) == 1
    print("  preset à 16 pistes : relu tel quel : OK")


# ---------------------------------------------------------------------------
# Aller-retour et piste 16
# ---------------------------------------------------------------------------

def test_migrated_preset_saved_with_sixteen_tracks():
    p = Pattern()
    p.from_dict(_old_tape_v2_preset())
    d = p.to_dict()
    assert d["num_tracks"] == N and len(d["tape_v2"]) == N
    assert len(d["track_slots"]) == N
    q = Pattern()
    q.from_dict(d)
    _assert_sixteen(q)
    assert q._track_slots == p._track_slots
    print("  preset migré : réécrit et relu à 16 pistes : OK")

def test_track_16_grid_and_tape_round_trip():
    p = Pattern()
    p.set_cell(15, 4, 0, 8, 110)
    p._tape[15].append(TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 64, "vel": 80}, time=12.0))
    q = Pattern()
    q.from_dict(p.to_dict())
    assert q.get_cell(15, 4, 0, 8) == 110
    assert [ev.etype for ev in q._tape[15]] == ["GRID", ETYPE_PATCH]
    print("  piste 16 : grille et tape conservées : OK")

def test_router_accepts_track_16_settings():
    router = TrackRouter.__new__(TrackRouter)
    router._track_mutes  = [False] * TrackRouter.NUM_TRACKS
    router._track_solos  = [False] * TrackRouter.NUM_TRACKS
    router._track_solos[15] = True
    assert router._track_is_audible(15) is True
    assert router._track_is_audible(0) is False
    print("  router : solo sur la piste 16 : OK")


# ---------------------------------------------------------------------------
# Sélection multi-pistes jusqu'à la piste 16
# ---------------------------------------------------------------------------

def test_selection_extends_down_to_track_16_and_stops():
    te = TrackEditor()
    assert te.extend_down(14, N) == 15
    assert te.extend_down(15, N) == 15
    te.select_all(N)
    assert te._sel_tracks == set(range(N))
    print("  sélection : Shift+↓ jusqu'à la piste 16, Ctrl+A sur 16 pistes : OK")
