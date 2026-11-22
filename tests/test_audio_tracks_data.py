#python3
"""
    File: tests/test_audio_tracks_data.py
    Données des pistes audio (Phase 8 étape 14b1, docs/DESIGN.md § 14a A2,
    A3, A7-A9 et essais) : type de piste et entrée audio par pattern (.gvp,
    anciens projets, redimensionnement, song figé, routeur), clip
    ETYPE_AUDIO (sérialisation, ignoré par la lecture jusqu'à 14d1) ;
    audio_takes (dossier Audios, noms, numéros libres, chemin choisi, WAV 24
    bits, copie renommée, dossier du projet) ; Enregistrer sous (case
    « Créer un nouveau dossier pour ce projet », « Chemin des fichiers
    audios », Parcourir…, prises copiées et clips repointés, clé audio_dir) ;
    propriétés de piste (« Type de piste » et « Entrée audio » en tête avec
    le focus, réglages MIDI grisés, effet immédiat, Ok, Annuler) ; vraie
    fenêtre principale (enregistrer puis rouvrir).
    Date: Sun, 15/11/2026
    Author: Coolbrother
"""
import sys
import os
import json
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import soundfile as sf
import wx
from conftest import main_thread_call_after

from pattern import (Pattern, TapeEvent, ETYPE_AUDIO, ETYPE_GRID, TRACK_MIDI, TRACK_AUDIO,
                     TRACK_KINDS)
from song import frozen_pattern
from rack import Rack, InstrumentType
from player import tape_events as te
from audio import audio_takes as at
from ui.dialogs_properties import TrackPropertiesDialog
from ui.mw_patterns import PatternMixin
from ui.mw_project import ProjectMixin, _ProjectFolderHook
from test_rack_mode_ui import _RackWin, _env   # noqa: F401  (App, Timer, SynthEngine factices)


def _clip(rel="Audios/a.wav", time=0, gain=1.0):
    return TapeEvent(ETYPE_AUDIO, payload={"file": rel, "gain": gain}, time=time)


# ---------------------------------------------------------------------------
# Pattern : type de piste, entrée audio, clips
# ---------------------------------------------------------------------------

def test_kinds_and_defaults():
    assert TRACK_KINDS == ("midi", "audio")
    p = Pattern()
    assert p._track_kinds == [TRACK_MIDI] * p._num_tracks
    assert p._track_audio_ins == [""] * p._num_tracks
    assert not p.is_audio_track(0) and not p.is_audio_track(99)


def test_kinds_saved_and_loaded():
    p = Pattern()
    p._track_kinds[2] = TRACK_AUDIO
    p._track_audio_ins[2] = "pipewire"
    p._tape[2].append(_clip("Audios/x.wav", time=4, gain=0.5))
    q = Pattern()
    q.from_dict(json.loads(json.dumps(p.to_dict())))
    assert q._track_kinds == p._track_kinds and q._track_audio_ins == p._track_audio_ins
    assert q.is_audio_track(2)
    (t, ev), = q.audio_clips()
    assert (t, ev.time, ev.payload) == (2, 4, {"file": "Audios/x.wav", "gain": 0.5})


def test_old_project_without_keys():
    d = Pattern().to_dict()
    del d["track_kinds"], d["track_audio_ins"]
    q = Pattern()
    q._track_kinds[0] = TRACK_AUDIO
    q.from_dict(d)
    assert q._track_kinds == [TRACK_MIDI] * q._num_tracks
    assert q._track_audio_ins == [""] * q._num_tracks


@pytest.mark.parametrize("value", [None, "x", ["audio", "synthé", 3, None, ""]])
def test_invalid_kinds_cleaned(value):
    d = Pattern().to_dict()
    d["track_kinds"] = value
    q = Pattern()
    q.from_dict(d)
    assert len(q._track_kinds) == q._num_tracks and set(q._track_kinds) <= set(TRACK_KINDS)
    if isinstance(value, list):
        assert q._track_kinds[:5] == ["audio", "midi", "midi", "midi", "midi"]


