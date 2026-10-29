#python3
"""
    File: tests/test_midi_import_ui.py
    Tests de l'interface de l'import MIDI (Phase 7 étape 18e1, docs/DESIGN.md
    § 18a1 I1-I3, I5, I11, avancement 18d1 et 18d3) : choix du slot Banque
    (trouvé, créé, emplacement de la soundfont, Rack plein), dialogue de
    fichier (dossier EXPORTS puis dernier dossier validé), annulation, erreur
    de lecture, confirmation d'un pattern non vide, remplacement du pattern
    courant (pistes, canaux, noms, slots, BPM, boucle), Undo, compte rendu,
    fenêtre et statut de l'éditeur MIDI, raccourcis Alt+Shift+I.
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import sys
import os
import types
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import mido
import pytest
import wx

import track_router as tr_mod
from pattern import Pattern, TapeEvent, ETYPE_PATCH, ETYPE_PGM
from rack import Rack, InstrumentType
from track_router import TrackRouter
from player.drum_player import DrumPlayer
from ui.mw_project import ProjectMixin
from ui.mw_patterns import PatternMixin
import ui.midi_editor_window as mew
from test_bank_slot import FakeBankEngine, FakeSynthEngine
from test_key_manager import make_km, FakeEvent, teardown

GM = "/fake/sf2/FluidR3_GM.sf2"


@pytest.fixture(autouse=True)
def _fake_synth(monkeypatch):
    """Aucun SynthEngine réel (flux audio jamais fermé, voir test_bank_slot)."""
    monkeypatch.setattr(tr_mod, "SynthEngine", FakeSynthEngine)


# ---------------------------------------------------------------------------
# Fenêtre factice : vrais ProjectMixin / PatternMixin, player, routeur, Rack
# ---------------------------------------------------------------------------

class _SilentSoundManager:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


class _Ctrl:
    def __init__(self):
        self.value = None
    def SetValue(self, v):     self.value = v
    def SetSelection(self, v): self.value = v


class _ImportWindow(ProjectMixin, PatternMixin):
    def __init__(self, exports_dir, rack=None):
        self._rack   = rack or Rack()
        self._router = TrackRouter(self._rack, "/fake", _SilentSoundManager(),
                                   lambda m: None, bank_engine=FakeBankEngine())
        self._player = DrumPlayer(_SilentSoundManager())
        self._pattern_list        = [Pattern() for _ in range(4)]
        self._cur_pattern_idx     = 1
        self._pattern_cache_dirty = set()
        self._exports_dir  = exports_dir
        self._gm_soundfont = GM
        self._take         = None
        self._cur_slot     = 0
        self._slot_choice  = _Ctrl()
        self._bpm_ctrl     = _Ctrl()
        self.statuses, self.undos, self.calls = [], [], []
    def _show_status(self, msg):        self.statuses.append(msg)
    def _add_undo(self, title):         self.undos.append(title)
    def _update_slot_list(self):        self.calls.append("slots")
    def _refresh_pattern_listbox(self): self.calls.append("patterns")
    def _refresh_grid(self):            pass
    def _refresh_all_voice_display(self): pass
    def _refresh_track_list(self):      self.calls.append("tracks")
    def _refresh_pad_list(self):        pass
    def _update_bpm_display(self):      pass


def _fake_file_dialog(result, path, seen):
    class FakeDlg:
        def __init__(self, parent, title, **kw):
            seen.update(kw, parent=parent, title=title)
        def ShowModal(self): return result
        def GetPath(self):   return path
        def Destroy(self):   pass
    return FakeDlg


def _fake_message_dialog(answer, seen):
    class FakeMsg:
        def __init__(self, parent, message, caption, style):
            seen.append((parent, message))
        def ShowModal(self): return answer
        def Destroy(self):   pass
    return FakeMsg


def _write_mid(path, *, bpm=96, end_bars=2):
    """Deux pistes : Basse (canal 2, programme 33, volume 64) et Batterie
    (canal 10)."""
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack([mido.MetaMessage("track_name", name="Chanson"),
                                mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))])
    bass = mido.MidiTrack([
        mido.MetaMessage("track_name", name="Basse"),
        mido.Message("program_change", channel=1, program=33),
        mido.Message("control_change", channel=1, control=7, value=64),
        mido.Message("note_on", channel=1, note=40, velocity=90),
        mido.Message("note_off", channel=1, note=40, time=480),
        mido.MetaMessage("end_of_track", time=480 * 4 * end_bars - 480)])
    drums = mido.MidiTrack([
        mido.MetaMessage("track_name", name="Batterie"),
        mido.Message("note_on", channel=9, note=36, velocity=100),
        mido.Message("note_off", channel=9, note=36, time=120)])
    mid.tracks.extend([conductor, bass, drums])
    mid.save(path)
    return path


def _run(win, path, *, answer=wx.ID_YES, result=wx.ID_OK, parent=None, status=None):
    seen, asked = {}, []
    with patch("ui.mw_project.wx.FileDialog", _fake_file_dialog(result, path, seen)), \
         patch("ui.mw_project.wx.MessageDialog", _fake_message_dialog(answer, asked)):
        win._import_midi(parent=parent, status=status)
    return seen, asked


# ---------------------------------------------------------------------------
# Slot Banque (I3)
# ---------------------------------------------------------------------------

def test_bank_slot_first_bank_slot_of_rack(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._rack.set_slot(2, InstrumentType.SYNTH, "Piano", {"patch": "p"})
    win._rack.set_slot(5, InstrumentType.BANK, "GeneralUser", {"bank_slot": 2})
    win._rack.set_slot(7, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
    assert win._import_bank_slot() == (5, 2, False)
    print("  slot : premier slot Banque du Rack : OK")

def test_bank_slot_created_in_first_empty_slot(tmp_path):
    win = _ImportWindow(str(tmp_path))
    for i in range(3):
        win._rack.set_slot(i, InstrumentType.KIT, f"Kit {i}", {})
    assert win._import_bank_slot() == (3, 0, True)
    print("  slot : créé dans le premier slot vide, premier emplacement libre : OK")

def test_bank_slot_reuses_emplacement_holding_gm_soundfont(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._rack.set_bank_file(0, "/autre.sf2")
    win._rack.set_bank_file(2, GM)
    assert win._import_bank_slot() == (0, 2, True)
    print("  slot : emplacement qui tient déjà la soundfont GM : OK")

def test_bank_slot_first_free_emplacement_else_first(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._rack.set_bank_file(0, "/a.sf2")
    assert win._import_bank_slot() == (0, 1, True)
    for i in range(Rack.NUM_BANK_SLOTS):
        win._rack.set_bank_file(i, f"/{i}.sf2")
    assert win._import_bank_slot() == (0, 0, True)
    print("  slot : premier emplacement libre, sinon le premier : OK")

def test_bank_slot_none_when_rack_full_without_bank(tmp_path):
    win = _ImportWindow(str(tmp_path))
    for i in range(Rack.NUM_SLOTS):
        win._rack.set_slot(i, InstrumentType.KIT, f"Kit {i}", {})
    assert win._import_bank_slot() is None
    print("  slot : Rack plein sans slot Banque → None : OK")

def test_bank_slot_does_not_touch_rack(tmp_path):
    win = _ImportWindow(str(tmp_path))
    before = win._rack.to_dict()
    win._import_bank_slot()
    assert win._rack.to_dict() == before
    print("  slot : le choix ne modifie pas le Rack : OK")


# ---------------------------------------------------------------------------
# Dialogue de fichier, annulation, erreurs (I1, I3)
# ---------------------------------------------------------------------------

def test_file_dialog_opens_in_exports_then_last_folder(tmp_path):
    exports = tmp_path / "EXPORTS"
    exports.mkdir()
    other = tmp_path / "midi"
    other.mkdir()
    win = _ImportWindow(str(exports))
    seen, _ = _run(win, _write_mid(str(other / "a.mid")))
    assert seen["defaultDir"] == str(exports)
    assert "*.mid" in seen["wildcard"] and "*.midi" in seen["wildcard"]
    assert seen["style"] & wx.FD_OPEN
    seen, _ = _run(win, "", result=wx.ID_CANCEL)
    assert seen["defaultDir"] == str(other)
    print("  dialogue : EXPORTS d'abord, puis le dernier dossier validé : OK")

def test_file_dialog_missing_folders_fall_back(tmp_path):
    win = _ImportWindow(str(tmp_path / "absent"))
    win._import_dir = str(tmp_path / "parti")
    seen, _ = _run(win, "", result=wx.ID_CANCEL)
    assert seen["defaultDir"] == os.path.expanduser("~")
    win._exports_dir = str(tmp_path)
    seen, _ = _run(win, "", result=wx.ID_CANCEL)
    assert seen["defaultDir"] == str(tmp_path)
    print("  dialogue : dossiers absents → EXPORTS, sinon le dossier personnel : OK")

def test_cancel_changes_nothing(tmp_path):
    win = _ImportWindow(str(tmp_path))
    before = win._pattern_list[1].to_dict()
    _run(win, "", result=wx.ID_CANCEL)
    assert win.statuses == ["Import MIDI annulé"]
    assert win.undos == [] and win._import_dir is None
    assert win._pattern_list[1].to_dict() == before
    print("  annulation du dialogue : rien ne change : OK")

def test_read_error_no_confirmation_no_undo(tmp_path):
    path = tmp_path / "faux.mid"
    path.write_bytes(b"pas un fichier MIDI")
    win = _ImportWindow(str(tmp_path))
    win._player._pattern._tape[0].append(
        TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 1}, time=0))
    _, asked = _run(win, str(path))
    assert win.statuses[-1].startswith("ERREUR import MIDI")
    assert asked == [] and win.undos == []
    assert win._import_dir == str(tmp_path)        # dossier retenu quand même
    print("  erreur de lecture : ni confirmation ni Undo : OK")

def test_refused_when_rack_full_without_bank(tmp_path):
    win = _ImportWindow(str(tmp_path))
    for i in range(Rack.NUM_SLOTS):
        win._rack.set_slot(i, InstrumentType.KIT, f"Kit {i}", {})
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    assert "refusé" in win.statuses[-1]
    assert win.undos == [] and win._player._pattern.is_empty()
    print("  Rack plein sans slot Banque : import refusé : OK")


# ---------------------------------------------------------------------------
# Confirmation, remplacement, Undo, compte rendu (I2, I5, I11)
# ---------------------------------------------------------------------------

def test_empty_pattern_no_confirmation(tmp_path):
    win = _ImportWindow(str(tmp_path))
    _, asked = _run(win, _write_mid(str(tmp_path / "a.mid")))
    assert asked == []
    assert win.undos == ["Import MIDI : a.mid"]
    print("  pattern vide : pas de confirmation, Undo posé : OK")

def test_non_empty_pattern_no_keeps_pattern(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._player._pattern._tape[3].append(
        TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 1}, time=0))
    _, asked = _run(win, _write_mid(str(tmp_path / "a.mid")), answer=wx.ID_NO)
    assert len(asked) == 1
    assert "pattern 02" in asked[0][1] and "a.mid" in asked[0][1]
    assert win.statuses == ["Import MIDI annulé"] and win.undos == []
    assert len(win._player._pattern._tape[3]) == 1
    print("  pattern non vide + Non : rien ne change : OK")

def test_non_empty_pattern_yes_replaces(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._player._pattern._tape[3].append(
        TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 1}, time=0))
    _run(win, _write_mid(str(tmp_path / "a.mid")), answer=wx.ID_YES)
    assert win.undos == ["Import MIDI : a.mid"]
    assert win._player._pattern._tape[3] == []
    print("  pattern non vide + Oui : remplacé : OK")

def test_pattern_replaced_in_store_and_live(tmp_path):
    win = _ImportWindow(str(tmp_path))
    _run(win, _write_mid(str(tmp_path / "a.mid"), bpm=96, end_bars=3))
    stored, live = win._pattern_list[1], win._player._pattern
    assert stored._name == "Chanson" and stored._bpm == 96 and stored._num_bars == 3
    assert live._num_bars == 3 and win._player.bpm == 96 and win._bpm_ctrl.value == 96
    assert [ev.etype for ev in live._tape[0]] == [ETYPE_PGM, ETYPE_PATCH]
    assert win._router._track_channels[:2] == [1, 9]
    assert win._router._track_volumes[0] == 50
    assert 1 in win._pattern_cache_dirty
    assert win._pattern_list[0].is_empty() and win._pattern_list[2].is_empty()
    print("  pattern courant remplacé (store, player, routeur), les autres intacts : OK")

def test_track_names_become_track_names(tmp_path):
    """I5 : noms SMF → noms de pistes (noms des pads de même numéro)."""
    win = _ImportWindow(str(tmp_path))
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    vm = win._player.voice_manager
    assert [vm.get_name(i) for i in range(3)] == ["Basse", "Batterie", ""]
    print("  noms des pistes du fichier : écrits : OK")

def test_slot_created_and_tracks_assigned(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    slot = win._rack.get_slot(1)
    assert slot.type == InstrumentType.BANK and slot.name == "FluidR3_GM"
    assert slot.bank_slot() == 0 and win._rack.bank_files[0] == GM
    assert win._router._track_slots[:3] == [1, 1, 0]
    assert win._pattern_list[1]._track_slots[:3] == [1, 1, 0]
    assert "slots" in win.calls
    assert win._cur_slot == 1 and win._slot_choice.value == 1
    assert win._router.synth is win._router._bank_preview
    print("  slot Banque créé (FluidR3, emplacement 1), pistes importées dessus : OK")

def test_existing_bank_slot_used_and_file_kept(tmp_path):
    win = _ImportWindow(str(tmp_path))
    win._rack.set_bank_file(1, "/autre.sf2")
    win._rack.set_slot(4, InstrumentType.BANK, "Autre", {"bank_slot": 1})
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    assert win._router._track_slots[:2] == [4, 4]
    assert win._rack.bank_files == [None, "/autre.sf2", None, None]
    assert "créé" not in win.statuses[-1]
    print("  slot Banque existant : utilisé, rien de créé : OK")

def test_loop_reset(tmp_path):
    win = _ImportWindow(str(tmp_path))
    live = win._player._pattern
    live._loop_start, live._loop_end, live._loop_count = 4, 12, 3
    win._player._loop_remaining = 2
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    assert (live._loop_start, live._loop_end, live._loop_count) == (None, None, 0)
    assert win._player._loop_remaining == 0
    print("  boucle remise à zéro : OK")

def test_playback_stopped_before_replacing(tmp_path):
    win = _ImportWindow(str(tmp_path))
    stops = []
    win._player._on_play_stop_cb = lambda: stops.append(True)
    win._player.playing = True
    _run(win, _write_mid(str(tmp_path / "a.mid")))
    assert win._player.playing is False and stops == [True]
    print("  lecture arrêtée avant le remplacement : OK")

def test_status_report(tmp_path):
    win = _ImportWindow(str(tmp_path))
    _run(win, _write_mid(str(tmp_path / "a.mid"), bpm=96, end_bars=1))
    assert win.statuses[-1] == ("Import MIDI : a.mid → Pattern 02, 2 pistes, 1 mesure, "
                                "96 BPM, 16 pas ; slot 01 créé : banque FluidR3_GM")
    print("  compte rendu dans la barre d'état : OK")

def test_status_report_includes_details(tmp_path):
    win = _ImportWindow(str(tmp_path))
    path = str(tmp_path / "b.mid")
    mid = mido.MidiFile(type=1, ticks_per_beat=480)
    mid.tracks.append(mido.MidiTrack([
        mido.Message("note_on", note=60, velocity=90, time=7),
        mido.Message("note_off", note=60, time=100),
        mido.Message("aftertouch", value=3)]))
    mid.save(path)
    win._rack.set_slot(0, InstrumentType.BANK, "B", {"bank_slot": 0})
    _run(win, path)
    assert win.statuses[-1].endswith("; 1 note déplacée ; ignorés : 1 aftertouch")
    print("  compte rendu : remarques de l'import : OK")

def test_parent_and_status_from_midi_editor(tmp_path):
    win = _ImportWindow(str(tmp_path))
    editor, msgs = object(), []
    seen, _ = _run(win, "", result=wx.ID_CANCEL, parent=editor, status=msgs.append)
    assert seen["parent"] is editor
    assert msgs == ["Import MIDI annulé"] and win.statuses == []
    print("  parent et statut fournis (éditeur MIDI) : utilisés : OK")


# ---------------------------------------------------------------------------
# Raccourcis (I1)
# ---------------------------------------------------------------------------

def test_alt_shift_i_main_window():
    app, win, km = make_km()
    calls = []
    win._import_midi = lambda: calls.append("import")
    km.handle(FakeEvent(key=ord('I'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('I'), alt=True))              # Alt+I seul : rien
    assert calls == ["import"]
    teardown(app)
    print("  fenêtre principale : Alt+Shift+I importe, Alt+I non : OK")


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
            def _import_midi(self, parent=None, status=None):
                editor.calls.append(("import", parent, status))
            _key_manager = SimpleNamespace(handle_transport=lambda evt: False)
        self._parent = Parent()
    def _set_status(self, msg):    pass
    def _refresh(self):            self.calls.append(("refresh",))
    def _set_lim_left(self, step): self.calls.append(("lim_left", step))


def test_alt_shift_i_midi_editor_imports_before_shift_i():
    """Testé avant Shift+I (limiteur gauche), qui ne regarde pas Alt."""
    ed = _FakeEditor()
    ed._on_key(_FakeKey(ord('I'), shift=True, alt=True))
    assert ed.calls == [("import", ed, ed._set_status), ("refresh",)]
    ed.calls.clear()
    ed._on_key(_FakeKey(ord('I'), shift=True))
    assert ed.calls == [("lim_left", 0)]
    print("  éditeur MIDI : Alt+Shift+I importe et rafraîchit, Shift+I inchangé : OK")
