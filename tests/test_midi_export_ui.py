#python3
"""
    File: tests/test_midi_export_ui.py
    Tests de l'interface de l'export MIDI (Phase 7 étape 10j1, docs/DESIGN.md
    § 10a1 D10) : AppConfig.exports_dir, ProjectMixin._midi_export_params /
    _midi_export_filename / _export_midi (FileDialog simulé : Ok, Annuler,
    extension, erreur), raccourci Alt+Shift+E dans la fenêtre principale
    et dans l'éditeur MIDI. Notes des pads, correspondance GM du kit et
    sons non convertis au statut (Phase 7 étape 11g1, docs/DESIGN.md
    § 11a1 D1, D4).
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import mido
import wx
from types import SimpleNamespace
from unittest.mock import patch

from app_config import AppConfig
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from rack import Rack, InstrumentType
from track_router import TrackRouter
from voice_manager import VoiceManager
from ui.mw_project import ProjectMixin
import ui.midi_editor_window as mew
from test_key_manager import make_km, FakeEvent, teardown


# ---------------------------------------------------------------------------
# AppConfig.exports_dir
# ---------------------------------------------------------------------------

def _config(tmp_path, data):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "config.json").write_text(json.dumps(data), encoding="utf-8")
    return AppConfig(str(tmp_path))

def test_exports_dir_default_next_to_projects(tmp_path):
    assert AppConfig(str(tmp_path)).exports_dir == "/home/com/groovybox/EXPORTS"
    cfg = _config(tmp_path, {"projects_dir": "/srv/music/PROJECTS/"})
    assert cfg.exports_dir == "/srv/music/EXPORTS"
    cfg = _config(tmp_path, {"projects_dir": "mes_projets"})
    assert cfg.exports_dir == os.path.join(str(tmp_path), "EXPORTS")
    print("  exports_dir par défaut : EXPORTS à côté du dossier des projets : OK")

def test_exports_dir_absolute_relative_or_blank(tmp_path):
    assert _config(tmp_path, {"exports_dir": "/data/midi"}).exports_dir == "/data/midi"
    assert _config(tmp_path, {"exports_dir": "out/midi"}).exports_dir == \
        os.path.join(str(tmp_path), "out/midi")
    assert _config(tmp_path, {"exports_dir": "  "}).exports_dir == "/home/com/groovybox/EXPORTS"
    print("  exports_dir configuré : absolu, relatif à base_dir, vide = défaut : OK")


# ---------------------------------------------------------------------------
# Fenêtre factice : vrai ProjectMixin, vrais TrackRouter / Rack / VoiceManager
# ---------------------------------------------------------------------------

KIT, PIANO, ORGAN = 0, 1, 3

class _FakeSoundManager:
    def __init__(self):
        self.kit_base, self.kit_offset = 36, 8
        self.pad_notes   = [44 + i for i in range(16)]   # kit décalé de 8
        self.gm_note_map = {46: 56}                       # pad 2 → Cowbell GM
        self.note_labels = {46: "Cowbell"}
    def play_sound(self, *a): pass
    def stop_all(self):       pass

class _ExportWindow(ProjectMixin):
    def __init__(self, exports_dir, cur_pattern_idx=0):
        rack = Rack()
        rack.set_slot(KIT,   InstrumentType.KIT,   "TR-707",       {"kit": "k.json"})
        rack.set_slot(PIANO, InstrumentType.SYNTH, "Piano 1",      {"patch": "p.json"})
        rack.set_slot(ORGAN, InstrumentType.SYNTH, "DrawbarOrgan", {"patch": "o.json", "gm_program": 18})
        self._rack   = rack
        self._snd    = _FakeSoundManager()
        self._router = TrackRouter(rack, "/fake", self._snd, lambda m: None)
        self._router._ensure_slot_synth = lambda slot_idx: None
        self._router.set_playback_kb("major", 48)
        self._router.assign_slot_by_user(0, PIANO)
        self._router.assign_slot_by_user(1, KIT)
        self._router.assign_slot_by_user(2, ORGAN)
        self._router.set_track_volume(0, 45)
        self._router.set_track_pan(2, -100)
        vm = VoiceManager(Pattern.NUM_PADS)
        vm.from_list([{"name": "", "volume": 100, "pan": 0, "mute": False,
                       "solo": False, "duration_ms": 200 + 10 * i} for i in range(16)])
        live = Pattern()
        live._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 2, "vel": 100}, time=0.0))
        live._tape[1].append(TapeEvent(ETYPE_GRID, payload={"pad": 2, "vel": 100}, time=4.0))
        live._tape[2].append(TapeEvent(ETYPE_PATCH, dur=300, payload={"note": 67, "vel": 90}, time=8.0))
        self._player = SimpleNamespace(bpm=110, voice_manager=vm, _pattern=live)
        self._pattern_list    = [Pattern() for _ in range(12)]
        self._cur_pattern_idx = cur_pattern_idx
        self._exports_dir     = exports_dir
        self.statuses         = []
    def _show_status(self, msg): self.statuses.append(msg)


def _fake_file_dialog(result, path, seen):
    class FakeDlg:
        def __init__(self, parent, title, **kw):
            seen.update(kw, parent=parent, title=title)
        def ShowModal(self): return result
        def GetPath(self):   return path
        def Destroy(self):   seen["destroyed"] = True
    return FakeDlg


# ---------------------------------------------------------------------------
# _midi_export_params / _midi_export_filename
# ---------------------------------------------------------------------------

def test_params_come_from_router_rack_player_and_kit(tmp_path):
    win = _ExportWindow(str(tmp_path))
    p = win._midi_export_params()
    assert p["name"] == "Pat_01" and p["bpm"] == 110
    assert p["track_channels"][:3] == [0, 9, 2]
    assert p["track_is_synth"][:3] == [True, False, True]
    assert p["track_names"][:3] == ["Piano 1", "TR-707", "DrawbarOrgan"]
    assert p["track_programs"][:3] == [0, 25, 18]
    assert p["track_volumes"][:3] == [45, 100, 100]
    assert p["track_pans"][:3] == [0, 0, -100]
    assert p["kit_pad_notes"] == list(range(44, 60))
    assert p["kit_gm_map"] == {46: 56}
    assert p["kit_pad_notes"] is not win._snd.pad_notes       # copies
    assert p["kit_gm_map"] is not win._snd.gm_note_map
    assert p["synth_grid_notes"] == win._router._kb_notes_play
    assert p["voice_durations"][:3] == [200, 210, 220]
    assert p["pad_volumes"] == [100] * 16                     # 12a1 D2
    assert p["track_channels"] is not win._router._track_channels   # copies
    print("  paramètres : router, slots du Rack, player, kit chargé, voix : OK")

def test_params_pad_volumes_follow_voice_manager(tmp_path):
    """Phase 7 étape 12e1 : volumes des pads → vélocité des cases de grille."""
    win = _ExportWindow(str(tmp_path))
    win._player.voice_manager.set_volume(2, 50)
    p = win._midi_export_params()
    assert p["pad_volumes"][:3] == [100, 100, 50]
    path, seen = str(tmp_path / "v.mid"), {}
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, path, seen)):
        win._export_midi()
    vels = [[m.velocity for m in tr if m.type == "note_on"] for tr in mido.MidiFile(path).tracks[1:3]]
    assert vels == [[64], [64]]          # pad 2 à 50 : piste synthé et piste kit
    print("  paramètres : volumes des pads, vélocité des cases de grille : OK")

def test_params_audible_follow_router_and_voice_manager(tmp_path):
    """Phase 7 étape 12f3 : mute et solo des pistes et des pads, règles du
    rejeu (le mute l'emporte sur le solo)."""
    win = _ExportWindow(str(tmp_path))
    p = win._midi_export_params()
    assert p["track_audible"] == [True] * 16 and p["pad_audible"] == [True] * 16
    r, vm = win._router, win._player.voice_manager
    r.toggle_track_mute(0)
    assert win._midi_export_params()["track_audible"][:3] == [False, True, True]
    r.toggle_track_solo(0)
    r.toggle_track_solo(2)
    assert win._midi_export_params()["track_audible"][:3] == [False, False, True]
    vm.toggle_solo(2)
    vm.set_mute(5, True)
    pads = win._midi_export_params()["pad_audible"]
    assert pads[2] is True and pads.count(True) == 1
    print("  paramètres : mute et solo du router et des pads, mute prioritaire : OK")

def test_export_file_omits_muted_track(tmp_path):
    win = _ExportWindow(str(tmp_path))
    win._router.toggle_track_mute(1)                          # TR-707
    path = str(tmp_path / "m.mid")
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, path, {})):
        win._export_midi()
    assert [tr.name for tr in mido.MidiFile(path).tracks] == ["Pat_01", "Piano 1", "DrawbarOrgan"]
    print("  fichier : la piste mutée n'est pas exportée : OK")