def test_extend_pads_the_lists():
    p = Pattern()
    n = p._num_tracks
    p._track_kinds[0] = TRACK_AUDIO
    p._extend_tracks(n + 3)
    assert len(p._track_kinds) == n + 3 and p._track_kinds[0] == TRACK_AUDIO
    assert p._track_kinds[-1] == TRACK_MIDI and len(p._track_audio_ins) == n + 3


def test_audio_clips_of_one_track_or_all():
    p = Pattern()
    p._tape[1] += [_clip("a"), TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 90}, time=0)]
    p._tape[3].append(_clip("b"))
    assert [ev.payload["file"] for _, ev in p.audio_clips(1)] == ["a"]
    assert [(t, ev.payload["file"]) for t, ev in p.audio_clips()] == [(1, "a"), (3, "b")]


def test_frozen_pattern_copies_kinds():
    p = Pattern()
    p._track_kinds[4] = TRACK_AUDIO
    p._track_audio_ins[4] = "pulse"
    out = frozen_pattern(p)
    assert out._track_kinds[4] == TRACK_AUDIO and out._track_audio_ins[4] == "pulse"
    p._track_kinds[4] = TRACK_MIDI
    assert out._track_kinds[4] == TRACK_AUDIO


def test_playback_emits_clips_since_14d1():
    clip = _clip(time=0)
    ev, = te.tape_events([[clip]], 0, 15, lambda s: s * 0.1)
    assert ev == (0.0, te.AUDIO_TAPE_EVENT, (0, "Audios/a.wav", 1.0, clip.id, 0.0, 0, None), 0)


def test_router_keeps_the_kinds_of_the_live_pattern():
    p = Pattern()
    p._track_kinds[2] = TRACK_AUDIO
    p._track_audio_ins[2] = "pipewire"
    router = SimpleNamespace(_track_slots=[0] * 16, _track_mutes=[False] * 16,
                             _track_solos=[False] * 16, _track_volumes=[100] * 16,
                             _track_pans=[0] * 16, _track_channels=[0] * 16,
                             _track_midi_outs=[""] * 16, _track_midi_ins=[""] * 16,
                             _track_kinds=list(p._track_kinds),
                             _track_audio_ins=list(p._track_audio_ins))
    win = SimpleNamespace(_router=router, _player=SimpleNamespace(_pattern=Pattern(), bpm=120))
    out = Pattern()
    PatternMixin._flush_pattern_to_store(win, out)
    assert out._track_kinds[2] == TRACK_AUDIO and out._track_audio_ins[2] == "pipewire"


# ---------------------------------------------------------------------------
# audio_takes
# ---------------------------------------------------------------------------

def test_stem_and_default_folder(tmp_path):
    proj = str(tmp_path / "P" / "Chanson.gvp")
    assert at.project_stem(proj) == "Chanson"
    assert at.audios_dir(proj) == str(tmp_path / "P" / "Audios")


def test_chosen_folder(tmp_path):
    proj = str(tmp_path / "P" / "Chanson.gvp")
    assert at.audios_dir(proj, "/srv/prises") == "/srv/prises"
    assert at.audios_dir(proj, "../Prises") == str(tmp_path / "Prises")


def test_take_name():
    assert at.take_name("/x/Chanson.gvp", 0, 2, 1) == "Chanson_pattern01_piste03_take_001.wav"
    assert at.take_name("/x/Chanson.gvp", 98, 15, 12) == "Chanson_pattern99_piste16_take_012.wav"


def test_next_take_numbers(tmp_path):
    proj = str(tmp_path / "Chanson.gvp")
    path, rel = at.next_take(proj, 0, 0)
    assert rel == "Audios/Chanson_pattern01_piste01_take_001.wav"
    at.write_take(path, np.zeros(10, np.float32), 44100)
    assert at.next_take(proj, 0, 0)[1].endswith("take_002.wav")
    assert at.next_take(proj, 0, 1)[1].endswith("piste02_take_001.wav")


