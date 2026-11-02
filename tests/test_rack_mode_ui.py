"""
    File: tests/test_rack_mode_ui.py
    Mode Rack 16 canaux, interface (Phase 8 étape 5e1, tests de 5d1 ;
    docs/DESIGN.md § Phase 8 étape 5a, M2, M4, M7, M12, M14-M16) : case des
    propriétés du pattern et Undo, libellé des pistes, Ctrl+T, slot courant
    qui suit le canal, Program Change reçu, kit sans renommer les pads,
    propriétés de piste où le slot est le canal, changement de pattern.
    Date: Sun, 01/11/2026
    Author: Coolbrother
"""

import os
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import track_router as tr_mod
import ui.midi_handler_window as mh
from pattern import Pattern, TapeEvent, ETYPE_GRID, ETYPE_PATCH, bank_header, with_bank_header
from player.drum_player import DrumPlayer
from rack import Rack, InstrumentType
from track_router import TrackRouter
from ui.dialogs_properties import PatternPropertiesDialog, TrackPropertiesDialog
from ui.mw_pads import PadMixin
from ui.mw_patterns import PatternMixin
from ui.mw_tracks import TrackMixin
from test_bank_slot import FakeBankEngine, FakeSoundManager, FakeTimer, FakeSynthEngine

SF = "/fake/FluidR3_GM.sf2"
SYNTH, BANK, KIT = 1, 5, 9          # slots 2, 6 et 10 = canaux 2, 6 et 10


_APP = None


class _Synth(FakeSynthEngine):
    def stop_all_voices(self):
        pass


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """wx.App présente (d'autres fichiers détruisent la leur) ; pas de vrai
    Timer ni de vrai SynthEngine dans track_router."""
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", _Synth)


class _Evt:
    def Skip(self):
        pass


# ---------------------------------------------------------------------------
# Fenêtre factice : pistes, patterns et pads sur un vrai TrackRouter
# ---------------------------------------------------------------------------

class _Snd(FakeSoundManager):
    """Sons du kit : chargement noté, libellés du kit rendus."""

    def __init__(self):
        super().__init__()
        self.kit_path    = None
        self.loaded      = []
        self.mute_groups = [0] * 16
        self.gm_note_map = {}
        self.note_map    = {}

    def load_kit(self, path):
        self.loaded.append(path)
        self.kit_path = os.path.abspath(path)
        return [f"Kit pad {i + 1}" for i in range(16)], [""] * 16

    def load_sounds(self):
        self.kit_path = None


class _Silent:
    def stop_all(self):           pass
    def play_sound(self, *a):     pass
    def play_note(self, *a):      pass
    def play_metronome(self, *a): pass


class _RackWin(TrackMixin, PatternMixin, PadMixin):
    def __init__(self, rack_mode=True, kit_path=""):
        rack = Rack()
        rack.set_slot(SYNTH, InstrumentType.SYNTH, "Piano WAV", {"patch": "p"})
        rack.set_slot(BANK,  InstrumentType.BANK,  "FluidR3",   {"bank_slot": 0})
        rack.set_slot(KIT,   InstrumentType.KIT,   "808",       {"kit": kit_path})
        rack.set_bank_file(0, SF)
        self._rack   = rack
        self._snd    = _Snd()
        self.statuses, self.undos, self.labels = [], [], []
        self._router = TrackRouter(rack, "/fake", self._snd, lambda m: None,
                                   bank_engine=FakeBankEngine(), schedule=lambda *a: None)
        self._router._track_slots[:] = [BANK] * 16
        self._router.sync_bank_files()
        self._player = DrumPlayer(_Silent())
        self._player._pattern._rack_mode = rack_mode
        self._router.rack_mode = rack_mode
        self._pattern_list = [Pattern(), Pattern()]
        self._pattern_list[0]._rack_mode = rack_mode
        self._cur_pattern_idx = 0
        self._pattern_cache_dirty = set()
        self._cur_slot     = BANK
        self._slot_choice  = MagicMock()
        self._bpm_ctrl     = MagicMock()
        self._track_editor = SimpleNamespace(is_selected=lambda i: False)
        self._midi_editor_window = None

    def _refresh_track_list(self):
        self.labels = [self._track_label(i) for i in range(4)]

    def _refresh_grid(self):              pass
    def _refresh_pad_list(self):          pass
    def _refresh_pattern_listbox(self):   pass
    def _refresh_all_voice_display(self): pass
    def _play_toggle(self):               pass
    def _show_status(self, msg):          self.statuses.append(msg)
    def _add_undo(self, title):           self.undos.append(title)
    def _pop_last_undo(self):             self.undos.append("pop")


def _channels(win, channels):
    for t, ch in enumerate(channels):
        win._router._track_channels[t] = ch
        win._router._track_cur_channels[t] = ch


def _grid(t=0):
    return TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=t)


# ---------------------------------------------------------------------------
# Propriétés du pattern (M2)
# ---------------------------------------------------------------------------

def _pattern_dlg(rack_mode=False):
    frame = wx.Frame(None)
    dlg = PatternPropertiesDialog(frame, 0, "P", 0, 1, 16, True, 999,
                                  Pattern.VALID_RESOLUTIONS, rack_mode=rack_mode)
    return frame, dlg


