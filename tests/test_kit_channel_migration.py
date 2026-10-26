#python3
"""
    File: tests/test_kit_channel_migration.py
    Tests de la migration des canaux (Phase 7 étape 10h7, docs/DESIGN.md
    § 10h7) : à l'ouverture d'un projet sans track_channels, les pistes dont
    le slot est un kit passent sur le canal 10 ; un projet qui a ses canaux
    n'est pas touché ; Pattern.apply_kit_channels n'agit qu'une fois.
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
# Pattern : drapeau et apply_kit_channels
# ---------------------------------------------------------------------------

def test_flag_set_only_when_key_missing():
    p = Pattern()
    assert p._needs_kit_channels is False
    p.from_dict(_old_pattern_dict([PIANO, KIT]))
    assert p._needs_kit_channels is True
    p.from_dict(Pattern().to_dict())          # Pattern réutilisé, clé présente
    assert p._needs_kit_channels is False
    print("  _needs_kit_channels : vrai seulement sans track_channels : OK")

def test_kit_tracks_move_to_channel_10():
    rack = _rack()
    p = Pattern()
    p.from_dict(_old_pattern_dict([PIANO, KIT, PIANO, KIT]))
    changed = p.apply_kit_channels(_is_kit(rack))
    assert p._track_channels[:4] == [0, 9, 2, 9]
    assert changed[:2] == [1, 3]
    assert p._track_channels[4:] == [9] * 12          # pistes vides sur le slot kit
    print("  pistes kit → canal 10, piste synthé gardée : OK")

def test_apply_only_once():
    rack = _rack()
    p = Pattern()
    p.from_dict(_old_pattern_dict([KIT]))
    p.apply_kit_channels(_is_kit(rack))
    p._track_channels[0] = 4                           # réglage ultérieur
    assert p.apply_kit_channels(_is_kit(rack)) == []
    assert p._track_channels[0] == 4
    print("  apply_kit_channels : une seule fois, puis sans effet : OK")

def test_saved_channels_untouched():
    rack = _rack()
    src = Pattern()
    src._track_slots[1] = KIT
    src._track_channels[1] = 1                         # kit laissé sur le canal 2
    p = Pattern()
    p.from_dict(src.to_dict())
    assert p.apply_kit_channels(_is_kit(rack)) == []
    assert p._track_channels[1] == 1
    print("  canaux enregistrés : migration sans effet : OK")

def test_saved_after_migration_keeps_channels():
    rack = _rack()
    p = Pattern()
    p.from_dict(_old_pattern_dict([PIANO, KIT]))
    p.apply_kit_channels(_is_kit(rack))
    q = Pattern()
    q.from_dict(p.to_dict())
    assert q._needs_kit_channels is False and q._track_channels[:2] == [0, 9]
    print("  projet migré puis réenregistré : canaux conservés, plus de migration : OK")


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

def test_load_project_with_channels_untouched(tmp_path):
    src = Pattern()
    src._track_slots[1] = KIT
    src._track_channels[1] = 1
    path = _write_project(tmp_path, [src.to_dict()])
    win = _FakeProjectWindow(path)
    win._load_project()
    assert win._pattern_list[0]._track_channels[1] == 1
    print("  _load_project d'un projet avec canaux : réglage conservé : OK")
