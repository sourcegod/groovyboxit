#python3
"""
    File: tests/test_engine_options.py
    Moteurs de synthèse optionnels (Phase 8 étape 7c1, docs/DESIGN.md § 7a2
    Z7, Z14 ; avancement 7b1) : options --no-fluidsynth / --no-sfizz de
    main.py, création des moteurs FluidSynth et sfizz par MainWindow selon
    l'option, la clé de config.json et la présence de la bibliothèque,
    messages de démarrage, et une vraie fenêtre principale lancée sans les
    deux moteurs.
    Date: Wed, 04/11/2026
    Author: Coolbrother
"""
import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import wx

import main as app_main
import ui.main_window as main_window
from engines.fluidsynth_engine import FluidSynthUnavailable
from engines.sfizz_engine import SfizzUnavailable
from ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    args = app_main.parse_args([])
    assert not args.no_fluidsynth and not args.no_sfizz


def test_parse_args_both_options():
    args = app_main.parse_args(["--no-fluidsynth", "--no-sfizz"])
    assert args.no_fluidsynth and args.no_sfizz


def test_parse_args_one_option():
    args = app_main.parse_args(["--no-sfizz"])
    assert not args.no_fluidsynth and args.no_sfizz


def test_parse_args_ignores_unknown_arguments():
    args = app_main.parse_args(["--inconnu", "fichier.gvp", "--no-fluidsynth"])
    assert args.no_fluidsynth and not args.no_sfizz


# ---------------------------------------------------------------------------
# Création des moteurs (MainWindow._init_bank_engine / _init_sfz_engine)
# ---------------------------------------------------------------------------

class _FakeDriver:
    samplerate = 48000
    def __init__(self):
        self.sources = []
    def add_render_source(self, fn):
        self.sources.append(fn)


class _FakeEngine:
    def __init__(self, **kw):
        self.kw = kw
    def render(self, out):
        pass


def _win(no_fluidsynth=False, no_sfizz=False):
    return types.SimpleNamespace(_audio_driver=_FakeDriver(), _engine_notes=[],
                                 _no_fluidsynth=no_fluidsynth, _no_sfizz=no_sfizz)


def _cfg(**kw):
    base = dict(midi_bank_select="gs", fluidsynth_gain=0.4, fluidsynth_enabled=True,
                sfizz_gain=1.0, sfizz_enabled=True, sfz_dir="/srv/sfz")
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(main_window, "FluidSynthEngine", _FakeEngine)
    monkeypatch.setattr(main_window, "SfzEngine", _FakeEngine)


def test_both_engines_created_and_plugged(fakes):
    win = _win()
    MainWindow._init_bank_engine(win, _cfg())
    MainWindow._init_sfz_engine(win, _cfg(sfizz_gain=1.5))
    assert isinstance(win._bank_engine, _FakeEngine)
    assert isinstance(win._sfz_engine, _FakeEngine)
    assert win._sfz_engine.kw["samplerate"] == 48000
    assert win._sfz_engine.kw["gain"] == 1.5
    assert callable(win._sfz_engine.kw["status_cb"])
    assert win._sfz_dir == "/srv/sfz"
    assert win._audio_driver.sources == [win._bank_engine.render, win._sfz_engine.render]
    assert win._engine_notes == []


def test_no_fluidsynth_option(fakes):
    win = _win(no_fluidsynth=True)
    MainWindow._init_bank_engine(win, _cfg())
    assert win._bank_engine is None and win._audio_driver.sources == []
    assert win._engine_notes == ["FluidSynth désactivé (--no-fluidsynth) : slots Banque muets"]


def test_no_sfizz_option(fakes):
    win = _win(no_sfizz=True)
    MainWindow._init_sfz_engine(win, _cfg())
    assert win._sfz_engine is None and win._audio_driver.sources == []
    assert win._sfz_dir == "/srv/sfz"          # gardé : le dialogue SFZ en a besoin
    assert win._engine_notes == ["sfizz désactivé (--no-sfizz) : slots Synth SFZ muets"]


def test_engines_disabled_by_config(fakes):
    win = _win()
    MainWindow._init_bank_engine(win, _cfg(fluidsynth_enabled=False))
    MainWindow._init_sfz_engine(win, _cfg(sfizz_enabled=False))
    assert win._bank_engine is None and win._sfz_engine is None
    assert win._audio_driver.sources == []
    assert win._engine_notes == [
        "FluidSynth désactivé (config.json) : slots Banque muets",
        "sfizz désactivé (config.json) : slots Synth SFZ muets"]


def test_option_wins_over_config(fakes):
    # La clé dit oui, l'option dit non : l'option prime, et le message la nomme.
    win = _win(no_fluidsynth=True, no_sfizz=True)
    MainWindow._init_bank_engine(win, _cfg(fluidsynth_enabled=True))
    MainWindow._init_sfz_engine(win, _cfg(sfizz_enabled=True))
    assert win._bank_engine is None and win._sfz_engine is None
    assert all("(--no-" in note for note in win._engine_notes)


def test_missing_libraries(monkeypatch):
    def no_fluid(**kw):
        raise FluidSynthUnavailable("absente")
    def no_sfizz(**kw):
        raise SfizzUnavailable("absente")
    monkeypatch.setattr(main_window, "FluidSynthEngine", no_fluid)
    monkeypatch.setattr(main_window, "SfzEngine", no_sfizz)
    win = _win()
    MainWindow._init_bank_engine(win, _cfg())
    MainWindow._init_sfz_engine(win, _cfg())
    assert win._bank_engine is None and win._sfz_engine is None
    assert win._audio_driver.sources == []
    assert win._engine_notes == ["libfluidsynth introuvable : slots Banque muets",
                                 "libsfizz introuvable : slots Synth SFZ muets"]


def test_sfz_status_goes_through_call_after(fakes, monkeypatch):
    # Le moteur appelle status_cb depuis son fil de chargement : passage par
    # wx.CallAfter vers la barre d'état.
    calls = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a: calls.append((fn, a)))
    win = _win()
    win._show_status = lambda msg: None
    MainWindow._init_sfz_engine(win, _cfg())
    win._sfz_engine.kw["status_cb"]("SFZ prêt : piano (canal 1)")
    assert calls == [(win._show_status, ("SFZ prêt : piano (canal 1)",))]


# ---------------------------------------------------------------------------
# Vraie fenêtre principale sans les deux moteurs
# ---------------------------------------------------------------------------

def test_main_window_runs_without_both_engines(monkeypatch):
    calls = []
    real_call_after = wx.CallAfter
    def record(fn, *a, **k):
        calls.append((fn, a))
    monkeypatch.setattr(wx, "CallAfter", record)
    win = MainWindow(no_fluidsynth=True, no_sfizz=True)
    try:
        assert win._bank_engine is None and win._sfz_engine is None
        assert win._router.bank_engine is None
        # message de démarrage, en dernier dans la barre d'état
        note = ("FluidSynth désactivé (--no-fluidsynth) : slots Banque muets ; "
                "sfizz désactivé (--no-sfizz) : slots Synth SFZ muets")
        assert (win._show_status, (note,)) in calls
        win._show_status(note)
        assert win._status_ctrl.GetString(0) == note
        # le reste marche : un pad du kit joue sans erreur
        win._router.wait_loaded()
        win._router.on_play(0, 0, 1.0, 0)
        assert win._sfz_dir                        # dossier SFZ connu malgré tout
    finally:
        monkeypatch.setattr(wx, "CallAfter", real_call_after)
        win._audio_driver.close()
        win.Destroy()
