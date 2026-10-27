#python3
"""
    File: tests/test_bank_dialogs.py
    Tests de la Phase 7 étape 17h1 (docs/DESIGN.md § 17e3 O5, précision
    17f2, § 17e2 R9) : entête d'une piste (bank_header / with_bank_header),
    TrackPropertiesDialog sur un slot Banque (liste du canal, MSB / LSB, le
    canal impose son instrument), propriétés de piste en direct
    (mw_tracks : piste temporaire, entêtes, autres pistes du canal, note
    d'aperçu, Annuler, Undo, aller-retour de canal), BankSlotDialog et
    élément « Banque » de l'Explorateur (mw_pads._explorer_bank).
    Date: Tue, 27/10/2026
    Author: Coolbrother
"""
import sys
import os
import threading
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import wx

import track_router as tr_mod
from pattern import (Pattern, TapeEvent, ETYPE_CC, ETYPE_PGM, ETYPE_GRID,
                     bank_header, with_bank_header)
from rack import Rack, InstrumentType
from track_router import TrackRouter
from ui.dialogs_properties import TrackPropertiesDialog
from ui.dialogs_bank import BankSlotDialog
from ui.mw_tracks import TrackMixin
from ui.mw_pads import PadMixin
from test_bank_slot import FakeBankEngine, FakeSoundManager, FakeTimer, FakeSynthEngine

KIT_CH = Pattern.KIT_CHANNEL
SF     = "/fake/FluidR3_GM.sf2"
SF2    = "/fake/GeneralUser_GS.sf2"
BANK   = 5      # slot Banque du Rack, emplacement 1
SYNTH  = 1


@pytest.fixture(autouse=True)
def _fake_timer_and_synth(monkeypatch):
    """Comme test_bank_slot : pas de vrai Timer ni de vrai SynthEngine
    (flux audio jamais fermé) dans track_router."""
    FakeTimer.created = []
    monkeypatch.setattr(tr_mod, "threading",
                        types.SimpleNamespace(Timer=FakeTimer, Thread=threading.Thread))
    monkeypatch.setattr(tr_mod, "SynthEngine", FakeSynthEngine)


class _Evt:
    def Skip(self):
        pass


# ---------------------------------------------------------------------------
# Entête d'une piste (pattern.py)
# ---------------------------------------------------------------------------

def _grid(t=0):
    return TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=t)


def test_bank_header_none_without_program_change_at_start():
    assert bank_header([]) is None
    assert bank_header([_grid(), TapeEvent(ETYPE_PGM, channel=2, payload={"program": 5}, time=4)]) is None
    assert bank_header([TapeEvent(ETYPE_CC, channel=2, payload={"cc_num": 0, "value": 8}, time=0)]) is None


def test_bank_header_reads_channel_program_msb_lsb():
    events = with_bank_header([_grid()], 3, 33, 8, 1)
    assert bank_header(events) == (3, 33, 8, 1)
    pgm_only = [TapeEvent(ETYPE_PGM, channel=4, payload={"program": 11}, time=0)]
    assert bank_header(pgm_only) == (4, 11, 0, 0)


def test_with_bank_header_order_and_replacement():
    old = with_bank_header([_grid(), _grid(4)], 0, 0, 0, 0)
    new = with_bank_header(old, 2, 48, 8, 3)
    head = [(e.etype, e.channel, e.payload) for e in new[:3]]
    assert head == [(ETYPE_CC, 2, {"cc_num": 0, "value": 8}),
                    (ETYPE_CC, 2, {"cc_num": 32, "value": 3}),
                    (ETYPE_PGM, 2, {"program": 48})]
    assert [e.etype for e in new[3:]] == [ETYPE_GRID, ETYPE_GRID]     # ancien entête retiré
    assert len(old) == 5                                                # liste d'origine intacte


def test_with_bank_header_keeps_later_bank_events():
    later = [TapeEvent(ETYPE_CC, channel=2, payload={"cc_num": 0, "value": 8}, time=8),
             TapeEvent(ETYPE_PGM, channel=4, payload={"program": 11}, time=8)]
    new = with_bank_header(later, 0, 0, 0, 0)
    assert new[3:] == later


