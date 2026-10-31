#python3
"""
    File: tests/test_song_export_ui.py
    Interface de l'export d'un song, Phase 8 étape 2g1 (tests de 2f1,
    docs/DESIGN.md § 2a E9, E15) : nom de fichier proposé, réglages de
    chaque pattern d'après son état figé (_song_midi_params) et cohérence
    avec ceux du pattern courant, _export_song_midi (dialogue simulé : Ok,
    Annuler, extension, erreur, song vide, dossier créé, compte rendu,
    notes de kit non converties), modifications non rangées du pattern
    courant, état propre à chaque pattern dans le fichier, règle
    TrackRouter.track_audible, raccourci Alt+Shift+E de la fenêtre Songs.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import mido
import wx

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from rack import InstrumentType
from song import Song
from synth_engine import scale_midi_notes
from track_router import TrackRouter
from ui.mw_songs import SongMixin
from ui.mw_patterns import PatternMixin
from ui.song_window import SongWindow
from test_key_manager import FakeEvent
from test_midi_export_ui import _ExportWindow, _fake_file_dialog, KIT, PIANO, ORGAN


# ---------------------------------------------------------------------------
# Fenêtre factice : celle des tests de l'export MIDI (vrais ProjectMixin,
# TrackRouter, Rack, VoiceManager) + vrai SongMixin et vrai rangement
# ---------------------------------------------------------------------------

BANK = 5

class _SongWindow(_ExportWindow, SongMixin):
    _flush_pattern_to_store = PatternMixin._flush_pattern_to_store

    def __init__(self, exports_dir, sequence=(0, 1), name=""):
        super().__init__(exports_dir)
        song = Song(0)
        song._name, song._sequence = name, list(sequence)
        self._song_list = [song, Song(1), Song(2)]
        self._song_list[2]._sequence = [1]
        # Pattern 2 du store : « Pont », orgue à 50, 60 BPM, gamme mineure
        b = self._pattern_list[1]
        b._name, b._bpm = "Pont", 60
        b._track_slots[0]   = ORGAN
        b._track_volumes[0] = 50
        b._track_pans[0]    = 30
        b._kb_scale, b._kb_root_midi = "minor", 50
        b._tape[0].append(TapeEvent(ETYPE_PATCH, dur=500, payload={"note": 64, "vel": 90}, time=0))


def _export(win, path, song_idx=0, result=wx.ID_OK, **kw):
    seen = {}
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(result, path, seen)):
        win._export_song_midi(song_idx, **kw)
    return seen


def _abs(track):
    out, now = [], 0
    for m in track:
        now += m.time
        out.append((now, m))
    return out


# ---------------------------------------------------------------------------
# Nom proposé
# ---------------------------------------------------------------------------

def test_song_export_filename(tmp_path):
    win = _SongWindow(str(tmp_path))
    assert win._song_export_filename(0) == "Song_01.mid"
    win._song_list[2]._name = "Mon song: final!"
    assert win._song_export_filename(2) == "Song_03_Mon_song_final.mid"
    assert win._song_export_filename(2, ".wav") == "Song_03_Mon_song_final.wav"
    print("  nom proposé : Song_NN[_nom], nom nettoyé, extension : OK")


# ---------------------------------------------------------------------------
# Réglages de chaque pattern d'après son état figé (E9)
# ---------------------------------------------------------------------------

def test_song_midi_params_come_from_frozen_pattern(tmp_path):
    win = _SongWindow(str(tmp_path))
    seg = win._song_segments(0)[1]                       # « Pont »
    p = win._song_midi_params(seg)
    assert p["name"] == "Pont" and p["bpm"] == 60
    assert p["track_names"][0] == "DrawbarOrgan"         # slot de Pont, pas celui du routeur
    assert p["track_programs"][0] == 18
    assert p["track_is_synth"][0] is True
    assert p["track_volumes"][0] == 50 and p["track_pans"][0] == 30
    assert p["track_channels"] == seg.pattern._track_channels
    assert p["track_channels"] is not seg.pattern._track_channels      # copies
    assert p["synth_grid_notes"] == scale_midi_notes("minor", 50, TrackRouter.KB_NUMPAD_NOTES)
    assert p["kit_pad_notes"] == list(range(44, 60)) and p["kit_gm_map"] == {46: 56}
    print("  réglages du segment : état figé de son pattern, Rack et kit du projet : OK")

def test_song_midi_params_voices_and_audible(tmp_path):
    win = _SongWindow(str(tmp_path))
    b = win._pattern_list[1]
    b._voices[3].update(volume=40, duration_ms=750)
    b._voices[5]["mute"] = True
    b._track_solos[2] = True
    b._track_solos[4] = True
    b._track_mutes[2] = True                             # mute l'emporte sur solo
    p = win._song_midi_params(win._song_segments(0)[1])
    assert p["pad_volumes"][3] == 40 and p["voice_durations"][3] == 750
    assert p["pad_audible"][5] is False and p["pad_audible"].count(False) == 1
    assert [t for t, a in enumerate(p["track_audible"]) if a] == [4]
    print("  réglages du segment : voix des pads, mute et solo des pistes : OK")

def test_song_params_of_current_pattern_match_live_params(tmp_path):
    """Le pattern courant, rangé puis figé, donne les mêmes réglages que
    l'export du pattern seul (nom mis à part)."""
    win = _SongWindow(str(tmp_path))
    win._router.toggle_track_mute(2)
    win._player.voice_manager.set_volume(4, 60)
    live = win._midi_export_params()
    song = win._song_midi_params(win._song_segments(0)[0])
    live.pop("name"), song.pop("name")
    assert song == live
    print("  pattern courant : mêmes réglages que l'export du pattern : OK")

