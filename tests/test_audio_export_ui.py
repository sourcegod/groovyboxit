#python3
"""
    File: tests/test_audio_export_ui.py
    Tests de l'interface des exports audio, Phase 8 étape 1i1 (docs/DESIGN.md
    § Phase 8 étape 1a W8, § 1h2, § 1h6, § 1h11 W21) : Alt+Shift+W
    (_export_audio) et Alt+Shift+S (_export_audio_selection) — ordre des
    dialogues (fichier puis paramètres), annulations, extension, nom
    proposé, dossier et options gardés pour la session, pause de la
    lecture, export déjà en cours, fil de rendu et statut, erreur, source
    sélection (limiteurs, pistes) ou presse-papier de la fenêtre,
    raccourcis dans la fenêtre principale et l'éditeur MIDI ; un rendu réel
    jusqu'au fichier.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest
import soundfile as sf
import wx
from types import SimpleNamespace

import audio_export
import ui.mw_project as mwp
import ui.midi_editor_window as mew
from ui.mw_project import ProjectMixin
from ui.dialogs import SelectionExportDialog
from pattern import Pattern, TapeEvent, ETYPE_GRID
from rack import Rack, InstrumentType
from track_editor import TrackEditor
from track_router import TrackRouter
from sound_device_driver import Mixer
from sound_manager import SoundManager
from voice_manager import VoiceManager
from test_key_manager import FakeWindow, FakeEvent
from ui.key_manager import KeyManager

SR = 44100


# ---------------------------------------------------------------------------
# Fenêtre factice : vrai ProjectMixin
# ---------------------------------------------------------------------------

class _Player:
    def __init__(self, playing=False):
        self.playing = playing
        self.paused  = 0
        self.bpm, self.pan, self.volume = 120, -20, 80
        self.voice_manager = VoiceManager()
        self._cur_track = 4
        self._pattern = Pattern()
        self._pattern._bpm = 120
        self._pattern._num_bars = 4
    def pause_pattern(self):
        self.paused += 1
        self.playing = False
    def tempo_map(self):
        return self._pattern.tempo_map(start_bpm=self.bpm)


class _Router:
    def __init__(self):
        self.stopped = 0
    def stop_all_synth_voices(self):
        self.stopped += 1


class _Window(ProjectMixin):
    def __init__(self, exports_dir, playing=False):
        self._player = _Player(playing)
        self._router = _Router()
        self._track_editor = TrackEditor()
        self._pattern_list = [Pattern() for _ in range(3)]
        self._pattern_list[1]._name = "Intro A"
        self._cur_pattern_idx = 1
        self._exports_dir = exports_dir
        self.statuses = []
    def _show_status(self, msg):
        self.statuses.append(msg)


class Dialogs:
    """Faux dialogues : fichier, paramètres, source. Chaque ouverture est
    notée dans self.order, avec ses arguments."""

    def __init__(self, file_ok=True, path="/tmp/x/out", opts_ok=True,
                 opts=(1, 2, True, 1, -10), sel_ok=True, source=0, window=(16, 31)):
        self.order, self.file_kw, self.opts_args, self.sel_args = [], {}, None, None
        d = self

        class FileDlg:
            def __init__(self, parent, title, **kw):
                d.order.append("fichier")
                d.file_kw = dict(kw, parent=parent, title=title)
            def ShowModal(self): return wx.ID_OK if file_ok else wx.ID_CANCEL
            def GetPath(self):   return path
            def Destroy(self):   pass

        class OptsDlg:
            def __init__(self, parent, *args, **kw):
                d.order.append("paramètres")
                d.opts_args = (parent, args, kw)
            def ShowModal(self): return wx.ID_OK if opts_ok else wx.ID_CANCEL
            def get_end_idx(self):     return opts[0]
            def get_format_idx(self):  return opts[1]
            def get_normalize(self):   return opts[2]
            def get_measure_idx(self): return opts[3]
            def get_level_db(self):    return opts[4]
            def Destroy(self): pass

        class SelDlg:
            SOURCE_SELECTION = SelectionExportDialog.SOURCE_SELECTION
            def __init__(self, parent, *args):
                d.order.append("source")
                d.sel_args = (parent, args)
            def ShowModal(self): return wx.ID_OK if sel_ok else wx.ID_CANCEL
            def get_source_idx(self): return source
            def get_window(self):     return window
            def Destroy(self): pass

        self.FileDlg, self.OptsDlg, self.SelDlg = FileDlg, OptsDlg, SelDlg


@pytest.fixture
def env(monkeypatch):
    """Dialogues factices, wx.CallAfter synchrone, rendu et écriture
    simulés (paramètres notés)."""
    rendered, written = [], []

    def install(dialogs):
        monkeypatch.setattr(mwp.wx, "FileDialog", dialogs.FileDlg)
        monkeypatch.setattr(mwp, "AudioExportDialog", dialogs.OptsDlg)
        monkeypatch.setattr(mwp, "SelectionExportDialog", dialogs.SelDlg)
        return dialogs

    def fake_render(**kw):
        rendered.append(kw)
        kw["progress"](0.5)
        kw["status_cb"]("Erreur slot 04: absent")
        return audio_export.RenderResult(np.zeros((SR, 2), np.float32), SR, SR, 0, False, 2,
                                         looped=True)

    def fake_write(path, res, subtype, normalize, measure, level):
        written.append((path, subtype, normalize, measure, level))
        return 3.0, -2.0

    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(audio_export, "render_pattern", fake_render)
    monkeypatch.setattr(audio_export, "write_wav", fake_write)
    return SimpleNamespace(install=install, rendered=rendered, written=written)


def _wait(win):
    if win._audio_export_thread is not None:
        win._audio_export_thread.join(5)


# ---------------------------------------------------------------------------
# Alt+Shift+W : parcours
# ---------------------------------------------------------------------------

def test_file_dialog_before_options(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path / "EXPORTS"))
    win._export_audio()
    _wait(win)
    assert d.order == ["fichier", "paramètres"]
    assert len(env.rendered) == 1


def test_cancel_file_dialog_stops_before_options(tmp_path, env):
    d = env.install(Dialogs(file_ok=False))
    win = _Window(str(tmp_path))
    win._export_audio()
    assert d.order == ["fichier"]
    assert win.statuses == ["Export audio annulé"]
    assert win._audio_export_thread is None and env.rendered == []


def test_cancel_options_renders_nothing(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav"), opts_ok=False))
    win = _Window(str(tmp_path))
    win._export_audio()
    assert d.order == ["fichier", "paramètres"]
    assert win.statuses == ["Export audio annulé"]
    assert env.rendered == [] and win._audio_export_opts == ProjectMixin._audio_export_opts


def test_wav_extension_added_and_name_proposed(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "sans_extension")))
    win = _Window(str(tmp_path / "EXPORTS"))
    win._export_audio()
    _wait(win)
    assert env.written[0][0] == str(tmp_path / "sans_extension.wav")
    assert d.file_kw["defaultFile"] == "Pat_02_Intro_A.wav"
    assert d.file_kw["title"] == "Exporter le pattern en WAV…"
    assert d.file_kw["wildcard"] == "Fichiers WAV (*.wav)|*.wav"
    assert d.file_kw["style"] & wx.FD_OVERWRITE_PROMPT


def test_exports_dir_created_then_last_dir_remembered(tmp_path, env):
    exports = tmp_path / "EXPORTS"
    d = env.install(Dialogs(path=str(tmp_path / "ailleurs" / "a.wav")))
    win = _Window(str(exports))
    win._export_audio()
    _wait(win)
    assert d.file_kw["defaultDir"] == str(exports) and exports.is_dir()
    win._export_audio()
    _wait(win)
    assert d.file_kw["defaultDir"] == str(tmp_path / "ailleurs")


def test_options_kept_for_session_and_passed_on(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav"), opts=(1, 2, True, 1, -10)))
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    _, args, kw = d.opts_args
    assert args == ProjectMixin._audio_export_opts          # défauts au premier appel
    assert (kw["level_min"], kw["level_max"]) == (audio_export.LEVEL_MIN_DB,
                                                  audio_export.LEVEL_MAX_DB)
    assert win._audio_export_opts == (1, 2, True, 1, -10)
    assert env.written[0][1:] == ("FLOAT", True, "rms", -10)
    assert env.rendered[0]["end"] == audio_export.END_TAIL
    win._export_audio()
    _wait(win)
    assert d.opts_args[1] == (1, 2, True, 1, -10)              # gardés pour la session


def test_render_params_from_player(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path))
    win._player._pattern._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 90},
                                                   time=3))
    win._export_audio()
    _wait(win)
    kw = env.rendered[0]
    assert kw["pattern"] is not win._player._pattern                  # copie
    assert [e.time for e in kw["pattern"]._tape[0]] == [3]
    assert (kw["master_pan"], kw["master_volume"]) == (-20, 80)
    assert kw["voice_manager"] is win._player.voice_manager
    assert kw["router"] is win._router
    assert kw["window"] is None and kw["tracks"] is None
    assert kw["tempo_map"].start_bpm == 120


def test_playback_paused_first(tmp_path, env):
    env.install(Dialogs(file_ok=False))
    win = _Window(str(tmp_path), playing=True)
    win._export_audio()
    assert win._player.paused == 1 and win._router.stopped == 1
    stopped = _Window(str(tmp_path))
    stopped._export_audio()
    assert stopped._player.paused == 0 and stopped._router.stopped == 0


def test_export_already_running(tmp_path, env):
    d = env.install(Dialogs())
    win = _Window(str(tmp_path))
    win._audio_export_thread = SimpleNamespace(is_alive=lambda: True)
    win._export_audio()
    win._export_audio_selection()
    assert d.order == []
    assert win.statuses == ["Export audio déjà en cours"] * 2


def test_status_progress_and_report(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "Pat.wav"), opts=(0, 0, True, 2, -6)))
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    assert win.statuses[0] == "Export audio : 0 %"
    assert "Export audio : 50 %" in win.statuses
    last = win.statuses[-1]
    assert last.startswith("Pattern 02 exporté en WAV : Pat.wav — 1,00 s, boucle exacte, 16 bits")
    assert "normalisé à −6 LUFS-I : +3,00 dB" in last
    assert "limiteur : −2,00 dB au plus" in last
    assert last.endswith("Erreur slot 04: absent")


def test_render_error_announced(tmp_path, env, monkeypatch):
    env.install(Dialogs(path=str(tmp_path / "a.wav")))
    def boom(**kw):
        raise RuntimeError("disque plein")
    monkeypatch.setattr(audio_export, "render_pattern", boom)
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    assert win.statuses[-1] == "ERREUR export audio : disque plein"


def test_given_parent_and_status_used(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path))
    editor, msgs = object(), []
    win._export_audio(parent=editor, status=msgs.append)
    _wait(win)
    assert d.file_kw["parent"] is editor and d.opts_args[0] is editor
    assert win.statuses == [] and msgs[-1].startswith("Pattern 02 exporté")


def test_closed_window_status_ignored(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path))
    calls = []
    def gone(msg):
        calls.append(msg)
        if len(calls) > 1:
            raise RuntimeError("wrapped C/C++ object has been deleted")
    win._export_audio(status=gone)
    _wait(win)
    assert env.written                                       # l'export va au bout


# ---------------------------------------------------------------------------
# Alt+Shift+S : sélection ou presse-papier
# ---------------------------------------------------------------------------

def test_selection_dialog_then_file_then_options(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "s.wav"), window=(16, 31)))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.set_lim_left(16)
    te.set_lim_right(31)
    te._sel_tracks = {5, 2}
    win._export_audio_selection()
    _wait(win)
    assert d.order == ["source", "fichier", "paramètres"]
    parent, args = d.sel_args
    pat = win._player._pattern
    assert args == (pat._num_bars, pat._num_beats, pat._num_steps, 16, 31, 0)
    assert d.file_kw["defaultFile"] == "Pat_02_Intro_A_selection.wav"
    assert d.file_kw["title"] == "Exporter la sélection en WAV…"
    kw = env.rendered[0]
    assert kw["window"] == (16, 32) and kw["tracks"] == {2, 5}
    assert kw["pattern"] is not pat
    assert win.statuses[-1].startswith(
        "Sélection (pistes 3, 6 ; 2:1:1 à 2:4:4) exportée en WAV : s.wav")


def test_selection_without_selected_tracks_uses_current_track(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), window=(0, 3)))
    win = _Window(str(tmp_path))
    win._export_audio_selection()
    _wait(win)
    assert env.rendered[0]["tracks"] == {4}
    assert "Sélection (piste 5 ; 1:1:1 à 1:1:4)" in win.statuses[-1]


def test_selection_cancel(tmp_path, env):
    d = env.install(Dialogs(sel_ok=False))
    win = _Window(str(tmp_path))
    win._export_audio_selection()
    assert d.order == ["source"] and win.statuses == ["Export audio annulé"]
    assert win._audio_sel_source == 0


def test_selection_limiters_not_moved(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), window=(4, 7)))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.set_lim_left(16)
    te.set_lim_right(31)
    win._export_audio_selection()
    _wait(win)
    assert env.rendered[0]["window"] == (4, 8)
    assert (te._lim_left, te._lim_right) == (16, 31)


def test_track_clipboard_main_window(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "c.wav"), source=1))
    win = _Window(str(tmp_path))
    pat = win._player._pattern
    pat._tape[6].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 90}, time=18))
    te = win._track_editor
    te._sel_tracks = {6}
    te.set_lim_left(16)
    te.set_lim_right(31)
    te.copy(pat, 0)
    win._export_audio_selection()
    _wait(win)
    assert win._audio_sel_source == 1
    assert d.file_kw["defaultFile"] == "Pat_02_Intro_A_presse-papier.wav"
    kw = env.rendered[0]
    assert [e.time for e in kw["pattern"]._tape[6]] == [2.0]
    assert kw["window"] is None and kw["tracks"] is None
    assert win.statuses[-1].startswith("Presse-papier (1 piste, 1 mesure) exporté en WAV : c.wav")
    win._export_audio_selection()                           # source gardée pour la session
    assert d.sel_args[1][-1] == 1


def test_note_clipboard_in_midi_editor(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "n.wav"), source=1))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.copy_events([{"type": "note", "etype": ETYPE_GRID, "track": 3, "pad": 1, "vel": 90,
                     "offset": 21, "dur": 500, "dur_override": 0, "channel": 0},
                    {"type": "note", "etype": ETYPE_GRID, "track": 7, "pad": 2, "vel": 90,
                     "offset": 40, "dur": 500, "dur_override": 0, "channel": 0}])
    win._export_audio_selection(editor=True)
    _wait(win)
    kw = env.rendered[0]
    assert kw["pattern"]._num_bars == 2
    assert [e.time for e in kw["pattern"]._tape[3]] == [5]
    assert "Presse-papier (2 pistes, 2 mesures)" in win.statuses[-1]


@pytest.mark.parametrize("editor", (False, True))
def test_empty_clipboard(tmp_path, env, editor):
    d = env.install(Dialogs(source=1))
    win = _Window(str(tmp_path))
    if editor:                                               # presse-papier des pistes plein
        win._track_editor.copy(win._player._pattern, 0)
    win._export_audio_selection(editor=editor)
    assert d.order == ["source"]
    assert win.statuses == ["Presse-papier vide"] and env.rendered == []


# ---------------------------------------------------------------------------
# Dialogue de la source
# ---------------------------------------------------------------------------

def test_selection_dialog_fields():
    dlg = SelectionExportDialog(None, 4, 4, 16, 16, 47, 0)
    try:
        assert (dlg._left.GetValue(), dlg._right.GetValue()) == ("2:1:1", "3:4:4")
        assert dlg._left.GetName() == "Limiteur gauche"
        assert dlg._right.GetName() == "Limiteur droit"
        assert dlg.get_window() == (16, 47) and dlg._validate() is None
        dlg._left.SetValue("4:1:1")
        assert dlg._validate() == "Le limiteur droit est avant le limiteur gauche"
        assert dlg.get_window() is None
        dlg._left.SetValue("x")
        assert dlg._validate().startswith("Position invalide")
        dlg._source_lb.SetSelection(1)
        dlg._update_enabled()
        assert not dlg._left.IsEnabled() and dlg._validate() is None
    finally:
        dlg.Destroy()


def test_selection_dialog_whole_pattern_without_limiters():
    dlg = SelectionExportDialog(None, 2, 3, 12, source_idx=1)
    try:
        assert (dlg._left.GetValue(), dlg._right.GetValue()) == ("1:1:1", "2:3:4")
        assert dlg.get_source_idx() == 1 and not dlg._right.IsEnabled()
    finally:
        dlg.Destroy()


def test_selection_dialog_invalid_keeps_dialog_open(monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda msg, *a, **k: shown.append(msg))
    dlg = SelectionExportDialog(None, 4, 4, 16, 16, 47)
    ended = []
    dlg.EndModal = ended.append
    try:
        dlg._right.SetValue("1:1:1")
        dlg._on_ok(None)
        assert shown == ["Le limiteur droit est avant le limiteur gauche"] and ended == []
        dlg._right.SetValue("4:1:1")
        dlg._on_ok(None)
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Raccourcis
# ---------------------------------------------------------------------------

def test_alt_shift_w_and_s_main_window():
    # KeyManager construit sur la wx.App de la session (conftest) : make_km()
    # en crée une autre que teardown() détruit, ce qui casse les fichiers de
    # tests suivants (PyNoAppError)
    win = FakeWindow()
    km = KeyManager(win)
    calls = []
    win._export_audio = lambda: calls.append("W")
    win._export_audio_selection = lambda: calls.append("S")
    km.handle(FakeEvent(key=ord('W'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('S'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('W'), alt=True))                # Alt seul : rien
    km.handle(FakeEvent(key=ord('S'), alt=True))
    assert calls == ["W", "S"]


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
        self.calls = calls = []
        class Parent:
            def _export_audio(self, parent=None, status=None):
                calls.append(("W", parent, status))
            def _export_audio_selection(self, parent=None, status=None, editor=False):
                calls.append(("S", parent, status, editor))
            _key_manager = SimpleNamespace(handle_transport=lambda evt: False)
        self._parent = Parent()
    def _set_status(self, msg): pass


def test_alt_shift_w_and_s_midi_editor():
    ed = _FakeEditor()
    for key in ('W', 'S'):
        evt = _FakeKey(ord(key), shift=True, alt=True)
        ed._on_key(evt)
        assert evt.skipped is False
    assert ed.calls == [("W", ed, ed._set_status), ("S", ed, ed._set_status, True)]


# ---------------------------------------------------------------------------
# Rendu réel jusqu'au fichier
# ---------------------------------------------------------------------------

def test_real_render_selection_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    wav = str(tmp_path / "imp.wav")
    x = np.zeros(2000, np.float32)
    x[0] = 0.5
    sf.write(wav, x, SR)
    drv = Mixer()
    snd = SoundManager([wav] * 16, wav, wav, driver=drv)
    snd.load_sounds()
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    win = _Window(str(tmp_path))
    win._router = TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=drv)
    win._player.volume = 100
    pat = win._player._pattern
    for t, tr in ((0, 0), (20, 1), (24, 2)):
        pat._tape[tr].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=t))
    win._track_editor._sel_tracks = {1, 2}
    out = str(tmp_path / "sel.wav")
    win._start_audio_export(out, (1, 2, False, 2, -14), win._show_status,
                            win._selection_job((16, 31)))
    _wait(win)
    y, sr = sf.read(out, dtype="float32")
    assert sf.info(out).subtype == "FLOAT" and len(y) == 2 * SR
    onsets = list(np.flatnonzero(np.abs(y[:, 0]) > 1e-3))
    assert onsets[:2] == [round(4 * 0.125 * SR), round(8 * 0.125 * SR)]
    assert win.statuses[-1].startswith("Sélection (pistes 2, 3 ; 2:1:1 à 2:4:4) exportée")
