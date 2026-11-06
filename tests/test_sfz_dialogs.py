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
    le chargement du programme ; 7k1 : composition d'une banque SFZ
    (SfzBankDialog : ajout, numéro, monter / descendre, renommer, retirer,
    touches, enregistrement, modification d'une banque), boutons du
    dialogue du slot, banque modifiée relue par l'Explorateur.
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
from audio.sfz_sources import source_entry, write_sfzbank
from ui.dialogs_sfz import SfzSlotDialog, SfzBankDialog, stored_source
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
        assert names[:6] == ["Sources SFZ", "Gain du slot", "Fichier…", "Dossier…",
                             "Nouvelle banque SFZ…", "Modifier la banque…"]    # 7j1
        # puis les boutons, dans l'ordre de GTK (Annuler avant Ok)
        assert sorted(names[6:]) == ["Annuler", "Ok"]
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


# ---------------------------------------------------------------------------
# Composition d'une banque SFZ (Phase 8 étape 7j1, Z21)
# ---------------------------------------------------------------------------

def _labels(lb):
    return [lb.GetString(i) for i in range(lb.GetCount())]


def _pick(dlg, text):
    for i, e in enumerate(dlg._available):
        if text in e.label:
            dlg._avail.SetSelection(i)
            return dlg.add_selected()
    raise AssertionError(text)


@pytest.fixture
def bank_dlg(library):
    dlg = SfzBankDialog(None, library.root)
    yield dlg
    dlg.Destroy()


def test_bank_dialog_lists_only_sfz_files(bank_dlg):
    labels = _labels(bank_dlg._avail)
    assert labels == ["Cello/Programs/a — SFZ", "GM/Melodic/001-Piano — SFZ",
                      "GM/Melodic/005-Rhodes — SFZ", "Solo/Sax — SFZ"]
    assert bank_dlg.GetTitle() == "Nouvelle banque SFZ"
    assert bank_dlg._programs.GetCount() == 0 and not bank_dlg._number.IsEnabled()


def test_bank_dialog_add_number_and_labels(bank_dlg):
    assert _pick(bank_dlg, "001-Piano") == 0
    assert _pick(bank_dlg, "Solo/Sax") == 1
    assert _labels(bank_dlg._programs) == ["1 - 001-Piano — GM/Melodic/001-Piano.sfz",
                                           "2 - Sax — Solo/Sax.sfz"]
    assert bank_dlg._programs.GetSelection() == 1 and bank_dlg._number.GetValue() == 2
    assert bank_dlg._note.GetLabel() == "Ajouté : programme 2, Sax"


def test_bank_dialog_number_swaps(bank_dlg):
    _pick(bank_dlg, "001-Piano")
    _pick(bank_dlg, "Solo/Sax")
    bank_dlg._programs.SetSelection(0)
    bank_dlg.set_number(2)                     # Piano prend 2, Sax prend 1
    assert _labels(bank_dlg._programs)[0].startswith("1 - Sax")
    assert bank_dlg._programs.GetSelection() == 1 and bank_dlg._number.GetValue() == 2
    bank_dlg.set_number(40)
    assert _labels(bank_dlg._programs)[1].startswith("40 - 001-Piano")


def test_bank_dialog_move_rename_remove(bank_dlg):
    for text in ("001-Piano", "005-Rhodes", "Solo/Sax"):
        _pick(bank_dlg, text)
    bank_dlg._programs.SetSelection(2)
    bank_dlg.move(-1)
    assert [l.split(" — ")[0] for l in _labels(bank_dlg._programs)] == \
        ["1 - 001-Piano", "2 - Sax", "3 - 005-Rhodes"]
    assert bank_dlg._programs.GetSelection() == 1
    bank_dlg.rename("Ténor")
    assert _labels(bank_dlg._programs)[1].startswith("2 - Ténor")
    bank_dlg.remove()
    assert bank_dlg._programs.GetCount() == 2 and bank_dlg._programs.GetSelection() == 1
    assert bank_dlg._note.GetLabel() == "Retiré : Ténor"


def _key(code, alt=False):
    return types.SimpleNamespace(GetKeyCode=lambda: code, AltDown=lambda: alt,
                                 skipped=[], Skip=lambda: None)


def test_bank_dialog_keys_on_program_list(bank_dlg, monkeypatch):
    for text in ("001-Piano", "Solo/Sax"):
        _pick(bank_dlg, text)
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: bank_dlg._programs))
    renamed = []
    monkeypatch.setattr(type(bank_dlg), "_ask_rename", lambda self: renamed.append(True))
    bank_dlg._programs.SetSelection(1)
    bank_dlg._on_key(_key(wx.WXK_UP, alt=True))                 # Alt+Haut : monter
    assert _labels(bank_dlg._programs)[0].startswith("1 - Sax")
    bank_dlg._on_key(_key(wx.WXK_F2))
    assert renamed == [True]
    bank_dlg._on_key(_key(wx.WXK_DELETE))
    assert bank_dlg._programs.GetCount() == 1


