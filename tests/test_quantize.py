#python3
"""
    File: tests/test_quantize.py
    Tests unitaires de la quantize en Lecture (apply_quant_row,
    apply_quant_to_pattern) et en Enregistrement (record_hit avec
    _quant_in_recording).
    Date: Tue, 19/05/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch
from drum_player import DrumPlayer


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeSoundManager:
    def play_sound(self, pad_idx, vol, pan): pass
    def stop_all(self):                      pass
    def play_metronome(self, beat):          pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T0 = 1000.0   # temps de référence arbitraire pour record_hit

def make_player():
    player = DrumPlayer(sound_manager=FakeSoundManager())
    player.bpm           = 120
    player.step_duration = 60.0 / 120 / 4   # 0.125 s/pas
    return player

def active_steps(player, pad_idx, bar=0):
    return [
        i for i, v in enumerate(
            player._pattern._curpattern[0][pad_idx][bar]
        )
        if v
    ]

def hit_at(player, float_offset):
    """Simule un hit à `float_offset` pas après measure_start."""
    t = T0 + float_offset * player.step_duration
    with patch("time.perf_counter", return_value=t):
        return player.record_hit(0)


# ---------------------------------------------------------------------------
# Quantize en Lecture — apply_quant_row
# ---------------------------------------------------------------------------

def test_quant_row_1_4_places_steps_on_quarter_grid():
    player = make_player()
    player.apply_quant_row(DrumPlayer.QUANT_STEPS.index(4), 0)
    assert active_steps(player, 0) == [0, 4, 8, 12]
    print("  quant_row 1/4 → [0,4,8,12] : OK")

def test_quant_row_1_8_places_steps_on_eighth_grid():
    player = make_player()
    player.apply_quant_row(DrumPlayer.QUANT_STEPS.index(8), 0)
    assert active_steps(player, 0) == [0, 2, 4, 6, 8, 10, 12, 14]
    print("  quant_row 1/8 → [0,2,4,…14] : OK")

def test_quant_row_1_16_fills_every_step():
    player = make_player()
    player.apply_quant_row(DrumPlayer.QUANT_STEPS.index(16), 0)
    assert active_steps(player, 0) == list(range(16))
    print("  quant_row 1/16 → tous les pas : OK")

def test_quant_row_clears_previous_content():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[1] = pat[3] = pat[7] = True
    player.apply_quant_row(DrumPlayer.QUANT_STEPS.index(4), 0)
    assert active_steps(player, 0) == [0, 4, 8, 12]
    print("  quant_row efface le contenu précédent : OK")

def test_quant_row_updates_float_offsets():
    player = make_player()
    player.apply_quant_row(DrumPlayer.QUANT_STEPS.index(4), 0)
    assert player.float_offsets[0] == [0.0, 4.0, 8.0, 12.0]
    print("  quant_row met à jour float_offsets : OK")


# ---------------------------------------------------------------------------
# Quantize en Lecture — apply_quant_to_pattern
# ---------------------------------------------------------------------------

def test_quant_pattern_snaps_2_6_to_1_4_grid():
    # grille 1/4 (0,4,8,12) : le plus proche de 2.6 est 4
    player = make_player()
    player.float_offsets[0] = [2.6]
    player.apply_quant_to_pattern(DrumPlayer.QUANT_STEPS.index(4))
    steps = active_steps(player, 0)
    assert 4 in steps and 2 not in steps and 3 not in steps
    print("  quant_pattern 1/4 : 2.6 → step 4 : OK")

def test_quant_pattern_snaps_3_4_to_1_8_grid():
    # grille 1/8 (0,2,4,…) : le plus proche de 3.4 est 4
    player = make_player()
    player.float_offsets[0] = [3.4]
    player.apply_quant_to_pattern(DrumPlayer.QUANT_STEPS.index(8))
    steps = active_steps(player, 0)
    assert 4 in steps and 3 not in steps
    print("  quant_pattern 1/8 : 3.4 → step 4 : OK")

def test_quant_pattern_clears_old_steps_before_snap():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[3] = True
    player.float_offsets[0] = [3.4]
    player.apply_quant_to_pattern(DrumPlayer.QUANT_STEPS.index(8))
    assert not pat[3]
    print("  quant_pattern efface les pas existants avant snap : OK")

def test_quant_pattern_no_offsets_leaves_pad_empty():
    player = make_player()
    player.apply_quant_to_pattern(DrumPlayer.QUANT_STEPS.index(4))
    assert active_steps(player, 0) == []
    print("  quant_pattern sans offsets → pad vide : OK")

def test_quant_pattern_none_idx_does_not_modify_pattern():
    player = make_player()
    pat = player._pattern._curpattern[0][0][0]
    pat[3] = True
    player.quant_idx = -1
    player.apply_quant_to_pattern()
    assert pat[3]
    print("  quant_pattern quant_idx=-1 (None) → pattern inchangé : OK")

def test_quant_pattern_snap_in_second_bar():
    # offset 18.4 sur grille 1/4 → point 20 → bar 1, step 4
    player = make_player()
    player._pattern.new_pattern(num_bars=2, num_steps=16)
    player._all_offsets = [
        [[] for _ in range(player._pattern._num_pads)]
        for _ in range(player._pattern._num_tracks)
    ]
    player.float_offsets[0] = [18.4]
    player.apply_quant_to_pattern(DrumPlayer.QUANT_STEPS.index(4))
    bar1 = player._pattern._curpattern[0][0][1]
    assert bar1[4]
    print("  quant_pattern multi-bar : 18.4 → bar 1, step 4 : OK")


# ---------------------------------------------------------------------------
# Quantize en Enregistrement — record_hit
# ---------------------------------------------------------------------------

def test_rec_quant_disabled_rounds_to_nearest_step():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = False
    _, step = hit_at(player, 2.6)
    assert step == 3   # round(2.6) = 3
    print("  rec quant OFF : 2.6 → step 3 (round simple) : OK")

def test_rec_quant_1_4_snaps_2_6_to_step_4():
    # quant_size=4 ; round(2.6/4)*4 = 1*4 = 4
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(4)
    _, step = hit_at(player, 2.6)
    assert step == 4
    print("  rec quant 1/4 : 2.6 → step 4 : OK")

def test_rec_quant_1_8_snaps_3_4_to_step_4():
    # quant_size=2 ; round(3.4/2)*2 = 2*2 = 4
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(8)
    _, step = hit_at(player, 3.4)
    assert step == 4
    print("  rec quant 1/8 : 3.4 → step 4 : OK")

def test_rec_quant_1_16_equals_no_quant():
    # quant_size=1 → identique à round()
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(16)
    _, step = hit_at(player, 2.6)
    assert step == 3
    print("  rec quant 1/16 = round() : 2.6 → step 3 : OK")

def test_rec_quant_none_idx_disables_snap():
    # quant_idx=-1 → même si flag actif, pas de snap
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = -1
    _, step = hit_at(player, 2.6)
    assert step == 3
    print("  rec quant quant_idx=-1 (None) → pas de snap : OK")

def test_rec_quant_writes_snapped_step_in_pattern():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → step 4
    assert player._pattern._curpattern[0][0][0][4]
    print("  rec quant écrit step 4 dans le pattern : OK")

def test_rec_quant_does_not_write_raw_step():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → 4, pas 3
    assert not player._pattern._curpattern[0][0][0][3]
    print("  rec quant n'écrit pas le step brut (3) : OK")

def test_rec_quant_stores_snapped_float_offset():
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(4)
    hit_at(player, 2.6)   # snap → 4.0
    assert 4.0 in player.float_offsets[0]
    print("  rec quant stocke l'offset snappé (4.0) : OK")

def test_rec_quant_wraps_at_end_of_measure():
    # offset 15.6 ; 1/4 : round(15.6/4)*4 = 4*4 = 16 → %16 = 0
    player = make_player()
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(4)
    bar, step = hit_at(player, 15.6)
    assert step == 0 and bar == 0
    print("  rec quant wrap fin de mesure : 15.6 → step 0 bar 0 : OK")

def test_rec_quant_multi_bar_correct_bar_and_step():
    # offset 17.4 → 1/8 → 18.0 → bar 1, step 2
    player = make_player()
    player._pattern.new_pattern(num_bars=2, num_steps=16)
    player._all_offsets = [
        [[] for _ in range(player._pattern._num_pads)]
        for _ in range(player._pattern._num_tracks)
    ]
    player._measure_start    = T0
    player._quant_in_recording = True
    player.quant_idx = DrumPlayer.QUANT_STEPS.index(8)
    bar, step = hit_at(player, 17.4)
    assert bar == 1 and step == 2
    print("  rec quant multi-bar : 17.4 → bar 1, step 2 : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_quantize ===")
    # Quantize en Lecture — apply_quant_row
    test_quant_row_1_4_places_steps_on_quarter_grid()
    test_quant_row_1_8_places_steps_on_eighth_grid()
    test_quant_row_1_16_fills_every_step()
    test_quant_row_clears_previous_content()
    test_quant_row_updates_float_offsets()
    # Quantize en Lecture — apply_quant_to_pattern
    test_quant_pattern_snaps_2_6_to_1_4_grid()
    test_quant_pattern_snaps_3_4_to_1_8_grid()
    test_quant_pattern_clears_old_steps_before_snap()
    test_quant_pattern_no_offsets_leaves_pad_empty()
    test_quant_pattern_none_idx_does_not_modify_pattern()
    test_quant_pattern_snap_in_second_bar()
    # Quantize en Enregistrement — record_hit
    test_rec_quant_disabled_rounds_to_nearest_step()
    test_rec_quant_1_4_snaps_2_6_to_step_4()
    test_rec_quant_1_8_snaps_3_4_to_step_4()
    test_rec_quant_1_16_equals_no_quant()
    test_rec_quant_none_idx_disables_snap()
    test_rec_quant_writes_snapped_step_in_pattern()
    test_rec_quant_does_not_write_raw_step()
    test_rec_quant_stores_snapped_float_offset()
    test_rec_quant_wraps_at_end_of_measure()
    test_rec_quant_multi_bar_correct_bar_and_step()
    print("Tous les tests : OK")
