#python3
"""
    File: tests/test_undo_manager.py
    Tests unitaires — UndoManager (historique undo/redo).
    Date: Sat, 21/06/2026
    Author: Coolbrother
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from undo_manager import UndoEntry, UndoManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(n):
    return {"value": n}


# ---------------------------------------------------------------------------
# UndoEntry
# ---------------------------------------------------------------------------

def test_entry_title_and_state():
    e = UndoEntry("Action A", _state(1))
    assert e.title == "Action A"
    assert e.state == {"value": 1}


def test_entry_timestamp():
    before = time.time()
    e = UndoEntry("T", _state(0))
    after  = time.time()
    assert before <= e.timestamp <= after


def test_entry_rel_time_seconds():
    e = UndoEntry("T", _state(0))
    rt = e.rel_time()
    assert "s" in rt or "min" in rt or "h" in rt


def test_entry_rel_time_old(monkeypatch):
    e = UndoEntry("T", _state(0))
    monkeypatch.setattr(e, "timestamp", time.time() - 90)
    assert "min" in e.rel_time()


def test_entry_rel_time_very_old(monkeypatch):
    e = UndoEntry("T", _state(0))
    monkeypatch.setattr(e, "timestamp", time.time() - 7200)
    assert "h" in e.rel_time()


# ---------------------------------------------------------------------------
# UndoManager — add / can_undo / can_redo
# ---------------------------------------------------------------------------

def test_empty_manager():
    m = UndoManager()
    assert not m.can_undo()
    assert not m.can_redo()
    assert m.undo() is None
    assert m.redo() is None


def test_add_single():
    m = UndoManager()
    m.add("A1", _state(1))
    assert m.can_undo()
    assert not m.can_redo()


def test_add_clears_future():
    m = UndoManager()
    m.add("A1", _state(1))
    entry = m.undo()
    m.push_future(entry.title, _state(99))
    assert m.can_redo()
    m.add("A2", _state(2))       # nouvelle action → efface le futur
    assert not m.can_redo()


def test_undo_returns_last_added():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    e = m.undo()
    assert e.title == "A2"
    assert e.state == _state(2)


def test_undo_depletes_history():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    m.undo()
    m.undo()
    assert not m.can_undo()
    assert m.undo() is None


def test_undo_multiple_times():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    m.add("A3", _state(3))
    assert m.undo().title == "A3"
    assert m.undo().title == "A2"
    assert m.undo().title == "A1"
    assert m.undo() is None


# ---------------------------------------------------------------------------
# UndoManager — push_future / redo
# ---------------------------------------------------------------------------

def test_push_future_and_redo():
    m = UndoManager()
    m.add("A1", _state(1))
    entry = m.undo()
    assert entry is not None
    m.push_future(entry.title, _state(99))
    assert m.can_redo()
    re = m.redo()
    assert re.title == "A1"
    assert re.state == _state(99)


def test_redo_empty():
    m = UndoManager()
    assert m.redo() is None


def test_redo_after_push_history():
    m = UndoManager()
    m.add("A1", _state(1))
    e1 = m.undo()
    m.push_future(e1.title, _state(10))
    e2 = m.redo()
    m.push_history(e2.title, _state(1))
    assert m.can_undo()
    e3 = m.undo()
    assert e3.title == "A1"
    assert e3.state == _state(1)


# ---------------------------------------------------------------------------
# UndoManager — max_size
# ---------------------------------------------------------------------------

def test_max_size_evicts_oldest():
    m = UndoManager(max_size=3)
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    m.add("A3", _state(3))
    m.add("A4", _state(4))    # doit évincer A1
    assert m.undo().title == "A4"
    assert m.undo().title == "A3"
    assert m.undo().title == "A2"
    assert m.undo() is None   # A1 évincé


def test_max_size_one():
    m = UndoManager(max_size=1)
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    e = m.undo()
    assert e.title == "A2"
    assert m.undo() is None


# ---------------------------------------------------------------------------
# UndoManager — history_list / future_list
# ---------------------------------------------------------------------------

def test_history_list_order():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    m.add("A3", _state(3))
    lst = m.history_list()
    assert [e.title for e in lst] == ["A3", "A2", "A1"]


def test_history_list_empty():
    m = UndoManager()
    assert m.history_list() == []


def test_future_list_order():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    e2 = m.undo()
    m.push_future(e2.title, _state(20))
    e1 = m.undo()
    m.push_future(e1.title, _state(10))
    lst = m.future_list()
    assert [e.title for e in lst] == ["A1", "A2"]


# ---------------------------------------------------------------------------
# UndoManager — clear
# ---------------------------------------------------------------------------

def test_clear():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    e = m.undo()
    m.push_future(e.title, _state(99))
    m.clear()
    assert not m.can_undo()
    assert not m.can_redo()
    assert m.history_list() == []
    assert m.future_list() == []


# ---------------------------------------------------------------------------
# Scénario complet undo/redo
# ---------------------------------------------------------------------------

def test_full_scenario():
    """Simule un workflow complet : action → undo → redo → nouvelle action."""
    m = UndoManager()

    # État initial : S0
    # Action 1 (état avant = S0) → S1
    m.add("Action 1", _state(0))
    # Action 2 (état avant = S1) → S2
    m.add("Action 2", _state(1))

    # Undo de Action 2 → retour à S1
    e = m.undo()
    assert e.title == "Action 2"
    assert e.state == _state(1)
    m.push_future("Action 2", _state(2))   # on sauvegarde S2 pour redo

    # Undo de Action 1 → retour à S0
    e = m.undo()
    assert e.title == "Action 1"
    assert e.state == _state(0)
    m.push_future("Action 1", _state(1))   # on sauvegarde S1 pour redo

    assert not m.can_undo()

    # Redo de Action 1 → retour à S1
    e = m.redo()
    assert e.title == "Action 1"
    assert e.state == _state(1)
    m.push_history("Action 1", _state(0))

    # Redo de Action 2 → retour à S2
    e = m.redo()
    assert e.title == "Action 2"
    assert e.state == _state(2)

    assert not m.can_redo()


def test_new_action_after_undo_clears_redo():
    m = UndoManager()
    m.add("A1", _state(1))
    m.add("A2", _state(2))
    e = m.undo()
    m.push_future(e.title, _state(99))
    assert m.can_redo()

    # Nouvelle action invalide le redo
    m.add("A3", _state(3))
    assert not m.can_redo()
    assert m.can_undo()
    assert m.undo().title == "A3"