def test_params_name_is_pattern_name_when_set(tmp_path):
    win = _ExportWindow(str(tmp_path), cur_pattern_idx=4)
    assert win._midi_export_params()["name"] == "Pat_05"
    win._pattern_list[4]._name = "Intro"
    assert win._midi_export_params()["name"] == "Intro"
    print("  nom de la piste conductor : nom du pattern, sinon Pat_NN : OK")

def test_filename_proposed_and_cleaned(tmp_path):
    win = _ExportWindow(str(tmp_path), cur_pattern_idx=11)
    assert win._midi_export_filename() == "Pat_12.mid"
    win._pattern_list[11]._name = "Intro / couplet: v2?"
    assert win._midi_export_filename() == "Pat_12_Intro_couplet_v2.mid"
    win._pattern_list[11]._name = "!!!"
    assert win._midi_export_filename() == "Pat_12.mid"
    print("  nom de fichier : Pat_NN[_nom].mid, caractères spéciaux retirés : OK")


# ---------------------------------------------------------------------------
# _export_midi (FileDialog simulé)
# ---------------------------------------------------------------------------

def test_export_ok_writes_file_and_announces(tmp_path):
    exports = tmp_path / "EXPORTS"
    win = _ExportWindow(str(exports))
    path, seen = str(exports / "Pat_01.mid"), {}
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, path, seen)):
        win._export_midi()
    assert exports.is_dir()                                   # créé au besoin
    assert seen["defaultDir"] == str(exports) and seen["defaultFile"] == "Pat_01.mid"
    assert seen["wildcard"] == "Fichiers MIDI (*.mid)|*.mid"
    assert seen["style"] & wx.FD_SAVE and seen["style"] & wx.FD_OVERWRITE_PROMPT
    assert seen["parent"] is win and seen["destroyed"]
    assert win.statuses == ["Pattern 01 exporté : Pat_01.mid"]
    mid = mido.MidiFile(path)
    assert [tr.name for tr in mid.tracks] == ["Pat_01", "Piano 1", "TR-707", "DrawbarOrgan"]
    chans = [{m.channel for m in tr if hasattr(m, "channel")} for tr in mid.tracks[1:]]
    assert chans == [{0}, {9}, {2}]
    kit_note = [m.note for m in mid.tracks[2] if m.type == "note_on"]
    assert kit_note == [56]                    # pad 2 → note 46 → GM 56 (11a1)
    print("  Ok : dossier créé, dialog, fichier écrit avec les réglages de l'appli, statut : OK")

