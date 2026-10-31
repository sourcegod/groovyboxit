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
    Export audio du song, Phase 8 étape 2k1 (tests de 2j1, § 2a E2, E11,
    E15) : parcours fichier puis paramètres, nom, fin proposée d'après la
    boucle du song et non gardée pour les patterns, libellé « Song +
    résonance », render_song et ses paramètres, annulations, song vide,
    pause, export déjà en cours, compte rendu, raccourci Alt+Shift+W, rendu
    réel jusqu'au fichier.
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
import numpy as np
import pytest
import soundfile as sf
import wx

from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from rack import InstrumentType
from song import Song
from synth_engine import scale_midi_notes
from track_router import TrackRouter
from ui.mw_songs import SongMixin
from ui.mw_patterns import PatternMixin
from ui.song_window import SongWindow
import audio_export
import ui.mw_project as mwp
from ui.dialogs import AudioExportDialog
from sound_device_driver import Mixer
from sound_manager import SoundManager
from rack import Rack
from test_key_manager import FakeEvent
from test_midi_export_ui import _ExportWindow, _fake_file_dialog, KIT, PIANO, ORGAN
from test_audio_export_ui import Dialogs, _wait


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
        _export_song_audio=lambda idx, **kw: calls.append(("W", idx, kw)),
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



# ---------------------------------------------------------------------------
# Export audio du song (Phase 8 étape 2k1, docs/DESIGN.md § 2a E2, E11, E15)
# ---------------------------------------------------------------------------

SR = 44100

class _AudioSongWindow(_SongWindow):
    """_SongWindow avec ce que l'export audio lit du player."""

    def __init__(self, exports_dir, playing=False, **kw):
        super().__init__(exports_dir, **kw)
        p = self._player
        p.playing, p.paused, p.pan, p.volume = playing, 0, -20, 80
        def pause():
            p.paused += 1
            p.playing = False
        p.pause_pattern = pause
        self._audio_export_opts = (1, 0, False, 2, -14)


@pytest.fixture
def audio(monkeypatch):
    """Dialogues factices, wx.CallAfter synchrone, render_song et write_wav
    simulés (paramètres notés) ; render_pattern ne doit pas servir."""
    rendered, written = [], []

    def install(dialogs):
        monkeypatch.setattr(mwp.wx, "FileDialog", dialogs.FileDlg)
        monkeypatch.setattr(mwp, "AudioExportDialog", dialogs.OptsDlg)
        return dialogs

    def fake_render(**kw):
        rendered.append(kw)
        kw["progress"](0.5)
        return audio_export.RenderResult(np.zeros((SR, 2), np.float32), SR, SR,
                                         SR // 2, False, 1)

    def fake_write(path, res, subtype, normalize, measure, level):
        written.append((path, subtype, normalize, measure, level))
        return 0.0, 0.0

    def no_pattern(**kw):
        raise AssertionError("render_pattern appelé pour un song")

    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(audio_export, "render_song", fake_render)
    monkeypatch.setattr(audio_export, "render_pattern", no_pattern)
    monkeypatch.setattr(audio_export, "write_wav", fake_write)
    return SimpleNamespace(install=install, rendered=rendered, written=written)


def test_song_audio_file_then_options(tmp_path, audio):
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path / "EXPORTS"), name="Mon song")
    win._export_song_audio(0)
    _wait(win)
    assert d.order == ["fichier", "paramètres"]
    assert d.file_kw["title"] == "Exporter le song en WAV…"
    assert d.file_kw["defaultFile"] == "Song_01_Mon_song.wav"
    assert d.file_kw["defaultDir"] == str(tmp_path / "EXPORTS")
    assert d.file_kw["wildcard"] == "Fichiers WAV (*.wav)|*.wav"
    assert d.file_kw["parent"] is win
    assert (tmp_path / "EXPORTS").is_dir()
    assert d.opts_args[2]["unit"] == "Song"
    print("  export audio du song : fichier puis paramètres, nom, libellé Song : OK")

@pytest.mark.parametrize("looping, proposed", [(True, 0), (False, 1)])
def test_song_audio_end_proposed_from_song_loop(tmp_path, audio, looping, proposed):
    """E2 : boucle exacte proposée si le song boucle, sinon song + résonance,
    quelle que soit la fin retenue pour les patterns."""
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path))
    win._song_list[0]._looping = looping
    win._audio_export_opts = (1 - proposed, 2, True, 0, -9)
    win._export_song_audio(0)
    _wait(win)
    assert d.opts_args[1] == (proposed, 2, True, 0, -9)
    print("  fin proposée d'après la boucle du song, autres options gardées : OK")