def test_next_take_in_a_chosen_folder(tmp_path):
    proj = str(tmp_path / "P" / "Chanson.gvp")
    path, rel = at.next_take(proj, 0, 0, audio_dir=str(tmp_path / "Prises"))
    assert path == str(tmp_path / "Prises" / "Chanson_pattern01_piste01_take_001.wav")
    assert rel == "../Prises/Chanson_pattern01_piste01_take_001.wav"
    assert at.resolve(proj, rel) == os.path.normpath(path) or \
        os.path.normpath(at.resolve(proj, rel)) == path


@pytest.mark.parametrize("shape, channels", [((441,), 1), ((441, 1), 1), ((441, 2), 2)])
def test_write_take_24_bits(tmp_path, shape, channels):
    path = str(tmp_path / "sous" / "dossier" / "t.wav")
    data = np.full(shape, 0.25, np.float32)
    at.write_take(path, data, 44100)
    info = sf.info(path)
    assert (info.subtype, info.channels, info.samplerate, info.frames) == \
        ("PCM_24", channels, 44100, 441)
    back, _ = sf.read(path)
    assert np.allclose(back, 0.25, atol=1e-6)


def test_resolve_and_relative(tmp_path):
    proj = str(tmp_path / "P" / "C.gvp")
    assert at.resolve(proj, "Audios/a.wav") == str(tmp_path / "P" / "Audios" / "a.wav")
    assert at.resolve(proj, "/abs/a.wav") == "/abs/a.wav"
    assert at.relative_to_project(proj, str(tmp_path / "P" / "Audios" / "a.wav")) == "Audios/a.wav"


@pytest.mark.parametrize("rel, expected", [
    ("Audios/Old_pattern01_piste01_take_001.wav", "Audios/New_pattern01_piste01_take_001.wav"),
    ("Audios/voix.wav", "Audios/voix.wav"),                     # autre nom : inchangé
    ("Audios/Old_notes.wav", "Audios/Old_notes.wav"),
    ("Old_pattern02_piste03_take_004.wav", "New_pattern02_piste03_take_004.wav"),
])
def test_renamed(rel, expected):
    assert at.renamed(rel, "Old", "New") == expected
    assert at.renamed(rel, "Old", "Old") == rel


def _take(proj, p=0, t=0):
    path, rel = at.next_take(proj, p, t)
    at.write_take(path, np.zeros(10, np.float32), 44100)
    return rel


def test_copy_takes_renamed_into_the_new_project(tmp_path):
    old = str(tmp_path / "PROJECTS" / "noname_001.gvp")
    new = str(tmp_path / "PROJECTS" / "Chanson" / "Chanson.gvp")
    rel = _take(old, 0, 2)
    mapping, missing = at.copy_takes(old, new, [rel, rel])
    assert mapping == {rel: "Audios/Chanson_pattern01_piste03_take_001.wav"} and missing == []
    assert os.path.isfile(at.resolve(new, mapping[rel]))
    assert os.path.isfile(at.resolve(old, rel))                 # rien d'effacé


def test_copy_takes_into_a_chosen_folder(tmp_path):
    old = str(tmp_path / "old.gvp")
    new = str(tmp_path / "P" / "Chanson.gvp")
    rel = _take(old)
    mapping, _ = at.copy_takes(old, new, [rel], new_audio_dir=str(tmp_path / "Prises"))
    assert mapping[rel] == "../Prises/Chanson_pattern01_piste01_take_001.wav"
    assert os.path.isfile(tmp_path / "Prises" / "Chanson_pattern01_piste01_take_001.wav")


def test_copy_takes_same_place_nothing_to_do(tmp_path):
    # même projet, même dossier : rien à copier, rien à signaler
    proj = str(tmp_path / "C.gvp")
    rel = _take(proj)
    mapping, missing = at.copy_takes(proj, proj, [rel, "Audios/absent.wav"])
    assert mapping[rel] == rel and missing == []


def test_copy_takes_missing_reported(tmp_path):
    old, new = str(tmp_path / "A.gvp"), str(tmp_path / "B" / "B.gvp")
    mapping, missing = at.copy_takes(old, new, ["Audios/absent.wav"])
    assert missing == ["Audios/absent.wav"]


