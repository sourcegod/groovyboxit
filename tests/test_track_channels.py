#python3
"""
    File: tests/test_track_channels.py
    Tests du canal MIDI par piste (Phase 7 étape 10f1, docs/DESIGN.md § 10a1
    D5 révisée en 10a2) : défaut piste N → canal N, sérialisation et
    migration, règle du kit (TrackRouter.channel_after_slot /
    assign_slot_by_user), ce qui ne touche pas au canal (Program Change,
    assign_slot seul), synchronisation store ↔ router, Ctrl+T et dialog de
    propriétés de piste (Undo posé, retiré si Annuler ou inchangé).
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import sys
import os
import copy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wx
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pattern import Pattern
from rack import Rack, InstrumentType
from track_router import TrackRouter
from ui.mw_tracks import TrackMixin
from ui.mw_patterns import PatternMixin
from ui.mw_songs import SongMixin


KIT, PIANO, GUITAR, EMPTY = 0, 1, 2, 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSoundManager:
    def play_sound(self, *a): pass
    def stop_all(self):       pass


def _make_router():
    rack = Rack()
    rack.set_slot(KIT,    InstrumentType.KIT,   "Default Kit", {})
    rack.set_slot(PIANO,  InstrumentType.SYNTH, "Piano",       {"patch": "piano_1"})
    rack.set_slot(GUITAR, InstrumentType.SYNTH, "Guitar",      {"patch": "guitar_1"})
    router = TrackRouter(rack, "/fake/synths", _FakeSoundManager(), lambda msg: None)
    router._ensure_slot_synth = lambda slot_idx: None   # pas de chargement de patch
    return router


# ---------------------------------------------------------------------------
# Défaut et sérialisation (Pattern)
# ---------------------------------------------------------------------------

def test_default_channel_is_track_index_capped_at_16():
    assert [Pattern.default_channel(t) for t in range(16)] == list(range(16))
    assert Pattern.default_channel(16) == 15 and Pattern.default_channel(40) == 15
    assert Pattern.KIT_CHANNEL == 9
    assert Pattern()._track_channels == list(range(16))
    print("  défaut : piste N → canal N, canal 16 au-delà : OK")

def test_channels_round_trip():
    p = Pattern()
    p._track_channels[3] = 9
    p._track_channels[12] = 0
    d = p.to_dict()
    assert d["track_channels"][3] == 9
    q = Pattern()
    q.from_dict(d)
    assert q._track_channels == p._track_channels
    print("  track_channels : aller-retour to_dict/from_dict : OK")

def test_missing_key_resets_default_channels():
    """Preset d'avant 10f1 rechargé dans un Pattern existant (Ctrl+O) : les
    canaux du projet précédent ne doivent pas survivre."""
    d = Pattern().to_dict()
    del d["track_channels"]
    q = Pattern()
    q._track_channels = [9] * 16
    q.from_dict(d)
    assert q._track_channels == list(range(16))
    print("  clé absente : canaux remis par défaut, même sur un Pattern réutilisé : OK")

def test_short_channel_list_completed_by_index():
    d = Pattern().to_dict()
    d["track_channels"] = [9, 9, 2]
    before = copy.deepcopy(d)
    q = Pattern()
    q.from_dict(d)
    assert q._track_channels == [9, 9, 2] + list(range(3, 16))
    assert d == before
    print("  liste courte : complétée par le canal de chaque index, dict intact : OK")


# ---------------------------------------------------------------------------
# Règle du kit (TrackRouter)
# ---------------------------------------------------------------------------

def test_router_default_channels():
    router = _make_router()
    assert router._track_channels == list(range(TrackRouter.NUM_TRACKS))
    assert router.get_track_channel(4) == 4
    print("  router : canaux par défaut : OK")

def test_set_track_channel_clamps():
    router = _make_router()
    router.set_track_channel(2, 20)
    assert router.get_track_channel(2) == 15
    router.set_track_channel(2, -1)
    assert router.get_track_channel(2) == 0
    print("  set_track_channel borné à 0..15 : OK")

def test_channel_after_slot_rules():
    router = _make_router()
    assert router.channel_after_slot(3, KIT, 3) == 9       # kit → 10
    assert router.channel_after_slot(3, PIANO, 9) == 3     # synthé, était sur 10 → défaut
    assert router.channel_after_slot(9, PIANO, 9) == 9     # piste 10 reste sur 10
    assert router.channel_after_slot(5, PIANO, 7) == 7     # canal manuel conservé
    assert router.channel_after_slot(5, EMPTY, 9) == 5     # slot vide : comme un synthé
    assert router.channel_after_slot(15, GUITAR, 9) == 15
    print("  channel_after_slot : kit → 10, retour au défaut, canal manuel gardé : OK")

def test_assign_slot_by_user_applies_rule():
    router = _make_router()
    router.assign_slot_by_user(4, KIT)
    assert router.slot_for_track(4) == KIT and router.get_track_channel(4) == 9
    router.assign_slot_by_user(4, PIANO)
    assert router.slot_for_track(4) == PIANO and router.get_track_channel(4) == 4
    print("  assign_slot_by_user : kit → 10, puis synthé → canal par défaut : OK")

def test_assign_slot_alone_keeps_channel():
    """Chargement d'un projet : assign_slot seul, le canal ne bouge pas."""
    router = _make_router()
    router.assign_slot(4, KIT)
    assert router.get_track_channel(4) == 4
    print("  assign_slot seul (chargement de projet) : canal inchangé : OK")