def test_pattern_dialog_rack_checkbox():
    frame, dlg = _pattern_dlg()
    assert dlg._rack.GetLabel() == "Mode Rack 16 canaux (canal N → slot N)"
    assert dlg.get_rack_mode() is False
    dlg.Destroy()
    dlg = PatternPropertiesDialog(frame, 0, "P", 0, 1, 16, True, 999,
                                  Pattern.VALID_RESOLUTIONS, rack_mode=True)
    assert dlg.get_rack_mode() is True
    dlg._rack.SetValue(False)
    assert dlg.get_rack_mode() is False
    dlg.Destroy()
    frame.Destroy()


def test_pattern_dialog_rack_checkbox_after_loop_in_tab_order():
    frame, dlg = _pattern_dlg()
    children = list(dlg.GetChildren())
    assert children.index(dlg._rack) == children.index(dlg._loop) + 1
    assert children.index(dlg._rack) < children.index(dlg._actions)
    dlg.Destroy()
    frame.Destroy()


def _fake_pattern_dlg(rack_mode, action="Courant", num_bars=1, num_steps=16):
    class FakeDlg:
        def __init__(self, *a, **kw): FakeDlg.kwargs = kw
        def ShowModal(self):       return wx.ID_OK
        def get_name(self):        return ""
        def get_start_bar(self):   return 0
        def get_num_bars(self):    return num_bars
        def get_num_steps(self):   return num_steps
        def get_num_beats(self):   return 4
        def get_denominator(self): return 4
        def get_resolution(self):  return num_steps
        def get_tempo(self):       return None
        def get_looping(self):     return True
        def get_rack_mode(self):   return rack_mode
        def get_action(self):      return action
        def Destroy(self):         pass
    return FakeDlg


def _properties(win, fake):
    with patch("ui.mw_patterns.PatternPropertiesDialog", fake):
        win._pattern_properties_dialog()


def test_pattern_properties_passes_current_rack_mode():
    win = _RackWin(rack_mode=True)
    fake = _fake_pattern_dlg(True)
    _properties(win, fake)
    assert fake.kwargs["rack_mode"] is True


def test_pattern_properties_enables_rack_mode_with_its_undo():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(True))
    assert win.undos == ["Mode Rack pattern 01 : activé"]
    assert win._pattern_list[0]._rack_mode is True
    assert win._player._pattern._rack_mode is True
    assert win._router.rack_mode is True
    assert 0 in win._pattern_cache_dirty
    assert "Pattern 01: mode Rack 16 canaux activé — le canal N joue le slot N" in win.statuses


def test_pattern_properties_disables_rack_mode():
    win = _RackWin(rack_mode=True)
    _properties(win, _fake_pattern_dlg(False))
    assert win.undos == ["Mode Rack pattern 01 : désactivé"]
    assert win._router.rack_mode is False and win._pattern_list[0]._rack_mode is False
    assert "Pattern 01: mode Rack 16 canaux désactivé" in win.statuses


def test_pattern_properties_rack_mode_with_resize_keeps_resize_undo():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(True, num_bars=2))
    assert win.undos == ["Redimensionner pattern 01"]
    assert win._router.rack_mode is True and win._player._pattern._num_bars == 2


def test_pattern_properties_rack_mode_unchanged_does_nothing():
    win = _RackWin(rack_mode=False)
    _properties(win, _fake_pattern_dlg(False))
    assert win.undos == ["Redimensionner pattern 01"]
    assert win._router.rack_mode is False
    assert not any("mode Rack" in s for s in win.statuses)


def test_set_rack_mode_chases_and_follows_slot():
    win = _RackWin(rack_mode=False)
    _channels(win, [SYNTH])
    win._set_rack_mode(True)
    assert win._cur_slot == SYNTH
    win._slot_choice.SetSelection.assert_called_with(SYNTH)
    assert win.labels[0].startswith("  Track_01 - Canal 2 → Slot_02 Piano WAV")
    win._set_rack_mode(False)
    assert win._cur_slot == BANK                      # la piste retrouve son slot


# ---------------------------------------------------------------------------
# Libellés (M14)
# ---------------------------------------------------------------------------

def test_rack_channel_desc():
    win = _RackWin()
    assert win._rack_channel_desc(SYNTH) == "Slot_02 Piano WAV"
    assert win._rack_channel_desc(3) == "Slot_04 vide → banque GM (Slot_06 FluidR3)"
    win._rack.clear_slot(BANK)
    assert win._rack_channel_desc(3) == "Slot_04 vide, muet"


def test_track_label_in_rack_mode():
    win = _RackWin()
    _channels(win, [SYNTH, 3, KIT])
    win._player.voice_manager.set_name(1, "Basse")
    labels = [win._track_label(t) for t in range(3)]
    assert labels[0] == "  Track_01 - Canal 2 → Slot_02 Piano WAV"
    assert labels[1].startswith("  Track_02 (Basse) - Canal 4 → Slot_04 vide → banque GM "
                                "(Slot_06 FluidR3) - ")      # + nom du preset du canal
    assert labels[2] == "  Track_03 - Canal 10 → Slot_10 808"


