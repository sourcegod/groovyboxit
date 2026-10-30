#python3
"""
    File: tests/test_tempo_dialog.py
    Tests de la liste des tempos (Phase 7 étape 19g1, docs/DESIGN.md § 19a1
    T8, T9, § 19d2 R3, avancement 19f1) : opérations du player (insérer,
    modifier selon trois portées, supprimer), TempoMixin (Undo, statut,
    champ BPM, éditeur), dialogue Tempo et dialogue d'édition ouverts par le
    chemin de l'appli (vrai Pattern : steps_per_beat() rend un float, que
    wx.SpinCtrl refusait), Entrée / Espace / Suppr, lignes Tempo de la liste
    des événements (affichage, ordre, suppression, filtre, Entrée), raccourcis
    Alt+Shift+T.
    Tap Tempo et case Click du dialogue (Phase 7 étape 19j1, ajout 19i1).
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import ui.dialogs_tempo as dt
import ui.midi_editor_window as mew
from pattern import Pattern, TapeEvent, ETYPE_PATCH
from player.drum_player import DrumPlayer
from midi.midi_editor import MidiEditor
from ui.mw_tempo import TempoMixin
from ui.main_window import MainWindow
from test_key_manager import make_km, FakeEvent, teardown

RECENT, SET_ALL, SCALE_ALL = DrumPlayer.SCOPE_RECENT, DrumPlayer.SCOPE_SET_ALL, \
    DrumPlayer.SCOPE_SCALE_ALL


def _player(bpm=92, changes=((16, 94), (32, 40)), bars=4):
    pl = DrumPlayer()
    pl._pattern._num_bars = bars
    pl.set_bpm(bpm)
    pl._pattern.set_tempo_changes(changes)
    return pl


@pytest.fixture
def app():
    """wx.App propre au test, comme les autres tests de dialogues (la
    wx.App de session de conftest peut déjà être détruite). Toutes les
    fenêtres sont détruites avant l'application : un dialogue survivant
    faisait planter Python à la sortie de la suite complète."""
    a = wx.App(False)
    frame = wx.Frame(None)
    yield frame
    for w in wx.GetTopLevelWindows():
        w.Destroy()
    a.Destroy()


# ---------------------------------------------------------------------------
# Opérations du player
# ---------------------------------------------------------------------------

def test_tempo_items_start_then_changes():
    assert _player().tempo_items() == [(-1, 0, 92), (0, 16, 94), (1, 32, 40)]


def test_insert_tempo():
    pl = _player()
    assert pl.insert_tempo(24, 70)
    assert pl.tempo_items()[2] == (1, 24, 70)


def test_insert_tempo_same_position_replaces():
    pl = _player()
    assert pl.insert_tempo(16, 60)
    assert pl._pattern._tempo_changes == [(16, 60), (32, 40)]


def test_insert_tempo_at_start_changes_start():
    pl = _player()
    assert pl.insert_tempo(0, 80)
    assert pl.bpm == 80 and pl._pattern._tempo_changes == [(16, 94), (32, 40)]


def test_insert_redundant_tempo_changes_nothing():
    pl = _player()
    assert not pl.insert_tempo(20, 94)            # égal au tempo en vigueur
    assert pl._pattern._tempo_changes == [(16, 94), (32, 40)]


def test_modify_recent_moves_and_changes_one():
    pl = _player()
    assert pl.modify_tempo(0, 20, 47, RECENT)
    assert pl.tempo_items() == [(-1, 0, 92), (0, 20, 47), (1, 32, 40)]


def test_modify_recent_start_tempo():
    pl = _player()
    assert pl.modify_tempo(-1, 0, 100, RECENT)
    assert pl.bpm == 100 and pl._pattern._bpm == 100
    assert pl._pattern._tempo_changes == [(16, 94), (32, 40)]


def test_modify_recent_moved_to_start_becomes_start():
    pl = _player()
    pl.modify_tempo(0, 0, 70, RECENT)
    assert pl.bpm == 70 and pl._pattern._tempo_changes == [(32, 40)]


def test_modify_set_all_leaves_single_tempo():
    pl = _player()
    assert pl.modify_tempo(1, 32, 92, SET_ALL)
    assert pl.tempo_items() == [(-1, 0, 92)]


def test_modify_scale_all_proportionally():
    pl = _player()
    assert pl.modify_tempo(0, 16, 47, SCALE_ALL)
    assert pl.tempo_items() == [(-1, 0, 46), (0, 16, 47), (1, 32, 20)]


def test_modify_unchanged_returns_false():
    pl = _player()
    assert not pl.modify_tempo(0, 16, 94, RECENT)
    assert not pl.modify_tempo(1, 32, 40, SCALE_ALL)


def test_delete_tempo():
    pl = _player()
    assert pl.delete_tempo(0)
    assert pl._pattern._tempo_changes == [(32, 40)]
    assert not pl.delete_tempo(-1) and not pl.delete_tempo(5)


def test_tempo_ops_keep_position_while_playing():
    import time
    pl = _player(changes=())
    pl.playing = True
    pl._cur_lp_start, pl._cur_loop_steps = 0, 0
    pl._measure_start = time.perf_counter() - 1.0
    pl.insert_tempo(40, 60)
    assert pl._resync_offset is not None


# ---------------------------------------------------------------------------
# TempoMixin (fenêtre principale)
# ---------------------------------------------------------------------------

class _Win(TempoMixin):
    def __init__(self, pl=None):
        self._player = pl or _player()
        self.undos, self.statuses, self.calls = [], [], []
        self._midi_editor_window = SimpleNamespace(refresh=lambda: self.calls.append("editeur"))
    def _add_undo(self, title):      self.undos.append(title)
    def _pop_last_undo(self):        self.undos.pop()
    def _show_status(self, msg):     self.statuses.append(msg)
    def _update_bpm_display(self):   self.calls.append("bpm")


def test_pos_str_and_item_label():
    win = _Win()
    assert win._tempo_pos_str(0) == "1:1:1"
    assert win._tempo_pos_str(16 * 20 + 5) == "21:2:2"
    assert win._tempo_pos_str(325.5) == "21:2:2"
    assert win._tempo_item_label(-1, 0, 92) == "1:1:1, 92 BPM, départ"
    assert win._tempo_item_label(0, 16, 46.5) == "2:1:1, 46,5 BPM"


def test_mixin_insert_with_undo():
    win = _Win()
    assert win._tempo_insert(16 * 20 + 4, 70)
    assert win.undos == ["Tempo : insérer 70 BPM à 21:2:1"]
    assert win.statuses == win.undos and win.calls == ["bpm", "editeur"]


def test_mixin_insert_unchanged_pops_undo():
    win = _Win()
    assert not win._tempo_insert(20, 94)
    assert win.undos == [] and "inchangé" in win.statuses[-1]


@pytest.mark.parametrize("scope, title", [
    (RECENT,    "Tempo : 47 BPM à 2:1:1"),
    (SET_ALL,   "Tempo : tous les tempos à 47 BPM"),
    (SCALE_ALL, "Tempo : tous les tempos proportionnellement, 47 BPM au lieu de 94"),
])
def test_mixin_modify_titles(scope, title):
    win = _Win()
    assert win._tempo_modify(0, 16, 47, scope)
    assert win.undos == [title]


def test_mixin_modify_unchanged_pops_undo():
    win = _Win()
    assert not win._tempo_modify(0, 16, 94, RECENT)
    assert win.undos == [] and win.statuses == ["Tempo : inchangé"]


def test_mixin_delete():
    win = _Win()
    assert win._tempo_delete(1)
    assert win.undos == ["Tempo : supprimer 40 BPM à 3:1:1"]
    assert win._player._pattern._tempo_changes == [(16, 94)]


def test_mixin_dialog_opens_and_updates_bpm_field(app, monkeypatch):
    shown = []
    monkeypatch.setattr(dt.TempoDialog, "ShowModal", lambda self: shown.append(self) or wx.ID_CANCEL)
    win = _Win()
    win._tempo_dialog(parent=app)
    assert len(shown) == 1 and win.calls == ["bpm"]


# ---------------------------------------------------------------------------
# Dialogue d'édition (chemin de l'appli)
# ---------------------------------------------------------------------------

def _owner(pl=None):
    win = _Win(pl)
    return win


def _tempo_dlg(app, pl=None):
    return dt.TempoDialog(app, _owner(pl))


def test_parse_bpm():
    assert dt.parse_bpm("92") == 92 and dt.parse_bpm(" 46,5 ") == 46.5
    assert dt.parse_bpm("46.25") == 46.25
    assert dt.parse_bpm("0") is None and dt.parse_bpm("601") is None
    assert dt.parse_bpm("abc") is None


def test_edit_dialog_opens_with_real_pattern(app):
    """19f1 : Pattern.steps_per_beat() rend un float ; le dialogue ne
    s'ouvrait pas (wx.SpinCtrl refuse un max float)."""
    pl = _player()
    pl._pattern._num_steps = 32
    assert isinstance(pl._pattern.steps_per_beat(), float)
    ed = _tempo_dlg(app, pl)._edit_dialog("Modifier", 40, 90, with_scope=True)
    assert (ed._bar.GetValue(), ed._beat.GetValue(), ed._tick.GetValue()) == (2, 2, 1)
    assert (ed._beat.GetMax(), ed._tick.GetMax()) == (4, 8)
    ed.Destroy()


