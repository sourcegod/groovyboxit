#python3
"""
    File: tests/test_audio_export_ui.py
    Tests de l'interface des exports audio, Phase 8 étape 1i1 (docs/DESIGN.md
    § Phase 8 étape 1a W8, § 1h2, § 1h6, § 1h11 W21), réécrits en Phase 8
    étape 15c1 pour le dialogue unique (§ 15a X1-X7 : source dans le
    dialogue, paramètres PUIS nom du fichier, Alt+Shift+S retiré) :
    Alt+Shift+W (_export_audio_choose, _export_audio) — annulations, extension, nom
    proposé, dossier et options gardés pour la session, pause de la
    lecture, export déjà en cours, fil de rendu et statut, erreur, source
    sélection (limiteurs, pistes) ou presse-papier de la fenêtre,
    raccourcis dans la fenêtre principale et l'éditeur MIDI ; un rendu réel
    jusqu'au fichier. Pistes séparées (Phase 8 étape 2m1, § 2a E3, E4,
    E12-E14) : Sortie passée au dialogue et gardée pour la session, mix
    seul, stems seuls (mix rendu, pas écrit), mix + stems, gain du mix
    commun, stems silencieux omis, noms des slots, sélection, presse-papier,
    avancement, compte rendu, rendu réel (somme des stems = mix). Choix
    Pistes d'Alt+Shift+S (Phase 8 étape 2o1, § 2a E16) : dialogue (liste,
    activation selon la source, Entrée, ordre de tabulation), toutes les
    pistes entre les limiteurs en mix et en stems, choix gardé pour la
    session, éditeur MIDI, rendu réel. Mot du compte rendu et de la fin
    pour une sélection ou un presse-papier (Phase 8 étape 2o3).
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

from audio import audio_export
import ui.mw_project as mwp
import ui.midi_editor_window as mew
from ui.mw_project import ProjectMixin
from ui.dialogs import AudioExportDialog
from song import Song
from pattern import Pattern, TapeEvent, ETYPE_GRID
from rack import Rack, InstrumentType
from track_editor import TrackEditor
from track_router import TrackRouter
from audio.sound_device_driver import Mixer
from audio.sound_manager import SoundManager
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
        self._song_list = [Song() for _ in range(2)]        # sources du dialogue (15b1)
        self._cur_song_idx = 0
        self._exports_dir = exports_dir
        self.statuses = []
    def _show_status(self, msg):
        self.statuses.append(msg)


class Dialogs:
    """Faux dialogues : « Exporter en audio » (paramètres) puis fichier.
    Chaque ouverture est notée dans self.order, avec ses arguments. source
    None : la source proposée par l'appli (source_idx)."""

    SEL, CLIP = AudioExportDialog.SOURCE_SELECTION, AudioExportDialog.SOURCE_CLIPBOARD

    def __init__(self, file_ok=True, path="/tmp/x/out", opts_ok=True,
                 opts=(1, 2, True, 1, -10), source=None, window=(16, 31),
                 output=0, only=False, mutes=True, solos=True):
        self.order, self.file_kw, self.opts_args = [], {}, None
        d = self

        class FileDlg:
            def __init__(self, parent, title, **kw):
                d.order.append("fichier")
                d.file_kw = dict(kw, parent=parent, title=title)
            def ShowModal(self): return wx.ID_OK if file_ok else wx.ID_CANCEL
            def GetPath(self):   return path
            def Destroy(self):   pass

        class OptsDlg:
            SOURCE_PATTERN, SOURCE_SONG, SOURCE_SELECTION, SOURCE_CLIPBOARD = range(4)
            def __init__(self, parent, *args, **kw):
                d.order.append("paramètres")
                d.opts_args = (parent, args, kw)
                self._source = kw["source_idx"] if source is None else source
            def ShowModal(self): return wx.ID_OK if opts_ok else wx.ID_CANCEL
            def get_source_idx(self):      return self._source
            def get_selected_tracks(self): return only
            def get_use_mutes(self):       return mutes
            def get_use_solos(self):       return solos
            def get_window(self):          return window
            def get_end_idx(self):     return opts[0]
            def get_format_idx(self):  return opts[1]
            def get_normalize(self):   return opts[2]
            def get_measure_idx(self): return opts[3]
            def get_level_db(self):    return opts[4]
            def get_output_idx(self):  return output          # Sortie (2l1)
            def Destroy(self): pass

        self.FileDlg, self.OptsDlg = FileDlg, OptsDlg


@pytest.fixture
def env(monkeypatch):
    """Dialogues factices, wx.CallAfter synchrone, rendu et écriture
    simulés (paramètres notés)."""
    rendered, written = [], []

    def install(dialogs):
        monkeypatch.setattr(mwp.wx, "FileDialog", dialogs.FileDlg)
        monkeypatch.setattr(mwp, "AudioExportDialog", dialogs.OptsDlg)
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

def test_options_dialog_before_file(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path / "EXPORTS"))
    win._export_audio()
    _wait(win)
    assert d.order == ["paramètres", "fichier"]               # 15b1 : paramètres d'abord
    assert len(env.rendered) == 1


