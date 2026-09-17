import threading
import wx
from rack import InstrumentType
from pattern import ETYPE_GRID, ETYPE_PATCH


class PlaybackMixin:
    """MidiEditorWindow — solo/mute piste, lecture preview et annonces de statut."""

    # ------------------------------------------------------------------
    # Solo / Mute piste
    # ------------------------------------------------------------------

    def _toggle_track_solo(self):
        """S : bascule le solo des pistes sélectionnées, sinon de la piste courante."""
        te     = self._parent._track_editor
        track  = self._parent._player._cur_track
        tracks = te.get_effective_tracks(track)
        router = self._parent._router
        states = [router.toggle_track_solo(t) for t in tracks]
        self._parent._refresh_track_list()
        if len(tracks) == 1:
            self._set_status(f"Piste {tracks[0] + 1}: Solo {'On' if states[0] else 'Off'}")
        else:
            noms = ", ".join(str(t + 1) for t in tracks)
            self._set_status(f"Pistes {noms}: Solo basculé")

    def _toggle_track_mute(self):
        """X : bascule le mute des pistes sélectionnées, sinon de la piste courante."""
        te     = self._parent._track_editor
        track  = self._parent._player._cur_track
        tracks = te.get_effective_tracks(track)
        router = self._parent._router
        states = [router.toggle_track_mute(t) for t in tracks]
        self._parent._refresh_track_list()
        if len(tracks) == 1:
            self._set_status(f"Piste {tracks[0] + 1}: Mute {'On' if states[0] else 'Off'}")
        else:
            noms = ", ".join(str(t + 1) for t in tracks)
            self._set_status(f"Pistes {noms}: Mute basculé")

    # ------------------------------------------------------------------
    # Lecture sonore (preview)
    # ------------------------------------------------------------------

    def _stop_preview(self):
        """Annule le timer en cours et arrête toutes les notes preview."""
        if self._preview_timer is not None:
            self._preview_timer.cancel()
            self._preview_timer = None
        if self._preview_midis:
            router = self._parent._router
            if router.synth_ready():
                for midi in self._preview_midis:
                    router.synth.stop(midi)
            self._preview_midis = []

    def _play_event(self, ev):
        """Joue le son d'un événement note (appelé depuis _play_group_at)."""
        if ev.get("type") != "note":
            return
        etype = ev.get("etype")
        vel   = max(1, min(127, ev.get("vel", 100)))
        slot  = self._parent._rack.get_slot(self._parent._cur_slot)
        if slot.type == InstrumentType.SYNTH:
            router = self._parent._router
            if not router.synth_ready():
                router.load_slot_preview(self._parent._cur_slot)
                return
            if etype == ETYPE_GRID:
                pad = ev["pad"]
                if pad >= len(router.kb_notes_input):
                    return
                midi = router.kb_notes_input[pad]
            elif etype == ETYPE_PATCH:
                midi = ev["pad"]
            else:
                return
            dur_ms = max(50, ev.get("dur", 500))
            router.synth.play(midi, min(1.0, vel / 127.0), maxtime_ms=dur_ms)
            self._preview_midis.append(midi)
            return dur_ms
        elif etype == ETYPE_GRID:
            self._parent._player.play_sound(ev["pad"], velocity=vel)
        return None

    def _play_group_at(self, idx):
        """Joue tous les événements du groupe à l'offset courant."""
        self._stop_preview()
        dur_ms = 500
        for i in self._midi_editor.group_indices(self._events, idx):
            result = self._play_event(self._events[i])
            if result is not None:
                dur_ms = result
        if self._preview_midis:
            self._preview_timer = threading.Timer(
                dur_ms / 1000.0,
                lambda: wx.CallAfter(self._stop_preview)
            )
            self._preview_timer.start()

    def _play_single_at(self, idx):
        """Stop le preview précédent et joue uniquement la note à idx."""
        self._stop_preview()
        dur_ms = self._play_event(self._events[idx])
        if self._preview_midis:
            self._preview_timer = threading.Timer(
                (dur_ms or 500) / 1000.0,
                lambda: wx.CallAfter(self._stop_preview)
            )
            self._preview_timer.start()

    # ------------------------------------------------------------------
    # Annonces de statut
    # ------------------------------------------------------------------

    def _announce_group(self, idx):
        """Annonce ←/→ : position BBT + nom de note (seule) ou nombre (accord)."""
        if not self._events or idx >= len(self._events):
            return
        group = self._midi_editor.group_indices(self._events, idx)
        ev    = self._events[idx]
        bbt   = self._bbt_str(ev["bar"], ev["step"])
        suf   = self._sel_status_suffix()
        if len(group) == 1:
            name = self._event_note_name(ev)
            self._set_status(f"{bbt}  ({name}){suf}")
        else:
            self._set_status(f"{bbt}  {len(group)} notes{suf}")

    def _announce_note(self, idx):
        """Annonce ↑/↓ : nom de note + position BBT."""
        if not self._events or idx >= len(self._events):
            return
        ev   = self._events[idx]
        bbt  = self._bbt_str(ev["bar"], ev["step"])
        name = self._event_note_name(ev)
        suf  = self._sel_status_suffix()
        self._set_status(f"({name})  {bbt}{suf}")

    def _announce_event(self, idx):
        """Annonce générique (clic listbox) : position BBT + nom + vélocité."""
        if not self._events or idx >= len(self._events):
            return
        e = self._events[idx]
        if e["type"] == "note":
            bbt  = self._bbt_str(e["bar"], e["step"])
            name = self._event_note_name(e)
            self._set_status(f"{bbt}  Tr{e['track']+1}  {name}  Vel:{e['vel']}")
        else:
            bbt = self._bbt_str(e["bar"], e["step"])
            self._set_status(f"{bbt}  Tr{e['track']+1}  "
                             f"{e['type'].capitalize()}:{e['value']}")