def test_song_audio_end_not_kept_for_patterns(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "s.wav"), opts=(0, 2, True, 1, -10)))
    win = _AudioSongWindow(str(tmp_path))
    win._export_song_audio(0)
    _wait(win)
    assert win._audio_export_opts == (1, 2, True, 1, -10)
    assert audio.written == [(str(tmp_path / "s.wav"), "FLOAT", True, "rms", -10)]
    print("  fin du song non gardée pour les patterns ; format et niveau gardés : OK")

def test_song_audio_renders_song_segments(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "s.wav"), opts=(0, 0, False, 2, -14)))
    win = _AudioSongWindow(str(tmp_path), sequence=(1, 0, 1))
    win._export_song_audio(0)
    _wait(win)
    kw, = audio.rendered
    assert [seg.pattern_idx for seg in kw["segments"]] == [1, 0, 1]
    assert kw["end"] == audio_export.END_LOOP
    assert kw["router"] is win._router and kw["voice_manager"] is win._player.voice_manager
    assert (kw["master_pan"], kw["master_volume"]) == (-20, 80)
    assert "pattern" not in kw and "window" not in kw
    print("  render_song : segments du song, fin, routeur, voix, pan et volume globaux : OK")

def test_song_audio_includes_unsaved_edits(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path))
    win._player._pattern._tape[4].append(
        TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 100}, time=2))
    win._player.bpm = 133
    win._export_song_audio(0)
    _wait(win)
    cur = audio.rendered[0]["segments"][0].pattern
    assert cur._bpm == 133 and [e.time for e in cur._tape[4]] == [2]
    print("  modifications non rangées du pattern courant : rendues : OK")

def test_song_audio_report(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "s.wav"), opts=(1, 0, False, 2, -14)))
    win = _AudioSongWindow(str(tmp_path))
    win._export_song_audio(0)
    _wait(win)
    assert win.statuses[:2] == ["Export audio : 0 %", "Export audio : 50 %"]
    assert win.statuses[-1] == ("Song 01 exporté en WAV : s.wav (2 patterns) — 1,00 s, "
                                "song + résonance (0,50 s), 16 bits")
    print("  compte rendu : song, nombre de patterns, song + résonance : OK")

def test_song_audio_parent_and_status_of_song_window(tmp_path, audio):
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path), sequence=(1,))
    said, parent = [], object()
    win._export_song_audio(0, parent=parent, status=said.append)
    _wait(win)
    assert d.file_kw["parent"] is parent and d.opts_args[0] is parent
    assert said[-1].startswith("Song 01 exporté en WAV : s.wav (1 pattern)")
    assert win.statuses == []
    print("  parent et statut de la fenêtre Songs ; « 1 pattern » : OK")

@pytest.mark.parametrize("file_ok, opts_ok", [(False, True), (True, False)])
def test_song_audio_cancelled(tmp_path, audio, file_ok, opts_ok):
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav"), file_ok=file_ok, opts_ok=opts_ok))
    win = _AudioSongWindow(str(tmp_path))
    win._player._pattern._tape[4].append(
        TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 100}, time=2))
    win._export_song_audio(0)
    _wait(win)
    assert win.statuses == ["Export audio annulé"]
    assert audio.rendered == [] and not win._pattern_list[0]._tape[4]   # rien rangé
    assert win._audio_export_opts == (1, 0, False, 2, -14)
    print("  annulé (fichier ou paramètres) : rien rendu, rien rangé : OK")

def test_song_audio_empty_song_refused(tmp_path, audio):
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path), playing=True, sequence=())
    win._export_song_audio(0)
    assert d.order == [] and audio.rendered == []
    assert win.statuses == ["Song vide — ajoutez des patterns dans la fenêtre Songs"]
    assert win._player.paused == 0
    print("  song vide : refusé sans dialogue ni pause : OK")

def test_song_audio_pauses_playback(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path), playing=True)
    win._export_song_audio(0)
    _wait(win)
    assert win._player.paused == 1 and len(audio.rendered) == 1
    print("  lecture en pause pendant l'export : OK")

def test_song_audio_already_running(tmp_path, audio):
    d = audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    win = _AudioSongWindow(str(tmp_path))
    win._audio_export_thread = SimpleNamespace(is_alive=lambda: True)
    win._export_song_audio(0)
    assert d.order == [] and win.statuses == ["Export audio déjà en cours"]
    print("  export déjà en cours : refusé : OK")

def test_song_audio_extension_added(tmp_path, audio):
    audio.install(Dialogs(path=str(tmp_path / "sans_ext")))
    win = _AudioSongWindow(str(tmp_path))
    win._export_song_audio(0)
    _wait(win)
    assert audio.written[0][0] == str(tmp_path / "sans_ext.wav")
    print("  extension .wav ajoutée : OK")

