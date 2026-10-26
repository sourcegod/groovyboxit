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


# ---------------------------------------------------------------------------
# last_entry (Phase 7 étape 10d2)
# ---------------------------------------------------------------------------

def test_last_entry_empty_is_none():
    assert UndoManager().last_entry() is None


def test_last_entry_returns_without_removing():
    mgr = UndoManager()
    mgr.add("A", _state(1))
    mgr.add("B", _state(2))
    e = mgr.last_entry()
    assert e.title == "B"
    assert mgr.last_entry() is e
    assert [x.title for x in mgr.history_list()] == ["B", "A"]


def test_last_entry_follows_pop_last():
    mgr = UndoManager()
    mgr.add("A", _state(1))
    mgr.add("B", _state(2))
    mgr.pop_last()
    assert mgr.last_entry().title == "A"


# ---------------------------------------------------------------------------
# Numéros d'état et point propre (Phase 7 étape 16c1, docs/DESIGN.md § 16a1
# D1, D2). Les helpers reproduisent l'usage de ProjectMixin : Undo pris
# avant la modification, puis new_state() ; après restore,
# current_id = entry.state_id.
# ---------------------------------------------------------------------------

def _change(mgr, title="X"):
    mgr.add(title, _state(mgr.current_id))
    mgr.new_state()


def _undo(mgr):
    e = mgr.undo()
    mgr.push_future(e.title, _state(mgr.current_id))
    mgr.current_id = e.state_id


def _redo(mgr):
    e = mgr.redo()
    mgr.push_history(e.title, _state(mgr.current_id))
    mgr.current_id = e.state_id


def test_new_manager_is_clean():
    mgr = UndoManager()
    assert mgr.is_clean()
    assert mgr.current_id == mgr.saved_id == 0


def test_new_state_gives_distinct_increasing_ids():
    mgr = UndoManager()
    ids = [mgr.new_state() for _ in range(3)]
    assert ids == sorted(set(ids))
    assert mgr.current_id == ids[-1]
    assert not mgr.is_clean()


def test_mark_saved_makes_clean():
    mgr = UndoManager()
    mgr.new_state()
    mgr.mark_saved()
    assert mgr.is_clean()


def test_entry_default_state_id_is_0():
    assert UndoEntry("T", _state(0)).state_id == 0


def test_add_stores_current_id_in_entry():
    mgr = UndoManager()
    sid = mgr.new_state()
    mgr.add("A", _state(1))
    assert mgr.last_entry().state_id == sid


def test_undo_back_to_saved_state_is_clean():
    mgr = UndoManager()
    _change(mgr)
    _change(mgr)
    assert not mgr.is_clean()
    _undo(mgr)
    assert not mgr.is_clean()
    _undo(mgr)
    assert mgr.is_clean()


def test_redo_after_undo_to_saved_state_is_dirty_again():
    mgr = UndoManager()
    _change(mgr)
    _undo(mgr)
    assert mgr.is_clean()
    _redo(mgr)
    assert not mgr.is_clean()


def test_undo_past_a_save_is_dirty():
    """Le cas du booléen par entrée : ouvrir, changer, sauvegarder, Ctrl+Z."""
    mgr = UndoManager()
    _change(mgr)
    mgr.mark_saved()
    _undo(mgr)
    assert not mgr.is_clean()
    _redo(mgr)
    assert mgr.is_clean()


def test_ids_never_reused_after_undo():
    mgr = UndoManager()
    _change(mgr)
    first = mgr.current_id
    _undo(mgr)
    _change(mgr)                                 # autre branche
    assert mgr.current_id != first
    assert not mgr.is_clean()


def test_push_future_and_history_store_current_id():
    mgr = UndoManager()
    _change(mgr)
    before_undo = mgr.current_id
    _undo(mgr)
    assert mgr.future_list()[0].state_id == before_undo
    _redo(mgr)
    assert mgr.last_entry().state_id == 0


def test_pop_last_restores_id_of_removed_entry():
    mgr = UndoManager()
    _change(mgr)                                 # action annulée ensuite
    assert not mgr.is_clean()
    mgr.pop_last()
    assert mgr.is_clean()
    assert mgr.current_id == 0


def test_pop_last_on_already_dirty_project_keeps_it_dirty():
    mgr = UndoManager()
    _change(mgr)
    dirty = mgr.current_id
    _change(mgr)
    mgr.pop_last()
    assert mgr.current_id == dirty
    assert not mgr.is_clean()


def test_pop_last_after_save_during_open_action_stays_clean():
    """Ctrl+S pendant une prise live restée sans effet : contenu identique."""
    mgr = UndoManager()
    _change(mgr, "Prise")
    mgr.mark_saved()
    mgr.pop_last()
    assert mgr.is_clean()
    assert mgr.current_id == mgr.saved_id == 0


def test_pop_last_on_empty_history_changes_nothing():
    mgr = UndoManager()
    sid = mgr.new_state()
    mgr.pop_last()
    assert mgr.current_id == sid


def test_history_limit_keeps_ids_consistent():
    mgr = UndoManager(max_size=3)
    for _ in range(5):
        _change(mgr)
    assert len(mgr.history_list()) == 3
    for _ in range(3):
        _undo(mgr)
    assert mgr.current_id == 2                   # le plus ancien état gardé
    assert not mgr.is_clean()


def test_clear_keeps_ids():
    mgr = UndoManager()
    _change(mgr)
    sid = mgr.current_id
    mgr.clear()
    assert mgr.current_id == sid
    assert not mgr.is_clean()
