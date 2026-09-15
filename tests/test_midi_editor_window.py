#python3
"""
    File: tests/test_midi_editor_window.py
    Tests unitaires — MidiEditorWindow._toggle_track_solo/_toggle_track_mute
    (Phase 6 étape 7c). Utilise un objet factice (duck-typing) au lieu d'un
    vrai wx.Frame : ces méthodes sont de la pure orchestration (get_effective_tracks
    + TrackRouter.toggle_* + refresh + status), sans logique wx propre à tester.
    Date: Fri, 17/07/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ui.midi_editor_window as mew
from track_editor import TrackEditor


class _FakeStatusCtrl:
    def __init__(self):
        self.last = None

    def SetString(self, idx, msg):
        self.last = msg


class _FakeRouter:
    def __init__(self, num_tracks=8):
        self._mutes = [False] * num_tracks
        self._solos = [False] * num_tracks

    def toggle_track_mute(self, track_idx):
        self._mutes[track_idx] = not self._mutes[track_idx]
        return self._mutes[track_idx]

    def toggle_track_solo(self, track_idx):
        self._solos[track_idx] = not self._solos[track_idx]
        return self._solos[track_idx]


class _FakePlayer:
    def __init__(self, cur_track=0):
        self._cur_track = cur_track


class _FakeParent:
    def __init__(self):
        self._track_editor = TrackEditor()
        self._player       = _FakePlayer()
        self._router       = _FakeRouter()
        self.refresh_calls = 0

    def _refresh_track_list(self):
        self.refresh_calls += 1


class _FakeMidiEditorWindow:
    """Objet minimal exposant les vraies méthodes de MidiEditorWindow."""
    _set_status          = mew.MidiEditorWindow._set_status
    _toggle_track_solo   = mew.MidiEditorWindow._toggle_track_solo
    _toggle_track_mute   = mew.MidiEditorWindow._toggle_track_mute

    def __init__(self):
        self._parent      = _FakeParent()
        self._status_ctrl = _FakeStatusCtrl()


# ---------------------------------------------------------------------------
# Solo — piste courante (pas de multi-sélection)
# ---------------------------------------------------------------------------

def test_toggle_solo_current_track_on():
    win = _FakeMidiEditorWindow()
    win._parent._player._cur_track = 2
    win._toggle_track_solo()
    assert win._parent._router._solos == [False, False, True, False, False, False, False, False]
    assert win._status_ctrl.last == "Piste 3: Solo On"
    assert win._parent.refresh_calls == 1


def test_toggle_solo_current_track_off_on_second_call():
    win = _FakeMidiEditorWindow()
    win._toggle_track_solo()
    win._toggle_track_solo()
    assert win._parent._router._solos[0] is False
    assert win._status_ctrl.last == "Piste 1: Solo Off"


# ---------------------------------------------------------------------------
# Solo — pistes sélectionnées (multi-sélection active)
# ---------------------------------------------------------------------------

def test_toggle_solo_multi_selection():
    win = _FakeMidiEditorWindow()
    te = win._parent._track_editor
    te.select_one(0)
    te.toggle_track(2)   # sélection = {0, 2}
    win._toggle_track_solo()
    assert win._parent._router._solos[0] is True
    assert win._parent._router._solos[2] is True
    assert win._parent._router._solos[1] is False
    assert win._status_ctrl.last == "Pistes 1, 3: Solo basculé"


# ---------------------------------------------------------------------------
# Mute — piste courante et multi-sélection
# ---------------------------------------------------------------------------

def test_toggle_mute_current_track_on():
    win = _FakeMidiEditorWindow()
    win._parent._player._cur_track = 1
    win._toggle_track_mute()
    assert win._parent._router._mutes[1] is True
    assert win._status_ctrl.last == "Piste 2: Mute On"
    assert win._parent.refresh_calls == 1


def test_toggle_mute_multi_selection():
    win = _FakeMidiEditorWindow()
    te = win._parent._track_editor
    te.select_one(1)
    te.toggle_track(3)   # sélection = {1, 3}
    win._toggle_track_mute()
    assert win._parent._router._mutes[1] is True
    assert win._parent._router._mutes[3] is True
    assert win._status_ctrl.last == "Pistes 2, 4: Mute basculé"


def test_toggle_mute_and_solo_are_independent():
    win = _FakeMidiEditorWindow()
    win._toggle_track_mute()
    win._toggle_track_solo()
    assert win._parent._router._mutes[0] is True
    assert win._parent._router._solos[0] is True


# ---------------------------------------------------------------------------
# _event_label — Ctrl+1 (MODE_NOTES) garde l'ancien format ; Ctrl+2 (MODE_ALL)
# utilise le nouveau format "index: position, canal, type, numéro, val1, val2"
# (décidé avec l'utilisateur le 2026-09-15 : canal = numéro de piste, Bend
# inchangé, vélocité conservée en plus pour les notes — voir
# project_event_list_window_todo).
# ---------------------------------------------------------------------------

from rack import InstrumentType
from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH
from synth_engine import midi_to_note_name


class _FakeLabelPattern:
    def __init__(self, num_steps=16, num_beats=4):
        self._num_steps = num_steps
        self._num_beats = num_beats


class _FakeLabelPlayer:
    def __init__(self):
        self._pattern = _FakeLabelPattern()


class _FakeSlot:
    def __init__(self, type_):
        self.type = type_


class _FakeLabelRouter:
    def __init__(self, slot_type=InstrumentType.SYNTH, kb_notes_input=None):
        self.kb_notes_input = kb_notes_input or []

    def slot_for_track(self, track_idx):
        return 0


class _FakeLabelRack:
    def __init__(self, slot_type=InstrumentType.SYNTH):
        self._slot = _FakeSlot(slot_type)

    def get_slot(self, slot_idx):
        return self._slot


class _FakeLabelParent:
    def __init__(self, slot_type=InstrumentType.SYNTH, kb_notes_input=None):
        self._player = _FakeLabelPlayer()
        self._router = _FakeLabelRouter(slot_type, kb_notes_input)
        self._rack   = _FakeLabelRack(slot_type)


class _FakeEventLabelWindow:
    """Objet minimal exposant les vraies méthodes de formatage de MidiEditorWindow."""
    MODE_NOTES           = mew.MidiEditorWindow.MODE_NOTES
    MODE_ALL             = mew.MidiEditorWindow.MODE_ALL
    _event_label         = mew.MidiEditorWindow._event_label
    _event_label_notes   = mew.MidiEditorWindow._event_label_notes
    _event_label_all     = mew.MidiEditorWindow._event_label_all
    _event_pitch_number  = mew.MidiEditorWindow._event_pitch_number
    _event_note_name     = mew.MidiEditorWindow._event_note_name
    _bbt_str             = mew.MidiEditorWindow._bbt_str
    _pad_name            = lambda self, pad: f"Pad{pad+1:02d}"

    def __init__(self, view_mode=None, slot_type=InstrumentType.SYNTH, kb_notes_input=None):
        self._parent    = _FakeLabelParent(slot_type, kb_notes_input)
        self._view_mode = self.MODE_ALL if view_mode is None else view_mode


def _note_ev(track=0, pad=60, vel=100, dur=500, etype=ETYPE_PATCH):
    return {"type": "note", "etype": etype, "track": track, "bar": 0, "step": 0,
            "pad": pad, "vel": vel, "dur": dur}


def test_event_label_mode_notes_keeps_old_format():
    win = _FakeEventLabelWindow(view_mode=mew.MidiEditorWindow.MODE_NOTES)
    ev  = {"type": "note", "etype": ETYPE_GRID, "track": 0, "bar": 0, "step": 0,
           "pad": 3, "vel": 100, "dur": 500}
    label = win._event_label(0, ev)
    assert label == win._event_label_notes(ev)
    assert "Canal" not in label   # ancien format : pas de champ "Canal"


def test_event_label_mode_all_uses_new_format():
    win = _FakeEventLabelWindow(view_mode=mew.MidiEditorWindow.MODE_ALL)
    ev  = _note_ev()
    assert win._event_label(0, ev) == win._event_label_all(0, ev)


def test_event_label_all_note_patch_format():
    win  = _FakeEventLabelWindow()
    ev   = _note_ev(track=0, pad=60, vel=100, dur=500)
    name = midi_to_note_name(60)
    assert win._event_label_all(0, ev) == \
        f"    1: 1:1:1, Canal 1, Note, 60 ({name}), Durée 500ms, Vel 100"


def test_event_label_all_note_selected_marks_line():
    win = _FakeEventLabelWindow()
    ev  = _note_ev()
    assert win._event_label_all(0, ev, selected=True).startswith("[*] 1: ")


def test_event_label_all_note_canal_is_track_number_1based():
    win = _FakeEventLabelWindow()
    ev  = _note_ev(track=4)
    assert "Canal 5" in win._event_label_all(0, ev)


def test_event_label_all_note_index_is_list_position():
    win = _FakeEventLabelWindow()
    ev  = _note_ev()
    assert win._event_label_all(3, ev).strip().startswith("4:")


def test_event_label_all_mod_cc_format():
    win = _FakeEventLabelWindow()
    ev  = {"type": "mod", "track": 1, "bar": 0, "step": 0, "value": 90}
    assert win._event_label_all(2, ev) == "    3: 1:1:1, Canal 2, CC, Numéro 1, Valeur 90"


def test_event_label_all_bend_format_unchanged():
    win = _FakeEventLabelWindow()
    ev  = {"type": "bend", "track": 0, "bar": 0, "step": 0, "value": 500}
    assert win._event_label_all(0, ev) == "    1:1:1  Tr01  Bend:+500"


def test_event_pitch_number_patch_is_raw_midi_note():
    win = _FakeEventLabelWindow()
    ev  = {"etype": ETYPE_PATCH, "pad": 60, "track": 0}
    assert win._event_pitch_number(ev) == 60


def test_event_pitch_number_kit_is_pad_index_1based():
    win = _FakeEventLabelWindow()
    ev  = {"etype": ETYPE_KIT, "pad": 3, "track": 0}
    assert win._event_pitch_number(ev) == 4


def test_event_pitch_number_grid_synth_resolves_real_midi_note():
    win = _FakeEventLabelWindow(slot_type=InstrumentType.SYNTH, kb_notes_input=[36, 38, 40])
    ev  = {"etype": ETYPE_GRID, "pad": 1, "track": 0}
    assert win._event_pitch_number(ev) == 38


def test_event_pitch_number_grid_kit_is_pad_index_1based():
    win = _FakeEventLabelWindow(slot_type=InstrumentType.KIT)
    ev  = {"etype": ETYPE_GRID, "pad": 2, "track": 0}
    assert win._event_pitch_number(ev) == 3


# ---------------------------------------------------------------------------
# Grille courante (étape 7d) — _grid_idx vit sur le player, pas sur Pattern
# (régression : une version précédente lisait/écrivait _parent._player._pattern._grid_idx)
# ---------------------------------------------------------------------------

class _FakeGridPattern:
    def __init__(self, num_steps=16, num_beats=4, bpm=100):
        self._num_steps = num_steps
        self._num_beats = num_beats
        self._bpm       = bpm


class _FakeGridPlayer:
    def __init__(self, grid_idx):
        self._pattern  = _FakeGridPattern()
        self._grid_idx = grid_idx


class _FakeGridParent:
    def __init__(self, grid_idx):
        self._player     = _FakeGridPlayer(grid_idx)
        self.undo_titles = []

    def _add_undo(self, title):
        self.undo_titles.append(title)

    def _pop_last_undo(self):
        self.undo_titles.pop()


class _FakeGridWindow:
    """Objet minimal exposant les méthodes de grille de MidiEditorWindow."""
    _set_status       = mew.MidiEditorWindow._set_status
    _add_undo         = mew.MidiEditorWindow._add_undo
    _grid_value_steps = mew.MidiEditorWindow._grid_value_steps
    _grid_value_ms    = mew.MidiEditorWindow._grid_value_ms
    _show_grid_value  = mew.MidiEditorWindow._show_grid_value
    _change_grid_idx  = mew.MidiEditorWindow._change_grid_idx
    _SNAP_NOTE_NAMES  = mew.MidiEditorWindow._SNAP_NOTE_NAMES

    def __init__(self, grid_idx):
        self._parent      = _FakeGridParent(grid_idx)
        self._status_ctrl = _FakeStatusCtrl()


def test_grid_value_steps_reads_player_grid_idx_not_pattern():
    from pattern import Pattern
    win = _FakeGridWindow(grid_idx=10)   # "1/16"
    assert win._grid_value_steps() == Pattern.grid_step_size(10, 16)


def test_show_grid_value_reports_current_grid_and_note_name():
    win = _FakeGridWindow(grid_idx=10)   # "1/16" → snap 16 → Double croche
    win._show_grid_value()
    assert win._status_ctrl.last == "Grille: 1/16, Double croche"


def test_change_grid_idx_updates_player_not_pattern():
    win = _FakeGridWindow(grid_idx=10)
    win._change_grid_idx(1)
    assert win._parent._player._grid_idx == 11
    assert not hasattr(win._parent._player._pattern, "_grid_idx")
    assert win._parent.undo_titles == ["Grille : 1/16 → 1/24"]


def test_change_grid_idx_clamped_at_upper_bound():
    from pattern import Pattern
    win = _FakeGridWindow(grid_idx=len(Pattern.GRID_RESOLUTIONS) - 1)
    win._change_grid_idx(1)
    assert win._status_ctrl.last == "Grille: déjà à la borne"
    assert win._parent.undo_titles == []


def test_change_grid_idx_clamped_at_lower_bound():
    win = _FakeGridWindow(grid_idx=0)
    win._change_grid_idx(-1)
    assert win._status_ctrl.last == "Grille: déjà à la borne"
    assert win._parent.undo_titles == []


# ---------------------------------------------------------------------------
# Filtre d'événements MIDI (étape 8a-8/8a-10) — _apply_filter_result()
# ---------------------------------------------------------------------------

class _FakeFilterPlayer:
    def __init__(self):
        self._event_filter_state = None


class _FakeFilterParent:
    def __init__(self):
        self._player = _FakeFilterPlayer()


class _FakeFilterWindow:
    """Objet minimal exposant _apply_filter_result ; _refresh_labels et
    _sync_lims_from_selection sont des fakes (leur logique propre est déjà
    couverte par test_select_all/test_deselect_all)."""
    _set_status          = mew.MidiEditorWindow._set_status
    _apply_filter_result = mew.MidiEditorWindow._apply_filter_result

    def __init__(self):
        self._parent           = _FakeFilterParent()
        self._status_ctrl      = _FakeStatusCtrl()
        self._events           = [1, 2, 3, 4]   # contenu peu importe, seuls les indices comptent
        self._selected_indices = set()
        self.refresh_calls     = 0
        self.sync_calls        = 0

    def _refresh_labels(self):
        self.refresh_calls += 1

    def _sync_lims_from_selection(self):
        self.sync_calls += 1


def test_apply_filter_result_apply_replaces_selection():
    win = _FakeFilterWindow()
    win._selected_indices = {0}
    criteria = {"etype_filter": "note"}
    win._apply_filter_result("apply", {1, 2}, criteria)
    assert win._selected_indices == {1, 2}
    assert win.refresh_calls == 1
    assert win.sync_calls == 1
    assert win._parent._player._event_filter_state is criteria
    assert "2 événement" in win._status_ctrl.last


def test_apply_filter_result_add_unions_selection():
    win = _FakeFilterWindow()
    win._selected_indices = {0}
    win._apply_filter_result("add", {1, 2}, {"etype_filter": "note"})
    assert win._selected_indices == {0, 1, 2}


def test_apply_filter_result_remove_subtracts_selection():
    win = _FakeFilterWindow()
    win._selected_indices = {0, 1, 2}
    win._apply_filter_result("remove", {1}, {"etype_filter": "note"})
    assert win._selected_indices == {0, 2}


def test_apply_filter_result_reset_sel_clears_selection_no_persist():
    win = _FakeFilterWindow()
    win._selected_indices = {0, 1, 2}
    win._apply_filter_result("reset_sel", set(), None)
    assert win._selected_indices == set()
    assert win._parent._player._event_filter_state is None


def test_apply_filter_result_reset_sel_does_not_overwrite_persisted_state():
    win = _FakeFilterWindow()
    prev_state = {"etype_filter": "note"}
    win._parent._player._event_filter_state = prev_state
    win._apply_filter_result("reset_sel", set(), None)
    assert win._parent._player._event_filter_state is prev_state


def test_apply_filter_result_always_calls_refresh_and_sync():
    win = _FakeFilterWindow()
    for action in ("apply", "add", "remove", "reset_sel"):
        win._apply_filter_result(action, set(), None)
    assert win.refresh_calls == 4
    assert win.sync_calls == 4


# ---------------------------------------------------------------------------
# Filtre d'événements MIDI — Ctrl+Shift+F dans _on_key
# ---------------------------------------------------------------------------

class _FakeFilterKeyEvent:
    def __init__(self, key, ctrl=False, shift=False, alt=False):
        self._key   = key
        self._ctrl  = ctrl
        self._shift = shift
        self._alt   = alt
        self.skipped = False

    def GetKeyCode(self):    return self._key
    def GetUnicodeKey(self): return self._key
    def ControlDown(self):   return self._ctrl
    def ShiftDown(self):     return self._shift
    def AltDown(self):       return self._alt
    def Skip(self):          self.skipped = True


class _FakeKeyManager:
    def handle_transport(self, evt):
        return False   # aucune touche de transport dans ces tests


class _FakeKeyParent:
    def __init__(self):
        self._key_manager = _FakeKeyManager()


class _FakeKeyWindow:
    """Objet minimal exposant _on_key ; toutes les branches précédant
    Ctrl+Shift+F ne testent que evt.*Down()/GetKeyCode() (aucun attribut
    self.* requis avant notre bloc). Après notre bloc, seul le transport
    partagé (_parent._key_manager.handle_transport, stubé à False ici) est
    consulté avant evt.Skip()."""
    _on_key = mew.MidiEditorWindow._on_key

    def __init__(self):
        self._parent = _FakeKeyParent()
        self.filter_dialog_calls = 0

    def _filter_dialog(self):
        self.filter_dialog_calls += 1


def test_on_key_ctrl_shift_f_opens_filter_dialog():
    win = _FakeKeyWindow()
    evt = _FakeFilterKeyEvent(key=ord('F'), ctrl=True, shift=True)
    win._on_key(evt)
    assert win.filter_dialog_calls == 1
    assert evt.skipped is False


def test_on_key_ctrl_f_without_shift_does_not_open_filter_dialog():
    """Ctrl+F (sans Shift) est un raccourci distinct (Doubler pattern, côté
    fenêtre principale) ; l'éditeur MIDI ne doit pas réagir à Ctrl+F seul."""
    win = _FakeKeyWindow()
    evt = _FakeFilterKeyEvent(key=ord('F'), ctrl=True, shift=False)
    win._on_key(evt)
    assert win.filter_dialog_calls == 0
    assert evt.skipped is True
