#python3
"""
    File: tests/test_audio_beep.py
    Bips (Phase 8 étape 20c1, docs/DESIGN.md § Phase 8 étape 20a B0-B3,
    avancement 20b1) : module autonome audio_beep (aucun import de l'appli ;
    onde carrée par défaut, dents de scie ; harmoniques sous Nyquist,
    impaires seulement pour le carré ; crête, fondus, durées ; ALERT
    montant, CONFIRM descendant ; play par un lecteur fourni ou par
    sounddevice ; écoute en ligne de commande) ; MainWindow._beep /
    _alert_beep / _confirm_beep (pilote, repli wx.Bell) ; ui_beep.alert
    (fenêtre principale trouvée par les parents ou la fenêtre de tête,
    wx.Bell sinon) ; SaveConfirmDialog.ShowModal bipe avant d'afficher.
    Tous sans marque (aucune carte son, aucune vraie fenêtre principale).
    Date: Sat, 21/11/2026
    Author: Coolbrother
"""
import ast
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pytest
import wx

from audio import audio_beep as ab
from audio.sound_device_driver import SdSound
from ui import ui_beep
import ui.main_window as main_window
from ui.main_window import MainWindow
from ui.dialogs import SaveConfirmDialog

SR = 44100


def _peak_freq(x, sr=SR):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.argmax(spec) * sr / len(x)


def _harmonics(x, f0, sr=SR, upto=8):
    """Amplitudes relatives des harmoniques 1..upto (spectre d'une note)."""
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    bin_hz = sr / len(x)
    amps = [spec[int(round(k * f0 / bin_hz)) - 2:int(round(k * f0 / bin_hz)) + 3].max()
            for k in range(1, upto + 1)]
    return np.array(amps) / amps[0]


# ---------------------------------------------------------------------------
# Module autonome
# ---------------------------------------------------------------------------