def test_cancel_file_dialog_renders_nothing(tmp_path, env):
    d = env.install(Dialogs(file_ok=False))
    win = _Window(str(tmp_path))
    win._export_audio()
    assert d.order == ["paramètres", "fichier"]
    assert win.statuses == ["Export audio annulé"]
    assert win._audio_export_thread is None and env.rendered == []


def test_cancel_options_stops_before_file(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav"), opts_ok=False))
    win = _Window(str(tmp_path))
    win._export_audio()
    assert d.order == ["paramètres"]
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
    win._export_audio_choose()
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
# Sources Sélection et Presse-papier (Alt+Shift+S avant 15b1)
# ---------------------------------------------------------------------------

def test_selection_source_then_file(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL, window=(16, 31),
                            only=True))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.set_lim_left(16)
    te.set_lim_right(31)
    te._sel_tracks = {5, 2}
    win._export_audio_choose()
    _wait(win)
    assert d.order == ["paramètres", "fichier"]
    kw = d.opts_args[2]
    pat = win._player._pattern
    assert (kw["num_bars"], kw["num_beats"], kw["num_steps"]) == \
        (pat._num_bars, pat._num_beats, pat._num_steps)
    assert (kw["lim_left"], kw["lim_right"]) == (16, 31)
    assert d.file_kw["defaultFile"] == "Pat_02_Intro_A_selection.wav"
    assert d.file_kw["title"] == "Exporter la sélection en WAV…"
    kw = env.rendered[0]
    assert kw["window"] == (16, 32) and kw["tracks"] == {2, 5}
    assert kw["pattern"] is not pat
    assert win.statuses[-1].startswith(
        "Sélection (pistes 3, 6 ; 2:1:1 à 2:4:4) exportée en WAV : s.wav")


def test_selection_without_selected_tracks_uses_current_track(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL, window=(0, 3),
                        only=True))
    win = _Window(str(tmp_path))
    win._export_audio_choose()
    _wait(win)
    assert env.rendered[0]["tracks"] == {4}
    assert "Sélection (piste 5 ; 1:1:1 à 1:1:4)" in win.statuses[-1]


def test_selection_cancel(tmp_path, env):
    d = env.install(Dialogs(opts_ok=False, source=Dialogs.SEL))
    win = _Window(str(tmp_path))
    win._export_audio_choose()
    assert d.order == ["paramètres"] and win.statuses == ["Export audio annulé"]
    assert win._audio_src == 0                                 # annulé : source inchangée


def test_selection_limiters_not_moved(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL, window=(4, 7)))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.set_lim_left(16)
    te.set_lim_right(31)
    win._export_audio_choose()
    _wait(win)
    assert env.rendered[0]["window"] == (4, 8)
    assert (te._lim_left, te._lim_right) == (16, 31)


def test_track_clipboard_main_window(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "c.wav"), source=Dialogs.CLIP))
    win = _Window(str(tmp_path))
    pat = win._player._pattern
    pat._tape[6].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 90}, time=18))
    te = win._track_editor
    te._sel_tracks = {6}
    te.set_lim_left(16)
    te.set_lim_right(31)
    te.copy(pat, 0)
    win._export_audio_choose()
    _wait(win)
    assert win._audio_src == Dialogs.CLIP
    assert d.file_kw["defaultFile"] == "Pat_02_Intro_A_presse-papier.wav"
    kw = env.rendered[0]
    assert [e.time for e in kw["pattern"]._tape[6]] == [2.0]
    assert kw["window"] is None and kw["tracks"] is None
    assert win.statuses[-1].startswith("Presse-papier (1 piste, 1 mesure) exporté en WAV : c.wav")
    win._export_audio_choose()                              # source gardée pour la session
    assert d.opts_args[2]["source_idx"] == Dialogs.CLIP


def test_note_clipboard_in_midi_editor(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "n.wav"), source=Dialogs.CLIP))
    win = _Window(str(tmp_path))
    te = win._track_editor
    te.copy_events([{"type": "note", "etype": ETYPE_GRID, "track": 3, "pad": 1, "vel": 90,
                     "offset": 21, "dur": 500, "dur_override": 0, "channel": 0},
                    {"type": "note", "etype": ETYPE_GRID, "track": 7, "pad": 2, "vel": 90,
                     "offset": 40, "dur": 500, "dur_override": 0, "channel": 0}])
    win._export_audio_choose(editor=True)
    _wait(win)
    kw = env.rendered[0]
    assert kw["pattern"]._num_bars == 2
    assert [e.time for e in kw["pattern"]._tape[3]] == [5]
    assert "Presse-papier (2 pistes, 2 mesures)" in win.statuses[-1]


@pytest.mark.parametrize("editor", (False, True))
def test_empty_clipboard(tmp_path, env, editor):
    d = env.install(Dialogs(source=Dialogs.CLIP))
    win = _Window(str(tmp_path))
    if editor:                                               # presse-papier des pistes plein
        win._track_editor.copy(win._player._pattern, 0)
    win._export_audio_choose(editor=editor)
    assert d.order == ["paramètres"]                         # pas de dialogue du fichier
    assert win.statuses == ["Presse-papier vide"] and env.rendered == []


# ---------------------------------------------------------------------------
# Dialogue « Exporter en audio » (Phase 8 étape 15b1, § 15a X4)
# ---------------------------------------------------------------------------