def test_edit_dialog_keeps_fractional_position_unless_changed(app):
    ed = _tempo_dlg(app, _player(bars=36))._edit_dialog("Modifier", 325.5, 46.5, with_scope=True)
    assert ed.get_position() == 325.5 and ed.get_bpm() == 46.5
    ed._bar.SetValue(3)
    assert ed.get_position() == 2 * 16 + 4 + 1
    ed.Destroy()


def test_edit_dialog_scopes(app):
    ed = _tempo_dlg(app)._edit_dialog("Modifier", 16, 94, with_scope=True)
    assert ed._scope.GetCount() == 3
    assert [ed._scope.GetString(i) for i in range(3)] == dt.SCOPE_LABELS
    got = []
    for i in range(3):
        ed._scope.SetSelection(i)
        ed._update_position_enabled()
        got.append((ed.get_scope(), ed._bar.IsEnabled()))
    assert got == [(RECENT, True), (SET_ALL, False), (SCALE_ALL, False)]
    ed.Destroy()


def test_edit_dialog_without_scope_and_fixed_position(app):
    ed = _tempo_dlg(app)._edit_dialog("Insérer", 8, 92)
    assert ed._scope is None and ed.get_scope() == RECENT
    ed.Destroy()
    ed = _tempo_dlg(app)._edit_dialog("Modifier", 0, 92, position_fixed=True, with_scope=True)
    assert not ed._bar.IsEnabled() and not ed._tick.IsEnabled()
    ed.Destroy()