def test_export_announces_unmapped_kit_notes(tmp_path):
    """D4 : sons sans correspondance GM listés au statut, triés par note,
    avec leur libellé, ou « Note N », suivi de la note."""
    win = _ExportWindow(str(tmp_path))
    win._snd.gm_note_map = {}
    win._player._pattern._tape[1].append(
        TapeEvent(ETYPE_KIT, payload={"note": 90, "vel": 100}, time=8.0))
    path = str(tmp_path / "Pat_01.mid")
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, path, {})):
        win._export_midi()
    assert win.statuses == ["Pattern 01 exporté : Pat_01.mid"
                            " — non converti en GM : Cowbell (46), Note 90 (90)"]
    kit_notes = [m.note for m in mido.MidiFile(path).tracks[2] if m.type == "note_on"]
    assert kit_notes == [46, 90]
    print("  sons non convertis : notes gardées, listés au statut : OK")

def test_export_unmapped_status_goes_to_given_status(tmp_path):
    win = _ExportWindow(str(tmp_path))
    win._snd.gm_note_map = {}
    msgs = []
    path = str(tmp_path / "x.mid")
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, path, {})):
        win._export_midi(status=msgs.append)
    assert msgs == ["Pattern 01 exporté : x.mid — non converti en GM : Cowbell (46)"]
    assert win.statuses == []
    print("  sons non convertis : annoncés dans le statut fourni (éditeur MIDI) : OK")