SOURCES = ["Pattern courant (Pat_02 Intro A)", "Song courant (Song_01, vide)",
           "Sélection", "Presse-papier"]


def _dialog(**kw):
    kw.setdefault("source_labels", SOURCES)
    return AudioExportDialog(None, **kw)


def test_dialog_source_first_with_focus():
    dlg = _dialog(source_idx=1)
    try:
        assert dlg.GetTitle() == "Exporter en audio"
        assert dlg._source_lb.GetStrings() == [f"Source : {n}" for n in SOURCES]
        assert dlg.get_source_idx() == 1
        assert wx.Window.FindFocus() in (dlg._source_lb, None)
    finally:
        dlg.Destroy()


def test_dialog_tab_order():
    """Ordre de création : Source, les trois cases, début, fin de la sélection,
    Fin, Format, Sortie, Normaliser, Mesure, Niveau, boutons ; libellés
    créés avant leur champ."""
    dlg = _dialog()
    try:
        focusable = [c for c in dlg.GetChildren() if not isinstance(c, wx.StaticText)]
        assert focusable[:12] == [dlg._source_lb, dlg._tracks_cb, dlg._mutes_cb, dlg._solos_cb,
                                  dlg._left, dlg._right, dlg._end_lb, dlg._format_lb,
                                  dlg._output_lb, dlg._normalize_cb, dlg._measure_lb, dlg._level]
        children = list(dlg.GetChildren())
        for field, label in ((dlg._left, "Début de la sélection"),
                             (dlg._right, "Fin de la sélection"), (dlg._level, "Niveau visé")):
            before = children[children.index(field) - 1]
            assert isinstance(before, wx.StaticText) and before.GetLabel().startswith(label)
    finally:
        dlg.Destroy()


def test_dialog_checkboxes():
    dlg = _dialog(selected_tracks=True, use_mutes=False, use_solos=True)
    try:
        assert dlg._tracks_cb.GetLabel() == "Exporter les pistes sélectionnées"
        assert dlg._mutes_cb.GetLabel() == "Tenir compte des Mutes"
        assert dlg._solos_cb.GetLabel() == "Tenir compte des Solos"
        assert (dlg.get_selected_tracks(), dlg.get_use_mutes(), dlg.get_use_solos()) == \
            (True, False, True)
    finally:
        dlg.Destroy()
    dlg = _dialog()
    try:                                                   # défauts : on exporte ce qu'on entend
        assert (dlg.get_selected_tracks(), dlg.get_use_mutes(), dlg.get_use_solos()) == \
            (False, True, True)
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("source, tracks, selection, unit", [
    (0, True, False, "Pattern"), (1, True, False, "Song"),
    (2, True, True, "Sélection"), (3, False, False, "Presse-papier")])
def test_dialog_fields_follow_the_source(source, tracks, selection, unit):
    dlg = _dialog(source_idx=0)
    try:
        dlg._source_lb.SetSelection(source)
        dlg._source_lb.ProcessEvent(wx.CommandEvent(wx.EVT_LISTBOX.typeId,
                                                    dlg._source_lb.GetId()))
        assert dlg._tracks_cb.IsEnabled() is tracks
        assert dlg._left.IsEnabled() is selection and dlg._right.IsEnabled() is selection
        assert dlg._end_lb.GetString(1) == f"Fin : {unit} + résonance"
        assert dlg._end_lb.GetString(0) == "Fin : Boucle exacte (résonance repliée)"
    finally:
        dlg.Destroy()


def test_dialog_selection_fields():
    dlg = _dialog(source_idx=2, num_bars=4, num_beats=4, num_steps=16,
                  lim_left=16, lim_right=47)
    try:
        assert (dlg._left.GetValue(), dlg._right.GetValue()) == ("2:1:1", "3:4:4")
        assert dlg._left.GetName() == "Début de la sélection"
        assert dlg._right.GetName() == "Fin de la sélection"
        assert dlg.get_window() == (16, 47) and dlg._validate() is None
        dlg._left.SetValue("4:1:1")
        assert dlg._validate() == "La fin de la sélection est avant son début"
        assert dlg.get_window() is None
        dlg._left.SetValue("x")
        assert dlg._validate().startswith("Position invalide")
        dlg._source_lb.SetSelection(0)
        dlg._update_enabled()
        assert not dlg._left.IsEnabled() and dlg._validate() is None   # sans objet
    finally:
        dlg.Destroy()


def test_dialog_whole_pattern_without_limiters():
    dlg = _dialog(source_idx=2, num_bars=2, num_beats=3, num_steps=12)
    try:
        assert (dlg._left.GetValue(), dlg._right.GetValue()) == ("1:1:1", "2:3:4")
    finally:
        dlg.Destroy()


def test_dialog_invalid_selection_keeps_dialog_open(monkeypatch):
    shown = []
    monkeypatch.setattr(wx, "MessageBox", lambda msg, *a, **k: shown.append(msg))
    dlg = _dialog(source_idx=2, num_bars=4, lim_left=16, lim_right=47)
    ended = []
    dlg.EndModal = ended.append
    try:
        dlg._right.SetValue("1:1:1")
        dlg._on_ok(None)
        assert shown == ["La fin de la sélection est avant son début"] and ended == []
        dlg._right.SetValue("4:1:1")
        dlg._on_ok(None)
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