class _OkEvent:
    def __init__(self): self.skipped = False
    def Skip(self):     self.skipped = True


def test_edit_dialog_rejects_bad_bpm_and_start_position(app, monkeypatch):
    msgs = []
    monkeypatch.setattr(dt.wx, "MessageBox", lambda *a, **k: msgs.append(a[0]))
    ed = _tempo_dlg(app)._edit_dialog("Insérer", 8, 92)
    ed._bpm.SetValue("700")
    e = _OkEvent(); ed._on_ok(e)
    assert not e.skipped and "Tempo invalide" in msgs[-1]
    ed._bpm.SetValue("80")
    ed._bar.SetValue(1); ed._beat.SetValue(1); ed._tick.SetValue(1)
    e = _OkEvent(); ed._on_ok(e)
    assert not e.skipped and "départ" in msgs[-1]
    ed._tick.SetValue(2)
    e = _OkEvent(); ed._on_ok(e)
    assert e.skipped
    ed.Destroy()


# ---------------------------------------------------------------------------
# Dialogue Tempo : liste, boutons, clavier
# ---------------------------------------------------------------------------

def test_list_labels_and_selection_at_current_position(app):
    pl = _player()
    pl._resume_offset = 20.0
    dlg = _tempo_dlg(app, pl)
    assert [dlg._list.GetString(i) for i in range(3)] == \
        ["1:1:1, 92 BPM, départ", "2:1:1, 94 BPM", "3:1:1, 40 BPM"]
    assert dlg._list.GetSelection() == 1
    dlg.Destroy()


def _accept(monkeypatch, bpm, scope_idx=None, bar=None):
    """TempoEditDialog.ShowModal : saisit les valeurs puis Ok."""
    def show(self):
        self._bpm.SetValue(bpm)
        if bar is not None:
            self._bar.SetValue(bar)
        if scope_idx is not None:
            self._scope.SetSelection(scope_idx)
        return wx.ID_OK
    monkeypatch.setattr(dt.TempoEditDialog, "ShowModal", show)