# ---------------------------------------------------------------------------
# TrackPropertiesDialog sur un slot Banque
# ---------------------------------------------------------------------------

class _Rack:
    def labels(self):
        return [f"Slot_{i + 1:02d}" for i in range(16)]


INSTR = {0: (0, 0, 0), 2: (48, 0, 0), 3: (33, 0, 0), KIT_CH: (8, 0, 0)}


def _bank_info(slot, ch, msb=None, lsb=None, gs=True):
    if slot != BANK:
        return None
    program = None
    if msb is None:
        program, msb, lsb = INSTR.get(ch, (0, 0, 0))
    bank = 128 if ch == KIT_CH else msb
    names = [f"B{bank}P{p}" if p % 2 == 0 else None for p in range(128)]
    return {"names": names, "program": program, "msb": msb, "lsb": lsb,
            "drums": ch == KIT_CH, "gs": gs}


def _dlg(slot=BANK, channel=3, bank_info=_bank_info, received=None):
    frame = wx.Frame(None)
    dlg = TrackPropertiesDialog(
        frame, 3, _Rack(), slot, 100, 0, False, False,
        on_change=(lambda *a: received.append(a)) if received is not None else None,
        channel=channel, channel_after_slot=lambda s, c: c,
        slot_program=lambda s: (None, None), bank_info=bank_info)
    return frame, dlg


def _close(frame, dlg):
    dlg.Destroy()
    frame.Destroy()


def test_bank_dialog_shows_channel_program_list():
    frame, dlg = _dlg()
    assert dlg._program_label.GetLabel() == "Programme du canal 4 :"
    assert dlg._programs.GetCount() == 128 and dlg._programs.IsEnabled()
    assert dlg._programs.GetString(0) == "1 - B0P0"
    assert dlg._programs.GetString(1) == "2 - (vide)"
    assert dlg.get_program() == 33
    assert (dlg.get_msb(), dlg.get_lsb()) == (0, 0)
    assert dlg._msb.IsEnabled() and dlg._lsb.IsEnabled()
    _close(frame, dlg)


def test_bank_dialog_lsb_label_follows_bank_select_mode():
    frame, dlg = _dlg()
    assert "sans effet en mode GS" in dlg._lsb_label.GetLabel()
    _close(frame, dlg)
    frame, dlg = _dlg(bank_info=lambda s, c, m=None, l=None: _bank_info(s, c, m, l, gs=False))
    assert dlg._lsb_label.GetLabel() == "Banque LSB (CC32) :"
    _close(frame, dlg)


def test_bank_dialog_channel_imposes_its_instrument():
    received = []
    frame, dlg = _dlg(received=received)
    dlg._channels.SetSelection(2)
    dlg._on_channel_change(_Evt())
    assert dlg._program_label.GetLabel() == "Programme du canal 3 :"
    assert dlg.get_program() == 48
    assert received[-1][5:7] == (2, 48)
    assert received[-1][9:] == (0, 0)
    _close(frame, dlg)


def test_bank_dialog_channel_10_drum_kits_and_bank_greyed():
    received = []
    frame, dlg = _dlg(received=received)
    dlg._channels.SetSelection(KIT_CH)
    dlg._on_channel_change(_Evt())
    assert dlg._programs.GetString(0) == "1 - B128P0"
    assert dlg.get_program() == 8
    assert not dlg._msb.IsEnabled() and not dlg._lsb.IsEnabled()
    _close(frame, dlg)


def test_bank_dialog_msb_reloads_names_keeps_program():
    received = []
    frame, dlg = _dlg(channel=0, received=received)
    dlg._programs.SetSelection(4)
    dlg._msb.SetValue(8)
    dlg._on_bank_change(_Evt())
    assert dlg._programs.GetString(0) == "1 - B8P0"
    assert dlg.get_program() == 4
    assert received[-1][5:7] == (0, 4) and received[-1][9:] == (8, 0)
    _close(frame, dlg)