@pytest.mark.parametrize("name", ["_source_lb", "_end_lb", "_format_lb", "_output_lb",
                                  "_measure_lb"])
def test_dialog_enter_on_a_list_validates(name):
    dlg = _dialog()
    ended = []
    dlg.EndModal = ended.append
    try:
        lb = getattr(dlg, name)
        lb.ProcessEvent(wx.CommandEvent(wx.EVT_LISTBOX_DCLICK.typeId, lb.GetId()))
        assert ended == [wx.ID_OK]
    finally:
        dlg.Destroy()


def test_dialog_normalize_enables_measure_and_level():
    dlg = _dialog(normalize=False)
    try:
        assert not dlg._measure_lb.IsEnabled() and not dlg._level.IsEnabled()
        dlg._normalize_cb.SetValue(True)
        dlg._update_enabled()
        assert dlg._measure_lb.IsEnabled() and dlg._level.IsEnabled()
    finally:
        dlg.Destroy()


def test_dialog_values_bounded():
    dlg = _dialog(source_idx=9, end_idx=5, format_idx=7, output_idx=4, level_db=10,
                  level_min=-24, level_max=0)
    try:
        assert dlg.get_source_idx() == 3
        assert (dlg.get_end_idx(), dlg.get_format_idx(), dlg.get_output_idx()) == (1, 2, 2)
        assert dlg.get_level_db() == 0
    finally:
        dlg.Destroy()


# ---------------------------------------------------------------------------
# Raccourcis (Alt+Shift+S retiré en 15b1 : redondant)
# ---------------------------------------------------------------------------

def test_alt_shift_w_main_window_and_no_alt_shift_s():
    # KeyManager construit sur la wx.App de la session (conftest) : make_km()
    # en crée une autre que teardown() détruit, ce qui casse les fichiers de
    # tests suivants (PyNoAppError)
    win = FakeWindow()
    km = KeyManager(win)
    calls = []
    win._export_audio_choose = lambda: calls.append("W")
    win._export_audio_selection = lambda: calls.append("S")
    km.handle(FakeEvent(key=ord('W'), alt=True, shift=True))
    km.handle(FakeEvent(key=ord('S'), alt=True, shift=True))   # plus d'export
    km.handle(FakeEvent(key=ord('W'), alt=True))                # Alt seul : rien
    assert calls == ["W"]


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
            def _export_audio_choose(self, parent=None, status=None, editor=False):
                calls.append(("W", parent, status, editor))
            def _export_audio_selection(self, *a, **k):
                calls.append(("S",))
            _key_manager = SimpleNamespace(handle_transport=lambda evt: False)
        self._parent = Parent()
    def _set_status(self, msg): pass


def test_alt_shift_w_midi_editor_with_its_clipboard():
    ed = _FakeEditor()
    evt = _FakeKey(ord('W'), shift=True, alt=True)
    ed._on_key(evt)
    assert evt.skipped is False
    ed._on_key(_FakeKey(ord('S'), shift=True, alt=True))
    assert ed.calls == [("W", ed, ed._set_status, True)]       # presse-papier des notes


def test_alt_shift_w_opens_on_the_last_source(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL))
    win = _Window(str(tmp_path))
    assert win._audio_src == AudioExportDialog.SOURCE_PATTERN
    win._export_audio_choose()
    _wait(win)
    assert d.opts_args[2]["source_idx"] == AudioExportDialog.SOURCE_PATTERN
    d2 = env.install(Dialogs(file_ok=False))
    win._export_audio_choose()
    assert d2.opts_args[2]["source_idx"] == Dialogs.SEL      # la dernière utilisée


def test_cancel_at_the_file_dialog_keeps_nothing(tmp_path, env):
    """Annuler au dialogue du fichier : aucun choix du dialogue gardé (15c1)."""
    env.install(Dialogs(file_ok=False, source=Dialogs.SEL, opts=(1, 2, True, 1, -10),
                        output=2, only=True, mutes=False, solos=False))
    win = _Window(str(tmp_path))
    win._export_audio_choose()
    assert (win._audio_src, win._audio_sel_only, win._audio_use_mutes,
            win._audio_use_solos) == (0, False, True, True)
    assert win._audio_export_opts == ProjectMixin._audio_export_opts
    assert win._audio_export_output == ProjectMixin.OUTPUT_MIX


def test_dialog_receives_the_sources_and_the_session_choices(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "a.wav"), only=True, mutes=False, solos=False))
    win = _Window(str(tmp_path))
    win._song_list[0]._name = "Fin"
    win._export_audio()
    _wait(win)
    kw = d.opts_args[2]
    assert kw["source_labels"] == ["Pattern courant (Pat_02 Intro A)",
                                   "Song courant (Song_01 Fin, vide)", "Sélection",
                                   "Presse-papier"]
    assert (kw["selected_tracks"], kw["use_mutes"], kw["use_solos"]) == (False, True, True)
    d2 = env.install(Dialogs(file_ok=False))
    win._export_audio()
    kw = d2.opts_args[2]
    assert (kw["selected_tracks"], kw["use_mutes"], kw["use_solos"]) == (True, False, False)