def test_insert_button_flow(app, monkeypatch):
    pl = _player()
    pl._resume_offset = 40.0
    dlg = _tempo_dlg(app, pl)
    _accept(monkeypatch, "70")
    dlg.insert()
    assert pl._pattern._tempo_changes == [(16, 94), (32, 40), (40, 70)]
    assert dlg._list.GetStringSelection() == "3:3:1, 70 BPM"      # pas 40 = 32 + 2 temps
    assert dlg._owner.undos == ["Tempo : insérer 70 BPM à 3:3:1"]
    dlg.Destroy()


@pytest.mark.parametrize("scope_idx, expected", [
    (0, [(-1, 0, 92), (0, 16, 47), (1, 32, 40)]),
    (1, [(-1, 0, 47)]),
    (2, [(-1, 0, 46), (0, 16, 47), (1, 32, 20)]),
])
def test_modify_button_flow_three_scopes(app, monkeypatch, scope_idx, expected):
    pl = _player()
    dlg = _tempo_dlg(app, pl)
    dlg._list.SetSelection(1)
    _accept(monkeypatch, "47", scope_idx)
    dlg.modify()
    assert pl.tempo_items() == expected
    dlg.Destroy()


def test_modify_cancel_changes_nothing(app, monkeypatch):
    pl = _player()
    dlg = _tempo_dlg(app, pl)
    monkeypatch.setattr(dt.TempoEditDialog, "ShowModal", lambda self: wx.ID_CANCEL)
    dlg._list.SetSelection(1)
    dlg.modify()
    assert pl.tempo_items() == [(-1, 0, 92), (0, 16, 94), (1, 32, 40)]
    assert dlg._owner.undos == []
    dlg.Destroy()


def test_delete_button_flow_and_start_refused(app, monkeypatch):
    bells = []
    monkeypatch.setattr(dt.wx, "Bell", lambda: bells.append(True))
    pl = _player()
    dlg = _tempo_dlg(app, pl)
    dlg._list.SetSelection(0)
    dlg.delete()
    assert bells == [True] and pl._pattern._tempo_changes == [(16, 94), (32, 40)]
    assert dlg._owner.statuses[-1] == "Le tempo de départ ne se supprime pas"
    dlg._list.SetSelection(2)
    dlg.delete()
    assert pl._pattern._tempo_changes == [(16, 94)]
    dlg.Destroy()


class _Key:
    def __init__(self, k): self.k, self.skipped = k, False
    def GetKeyCode(self):  return self.k
    def Skip(self):        self.skipped = True


def _focus(monkeypatch, widget):
    """Focus simulé : afficher un vrai dialogue pour lui donner le focus
    faisait planter Python à la sortie de la suite complète."""
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: widget))


def test_enter_and_space_activate_focused_button(app, monkeypatch):
    """19f1 : EVT_CHAR_HOOK bloquait Entrée et Espace sur les boutons ; le
    dialogue les traite selon le bouton qui a le focus."""
    dlg = _tempo_dlg(app)
    calls = []
    dlg._actions = {btn: (lambda b=btn: calls.append(b.GetLabel())) for btn in dlg._actions}
    for btn in list(dlg._actions):
        _focus(monkeypatch, btn)
        for key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            e = _Key(key)
            dlg._on_char_hook(e)
            assert not e.skipped
    assert calls == [lbl for lbl in ("&Insérer…", "&Modifier…", "&Supprimer",
                                     "&Tap Tempo", "&Fermer")      # Tap Tempo : 19i1
                     for _ in range(3)]


def test_list_keys(app, monkeypatch):
    dlg = _tempo_dlg(app)
    calls = []
    monkeypatch.setattr(dlg, "modify", lambda: calls.append("modify"))
    monkeypatch.setattr(dlg, "delete", lambda: calls.append("delete"))
    _focus(monkeypatch, dlg._list)
    for key in (wx.WXK_RETURN, wx.WXK_DELETE):
        dlg._on_char_hook(_Key(key))
    arrow, space = _Key(wx.WXK_DOWN), _Key(wx.WXK_SPACE)
    dlg._on_char_hook(arrow)
    dlg._on_char_hook(space)
    assert calls == ["modify", "delete"] and arrow.skipped and space.skipped