@pytest.mark.parametrize("given, expected", [
    ("/p/Chanson.gvp", "/p/Chanson/Chanson.gvp"),
    ("/p/Chanson/Chanson.gvp", "/p/Chanson/Chanson.gvp"),      # déjà dans son dossier
    ("/p/Autre/Chanson.gvp", "/p/Autre/Chanson/Chanson.gvp"),
])
def test_project_folder_path(given, expected):
    assert at.project_folder_path(given) == expected


# ---------------------------------------------------------------------------
# Enregistrer sous : case, chemin, Parcourir…
# ---------------------------------------------------------------------------

class _Ctrl:
    def __init__(self, label=""):
        self.label, self.value, self.bound = label, None, None
    def SetValue(self, v):  self.value = v
    def GetValue(self):     return self.value
    def Bind(self, evt, fn): self.bound = fn


class _Customizer:
    def __init__(self):
        self.added = []
    def AddCheckBox(self, label):
        c = _Ctrl(label); self.added.append(("case", c)); return c
    def AddTextCtrl(self, label):
        c = _Ctrl(label); self.added.append(("champ", c)); return c
    def AddButton(self, label):
        c = _Ctrl(label); self.added.append(("bouton", c)); return c


class _DirDlg:
    def __init__(self, result, path):
        self.result, self.path, self.destroyed = result, path, False
    def ShowModal(self): return self.result
    def GetPath(self):   return self.path
    def Destroy(self):   self.destroyed = True


def test_hook_controls_and_defaults():
    hook = _ProjectFolderHook(audio_path="/p/C/Audios")
    cust = _Customizer()
    hook.AddCustomControls(cust)
    kinds = [(k, c.label) for k, c in cust.added]
    assert kinds == [("case", "Créer un nouveau dossier pour ce projet"),
                     ("champ", "Chemin des fichiers audios"), ("bouton", "Parcourir…")]
    assert cust.added[0][1].value is True and cust.added[1][1].value == "/p/C/Audios"
    hook.TransferDataFromCustomControls()
    assert hook.create_folder is True and not hook.audio_path_changed()


def test_hook_user_changes():
    hook = _ProjectFolderHook(audio_path="/p/C/Audios")
    cust = _Customizer()
    hook.AddCustomControls(cust)
    cust.added[0][1].SetValue(False)
    cust.added[1][1].SetValue("  /srv/prises  ")
    hook.TransferDataFromCustomControls()
    assert hook.create_folder is False and hook.audio_path == "/srv/prises"
    assert hook.audio_path_changed()


def test_hook_browse():
    hook = _ProjectFolderHook(audio_path="/p/C/Audios")
    cust = _Customizer()
    hook.AddCustomControls(cust)
    dlg = _DirDlg(wx.ID_OK, "/autre/Prises")
    hook.dir_dialog = lambda msg, start: dlg
    cust.added[2][1].bound(None)                                 # clic sur Parcourir…
    assert cust.added[1][1].value == "/autre/Prises" and dlg.destroyed
    dlg2 = _DirDlg(wx.ID_CANCEL, "/ignoré")
    hook.dir_dialog = lambda msg, start: dlg2
    hook.browse()
    assert cust.added[1][1].value == "/autre/Prises"


def test_hook_empty_path_is_no_change():
    hook = _ProjectFolderHook(audio_path="/p/C/Audios")
    hook.audio_path = ""
    assert not hook.audio_path_changed()


class _SaveDlg:
    """wx.FileDialog factice : le hook reçoit les choix de l'utilisateur."""
    choice = {}

    def __init__(self, *a, **kw):
        self.hook = None
    def SetCustomizeHook(self, hook):
        self.hook = hook
    def ShowModal(self):
        c = _SaveDlg.choice
        self.hook.create_folder = c.get("folder", True)
        if "audio" in c:
            self.hook.audio_path = c["audio"]
        return wx.ID_OK
    def GetPath(self):
        return _SaveDlg.choice["path"]
    def Destroy(self):
        pass