def test_mutes_solos_and_tracks_passed_to_the_render(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "a.wav"), only=True, mutes=False, solos=False))
    win = _Window(str(tmp_path))
    win._track_editor._sel_tracks = {1, 3}
    win._export_audio()
    _wait(win)
    kw = env.rendered[0]
    assert (kw["use_mutes"], kw["use_solos"]) == (False, False)
    assert kw["tracks"] == {1, 3} and kw["window"] is None
    assert win.statuses[-1].startswith("Pattern 02 (pistes 2, 4) exporté en WAV")


def test_pattern_with_the_current_track_only(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "a.wav"), only=True))
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    assert env.rendered[0]["tracks"] == {4}
    assert win.statuses[-1].startswith("Pattern 02 (piste 5) exporté en WAV")


def test_default_render_hears_mutes_and_solos(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "a.wav")))
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    kw = env.rendered[0]
    assert (kw["use_mutes"], kw["use_solos"], kw["tracks"]) == (True, True, None)


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



# ---------------------------------------------------------------------------
# Pistes séparées (Phase 8 étape 2m1, docs/DESIGN.md § 2a E3, E4, E12-E14)
# ---------------------------------------------------------------------------

@pytest.fixture
def stems_env(monkeypatch):
    """Comme env, mais le rendu dépend des pistes demandées : mix (tracks
    du travail) à 0,5, stem d'une piste à 0,1, sauf les pistes de silent ;
    write_wav note le chemin et le gain reçu."""
    rendered, written = [], []
    silent = set()

    def install(dialogs):
        monkeypatch.setattr(mwp.wx, "FileDialog", dialogs.FileDlg)
        monkeypatch.setattr(mwp, "AudioExportDialog", dialogs.OptsDlg)
        return dialogs

    def fake_render(**kw):
        rendered.append(kw)
        kw["progress"](1.0)
        tracks = kw.get("tracks")
        single = tracks is not None and len(tracks) == 1 and len(rendered) > 1
        value = 0.0 if single and next(iter(tracks)) in silent else (0.1 if single else 0.5)
        n = SR if not single else SR // 2          # stem plus court : aligné sur le mix
        return audio_export.RenderResult(np.full((n, 2), value, np.float32), SR, SR, 0,
                                         False, 1)

    def fake_write(path, res, subtype, normalize=False, measure="lufs", level=-14,
                   rng=None, gain=None):
        written.append(SimpleNamespace(path=path, n=len(res.data), gain=gain,
                                       normalize=normalize, data=res.data))
        return (gain.gain_db, gain.limit_db) if gain else (1.5, 0.0)

    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(audio_export, "render_pattern", fake_render)
    monkeypatch.setattr(audio_export, "write_wav", fake_write)
    return SimpleNamespace(install=install, rendered=rendered, written=written, silent=silent)


def _stems_window(tmp_path, tracks=(0, 2, 5)):
    win = _Window(str(tmp_path / "EXPORTS"))
    pat = win._player._pattern
    for t in tracks:
        pat._tape[t].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=t))
    names = [""] * 16
    names[0], names[2] = "Kit 909", "Piano 1"
    win._midi_export_params = lambda: {"track_names": names}
    return win


def test_output_passed_to_dialog_and_kept_for_session(tmp_path, stems_env):
    d = stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=2))
    win = _stems_window(tmp_path)
    assert win._audio_export_output == ProjectMixin.OUTPUT_MIX
    win._export_audio()
    _wait(win)
    assert d.opts_args[2]["output_idx"] == 0
    assert win._audio_export_output == 2
    d2 = stems_env.install(Dialogs(path=str(tmp_path / "b.wav"), output=1, opts_ok=False))
    win._export_audio()
    assert d2.opts_args[2]["output_idx"] == 2           # gardée
    assert win._audio_export_output == 2                # annulé : inchangée
    print("  Sortie passée au dialogue, gardée pour la session, pas sur annulation : OK")


def test_output_mix_renders_once(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=0))
    win = _stems_window(tmp_path)
    win._export_audio()
    _wait(win)
    assert len(stems_env.rendered) == 1
    assert [w.path for w in stems_env.written] == [str(tmp_path / "a.wav")]
    assert not (tmp_path / "a").exists()
    print("  Sortie Mix : un rendu, un fichier, pas de dossier : OK")


def test_output_stems_only(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=1))
    win = _stems_window(tmp_path)
    win._export_audio()
    _wait(win)
    assert [kw["tracks"] for kw in stems_env.rendered] == [None, {0}, {2}, {5}]
    folder = tmp_path / "a"
    assert folder.is_dir()
    assert [w.path for w in stems_env.written] == [
        str(folder / "a_01_Kit_909.wav"), str(folder / "a_03_Piano_1.wav"),
        str(folder / "a_06_Track_06.wav")]
    assert all(w.n == SR for w in stems_env.written)     # alignés sur le mix
    assert win.statuses[-1].startswith(
        "Pattern 02 exporté en WAV : 3 pistes séparées dans a/ — 1,00 s")
    print("  Sortie Pistes séparées : mix rendu non écrit, stems nommés, alignés : OK")


