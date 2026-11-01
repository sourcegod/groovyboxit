#python3
"""
    File: tests/test_kit_channel_migration.py
    Tests de la règle « kit → canal 10 » des données. D'abord migration des
    projets sans canaux (Phase 7 étape 10h7) ; depuis la Phase 8 étape 3c1
    (docs/DESIGN.md § 3a K1-K7) : une piste sur un kit restée sur son canal
    par défaut passe au canal 10, un canal choisi est gardé, synthé et
    banque intacts, règle sans effet la seconde fois ; appliquée aux 99
    patterns au démarrage (projet absent compris, routeur aligné), à Ctrl+N
    et à Ctrl+O, ni Undo ni « modifié », compte rendu de Ctrl+O.
    Date: Wed, 21/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock

from pattern import Pattern
from rack import Rack, InstrumentType
from song import Song
from project_manager import ProjectManager
from undo_manager import UndoManager
from ui.mw_project import ProjectMixin


KIT, PIANO = 0, 1


def _rack():
    rack = Rack()
    rack.set_slot(KIT,   InstrumentType.KIT,   "TR-707",  {"kit": "k.json"})
    rack.set_slot(PIANO, InstrumentType.SYNTH, "Piano 1", {"patch": "p.json"})
    return rack

def _is_kit(rack):
    return lambda slot_idx: rack.get_slot(slot_idx).type == InstrumentType.KIT

def _old_pattern_dict(slots):
    """Pattern sauvé avant 10f1 : pas de clé track_channels."""
    p = Pattern()
    p._track_slots = list(slots) + [KIT] * (16 - len(slots))
    d = p.to_dict()
    del d["track_channels"]
    return d


# ---------------------------------------------------------------------------
# Pattern.apply_kit_channels (Phase 8 étape 3c1, § 3a K1, K4)
# ---------------------------------------------------------------------------

BANK = 5

def _bank_rack():
    rack = _rack()
    rack.set_slot(BANK, InstrumentType.BANK, "FluidR3", {"bank_slot": 0})
    return rack

def test_no_flag_any_more():
    """Le drapeau de 10h7 est retiré : la règle ne dépend plus de la clé
    track_channels."""
    p = Pattern()
    assert not hasattr(p, "_needs_kit_channels")
    p.from_dict(_old_pattern_dict([PIANO, KIT]))
    assert not hasattr(p, "_needs_kit_channels")
    print("  plus de drapeau _needs_kit_channels : OK")

def test_kit_tracks_move_to_channel_10():
    rack = _rack()
    p = Pattern()
    p.from_dict(_old_pattern_dict([PIANO, KIT, PIANO, KIT]))
    changed = p.apply_kit_channels(_is_kit(rack))
    assert p._track_channels[:4] == [0, 9, 2, 9]
    assert changed[:2] == [1, 3]
    assert p._track_channels[4:] == [9] * 12          # pistes vides sur le slot kit
    assert 9 not in changed                           # piste 10 déjà au canal 10
    print("  projet sans canaux : pistes kit → canal 10, piste synthé gardée : OK")

def test_new_pattern_all_kit_tracks_move():
    """Pattern créé sans réglage : toutes ses pistes sur le kit du slot 0,
    canaux 1 à 16 → toutes au canal 10 (cas trouvé à l'essai, § 2p2)."""
    p = Pattern()
    changed = p.apply_kit_channels(_is_kit(_rack()))
    assert p._track_channels == [9] * 16
    assert changed == [t for t in range(16) if t != 9]
    print("  pattern neuf : toutes les pistes kit au canal 10 : OK")

def test_chosen_channel_kept():
    """K1 : un canal autre que le canal par défaut est un choix, gardé."""
    p = Pattern()
    p._track_channels[0] = 4                           # piste 1 mise au canal 5
    p._track_channels[3] = 0                           # piste 4 mise au canal 1
    p.apply_kit_channels(_is_kit(_rack()))
    assert p._track_channels[0] == 4 and p._track_channels[3] == 0
    print("  kit sur un canal choisi : gardé : OK")

def test_choice_equal_to_default_is_corrected():
    """Limite acceptée de K1 (ancien test de 10h8 : kit « laissé sur le
    canal 2 ») : la piste 2 au canal 2 est sur son canal par défaut, elle
    passe au canal 10."""
    rack = _rack()
    src = Pattern()
    src._track_slots[1] = KIT
    src._track_channels[1] = 1
    p = Pattern()
    p.from_dict(src.to_dict())
    assert 1 in p.apply_kit_channels(_is_kit(rack))
    assert p._track_channels[1] == 9
    print("  piste 2 au canal 2 (son canal par défaut) : passe au canal 10 : OK")

def test_synth_and_bank_tracks_untouched():
    rack = _bank_rack()
    p = Pattern()
    p._track_slots[:4] = [PIANO, BANK, BANK, KIT]
    p._track_channels[2] = 9                           # banque : batterie au canal 10
    assert p.apply_kit_channels(_is_kit(rack))[:1] == [3]
    assert p._track_channels[:4] == [0, 1, 9, 9]
    print("  synthé et banque intacts (banque au canal 10 comprise) : OK")

def test_second_application_does_nothing():
    rack = _rack()
    p = Pattern()
    p.apply_kit_channels(_is_kit(rack))
    p._track_channels[0] = 4                           # réglage ultérieur
    assert p.apply_kit_channels(_is_kit(rack)) == []
    assert p._track_channels[0] == 4
    print("  seconde application sans effet, réglage ultérieur gardé : OK")

def test_saved_after_rule_keeps_channels():
    rack = _rack()
    p = Pattern()
    p.from_dict(_old_pattern_dict([PIANO, KIT]))
    p.apply_kit_channels(_is_kit(rack))
    q = Pattern()
    q.from_dict(p.to_dict())
    assert q._track_channels[:2] == [0, 9]
    assert q.apply_kit_channels(_is_kit(rack)) == []
    print("  projet mis en règle puis réenregistré : canaux conservés : OK")


# ---------------------------------------------------------------------------
# _load_project (Ctrl+O, démarrage) sur un vrai .gvp
# ---------------------------------------------------------------------------

class _FakeProjectWindow(ProjectMixin):
    def __init__(self, path):
        self._project_path     = path
        self._rack             = Rack()
        self._pattern_list     = [Pattern() for _ in range(3)]
        self._song_list        = [Song(i) for i in range(2)]
        self._song_window      = None
        self._player           = MagicMock()
        self._player._cur_track = 0
        self._router           = MagicMock()
        self._slot_choice      = MagicMock()
        self._volume_ctrl      = MagicMock()   # volume et pan globaux (Phase 7 étape 15d1)
        self._pan_ctrl         = MagicMock()
        self._master_defaults  = (100, 0)
        self._undo             = UndoManager()   # _project_modified en dépend (Phase 7 étape 16d1)
        self._project_modified = True
        self.applied           = []
    def _apply_pattern_from_store(self, new): self.applied.append(new)
    def _update_slot_list(self):        pass
    def _refresh_pattern_listbox(self): pass
    def _load_kit_slot(self, idx):      pass
    def _refresh_grid(self):            pass
    def _refresh_all_voice_display(self): pass
    def _refresh_track_list(self):      pass
    def _refresh_pad_list(self):        pass
    def _update_title(self):            pass
    def _show_status(self, msg):        pass

def _write_project(tmp_path, patterns):
    path = str(tmp_path / "ancien.gvp")
    ProjectManager.save(path, {"version": 1, "rack": _rack().to_dict(),
                               "patterns": patterns, "songs": [], "cur_song": 0})
    return path

def test_load_old_project_moves_kit_tracks(tmp_path):
    path = _write_project(tmp_path, [_old_pattern_dict([PIANO, KIT]),
                                     _old_pattern_dict([KIT, PIANO])])
    win = _FakeProjectWindow(path)
    win._load_project()
    assert win._pattern_list[0]._track_channels[:2] == [0, 9]
    assert win._pattern_list[1]._track_channels[:2] == [9, 1]
    assert win.applied[0] is win._pattern_list[0]   # le router reçoit le pattern migré
    assert win._project_modified is False
    print("  _load_project d'un ancien projet : pistes kit sur 10, router alimenté : OK")

def test_load_project_keeps_chosen_and_corrects_default(tmp_path):
    src = Pattern()
    src._track_slots[:3] = [PIANO, KIT, KIT]
    src._track_channels[1] = 1                          # canal par défaut : corrigé
    src._track_channels[2] = 6                          # choisi : gardé
    path = _write_project(tmp_path, [src.to_dict()])
    win = _FakeProjectWindow(path)
    win._load_project()
    assert win._pattern_list[0]._track_channels[:3] == [0, 9, 6]
    print("  _load_project : canal par défaut corrigé, canal choisi gardé : OK")


# ---------------------------------------------------------------------------
# Moments : Ctrl+O, démarrage, Ctrl+N (Phase 8 étape 3c1, § 3a K2, K5-K7)
# ---------------------------------------------------------------------------

def test_load_project_applies_rule_to_every_pattern(tmp_path):
    a, b = Pattern(), Pattern()                         # pistes sur le kit, canaux par défaut
    b._track_slots = [PIANO] * 16
    path = _write_project(tmp_path, [a.to_dict(), b.to_dict()])
    win = _FakeProjectWindow(path)
    win._load_project()
    assert win._pattern_list[0]._track_channels == [9] * 16
    assert win._pattern_list[1]._track_channels == list(range(16))
    assert win._pattern_list[2]._track_channels == [9] * 16      # absent du fichier : neuf
    assert win._kit_rule_count == 2 * 15
    assert win.applied[0]._track_channels == [9] * 16            # routeur : canaux justes
    print("  Ctrl+O : règle sur tous les patterns avant le routeur : OK")

def test_load_project_neither_undo_nor_modified(tmp_path):
    path = _write_project(tmp_path, [Pattern().to_dict()])
    win = _FakeProjectWindow(path)
    win._load_project()
    assert win._kit_rule_count > 0
    assert win._project_modified is False
    assert not win._undo.can_undo()
    print("  Ctrl+O : ni Undo ni « modifié » : OK")

def test_loaded_message_counts_kit_tracks(tmp_path):
    win = _FakeProjectWindow(str(tmp_path / "x.gvp"))
    win._project_path = str(tmp_path / "projet.gvp")
    win._kit_rule_count = 12
    assert win._project_loaded_msg() == \
        "Projet chargé : projet.gvp — 12 pistes kit mises au canal 10"
    win._kit_rule_count = 1
    assert win._project_loaded_msg() == \
        "Projet chargé : projet.gvp — 1 piste kit mise au canal 10"
    win._kit_rule_count = 0
    assert win._project_loaded_msg() == "Projet chargé : projet.gvp"
    print("  message de Ctrl+O : nombre de pistes mises au canal 10, ou rien : OK")

def test_ctrl_o_reports_count(tmp_path, monkeypatch):
    import ui.mw_project as mwp
    import wx
    path = _write_project(tmp_path, [Pattern().to_dict()])
    win = _FakeProjectWindow(path)
    win._project_modified = False
    win._projects_dir = str(tmp_path)
    win._take = None
    said = []
    win._show_status = said.append
    class Dlg:
        def __init__(self, *a, **k): pass
        def ShowModal(self): return wx.ID_OK
        def GetPath(self):   return path
        def Destroy(self):   pass
    monkeypatch.setattr(mwp.wx, "FileDialog", Dlg)
    win._open_project()
    assert said[-1] == "Projet chargé : ancien.gvp — 45 pistes kit mises au canal 10"
    print("  Ctrl+O : compte rendu au statut : OK")


class _Router:
    """Routeur minimal : canaux des pistes, réglés par set_track_channel."""
    def __init__(self):
        self._track_channels = [Pattern.default_channel(t) for t in range(16)]
        self.set_calls = []
    def get_track_channel(self, t):
        return self._track_channels[t]
    def set_track_channel(self, t, ch):
        self.set_calls.append((t, ch))
        self._track_channels[t] = ch


def test_startup_without_project_file(tmp_path):
    """Démarrage sans fichier de projet : patterns neufs mis en règle, et
    le routeur suit le pattern courant."""
    win = _FakeProjectWindow(str(tmp_path / "absent.gvp"))
    win._rack = _rack()                                           # Rack de démarrage : kit au slot 0
    win._router = _Router()
    win._pattern_list[1]._track_slots = [PIANO] * 16
    win._cur_pattern_idx = 0
    win._load_project()
    assert win._pattern_list[0]._track_channels == [9] * 16
    assert win._pattern_list[1]._track_channels == list(range(16))
    assert win._router._track_channels == [9] * 16
    assert len(win._router.set_calls) == 15                       # piste 10 déjà au canal 10
    assert win._project_modified is False and win._kit_rule_count == 0
    print("  démarrage sans projet : patterns et routeur au canal 10 : OK")


def test_new_project_applies_rule(tmp_path):
    win = _FakeProjectWindow(str(tmp_path / "x.gvp"))
    win._rack = _rack()
    win._project_modified = False
    win._projects_dir = str(tmp_path)
    win._take = None
    win._pattern_listbox = MagicMock()
    seen = {}
    win._apply_pattern_from_store = lambda new: seen.setdefault("channels", list(new._track_channels))
    win._new_project()
    assert len(win._pattern_list) == 99
    assert all(p._track_channels == [9] * 16 for p in win._pattern_list)
    assert seen["channels"] == [9] * 16                           # avant le routeur
    assert win._project_modified is False and not win._undo.can_undo()
    print("  Ctrl+N : 99 patterns neufs au canal 10, avant le routeur : OK")