def test_bank_dialog_keys_elsewhere_are_ignored(bank_dlg, monkeypatch):
    _pick(bank_dlg, "001-Piano")
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: bank_dlg._avail))
    bank_dlg._on_key(_key(wx.WXK_DELETE))
    assert bank_dlg._programs.GetCount() == 1


def test_bank_dialog_save(bank_dlg, library):
    path = str(library.tmp / "out" / "Mes sons")
    os.makedirs(library.tmp / "out")
    assert not bank_dlg.save(path)                              # banque vide
    assert bank_dlg._note.GetLabel() == "Banque vide : ajoutez au moins un programme"
    _pick(bank_dlg, "Solo/Sax")
    bank_dlg._name.SetValue("  Mes sons  ")
    assert bank_dlg.save(path)
    assert bank_dlg.get_path() == path + ".sfzbank.json"
    from audio.sfz_sources import read_source
    src = read_source(bank_dlg.get_path())
    assert src.name == "Mes sons" and [p.name for p in src.programs] == ["Sax"]


def test_bank_dialog_default_path(bank_dlg, library):
    bank_dlg._name.SetValue('Pia/no: "1"')
    assert bank_dlg.default_path() == os.path.join(library.root, "Piano 1.sfzbank.json")
    bank_dlg._name.SetValue("")
    assert bank_dlg.default_path() == os.path.join(library.root, "Banque SFZ.sfzbank.json")


def test_bank_dialog_edits_existing_bank(library):
    bank = os.path.join(library.root, "Mes pianos.sfzbank.json")
    write_sfzbank(bank, "Mes pianos", [(4, "Piano", os.path.join(library.melodic, "001-Piano.sfz"))])
    dlg = SfzBankDialog(None, library.root, path=bank)
    try:
        assert dlg.GetTitle() == "Banque SFZ — modifier"
        assert dlg.get_name() == "Mes pianos" and dlg.get_path() == bank
        assert _labels(dlg._programs) == ["5 - Piano — GM/Melodic/001-Piano.sfz"]
        _pick(dlg, "Solo/Sax")
        assert dlg.save(dlg.get_path())
    finally:
        dlg.Destroy()
    entries = [e for e in [source_entry(bank)] if e]
    assert entries[0].count == 2


# ---------------------------------------------------------------------------
# Dialogue du slot : boutons de banque SFZ (7j1)
# ---------------------------------------------------------------------------

class _BankDialog:
    def __init__(self, result, saved):
        self.result, self.saved, self.args = result, saved, None

    def __call__(self, parent, sfz_dir, entries=None, path=None):
        self.args = (sfz_dir, path, len(entries))
        return self

    def ShowModal(self):
        return self.result

    def get_path(self):
        return self.saved

    def Destroy(self):
        pass