def _save_win(tmp_path, old_name="noname_001.gvp"):
    old = str(tmp_path / "PROJECTS" / old_name)
    live = Pattern()
    store = [Pattern(), Pattern()]
    win = SimpleNamespace(_projects_dir=str(tmp_path / "PROJECTS"), _project_path=old,
                          _player=SimpleNamespace(_pattern=live), _pattern_list=store,
                          statuses=[], saved=[])
    win._show_status = win.statuses.append
    win._save_project = lambda: win.saved.append((win._project_path, win._audio_dir))
    win._all_patterns = lambda: ProjectMixin._all_patterns(win)
    win._move_takes = lambda o, n, d="": ProjectMixin._move_takes(win, o, n, d)
    return win, old, live, store


def _save_as(win, **choice):
    _SaveDlg.choice = choice
    with patch("ui.mw_project.wx.FileDialog", _SaveDlg):
        ProjectMixin._save_project_as(win)


def test_save_as_in_its_own_folder(tmp_path):
    win, old, live, store = _save_win(tmp_path)
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson.gvp"))
    assert win._project_path == str(tmp_path / "PROJECTS" / "Chanson" / "Chanson.gvp")
    assert os.path.isdir(tmp_path / "PROJECTS" / "Chanson")
    assert win.saved == [(win._project_path, "")]


def test_save_as_without_folder(tmp_path):
    win, *_ = _save_win(tmp_path)
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson"), folder=False)
    assert win._project_path == str(tmp_path / "PROJECTS" / "Chanson.gvp")


def test_save_as_moves_takes_and_repoints_clips(tmp_path):
    win, old, live, store = _save_win(tmp_path)
    rel = _take(old, 1, 2)
    store[1]._tape[2].append(_clip(rel))
    live._tape[2].append(_clip(rel))
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson.gvp"))
    new_rel = "Audios/Chanson_pattern02_piste03_take_001.wav"
    assert store[1].audio_clips()[0][1].payload["file"] == new_rel
    assert live.audio_clips()[0][1].payload["file"] == new_rel
    assert os.path.isfile(at.resolve(win._project_path, new_rel))


def test_save_as_with_a_chosen_audio_folder(tmp_path):
    win, old, live, store = _save_win(tmp_path)
    rel = _take(old)
    live._tape[0].append(_clip(rel))
    prises = str(tmp_path / "Prises")
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson.gvp"), audio=prises)
    assert win._audio_dir == prises                              # hors du dossier : absolu
    assert live.audio_clips()[0][1].payload["file"] == \
        "../../Prises/Chanson_pattern01_piste01_take_001.wav"


def test_save_as_audio_folder_inside_the_project_kept_relative(tmp_path):
    win, *_ = _save_win(tmp_path)
    inside = str(tmp_path / "PROJECTS" / "Chanson" / "Voix")
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson.gvp"), audio=inside)
    assert win._audio_dir == "Voix"


def test_missing_takes_announced(tmp_path):
    win, old, live, store = _save_win(tmp_path)
    live._tape[0].append(_clip("Audios/perdue.wav"))
    _save_as(win, path=str(tmp_path / "PROJECTS" / "Chanson.gvp"))
    assert win.statuses == ["Prises audio introuvables : Audios/perdue.wav"]


def test_no_clip_nothing_to_move(tmp_path):
    win, *_ = _save_win(tmp_path)
    assert ProjectMixin._move_takes(win, "/a/b.gvp", "/c/d.gvp") == []


# ---------------------------------------------------------------------------
# Propriétés de piste : Type de piste, Entrée audio
# ---------------------------------------------------------------------------

@pytest.fixture
def frame():
    f = wx.Frame(None)
    f.Show()
    yield f
    f.Destroy()


def _rack():
    rack = Rack()
    rack.set_slot(1, InstrumentType.SYNTH, "Piano", {"patch": "p"})
    return rack


def _props(frame, **kw):
    return TrackPropertiesDialog(frame, 0, _rack(), 1, 100, 0, False, False, channel=2, **kw)


