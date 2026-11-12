#python3
"""
    File: tests/test_preferences_dialog.py
    Dialogue des Préférences (Phase 8 étape 10d1, docs/DESIGN.md § 10a
    P3-P8) : onglets, valeurs lues dans AppConfig, réglages changés, Ok /
    Annuler / Appliquer, Parcourir…, onglets au clavier (Ctrl+Tab,
    Ctrl+Shift+Tab, Gauche / Droite sur l'onglet), libellé créé avant son
    champ (lu par Orca, essai de 10d1) ; _open_preferences /
    _apply_preferences ; Alt+Shift+P dans la fenêtre principale, l'éditeur
    MIDI et la fenêtre Songs.
    Date: Wed, 11/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

from app_config import AppConfig
from ui.dialogs_preferences import PreferencesDialog
import ui.dialogs_preferences as dp
from ui.mw_project import ProjectMixin
from ui.song_window import SongWindow
import ui.midi_editor_window as mew
from ui.key_manager import KeyManager
from test_key_manager import FakeWindow, FakeEvent


# ---------------------------------------------------------------------------
# Montage
# ---------------------------------------------------------------------------

def _cfg(tmp_path, prefs=None, defaults=None):
    base = tmp_path / "app"
    os.makedirs(base / "data", exist_ok=True)
    if defaults is not None:
        (base / "data" / "config.json").write_text(json.dumps(defaults), encoding="utf-8")
    path = tmp_path / "cfg" / "preferences.json"
    if prefs is not None:
        os.makedirs(path.parent, exist_ok=True)
        path.write_text(json.dumps(prefs), encoding="utf-8")
    return AppConfig(str(base), prefs_path=str(path))


@pytest.fixture
def make(tmp_path):
    dialogs, applied = [], []

    def build(prefs=None, defaults=None, page=0, on_apply=True):
        cfg = _cfg(tmp_path, prefs, defaults)
        dlg = PreferencesDialog(None, cfg, on_apply=applied.append if on_apply else None,
                                page=page)
        dialogs.append(dlg)
        return dlg
    build.applied = applied
    yield build
    for dlg in dialogs:
        dlg.Destroy()


FULL_PREFS = {
    "startup": "new", "autoplay": False, "explorer_autoplay": False,
    "live_limiter": False, "fluidsynth": False, "sfizz": False,
    "fluidsynth_gain": 0.8, "sfizz_gain": 2.5,
    "master_volume": 150, "master_pan": -30, "midi_bank_select": "mma",
    "app_projects_dir": "/opt/demos", "projects_dir": "/u/PROJECTS",
    "app_banks_dir": "/opt/banks", "user_banks_dir": "/u",
}


# ---------------------------------------------------------------------------
# Onglets et pages
# ---------------------------------------------------------------------------

def test_seven_tabs_in_order(make):
    dlg = make()
    book = dlg._book
    assert [book.GetPageText(i) for i in range(book.GetPageCount())] == \
        ["Général", "Matériel", "Audio", "Midi", "Projet", "Raccourcis", "Divers"]


def test_title_and_buttons(make):
    dlg = make()
    assert dlg.GetTitle() == "Préférences"
    labels = {dlg.FindWindow(i).GetLabel() for i in (wx.ID_OK, wx.ID_CANCEL, wx.ID_APPLY)}
    assert labels == {"Ok", "Annuler", "Appliquer"}


@pytest.mark.parametrize("page, expected", [(0, 0), (4, 4), (-3, 0), (99, 6)])
def test_initial_page(make, page, expected):
    assert make(page=page)._book.GetSelection() == expected


@pytest.mark.parametrize("tab", ["Matériel", "Raccourcis", "Divers"])
def test_later_tabs_carry_a_sentence(make, tab):
    children = make()._pages[tab].GetChildren()
    assert len(children) == 1 and isinstance(children[0], wx.StaticText)
    assert children[0].GetLabel()


# ---------------------------------------------------------------------------
# Valeurs lues dans AppConfig
# ---------------------------------------------------------------------------

def test_default_values(make):
    vals = make(defaults={"projects_dir": "/gb/PROJECTS"}).values()
    assert vals["startup"] == "last"
    assert vals["autoplay"] is True and vals["explorer_autoplay"] is True
    assert vals["live_limiter"] is True and vals["fluidsynth"] is True and vals["sfizz"] is True
    assert vals["fluidsynth_gain"] == 0.4 and vals["sfizz_gain"] == 1.5
    assert vals["master_volume"] == 100 and vals["master_pan"] == 0
    assert vals["midi_bank_select"] == "gs"
    assert vals["projects_dir"] == "/gb/PROJECTS"
    assert vals["user_banks_dir"] == "/gb"


def test_values_from_preferences(make):
    assert make(FULL_PREFS).values() == FULL_PREFS


def test_controls_show_the_values(make):
    dlg = make(FULL_PREFS)
    assert dlg._startup.GetStringSelection() == "Nouveau projet"
    assert dlg._bank_select.GetStringSelection() == "MMA (MSB × 128 + LSB)"
    assert dlg._fluidsynth_gain.GetValue() == 8 and dlg._sfizz_gain.GetValue() == 25
    assert dlg._master_volume.GetValue() == 150 and dlg._master_pan.GetValue() == -30
    assert dlg._paths["user_banks_dir"].GetValue() == "/u"


def test_spin_ranges(make):
    dlg = make()
    assert (dlg._fluidsynth_gain.GetMin(), dlg._fluidsynth_gain.GetMax()) == (0, 100)
    assert (dlg._sfizz_gain.GetMin(), dlg._sfizz_gain.GetMax()) == (0, 100)
    assert (dlg._master_volume.GetMin(), dlg._master_volume.GetMax()) == (0, 200)
    assert (dlg._master_pan.GetMin(), dlg._master_pan.GetMax()) == (-100, 100)


def test_gain_rounded_to_tenths(make):
    assert make({"fluidsynth_gain": 0.44}).values()["fluidsynth_gain"] == 0.4


# ---------------------------------------------------------------------------
# Réglages changés
# ---------------------------------------------------------------------------

def test_no_change_at_opening(make):
    assert make(FULL_PREFS).changes() == {}


def test_changes_list_only_what_moved(make):
    dlg = make()
    dlg._startup.SetSelection(1)
    dlg._explorer_autoplay.SetValue(False)
    dlg._sfizz_gain.SetValue(20)
    dlg._master_pan.SetValue(10)
    dlg._bank_select.SetSelection(1)
    dlg._paths["projects_dir"].SetValue("  /ailleurs/P  ")
    assert dlg.changes() == {"startup": "new", "explorer_autoplay": False,
                             "sfizz_gain": 2.0, "master_pan": 10,
                             "midi_bank_select": "mma", "projects_dir": "/ailleurs/P"}


def test_change_back_is_no_change(make):
    dlg = make()
    dlg._autoplay.SetValue(False)
    dlg._autoplay.SetValue(True)
    assert dlg.changes() == {}


def test_cleared_path_means_back_to_default(make):
    dlg = make(FULL_PREFS)
    dlg._paths["app_banks_dir"].SetValue("   ")
    assert dlg.changes() == {"app_banks_dir": None}


# ---------------------------------------------------------------------------
# Ok / Annuler / Appliquer
# ---------------------------------------------------------------------------

def _click(dlg, btn_id):
    evt = wx.CommandEvent(wx.wxEVT_BUTTON, btn_id)
    evt.SetEventObject(dlg.FindWindow(btn_id))
    dlg.FindWindow(btn_id).GetEventHandler().ProcessEvent(evt)


def test_apply_passes_changes_and_stays_open(make, monkeypatch):
    dlg = make()
    ended = []
    monkeypatch.setattr(PreferencesDialog, "EndModal", lambda self, code: ended.append(code))
    dlg._autoplay.SetValue(False)
    _click(dlg, wx.ID_APPLY)
    assert make.applied == [{"autoplay": False}]
    assert ended == []
    assert dlg.changes() == {}                 # nouveau point de départ
    dlg._master_volume.SetValue(120)
    _click(dlg, wx.ID_APPLY)
    assert make.applied[-1] == {"master_volume": 120}


def test_apply_without_change_calls_nothing(make):
    dlg = make()
    _click(dlg, wx.ID_APPLY)
    assert make.applied == []


def test_ok_applies_then_closes(make, monkeypatch):
    dlg = make()
    ended = []
    monkeypatch.setattr(PreferencesDialog, "EndModal", lambda self, code: ended.append(code))
    dlg._fluidsynth.SetValue(False)
    _click(dlg, wx.ID_OK)
    assert make.applied == [{"fluidsynth": False}]
    assert ended == [wx.ID_OK]


def test_ok_after_apply_sends_nothing_more(make, monkeypatch):
    dlg = make()
    monkeypatch.setattr(PreferencesDialog, "EndModal", lambda self, code: None)
    dlg._sfizz.SetValue(False)
    _click(dlg, wx.ID_APPLY)
    _click(dlg, wx.ID_OK)
    assert make.applied == [{"sfizz": False}]


def test_ok_without_callback(make, monkeypatch):
    dlg = make(on_apply=False)
    ended = []
    monkeypatch.setattr(PreferencesDialog, "EndModal", lambda self, code: ended.append(code))
    dlg._autoplay.SetValue(False)
    _click(dlg, wx.ID_OK)
    assert ended == [wx.ID_OK]


def test_cancel_applies_nothing(make):
    dlg = make()
    dlg._autoplay.SetValue(False)
    cancel = dlg.FindWindow(wx.ID_CANCEL)
    assert cancel.GetId() == wx.ID_CANCEL      # fermeture standard de wx, sans on_apply
    assert make.applied == []


# ---------------------------------------------------------------------------
# Parcourir…
# ---------------------------------------------------------------------------

class _FakeDirDialog:
    def __init__(self, result, path, seen):
        self._result, self._path, self.seen = result, path, seen
    def ShowModal(self):
        return self._result
    def GetPath(self):
        return self._path
    def Destroy(self):
        self.seen["destroyed"] = True


def _dir_factory(result, path, seen):
    def make(parent, msg, start):
        seen.update(parent=parent, msg=msg, start=start)
        return _FakeDirDialog(result, path, seen)
    return make


def test_browse_ok_fills_the_field(make):
    dlg = make({"user_banks_dir": "/u"})
    seen = {}
    dlg._dir_dialog = _dir_factory(wx.ID_OK, "/nouveau/banques", seen)
    dlg._browse("user_banks_dir")
    assert dlg._paths["user_banks_dir"].GetValue() == "/nouveau/banques"
    assert seen == {"parent": dlg, "msg": "Banques de l'utilisateur", "start": "/u",
                    "destroyed": True}
    assert dlg.changes() == {"user_banks_dir": "/nouveau/banques"}


def test_browse_cancel_keeps_the_field(make):
    dlg = make({"projects_dir": "/u/P"})
    seen = {}
    dlg._dir_dialog = _dir_factory(wx.ID_CANCEL, "/ignoré", seen)
    dlg._browse("projects_dir")
    assert dlg._paths["projects_dir"].GetValue() == "/u/P"
    assert seen["destroyed"]


def test_browse_button_per_path(make):
    children = make()._pages["Projet"].GetChildren()
    buttons = [c for c in children if isinstance(c, wx.Button)]
    assert [b.GetLabel() for b in buttons] == ["Parcourir…"] * 4 + ["Valeurs par défaut"]


# ---------------------------------------------------------------------------
# Onglets au clavier (P4)
# ---------------------------------------------------------------------------

def test_select_tab_wraps_both_ways(make):
    dlg = make()
    dlg.select_tab(-1)
    assert dlg._book.GetSelection() == 6
    dlg.select_tab(1)
    assert dlg._book.GetSelection() == 0
    dlg.select_tab(1)
    assert dlg._book.GetSelection() == 1


def test_ctrl_tab_next_and_ctrl_shift_tab_previous(make):
    dlg = make(page=2)
    evt = FakeEvent(key=wx.WXK_TAB, ctrl=True)
    dlg._on_char_hook(evt)
    assert dlg._book.GetSelection() == 3 and not evt.skipped
    evt = FakeEvent(key=wx.WXK_TAB, ctrl=True, shift=True)
    dlg._on_char_hook(evt)
    assert dlg._book.GetSelection() == 2 and not evt.skipped


def test_ctrl_tab_moves_focus_to_the_tab(make, monkeypatch):
    dlg = make()
    focused = []
    monkeypatch.setattr(dlg._book, "SetFocus", lambda: focused.append(True))
    dlg._on_char_hook(FakeEvent(key=wx.WXK_TAB, ctrl=True))
    assert focused == [True]


def test_ctrl_tab_works_from_any_field(make, monkeypatch):
    dlg = make()
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: dlg._autoplay))
    dlg._on_char_hook(FakeEvent(key=wx.WXK_TAB, ctrl=True))
    assert dlg._book.GetSelection() == 1


def test_arrows_on_the_tab(make, monkeypatch):
    dlg = make(page=3)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: dlg._book))
    evt = FakeEvent(key=wx.WXK_RIGHT)
    dlg._on_char_hook(evt)
    assert dlg._book.GetSelection() == 4 and not evt.skipped
    dlg._on_char_hook(FakeEvent(key=wx.WXK_LEFT))
    dlg._on_char_hook(FakeEvent(key=wx.WXK_LEFT))
    assert dlg._book.GetSelection() == 2


def test_arrows_wrap_on_the_tab(make, monkeypatch):
    dlg = make(page=6)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: dlg._book))
    dlg._on_char_hook(FakeEvent(key=wx.WXK_RIGHT))
    assert dlg._book.GetSelection() == 0


def test_arrows_in_a_field_are_left_to_the_field(make, monkeypatch):
    dlg = make(page=4)
    monkeypatch.setattr(wx.Window, "FindFocus",
                        staticmethod(lambda: dlg._paths["projects_dir"]))
    evt = FakeEvent(key=wx.WXK_LEFT)
    dlg._on_char_hook(evt)
    assert dlg._book.GetSelection() == 4 and evt.skipped


@pytest.mark.parametrize("mods", [{"ctrl": True}, {"alt": True}, {"shift": True}])
def test_modified_arrows_not_taken(make, monkeypatch, mods):
    dlg = make(page=3)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: dlg._book))
    evt = FakeEvent(key=wx.WXK_RIGHT, **mods)
    dlg._on_char_hook(evt)
    assert dlg._book.GetSelection() == 3 and evt.skipped


@pytest.mark.parametrize("evt", [
    FakeEvent(key=wx.WXK_TAB), FakeEvent(key=wx.WXK_TAB, shift=True),
    FakeEvent(key=wx.WXK_TAB, ctrl=True, alt=True),
    FakeEvent(key=wx.WXK_RETURN), FakeEvent(key=wx.WXK_ESCAPE), FakeEvent(key=ord('A'))])
def test_other_keys_pass_through(make, evt):
    dlg = make(page=2)
    dlg._on_char_hook(evt)
    assert evt.skipped and dlg._book.GetSelection() == 2


# ---------------------------------------------------------------------------
# Accessibilité : libellé créé avant son champ (essai de 10d1)
# ---------------------------------------------------------------------------

LABELED = (wx.SpinCtrl, wx.Choice, wx.TextCtrl)


@pytest.mark.parametrize("tab", ["Général", "Audio", "Midi", "Projet"])
def test_each_field_follows_its_label(make, tab):
    children = list(make()._pages[tab].GetChildren())
    fields = [i for i, c in enumerate(children) if isinstance(c, LABELED)]
    assert fields
    for i in fields:
        assert i > 0 and isinstance(children[i - 1], wx.StaticText), \
            f"{tab} : champ n° {i} sans libellé juste avant"
        assert children[i - 1].GetLabel().endswith(":")


def test_audio_labels(make):
    children = list(make()._pages["Audio"].GetChildren())
    labels = [children[i - 1].GetLabel() for i, c in enumerate(children)
              if isinstance(c, wx.SpinCtrl)]
    assert labels == ["Gain FluidSynth (en dixièmes) :", "Gain sfizz (en dixièmes) :",
                      "Volume global d'un nouveau projet :",
                      "Pan global d'un nouveau projet :"]


def test_checkboxes_carry_their_label(make):
    dlg = make()
    for chk in (dlg._autoplay, dlg._explorer_autoplay, dlg._live_limiter,
                dlg._fluidsynth, dlg._sfizz):
        assert chk.GetLabel()


# ---------------------------------------------------------------------------
# _open_preferences / _apply_preferences
# ---------------------------------------------------------------------------

def _host(cfg):
    win = SimpleNamespace(_cfg=cfg, statuses=[])
    win._show_status = win.statuses.append
    win._apply_preferences = lambda changes, status=None: \
        ProjectMixin._apply_preferences(win, changes, status)
    win._apply_preferences_now = lambda changes: []    # effets : test_preferences_effects.py
    win.PREFS_AUDIO_OUT_KEYS = ProjectMixin.PREFS_AUDIO_OUT_KEYS   # sortie audio (11b1)
    win.PREFS_MIDI_KEYS = ProjectMixin.PREFS_MIDI_KEYS             # ports MIDI (11f1)
    return win


def test_apply_preferences_writes_and_announces(tmp_path):
    cfg = _cfg(tmp_path)
    win = _host(cfg)
    assert ProjectMixin._apply_preferences(win, {"autoplay": False, "startup": "new"}) is True
    with open(cfg.prefs_path, encoding="utf-8") as f:
        assert json.load(f) == {"autoplay": False, "startup": "new"}
    assert win.statuses == ["Préférences enregistrées (2 réglages)"]
    ProjectMixin._apply_preferences(win, {"sfizz": False})
    assert win.statuses[-1] == "Préférences enregistrées (1 réglage)"


def test_apply_preferences_error_announced(tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("x")
    cfg = AppConfig(str(tmp_path), prefs_path=str(blocker / "sous" / "p.json"))
    win = _host(cfg)
    assert ProjectMixin._apply_preferences(win, {"autoplay": False}) is False
    assert win.statuses[0].startswith("ERREUR Préférences : ")


def test_apply_preferences_uses_given_status(tmp_path):
    win = _host(_cfg(tmp_path))
    said = []
    ProjectMixin._apply_preferences(win, {"autoplay": False}, said.append)
    assert said == ["Préférences enregistrées (1 réglage)"] and win.statuses == []


class _ShownDialog:
    """Remplace PreferencesDialog : retient ses arguments, simule Ok."""
    last = None

    def __init__(self, parent, cfg, on_apply=None, page=0, hardware=None):
        _ShownDialog.last = self
        self.parent, self.cfg, self.on_apply = parent, cfg, on_apply
        self.page, self.hardware = page, hardware
        self.destroyed = False
    def ShowModal(self):
        self.on_apply({"autoplay": False})
        return wx.ID_OK
    def Destroy(self):
        self.destroyed = True


def test_open_preferences_from_main_window(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "PreferencesDialog", _ShownDialog)
    win = _host(_cfg(tmp_path))
    ProjectMixin._open_preferences(win)
    dlg = _ShownDialog.last
    assert dlg.parent is win and dlg.cfg is win._cfg and dlg.destroyed
    assert win.statuses == ["Préférences enregistrées (1 réglage)"]
    assert win._cfg.autoplay is False


def test_open_preferences_from_another_window(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "PreferencesDialog", _ShownDialog)
    win = _host(_cfg(tmp_path))
    editor, said = object(), []
    ProjectMixin._open_preferences(win, parent=editor, status=said.append)
    assert _ShownDialog.last.parent is editor
    assert said == ["Préférences enregistrées (1 réglage)"] and win.statuses == []


def test_open_preferences_destroys_on_error(tmp_path, monkeypatch):
    class Boom(_ShownDialog):
        def ShowModal(self):
            raise RuntimeError("boum")
    monkeypatch.setattr(dp, "PreferencesDialog", Boom)
    with pytest.raises(RuntimeError):
        ProjectMixin._open_preferences(_host(_cfg(tmp_path)))
    assert _ShownDialog.last.destroyed


# ---------------------------------------------------------------------------
# Alt+Shift+P dans les trois fenêtres (P3)
# ---------------------------------------------------------------------------

def test_alt_shift_p_main_window():
    win = FakeWindow()          # wx.App de la session (make_km la détruirait)
    km = KeyManager(win)
    calls = []
    win._open_preferences = lambda: calls.append("prefs")
    win._player._pattern.gen_pattern = lambda t: calls.append("aléatoire")
    km.handle(FakeEvent(key=ord('P'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('P'), ukey=ord('p'), alt=True, shift=True))
    assert calls == ["prefs", "prefs"]


def test_alt_p_without_shift_does_not_open():
    win = FakeWindow()
    km = KeyManager(win)
    calls = []
    win._open_preferences = lambda: calls.append("prefs")
    km.handle(FakeEvent(key=ord('P'), alt=True))
    km.handle(FakeEvent(key=ord('P'), ctrl=True, alt=True, shift=True))
    assert calls == []


class _Parent:
    def __init__(self):
        self.calls = []
        self._key_manager = SimpleNamespace(handle_transport=lambda evt: False)
    def _open_preferences(self, parent=None, status=None):
        self.calls.append((parent, status))


def test_alt_shift_p_midi_editor():
    ed = SimpleNamespace(_parent=_Parent(), _set_status=lambda m: None)
    evt = FakeEvent(key=ord('P'), alt=True, shift=True)
    mew.MidiEditorWindow._on_key(ed, evt)
    assert ed._parent.calls == [(ed, ed._set_status)]
    assert not evt.skipped


def test_alt_shift_p_song_window():
    stub = SimpleNamespace(_parent=_Parent(), _cur_song_idx=0, _set_status=lambda m: None)
    evt = FakeEvent(key=ord('P'), ukey=ord('p'), alt=True, shift=True)
    SongWindow._on_key(stub, evt)
    assert stub._parent.calls == [(stub, stub._set_status)]
    assert not evt.skipped


def test_song_window_p_still_plays():
    stub = SimpleNamespace(_parent=_Parent(), _cur_song_idx=2, _set_status=lambda m: None)
    played = []
    stub._parent._song_play_pause = played.append
    SongWindow._on_key(stub, FakeEvent(key=ord('P')))
    assert played == [2] and stub._parent.calls == []