def test_program_change_keeps_channel():
    router = _make_router()
    router.on_program_change_tape(6, KIT)
    assert router.slot_for_track(6) == KIT
    assert router.get_track_channel(6) == 6
    print("  Program Change (pont assign_slot) : canal inchangé : OK")


# ---------------------------------------------------------------------------
# Synchronisation store ↔ router
# ---------------------------------------------------------------------------

class _FakeStoreWindow(PatternMixin, SongMixin):
    def __init__(self):
        self._router          = _make_router()
        self._player          = MagicMock()
        self._player._pattern = Pattern()
        self._player.bpm      = 120
        self._pattern_list    = [Pattern() for _ in range(2)]
        self._cur_pattern_idx = 0
        self._bpm_ctrl        = MagicMock()
        self._pattern_listbox = MagicMock()
        self._song_window     = None
    def _show_status(self, msg): pass

def test_flush_copies_channels_to_store():
    win = _FakeStoreWindow()
    win._router._track_channels[2] = 9
    pat = win._pattern_list[0]
    win._flush_pattern_to_store(pat)
    assert pat._track_channels[2] == 9
    assert pat._track_channels is not win._router._track_channels
    print("  _flush_pattern_to_store : canaux copiés dans le store : OK")

def test_apply_loads_channels_into_router():
    win = _FakeStoreWindow()
    new = win._pattern_list[1]
    new._track_channels[7] = 9
    channels = win._router._track_channels
    win._apply_pattern_from_store(new)
    assert win._router._track_channels[7] == 9
    assert win._router._track_channels is channels     # liste du router conservée
    print("  _apply_pattern_from_store : canaux chargés dans le router : OK")

def test_song_advance_loads_channels_into_router():
    win = _FakeStoreWindow()
    win._pattern_list[1]._track_channels[0] = 9
    win._on_song_advance(1)
    assert win._router._track_channels[0] == 9
    print("  enchaînement du song : canaux du pattern suivant chargés : OK")


# ---------------------------------------------------------------------------
# Fenêtre : Ctrl+T et dialog de propriétés de piste
# ---------------------------------------------------------------------------

class _FakeTrackWindow(TrackMixin):
    def __init__(self, cur_track=3, modified=False):
        self._router           = _make_router()
        self._rack             = self._router._rack
        self._player           = SimpleNamespace(_cur_track=cur_track)
        self._cur_slot         = KIT
        self._slot_choice      = MagicMock()
        self._project_modified = modified
        self.calls             = []
    def _refresh_track_list(self):  pass
    def _show_status(self, msg):    self.calls.append(('status', msg))
    def _play_toggle(self):         pass
    def _add_undo(self, title):
        self.calls.append(('_add_undo', title))
        self._project_modified = True
    def _pop_last_undo(self):       self.calls.append('_pop_last_undo')
    def _update_title(self):        self.calls.append('_update_title')


