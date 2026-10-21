#python3
"""
    File: tests/test_load_project_cache.py
    Non-régression du bug corrigé en Phase 7 étape 10h9 : après Ctrl+O
    (_load_project), le cache des patterns sérialisés de _capture_state
    (Undo) ne doit plus servir les dicts du projet précédent.
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from pattern import Pattern
from rack import Rack
from project_manager import ProjectManager
from undo_manager import UndoManager
from test_kit_channel_migration import _FakeProjectWindow


class _Window(_FakeProjectWindow):
    """Fenêtre factice de test_kit_channel_migration, avec ce qu'il faut à
    _capture_state et _add_undo (vrais, ProjectMixin)."""
    def __init__(self, path, names):
        super().__init__(path)
        for p, name in zip(self._pattern_list, names):
            p._name = name
        self._cur_pattern_idx     = 0
        self._cur_song_idx        = 0
        self._undo                = UndoManager()
        self._pattern_cache       = [None] * len(self._pattern_list)
        self._pattern_cache_dirty = set(range(len(self._pattern_list)))
    def _flush_pattern_to_store(self, pat): pass
    def _clipboard_to_dict(self):           return None


def _save_project(tmp_path, name, n=3):
    pats = [Pattern() for _ in range(n)]
    for i, p in enumerate(pats):
        p._name = f"{name}{i + 1}"
    path = str(tmp_path / f"{name}.gvp")
    ProjectManager.save(path, {"version": 1, "rack": Rack().to_dict(),
                               "patterns": [p.to_dict() for p in pats],
                               "songs": [], "cur_song": 0})
    return path

def _names(state):
    return [d["name"] for d in state["patterns"]]


def test_snapshot_after_open_holds_opened_project_only(tmp_path):
    win = _Window(_save_project(tmp_path, "B"), ["A1", "A2", "A3"])
    assert _names(win._capture_state()) == ["A1", "A2", "A3"]   # cache rempli par A
    win._load_project()                                          # Ctrl+O sur B
    assert _names(win._capture_state()) == ["B1", "B2", "B3"]
    print("  instantané après Ctrl+O : seulement les patterns du projet ouvert : OK")

def test_load_marks_every_pattern_dirty(tmp_path):
    win = _Window(_save_project(tmp_path, "B"), ["A1", "A2", "A3"])
    win._capture_state()
    assert win._pattern_cache_dirty == set()
    win._load_project()
    assert win._pattern_cache_dirty == {0, 1, 2}
    print("  _load_project : tous les patterns marqués à re-sérialiser : OK")

def test_undo_entry_after_open_has_no_pattern_of_previous_project(tmp_path):
    win = _Window(_save_project(tmp_path, "B"), ["A1", "A2", "A3"])
    win._add_undo("Action dans A")                 # cache rempli par A
    win._load_project()
    win._add_undo("Action dans B")
    entry = win._undo.last_entry()
    assert entry.title == "Action dans B"
    assert _names(entry.state) == ["B1", "B2", "B3"]
    print("  entrée d'Undo prise après Ctrl+O : aucun pattern de l'ancien projet : OK")
