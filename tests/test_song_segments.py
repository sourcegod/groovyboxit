#python3
"""
    File: tests/test_song_segments.py
    Segments d'un song pour l'export, Phase 8 étape 2c1 (tests de 2b1,
    docs/DESIGN.md § 2a E5, E6) : début des segments en secondes et en
    noires, tempo, carte de tempo et signature propres à chaque pattern,
    pattern répété, indices hors du store, copie figée de l'état du pattern
    (pistes, voix, gamme) indépendante du store, boucle ignorée, et
    rangement du pattern courant avant l'export (_store_current_pattern,
    _song_segments).
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import Pattern, TapeEvent, ETYPE_GRID
from song import Song, SongSegment, frozen_pattern, song_segments, song_secs
from player.drum_player import DrumPlayer
from ui.mw_songs import SongMixin
from ui.mw_patterns import PatternMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pattern(bpm=100, num_bars=1, beats=4, steps=16, denominator=4, name=""):
    p = Pattern()
    p._bpm, p._num_bars, p._name = bpm, num_bars, name
    p._num_beats, p._num_steps, p._denumerator = beats, steps, denominator
    return p


def make_song(sequence, looping=False):
    s = Song()
    s._sequence, s._looping = list(sequence), looping
    return s


def grid_event(time, pad=0):
    return TapeEvent(ETYPE_GRID, payload={"pad": pad, "vel": 100}, time=time)


# ---------------------------------------------------------------------------
# Début et durée des segments (E5, E6)
# ---------------------------------------------------------------------------

class TestTiming:

    def test_empty_song_gives_no_segment(self):
        assert song_segments(make_song([]), [make_pattern()]) == []
        assert song_secs([]) == 0.0

    def test_single_pattern_duration(self):
        # 2 mesures 4/4 à 120 BPM : 8 noires, 4 s
        seg, = song_segments(make_song([0]), [make_pattern(bpm=120, num_bars=2)])
        assert isinstance(seg, SongSegment)
        assert seg.start_secs == 0.0 and seg.start_quarters == 0.0
        assert seg.secs == pytest.approx(4.0)
        assert seg.quarters == pytest.approx(8.0)
        assert seg.total_steps == 32

    def test_starts_are_cumulative(self):
        a = make_pattern(bpm=120, num_bars=2)                 # 4 s, 8 noires
        b = make_pattern(bpm=60, beats=3, steps=12)           # 3/4 à 60 : 3 s, 3 noires
        segs = song_segments(make_song([0, 1, 0]), [a, b])
        assert [s.start_secs for s in segs] == pytest.approx([0.0, 4.0, 7.0])
        assert [s.start_quarters for s in segs] == pytest.approx([0.0, 8.0, 11.0])
        assert [s.end_secs for s in segs] == pytest.approx([4.0, 7.0, 11.0])
        assert song_secs(segs) == pytest.approx(11.0)

    def test_signature_in_eighths(self):
        # 6/8, 12 pas par mesure à 60 BPM (noire) : 3 noires par mesure, 3 s
        seg, = song_segments(make_song([0]),
                             [make_pattern(bpm=60, beats=6, steps=12, denominator=8)])
        assert seg.quarters == pytest.approx(3.0)
        assert seg.secs == pytest.approx(3.0)

    def test_tempo_map_of_each_pattern(self):
        # 1 mesure 4/4 : 60 BPM puis 120 BPM à la moitié (pas 8)
        # → 2 noires à 1 s + 2 noires à 0,5 s = 3 s
        a = make_pattern(bpm=60)
        a.set_tempo_changes([(8, 120)])
        b = make_pattern(bpm=60)
        segs = song_segments(make_song([0, 1]), [a, b])
        assert segs[0].secs == pytest.approx(3.0)
        assert segs[1].start_secs == pytest.approx(3.0)
        assert segs[1].secs == pytest.approx(4.0)        # son propre tempo, constant
        assert segs[0].tempo_map().bpm_at(10) == 120
        assert segs[1].tempo_map().bpm_at(10) == 60

    def test_bpm_of_each_pattern(self):
        segs = song_segments(make_song([1, 0]), [make_pattern(bpm=90), make_pattern(bpm=140)])
        assert [s.bpm for s in segs] == [140, 90]


# ---------------------------------------------------------------------------
# Séquence : rang, indices, libellés
# ---------------------------------------------------------------------------

class TestSequence:

    def test_positions_and_indices(self):
        pats = [make_pattern(), make_pattern(), make_pattern()]
        segs = song_segments(make_song([2, 0, 2]), pats)
        assert [s.position for s in segs] == [0, 1, 2]
        assert [s.pattern_idx for s in segs] == [2, 0, 2]

    def test_repeated_pattern_gives_independent_copies(self):
        p = make_pattern()
        p._tape[0].append(grid_event(0))
        segs = song_segments(make_song([0, 0]), [p])
        assert segs[0].pattern is not segs[1].pattern
        assert segs[0].pattern is not p
        segs[0].pattern._tape[0].clear()
        assert len(segs[1].pattern._tape[0]) == 1
        assert len(p._tape[0]) == 1

    def test_out_of_range_index_is_skipped(self):
        a, b = make_pattern(bpm=120), make_pattern(bpm=60)
        segs = song_segments(make_song([0, 7, -1, 1]), [a, b])
        assert [s.pattern_idx for s in segs] == [0, 1]
        assert [s.position for s in segs] == [0, 1]
        assert segs[1].start_secs == pytest.approx(2.0)   # pas de trou

    def test_label(self):
        pats = [make_pattern(), make_pattern(name="Refrain")]
        segs = song_segments(make_song([0, 1]), pats)
        assert [s.label for s in segs] == ["Pat_01", "Refrain"]

    def test_song_left_unchanged(self):
        song = make_song([0, 1, 0], looping=True)
        song_segments(song, [make_pattern(), make_pattern()])
        assert song._sequence == [0, 1, 0] and song._looping is True


# ---------------------------------------------------------------------------
# Copie figée de l'état du pattern (E5)
# ---------------------------------------------------------------------------

class TestFrozenPattern:

    def make_rich(self):
        p = make_pattern(bpm=133, num_bars=3, beats=3, steps=12, name="Couplet")
        p.set_tempo_changes([(12, 90)])
        p._tape[1].append(grid_event(5, pad=3))
        p._track_slots[1]    = 4
        p._track_mutes[2]    = True
        p._track_solos[3]    = True
        p._track_volumes[1]  = 70
        p._track_pans[1]     = -40
        p._track_channels[1] = 9
        p._voices[3]["volume"] = 55
        p._voices[3]["mute"]   = True
        p._kb_scale, p._kb_root_midi = "minor", 50
        p._looping, p._loop_start, p._loop_end, p._loop_count = True, 4, 20, 2
        return p

    def test_copies_everything_an_export_needs(self):
        p = self.make_rich()
        f = frozen_pattern(p)
        assert (f._name, f._bpm) == ("Couplet", 133)
        assert (f._num_bars, f._num_beats, f._num_steps, f._denumerator) == (3, 3, 12, 4)
        assert f._tempo_changes == p._tempo_changes
        assert [e.time for e in f._tape[1]] == [5]
        assert f._track_slots == p._track_slots
        assert f._track_mutes == p._track_mutes
        assert f._track_solos == p._track_solos
        assert f._track_volumes == p._track_volumes
        assert f._track_pans == p._track_pans
        assert f._track_channels == p._track_channels
        assert f._voices == p._voices
        assert (f._kb_scale, f._kb_root_midi) == ("minor", 50)

    def test_played_once_whole(self):
        # Comme en song (dp_playback._on_measure_end) : pas de boucle
        f = frozen_pattern(self.make_rich())
        assert f._looping is False
        assert (f._loop_start, f._loop_end, f._loop_count) == (None, None, 0)

    def test_store_untouched(self):
        p = self.make_rich()
        frozen_pattern(p)
        assert p._looping is True and p._loop_start == 4 and p._loop_count == 2

    def test_independent_of_later_store_changes(self):
        p = self.make_rich()
        seg, = song_segments(make_song([0]), [p])
        p._bpm = 60
        p._num_bars = 8
        p._tempo_changes.clear()
        p._tape[1].append(grid_event(7))
        p._track_slots[1] = 0
        p._track_mutes[2] = False
        p._track_solos[3] = False
        p._track_volumes[1] = 100
        p._track_pans[1] = 0
        p._track_channels[1] = 1
        p._voices[3]["volume"] = 100
        p._kb_scale = "major"
        f = seg.pattern
        assert f._bpm == 133 and f._num_bars == 3
        assert f._tempo_changes == [(12, 90)]
        assert len(f._tape[1]) == 1
        assert f._track_slots[1] == 4 and f._track_mutes[2] and f._track_solos[3]
        assert (f._track_volumes[1], f._track_pans[1], f._track_channels[1]) == (70, -40, 9)
        assert f._voices[3]["volume"] == 55
        assert f._kb_scale == "minor"


# ---------------------------------------------------------------------------
# Rangement du pattern courant avant l'export (mw_songs)
# ---------------------------------------------------------------------------

class FakeWindow(SongMixin):
    """Juste ce qu'il faut de MainWindow : vrai DrumPlayer (sans son), état
    du routeur, store des patterns ; vrai rangement (PatternMixin)."""
    _flush_pattern_to_store = PatternMixin._flush_pattern_to_store

    def __init__(self, pattern_list, songs, cur_idx=0):
        self._pattern_list    = pattern_list
        self._song_list       = songs
        self._cur_pattern_idx = cur_idx
        self._player = DrumPlayer(sound_manager=None)
        self._player._pattern.copy_from(pattern_list[cur_idx])
        self._player.bpm = pattern_list[cur_idx]._bpm
        n = Pattern.DEFAULT_NUM_TRACKS
        self._router = SimpleNamespace(
            _track_slots=[0] * n, _track_mutes=[False] * n, _track_solos=[False] * n,
            _track_volumes=[100] * n, _track_pans=[0] * n,
            _track_channels=[Pattern.default_channel(t) for t in range(n)])


class TestStoreCurrentPattern:

    def test_store_current_pattern(self):
        pats = [make_pattern(bpm=100), make_pattern(bpm=80)]
        win = FakeWindow(pats, [make_song([0])], cur_idx=1)
        win._player._pattern._tape[0].append(grid_event(3))
        win._player.bpm = 97
        win._router._track_volumes[2] = 42
        win._player.voice_manager.set_volume(5, 33)
        win._store_current_pattern()
        stored = pats[1]
        assert [e.time for e in stored._tape[0]] == [3]
        assert stored._bpm == 97
        assert stored._track_volumes[2] == 42
        assert stored._voices[5]["volume"] == 33
        assert pats[0]._bpm == 100 and not pats[0]._tape[0]   # autres intacts

    def test_song_segments_sees_unsaved_edits(self):
        # Le pattern courant, édité dans le player, est exporté tel quel
        pats = [make_pattern(bpm=100), make_pattern(bpm=80)]
        win = FakeWindow(pats, [make_song([1, 0, 1])], cur_idx=0)
        win._player._pattern._tape[0].append(grid_event(2))
        win._player.bpm = 150
        win._router._track_pans[0] = 25
        segs = win._song_segments(0)
        assert [s.pattern_idx for s in segs] == [1, 0, 1]
        cur = segs[1].pattern
        assert cur._bpm == 150 and cur._track_pans[0] == 25
        assert [e.time for e in cur._tape[0]] == [2]
        assert segs[0].pattern._bpm == 80
        assert segs[1].start_secs == pytest.approx(60.0 / 80 * 4)

    def test_song_segments_of_empty_song(self):
        win = FakeWindow([make_pattern()], [make_song([])])
        assert win._song_segments(0) == []
