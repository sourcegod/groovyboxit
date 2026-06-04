#python3
"""
    File: src/track_router.py
    Routage piste → slot → SynthEngine et dispatch sonore multi-piste.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""

import threading
import os, time as _time
from synth_engine import SynthEngine, scale_midi_notes, midi_to_note_name
from rack import InstrumentType

_BEND_LOG = os.environ.get("GROOVY_BEND_LOG") == "1"
_BEND_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "bend_log.txt")

def _bend_log(msg):
    if not _BEND_LOG:
        return
    ts = _time.strftime("%H:%M:%S")
    with open(_BEND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


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

    NUM_TRACKS      = 8
    KB_NUMPAD_NOTES = 16   # notes de gamme pour les Numpads (8 touches × 2 banques)
    KB_MIDI_NOTES   = 25   # notes de gamme pour le clavier MIDI
    KB_SYNTH_MIN    = 36   # C2 — borne basse du pré-calcul chromatique
    KB_SYNTH_MAX    = 96   # C7 — borne haute du pré-calcul chromatique (61 notes)

    def __init__(self, rack, synths_dir, sound_manager, status_cb, driver=None):
        self._rack       = rack
        self._synths_dir = synths_dir
        self._snd        = sound_manager
        self._status_cb  = status_cb
        self._driver     = driver   # propagé aux SynthEngine

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
        self._kb_scale       = "chromatic"  # pour le message de status
        self._kb_root_midi   = 48       # pour play_kit_pitched / status

        self.kb_notes        = []   # notes d'entrée MIDI (clavier externe)
        self.kb_notes_input  = []   # notes d'entrée Numpad (transposables)
        self._kb_notes_play  = []   # notes de lecture (gamme du pattern courant — figée)
        self.kb_last_midi    = None

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

    def set_playback_kb(self, scale, root_midi):
        """Fixe les notes de LECTURE depuis la gamme stockée dans le pattern courant.

        Appelé lors du chargement/changement de pattern.
        Indépendant des changements de gamme dans l'UI (update_kb_notes).
        """
        self._kb_notes_play = scale_midi_notes(scale, root_midi, self.KB_NUMPAD_NOTES)

    def update_kb_notes(self, scale, root_midi):
        """Recalcule kb_notes/kb_notes_input (entrées clavier et numpad uniquement).

        Ne relance pas le pré-calcul : la plage C2-C7 est déjà en cache depuis
        le chargement du patch. Le changement de gamme n'affecte pas la lecture
        des données déjà enregistrées dans les patterns.
        """
        self._kb_scale      = scale
        self._kb_root_midi  = root_midi
        self.kb_notes       = scale_midi_notes(scale, root_midi, self.KB_MIDI_NOTES)
        self.kb_notes_input = scale_midi_notes(scale, root_midi, self.KB_NUMPAD_NOTES)

    def update_input_kb(self, root_midi):
        """Transpose le clavier Numpad d'entrée sans affecter kb_notes (lecture)."""
        self.kb_notes_input = scale_midi_notes(self._kb_scale, root_midi, self.KB_NUMPAD_NOTES)

    def precompute_async(self):
        """Précalcule la plage C2-C7 (61 notes) pour _synth en arrière-plan.

        Skip si le patch couvre déjà ≥88 notes (pas de pitch shift nécessaire).
        """
        if self._synth is None or not self._synth.is_loaded():
            return
        if self._synth.has_full_range():
            self._status_cb("Keyboard: patch complet (≥88 notes) — prêt")
            return
        notes  = list(range(self.KB_SYNTH_MIN, self.KB_SYNTH_MAX + 1))
        engine = self._synth
        def run():
            engine.precompute(notes)
            self._status_cb("Keyboard: C2–C7 pré-calculé — prêt")
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
        engine = SynthEngine(self._synths_dir, driver=self._driver)
        self._slot_synths[slot_idx] = engine
        def run():
            try:
                engine.load_patch(patch_name)
                if not engine.has_full_range():
                    notes = list(range(self.KB_SYNTH_MIN, self.KB_SYNTH_MAX + 1))
                    engine.precompute(notes)
                self._status_cb(
                    f"Slot {slot_idx + 1:02d} ({patch_name}) prêt pour lecture"
                )
            except Exception as e:
                self._slot_synths.pop(slot_idx, None)
                self._status_cb(f"Erreur slot {slot_idx + 1:02d}: {e}")
        threading.Thread(target=run, daemon=True).start()

    def clear_slot_synths(self):
        """Invalide tous les moteurs SYNTH en cache (force rechargement au prochain assign)."""
        self._slot_synths.clear()
        if self._synth is not self._kit_synth:
            self._synth          = None
            self._synth_slot_idx = None

    def reload_slot(self, slot_idx):
        """Invalide l'ancien moteur du slot et recharge le nouveau patch.
        Toutes les pistes assignées à ce slot bénéficieront du nouveau moteur."""
        self._slot_synths.pop(slot_idx, None)
        if self._synth_slot_idx == slot_idx:
            self._synth = None
            self._synth_slot_idx = None
        slot = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.SYNTH:
            return
        self._ensure_slot_synth(slot_idx)
        self._synth          = self._slot_synths.get(slot_idx)
        self._synth_slot_idx = slot_idx

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
            self._synth = SynthEngine(self._synths_dir, driver=self._driver)
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

    def stop_all_synth_voices(self):
        """Coupe toutes les voix actives de tous les slots synthé (All Notes Off)."""
        seen = set()
        for eng in self._slot_synths.values():
            if eng is not None and id(eng) not in seen:
                eng.stop_all_voices()
                seen.add(id(eng))
        if self._synth is not None and id(self._synth) not in seen:
            self._synth.stop_all_voices()

    def stop_all_sounds(self):
        """Coupe voix synthé + sons one-shot drums (All Sounds Off, CC#120)."""
        self.stop_all_synth_voices()
        self._snd.stop_all()

    def panic(self):
        """Coupure d'urgence : All Notes Off + All Sounds Off."""
        self.stop_all_sounds()

    def on_play(self, track_idx, pad_idx, vol_factor, pan, duration_ms=500):
        """Dispatch sonore lors de la lecture multi-piste (DrumPlayer callback)."""
        if not self._track_is_audible(track_idx):
            return
        vol_factor = vol_factor * (self._track_volumes[track_idx] / 100.0)
        pan = max(-100, min(100, pan + self._track_pans[track_idx]))
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.SYNTH:
            engine = self._slot_synths.get(slot_idx)
            if engine and engine.is_loaded() and pad_idx < len(self._kb_notes_play):
                midi = self._kb_notes_play[pad_idx]
                dur  = duration_ms if duration_ms > 0 else 500
                engine.play(midi, vol_factor, pan, dur)
                threading.Timer(dur / 1000.0, engine.stop, [midi]).start()
        else:
            self._snd.play_sound(pad_idx, vol_factor, pan)

    def on_kit_tape(self, track_idx, midi_note, velocity, duration_ms=0):
        """Lecture d'un événement kit_tape : note MIDI brute, indépendante du kit_offset."""
        if not self._track_is_audible(track_idx):
            return
        vol = min(1.0, self._track_volumes[track_idx] / 100.0 * velocity / 127.0)
        self._snd.play_note(midi_note, vol)

    def on_patch_tape(self, track_idx, midi_note, velocity, duration_ms=0, bend=0):
        """Lecture d'un événement patch_tape : note MIDI brute pour un synth.
        bend : valeur pitch bend enregistrée (-8192..+8191) — appliquée via phase_incr."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            vol = min(1.0, self._track_volumes[track_idx] / 100.0 * velocity / 127.0)
            pan = self._track_pans[track_idx]
            dur = duration_ms if duration_ms > 0 else 500
            old_bend          = engine.pitch_bend
            engine.pitch_bend = bend
            pi = 2.0 ** (engine.pitch_bend_semitones / 12.0)
            _bend_log(f"PLAY note={midi_note} bend={bend} "
                      f"({engine.pitch_bend_semitones:+.3f}st) phase_incr={pi:.5f} "
                      f"old_bend={old_bend} engine_id={id(engine)}")
            engine.play(midi_note, vol, pan, dur)
            engine.pitch_bend = old_bend
            threading.Timer(dur / 1000.0, engine.stop, [midi_note]).start()

    def on_bend_tape(self, track_idx, bend_value):
        """Applique un point d'automation pitch bend au moteur du slot de la piste."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            engine.pitch_bend = bend_value
            engine.apply_pitch_bend()
            _bend_log(f"BEND_AUTO track={track_idx} bend={bend_value} "
                      f"({engine.pitch_bend_semitones:+.3f}st)")

    def on_mod_tape(self, track_idx, mod_value):
        """Applique un point d'automation mod wheel au moteur du slot de la piste."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            engine.set_mod_wheel(mod_value)

    def play_kit_pitched(self, note_idx, pad_idx, wav_path, fallback_play_fn):
        """Mode Keyboard/KIT : joue pad_idx pitché sur la gamme courante."""
        if not wav_path:
            return
        if self._kit_synth is None:
            self._kit_synth = SynthEngine(self._synths_dir, driver=self._driver)

        if self._kb_kit_pad != pad_idx:
            self._kb_kit_pad = pad_idx
            notes      = self.kb_notes_input[:]
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
            midi = self.kb_notes_input[note_idx]
            self._kit_synth.play(midi)
            self.kb_last_midi = midi
        else:
            fallback_play_fn(pad_idx)