def test_module_is_standalone():
    path = os.path.join(os.path.dirname(__file__), "..", "src", "audio", "audio_beep.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"math", "numpy", "sounddevice", "sys", "time"}


def test_square_is_the_default_wave():
    assert ab.WAVE == ab.SQUARE
    assert np.array_equal(ab.beep(ab.ALERT), ab.beep(ab.ALERT, wave=ab.SQUARE))
    assert not np.array_equal(ab.beep(ab.ALERT), ab.beep(ab.ALERT, wave=ab.SAW))


def _rms(d):
    return float(np.sqrt(np.mean(np.square(d[:, 0], dtype=np.float64))))


def test_square_as_loud_as_saw_on_average():
    """Essai de 20d1 : le carré à la même crête était un peu fort aux
    haut-parleurs → crête 0,15, même niveau moyen que les dents de scie."""
    sq, sw = ab.beep(ab.ALERT, wave=ab.SQUARE), ab.beep(ab.ALERT, wave=ab.SAW)
    assert abs(np.max(np.abs(sq)) - ab.SQUARE_LEVEL) < 1e-6 and ab.SQUARE_LEVEL == 0.15
    assert abs(np.max(np.abs(sw)) - ab.LEVEL) < 1e-6
    assert abs(20 * np.log10(_rms(sq) / _rms(sw))) < 0.5            # à 0,5 dB près


def test_default_level_per_wave():
    assert ab.default_level(ab.SQUARE) == ab.SQUARE_LEVEL
    assert ab.default_level(ab.SAW) == ab.LEVEL
    assert ab.default_level() == ab.SQUARE_LEVEL                    # carré par défaut
    assert abs(np.max(np.abs(ab.beep(ab.ALERT, level=0.5))) - 0.5) < 1e-6   # level imposé


def test_unknown_wave_refused():
    with pytest.raises(KeyError):
        ab.beep(ab.ALERT, wave="triangle")


@pytest.mark.parametrize("gen", [ab.saw, ab.square])
def test_note_length_peak_and_fades(gen):
    x = gen(880.0, 0.12, SR, level=0.25)
    assert len(x) == round(0.12 * SR)
    assert abs(np.max(np.abs(x)) - 0.25) < 1e-9                 # crête = level
    assert x[0] == 0.0 and x[-1] == 0.0                         # fondus : sans clic
    fade = int(SR * ab.FADE_MS / 1000)
    assert np.max(np.abs(x[:fade // 4])) < 0.25 * 0.4           # montée progressive


@pytest.mark.parametrize("gen", [ab.saw, ab.square])
def test_fundamental(gen):
    assert abs(_peak_freq(gen(880.0, 0.5, SR)) - 880.0) < 5


def test_square_has_odd_harmonics_only():
    h = _harmonics(ab.square(440.0, 0.5, SR), 440.0)
    assert h[1] < 0.02 and h[3] < 0.02                          # 2e, 4e : absentes
    assert abs(h[2] - 1 / 3) < 0.05 and abs(h[4] - 1 / 5) < 0.05


def test_saw_has_all_harmonics():
    h = _harmonics(ab.saw(440.0, 0.5, SR), 440.0)
    assert abs(h[1] - 1 / 2) < 0.05 and abs(h[2] - 1 / 3) < 0.05 and abs(h[3] - 1 / 4) < 0.05


@pytest.mark.parametrize("gen", [ab.saw, ab.square])
def test_band_limited_nothing_folded(gen):
    """Rien au-dessus de la dernière harmonique sous Nyquist (pas de
    repliement) : 6 000 Hz à 16 kHz → seule la fondamentale (12 kHz > 8 kHz)."""
    sr = 16000
    x = gen(6000.0, 0.5, sr)
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    assert spec[np.abs(freqs - 6000) > 50].max() < spec.max() * 1e-3


def test_zero_length_note():
    assert len(ab.saw(880.0, 0.0)) == 0 and len(ab.square(880.0, 0.0)) == 0
    assert ab.beep((), SR).shape == (0, 2)


def test_beep_stereo_float32_contiguous():
    d = ab.beep(ab.ALERT, SR)
    assert d.dtype == np.float32 and d.shape == (2 * round(ab.NOTE_SECONDS * SR), 2)
    assert d.flags["C_CONTIGUOUS"] and np.array_equal(d[:, 0], d[:, 1])


@pytest.mark.parametrize("notes, rising", [(ab.ALERT, True), (ab.CONFIRM, False)])
def test_direction(notes, rising):
    d = ab.beep(notes, SR)
    half = len(d) // 2
    first, second = _peak_freq(d[:half, 0]), _peak_freq(d[half:, 0])
    assert (first < second) == rising
    low, high = sorted((first, second))           # résolution ≈ 8 Hz sur 0,12 s
    assert abs(low - ab.LOW) < 10 and abs(high - ab.HIGH) < 10


def test_duration():
    assert ab.duration(ab.ALERT) == pytest.approx(0.24)
    assert ab.duration(()) == 0.0


def test_play_through_given_player():
    got = []
    data = ab.play(ab.CONFIRM, 48000, player=lambda d, sr: got.append((d, sr)))
    (d, sr), = got
    assert sr == 48000 and d is data and len(d) == 2 * round(ab.NOTE_SECONDS * 48000)


def test_play_through_sounddevice(monkeypatch):
    import sounddevice as sd
    got = []
    monkeypatch.setattr(sd, "play", lambda d, samplerate, device: got.append((samplerate, device)))
    ab.play(ab.ALERT, SR, device=3, wave=ab.SAW)
    assert got == [(SR, 3)]


def test_play_errors_reach_the_caller():
    def refuse(d, sr):
        raise RuntimeError("occupé")
    with pytest.raises(RuntimeError):
        ab.play(ab.ALERT, SR, player=refuse)


def test_command_line(monkeypatch, capsys):
    import sounddevice as sd
    played = []
    monkeypatch.setattr(sd, "play", lambda d, samplerate, device: played.append(d))
    monkeypatch.setattr(sd, "wait", lambda: None)
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    ab.main([])
    assert capsys.readouterr().out.splitlines() == [
        "alert — saw", "confirm — saw", "alert — square", "confirm — square"]
    ab.main(["confirm", "square"])
    assert capsys.readouterr().out.splitlines() == ["confirm — square"]
    assert len(played) == 5


# ---------------------------------------------------------------------------
# MainWindow._beep / _alert_beep / _confirm_beep
# ---------------------------------------------------------------------------

class _Driver:
    samplerate = SR

    def __init__(self, fail=False):
        self.played, self.fail = [], fail

    def play(self, sound, vol=1.0, pan=0):
        if self.fail:
            raise RuntimeError("pas de son")
        self.played.append(sound)


def _win(driver):
    win = SimpleNamespace(_audio_driver=driver)
    win._beep = lambda notes: MainWindow._beep(win, notes)
    return win


@pytest.mark.parametrize("method, notes", [("_alert_beep", ab.ALERT),
                                           ("_confirm_beep", ab.CONFIRM)])
def test_window_beeps_through_driver(method, notes):
    win = _win(_Driver())
    getattr(MainWindow, method)(win)
    (snd,) = win._audio_driver.played
    assert isinstance(snd, SdSound) and snd.samplerate == SR
    assert np.array_equal(snd.data, ab.beep(notes, SR))


def test_window_beep_falls_back_to_bell(monkeypatch):
    rang = []
    monkeypatch.setattr(main_window.wx, "Bell", lambda: rang.append(1))
    MainWindow._alert_beep(_win(_Driver(fail=True)))
    assert rang == [1]


def test_window_beep_without_driver(monkeypatch):
    monkeypatch.setattr(main_window.wx, "Bell", lambda: pytest.fail("pas de bip du bureau"))
    MainWindow._alert_beep(_win(None))                 # rien, sans erreur


# ---------------------------------------------------------------------------
# ui_beep.alert
# ---------------------------------------------------------------------------

class _Node:
    def __init__(self, parent=None, beeps=None):
        self._parent = parent
        if beeps is not None:
            self._alert_beep = lambda: beeps.append(self)

    def GetParent(self):
        return self._parent


def test_alert_climbs_parents():
    beeps = []
    main = _Node(beeps=beeps)
    ui_beep.alert(_Node(_Node(main)))
    assert beeps == [main]


def test_alert_on_the_window_itself():
    beeps = []
    main = _Node(beeps=beeps)
    ui_beep.alert(main)
    assert beeps == [main]


def test_alert_falls_back_to_top_window(monkeypatch):
    beeps = []
    top = _Node(beeps=beeps)
    monkeypatch.setattr(ui_beep.wx, "GetApp", lambda: SimpleNamespace(GetTopWindow=lambda: top))
    ui_beep.alert(_Node(_Node()))
    ui_beep.alert(None)
    assert beeps == [top, top]


def test_alert_bell_without_main_window(monkeypatch):
    rang = []
    monkeypatch.setattr(ui_beep.wx, "GetApp", lambda: SimpleNamespace(GetTopWindow=lambda: _Node()))
    monkeypatch.setattr(ui_beep.wx, "Bell", lambda: rang.append(1))
    ui_beep.alert(_Node())
    monkeypatch.setattr(ui_beep.wx, "GetApp", lambda: None)
    ui_beep.alert(None)
    assert rang == [1, 1]


# ---------------------------------------------------------------------------
# SaveConfirmDialog : bip de question avant l'affichage
# ---------------------------------------------------------------------------

def test_save_confirm_beeps_before_showing(monkeypatch):
    order = []
    frame = wx.Frame(None)
    frame._alert_beep = lambda: order.append("bip")
    monkeypatch.setattr(wx.Dialog, "ShowModal", lambda self: order.append("affiché") or wx.ID_NO)
    dlg = SaveConfirmDialog(frame, "Le projet a été modifié.", "Quitter")
    try:
        assert dlg.ShowModal() == wx.ID_NO
        assert order == ["bip", "affiché"]
    finally:
        dlg.Destroy()
        frame.Destroy()