def test_export_adds_mid_extension(tmp_path):
    win = _ExportWindow(str(tmp_path))
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, str(tmp_path / "groove"), {})):
        win._export_midi()
    assert (tmp_path / "groove.mid").is_file()
    assert win.statuses == ["Pattern 01 exporté : groove.mid"]
    print("  extension .mid ajoutée si absente : OK")

def test_export_cancel_writes_nothing(tmp_path):
    win = _ExportWindow(str(tmp_path))
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_CANCEL, "", {})):
        win._export_midi()
    assert list(tmp_path.iterdir()) == []
    assert win.statuses == ["Export MIDI annulé"]
    print("  Annuler : rien d'écrit, « Export MIDI annulé » : OK")

def test_export_write_error_is_announced(tmp_path):
    win = _ExportWindow(str(tmp_path))
    bad = str(tmp_path / "absent" / "x.mid")
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_OK, bad, {})):
        win._export_midi()
    assert len(win.statuses) == 1 and win.statuses[0].startswith("ERREUR export MIDI : ")
    print("  erreur d'écriture : annoncée, sans exception : OK")

def test_export_uses_given_parent_and_status(tmp_path):
    win = _ExportWindow(str(tmp_path))
    editor, editor_msgs, seen = object(), [], {}
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(wx.ID_CANCEL, "", seen)):
        win._export_midi(parent=editor, status=editor_msgs.append)
    assert seen["parent"] is editor
    assert editor_msgs == ["Export MIDI annulé"] and win.statuses == []
    print("  parent et statut fournis (éditeur MIDI) : utilisés : OK")


# ---------------------------------------------------------------------------
# Raccourcis
# ---------------------------------------------------------------------------

def test_alt_shift_e_main_window():
    app, win, km = make_km()
    calls = []
    win._export_midi = lambda: calls.append("export")
    km.handle(FakeEvent(key=ord('E'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('E'), alt=True))              # Alt+E seul : rien
    assert calls == ["export"]
    teardown(app)
    print("  fenêtre principale : Alt+Shift+E exporte, Alt+E non : OK")

class _FakeKey:
    def __init__(self, key, ctrl=False, shift=False, alt=False):
        self._k, self._c, self._s, self._a = key, ctrl, shift, alt
        self.skipped = False
    def GetKeyCode(self):    return self._k
    def GetUnicodeKey(self): return self._k
    def ControlDown(self):   return self._c
    def ShiftDown(self):     return self._s
    def AltDown(self):       return self._a
    def Skip(self):          self.skipped = True

class _FakeEditor:
    _on_key = mew.MidiEditorWindow._on_key
    def __init__(self):
        self.calls = []
        editor = self
        class Parent:
            def _export_midi(self, parent=None, status=None):
                editor.calls.append((parent, status))
            _key_manager = SimpleNamespace(handle_transport=lambda evt: False)
        self._parent = Parent()
    def _set_status(self, msg): pass

def test_alt_shift_e_midi_editor_uses_its_window():
    ed = _FakeEditor()
    evt = _FakeKey(ord('E'), shift=True, alt=True)
    ed._on_key(evt)
    assert len(ed.calls) == 1
    parent, status = ed.calls[0]
    assert parent is ed and status == ed._set_status
    assert evt.skipped is False
    print("  éditeur MIDI : Alt+Shift+E exporte, dialog et statut de l'éditeur : OK")