def test_song_midi_params_bank_track_named_after_slot(tmp_path):
    win = _SongWindow(str(tmp_path))
    win._rack.set_slot(BANK, InstrumentType.BANK, "Orchestre", {})
    win._pattern_list[1]._track_slots[3] = BANK
    p = win._song_midi_params(win._song_segments(0)[1])
    assert p["track_is_bank"][3] is True and p["track_names"][3] == "Orchestre"
    assert p["track_programs"][3] is None
    print("  piste en Banque dans un song : nom de son slot : OK")

def test_track_audible_rule():
    mutes, solos = [False, True, False], [False, False, False]
    assert [TrackRouter.track_audible(mutes, solos, t) for t in range(3)] == [True, False, True]
    solos = [False, True, True]
    assert [TrackRouter.track_audible(mutes, solos, t) for t in range(3)] == [False, False, True]
    print("  TrackRouter.track_audible : mute, solo, mute prioritaire : OK")


# ---------------------------------------------------------------------------
# _export_song_midi (E15)
# ---------------------------------------------------------------------------

def test_export_song_writes_file_and_reports(tmp_path):
    win = _SongWindow(str(tmp_path), name="Mon song")
    path = str(tmp_path / "s.mid")
    seen = _export(win, path)
    assert seen["title"] == "Exporter le song en MIDI…"
    assert seen["defaultDir"] == str(tmp_path)
    assert seen["defaultFile"] == "Song_01_Mon_song.mid"
    assert seen["wildcard"] == "Fichiers MIDI (*.mid)|*.mid"
    assert seen["parent"] is win and seen["destroyed"]
    assert win.statuses == ["Song 01 exporté : s.mid (2 patterns)"]
    mid = mido.MidiFile(path)
    assert mid.tracks[0].name == "Mon song"
    assert [m.text for m in mid.tracks[0] if m.type == "marker"] == ["Pat_01", "Pont"]
    print("  export du song : dialogue, fichier, marqueurs, compte rendu : OK")

def test_export_song_singular_and_default_name(tmp_path):
    win = _SongWindow(str(tmp_path))
    path = str(tmp_path / "one.mid")
    _export(win, path, song_idx=2)
    assert win.statuses == ["Song 03 exporté : one.mid (1 pattern)"]
    assert mido.MidiFile(path).tracks[0].name == "Song_03"
    print("  un seul pattern : singulier ; song sans nom : Song_NN : OK")

def test_export_song_parent_and_status_of_song_window(tmp_path):
    win = _SongWindow(str(tmp_path))
    said, parent = [], object()
    seen = _export(win, str(tmp_path / "s.mid"), parent=parent, status=said.append)
    assert seen["parent"] is parent
    assert said == ["Song 01 exporté : s.mid (2 patterns)"] and win.statuses == []
    print("  parent et statut transmis (fenêtre Songs) : OK")

def test_export_song_cancelled(tmp_path):
    win = _SongWindow(str(tmp_path))
    win._player._pattern._tape[3].append(
        TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 60, "vel": 90}, time=0))
    _export(win, str(tmp_path / "s.mid"), result=wx.ID_CANCEL)
    assert win.statuses == ["Export MIDI annulé"]
    assert not os.path.exists(str(tmp_path / "s.mid"))
    assert not win._pattern_list[0]._tape[3]             # rien rangé
    print("  annulé : rien d'écrit, pattern courant pas rangé : OK")

def test_export_song_extension_added(tmp_path):
    win = _SongWindow(str(tmp_path))
    _export(win, str(tmp_path / "sans_ext"))
    assert os.path.exists(str(tmp_path / "sans_ext.mid"))
    assert win.statuses == ["Song 01 exporté : sans_ext.mid (2 patterns)"]
    print("  extension .mid ajoutée : OK")

def test_export_empty_song_refused_without_dialog(tmp_path):
    win = _SongWindow(str(tmp_path), sequence=())
    seen = _export(win, str(tmp_path / "s.mid"))
    assert seen == {}
    assert win.statuses == ["Song vide — ajoutez des patterns dans la fenêtre Songs"]
    print("  song vide : refusé, sans dialogue : OK")