def test_output_mix_and_stems_with_common_gain(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=2,
                              opts=(1, 2, True, 1, -10)))
    win = _stems_window(tmp_path)
    win._export_audio()
    _wait(win)
    mix, *stems = stems_env.written
    assert mix.path == str(tmp_path / "a.wav") and mix.gain is None and mix.normalize
    gains = {id(w.gain) for w in stems}
    assert len(stems) == 3 and len(gains) == 1                  # un seul gain, partagé
    gain = stems[0].gain
    expected = audio_export.mix_gain(
        audio_export.RenderResult(np.full((SR, 2), 0.5, np.float32), SR, SR, 0, False, 1),
        True, "rms", -10)
    assert gain.gain_db == pytest.approx(expected.gain_db)
    assert win.statuses[-1].startswith(
        "Pattern 02 exporté en WAV : a.wav + 3 pistes séparées dans a/ — 1,00 s")
    assert "normalisé à −10 dBFS RMS" in win.statuses[-1]
    print("  Mix + pistes : mix écrit, gain du mix commun aux stems, compte rendu : OK")


def test_silent_stem_omitted(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=1))
    stems_env.silent.add(2)
    win = _stems_window(tmp_path)
    win._export_audio()
    _wait(win)
    assert [os.path.basename(w.path) for w in stems_env.written] == \
        ["a_01_Kit_909.wav", "a_06_Track_06.wav"]
    assert "2 pistes séparées dans a/" in win.statuses[-1]
    print("  stem silencieux (piste muette) omis, compte juste : OK")


def test_single_stem_wording(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=1))
    win = _stems_window(tmp_path, tracks=(4,))
    win._export_audio()
    _wait(win)
    assert "1 piste séparée dans a/" in win.statuses[-1]
    print("  une seule piste : « 1 piste séparée » : OK")


def test_stems_progress_over_all_renders(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "a.wav"), output=1))
    win = _stems_window(tmp_path)
    win._export_audio()
    _wait(win)
    progress = [m for m in win.statuses if m.startswith("Export audio :")]
    assert progress == ["Export audio : 0 %", "Export audio : 25 %", "Export audio : 50 %",
                        "Export audio : 75 %", "Export audio : 100 %"]
    print("  avancement sur le mix et chaque piste : OK")


def test_selection_stems_limited_to_selection(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "s.wav"), output=1, window=(16, 31),
                              source=Dialogs.SEL, only=True))
    win = _stems_window(tmp_path)
    win._track_editor._sel_tracks = {2, 5, 7}
    win._export_audio_choose()
    _wait(win)
    mix, *stems = stems_env.rendered
    assert mix["tracks"] == {2, 5, 7}
    assert [kw["tracks"] for kw in stems] == [{2}, {5}]           # 7 vide
    assert all(kw["window"] == (16, 32) for kw in stems_env.rendered)
    print("  sélection : stems des pistes sélectionnées non vides, même fenêtre : OK")


def test_clipboard_stems(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "c.wav"), output=1, source=Dialogs.CLIP))
    win = _stems_window(tmp_path)
    te = win._track_editor
    te._sel_tracks = {0, 5}
    te.set_lim_left(0)
    te.set_lim_right(15)
    te.copy(win._player._pattern, 0)
    win._export_audio_choose()
    _wait(win)
    assert [kw["tracks"] for kw in stems_env.rendered[1:]] == [{0}, {5}]
    print("  presse-papier : stems des pistes d'origine : OK")


def test_real_render_stems_sum_to_mix(tmp_path, monkeypatch):
    """Vrai routeur, vrai rendu, vrais fichiers en flottant, normalisés et
    limités : la somme des stems redonne le mix."""
    monkeypatch.setattr(mwp.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    pads = []
    for i in range(16):
        w = str(tmp_path / f"p{i}.wav")
        sf.write(w, np.full(int(0.4 * SR), 0.3 + 0.02 * i, np.float32), SR)
        pads.append(w)
    drv = Mixer()
    snd = SoundManager(pads, pads[0], pads[0], driver=drv)
    snd.load_sounds()
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    win = _Window(str(tmp_path))
    win._router = TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=drv)
    win._midi_export_params = lambda: {"track_names": ["Kit"] * 16}
    win._player.volume, win._player.pan = 100, 0
    pat = win._player._pattern
    pat._num_bars = 1
    for t, pad, at in ((0, 0, 0), (0, 0, 8), (1, 3, 4), (3, 6, 14)):
        pat._tape[t].append(TapeEvent(ETYPE_GRID, payload={"pad": pad, "vel": 100}, time=at))
    out = str(tmp_path / "mix.wav")
    win._start_audio_export(out, (1, 2, True, 1, -3), win._show_status, None,
                            ProjectMixin.OUTPUT_BOTH)
    _wait(win)
    mix = sf.read(out, dtype="float32")[0]
    files = sorted(os.listdir(tmp_path / "mix"))
    assert files == ["mix_01_Kit.wav", "mix_02_Kit.wav", "mix_04_Kit.wav"]
    total = sum(sf.read(str(tmp_path / "mix" / f), dtype="float32")[0] for f in files)
    assert np.max(np.abs(mix)) > 0.9                   # limiteur actif
    assert np.allclose(total, mix, atol=1e-6)
    print("  rendu réel : somme des stems = mix, limiteur actif : OK")