def _fake_dialog(result, values=None, seen=None):
    """values : (slot, vol, pan, mute, solo, channel) rendus par le dialog ;
    None = valeurs initiales inchangées."""
    class FakeDlg:
        def __init__(self, parent, tidx, rack, slot, vol, pan, mute, solo, **kw):
            self._v = values or (slot, vol, pan, mute, solo, kw["channel"])
            if seen is not None:
                seen.update(kw, initial=(slot, vol, pan, mute, solo))
        def ShowModal(self):    return result
        def get_slot_idx(self): return self._v[0]
        def get_volume(self):   return self._v[1]
        def get_pan(self):      return self._v[2]
        def get_mute(self):     return self._v[3]
        def get_solo(self):     return self._v[4]
        def get_channel(self):  return self._v[5]
        def Destroy(self):      pass
    return FakeDlg

def test_ctrl_t_kit_sets_channel_10_and_announces_it():
    win = _FakeTrackWindow(cur_track=3)
    win._cur_slot = KIT
    win._assign_track_slot()
    assert win._router.get_track_channel(3) == 9
    assert win.calls[-1] == ('status', "Piste 4 → Slot_01 (Default Kit), canal 10")
    win._cur_slot = PIANO
    win._assign_track_slot()
    assert win._router.get_track_channel(3) == 3
    print("  Ctrl+T : kit → canal 10 annoncé, synthé → retour au canal 4 : OK")

def test_dialog_receives_channel_and_rule():
    seen = {}
    win = _FakeTrackWindow(cur_track=3)
    win._router.set_track_channel(3, 11)
    with patch("ui.mw_tracks.TrackPropertiesDialog", _fake_dialog(wx.ID_CANCEL, seen=seen)):
        win._track_properties_dialog()
    assert seen["channel"] == 11
    assert seen["channel_after_slot"](KIT, 11) == 9
    assert seen["channel_after_slot"](PIANO, 9) == 3      # défaut de la piste 4
    print("  dialog : canal courant et règle du kit transmis : OK")

def test_dialog_ok_with_change_keeps_undo():
    win = _FakeTrackWindow(cur_track=3)
    vals = (KIT, 100, 0, False, False, 12)
    with patch("ui.mw_tracks.TrackPropertiesDialog", _fake_dialog(wx.ID_OK, vals)):
        win._track_properties_dialog()
    assert win._router.get_track_channel(3) == 12
    assert ('_add_undo', "Propriétés piste 4") in win.calls
    assert '_pop_last_undo' not in win.calls
    assert win._project_modified is True
    print("  dialog Ok avec changement : canal appliqué, Undo gardé : OK")

def test_dialog_ok_unchanged_pops_undo_and_restores_state():
    win = _FakeTrackWindow(cur_track=3, modified=False)
    with patch("ui.mw_tracks.TrackPropertiesDialog", _fake_dialog(wx.ID_OK)):
        win._track_properties_dialog()
    assert '_pop_last_undo' in win.calls and '_update_title' in win.calls
    assert win._project_modified is False
    assert win.calls[-1] == ('status', "Piste 4: propriétés inchangées")
    print("  dialog Ok sans changement : Undo retiré, projet non modifié : OK")

def test_dialog_cancel_restores_values_and_state():
    win = _FakeTrackWindow(cur_track=3, modified=True)
    vals = (KIT, 10, 50, True, True, 9)
    with patch("ui.mw_tracks.TrackPropertiesDialog", _fake_dialog(wx.ID_CANCEL, vals)):
        win._track_properties_dialog()
    r = win._router
    assert (r.slot_for_track(3), r.get_track_volume(3), r.get_track_pan(3),
            r._track_mutes[3], r._track_solos[3], r.get_track_channel(3)) \
        == (0, 100, 0, False, False, 3)
    assert '_pop_last_undo' in win.calls
    assert win._project_modified is True     # déjà modifié avant : reste modifié
    print("  dialog Annuler : valeurs d'origine rétablies, Undo retiré : OK")