def test_kind_lists_first(frame):
    dlg = _props(frame, track_kind="midi", audio_inputs=["pipewire"])
    try:
        texts = [c.GetLabel() for c in dlg.GetChildren() if isinstance(c, (wx.StaticText, wx.CheckBox))]
        assert texts[:3] == ["Type de piste :", "Entrée audio :", "Mute"]
        kids = list(dlg.GetChildren())
        assert isinstance(kids[1], wx.ListBox) and isinstance(kids[3], wx.ListBox)
        assert [dlg._kind_list.GetString(i) for i in range(2)] == ["MIDI", "Audio"]
        assert [dlg._audio_in.GetString(i) for i in range(2)] == ["Entrée par défaut", "pipewire"]
    finally:
        dlg.Destroy()


@pytest.mark.gui                  # dialogue affiché, boucle d'événements (Phase 8 étape 17c1)
@pytest.mark.parametrize("kind", ["midi", "audio"])
def test_focus_on_the_kind_list(frame, kind):
    dlg = _props(frame, track_kind=kind, audio_inputs=[])
    try:
        dlg.Show()
        wx.SafeYield()
        assert wx.Window.FindFocus() is dlg._kind_list
    finally:
        dlg.Destroy()


@pytest.mark.gui                  # dialogue affiché, boucle d'événements (17c1)
def test_focus_on_mute_without_kind_list(frame):
    dlg = _props(frame)
    try:
        dlg.Show()
        wx.SafeYield()
        assert wx.Window.FindFocus() is dlg._mute
        assert dlg.get_track_kind() is None and dlg.get_audio_in() is None
    finally:
        dlg.Destroy()


def test_audio_track_greys_midi_settings(frame):
    dlg = _props(frame, track_kind="audio", audio_inputs=["pipewire"], audio_in="pipewire",
                 midi_ports=dict(inputs=[], outputs=[], midi_in="", midi_out=""))
    try:
        for w in (dlg._slots, dlg._channels, dlg._programs, dlg._midi_in, dlg._midi_out):
            assert not w.IsEnabled()
        assert dlg._audio_in.IsEnabled() and dlg._mute.IsEnabled() and dlg._vol.IsEnabled()
        assert (dlg.get_track_kind(), dlg.get_audio_in()) == ("audio", "pipewire")
    finally:
        dlg.Destroy()


def test_back_to_midi(frame):
    seen = []
    dlg = _props(frame, track_kind="audio", audio_inputs=[], on_kind_change=
                 lambda k, a: seen.append((k, a)))
    try:
        dlg._kind_list.SetSelection(0)
        dlg._kind_list.GetEventHandler().ProcessEvent(
            wx.CommandEvent(wx.wxEVT_LISTBOX, dlg._kind_list.GetId()))
        assert dlg._slots.IsEnabled() and not dlg._audio_in.IsEnabled()
        assert seen == [("midi", "")]
    finally:
        dlg.Destroy()


def test_absent_audio_input_kept(frame):
    dlg = _props(frame, track_kind="audio", audio_inputs=["pulse"], audio_in="Carte USB")
    try:
        assert dlg._audio_in.GetString(2) == "Carte USB — absent"
        assert dlg.get_audio_in() == "Carte USB"
    finally:
        dlg.Destroy()


# _track_properties_dialog (dialogue factice)

def _kind_dlg(result, kind=None, audio_in=None, live=True):
    class Dlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            Dlg.kw = kw
            ch = kw["channel"]
            info = kw["bank_info"](slot, ch)
            self.v = [slot, vol, pan, mute, solo, ch,
                      info["program"] if info else kw["slot_program"](slot)[1],
                      *kw["slot_gm_tuning"](slot),
                      info["msb"] if info else None, info["lsb"] if info else None]
            self.kind = (kw["track_kind"] if kind is None else kind,
                         kw["audio_in"] if audio_in is None else audio_in)
            if live:
                kw["on_kind_change"](*self.kind)
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
        def get_midi_in(self):   return None
        def get_midi_out(self):  return None
        def get_track_kind(self): return self.kind[0]
        def get_audio_in(self):   return self.kind[1]
        def Destroy(self):       pass
    return Dlg