def test_track_label_follows_current_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._router._track_cur_channels[0] = KIT          # Program Change passé
    assert win._track_label(0) == "  Track_01 - Canal 10 → Slot_10 808"


def test_track_label_normal_mode_unchanged():
    win = _RackWin(rack_mode=False)
    win._router._track_slots[0] = SYNTH
    assert win._track_label(0) == "  Track_01 - Slot_02 - Piano WAV"


def test_track_label_keeps_mute_flag_in_rack_mode():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._router.toggle_track_mute(0)
    assert win._track_label(0).endswith(" [M]")


# ---------------------------------------------------------------------------
# Ctrl+T (M7)
# ---------------------------------------------------------------------------

def test_ctrl_t_in_rack_mode_moves_track_to_slot_channel():
    win = _RackWin()
    _channels(win, [0])
    win._cur_slot = SYNTH
    win._assign_track_slot()
    r = win._router
    assert r.get_track_channel(0) == SYNTH and r.track_channel_now(0) == SYNTH
    assert r._track_slots[0] == BANK                  # slot propre intact (M9)
    assert win.undos == ["Piste 1 → canal 2"]
    assert win.statuses[-1] == "Piste 1 → canal 2 — Slot_02 Piano WAV"
    assert win._cur_slot == SYNTH


def test_ctrl_t_in_rack_mode_rewrites_header_on_new_channel():
    win = _RackWin()
    _channels(win, [3])
    live = win._player._pattern
    live._tape[0] = with_bank_header([_grid()], 3, 33, 8, 0)
    win._cur_slot = KIT
    win._assign_track_slot()
    assert bank_header(live._tape[0]) == (KIT, 33, 8, 0)
    assert win._router.track_channel_now(0) == KIT    # la poursuite garde le canal


def test_ctrl_t_in_rack_mode_same_channel_does_nothing():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._cur_slot = SYNTH
    win._assign_track_slot()
    assert win.undos == []
    assert win.statuses == ["Piste 1: déjà au canal 2 — Slot_02 Piano WAV"]


def test_ctrl_t_normal_mode_assigns_slot():
    win = _RackWin(rack_mode=False)
    win._refresh_track_list = lambda: None
    win._cur_slot = SYNTH
    win._assign_track_slot()
    # Undo posé depuis 5d5 (essai de l'utilisateur)
    assert win._router._track_slots[0] == SYNTH and win.undos == ["Piste 1 → Slot_02"]


# ---------------------------------------------------------------------------
# Slot courant qui suit la piste (M4, M16) et kit sans renommage (M12)
# ---------------------------------------------------------------------------

def test_follow_track_slot_loads_synth_preview():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._follow_track_slot()
    assert win._cur_slot == SYNTH and win._router._synth_slot_idx == SYNTH


def test_follow_track_slot_bank_preview_on_fallback():
    win = _RackWin()
    _channels(win, [3])
    win._follow_track_slot()
    assert win._cur_slot == BANK and win._router.synth is win._router._bank_preview


def test_go_to_track_follows_channel_slot():
    win = _RackWin()
    _channels(win, [0, SYNTH])
    win._go_to_track(1)
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Piste 2 — Piano WAV"