def test_keys_elsewhere_left_to_native(app, monkeypatch):
    dlg = _tempo_dlg(app)
    _focus(monkeypatch, None)
    for key in (wx.WXK_RETURN, wx.WXK_SPACE, wx.WXK_DELETE):
        e = _Key(key)
        dlg._on_char_hook(e)
        assert e.skipped


# ---------------------------------------------------------------------------
# Liste des événements (Ctrl+2)
# ---------------------------------------------------------------------------

def _pattern_with_notes():
    p = Pattern()
    p._num_bars = 4
    p._bpm = 92
    p.set_tempo_changes([(16, 94), (32.5, 40)])
    p._tape[0].append(TapeEvent(ETYPE_PATCH, dur=100, payload={"note": 60, "vel": 90}, time=16))
    return p


def test_get_tempo_events():
    ev = MidiEditor().get_tempo_events(_pattern_with_notes())
    assert [(e["type"], e["track"], e["offset"], e["bpm"], e["tempo_idx"]) for e in ev] == \
        [("tempo", -1, 0, 92, -1), ("tempo", -1, 16, 94, 0), ("tempo", -1, 32.5, 40, 1)]


def test_get_tempo_events_limits():
    ev = MidiEditor().get_tempo_events(_pattern_with_notes(), lim_left=10, lim_right=32)
    assert [e["offset"] for e in ev] == [16, 32.5]          # pas 32 inclus, fraction comprise


def test_all_events_tempo_first_at_same_position_any_tracks():
    events = MidiEditor().get_all_events(_pattern_with_notes(), [3])
    assert [e["type"] for e in events] == ["tempo", "tempo", "tempo"]
    events = MidiEditor().get_all_events(_pattern_with_notes(), [0])
    assert [(e["offset"], e["type"]) for e in events][1:3] == [(16, "tempo"), (16, "note")]


def test_delete_tempo_event():
    me, p = MidiEditor(), _pattern_with_notes()
    ev = me.get_tempo_events(p)
    assert not me.delete_event(p, ev[0])                   # départ
    assert me.delete_event(p, ev[2])
    assert p._tempo_changes == [(16, 94)]
    assert not me.delete_event(p, ev[2])                   # déjà supprimé


def test_filter_tempo_type():
    me = MidiEditor()
    events = me.get_all_events(_pattern_with_notes(), [0])
    kept = me.filter_events(events, {"active": True, "etype_filter": "tempo"})
    assert sorted(events[i]["offset"] for i in kept) == [0, 16, 32.5]


class _FakeEd:
    _event_label_all = mew.MidiEditorWindow._event_label_all
    _bbt_str         = mew.MidiEditorWindow._bbt_str
    def __init__(self, pattern):
        self._parent = SimpleNamespace(_player=SimpleNamespace(_pattern=pattern))


def test_event_list_label():
    p = _pattern_with_notes()
    ed = _FakeEd(p)
    ev = MidiEditor().get_tempo_events(p)
    assert ed._event_label_all(0, ev[0]).strip() == "1: 1:1:1, Tempo, 92 BPM, départ"
    p.set_tempo_changes([(16, 46.5)])
    ev = MidiEditor().get_tempo_events(p)
    assert ed._event_label_all(1, ev[1]).strip() == "2: 2:1:1, Tempo, 46,5 BPM"


class _FakeDeleteEditor:
    _delete_event    = mew.MidiEditorWindow._delete_event
    _deleted_name    = staticmethod(mew.MidiEditorWindow._deleted_name)
    _DELETABLE_TYPES = mew.MidiEditorWindow._DELETABLE_TYPES

    def __init__(self, pattern):
        self.statuses, self.calls = [], []
        ed = self
        class Parent:
            _player = SimpleNamespace(_pattern=pattern, _compute_offsets=lambda: None)
            def _tempo_delete(self, idx):
                ed.calls.append(("tempo_delete", idx)); return True
            def _update_bpm_display(self):
                ed.calls.append("bpm")
            def _pop_last_undo(self): pass
        self._parent = Parent()
        self._midi_editor = MidiEditor()
        self._selected_indices = set()
        self._refresh()
    def _refresh(self):
        self._events = self._midi_editor.get_all_events(self._parent._player._pattern, [0])
    def _set_status(self, msg):   self.statuses.append(msg)
    def _add_undo(self, title):   self.calls.append(("undo", title))
    def _clear_selection(self):   self._selected_indices.clear()