def _kind_win(tmp_path, inputs=("pipewire",)):
    win = _RackWin(rack_mode=False)
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"audio_inputs": list(inputs)}), encoding="utf-8")
    from app_config import AppConfig
    os.makedirs(tmp_path / "app" / "data", exist_ok=True)
    win._cfg = AppConfig(str(tmp_path / "app"), prefs_path=str(path))
    win._warn_track_midi_outs = lambda: []
    return win


def _run_kind(win, dlg):
    with patch("ui.mw_tracks.TrackPropertiesDialog", dlg):
        win._track_properties_dialog()


def test_kind_passed_to_the_dialog(tmp_path):
    win = _kind_win(tmp_path)
    win._router._track_kinds[0] = "audio"
    win._router._track_audio_ins[0] = "pipewire"
    dlg = _kind_dlg(wx.ID_CANCEL, live=False)
    _run_kind(win, dlg)
    assert (dlg.kw["track_kind"], dlg.kw["audio_inputs"], dlg.kw["audio_in"]) == \
        ("audio", ["pipewire"], "pipewire")


def test_ok_keeps_the_kind_and_counts_as_a_change(tmp_path):
    win = _kind_win(tmp_path)
    _run_kind(win, _kind_dlg(wx.ID_OK, kind="audio", audio_in="pipewire"))
    assert win._router._track_kinds[0] == "audio" and win._router._track_audio_ins[0] == "pipewire"
    assert win.undos == ["Propriétés piste 1"]
    assert win.statuses[-1] == "Piste 1: propriétés mises à jour"


def test_cancel_restores_the_kind(tmp_path):
    win = _kind_win(tmp_path)
    _run_kind(win, _kind_dlg(wx.ID_CANCEL, kind="audio", audio_in="pipewire"))
    assert win._router._track_kinds[0] == "midi" and win._router._track_audio_ins[0] == ""
    assert win.undos == ["Propriétés piste 1", "pop"]


def test_kind_change_cuts_the_track_notes(tmp_path, monkeypatch):
    win = _kind_win(tmp_path)
    cut = []
    monkeypatch.setattr(win._router, "cut_track_notes", lambda t: cut.append(t))
    _run_kind(win, _kind_dlg(wx.ID_OK, kind="audio"))
    assert 0 in cut


# ---------------------------------------------------------------------------
# Vraie fenêtre principale : enregistrer puis rouvrir
# ---------------------------------------------------------------------------

@pytest.mark.gui
def test_real_main_window_save_and_reopen(isolated_preferences, tmp_path, monkeypatch):
    """Une seule vraie MainWindow (clients ALSA)."""
    from ui.main_window import MainWindow
    monkeypatch.setattr(wx, "CallAfter", main_thread_call_after())
    win = None
    try:
        win = MainWindow(no_fluidsynth=True, no_sfizz=True)
        path = str(tmp_path / "Chanson" / "Chanson.gvp")
        os.makedirs(os.path.dirname(path))
        win._router._track_kinds[3] = "audio"
        win._router._track_audio_ins[3] = "pipewire"
        win._player._pattern._tape[3].append(_clip("Audios/x.wav", time=4))
        win._project_path = path
        win._audio_dir = "../Prises"
        win._save_project()
        data = json.load(open(path, encoding="utf-8"))
        assert data["audio_dir"] == "../Prises"
        win._audio_dir = ""
        win._router._track_kinds[3] = "midi"
        win._load_project()
        assert win._audio_dir == "../Prises"
        assert win._router._track_kinds[3] == "audio"
        assert win._router._track_audio_ins[3] == "pipewire"
        assert win._player._pattern.audio_clips(3)[0][1].payload["file"] == "Audios/x.wav"
    finally:
        if win is not None:
            win._router.wait_loaded()
            win._close_midi_devices()
            win._audio_driver.close()
            win.Destroy()