def test_non_bank_slot_keeps_gm_list_and_no_bank_values():
    received = []
    frame, dlg = _dlg(slot=SYNTH, received=received)
    assert dlg._program_label.GetLabel() == "Programme GM du slot :"
    assert not dlg._msb.IsEnabled() and dlg.get_msb() is None and dlg.get_lsb() is None
    dlg._on_widget_change(_Evt())
    assert received[-1][9:] == (None, None)
    _close(frame, dlg)


def test_slot_change_from_bank_to_synth_and_back():
    frame, dlg = _dlg()
    dlg._slots.SetSelection(SYNTH)
    dlg._on_slot_change(_Evt())
    assert dlg._program_label.GetLabel() == "Programme GM du slot :"
    assert dlg.get_msb() is None
    dlg._slots.SetSelection(BANK)
    dlg._on_slot_change(_Evt())
    assert dlg._program_label.GetLabel() == "Programme du canal 4 :"
    assert dlg.get_program() == 33
    _close(frame, dlg)


def test_bank_spinctrls_have_accessible_names():
    frame, dlg = _dlg()
    assert (dlg._msb.GetName(), dlg._lsb.GetName()) == ("Banque MSB", "Banque LSB")
    _close(frame, dlg)


# ---------------------------------------------------------------------------
# Propriétés de piste en direct (mw_tracks), modèle orchestre
# ---------------------------------------------------------------------------

def _router_and_tape():
    """Pistes 1 (piano, canal 1), 2 (piano, canal 1), 3 (cordes, canal 3)
    et 4 (basse, canal 4) sur le slot Banque, entêtes à 1.1.1 ; piste 5
    sur un synthé WAV."""
    rack = Rack()
    rack.set_slot(SYNTH, InstrumentType.SYNTH, "Piano WAV", {"patch": "p"})
    rack.set_slot(BANK, InstrumentType.BANK, "FluidR3_GM", {"bank_slot": 0})
    rack.set_bank_file(0, SF)
    statuses = []
    router = TrackRouter(rack, "/fake", FakeSoundManager(), statuses.append,
                         bank_engine=FakeBankEngine())
    pat = Pattern()
    pat.new_pattern(1, 16)
    for t, ch, prog in ((0, 0, 0), (1, 0, 0), (2, 2, 48), (3, 3, 33)):
        router.assign_slot(t, BANK)
        router._track_channels[t] = ch
        pat._tape[t] = with_bank_header([_grid()], ch, prog, 0, 0)
    router.assign_slot(4, SYNTH)
    router.chase(pat._tape, 0.0)
    return router, pat


class _TrackWindow(TrackMixin):
    def __init__(self, cur_track=3):
        self._router, pat = _router_and_tape()
        self._rack        = self._router._rack
        self._player      = SimpleNamespace(_cur_track=cur_track, _pattern=pat,
                                            _current_offset=lambda: 0.0)
        self._cur_slot    = BANK
        self._slot_choice = MagicMock()
        self.calls        = []

    def _refresh_track_list(self):  pass
    def _play_toggle(self):         pass
    def _show_status(self, msg):    self.calls.append(("status", msg))
    def _add_undo(self, title):     self.calls.append(("undo", title))
    def _pop_last_undo(self):       self.calls.append("pop")


