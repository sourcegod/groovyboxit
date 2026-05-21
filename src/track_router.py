#python3
"""
    File: src/track_router.py
    Routage piste → slot → SynthEngine et dispatch sonore multi-piste.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""

import threading
from synth_engine import SynthEngine, scale_midi_notes, midi_to_note_name
from rack import InstrumentType


class TrackRouter:
    """
    Gère l'association piste → slot → SynthEngine et le dispatch sonore.

    Responsabilités
    ---------------
    _track_slots  : slot assigné à chaque piste (défaut : slot 0)
    _slot_synths  : un SynthEngine dédié par slot SYNTH commis (Ctrl+T)
    _synth        : moteur de preview interactive (slot courant)
    _kit_synth    : moteur dédié au mode Keyboard/KIT pitché
    kb_notes      : notes MIDI de la gamme courante (accès public)
    kb_last_midi  : dernière note MIDI jouée (accès public)

    Dépendances injectées
    ---------------------
    rack          : Rack — slots d'instruments
    synths_dir    : str  — chemin vers les dossiers de patches SYNTH
    sound_manager : SoundManager — lecture des sons KIT
    status_cb     : callable(str) — DOIT être thread-safe (envelopper wx.CallAfter)
    """

    NUM_TRACKS = 8

    def __init__(self, rack, synths_dir, sound_manager, status_cb):
        self._rack       = rack
        self._synths_dir = synths_dir
        self._snd        = sound_manager
        self._status_cb  = status_cb

        self._track_slots    = [0] * self.NUM_TRACKS
        self._track_mutes    = [False] * self.NUM_TRACKS
        self._track_solos    = [False] * self.NUM_TRACKS
        self._track_volumes  = [100]   * self.NUM_TRACKS  # 0..100
        self._track_pans     = [0]     * self.NUM_TRACKS  # -100..+100
        self._slot_synths    = {}       # {slot_idx: SynthEngine}
        self._synth          = None     # moteur de preview
        self._synth_slot_idx = None     # slot_idx actuellement chargé dans _synth
        self._kit_synth      = None     # moteur Keyboard/KIT
        self._kb_kit_pad     = None     # pad source du Kit pitché courant
        self._kb_scale       = "major"  # pour le message de status
        self._kb_root_midi   = 48       # pour play_kit_pitched / status

        self.kb_notes     = []
        self.kb_last_midi = None

    # ------------------------------------------------------------------
    # Propriétés (accès lecture seule aux moteurs)
    # ------------------------------------------------------------------

    @property
    def synth(self):
        return self._synth

    @property
    def kit_synth(self):
        return self._kit_synth

    # ------------------------------------------------------------------
    # kb_notes / gamme
    # ------------------------------------------------------------------

    def update_kb_notes(self, scale, root_midi):
        """Recalcule kb_notes puis relance le précalcul pour _synth."""
        self._kb_scale     = scale
        self._kb_root_midi = root_midi
        self.kb_notes = scale_midi_notes(scale, root_midi, 16)
        self.precompute_async()

    def precompute_async(self):
        """Précalcule les notes pour _synth en arrière-plan."""
        if self._synth is None or not self._synth.is_loaded():
            return
        notes  = self.kb_notes[:]
        engine = self._synth
        scale  = self._kb_scale
        root   = self._kb_root_midi
        def run():
            engine.precompute(notes)
            self._status_cb(
                f"Keyboard: {scale} @ {midi_to_note_name(root)} — prêt"
            )
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    # Slot / piste
    # ------------------------------------------------------------------

    def slot_for_track(self, track_idx):
        return self._track_slots[track_idx]

    def slot_name(self, track_idx):
        return self._rack.get_slot(self._track_slots[track_idx]).name

    def assign_slot(self, track_idx, slot_idx):
        """Assigne slot_idx à track_idx et ancre le SynthEngine si SYNTH."""
        self._track_slots[track_idx] = slot_idx
        slot = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH and slot_idx not in self._slot_synths:
            if (self._synth and self._synth_slot_idx == slot_idx
                    and self._synth.is_loaded()
                    and self._synth is not self._kit_synth):
                self._slot_synths[slot_idx] = self._synth
            else:
                self._ensure_slot_synth(slot_idx)

    def _ensure_slot_synth(self, slot_idx):
        """Crée et charge un SynthEngine dédié pour slot_idx en arrière-plan."""
        if slot_idx in self._slot_synths:
            return
        slot = self._rack.get_slot(slot_idx)
        patch_name = slot.config.get("patch", "")
        if not patch_name:
            return
        engine = SynthEngine(self._synths_dir)
        self._slot_synths[slot_idx] = engine
        notes = self.kb_notes[:]
        def run():
            try:
                engine.load_patch(patch_name)
                engine.precompute(notes)
                self._status_cb(
                    f"Slot {slot_idx + 1:02d} ({patch_name}) prêt pour lecture"
                )
            except Exception as e:
                self._slot_synths.pop(slot_idx, None)
                self._status_cb(f"Erreur slot {slot_idx + 1:02d}: {e}")
        threading.Thread(target=run, daemon=True).start()

    def load_slot_preview(self, slot_idx):
        """Charge slot_idx dans _synth pour la preview interactive."""
        slot = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.SYNTH:
            return
        # Slot déjà commis → réutiliser son moteur
        if slot_idx in self._slot_synths:
            self._synth = self._slot_synths[slot_idx]
            self._synth_slot_idx = slot_idx
            return
        patch_name = slot.config.get("patch", "")
        if not patch_name:
            return
        # Nouveau moteur de preview (ne pas clobber un moteur commis ni _kit_synth)
        if (self._synth is None
                or self._synth in self._slot_synths.values()
                or self._synth is self._kit_synth):
            self._synth = SynthEngine(self._synths_dir)
        self._synth_slot_idx = slot_idx
        self._status_cb(f"Chargement du patch '{patch_name}'…")
        engine = self._synth
        def run():
            try:
                engine.load_patch(patch_name)
                engine.precompute(self.kb_notes)
                self._status_cb(
                    f"Patch chargé: {patch_name} — {len(engine._cache)} notes"
                )
            except Exception as e:
                self._status_cb(f"Erreur chargement patch: {e}")
        threading.Thread(target=run, daemon=True).start()

    def reset_kit_pad(self):
        """Force le rechargement du sample Kit pitché au prochain play_kit_pitched."""
        self._kb_kit_pad = None

    # ------------------------------------------------------------------
    # Mute / Solo par piste
    # ------------------------------------------------------------------

    def toggle_track_mute(self, track_idx):
        """Bascule le mute de la piste track_idx. Retourne le nouvel état."""
        self._track_mutes[track_idx] = not self._track_mutes[track_idx]
        return self._track_mutes[track_idx]

    def unmute_all_tracks(self):
        """Démute toutes les pistes."""
        self._track_mutes = [False] * self.NUM_TRACKS

    def toggle_track_solo(self, track_idx):
        """Bascule le solo de la piste track_idx. Retourne le nouvel état."""
        self._track_solos[track_idx] = not self._track_solos[track_idx]
        return self._track_solos[track_idx]

    def unsolo_all_tracks(self):
        """Désactive le solo sur toutes les pistes."""
        self._track_solos = [False] * self.NUM_TRACKS

    def _track_is_audible(self, track_idx):
        """Vrai si la piste doit être entendue (solo / mute pris en compte)."""
        if self._track_mutes[track_idx]:
            return False
        if any(self._track_solos):
            return self._track_solos[track_idx]
        return True

    # ------------------------------------------------------------------
    # Volume / Pan par piste
    # ------------------------------------------------------------------

    def get_track_volume(self, track_idx):
        return self._track_volumes[track_idx]

    def set_track_volume(self, track_idx, vol):
        self._track_volumes[track_idx] = max(0, min(100, vol))

    def get_track_pan(self, track_idx):
        return self._track_pans[track_idx]

    def set_track_pan(self, track_idx, pan):
        self._track_pans[track_idx] = max(-100, min(100, pan))

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def synth_ready(self):
        """Vrai si _synth est chargé et prêt à jouer."""
        return self._synth is not None and self._synth.is_loaded()

    def on_play(self, track_idx, pad_idx, vol_factor, pan, duration_ms=100):
        """Dispatch sonore lors de la lecture multi-piste (DrumPlayer callback)."""
        if not self._track_is_audible(track_idx):
            return
        vol_factor = vol_factor * (self._track_volumes[track_idx] / 100.0)
        pan = max(-100, min(100, pan + self._track_pans[track_idx]))
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH:
            engine = self._slot_synths.get(slot_idx)
            if engine and engine.is_loaded() and pad_idx < len(self.kb_notes):
                engine.play(self.kb_notes[pad_idx], vol_factor, pan, duration_ms)
        else:
            self._snd.play_sound(pad_idx, vol_factor, pan)

    def play_kit_pitched(self, note_idx, pad_idx, wav_path, fallback_play_fn):
        """Mode Keyboard/KIT : joue pad_idx pitché sur la gamme courante."""
        if not wav_path:
            return
        if self._kit_synth is None:
            self._kit_synth = SynthEngine(self._synths_dir)

        if self._kb_kit_pad != pad_idx:
            self._kb_kit_pad = pad_idx
            notes      = self.kb_notes[:]
            kit_engine = self._kit_synth
            root_midi  = self._kb_root_midi
            def run():
                kit_engine.load_single_sample(wav_path, root_midi=60)
                kit_engine.precompute(notes)
                self._status_cb(
                    f"Kit pitché: Pad {pad_idx + 1} — {midi_to_note_name(root_midi)}"
                )
            threading.Thread(target=run, daemon=True).start()
            fallback_play_fn(pad_idx)
            return

        if self._kit_synth.is_loaded():
            midi = self.kb_notes[note_idx]
            self._kit_synth.play(midi)
            self.kb_last_midi = midi
        else:
            fallback_play_fn(pad_idx)