def test_editor_delete_tempo_row_goes_through_main_window():
    ed = _FakeDeleteEditor(_pattern_with_notes())
    ed._midi_editor._cur_idx = 1                      # 2:1:1, Tempo 94
    ed._delete_event()
    assert ed.calls == [("tempo_delete", 0)] and ed.statuses == ["Tempo supprimé"]


def test_editor_delete_selection_with_tempo_updates_bpm_field():
    p = _pattern_with_notes()
    ed = _FakeDeleteEditor(p)
    ed._selected_indices = {0, 1, 2}                  # départ, tempo 94, note
    ed._delete_event()
    assert p._tempo_changes == [(32.5, 40)] and p._tape[0] == []
    assert "bpm" in ed.calls


class _EditorFrame(wx.Frame):
    """Vraie fenêtre (parent du dialogue) qui porte la méthode de l'éditeur."""
    _edit_tempo_dialog = mew.MidiEditorWindow._edit_tempo_dialog

    def __init__(self, frame, pattern):
        super().__init__(frame)
        self.calls, self._events = [], []
        ed = self
        class Parent:
            _player = SimpleNamespace(_pattern=pattern)
            def _tempo_modify(self, *a): ed.calls.append(a)
        self._parent = Parent()
    def _refresh(self):        pass
    def _navigate_to(self, i): pass


def test_editor_enter_on_tempo_row_opens_shared_dialog(app, monkeypatch):
    """Entrée sur une ligne Tempo : vrai TempoEditDialog (vrai Pattern),
    portée choisie transmise à la fenêtre principale."""
    p = _pattern_with_notes()
    _accept(monkeypatch, "47", scope_idx=2)
    ed = _EditorFrame(app, p)
    ed._edit_tempo_dialog(MidiEditor().get_tempo_events(p)[1])
    assert ed.calls == [(0, 16, 47.0, SCALE_ALL)]
    _accept(monkeypatch, "50", scope_idx=0, bar=3)
    ed._edit_tempo_dialog(MidiEditor().get_tempo_events(p)[1])
    assert ed.calls[-1] == (0, 32, 50.0, RECENT)
    ed.Destroy()


# ---------------------------------------------------------------------------
# Raccourcis Alt+Shift+T
# ---------------------------------------------------------------------------

def test_alt_shift_t_main_window():
    app_, win, km = make_km()
    calls = []
    win._tempo_dialog = lambda: calls.append("tempo")
    km.handle(FakeEvent(key=ord('T'), alt=True, shift=True))
    assert calls == ["tempo"]
    teardown(app_)


class _KeyEv:
    def __init__(self, key, ctrl=False, shift=False, alt=False):
        self._k, self._c, self._s, self._a = key, ctrl, shift, alt
        self.skipped = False
    def GetKeyCode(self):    return self._k
    def GetUnicodeKey(self): return self._k
    def ControlDown(self):   return self._c
    def ShiftDown(self):     return self._s
    def AltDown(self):       return self._a
    def Skip(self):          self.skipped = True


def test_alt_shift_t_midi_editor():
    calls = []
    class Ed:
        _on_key = mew.MidiEditorWindow._on_key
        def __init__(self):
            ed = self
            class Parent:
                def _tempo_dialog(self, parent=None): calls.append(("tempo", parent is ed))
                _key_manager = SimpleNamespace(handle_transport=lambda evt: False)
            self._parent = Parent()
        def _set_status(self, msg): pass
        def _refresh(self):         calls.append("refresh")
    Ed()._on_key(_KeyEv(ord('T'), shift=True, alt=True))
    assert calls == [("tempo", True), "refresh"]


# ---------------------------------------------------------------------------
# Tap Tempo et Click du dialogue (Phase 7 étape 19i1)
# ---------------------------------------------------------------------------

import metronome


class _Clock:
    """Horloge monotone factice du Tap Tempo."""
    def __init__(self):  self.now = 1000.0
    def __call__(self):  return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(metronome._time, "monotonic", c)
    return c


def _taps(win_or_dlg, clock, n, interval=0.5, idx=None):
    out = []
    for _ in range(n):
        clock.now += interval
        out.append(win_or_dlg.tap() if idx is None else win_or_dlg._tempo_tap(idx))
    return out