def _scripted(result, script):
    """Dialog factice : script(dlg) appelle dlg.choose(...) comme les
    gestes de l'utilisateur, avec bank_info pour le choix B ; les valeurs
    finales sont les dernières transmises."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            self.kw = kw
            info = kw["bank_info"](slot, kw["channel"])
            self.v = [slot, vol, pan, mute, solo, kw["channel"],
                      info["program"] if info else kw["slot_program"](slot)[1],
                      *kw["slot_gm_tuning"](slot),
                      info["msb"] if info else None, info["lsb"] if info else None]
            script(self)

        def choose(self, channel=None, program=None, msb=None):
            if channel is not None:                     # le canal impose son instrument
                self.v[5] = channel
                info = self.kw["bank_info"](self.v[0], channel)
                if info is not None:
                    self.v[6], self.v[9], self.v[10] = info["program"], info["msb"], info["lsb"]
            if program is not None:
                self.v[6] = program
            if msb is not None:
                self.v[9] = msb
            self.kw["on_change"](*self.v)

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


def _run(win, result, script):
    with patch("ui.mw_tracks.TrackPropertiesDialog", _scripted(result, script)):
        win._track_properties_dialog()


def _headers(win):
    return [bank_header(win._player._pattern._tape[t]) for t in range(4)]


ORIG = [(0, 0, 0, 0), (0, 0, 0, 0), (2, 48, 0, 0), (3, 33, 0, 0)]


def test_bank_gm_tuning_greyed_and_bank_info():
    win = _TrackWindow()
    assert win._slot_gm_tuning(BANK) == (None, None)
    assert win._bank_info(SYNTH, 0) is None
    info = win._bank_info(BANK, 3)
    assert (info["program"], info["msb"], info["lsb"], info["gs"]) == (33, 0, 0, True)
    assert info["names"][33] == "Fingered Bass" and info["names"][1] is None
    assert win._bank_info(BANK, KIT_CH)["names"][0] == "Standard"
    assert win._bank_info(BANK, 0, 8, 0)["program"] is None


def test_move_to_channel_takes_its_instrument_live(monkeypatch):
    win = _TrackWindow()
    seen = {}

    def script(dlg):
        dlg.choose(channel=0)
        seen["headers"] = _headers(win)
        seen["name"] = win._router.bank_preset_name(3)
    _run(win, wx.ID_OK, script)
    assert seen["headers"][3] == (0, 0, 0, 0)            # basse au canal 1 : piano
    assert seen["name"] == "Piano"
    assert win._router.track_channel_now(3) == 0
    assert ("note_on", 0, 60, 100) in win._router.bank_engine.calls   # aperçu (D16)
    assert win.calls[0] == ("undo", "Propriétés piste 4")
    assert "pop" not in win.calls


def test_program_change_on_channel_updates_other_tracks():
    win = _TrackWindow()
    _run(win, wx.ID_OK, lambda dlg: (dlg.choose(channel=0), dlg.choose(program=48)))
    assert _headers(win)[:2] == [(0, 48, 0, 0), (0, 48, 0, 0)]
    assert _headers(win)[3] == (0, 48, 0, 0)
    assert [win._router.bank_preset_name(t) for t in (0, 1, 3)] == ["Strings"] * 3
    assert win.calls[-1] == ("status", "Piste 4: propriétés mises à jour; "
                                       "entête mis à jour aussi sur les pistes 1, 2")


def test_header_survives_loop_replay():
    """Précision 17f2 : la poursuite (bouclage) rejoue le nouveau réglage."""
    win = _TrackWindow()
    _run(win, wx.ID_OK, lambda dlg: dlg.choose(program=48))
    win._router.chase(win._player._pattern._tape, 0.0)
    assert win._router.bank_preset_name(3) == "Strings"


def test_cancel_restores_tracks_and_instruments():
    win = _TrackWindow()
    _run(win, wx.ID_CANCEL, lambda dlg: (dlg.choose(channel=0), dlg.choose(program=48)))
    assert _headers(win) == ORIG
    assert win._router.get_track_channel(3) == 3 and win._router.track_channel_now(3) == 3
    assert [win._router.bank_preset_name(t) for t in range(4)] == \
        ["Piano", "Piano", "Strings", "Fingered Bass"]
    assert "pop" in win.calls


def test_ok_unchanged_pops_undo_and_keeps_tracks():
    win = _TrackWindow()
    before = [list(e) for e in win._player._pattern._tape]
    _run(win, wx.ID_OK, lambda dlg: None)
    assert "pop" in win.calls
    assert win._player._pattern._tape == before


def test_channel_round_trip_gives_back_own_instrument():
    """Défaut constaté à l'essai de 17h1 : la basse revenue sur son canal
    jouait le piano (canal 4 remis à l'état GM par la poursuite)."""
    win = _TrackWindow()
    seen = []

    def script(dlg):
        for ch in (0, 2, 3):
            dlg.choose(channel=ch)
            seen.append((dlg.v[6], win._router.bank_preset_name(3)))
    _run(win, wx.ID_OK, script)
    assert seen == [(0, "Piano"), (48, "Strings"), (33, "Fingered Bass")]
    assert _headers(win) == ORIG
    assert "pop" in win.calls                                 # retour à l'origine


def test_preview_note_only_on_new_instrument_or_channel():
    win = _TrackWindow()
    _run(win, wx.ID_OK, lambda dlg: (dlg.choose(), dlg.choose(program=34),
                                     dlg.choose(program=34)))
    notes = win._router.bank_engine.of("note_on")
    assert notes == [("note_on", 3, 60, 100)]


def test_preview_note_on_channel_10_is_kick():
    win = _TrackWindow()
    _run(win, wx.ID_OK, lambda dlg: dlg.choose(channel=KIT_CH))
    assert win._router.bank_engine.of("note_on")[-1] == ("note_on", KIT_CH, 36, 100)


def test_bank_change_in_dialog_writes_msb():
    win = _TrackWindow()
    _run(win, wx.ID_OK, lambda dlg: dlg.choose(msb=8, program=1))
    assert _headers(win)[3] == (3, 1, 8, 0)
    assert win._router.bank_preset_name(3) == "Piano 2"


def test_non_bank_track_gets_no_header():
    win = _TrackWindow(cur_track=4)
    win._cur_slot = SYNTH
    _run(win, wx.ID_OK, lambda dlg: dlg.choose(channel=7))
    assert bank_header(win._player._pattern._tape[4]) is None
    assert win._router.get_track_channel(4) == 7


def test_leaving_bank_slot_in_dialog_restores_header():
    win = _TrackWindow()

    def script(dlg):
        dlg.choose(program=48)
        dlg.v[0] = SYNTH                                     # passe sur le synthé WAV
        dlg.v[6], dlg.v[9], dlg.v[10] = None, None, None
        dlg.kw["on_change"](*dlg.v)
    _run(win, wx.ID_OK, script)
    assert _headers(win)[3] == ORIG[3]


# ---------------------------------------------------------------------------
# BankSlotDialog
# ---------------------------------------------------------------------------

def _bank_dlg(files=(SF, None, None, None), bank_slot=1):
    frame = wx.Frame(None)
    dlg = BankSlotDialog(frame, 5, list(files), bank_slot, "/sf2/FluidR3_GM.sf2", "/sf2")
    return frame, dlg


def test_bank_slot_dialog_lists_slots_with_files():
    frame, dlg = _bank_dlg()
    assert dlg.GetTitle() == "Banque — Slot 06"
    assert dlg._slots.GetString(0) == "Emplacement 1 — FluidR3_GM.sf2"
    assert dlg._slots.GetString(3) == "Emplacement 4 — (vide)"
    assert dlg._file.GetName() == "Fichier de banque"
    _close(frame, dlg)


def test_bank_slot_dialog_empty_slot_proposes_default_file():
    frame, dlg = _bank_dlg()
    assert dlg.get_bank_slot() == 1
    assert dlg.get_path() == "/sf2/FluidR3_GM.sf2"
    assert dlg._note.GetLabel() == "Emplacement vide."
    _close(frame, dlg)


def test_bank_slot_dialog_choosing_slot_shows_its_file():
    frame, dlg = _bank_dlg()
    dlg._slots.SetSelection(0)
    dlg._on_slot_change(_Evt())
    assert dlg.get_path() == SF
    assert "tous les slots de cet emplacement" in dlg._note.GetLabel()
    dlg._file.SetValue("  /autre.sf2  ")
    assert dlg.get_path() == "/autre.sf2"
    _close(frame, dlg)


# ---------------------------------------------------------------------------
# Explorateur → « Banque » (mw_pads._explorer_bank)
# ---------------------------------------------------------------------------

class _PadWindow(PadMixin):
    def __init__(self, cur_slot=6):
        self._rack = Rack()
        self._rack.set_slot(BANK, InstrumentType.BANK, "FluidR3_GM", {"bank_slot": 0})
        self._rack.set_bank_file(0, SF)
        self._cur_slot       = cur_slot
        self._gm_soundfont   = "/sf2/FluidR3_GM.sf2"
        self._soundfonts_dir = "/sf2"
        self._router         = MagicMock()
        self.calls           = []

    def _add_undo(self, title):     self.calls.append(("undo", title))
    def _pop_last_undo(self):       self.calls.append("pop")
    def _show_status(self, msg):    self.calls.append(("status", msg))
    def _update_slot_list(self):    self.calls.append("slots")
    def _refresh_track_list(self):  self.calls.append("tracks")


def _stub_bank_dlg(result, bank_slot, path, seen=None):
    class Stub:
        def __init__(self, parent, slot_idx, files, proposed, default, folder):
            if seen is not None:
                seen.update(slot_idx=slot_idx, files=list(files), proposed=proposed,
                            default=default, folder=folder)
        def ShowModal(self):     return result
        def get_bank_slot(self): return bank_slot
        def get_path(self):      return path
        def Destroy(self):       pass
    return Stub


def _explore(win, stub):
    with patch("ui.mw_pads.BankSlotDialog", stub):
        win._explorer_bank()


def test_explorer_bank_sets_slot_and_file():
    win = _PadWindow()
    seen = {}
    _explore(win, _stub_bank_dlg(wx.ID_OK, 1, SF2, seen))
    assert seen["proposed"] == 1                          # premier emplacement vide
    assert seen["default"] == "/sf2/FluidR3_GM.sf2"
    slot = win._rack.get_slot(6)
    assert (slot.type, slot.name, slot.config) == (InstrumentType.BANK, "GeneralUser_GS",
                                                   {"bank_slot": 1})
    assert win._rack.bank_files[1] == SF2
    win._router.sync_banks.assert_called_once()
    win._router.load_slot_preview.assert_called_once_with(6)
    assert win.calls[0] == ("undo", "Banque slot 07")
    assert "pop" not in win.calls
    assert win.calls[-1] == ("status", "Slot 07: banque GeneralUser_GS, emplacement 2")


def test_explorer_bank_proposes_own_slot_for_bank_slot():
    win = _PadWindow(cur_slot=BANK)
    seen = {}
    _explore(win, _stub_bank_dlg(wx.ID_CANCEL, 0, SF, seen))
    assert seen["proposed"] == 0


def test_explorer_bank_cancel_pops_undo():
    win = _PadWindow()
    _explore(win, _stub_bank_dlg(wx.ID_CANCEL, 1, SF2))
    assert win.calls[-2:] == ["pop", ("status", "Banque : annulé")]
    assert win._rack.get_slot(6).is_empty


def test_explorer_bank_unchanged_or_empty_pops_undo():
    win = _PadWindow(cur_slot=BANK)
    _explore(win, _stub_bank_dlg(wx.ID_OK, 0, SF))
    assert win.calls[-2:] == ["pop", ("status", "Banque : inchangé")]
    win = _PadWindow()
    _explore(win, _stub_bank_dlg(wx.ID_OK, 1, ""))
    assert win.calls[-2:] == ["pop", ("status", "Banque : aucun fichier")]
    assert win._rack.get_slot(6).is_empty


def test_explorer_bank_warns_when_shared_file_replaced():
    win = _PadWindow()
    _explore(win, _stub_bank_dlg(wx.ID_OK, 0, SF2))
    assert win._rack.bank_files[0] == SF2
    assert win.calls[-1] == ("status", "Slot 07: banque GeneralUser_GS, emplacement 1"
                                       " — son changé aussi pour les slots 06")
