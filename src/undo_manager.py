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
    __slots__ = ("title", "timestamp", "state", "state_id")

    def __init__(self, title, state, timestamp=None, state_id=0):
        self.title     = title
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.state     = state
        self.state_id  = state_id   # numéro de l'état contenu (Phase 7 étape 16b1)

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

    Numéros d'état (Phase 7 étape 16b1, docs/DESIGN.md § 16a1 D1, D2) :
    current_id est l'état courant, saved_id celui du fichier ; chaque
    entrée garde le numéro de l'état qu'elle contient. Après chaque
    modification, new_state() ; après une sauvegarde, mark_saved() ; après
    restore(entry.state), current_id = entry.state_id. is_clean() dit si
    l'état courant est celui du fichier.
    """

    def __init__(self, max_size=MAX_HISTORY):
        self._history = []   # list[UndoEntry], plus ancien en tête
        self._future  = []   # list[UndoEntry], plus récent en queue
        self._max     = max_size
        self.current_id = 0
        self.saved_id   = 0
        self._next_id   = 1

    # ------------------------------------------------------------------
    # Numéros d'état

    def new_state(self):
        """Nouveau numéro pour l'état courant, après une modification."""
        self.current_id = self._next_id
        self._next_id  += 1
        return self.current_id

    def mark_saved(self):
        """L'état courant est celui du fichier."""
        self.saved_id = self.current_id

    def is_clean(self):
        """Vrai si l'état courant est celui du fichier."""
        return self.current_id == self.saved_id

    # ------------------------------------------------------------------

    def add(self, title, state, timestamp=None):
        """Enregistre un point de sauvegarde AVANT une modification.
        Vide le futur (redo) car un nouvel historique commence.
        timestamp : si fourni, horodatage pré-calculé (utile quand _capture_state
        est lent — on capture time.time() avant l'appel à la sérialisation).
        """
        self._history.append(UndoEntry(title, state, timestamp, self.current_id))
        if len(self._history) > self._max:
            self._history.pop(0)
        self._future.clear()

    def pop_last(self):
        """Retire silencieusement la dernière entrée de l'historique.

        À utiliser quand un dialog (renommage, etc.) est annulé ou que
        l'action n'a finalement rien changé, afin d'éviter une entrée
        undo sans effet.

        L'état n'a pas changé : le numéro de l'entrée redevient le numéro
        courant (Phase 7 étape 16b1, D2). Si une sauvegarde a eu lieu
        entre-temps (contenu identique), saved_id le suit aussi.
        """
        if self._history:
            entry = self._history.pop()
            if self.current_id == self.saved_id:
                self.saved_id = entry.state_id
            self.current_id = entry.state_id

    def last_entry(self):
        """Dernière entrée de l'historique (None si vide), sans la retirer."""
        return self._history[-1] if self._history else None

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
        self._future.append(UndoEntry(title, state, state_id=self.current_id))

    def push_history(self, title, state):
        """Re-pousse l'état courant dans l'historique (appelé après redo)."""
        self._history.append(UndoEntry(title, state, state_id=self.current_id))

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