# ---------------------------------------------------------------------------
# Sélection : pistes sélectionnées ou toutes (avant 15b1 : liste Pistes
# d'Alt+Shift+S, Phase 8 étape 2o1 ; maintenant la case du dialogue)
# ---------------------------------------------------------------------------

def test_selection_all_tracks_job(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), window=(16, 31), source=Dialogs.SEL,
                        only=False))
    win = _Window(str(tmp_path))
    win._track_editor._sel_tracks = {2}
    win._export_audio_choose()
    _wait(win)
    kw = env.rendered[0]
    assert kw["tracks"] is None and kw["window"] == (16, 32)
    assert win._audio_sel_only is False
    assert win.statuses[-1].startswith(
        "Sélection (toutes les pistes ; 2:1:1 à 2:4:4) exportée en WAV : s.wav")


def test_tracks_choice_kept_for_session_not_on_cancel(tmp_path, env):
    d = env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL, only=True))
    win = _Window(str(tmp_path))
    assert win._audio_sel_only is False
    win._export_audio_choose()
    _wait(win)
    assert d.opts_args[2]["selected_tracks"] is False              # défaut au premier appel
    d2 = env.install(Dialogs(source=Dialogs.SEL, only=False, opts_ok=False))
    win._export_audio_choose()
    assert d2.opts_args[2]["selected_tracks"] is True              # gardé
    assert win._audio_sel_only is True                              # annulé : inchangé


def test_selection_all_tracks_stems(tmp_path, stems_env):
    stems_env.install(Dialogs(path=str(tmp_path / "s.wav"), output=1, window=(0, 15),
                              source=Dialogs.SEL))
    win = _stems_window(tmp_path, tracks=(0, 2, 5, 9))
    win._track_editor._sel_tracks = {5}
    win._export_audio_choose()
    _wait(win)
    mix, *stems = stems_env.rendered
    assert mix["tracks"] is None
    assert [kw["tracks"] for kw in stems] == [{0}, {2}, {5}, {9}]
    assert all(kw["window"] == (0, 16) for kw in stems_env.rendered)
    assert "4 pistes séparées dans s/" in win.statuses[-1]


def test_selection_all_tracks_in_midi_editor(tmp_path, env):
    env.install(Dialogs(path=str(tmp_path / "s.wav"), source=Dialogs.SEL))
    win = _Window(str(tmp_path))
    win._track_editor._sel_tracks = {3}
    said = []
    win._export_audio_choose(parent="éditeur", status=said.append, editor=True)
    _wait(win)
    assert env.rendered[0]["tracks"] is None
    assert said[-1].startswith("Sélection (toutes les pistes ;")


def test_real_render_all_tracks_between_limiters(tmp_path, monkeypatch):
    """Vrai rendu : toutes les pistes entre G et D, sélection ignorée ; une
    note avant G ou après D n'est pas jouée."""
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
    for t, at in ((0, 2), (0, 20), (3, 24), (6, 28), (9, 40)):
        pat._tape[t].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=at))
    win._track_editor._sel_tracks = {3}
    out = str(tmp_path / "all.wav")
    win._start_audio_export(out, (1, 2, False, 2, -14), win._show_status,
                            win._selection_job((16, 31), all_tracks=True))
    _wait(win)
    y, _ = sf.read(out, dtype="float32")
    onsets = list(np.flatnonzero(np.abs(y[:, 0]) > 1e-3))
    assert onsets == [round(s * 0.125 * SR) for s in (4, 8, 12)]
    print("  rendu réel : toutes les pistes entre les limiteurs, rien hors fenêtre : OK")



# ---------------------------------------------------------------------------
# « Sélection + résonance », « Presse-papier + résonance » (Phase 8 étape 2o3)
# ---------------------------------------------------------------------------