def test_load_kit_slot_does_not_rename_pads_in_rack_mode(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(kit_path=str(path))
    win._player.voice_manager.set_name(0, "Batterie")
    win._load_kit_slot(KIT)
    assert win._snd.loaded == [str(path)]
    assert win._player.voice_manager.get_name(0) == "Batterie"


def test_load_kit_slot_renames_pads_in_normal_mode(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(rack_mode=False, kit_path=str(path))
    win._kit_status = lambda: "kit"
    win._load_kit_slot(KIT)
    assert win._player.voice_manager.get_name(0) == "Kit pad 1"


def test_go_to_kit_track_in_rack_mode_keeps_track_names(tmp_path):
    path = tmp_path / "kit.json"
    path.write_text("{}")
    win = _RackWin(kit_path=str(path))
    _channels(win, [0, KIT])
    win._player.voice_manager.set_name(1, "Batterie")
    win._go_to_track(1)
    assert win._snd.loaded == [str(path)]
    assert win._player.voice_manager.get_name(1) == "Batterie"


# ---------------------------------------------------------------------------
# Program Change reçu du contrôleur (M3, M4, M16)
# ---------------------------------------------------------------------------

def _handler(win):
    win._input_mode = "pads"
    return mh.MidiHandler(win)


def test_live_program_change_on_synth_channel_message():
    win = _RackWin()
    _channels(win, [SYNTH])
    _handler(win).on_program_change(40, 7)            # canal du contrôleur ignoré (M4)
    assert win._router._track_slots[0] == BANK        # pas de pont
    assert win._router.track_channel_now(0) == SYNTH
    assert win.statuses[-1] == ("Piste 1: Program Change 40 — canal 2, Slot_02 Piano WAV "
                                "(programme sans effet sur ce slot)")


def test_live_program_change_on_bank_channel_names_preset():
    win = _RackWin()
    _channels(win, [3])
    _handler(win).on_program_change(33, 0)
    msg = win.statuses[-1]
    assert msg.startswith("Piste 1: Program Change 33 — canal 4, Slot_04 vide → banque GM")
    assert "sans effet" not in msg


def test_live_program_change_recorded_on_track_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    win._player.recording = True
    recorded = []
    win._player.record_program_change = lambda p, ch: recorded.append((p, ch))
    _handler(win).on_program_change(12, 7)
    assert recorded == [(12, SYNTH)]                  # O7 : canal de la piste


def test_live_program_change_normal_mode_keeps_bridge_message():
    win = _RackWin(rack_mode=False)
    win._router._track_slots[0] = KIT
    _handler(win).on_program_change(17, 0)
    assert win.statuses[-1] == "Piste 1: Program Change → Slot 2"


# ---------------------------------------------------------------------------
# Propriétés de piste (M15)
# ---------------------------------------------------------------------------

def _track_dlg(win, channel, received=None):
    frame = wx.Frame(None)
    r = win._router
    instruments = [r.channel_instrument(c) for c in range(16)]
    dlg = TrackPropertiesDialog(
        frame, 0, win._rack, r.slot_for_track(0), 100, 0, False, False,
        on_change=(lambda *a: received.append(a)) if received is not None else None,
        channel=channel,
        slot_program=lambda s: ({InstrumentType.SYNTH: "synth"}.get(win._rack.get_slot(s).type),
                                win._rack.get_slot(s).gm_program()),
        slot_gm_tuning=win._slot_gm_tuning,
        bank_info=lambda s, c, m=None, l=None: win._bank_info(s, c, m, l, instruments),
        rack_slot_of=r.rack_slot_idx,
        channel_labels=[f"Canal {c + 1} — {win._rack_channel_desc(c)}" for c in range(16)])
    return frame, dlg


def test_track_dialog_rack_slot_is_channel_and_labels():
    win = _RackWin()
    _channels(win, [3])
    frame, dlg = _track_dlg(win, 3)
    assert dlg.get_slot_idx() == 3                    # slot N = canal N, même vide
    assert dlg._channels.GetString(1) == "Canal 2 — Slot_02 Piano WAV"
    assert dlg._channels.GetString(3) == "Canal 4 — Slot_04 vide → banque GM (Slot_06 FluidR3)"
    assert dlg.get_msb() is not None                  # le canal joue la banque de repli
    dlg.Destroy()
    frame.Destroy()


def test_track_dialog_rack_channel_change_moves_slot_and_programs():
    win = _RackWin()
    _channels(win, [3])
    received = []
    frame, dlg = _track_dlg(win, 3, received)
    dlg._channels.SetSelection(SYNTH)
    dlg._on_channel_change(_Evt())
    assert dlg.get_slot_idx() == SYNTH
    assert dlg.get_msb() is None and dlg._program_label.GetLabel() == "Programme GM du slot :"
    assert dlg._transpose.IsEnabled()                 # réglages GM du synthé
    assert received[-1][0] == SYNTH and received[-1][5] == SYNTH
    dlg.Destroy()
    frame.Destroy()


def test_track_dialog_rack_slot_change_moves_channel():
    win = _RackWin()
    _channels(win, [SYNTH])
    received = []
    frame, dlg = _track_dlg(win, SYNTH, received)
    dlg._slots.SetSelection(7)                        # slot vide → banque de repli
    dlg._on_slot_change(_Evt())
    assert dlg.get_channel() == 7
    assert dlg.get_msb() is not None and dlg._program_label.GetLabel() == "Programme du canal 8 :"
    dlg.Destroy()
    frame.Destroy()


def _scripted_track_dlg(result, channel=None):
    """Dialogue factice : enregistre ses arguments ; channel : canal choisi
    (le slot suit, comme le vrai dialogue en mode Rack)."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            FakeDlg.kw, FakeDlg.slot = kw, slot
            ch = kw["channel"] if channel is None else channel
            played = kw["rack_slot_of"](ch) if kw.get("rack_slot_of") else slot
            info = kw["bank_info"](played, ch)
            self.v = [ch if kw.get("rack_slot_of") else slot, vol, pan, mute, solo, ch,
                      info["program"] if info else kw["slot_program"](played)[1],
                      *kw["slot_gm_tuning"](played),
                      info["msb"] if info else None, info["lsb"] if info else None]
            if channel is not None:
                kw["on_change"](*self.v)

        def ShowModal(self):     return result
        def get_slot_idx(self):  return self.v[0]
        def get_volume(self):    return self.v[1]
        def get_pan(self):       return self.v[2]
        def get_mute(self):      return self.v[3]
        def get_solo(self):      return self.v[4]
        def get_channel(self):   return self.v[5]
        def get_program(self):   return self.v[6]
        def get_transpose(self): return self.v[7]
        def get_gain_db(self):   return self.v[8]
        def get_msb(self):       return self.v[9]
        def get_lsb(self):       return self.v[10]
        def Destroy(self):       pass
    return FakeDlg


def _track_props(win, fake):
    with patch("ui.mw_tracks.TrackPropertiesDialog", fake):
        win._track_properties_dialog()


def test_track_properties_rack_mode_passes_channel_as_slot():
    win = _RackWin()
    _channels(win, [3])
    fake = _scripted_track_dlg(wx.ID_OK)
    _track_props(win, fake)
    assert fake.slot == 3                             # pas le slot de repli (BANK)
    assert fake.kw["rack_slot_of"](3) == BANK
    assert fake.kw["channel_labels"][1] == "Canal 2 — Slot_02 Piano WAV"
    assert win.statuses[-1] == "Piste 1: propriétés inchangées"
    assert win.undos == ["Propriétés piste 1", "pop"]


def test_track_properties_rack_mode_change_channel_keeps_track_slot():
    win = _RackWin()
    _channels(win, [3])
    _track_props(win, _scripted_track_dlg(wx.ID_OK, channel=SYNTH))
    r = win._router
    assert r.get_track_channel(0) == SYNTH and r._track_slots[0] == BANK
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Piste 1: propriétés mises à jour"
    assert win.undos == ["Propriétés piste 1"]


def test_track_properties_rack_mode_cancel_restores_channel():
    win = _RackWin()
    _channels(win, [3])
    _track_props(win, _scripted_track_dlg(wx.ID_CANCEL, channel=SYNTH))
    assert win._router.get_track_channel(0) == 3 and win._cur_slot == BANK
    assert win.undos[-1] == "pop"


def test_track_properties_normal_mode_has_no_rack_args():
    win = _RackWin(rack_mode=False)
    fake = _scripted_track_dlg(wx.ID_CANCEL)
    _track_props(win, fake)
    assert fake.kw["rack_slot_of"] is None and fake.kw["channel_labels"] is None


# ---------------------------------------------------------------------------
# Changement de pattern (M16, M6)
# ---------------------------------------------------------------------------

def test_switch_to_rack_pattern_announces_mode_and_follows_slot():
    win = _RackWin(rack_mode=False)
    win._player.voice_manager.to_list = lambda: []
    new = win._pattern_list[1]
    new._rack_mode = True
    new._track_slots = [BANK] * 16
    new._track_channels = [SYNTH] + [Pattern.default_channel(t) for t in range(1, 16)]
    new._tape[0] = [TapeEvent(ETYPE_PATCH, payload={"note": 60, "vel": 100}, time=0, channel=SYNTH)]
    win._switch_pattern(1)
    assert win._router.rack_mode is True
    assert win._cur_slot == SYNTH
    assert win.statuses[-1] == "Pattern 02 — mode Rack 16 canaux"


def test_switch_back_to_normal_pattern_restores_track_slot():
    win = _RackWin(rack_mode=True)
    _channels(win, [SYNTH])
    win._player.voice_manager.to_list = lambda: []
    win._pattern_list[1]._track_slots = [BANK] * 16
    win._switch_pattern(1)
    assert win._router.rack_mode is False and win._cur_slot == BANK
    assert win.statuses[-1] == "Pattern 02"


# ---------------------------------------------------------------------------
# Curseur clavier des listes des propriétés de piste (Phase 8 étape 5e2,
# tests de 5d2 : essai de l'utilisateur)
# ---------------------------------------------------------------------------

from ui.gtk_listbox import select_with_cursor, cursor_row
import ui.gtk_listbox as gtk_listbox

gtk_only = pytest.mark.skipif("__WXGTK__" not in wx.PlatformInfo, reason="curseur GTK")


def _listbox(n=16):
    frame = wx.Frame(None)
    lb = wx.ListBox(frame, choices=[f"Canal {c + 1}" for c in range(n)])
    return frame, lb


@gtk_only
def test_set_selection_alone_leaves_gtk_cursor_behind():
    """Le défaut de wxGTK que 5d2 contourne."""
    frame, lb = _listbox()
    lb.SetSelection(9)
    assert cursor_row(lb) != 9
    frame.Destroy()


@gtk_only
def test_select_with_cursor_moves_selection_and_cursor_without_event():
    frame, lb = _listbox()
    events = []
    lb.Bind(wx.EVT_LISTBOX, lambda e: events.append(e.GetSelection()))
    select_with_cursor(lb, 9)
    assert lb.GetSelection() == 9 and cursor_row(lb) == 9
    select_with_cursor(lb, 2)
    assert lb.GetSelection() == 2 and cursor_row(lb) == 2
    # Le signal GTK « changed » serait émis tout de suite, pendant
    # set_cursor : pas de wx.Yield (il traiterait en pleine suite les
    # événements laissés par d'autres fichiers de tests).
    assert events == []
    lb.Unbind(wx.EVT_LISTBOX)
    frame.Destroy()


def test_select_with_cursor_out_of_range_and_without_gtk(monkeypatch):
    frame, lb = _listbox()
    select_with_cursor(lb, wx.NOT_FOUND)                 # désélection, pas de curseur
    assert lb.GetSelection() == wx.NOT_FOUND
    monkeypatch.setattr(gtk_listbox, "_tree_view", lambda listbox: None)
    select_with_cursor(lb, 4)                            # hors GTK : SetSelection seul
    assert lb.GetSelection() == 4
    frame.Destroy()


@gtk_only
def test_track_dialog_slot_change_moves_channel_cursor_normal_mode():
    """Essai : canal 1, choix d'un kit → canal 10, curseur au canal 10."""
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    rack.set_slot(1, InstrumentType.SYNTH, "Piano", {})
    frame = wx.Frame(None)
    dlg = TrackPropertiesDialog(
        frame, 0, rack, 1, 100, 0, False, False, channel=0,
        channel_after_slot=lambda s, c: Pattern.KIT_CHANNEL
        if rack.get_slot(s).type == InstrumentType.KIT else c,
        slot_program=lambda s: (None, None))
    assert cursor_row(dlg._channels) == 0 and cursor_row(dlg._slots) == 1
    dlg._slots.SetSelection(0)
    dlg._on_slot_change(_Evt())
    assert dlg.get_channel() == Pattern.KIT_CHANNEL
    assert cursor_row(dlg._channels) == Pattern.KIT_CHANNEL
    dlg.Destroy()
    frame.Destroy()


@gtk_only
def test_track_dialog_rack_mode_cursors_follow_both_ways():
    win = _RackWin()
    _channels(win, [SYNTH])
    frame, dlg = _track_dlg(win, SYNTH)
    dlg._slots.SetSelection(7)
    dlg._on_slot_change(_Evt())
    assert cursor_row(dlg._channels) == 7
    dlg._channels.SetSelection(KIT)
    dlg._on_channel_change(_Evt())
    assert cursor_row(dlg._slots) == KIT
    dlg.Destroy()
    frame.Destroy()


@gtk_only
def test_track_dialog_bank_program_cursor_on_channel_instrument():
    win = _RackWin()
    _channels(win, [3])
    win._router.program_change(0, 33, 3)                 # canal 4 : programme 34
    frame, dlg = _track_dlg(win, 3)
    assert dlg.get_program() == 33 and cursor_row(dlg._programs) == 33
    dlg.Destroy()
    frame.Destroy()


# ---------------------------------------------------------------------------
# Program Change du contrôleur, de bout en bout (Phase 8 étape 5e2 ;
# remarque 3 de l'essai) : octets MIDI → MidiManager → MidiHandler →
# routeur et moteur de banque, comme dans main_window (CallAfter ôté)
# ---------------------------------------------------------------------------

from midi.midi_manager import MidiManager
from pattern import ETYPE_PGM, ETYPE_CC


def _controller(win):
    handler = _handler(win)
    return MidiManager(on_program_change=handler.on_program_change, on_cc=handler.on_cc)


def _send(midi, *data):
    midi._callback((list(data), 0.0), None)


def test_controller_program_change_on_bank_channel_selects_instrument():
    win = _RackWin()
    _channels(win, [3])                                   # canal 4 → banque de repli
    _send(_controller(win), 0xC5, 33)                     # contrôleur sur le canal 6
    eng = win._router.bank_engine
    assert eng.selects(3)[-1] == ("select", 3, 0, 0, 33)  # canal de la piste (M4)
    assert eng.selects(5) == []
    assert win._router.channel_instrument(3)[0] == 33
    assert "Program Change 33 — canal 4" in win.statuses[-1]


def test_controller_bank_select_then_program_change():
    win = _RackWin()
    _channels(win, [3])
    midi = _controller(win)
    _send(midi, 0xB0, 0, 8)                               # CC0 = 8
    _send(midi, 0xC0, 1)
    assert win._router.channel_instrument(3) == (1, 8, 0)
    assert win._router.bank_engine.selects(3)[-1] == ("select", 3, 0, 8, 1)


def test_controller_program_change_on_synth_channel_keeps_slot():
    win = _RackWin()
    _channels(win, [SYNTH])
    _send(_controller(win), 0xC0, 40)
    assert win._router._track_slots[0] == BANK and win._router.slot_for_track(0) == SYNTH
    assert win._router.bank_engine.selects(SYNTH) == []
    assert win.statuses[-1].endswith("(programme sans effet sur ce slot)")


def test_controller_program_change_recorded_on_track_channel():
    win = _RackWin()
    _channels(win, [3])
    win._player.recording = True
    _send(_controller(win), 0xC9, 12)                     # contrôleur sur le canal 10
    pgms = [ev for ev in win._player._pattern._tape[0] if ev.etype == ETYPE_PGM]
    assert [(ev.channel, ev.payload["program"]) for ev in pgms] == [(3, 12)]


def test_controller_program_change_normal_mode_bridge_and_bank():
    win = _RackWin(rack_mode=False)
    win._router._track_slots[0] = KIT
    _send(_controller(win), 0xC0, 17)
    assert win._router._track_slots[0] == 1              # pont : 17 % 16
    win._router._track_slots[0] = BANK
    _channels(win, [2])
    _send(_controller(win), 0xC0, 33)
    assert win._router.bank_engine.selects(2)[-1] == ("select", 2, 0, 0, 33)


# ---------------------------------------------------------------------------
# Parcourir la liste des slots sans les charger (Phase 8 étape 5e4, tests de
# 5d3 : essai de l'utilisateur) — slot joué (_cur_slot) et slot listé
# ---------------------------------------------------------------------------

import ui.mw_pads as mw_pads_mod


def _list_win(tmp_path, rack_mode=False):
    """Fenêtre en mode normal, piste 1 sur la banque (slot joué), vraie liste
    des slots ; kit du slot 10 = un vrai fichier."""
    path = tmp_path / "808.json"
    path.write_text("{}")
    win = _RackWin(rack_mode=rack_mode, kit_path=str(path))
    win._kit_status = lambda: "kit"
    win._kits_dir = win._patches_dir = str(tmp_path)
    win._gm_soundfont, win._soundfonts_dir = SF, "/fake"
    frame = wx.Frame(None)
    win._slot_choice = wx.ListBox(frame, choices=win._rack.labels())
    select_with_cursor(win._slot_choice, win._cur_slot)
    return win, frame, str(path)


def _browse(win, idx):
    win._slot_choice.SetSelection(idx)
    win._on_slot_choice(_Evt())


def test_browsing_kit_slot_loads_nothing(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    win._player.voice_manager.set_name(0, "Batterie")
    _browse(win, KIT)
    assert win._snd.loaded == []                         # la batterie ne change pas
    assert win._cur_slot == BANK and win._listed_slot() == KIT
    assert win._player.voice_manager.get_name(0) == "Batterie"
    assert win.statuses[-1] == "Slot 10: 808 (Ctrl+T pour assigner)"
    frame.Destroy()


def test_browsing_synth_slot_loads_no_preview(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    _browse(win, SYNTH)
    assert win._router._synth is None and SYNTH not in win._router._slot_synths
    assert win.statuses[-1] == "Slot 02: Piano WAV (Ctrl+T pour assigner)"
    frame.Destroy()


def test_browsing_empty_slot_message(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    _browse(win, 3)
    assert win.statuses[-1] == "Slot 04: vide — Alt+X pour charger"
    frame.Destroy()


def test_ctrl_t_assigns_listed_slot_and_loads_it(tmp_path):
    win, frame, path = _list_win(tmp_path)
    _browse(win, KIT)
    win._assign_track_slot()
    assert win._router._track_slots[0] == KIT and win._cur_slot == KIT
    assert win._snd.loaded == [path]                     # chargé à l'assignation
    assert win._player.voice_manager.get_name(0) == "Kit pad 1"   # mode normal : renommés
    assert win.statuses[-1] == "Piste 1 → Slot_10 (808), canal 10"
    frame.Destroy()


def test_ctrl_t_on_synth_loads_preview(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    _browse(win, SYNTH)
    win._assign_track_slot()
    assert win._cur_slot == SYNTH and win._router._synth_slot_idx == SYNTH
    frame.Destroy()


def _fake_file_dlg(path):
    class FakeDlg:
        def __init__(self, *a, **kw): pass
        def ShowModal(self): return wx.ID_OK
        def GetPath(self):   return path
        def Destroy(self):   pass
    return FakeDlg


def test_explorer_kit_into_listed_slot_not_played_keeps_drums(tmp_path, monkeypatch):
    win, frame, path = _list_win(tmp_path)
    _browse(win, 7)
    monkeypatch.setattr(mw_pads_mod.wx, "FileDialog", _fake_file_dlg(path))
    win._explorer_kit()
    assert win._rack.get_slot(7).type == InstrumentType.KIT
    assert win._snd.loaded == []                         # slot non joué : rien chargé
    assert win._slot_choice.GetSelection() == 7          # la liste reste sur lui
    assert win.statuses[-1] == "Slot 08: kit 808 (Ctrl+T pour assigner)"
    frame.Destroy()


def test_explorer_kit_into_played_slot_loads_it(tmp_path, monkeypatch):
    win, frame, path = _list_win(tmp_path)
    _browse(win, KIT)
    win._assign_track_slot()                              # KIT devient le slot joué
    win._snd.loaded.clear()
    monkeypatch.setattr(mw_pads_mod.wx, "FileDialog", _fake_file_dlg(path))
    win._explorer_kit()
    assert win._snd.loaded == [path]
    frame.Destroy()


def test_explorer_patch_into_listed_slot_keeps_keyboard_sound(tmp_path, monkeypatch):
    win, frame, _ = _list_win(tmp_path)
    win._follow_track_slot()                             # préécoute : banque (slot joué)
    _browse(win, 7)
    monkeypatch.setattr(mw_pads_mod.wx, "FileDialog", _fake_file_dlg(str(tmp_path / "p.json")))
    win._explorer_patch()
    assert win._rack.get_slot(7).type == InstrumentType.SYNTH
    assert 7 in win._router._slot_synths                 # patch rechargé pour ses pistes
    assert win._router._synth_slot_idx == BANK           # le clavier garde son son
    assert win._slot_choice.GetSelection() == 7
    frame.Destroy()


def test_explorer_bank_into_listed_slot_keeps_preview(tmp_path, monkeypatch):
    win, frame, _ = _list_win(tmp_path)
    win._router._track_slots[0] = SYNTH
    win._follow_track_slot()                             # slot joué : synthé
    _browse(win, 7)

    class FakeBankDlg:
        def __init__(self, parent, slot_idx, files, bank_slot, *a):
            FakeBankDlg.slot_idx = slot_idx
        def ShowModal(self):     return wx.ID_OK
        def get_bank_slot(self): return 1
        def get_path(self):      return "/fake/GeneralUser.sf2"
        def Destroy(self):       pass
    monkeypatch.setattr(mw_pads_mod, "BankSlotDialog", FakeBankDlg)
    win._explorer_bank()
    assert FakeBankDlg.slot_idx == 7
    assert win._rack.get_slot(7).type == InstrumentType.BANK
    assert win._router._synth_slot_idx == SYNTH and win._cur_slot == SYNTH
    assert win.undos[-1] == "Banque slot 08"
    frame.Destroy()


@gtk_only
def test_update_slot_list_keeps_listed_slot_with_cursor(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    win._update_slot_list(7)
    assert win._slot_choice.GetSelection() == 7 and cursor_row(win._slot_choice) == 7
    win._update_slot_list()
    assert win._slot_choice.GetSelection() == BANK and cursor_row(win._slot_choice) == BANK
    frame.Destroy()


@gtk_only
def test_go_to_track_moves_slot_list_cursor(tmp_path):
    win, frame, _ = _list_win(tmp_path)
    win._router._track_slots[1] = SYNTH
    win._go_to_track(1)
    assert win._slot_choice.GetSelection() == SYNTH and cursor_row(win._slot_choice) == SYNTH
    frame.Destroy()


# ---------------------------------------------------------------------------
# Undo de Ctrl+T (Phase 8 étape 5e5, tests de 5d5 : essai de l'utilisateur),
# de bout en bout : vrai UndoManager, capture et restauration de l'état
# ---------------------------------------------------------------------------

from ui.mw_project import ProjectMixin
from undo_manager import UndoManager
from song import Song


class _UndoWin(ProjectMixin, _RackWin):
    """_RackWin + vraie capture / restauration d'état et vrai Undo."""

    def __init__(self, tmp_path):
        path = tmp_path / "808.json"
        path.write_text("{}")
        super().__init__(rack_mode=False, kit_path=str(path))
        self.kit_path    = str(path)
        self._kit_status = lambda: "kit"
        self._song_list  = [Song(i) for i in range(2)]
        self._cur_song_idx = 0
        self._song_window  = None
        self._undo = UndoManager()
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
        self._pattern_listbox = MagicMock()
        self._take = None
        self._frame = wx.Frame(None)
        self._slot_choice = wx.ListBox(self._frame, choices=self._rack.labels())
        select_with_cursor(self._slot_choice, self._cur_slot)

    _add_undo = ProjectMixin._add_undo          # le vrai (capture l'état)
    def _clipboard_to_dict(self):        return None
    def _clipboard_from_dict(self, d):   pass
    def _master_dict(self):              return {}
    def _master_from_dict(self, d):      return (100, 0)
    def _apply_master(self, *a):         pass
    def _update_title(self):             pass
    def _update_bpm_display(self):       pass

    def close(self):
        self._frame.Destroy()


def _ctrl_t(win, slot_idx):
    win._slot_choice.SetSelection(slot_idx)
    win._assign_track_slot()


def test_ctrl_t_undo_and_redo_restore_slot_channel_and_sound(tmp_path):
    win = _UndoWin(tmp_path)
    r = win._router
    _ctrl_t(win, KIT)
    assert r._track_slots[0] == KIT and r.get_track_channel(0) == Pattern.KIT_CHANNEL
    assert win._snd.loaded == [win.kit_path] and win._cur_slot == KIT
    win._undo_action()
    assert r._track_slots[0] == BANK and r.get_track_channel(0) == 0
    assert win._cur_slot == BANK and r.synth is r._bank_preview      # son du slot rétabli
    assert win._slot_choice.GetSelection() == BANK
    assert win.statuses[-1].startswith("Undo: Piste 1 → Slot_10")
    win._redo_action()
    assert r._track_slots[0] == KIT and r.get_track_channel(0) == Pattern.KIT_CHANNEL
    assert win._cur_slot == KIT and win._snd.loaded == [win.kit_path] * 2
    assert win.statuses[-1].startswith("Redo: Piste 1 → Slot_10")
    win.close()


def test_ctrl_t_same_slot_and_channel_adds_no_undo(tmp_path):
    win = _UndoWin(tmp_path)
    _ctrl_t(win, KIT)
    n = len(win._undo.history_list())
    _ctrl_t(win, KIT)
    assert len(win._undo.history_list()) == n
    assert win.statuses[-1] == "Piste 1: déjà sur Slot_10 (808), canal 10"
    win.close()


def test_undo_of_other_action_does_not_reload_kit(tmp_path):
    win = _UndoWin(tmp_path)
    _ctrl_t(win, KIT)
    win._add_undo("Autre action")
    win._undo_action()
    assert win._router._track_slots[0] == KIT
    assert win._snd.loaded == [win.kit_path]           # kit (et noms des pads) non rechargé
    win.close()
