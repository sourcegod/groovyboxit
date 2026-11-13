#python3
"""
    File: tests/test_overdub_recording.py
    Overdub comme Sonar (Phase 8 étape 13b1, docs/DESIGN.md § 13a V5) :
    toutes les frappes gardées, même traitement pour toutes les notes
    (grille, Note Repeat, kit, synthé) ; Pattern.add_grid_note ; case de
    grille = vélocité de la dernière note jouée ; saisie à la main,
    effacement et mode Remplacement vident toujours la case entière ;
    sauvegarde des doublons. Métronome rétabli au retour de l'effacement
    pendant un enregistrement (Phase 8 étape 13b2).
    Date: Sat, 14/11/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from player.drum_player import DrumPlayer


class _Snd:
    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def player():
    p = DrumPlayer(_Snd())
    p._quant_in_recording = False
    p._measure_start = None                    # position 0 : même pas pour chaque frappe
    p.start_thread = lambda: None
    p.stop_thread = lambda: None
    p.play_pattern = lambda: setattr(p, "playing", True)
    return p


def _grid(p, track=0, pad=None):
    return [e for e in p._tape[track] if e.etype == ETYPE_GRID
            and (pad is None or e.payload["pad"] == pad)]


# ---------------------------------------------------------------------------
# Pattern : notes de grille
# ---------------------------------------------------------------------------

def test_add_grid_note_appends():
    p = Pattern()
    p.add_grid_note(0, 3, 0, 4, 80)
    p.add_grid_note(0, 3, 0, 4, 110, channel=9, dur=250)
    notes = _grid(p, pad=3)
    assert [(e.payload["vel"], e.channel, e.dur) for e in notes] == [(80, 0, 0), (110, 9, 250)]
    assert notes[0].time == notes[1].time == p._bar_step_to_time(0, 4)


def test_add_grid_note_zero_velocity_does_nothing():
    p = Pattern()
    p.add_grid_note(0, 3, 0, 4, 0)
    p.add_grid_note(0, 3, 0, 4, -5)
    assert _grid(p) == []


def test_add_grid_note_extends_tracks():
    p = Pattern()
    n = len(p._tape)
    p.add_grid_note(n + 2, 0, 0, 0, 100)
    assert len(p._tape) >= n + 3 and len(_grid(p, track=n + 2)) == 1


def test_case_shows_the_last_played_velocity():
    p = Pattern()
    p.add_grid_note(0, 1, 0, 2, 40)
    p.add_grid_note(0, 1, 0, 2, 90)
    p.add_grid_note(0, 1, 0, 2, 70)
    assert p.get_cell(0, 1, 0, 2) == 70
    assert p.grid_row(0, 1, 0)[2] == 70


def test_iter_grid_yields_every_note():
    p = Pattern()
    p.add_grid_note(0, 1, 0, 2, 40)
    p.add_grid_note(0, 1, 0, 2, 90)
    assert [v for t, pad, b, s, v in p.iter_grid(0)] == [40, 90]


def test_set_cell_writes_one_note_on_the_case():
    # saisie à la main : la case entière est réécrite (doublons compris)
    p = Pattern()
    p.add_grid_note(0, 1, 0, 2, 40)
    p.add_grid_note(0, 1, 0, 2, 90)
    p.set_cell(0, 1, 0, 2, 64)
    assert [e.payload["vel"] for e in _grid(p, pad=1)] == [64]


def test_set_cell_zero_empties_the_whole_case():
    p = Pattern()
    p.add_grid_note(0, 1, 0, 2, 40)
    p.add_grid_note(0, 1, 0, 2, 90)
    p.add_grid_note(0, 2, 0, 2, 90)            # autre pad : gardé
    p.set_cell(0, 1, 0, 2, 0)
    assert _grid(p, pad=1) == [] and len(_grid(p, pad=2)) == 1


def test_duplicates_survive_save_and_load():
    p = Pattern()
    p.add_grid_note(0, 1, 0, 2, 40)
    p.add_grid_note(0, 1, 0, 2, 90)
    p._tape[0].append(TapeEvent(ETYPE_KIT, payload={"note": 36, "vel": 50}, time=4))
    p._tape[0].append(TapeEvent(ETYPE_KIT, payload={"note": 36, "vel": 120}, time=4))
    q = Pattern()
    q.from_dict(json.loads(json.dumps(p.to_dict())))
    assert [e.payload["vel"] for e in _grid(q, pad=1)] == [40, 90]
    assert [e.payload["vel"] for e in q._tape[0] if e.etype == ETYPE_KIT] == [50, 120]


# ---------------------------------------------------------------------------
# Enregistrement : toutes les frappes gardées (V5)
# ---------------------------------------------------------------------------

def test_grid_hits_all_kept(player):
    player.record_hit(4, 60)
    player.record_hit(4, 100)
    player.record_hit(4, 30)
    assert [e.payload["vel"] for e in _grid(player._pattern, pad=4)] == [60, 100, 30]
    assert player._pattern.get_cell(0, 4, 0, 0) == 30


def test_grid_hit_keeps_channel(player):
    player.record_hit(4, 60, channel=9)
    assert _grid(player._pattern, pad=4)[0].channel == 9


def test_note_repeat_hits_all_kept(player):
    player._record_nr_hit(2, 4.0)
    player._record_nr_hit(2, 4.0)
    assert len(_grid(player._pattern, pad=2)) == 2


def test_kit_hits_all_kept_with_their_velocity(player):
    # le bug de l'essai de 12b1 : la seconde vélocité était perdue
    player.record_kit_note(38, 70)
    player.record_kit_note(38, 125)
    kit = [e for e in player._pattern._tape[0] if e.etype == ETYPE_KIT]
    assert [e.payload["vel"] for e in kit] == [70, 125]


def test_synth_hits_all_kept(player):
    player.record_patch_note(64, 70, 200)
    player.record_patch_note(64, 110, 300)
    notes = [e for e in player._pattern._tape[0] if e.etype == ETYPE_PATCH]
    assert [(e.payload["vel"], e.dur) for e in notes] == [(70, 200), (110, 300)]


def test_synth_note_off_finishes_the_last_hit(player):
    player.record_patch_note(64, 70, 200)
    player.record_patch_note(64, 110)          # durée mesurée jusqu'au note off
    player.record_patch_note_off(64)
    notes = [e for e in player._pattern._tape[0] if e.etype == ETYPE_PATCH]
    assert notes[0].dur == 200 and notes[1].dur >= 1


def test_every_source_on_the_current_track(player):
    player._cur_track = 2
    player.record_hit(0, 90)
    player.record_kit_note(36, 90)
    player.record_patch_note(60, 90, 100)
    kinds = sorted(e.etype for e in player._pattern._tape[2])
    assert kinds == sorted([ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH])
    assert player._pattern._tape[0] == []


# ---------------------------------------------------------------------------
# Effacement et mode Remplacement : la case entière
# ---------------------------------------------------------------------------

def test_erase_clears_the_whole_case(player):
    player.record_hit(4, 60)
    player.record_hit(4, 100)
    player._clear_offset(4, 0.0)
    assert _grid(player._pattern, pad=4) == []


# ---------------------------------------------------------------------------
# Métronome au retour de l'effacement (13b2)
# ---------------------------------------------------------------------------

def test_click_back_with_recording(player):
    player.click_in_recording = True
    player.record_pattern()
    assert player.recording and player.clicking
    assert player.toggle_erase() is True
    assert not player.recording and not player.clicking
    assert player.toggle_erase() is False
    assert player.recording and player.clicking            # signe de l'enregistrement


def test_click_back_in_replace_recording(player):
    player.click_in_recording = True
    player.start_replace_recording()
    player.toggle_erase()
    player.toggle_erase()
    assert player.recording and player.replace_recording and player.clicking


def test_no_click_stays_without_click(player):
    player.click_in_recording = False
    player.record_pattern()
    player.toggle_erase()
    player.toggle_erase()
    assert player.recording and not player.clicking


def test_click_started_by_the_user_keeps_running(player):
    player.click_in_recording = True
    player.play_click()                                     # avant l'enregistrement
    player.record_pattern()
    player.toggle_erase()
    assert player.clicking                                  # pas coupé : il était déjà là
    player.toggle_erase()
    assert player.recording and player.clicking


def test_erase_without_recording_leaves_click_alone(player):
    player.toggle_erase()
    player.toggle_erase()
    assert not player.recording and not player.clicking


def test_click_flag_reset_by_a_new_erase(player):
    player.click_in_recording = True
    player.record_pattern()
    player.toggle_erase()
    player.toggle_erase()
    player.stop_record()
    player.stop_click()
    player.toggle_erase()                                   # sans enregistrement
    player.toggle_erase()
    assert not player.clicking
