#python3
"""
    File: tests/test_live_take.py
    Tests de la prise d'enregistrement live (Phase 7 étape 10d2,
    docs/DESIGN.md § 10a1, avancement 10d2) : ProjectMixin._take_begin pose
    un Undo avant la prise ; _take_end_if_idle le retire si _tape n'a pas
    changé et rétablit l'état « modifié ». Effacer à vide (Remplacement,
    Erase) change _tape : la prise est gardée. Branchement dans
    MainWindow._on_char_hook et _on_close.
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx

from pattern import Pattern, TapeEvent, ETYPE_KIT
from player.drum_player import DrumPlayer
from undo_manager import UndoManager
from ui.mw_project import ProjectMixin
from ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProjectWindow(ProjectMixin):
    """Fenêtre minimale : _add_undo, _mark_modified et la prise sont les vrais
    (ProjectMixin) ; _capture_state est réduit à un marqueur."""
    def __init__(self, modified=False):
        self._player           = DrumPlayer(sound_manager=None)
        self._pattern_list     = [Pattern() for _ in range(2)]
        self._cur_pattern_idx  = 0
        self._undo             = UndoManager()
        self._project_modified = modified
        self._take             = None
        self.titles            = []

    def _capture_state(self):     return {"marker": len(self._undo.history_list())}
    def _update_title(self):      self.titles.append(self._project_modified)


def _kit(time_val, note=36):
    return TapeEvent(ETYPE_KIT, payload={"note": note, "vel": 100}, time=time_val)


def _titles(win):
    return [e.title for e in win._undo.history_list()]


def _record(win, events=()):
    """Simule une prise R : ouverture, enregistrement de `events`, arrêt."""
    win._take_begin("Enregistrement piste 1")
    win._player.recording = True
    win._player._pattern._tape[0].extend(events)
    win._player.recording = False
    win._take_end_if_idle()


# ---------------------------------------------------------------------------
# Prise vide / prise jouée
# ---------------------------------------------------------------------------

def test_empty_take_removes_undo_and_restores_unmodified():
    win = _FakeProjectWindow(modified=False)
    _record(win)
    assert _titles(win) == []
    assert win._project_modified is False
    assert win.titles[-1] is False and win._take is None
    print("  prise vide : Undo retiré, projet non modifié : OK")

def test_recorded_take_keeps_undo_and_marks_modified():
    win = _FakeProjectWindow(modified=False)
    _record(win, [_kit(4.0)])
    assert _titles(win) == ["Enregistrement piste 1"]
    assert win._project_modified is True and win._take is None
    print("  prise jouée : Undo gardé, projet modifié : OK")

def test_empty_take_keeps_previous_modified_state():
    win = _FakeProjectWindow(modified=True)
    _record(win)
    assert _titles(win) == [] and win._project_modified is True
    print("  prise vide sur projet déjà modifié : reste modifié : OK")

def test_take_begin_records_state_before_take():
    win = _FakeProjectWindow()
    win._take_begin("Enregistrement piste 1")
    entry = win._undo.last_entry()
    assert entry.title == "Enregistrement piste 1"
    assert win._take[1] is entry           # (signature, entrée) depuis 16d1
    assert win._project_modified is True   # marqué dès l'ouverture
    print("  _take_begin : Undo posé, projet marqué modifié pendant la prise : OK")


# ---------------------------------------------------------------------------
# Effacer à vide (Remplacement, Erase) : demande de l'utilisateur
# ---------------------------------------------------------------------------

def test_replace_take_that_only_erases_is_kept():
    win = _FakeProjectWindow()
    tape = win._player._pattern._tape[0]
    tape.extend([_kit(0.0), _kit(4.0)])
    win._take_begin("Remplacement piste 1")
    win._player.recording = win._player.replace_recording = True
    tape.pop()                             # effacée au passage, rien de joué
    win._player.recording = win._player.replace_recording = False
    win._take_end_if_idle()
    assert _titles(win) == ["Remplacement piste 1"]
    assert win._project_modified is True
    print("  Remplacement à vide qui efface : prise gardée : OK")

def test_erase_take_that_erases_is_kept():
    win = _FakeProjectWindow()
    tape = win._player._pattern._tape[0]
    tape.append(_kit(2.0))
    win._take_begin("Erase piste 1")
    win._player.erasing = True
    tape.clear()
    win._player.erasing = False
    win._take_end_if_idle()
    assert _titles(win) == ["Erase piste 1"] and win._project_modified is True
    print("  Erase qui efface : prise gardée : OK")

def test_modified_payload_counts_as_change():
    win = _FakeProjectWindow()
    ev = _kit(0.0)
    win._player._pattern._tape[0].append(ev)
    win._take_begin("Enregistrement piste 1")
    ev.payload = {"note": 36, "vel": 64}   # même note, vélocité changée
    win._take_end_if_idle()
    assert _titles(win) == ["Enregistrement piste 1"]
    print("  payload modifié : prise gardée : OK")


# ---------------------------------------------------------------------------
# Fermeture : seulement quand le player est au repos
# ---------------------------------------------------------------------------

def test_end_waits_while_recording_erasing_or_count_in():
    for attr, value in (("recording", True), ("erasing", True), ("_count_in", 1)):
        win = _FakeProjectWindow()
        win._take_begin("Enregistrement piste 1")
        setattr(win._player, attr, value)
        win._take_end_if_idle()
        assert win._take is not None, attr
        assert _titles(win) == ["Enregistrement piste 1"], attr
    print("  prise non fermée pendant Rec, Erase ou décompte : OK")

def test_end_without_take_does_nothing():
    win = _FakeProjectWindow()
    win._undo.add("Autre", {})
    win._take_end_if_idle()
    assert _titles(win) == ["Autre"] and win.titles == []
    print("  pas de prise ouverte : rien : OK")

def test_second_begin_reuses_open_take():
    """Erase pendant un Rec : même prise, un seul Undo."""
    win = _FakeProjectWindow()
    win._take_begin("Enregistrement piste 1")
    win._player.recording = True
    win._take_begin("Erase piste 1")
    win._player.recording = False
    win._take_end_if_idle()
    assert _titles(win) == []
    print("  deuxième ouverture pendant une prise : un seul Undo : OK")


# ---------------------------------------------------------------------------
# Interactions : sauvegarde, autre action, Undo, changement de pattern
# ---------------------------------------------------------------------------

def test_save_during_empty_take_stays_saved():
    win = _FakeProjectWindow(modified=True)
    win._take_begin("Enregistrement piste 1")
    win._project_modified = False          # Ctrl+S pendant la prise
    win._take_end_if_idle()
    assert _titles(win) == [] and win._project_modified is False
    print("  sauvegarde pendant une prise vide : reste enregistré : OK")

def test_other_undo_action_during_take_keeps_take():
    win = _FakeProjectWindow()
    win._take_begin("Enregistrement piste 1")
    win._add_undo("Cellule 1/1")
    win._take_end_if_idle()
    assert _titles(win) == ["Cellule 1/1", "Enregistrement piste 1"]
    assert win._project_modified is True
    print("  autre action annulable pendant la prise : rien n'est retiré : OK")

def test_take_entry_already_undone_pops_nothing_else():
    win = _FakeProjectWindow()
    win._undo.add("Avant", {})
    win._take_begin("Enregistrement piste 1")
    win._undo.undo()                       # Ctrl+Z retire l'entrée de la prise
    win._take_end_if_idle()
    assert _titles(win) == ["Avant"]
    print("  entrée de prise déjà annulée : aucune autre entrée retirée : OK")

def test_pattern_switch_during_take_keeps_take():
    win = _FakeProjectWindow()
    win._take_begin("Enregistrement piste 1")
    win._cur_pattern_idx = 1
    win._take_end_if_idle()
    assert _titles(win) == ["Enregistrement piste 1"]
    print("  changement de pattern pendant la prise : prise gardée : OK")


# ---------------------------------------------------------------------------
# Branchement dans MainWindow
# ---------------------------------------------------------------------------

class _FakeMain:
    def __init__(self):
        self.calls = []
        win = self
        class _KM:
            def handle(self, event): win.calls.append('handle')
        class _Closable:
            def __init__(self, name): self.name = name
            def close(self):          win.calls.append(self.name)
        self._key_manager      = _KM()
        self._project_modified = False
        self._midi             = _Closable('midi.close')
        self._audio_driver     = _Closable('audio.close')
        self._bank_engine      = _Closable('bank.close')   # Phase 7 étape 17b1
    def _take_end_if_idle(self): self.calls.append('_take_end_if_idle')

class _FakeEvent:
    def __init__(self):  self.skipped = False
    def Skip(self):      self.skipped = True

def test_char_hook_ends_take_after_each_key(monkeypatch):
    # FindFocus exige un wx.App : pas de focus, sans dépendre de l'ordre des tests
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    win = _FakeMain()
    MainWindow._on_char_hook(win, _FakeEvent())
    assert win.calls == ['handle', '_take_end_if_idle']
    print("  _on_char_hook : fermeture de prise après chaque touche : OK")

def test_close_ends_take_before_save_check():
    win = _FakeMain()
    ev = _FakeEvent()
    MainWindow._on_close(win, ev)
    assert win.calls[0] == '_take_end_if_idle' and ev.skipped
    # le moteur de banque se ferme après le pilote : le callback ne l'appelle plus
    assert win.calls[1:] == ['midi.close', 'audio.close', 'bank.close']
    print("  _on_close : prise fermée avant la question d'enregistrement : OK")