def test_song_audio_render_error_reported(tmp_path, audio, monkeypatch):
    audio.install(Dialogs(path=str(tmp_path / "s.wav")))
    def boom(**kw):
        raise RuntimeError("panne")
    monkeypatch.setattr(audio_export, "render_song", boom)
    win = _AudioSongWindow(str(tmp_path))
    win._export_song_audio(0)
    _wait(win)
    assert win.statuses[-1] == "ERREUR export audio : panne"
    print("  erreur de rendu : annoncée : OK")

def test_audio_report_unit_and_detail_defaults(tmp_path):
    """Sans unit ni detail : le compte rendu d'un pattern, inchangé."""
    win = _AudioSongWindow(str(tmp_path))
    res = audio_export.RenderResult(np.zeros((SR, 2), np.float32), SR, SR, 0, False, 1)
    assert win._audio_export_report("Pattern 02", "/x/p.wav", res, 1, 0, 0.0, 0.0, []) == \
        "Pattern 02 exporté en WAV : p.wav — 1,00 s, pattern + résonance (aucune), 16 bits"
    assert win._audio_export_report("Song 01", "/x/s.wav", res, 1, 0, 0.0, 0.0, [],
                                    unit="song", detail="3 patterns") == \
        "Song 01 exporté en WAV : s.wav (3 patterns) — 1,00 s, song + résonance (aucune), 16 bits"
    print("  compte rendu : unité et précision, pattern inchangé : OK")

@pytest.fixture
def wx_app_alive():
    """test_midi_export_ui.py, qui passe avant ce fichier, détruit la wx.App
    de session (make_km / teardown) : en recréer une au besoin, gardée
    dans le module (sans référence, elle serait aussitôt libérée), sans la
    détruire ensuite."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    yield


_APP = None


def test_audio_dialog_end_label_for_song(wx_app_alive):
    for kw, label in (({}, "Fin : Pattern + résonance"), ({"unit": "Song"}, "Fin : Song + résonance")):
        dlg = AudioExportDialog(None, 1, **kw)
        try:
            assert dlg._end_lb.GetString(0) == "Fin : Boucle exacte (résonance repliée)"
            assert dlg._end_lb.GetString(1) == label
            assert dlg.get_end_idx() == 1
        finally:
            dlg.Destroy()
    print("  dialogue : « Song + résonance » pour un song, pattern inchangé : OK")

def test_song_window_alt_shift_w_exports_song_audio():
    stub, calls = _song_window_stub()
    SongWindow._on_key(stub, FakeEvent(key=ord('W'), alt=True, shift=True))
    SongWindow._on_key(stub, FakeEvent(key=ord('W'), ukey=ord('w'), alt=True, shift=True))
    assert calls == [("W", 4, {"parent": stub, "status": stub._set_status})] * 2
    for evt in (FakeEvent(key=ord('W'), alt=True),
                FakeEvent(key=ord('W'), shift=True)):
        SongWindow._on_key(stub, evt)
        assert evt.skipped
    assert len(calls) == 2
    print("  fenêtre Songs : Alt+Shift+W exporte le song en audio ; Alt+W, Shift+W non : OK")

def test_song_audio_real_render_to_file(tmp_path, monkeypatch):
    """Vrai routeur, vrai rendu, vrai fichier : pattern courant (2 s à
    120 BPM) puis un pattern à 60 BPM (4 s)."""
    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    wav = str(tmp_path / "imp.wav")
    x = np.zeros(2000, np.float32)
    x[0] = 0.5
    sf.write(wav, x, SR)
    drv = Mixer()
    snd = SoundManager([wav] * 16, wav, wav, driver=drv)
    snd.load_sounds()
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    d = Dialogs(path=str(tmp_path / "song"), opts=(1, 2, False, 2, -14))
    monkeypatch.setattr(mwp.wx, "FileDialog", d.FileDlg)
    monkeypatch.setattr(mwp, "AudioExportDialog", d.OptsDlg)
    win = _AudioSongWindow(str(tmp_path))
    win._router = TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=drv)
    win._router.set_playback_kb("major", 48)
    win._player.volume, win._player.pan, win._player.bpm = 100, 0, 120
    live = win._player._pattern
    live._tape = [[] for _ in live._tape]
    live._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=4))
    b = win._pattern_list[1]
    b._tape = [[] for _ in b._tape]
    b._track_slots = [0] * len(b._track_slots)
    b._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=8))
    win._export_song_audio(0)
    _wait(win)
    y, sr = sf.read(str(tmp_path / "song.wav"), dtype="float32")
    assert sf.info(str(tmp_path / "song.wav")).subtype == "FLOAT"
    assert len(y) == 6 * SR
    assert list(np.flatnonzero(np.abs(y[:, 0]) > 1e-3)) == [round(0.5 * SR), 4 * SR]
    assert win.statuses[-1].startswith("Song 01 exporté en WAV : song.wav (2 patterns) — 6,00 s")
    print("  rendu réel jusqu'au fichier : longueur et positions : OK")
