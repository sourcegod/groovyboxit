#python3
"""
    File: tests/test_sfz_dialogs.py
    Interface du slot Synth SFZ (Phase 8 étape 7i1, docs/DESIGN.md § 7a2
    Z6, Z7, Z15, § 7a3 Z24, Z26 ; avancement 7h1) : dialogue du slot
    (SfzSlotDialog : liste des sources, présélection, gain, ajout d'une
    source, ordre Tab, chemin enregistré), élément « SFZ » de l'Explorateur
    sur une vraie fenêtre principale sans moteurs (slot rempli, Undo,
    Annuler, inchangé, réglages gardés, message de moteur coupé, liste des
    slots rétablie par l'Undo), propriétés de piste (Alt+Entrée) sur un SFZ
    (programmes de la source, MSB / LSB grisés), note d'aperçu qui attend
    le chargement du programme.
    Date: Thu, 05/11/2026
    Author: Coolbrother
"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import ui.mw_pads as mw_pads
import ui.mw_tracks as mw_tracks
from rack import Rack, InstrumentType
from sfz_sources import source_entry, write_sfzbank
from ui.dialogs_sfz import SfzSlotDialog, stored_source
from ui.dialogs_properties import TrackPropertiesDialog
from ui.main_window import MainWindow
from ui.mw_pads import PadMixin
from ui.mw_tracks import TrackMixin

# Des fichiers passés avant celui-ci détruisent la wx.App de session : la
# recréer au besoin, gardée dans le module (voir test_playback_rewind.py).
_APP = None


@pytest.fixture(autouse=True)
def _app():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)


def _sfz(path, text="<region> sample=a.wav\n"):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


@pytest.fixture
def library(tmp_path):
    """sfz_dir : dossier GM numéroté (2 programmes), .sfz seul, .bank.xml ;
    et une source hors de sfz_dir."""
    root = tmp_path / "sfz"
    _sfz(root / "GM" / "Melodic" / "001-Piano.sfz")
    _sfz(root / "GM" / "Melodic" / "005-Rhodes.sfz")
    _sfz(root / "Solo" / "Sax.sfz")
    _sfz(root / "Cello" / "Programs" / "a.sfz")
    _sfz(root / "Cello" / "Cello.bank.xml",
         '<AriaBank name="Cello"><AriaProgram name="A">'
         '<AriaElement path="Programs/a.sfz"/></AriaProgram></AriaBank>')
    _sfz(tmp_path / "ailleurs" / "Flute.sfz")
    return types.SimpleNamespace(root=str(root), melodic=str(root / "GM" / "Melodic"),
                                 sax=str(root / "Solo" / "Sax.sfz"),
                                 bank=str(root / "Cello" / "Cello.bank.xml"),
                                 outside=str(tmp_path / "ailleurs" / "Flute.sfz"),
                                 tmp=tmp_path)


# ---------------------------------------------------------------------------
# SfzSlotDialog
# ---------------------------------------------------------------------------

def _dialog(library, current=None, gain=0, **kw):
    return SfzSlotDialog(None, 6, library.root, current, gain, **kw)


def test_dialog_lists_sources_and_preselects_current(library):
    dlg = _dialog(library, current=library.melodic, gain=-10)
    try:
        labels = [dlg._list.GetString(i) for i in range(dlg._list.GetCount())]
        assert "GM/Melodic — dossier, 2 programmes" in labels
        assert "Solo/Sax — SFZ" in labels
        assert "Cello/Cello.bank.xml — banque Sforzando, 1 programme" in labels
        assert dlg._list.GetStringSelection() == "GM/Melodic — dossier, 2 programmes"
        assert dlg.get_source() == library.melodic
        assert dlg.get_entry().count == 2 and dlg.get_gain_db() == -10
        assert dlg.GetTitle() == "Synth SFZ — Slot 07"
    finally:
        dlg.Destroy()


def test_dialog_gain_bounded(library):
    dlg = _dialog(library, gain=-40)
    try:
        assert dlg.get_gain_db() == SfzSlotDialog.GAIN_MIN == -24
        dlg._gain.SetValue(50)
        assert dlg.get_gain_db() == SfzSlotDialog.GAIN_MAX == 12
    finally:
        dlg.Destroy()


def test_dialog_without_current_selects_first(library):
    dlg = _dialog(library)
    try:
        assert dlg._list.GetSelection() == 0
    finally:
        dlg.Destroy()


def test_dialog_current_outside_sfz_dir_listed_first(library):
    dlg = _dialog(library, current=library.outside)
    try:
        assert dlg._list.GetSelection() == 0
        assert dlg.get_source() == library.outside
        assert dlg._list.GetString(0) == f"{library.outside[:-4]} — SFZ"
    finally:
        dlg.Destroy()


def test_add_source_new_existing_and_empty(library):
    dlg = _dialog(library)
    try:
        count = dlg._list.GetCount()
        assert dlg.add_source(library.outside)                 # nouvelle : en tête
        assert dlg._list.GetCount() == count + 1 and dlg._list.GetSelection() == 0
        assert dlg.get_source() == library.outside
        assert dlg.add_source(library.sax)                     # déjà listée : retrouvée
        assert dlg._list.GetCount() == count + 1 and dlg.get_source() == library.sax
        os.makedirs(library.tmp / "vide")
        assert not dlg.add_source(str(library.tmp / "vide"))   # aucun programme
        assert dlg._note.GetLabel() == "Aucun programme SFZ dans vide"
        assert dlg.get_source() == library.sax
    finally:
        dlg.Destroy()


def test_dialog_with_given_entries_does_not_scan(library, monkeypatch):
    monkeypatch.setattr("ui.dialogs_sfz.list_sources",
                        lambda root: pytest.fail("parcours inattendu"))
    entry = source_entry(library.sax, library.root)
    dlg = _dialog(library, entries=[entry])
    try:
        assert dlg._list.GetCount() == 1
    finally:
        dlg.Destroy()


def test_dialog_empty_sfz_dir(tmp_path):
    os.makedirs(tmp_path / "vide")
    dlg = SfzSlotDialog(None, 0, str(tmp_path / "vide"))
    try:
        assert dlg._list.GetCount() == 0 and dlg.get_source() is None
        assert dlg._note.GetLabel() == f"Aucune source SFZ dans {tmp_path / 'vide'}"
    finally:
        dlg.Destroy()


def test_dialog_tab_order(library):
    dlg = _dialog(library)
    try:
        focusable = [w for w in dlg.GetChildren() if w.AcceptsFocus()]
        names = [w.GetName() if isinstance(w, (wx.ListBox, wx.SpinCtrl)) else w.GetLabel()
                 for w in focusable]
        assert names[:4] == ["Sources SFZ", "Gain du slot", "Fichier…", "Dossier…"]
        # puis les boutons, dans l'ordre de GTK (Annuler avant Ok)
        assert sorted(names[4:]) == ["Annuler", "Ok"]
    finally:
        dlg.Destroy()


def test_stored_source_relative_inside_absolute_outside(library):
    assert stored_source(library.melodic, library.root) == os.path.join("GM", "Melodic")
    assert stored_source(library.outside, library.root) == library.outside
    assert stored_source(library.sax, "") == library.sax


# ---------------------------------------------------------------------------
# Explorateur « SFZ » sur une vraie fenêtre principale (sans moteurs)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def win():
    global _APP
    if wx.GetApp() is None:
        _APP = wx.App(False)
    w = MainWindow(no_fluidsynth=True, no_sfizz=True)
    w._router.wait_loaded()
    yield w
    w._audio_driver.close()
    w.Destroy()


class _Dialog:
    """Remplace SfzSlotDialog : réponse et choix donnés ; retient ses
    arguments."""
    def __init__(self, result=wx.ID_OK, source=None, gain=0):
        self.result, self.source, self.gain, self.args = result, source, gain, None

    def __call__(self, parent, slot_idx, sfz_dir, current=None, gain_db=0):
        self.args = (slot_idx, sfz_dir, current, gain_db)
        return self

    def ShowModal(self):
        return self.result

    def get_source(self):
        return self.source

    def get_gain_db(self):
        return self.gain

    def get_entry(self):
        return source_entry(self.source) if self.source else None

    def Destroy(self):
        pass


def _explore(win, monkeypatch, slot, **kw):
    fake = _Dialog(**kw)
    monkeypatch.setattr(mw_pads, "SfzSlotDialog", fake)
    win._slot_choice.SetSelection(slot)
    win._explorer_sfz()
    return fake


def test_explorer_sfz_fills_slot(win, library, monkeypatch):
    win._sfz_dir = library.root
    win._router.sfz_dir = library.root
    win._rack.clear_slot(10)
    win._update_slot_list()
    _explore(win, monkeypatch, 10, source=library.melodic, gain=-6)
    slot = win._rack.get_slot(10)
    assert slot.type == InstrumentType.SFZ and slot.name == "GM — Melodic"
    assert slot.config == {"sfz_source": os.path.join("GM", "Melodic"), "sfz_gain_db": -6}
    assert win._slot_choice.GetString(10) == "Slot_11 - GM — Melodic"
    status = win._status_ctrl.GetString(0)
    assert status.startswith("Slot 11: SFZ GM — Melodic, 2 programmes, gain -6 dB")
    assert status.endswith(" — sfizz désactivé ou absent : slot muet")
    assert win._undo.last_entry().title == "SFZ slot 11"


def test_explorer_sfz_cancel_keeps_slot_and_pops_undo(win, library, monkeypatch):
    win._rack.clear_slot(11)
    before = win._undo.last_entry()
    _explore(win, monkeypatch, 11, result=wx.ID_CANCEL, source=library.sax)
    assert win._rack.get_slot(11).is_empty
    assert win._status_ctrl.GetString(0) == "SFZ : annulé"
    assert win._undo.last_entry() is before                 # Undo retiré


def test_explorer_sfz_unchanged(win, library, monkeypatch):
    win._sfz_dir = win._router.sfz_dir = library.root
    _explore(win, monkeypatch, 12, source=library.sax, gain=0)
    before = win._undo.last_entry()
    fake = _explore(win, monkeypatch, 12, source=library.sax, gain=0)
    assert fake.args[2] == library.sax and fake.args[3] == 0     # source et gain actuels
    assert win._status_ctrl.GetString(0) == "SFZ : inchangé"
    assert win._undo.last_entry() is before                       # Undo retiré


def test_explorer_sfz_keeps_other_settings_of_sfz_slot(win, library, monkeypatch):
    win._sfz_dir = win._router.sfz_dir = library.root
    _explore(win, monkeypatch, 13, source=library.sax)
    win._rack.get_slot(13).set_gm_program(65)
    _explore(win, monkeypatch, 13, source=library.bank, gain=3)
    slot = win._rack.get_slot(13)
    assert slot.config["gm_program"] == 65 and slot.config["sfz_gain_db"] == 3
    assert slot.config["sfz_source"] == os.path.join("Cello", "Cello.bank.xml")
    assert slot.name == "Cello"


def test_explorer_sfz_old_key_replaced(win, library, monkeypatch):
    win._sfz_dir = win._router.sfz_dir = library.root
    win._rack.set_slot(14, InstrumentType.SFZ, "Ancien", {"sfz_file": "Solo/Sax.sfz"})
    _explore(win, monkeypatch, 14, source=library.melodic)
    assert "sfz_file" not in win._rack.get_slot(14).config


def test_undo_restores_slot_list_label(win, library, monkeypatch):
    # Essai de 7h1 : Undo d'un slot rempli par l'Explorateur, libellé rétabli
    win._sfz_dir = win._router.sfz_dir = library.root
    win._rack.clear_slot(15)
    win._update_slot_list()
    win._undo.clear()
    win._project_modified = False
    _explore(win, monkeypatch, 15, source=library.sax)
    assert win._slot_choice.GetString(15) == "Slot_16 - Sax"
    win._undo_action()
    assert win._rack.get_slot(15).is_empty
    assert win._slot_choice.GetString(15) == "Slot_16 - Empty"


def test_explorer_lists_sfz_item():
    from ui.dialogs_simple import ExplorerDialog
    assert ExplorerDialog.ITEMS[-1] == "SFZ"


def test_open_explorer_dispatches_sfz(win, monkeypatch):
    calls = []
    monkeypatch.setattr(mw_pads, "ExplorerDialog", lambda parent: types.SimpleNamespace(
        ShowModal=lambda: wx.ID_OK, get_selection=lambda: "SFZ", Destroy=lambda: None))
    monkeypatch.setattr(type(win), "_explorer_sfz", lambda self: calls.append("sfz"))
    win._open_explorer()
    assert calls == ["sfz"]


# ---------------------------------------------------------------------------
# Message des moteurs coupés (Z7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot_type, bank, sfz, note", [
    (InstrumentType.SFZ, object(), None, " — sfizz désactivé ou absent : slot muet"),
    (InstrumentType.SFZ, None, object(), ""),
    (InstrumentType.BANK, None, object(), " — FluidSynth désactivé ou absent : slot muet"),
    (InstrumentType.BANK, object(), None, ""),
    (InstrumentType.KIT, None, None, ""),
])
def test_engine_off_note(slot_type, bank, sfz, note):
    fake = types.SimpleNamespace(_router=types.SimpleNamespace(bank_engine=bank, sfz_engine=sfz))
    assert PadMixin._engine_off_note(fake, slot_type) == note


# ---------------------------------------------------------------------------
# Propriétés de piste (Alt+Entrée) sur un SFZ (Z24)
# ---------------------------------------------------------------------------

from test_sfz_slot import _make_router, SFZ_A, BANK   # noqa: E402


def test_bank_info_of_sfz_slot():
    router, *_ = _make_router()
    router.assign_slot(0, SFZ_A)
    router.program_change(0, 48)
    fake = types.SimpleNamespace(_rack=router._rack, _router=router)
    info = TrackMixin._bank_info(fake, SFZ_A, 0)
    assert info["sfz"] is True and info["program"] == 48
    assert info["names"][0] == "001-Headroom Piano" and info["names"][48] == "049-Headroom Piano"
    assert TrackMixin._bank_info(fake, BANK, 0)["sfz"] is False
    assert TrackMixin._bank_info(fake, 1, 0) is None          # synthé WAV


def _sfz_info(program=1):
    names = [None] * 128
    names[0], names[1] = "001-Piano", "002-Rhodes (Dummy)"
    return {"names": names, "program": program, "msb": 0, "lsb": 0,
            "drums": False, "gs": True, "sfz": True}


def test_properties_dialog_on_sfz_slot():
    rack = Rack()
    rack.set_slot(3, InstrumentType.SFZ, "GM", {"sfz_source": "GM"})
    dlg = TrackPropertiesDialog(None, 0, rack, 3, 100, 0, False, False, channel=2,
                                bank_info=lambda slot, ch, msb=None, lsb=None:
                                _sfz_info() if slot == 3 else None)
    try:
        assert dlg._program_label.GetLabel() == "Programme du canal 3 :"
        assert dlg._programs.GetString(1) == "2 - 002-Rhodes (Dummy)"
        assert dlg._programs.GetString(2) == "3 - (vide)"
        assert dlg.get_program() == 1
        assert not dlg._msb.IsEnabled() and not dlg._lsb.IsEnabled()
        assert dlg._lsb_label.GetLabel() == "Banque LSB (CC32, sans objet pour un SFZ) :"
    finally:
        dlg.Destroy()


def test_properties_dialog_bank_slot_unchanged():
    rack = Rack()
    rack.set_slot(3, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
    info = dict(_sfz_info(), sfz=False)
    dlg = TrackPropertiesDialog(None, 0, rack, 3, 100, 0, False, False, channel=2,
                                bank_info=lambda slot, ch, msb=None, lsb=None: info)
    try:
        assert dlg._msb.IsEnabled() and dlg._lsb.IsEnabled()
        assert dlg._lsb_label.GetLabel() == "Banque LSB (CC32, sans effet en mode GS) :"
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Note d'aperçu : attend le chargement du programme (essai de 7h1)
# ---------------------------------------------------------------------------

class _Engine:
    def __init__(self, ready_after):
        self.polls = 0
        self.ready_after = ready_after

    def channel_ready(self, channel):
        self.polls += 1
        return self.polls > self.ready_after


class _PreviewWindow:
    """Fenêtre minimale : routeur qui enregistre bank_note ; CallLater
    remplacé par une file exécutée à la main."""
    PREVIEW_POLL_MS = TrackMixin.PREVIEW_POLL_MS
    PREVIEW_WAIT_MS = TrackMixin.PREVIEW_WAIT_MS
    _preview_note_when_ready = TrackMixin._preview_note_when_ready

    def __init__(self):
        self.notes = []
        self._router = types.SimpleNamespace(
            bank_note=lambda ch, note, vel, dur, engine: self.notes.append((ch, note, engine)))


@pytest.fixture
def later(monkeypatch):
    queue = []
    monkeypatch.setattr(mw_tracks.wx, "CallLater",
                        lambda ms, fn, *args: queue.append((ms, fn, args)))

    def run():
        while queue:
            ms, fn, args = queue.pop(0)
            fn(*args)
    return queue, run


def test_preview_waits_until_program_loaded(later):
    queue, run = later
    win, engine = _PreviewWindow(), _Engine(ready_after=3)
    state = {"last": "k"}
    win._preview_note_when_ready(engine, 2, 60, state, "k")
    assert win.notes == [] and queue[0][0] == TrackMixin.PREVIEW_POLL_MS
    run()
    assert win.notes == [(2, 60, engine)] and engine.polls == 4


def test_preview_abandoned_when_program_changed(later):
    queue, run = later
    win, engine = _PreviewWindow(), _Engine(ready_after=2)
    state = {"last": "k1"}
    win._preview_note_when_ready(engine, 0, 60, state, "k1")
    state["last"] = "k2"                       # un autre programme a été choisi
    run()
    assert win.notes == []


def test_preview_plays_after_timeout(later):
    queue, run = later
    win, engine = _PreviewWindow(), _Engine(ready_after=10 ** 6)
    win._preview_note_when_ready(engine, 0, 36, {"last": "k"}, "k")
    run()
    assert win.notes == [(0, 36, engine)]
    assert engine.polls == TrackMixin.PREVIEW_WAIT_MS // TrackMixin.PREVIEW_POLL_MS + 1


def test_preview_on_bank_engine_plays_at_once(later):
    queue, run = later
    win, bank = _PreviewWindow(), object()     # FluidSynth : pas de channel_ready
    win._preview_note_when_ready(bank, 0, 60, {"last": "k"}, "k")
    assert win.notes == [(0, 60, bank)] and queue == []


def test_preview_without_engine_does_nothing(later):
    queue, run = later
    win = _PreviewWindow()
    win._preview_note_when_ready(None, 0, 60, {"last": "k"}, "k")
    assert win.notes == [] and queue == []