def test_mixin_tap_needs_four_taps_then_scales_all(clock):
    win = _Win()
    got = _taps(win, clock, 4, 0.5, idx=-1)               # 120 BPM
    assert got == [None, None, None, 120]
    assert win._player.tempo_items() == [(-1, 0, 120), (0, 16, 122.61), (1, 32, 52.17)]
    assert win.statuses[-1] == "Tap Tempo: 120 BPM"
    assert "bpm" in win.calls and "editeur" in win.calls


def test_mixin_tap_selected_tempo_takes_tapped_value(clock):
    win = _Win()
    _taps(win, clock, 4, 1.0, idx=1)                      # 40 → 60 BPM
    assert win._player.tempo_items() == [(-1, 0, 138), (0, 16, 141), (1, 32, 60)]


def test_mixin_tap_one_undo_per_series(clock):
    win = _Win()
    _taps(win, clock, 6, 0.5, idx=-1)
    assert win.undos == ["Tap Tempo (BPM: 92)"]
    clock.now += 3.0                                       # pause > 2 s : nouvelle série
    _taps(win, clock, 4, 0.6, idx=-1)
    assert win.undos == ["Tap Tempo (BPM: 92)", "Tap Tempo (BPM: 120)"]
    assert win._player.bpm == 100


def test_dialog_tap_button_label_and_list(app, clock):
    dlg = _tempo_dlg(app)
    dlg._list.SetSelection(0)
    _taps(dlg, clock, 3)
    assert dlg._tap_btn.GetLabel() == "&Tap Tempo"
    _taps(dlg, clock, 1)
    assert dlg._tap_btn.GetLabel() == "&Tap Tempo : 120 BPM"
    assert dlg._list.GetString(0) == "1:1:1, 120 BPM, départ"
    assert dlg._list.GetSelection() == 0


def test_dialog_tap_by_enter_or_space_on_button(app, clock, monkeypatch):
    dlg = _tempo_dlg(app)
    _focus(monkeypatch, dlg._tap_btn)
    for key in (wx.WXK_RETURN, wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_SPACE):
        clock.now += 0.5
        e = _Key(key)
        dlg._on_char_hook(e)
        assert not e.skipped
    assert dlg._owner._player.bpm == 120


class _ClickPlayer:
    """Remplace play_click / stop_click du vrai player (pas de thread)."""
    @staticmethod
    def patch(monkeypatch, pl, calls):
        def play():
            calls.append("on"); pl._metro.active = True
        def stop():
            calls.append("off"); pl._metro.active = False
        monkeypatch.setattr(pl, "play_click", play)
        monkeypatch.setattr(pl, "stop_click", stop)


def test_click_checkbox_reflects_state_at_opening(app):
    pl = _player()
    assert not _tempo_dlg(app, pl)._click_cb.GetValue()
    pl._metro.active = True
    assert _tempo_dlg(app, pl)._click_cb.GetValue()


def test_click_checkbox_toggles_like_c(app, monkeypatch):
    pl, calls = _player(), []
    _ClickPlayer.patch(monkeypatch, pl, calls)
    dlg = _tempo_dlg(app, pl)
    dlg._click_cb.SetValue(True)
    dlg.toggle_click()
    dlg._click_cb.SetValue(False)
    dlg.toggle_click()
    assert calls == ["on", "off"]
    assert dlg._owner.statuses[-2:] == ["Click: On", "Click: Off"]


def test_click_space_on_checkbox_handled_by_dialog(app, monkeypatch):
    """Même piège EVT_CHAR_HOOK que les boutons : Espace traité ici."""
    pl, calls = _player(), []
    _ClickPlayer.patch(monkeypatch, pl, calls)
    dlg = _tempo_dlg(app, pl)
    _focus(monkeypatch, dlg._click_cb)
    for _ in range(2):
        e = _Key(wx.WXK_SPACE)
        dlg._on_char_hook(e)
        assert not e.skipped
    assert calls == ["on", "off"] and not dlg._click_cb.GetValue()
    e = _Key(wx.WXK_RETURN)
    dlg._on_char_hook(e)
    assert e.skipped and calls == ["on", "off"]


def test_click_state_kept_when_dialog_closes(app, monkeypatch):
    pl, calls = _player(), []
    _ClickPlayer.patch(monkeypatch, pl, calls)
    dlg = _tempo_dlg(app, pl)
    dlg._click_cb.SetValue(True)
    dlg.toggle_click()
    dlg.Destroy()
    assert pl.clicking and calls == ["on"]