def _tail_render(monkeypatch):
    """Rendu simulé « + résonance » : 1 s, dont 0,5 s de résonance."""
    def fake(**kw):
        kw["progress"](1.0)
        return audio_export.RenderResult(np.zeros((SR, 2), np.float32), SR, SR // 2,
                                         SR // 2, False, 1)
    monkeypatch.setattr(audio_export, "render_pattern", fake)


def test_selection_report_and_end_label_say_selection(tmp_path, env, monkeypatch):
    _tail_render(monkeypatch)
    d = env.install(Dialogs(path=str(tmp_path / "s.wav"), opts=(1, 0, False, 2, -14),
                            source=Dialogs.SEL))
    win = _Window(str(tmp_path))
    win._export_audio_choose()
    _wait(win)
    assert "sélection + résonance (0,50 s)" in win.statuses[-1]
    assert "pattern + résonance" not in win.statuses[-1]
    print("  sélection : « Sélection + résonance » au dialogue et au compte rendu : OK")


@pytest.mark.parametrize("editor", (False, True))
def test_clipboard_report_and_end_label_say_clipboard(tmp_path, env, monkeypatch, editor):
    _tail_render(monkeypatch)
    d = env.install(Dialogs(path=str(tmp_path / "c.wav"), source=Dialogs.CLIP,
                            opts=(1, 0, False, 2, -14)))
    win = _Window(str(tmp_path))
    te = win._track_editor
    if editor:
        te.copy_events([{"type": "note", "etype": ETYPE_GRID, "track": 3, "pad": 1, "vel": 90,
                         "offset": 21, "dur": 500, "dur_override": 0, "channel": 0}])
    else:
        pat = win._player._pattern
        pat._tape[6].append(TapeEvent(ETYPE_GRID, payload={"pad": 1, "vel": 90}, time=18))
        te._sel_tracks = {6}
        te.copy(pat, 0)
    win._export_audio_choose(editor=editor)
    _wait(win)
    assert "presse-papier + résonance (0,50 s)" in win.statuses[-1]
    print("  presse-papier : « Presse-papier + résonance » au dialogue et au compte rendu : OK")


def test_pattern_report_and_end_label_unchanged(tmp_path, env, monkeypatch):
    _tail_render(monkeypatch)
    d = env.install(Dialogs(path=str(tmp_path / "p.wav"), opts=(1, 0, False, 2, -14)))
    win = _Window(str(tmp_path))
    win._export_audio()
    _wait(win)
    assert d.opts_args[2]["source_idx"] == AudioExportDialog.SOURCE_PATTERN
    assert "pattern + résonance (0,50 s)" in win.statuses[-1]
    print("  pattern : libellé et compte rendu inchangés : OK")


# ---------------------------------------------------------------------------
# Rendu réel : Mutes et Solos ignorés sur demande (Phase 8 étape 15c1, § 15a
# X3, X7) — pattern, et song (état de chaque pattern à sa frontière)
# ---------------------------------------------------------------------------

def _impulse_router(tmp_path):
    wav = str(tmp_path / "imp.wav")
    x = np.zeros(2000, np.float32)
    x[0] = 0.5
    sf.write(wav, x, SR)
    drv = Mixer()
    snd = SoundManager([wav] * 16, wav, wav, driver=drv)
    snd.load_sounds()
    rack = Rack()
    rack.set_slot(0, InstrumentType.KIT, "Kit", {})
    return TrackRouter(rack, str(tmp_path), snd, lambda m: None, driver=drv)


def _two_track_pattern():
    """Piste 1 au pas 0, piste 2 au pas 8 (1 s à 120 BPM), une mesure de 2 s."""
    pat = Pattern()
    pat._bpm, pat._num_bars = 120, 1
    pat._track_slots = [0] * len(pat._track_slots)
    pat._tape[0].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=0))
    pat._tape[1].append(TapeEvent(ETYPE_GRID, payload={"pad": 0, "vel": 100}, time=8))
    return pat


def _onsets(res):
    return [round(i / SR, 3) for i in np.flatnonzero(np.abs(res.data[:, 0]) > 1e-3)
            if i == 0 or abs(res.data[i - 1, 0]) <= 1e-3]


@pytest.mark.parametrize("mute, solo, use_mutes, use_solos, heard", [
    (True, False, True, True, [0.0]),            # piste 2 muette : on ne l'entend pas
    (True, False, False, True, [0.0, 1.0]),      # Mutes ignorés
    (False, True, True, True, [0.0]),            # piste 1 en solo
    (False, True, True, False, [0.0, 1.0]),      # Solos ignorés
    (True, True, False, False, [0.0, 1.0]),      # les deux ignorés
])
def test_real_render_pattern_mutes_and_solos(tmp_path, mute, solo, use_mutes, use_solos, heard):
    router = _impulse_router(tmp_path)
    router._track_mutes[1] = mute
    router._track_solos[0] = solo
    pat = _two_track_pattern()
    res = audio_export.render_pattern(pat, pat.tempo_map(), router, VoiceManager(),
                                      end=audio_export.END_TAIL, master_volume=100,
                                      use_mutes=use_mutes, use_solos=use_solos)
    assert _onsets(res)[:2] == heard
    assert router._track_mutes[1] is mute and router._track_solos[0] is solo   # écoute intacte


@pytest.mark.parametrize("use_mutes, heard", [(True, [0.0, 2.0]), (False, [0.0, 1.0, 2.0, 3.0])])
def test_real_render_song_mutes_at_each_pattern(tmp_path, use_mutes, heard):
    """Song de deux patterns dont la piste 2 est muette dans chacun : l'état
    du pattern, réappliqué à sa frontière, garde le Mute ignoré."""
    from song import song_segments
    router = _impulse_router(tmp_path)
    pats = [_two_track_pattern(), _two_track_pattern()]
    for p in pats:
        p._track_mutes[1] = True
    song = Song(0)
    song._sequence = [0, 1]
    res = audio_export.render_song(song_segments(song, pats), router, VoiceManager(),
                                   end=audio_export.END_TAIL, master_volume=100,
                                   use_mutes=use_mutes)
    assert _onsets(res)[:len(heard)] == heard


def test_real_render_song_selected_tracks(tmp_path):
    from song import song_segments
    router = _impulse_router(tmp_path)
    pats = [_two_track_pattern(), _two_track_pattern()]
    song = Song(0)
    song._sequence = [0, 1]
    res = audio_export.render_song(song_segments(song, pats), router, VoiceManager(),
                                   end=audio_export.END_TAIL, master_volume=100, tracks={1})
    assert _onsets(res)[:2] == [1.0, 3.0]                    # piste 2 seule, dans chaque pattern
