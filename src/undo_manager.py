#python3
"""
    File: src/undo_manager.py
    Gestionnaire Undo/Redo — historique de snapshots d'état complet.
    Date: Sat, 21/06/2026
    Author: Coolbrother
"""
import time

MAX_HISTORY = 50


class UndoEntry:
    __slots__ = ("title", "timestamp", "state")

    def __init__(self, title, state, timestamp=None):
        self.title     = title
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.state     = state

    def rel_time(self):
        delta = time.time() - self.timestamp
        if delta < 60:
            return f"il y a {int(delta)} s"
        if delta < 3600:
            return f"il y a {int(delta // 60)} min"
        return f"il y a {int(delta // 3600)} h"


class UndoManager:
    """Pile d'historique Undo/Redo basée sur des snapshots d'état complet.

    Utilisation :
        # Avant chaque action modifiant l'état :
        mgr.add("Coller", state_dict)

        # Ctrl+Z :
        entry = mgr.undo()
        if entry:
            current = capture_current()
            mgr.push_future(entry.title, current)
            restore(entry.state)

        # Shift+Z :
        entry = mgr.redo()
        if entry:
            current = capture_current()
            mgr.push_history(entry.title, current)
            restore(entry.state)
    """

    def __init__(self, max_size=MAX_HISTORY):
        self._history = []   # list[UndoEntry], plus ancien en tête
        self._future  = []   # list[UndoEntry], plus récent en queue
        self._max     = max_size

    # ------------------------------------------------------------------

    def add(self, title, state, timestamp=None):
        """Enregistre un point de sauvegarde AVANT une modification.
        Vide le futur (redo) car un nouvel historique commence.
        timestamp : si fourni, horodatage pré-calculé (utile quand _capture_state
        est lent — on capture time.time() avant l'appel à la sérialisation).
        """
        self._history.append(UndoEntry(title, state, timestamp))
        if len(self._history) > self._max:
            self._history.pop(0)
        self._future.clear()

    def pop_last(self):
        """Retire silencieusement la dernière entrée de l'historique.

        À utiliser quand un dialog (renommage, etc.) est annulé ou que
        l'action n'a finalement rien changé, afin d'éviter une entrée
        undo sans effet.
        """
        if self._history:
            self._history.pop()

    def undo(self):
        """Retourne l'entrée la plus récente de l'historique (à restaurer).
        Retourne None si l'historique est vide.
        L'appelant est responsable de pousser l'état courant dans le futur.
        """
        if not self._history:
            return None
        return self._history.pop()

    def redo(self):
        """Retourne l'entrée la plus récente du futur (à restaurer).
        Retourne None si le futur est vide.
        L'appelant est responsable de pousser l'état courant dans l'historique.
        """
        if not self._future:
            return None
        return self._future.pop()

    def push_future(self, title, state):
        """Stocke l'état courant dans le futur (appelé après undo)."""
        self._future.append(UndoEntry(title, state))

    def push_history(self, title, state):
        """Re-pousse l'état courant dans l'historique (appelé après redo)."""
        self._history.append(UndoEntry(title, state))

    # ------------------------------------------------------------------

    def history_list(self):
        """Retourne l'historique du plus récent au plus ancien."""
        return list(reversed(self._history))

    def future_list(self):
        """Retourne le futur (redoable) du plus récent au plus ancien."""
        return list(reversed(self._future))

    def can_undo(self):
        return bool(self._history)

    def can_redo(self):
        return bool(self._future)

    def clear(self):
        self._history.clear()
        self._future.clear()