def test_export_song_error_reported(tmp_path):
    win = _SongWindow(str(tmp_path))
    with patch("ui.mw_project.export_song", side_effect=OSError("disque plein")):
        _export(win, str(tmp_path / "s.mid"))
    assert win.statuses == ["ERREUR export MIDI : disque plein"]
    print("  erreur d'écriture : annoncée au statut : OK")

def test_export_song_creates_exports_dir(tmp_path):
    exports = tmp_path / "EXPORTS"
    win = _SongWindow(str(exports))
    _export(win, str(exports / "s.mid"))
    assert exports.is_dir() and (exports / "s.mid").exists()
    print("  dossier EXPORTS créé : OK")

def test_export_song_reports_unmapped_kit_notes(tmp_path):
    win = _SongWindow(str(tmp_path))
    win._pattern_list[1]._track_slots[1] = KIT
    win._pattern_list[1]._tape[1].append(
        TapeEvent(ETYPE_KIT, payload={"note": 46, "vel": 100}, time=0))   # Cowbell → GM 56
    win._pattern_list[1]._tape[1].append(
        TapeEvent(ETYPE_KIT, payload={"note": 47, "vel": 100}, time=4))   # sans équivalent
    _export(win, str(tmp_path / "s.mid"))
    assert win.statuses == ["Song 01 exporté : s.mid (2 patterns) — non converti en GM : Note 47 (47)"]
    print("  notes de kit non converties : au compte rendu : OK")


# ---------------------------------------------------------------------------
# Contenu : pattern courant et état propre à chaque pattern
# ---------------------------------------------------------------------------

def test_export_song_includes_unsaved_edits_of_current_pattern(tmp_path):
    win = _SongWindow(str(tmp_path))
    win._player._pattern._tape[3].append(
        TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 72, "vel": 90}, time=0))
    win._router.assign_slot_by_user(3, PIANO)
    win._player.bpm = 140
    path = str(tmp_path / "s.mid")
    _export(win, path)
    mid = mido.MidiFile(path)
    tempos = [round(mido.tempo2bpm(m.tempo)) for m in mid.tracks[0] if m.type == "set_tempo"]
    assert tempos == [140, 60]
    notes = [m.note for tr in mid.tracks[1:] for m in tr if m.type == "note_on"]
    assert 72 in notes
    assert win._pattern_list[0]._bpm == 140              # rangé dans le store
    print("  modifications non rangées du pattern courant : exportées : OK")

def test_export_song_state_of_each_pattern(tmp_path):
    """Piste 1 : piano à 45 dans le pattern courant, orgue à 50 et pan 30
    dans « Pont » : programme, volume et pan réécrits au début de Pont."""
    win = _SongWindow(str(tmp_path))
    path = str(tmp_path / "s.mid")
    _export(win, path)
    track = mido.MidiFile(path).tracks[1]
    at_pont = [(m.type, getattr(m, "control", None), getattr(m, "program", None),
                getattr(m, "value", None))
               for at, m in _abs(track) if at == 4 * 480 and m.type != "note_on"]
    assert ("program_change", None, 18, None) in at_pont
    assert ("control_change", 7, None, 64) in at_pont            # volume 50
    assert ("control_change", 10, None, 83) in at_pont           # pan 30
    print("  état propre à chaque pattern : réécrit au début de Pont : OK")


# ---------------------------------------------------------------------------
# Raccourci de la fenêtre Songs
# ---------------------------------------------------------------------------

def _song_window_stub():
    calls = []
    parent = SimpleNamespace(
        _export_song_midi=lambda idx, **kw: calls.append((idx, kw)),
        _key_manager=SimpleNamespace(handle_transport=lambda evt: False))
    stub = SimpleNamespace(_parent=parent, _cur_song_idx=4, _set_status=lambda m: None)
    return stub, calls

def test_song_window_alt_shift_e_exports_current_song():
    stub, calls = _song_window_stub()
    SongWindow._on_key(stub, FakeEvent(key=ord('E'), alt=True, shift=True))
    assert calls == [(4, {"parent": stub, "status": stub._set_status})]
    SongWindow._on_key(stub, FakeEvent(key=ord('E'), ukey=ord('e'), alt=True, shift=True))
    assert len(calls) == 2
    print("  fenêtre Songs : Alt+Shift+E exporte le song courant : OK")

def test_song_window_other_e_combinations_do_not_export():
    stub, calls = _song_window_stub()
    for evt in (FakeEvent(key=ord('E'), alt=True),
                FakeEvent(key=ord('E'), shift=True),
                FakeEvent(key=ord('E'), ctrl=True, alt=True, shift=True)):
        SongWindow._on_key(stub, evt)
        assert evt.skipped
    assert calls == []
    print("  fenêtre Songs : Alt+E, Shift+E, Ctrl+Alt+Shift+E n'exportent pas : OK")
