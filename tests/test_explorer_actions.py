#python3
"""
    File: tests/test_explorer_actions.py
    Tests unitaires des actions de l'explorateur : _explorer_preset,
    _explorer_kit, _explorer_patch, _explorer_sound.
    wx.FileDialog est mocké pour simuler sélection OK ou annulation.
    Date: Thu, 28/05/2026
    Author: Coolbrother
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from unittest.mock import MagicMock, patch
from rack import InstrumentType
from ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class FakeRack:
    def __init__(self):
        self.set_slot_calls = []

    def set_slot(self, slot_idx, itype, name, config):
        self.set_slot_calls.append((slot_idx, itype, name, config))


class FakeRouter:
    def __init__(self):
        self.reload_slot_calls = []

    def reload_slot(self, slot_idx):
        self.reload_slot_calls.append(slot_idx)


class FakeVoiceManager:
    def __init__(self):
        self.names = {}

    def set_name(self, pad_idx, name):
        self.names[pad_idx] = name


class FakePlayer:
    def __init__(self):
        self.voice_manager = FakeVoiceManager()


class FakeSnd:
    def __init__(self):
        self.load_pad_calls = []

    def load_pad_sound(self, pad_idx, wav_path):
        self.load_pad_calls.append((pad_idx, wav_path))


# ---------------------------------------------------------------------------
# FakeWindow — objet minimal portant les attributs lus par _explorer_*
# ---------------------------------------------------------------------------

class FakeWindow:
    pass


def make_win(tmp):
    win = FakeWindow()
    win._presets_dir  = tmp
    win._kits_dir     = tmp
    win._patches_dir  = tmp
    win._samples_dir  = tmp
    win._preset_path  = "/old/preset.json"
    win._cur_slot     = 2
    win._cur_row      = 3
    win._media_lst    = [""] * 16
    win._rack         = FakeRack()
    win._router       = FakeRouter()
    win._snd          = FakeSnd()
    win._player       = FakePlayer()

    win._load_preset_calls      = []
    win._load_kit_slot_calls    = []
    win._update_slot_list_calls = []
    win._refresh_pad_list_calls = []
    win._show_status_calls      = []

    win._load_preset      = lambda:    win._load_preset_calls.append(1)
    win._load_kit_slot    = lambda s:  win._load_kit_slot_calls.append(s)
    win._update_slot_list = lambda:    win._update_slot_list_calls.append(1)
    win._refresh_pad_list = lambda:    win._refresh_pad_list_calls.append(1)
    win._show_status      = lambda msg: win._show_status_calls.append(msg)
    return win


def dlg_ok(path):
    m = MagicMock()
    m.ShowModal.return_value = wx.ID_OK
    m.GetPath.return_value   = path
    return m


def dlg_cancel():
    m = MagicMock()
    m.ShowModal.return_value = wx.ID_CANCEL
    return m


# ---------------------------------------------------------------------------
# _explorer_preset
# ---------------------------------------------------------------------------

def test_preset_ok_sets_preset_path():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "new.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_preset(win)
        assert win._preset_path == path
        print("  preset OK → _preset_path mis à jour : OK")


def test_preset_ok_calls_load_preset():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "new.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_preset(win)
        assert win._load_preset_calls == [1]
        print("  preset OK → _load_preset() appelé : OK")


def test_preset_ok_shows_status():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "new.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_preset(win)
        assert any("new.json" in s for s in win._show_status_calls)
        print("  preset OK → _show_status affiche le nom du fichier : OK")


def test_preset_cancel_no_load():
    with tempfile.TemporaryDirectory() as tmp:
        win = make_win(tmp)
        with patch.object(wx, 'FileDialog', return_value=dlg_cancel()):
            MainWindow._explorer_preset(win)
        assert win._load_preset_calls == []
        assert win._preset_path == "/old/preset.json"
        print("  preset Annuler → _load_preset() non appelé, path inchangé : OK")


# ---------------------------------------------------------------------------
# _explorer_kit
# ---------------------------------------------------------------------------

def test_kit_ok_calls_set_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "my_kit.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_kit(win)
        assert len(win._rack.set_slot_calls) == 1
        slot_idx, itype, name, config = win._rack.set_slot_calls[0]
        assert slot_idx == 2
        assert itype    == InstrumentType.KIT
        assert name     == "my_kit"
        assert config   == {"kit": path}
        print("  kit OK → rack.set_slot(cur_slot, KIT, name, {kit}) : OK")


def test_kit_ok_calls_load_kit_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "my_kit.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_kit(win)
        assert win._load_kit_slot_calls == [2]
        print("  kit OK → _load_kit_slot(cur_slot) appelé : OK")


def test_kit_ok_calls_update_slot_list():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "my_kit.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_kit(win)
        assert win._update_slot_list_calls == [1]
        print("  kit OK → _update_slot_list() appelé : OK")


def test_kit_cancel_no_set_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win = make_win(tmp)
        with patch.object(wx, 'FileDialog', return_value=dlg_cancel()):
            MainWindow._explorer_kit(win)
        assert win._rack.set_slot_calls == []
        assert win._load_kit_slot_calls == []
        print("  kit Annuler → rack.set_slot non appelé : OK")


# ---------------------------------------------------------------------------
# _explorer_patch
# ---------------------------------------------------------------------------

def test_patch_ok_calls_set_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "piano.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_patch(win)
        assert len(win._rack.set_slot_calls) == 1
        slot_idx, itype, name, config = win._rack.set_slot_calls[0]
        assert slot_idx == 2
        assert itype    == InstrumentType.SYNTH
        assert name     == "piano"
        assert config   == {"patch": path}
        print("  patch OK → rack.set_slot(cur_slot, SYNTH, name, {patch}) : OK")


def test_patch_ok_calls_reload_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "piano.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_patch(win)
        assert win._router.reload_slot_calls == [2]
        print("  patch OK → router.reload_slot(cur_slot) appelé : OK")


def test_patch_ok_calls_update_slot_list():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "piano.json")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_patch(win)
        assert win._update_slot_list_calls == [1]
        print("  patch OK → _update_slot_list() appelé : OK")


def test_patch_cancel_no_set_slot():
    with tempfile.TemporaryDirectory() as tmp:
        win = make_win(tmp)
        with patch.object(wx, 'FileDialog', return_value=dlg_cancel()):
            MainWindow._explorer_patch(win)
        assert win._rack.set_slot_calls          == []
        assert win._router.reload_slot_calls     == []
        assert win._update_slot_list_calls       == []
        print("  patch Annuler → rack.set_slot non appelé : OK")


# ---------------------------------------------------------------------------
# _explorer_sound
# ---------------------------------------------------------------------------

def test_sound_ok_calls_load_pad_sound():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "kick.wav")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_sound(win)
        assert win._snd.load_pad_calls == [(3, path)]
        print("  sound OK → snd.load_pad_sound(cur_row, wav_path) : OK")


def test_sound_ok_sets_voice_name():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "kick.wav")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_sound(win)
        assert win._player.voice_manager.names[3] == "kick"
        print("  sound OK → voice_manager.set_name(cur_row, 'kick') : OK")


def test_sound_ok_updates_media_lst():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "kick.wav")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_sound(win)
        assert win._media_lst[3] == path
        print("  sound OK → _media_lst[cur_row] mis à jour : OK")


def test_sound_ok_calls_refresh_pad_list():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "kick.wav")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_sound(win)
        assert win._refresh_pad_list_calls == [1]
        print("  sound OK → _refresh_pad_list() appelé : OK")


def test_sound_ok_shows_status():
    with tempfile.TemporaryDirectory() as tmp:
        win  = make_win(tmp)
        path = os.path.join(tmp, "kick.wav")
        with patch.object(wx, 'FileDialog', return_value=dlg_ok(path)):
            MainWindow._explorer_sound(win)
        assert any("kick" in s for s in win._show_status_calls)
        print("  sound OK → _show_status mentionne le nom du pad : OK")


def test_sound_cancel_no_load():
    with tempfile.TemporaryDirectory() as tmp:
        win = make_win(tmp)
        with patch.object(wx, 'FileDialog', return_value=dlg_cancel()):
            MainWindow._explorer_sound(win)
        assert win._snd.load_pad_calls          == []
        assert win._refresh_pad_list_calls      == []
        assert win._player.voice_manager.names  == {}
        print("  sound Annuler → aucune action : OK")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== test_explorer_actions ===")
    # _explorer_preset
    test_preset_ok_sets_preset_path()
    test_preset_ok_calls_load_preset()
    test_preset_ok_shows_status()
    test_preset_cancel_no_load()
    # _explorer_kit
    test_kit_ok_calls_set_slot()
    test_kit_ok_calls_load_kit_slot()
    test_kit_ok_calls_update_slot_list()
    test_kit_cancel_no_set_slot()
    # _explorer_patch
    test_patch_ok_calls_set_slot()
    test_patch_ok_calls_reload_slot()
    test_patch_ok_calls_update_slot_list()
    test_patch_cancel_no_set_slot()
    # _explorer_sound
    test_sound_ok_calls_load_pad_sound()
    test_sound_ok_sets_voice_name()
    test_sound_ok_updates_media_lst()
    test_sound_ok_calls_refresh_pad_list()
    test_sound_ok_shows_status()
    test_sound_cancel_no_load()
    print("Tous les tests : OK")