def test_edit_button_enabled_on_sfz_bank_only(library):
    bank = os.path.join(library.root, "B.sfzbank.json")
    write_sfzbank(bank, "B", [(0, "Sax", library.sax)])
    dlg = _dialog(library, current=library.melodic)
    try:
        assert not dlg._edit_bank_btn.IsEnabled()
        dlg.add_source(bank)
        assert dlg._edit_bank_btn.IsEnabled()
        dlg.add_source(library.sax)
        assert not dlg._edit_bank_btn.IsEnabled()
    finally:
        dlg.Destroy()


def test_new_bank_added_and_selected(library, monkeypatch):
    bank = os.path.join(library.root, "Nouvelle.sfzbank.json")
    write_sfzbank(bank, "Nouvelle", [(0, "Sax", library.sax)])
    fake = _BankDialog(wx.ID_OK, bank)
    monkeypatch.setattr(SfzSlotDialog, "BANK_DIALOG", fake)
    dlg = _dialog(library, entries=[source_entry(library.sax, library.root)])
    try:
        dlg._compose_bank(None)
        assert fake.args == (library.root, None, 1)
        assert dlg._list.GetSelection() == 0 and dlg.get_source() == bank
        assert dlg._list.GetString(0) == "Nouvelle.sfzbank.json — banque SFZ, 1 programme"
        assert dlg._edit_bank_btn.IsEnabled()
    finally:
        dlg.Destroy()


def test_modified_bank_line_updated(library, monkeypatch):
    bank = os.path.join(library.root, "M.sfzbank.json")
    write_sfzbank(bank, "M", [(0, "Sax", library.sax)])
    dlg = _dialog(library, current=bank)
    try:
        index = dlg._list.GetSelection()
        write_sfzbank(bank, "M", [(0, "Sax", library.sax),
                                  (1, "Piano", os.path.join(library.melodic, "001-Piano.sfz"))])
        fake = _BankDialog(wx.ID_OK, bank)
        monkeypatch.setattr(SfzSlotDialog, "BANK_DIALOG", fake)
        count = dlg._list.GetCount()
        dlg._compose_bank(dlg.get_source())
        assert fake.args[1] == bank
        assert dlg._list.GetCount() == count and dlg._list.GetSelection() == index
        assert dlg._list.GetString(index) == "M.sfzbank.json — banque SFZ, 2 programmes"
    finally:
        dlg.Destroy()


def test_cancelled_composition_changes_nothing(library, monkeypatch):
    monkeypatch.setattr(SfzSlotDialog, "BANK_DIALOG", _BankDialog(wx.ID_CANCEL, None))
    dlg = _dialog(library, current=library.sax)
    try:
        before = (dlg._list.GetCount(), dlg.get_source())
        dlg._compose_bank(None)
        assert (dlg._list.GetCount(), dlg.get_source()) == before
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Explorateur : même source modifiée, relue (correction de l'essai de 7j1)
# ---------------------------------------------------------------------------

def test_explorer_rereads_modified_source(win, library, monkeypatch):
    from test_sfz_slot import FakeSfzEngine
    win._sfz_dir = win._router.sfz_dir = library.root
    _explore(win, monkeypatch, 9, source=library.sax)
    engine = FakeSfzEngine()
    monkeypatch.setattr(win._router, "sfz_engine", engine)
    engine.stale = (9,)
    before = win._undo.last_entry()
    _explore(win, monkeypatch, 9, source=library.sax)
    assert ("load", 9, library.sax) in engine.calls            # relue par la synchronisation
    assert win._status_ctrl.GetString(0) == "Slot 10: SFZ Sax relu, 3 programmes"
    assert win._undo.last_entry() is before                     # le Rack n'a pas changé
    engine.stale = ()
    _explore(win, monkeypatch, 9, source=library.sax)
    assert win._status_ctrl.GetString(0) == "SFZ : inchangé"

