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
from pattern import Pattern, ETYPE_CC, ETYPE_PGM
from bend_log import bend_log
from midi.midi_export import volume_to_cc7, pan_to_cc10


class BankPreview:
    """Jeu direct sur un slot Banque (Phase 7 étape 17d1, § 17a1 « Envoi aux
    canaux ») : même interface que le SynthEngine d'aperçu (TrackRouter.synth),
    les notes allant au moteur de banque sur le canal de la piste courante.
    Le pan est celui du canal (CC10), pas celui de la note."""

    def __init__(self, router):
        self._router    = router
        self.slot_idx   = None
        self.pitch_bend = 0           # -8192..+8191, comme SynthEngine
        self.sustain    = False

    def _channel(self):
        return self._router.track_channel_now(self._router.cur_track())

    def is_loaded(self):
        return self._router.bank_slot_ready(self.slot_idx)

    def has_full_range(self):
        return True

    def play(self, midi_note, volume_factor=1.0, pan=0, maxtime_ms=500):
        if not self.is_loaded():
            return
        vel = max(1, min(127, round(127 * min(1.0, volume_factor))))
        self._router.bank_note(self._channel(), midi_note, vel, maxtime_ms)

    def stop(self, midi_note):
        engine = self._router.bank_engine
        if engine is not None:
            engine.note_off(self._channel(), midi_note)

    def apply_pitch_bend(self):
        engine = self._router.bank_engine
        if engine is not None:
            engine.pitch_bend(self._channel(), self.pitch_bend)

    @property
    def pitch_bend_semitones(self):
        return self.pitch_bend / 8192.0 * 2.0   # plage GM par défaut ±2

    def set_mod_wheel(self, value):
        engine = self._router.bank_engine
        if engine is not None:
            engine.cc(self._channel(), 1, value)

    def release_sustain(self):
        pass                                     # CC64 envoyé par set_sustain

    def stop_all_voices(self):
        engine = self._router.bank_engine
        if engine is not None:
            engine.all_notes_off()

    def reset_all_controls(self):
        self.pitch_bend = 0
        self.sustain    = False


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

    NUM_TRACKS      = 16   # = Pattern.DEFAULT_NUM_TRACKS (Phase 7 étape 10d1)
    KB_NUMPAD_NOTES = 16   # notes de gamme pour les Numpads (8 touches × 2 banques)
    KB_MIDI_NOTES   = 25   # notes de gamme pour le clavier MIDI
    KB_SYNTH_MIN    = 36   # C2 — borne basse du pré-calcul chromatique
    KB_SYNTH_MAX    = 96   # C7 — borne haute du pré-calcul chromatique (61 notes)

    def __init__(self, rack, synths_dir, sound_manager, status_cb, driver=None,
                 bank_engine=None, cur_track=None):
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
        self._track_channels = [Pattern.default_channel(t)    # 0..15 (export MIDI)
                                for t in range(self.NUM_TRACKS)]
        # Canal courant de chaque piste sur slot Banque : celui de son dernier
        # Program Change (17f1, docs/DESIGN.md § 17e3 O3), sinon _track_channels.
        self._track_cur_channels = list(self._track_channels)
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

        self._load_threads   = []   # threads de chargement/precompute en cours

        # Slot Banque (Phase 7 étape 17d1) : moteur partagé (None sans
        # libfluidsynth : banques muettes), piste courante pour le jeu
        # direct, instrument envoyé à chaque canal (emplacement, banque,
        # programme) pour ne renvoyer select que s'il change.
        self.bank_engine    = bank_engine
        self._cur_track_cb  = cur_track or (lambda: 0)
        self._chan_sel      = [None] * 16
        # Instrument de chaque canal (§ 17e3 O1) : dernier programme, CC0 et
        # CC32 reçus ou rejoués ; programme 0 banque 0 par défaut.
        self._chan_prog     = [0] * 16
        self._chan_msb      = [0] * 16
        self._chan_lsb      = [0] * 16
        self._preset_names  = {}        # {emplacement: {(banque, programme): nom}}
        self.master_pan     = 0
        self._bank_preview  = BankPreview(self)

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
        if slot.type == InstrumentType.BANK:
            self.sync_banks()
            return
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
        t = threading.Thread(target=run, daemon=True)
        self._load_threads.append(t)
        t.start()

    def wait_loaded(self):
        """Attend la fin de tous les threads de chargement/precompute en cours."""
        for t in self._load_threads:
            t.join()
        self._load_threads.clear()

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
        if slot.type == InstrumentType.BANK:          # jeu direct sur la banque (17d1)
            self.sync_bank_files()
            self._bank_preview.slot_idx = slot_idx
            self._synth          = self._bank_preview
            self._synth_slot_idx = slot_idx
            return
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
                or self._synth is self._kit_synth
                or self._synth is self._bank_preview):
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
        t = threading.Thread(target=run, daemon=True)
        self._load_threads.append(t)
        t.start()

    def reset_kit_pad(self):
        """Force le rechargement du sample Kit pitché au prochain play_kit_pitched."""
        self._kb_kit_pad = None

    # ------------------------------------------------------------------
    # Slot Banque (Phase 7 étape 17d1, docs/DESIGN.md § 17a1 D4, D8-D13)
    # ------------------------------------------------------------------

    DRUM_GRID_BASE = 36    # pad i d'une piste au canal 10 = note GM 36 + i (D12)

    def cur_track(self):
        return self._cur_track_cb()

    def _bank_slot_of(self, track_idx):
        """Slot Banque de la piste, ou None."""
        slot = self._rack.get_slot(self._track_slots[track_idx])
        return slot if slot.type == InstrumentType.BANK else None

    def bank_slot_ready(self, slot_idx):
        """Vrai si le slot est une banque dont l'emplacement est chargé."""
        if self.bank_engine is None or slot_idx is None:
            return False
        slot = self._rack.get_slot(slot_idx)
        return slot.type == InstrumentType.BANK \
            and self.bank_engine.loaded_path(slot.bank_slot()) is not None

    DRUM_BANK = 128        # banque des batteries d'une soundfont GM (§ 17e2 R3)

    def track_channel_now(self, track_idx):
        """Canal courant de la piste : celui de son dernier Program Change
        sur slot Banque (§ 17e3 O3), sinon son canal."""
        if self._bank_slot_of(track_idx) is not None:
            return self._track_cur_channels[track_idx]
        return self._track_channels[track_idx]

    def channel_instrument(self, channel):
        """(programme, MSB, LSB) courants du canal (§ 17e3 O1)."""
        return self._chan_prog[channel], self._chan_msb[channel], self._chan_lsb[channel]

    def _chan_bank(self, channel):
        """Banque de la soundfont jouée par le canal : 128 au canal 10
        (batterie, R3), sinon celle de son MSB / LSB selon le mode Bank Select."""
        if channel == Pattern.KIT_CHANNEL:
            return self.DRUM_BANK
        return self.bank_engine.bank_number(self._chan_msb[channel], self._chan_lsb[channel])

    def _bank_key(self, channel, slot):
        """(emplacement du slot, banque, programme) à sélectionner sur le canal."""
        return slot.bank_slot(), self._chan_bank(channel), self._chan_prog[channel]

    def _select_channel(self, channel, slot, track_idx):
        """Envoie au moteur l'instrument du canal s'il a changé."""
        key = self._bank_key(channel, slot)
        if self._chan_sel[channel] == key:
            return
        if not self.bank_engine.select(channel, *key):
            self._status_cb(f"Piste {track_idx + 1}: banque {key[0] + 1} vide ou "
                            f"preset {key[1]}:{key[2]} introuvable")
        self._chan_sel[channel] = key

    def bank_preset_name(self, track_idx):
        """Nom du preset que joue une piste sur slot Banque : l'instrument de
        son canal courant (§ 17e3 R7, O1). None si la piste n'est pas sur une
        banque ou si son emplacement est vide ; « (preset absent) » si la
        banque ne le contient pas."""
        slot = self._bank_slot_of(track_idx)
        if slot is None or self.bank_engine is None \
                or self.bank_engine.loaded_path(slot.bank_slot()) is None:
            return None
        _, bank, program = self._bank_key(self._track_cur_channels[track_idx], slot)
        return self._preset_names_of(slot.bank_slot()).get((bank, program), "(preset absent)")

    def _preset_names_of(self, bank_slot):
        """{(banque, programme): nom} de l'emplacement, lu une fois."""
        names = self._preset_names.get(bank_slot)
        if names is None:
            names = {(b, p): n for b, p, n in self.bank_engine.presets(bank_slot)}
            self._preset_names[bank_slot] = names
        return names

    def program_names(self, slot_idx, channel, msb, lsb):
        """Noms des 128 programmes de la banque que choisiraient MSB / LSB
        sur ce canal (128 au canal 10), dans le fichier du slot Banque ;
        None pour un numéro absent (propriétés de piste, Alt+Entrée, Phase 7 étape 17h1, § 17e3 O5)."""
        slot = self._rack.get_slot(slot_idx)
        if self.bank_engine is None or slot.type != InstrumentType.BANK \
                or self.bank_engine.loaded_path(slot.bank_slot()) is None:
            return [None] * 128
        bank = self.DRUM_BANK if channel == Pattern.KIT_CHANNEL \
            else self.bank_engine.bank_number(msb, lsb)
        names = self._preset_names_of(slot.bank_slot())
        return [names.get((bank, p)) for p in range(128)]

    def bank_note(self, channel, note, velocity, duration_ms):
        """Note du moteur de banque ; coupée après duration_ms (> 0), tenue
        sinon (jeu direct : stop au relâchement)."""
        engine = self.bank_engine
        if engine is None:
            return
        note = max(0, min(127, note))
        engine.note_on(channel, note, velocity)
        if duration_ms > 0:
            threading.Timer(duration_ms / 1000.0, engine.note_off,
                            [channel, note]).start()

    def _bank_grid_note(self, track_idx, pad_idx):
        """Note d'un pad sur une piste Banque (D12) : canal 10 → 36 + pad,
        sinon la gamme du clavier (comme un synthé). None hors gamme."""
        if self._track_cur_channels[track_idx] == Pattern.KIT_CHANNEL:
            return self.DRUM_GRID_BASE + pad_idx
        if pad_idx < len(self._kb_notes_play):
            return self._kb_notes_play[pad_idx]
        return None

    def input_note(self, pad_idx):
        """Note jouée par un pad en direct : batterie sur une banque au canal
        10 → 36 + pad, sinon la gamme d'entrée (kb_notes_input)."""
        if self._synth is self._bank_preview \
                and self.track_channel_now(self.cur_track()) == Pattern.KIT_CHANNEL:
            return self.DRUM_GRID_BASE + pad_idx
        return self.kb_notes_input[pad_idx]

    def _send_bank_mix(self, track_idx):
        """CC7 (volume de piste) et CC10 (pan de piste + pan global) au canal
        courant de la piste (D11, D13)."""
        ch = self._track_cur_channels[track_idx]
        pan = max(-100, min(100, self._track_pans[track_idx] + self.master_pan))
        self.bank_engine.cc(ch, 7, volume_to_cc7(self._track_volumes[track_idx]))
        self.bank_engine.cc(ch, 10, pan_to_cc10(pan))

    def sync_bank_files(self):
        """Charge dans le moteur les fichiers des emplacements du Rack qui
        ont changé (FluidSynth lit la soundfont à la demande : FluidR3 se
        charge en 0,1 s, sans fil)."""
        engine = self.bank_engine
        if engine is None:
            return
        for i, path in enumerate(self._rack.bank_files):
            if engine.loaded_path(i) == path:
                continue
            self._chan_sel = [None] * len(self._chan_sel)
            self._preset_names.pop(i, None)
            if path is None:
                engine.unload(i)
            elif not engine.load(i, path):
                engine.unload(i)
                self._status_cb(f"Banque {i + 1}: fichier refusé ou introuvable — {path}")

    def sync_banks(self, force=False):
        """Emplacements, puis instrument de chaque canal joué par une piste
        sur slot Banque (§ 17e3 O1), CC7 et CC10 de ces pistes. force :
        resélectionne même un instrument déjà envoyé. Deux pistes au même
        canal sur des emplacements différents : avertissement, la dernière
        l'emporte (D10)."""
        engine = self.bank_engine
        if engine is None:
            return
        self.sync_bank_files()
        if force:
            self._chan_sel = [None] * len(self._chan_sel)
        owners = {}
        for t in range(self.NUM_TRACKS):
            slot = self._bank_slot_of(t)
            if slot is None:
                continue
            ch = self._track_cur_channels[t]
            prev = owners.get(ch)
            if prev is not None and prev[1].bank_slot() != slot.bank_slot():
                self._status_cb(f"Canal {ch + 1}: pistes {prev[0] + 1} et {t + 1} "
                                f"sur des banques différentes — la piste {t + 1} l'emporte")
            owners[ch] = (t, slot)
        for ch, (t, slot) in owners.items():
            self._select_channel(ch, slot, t)
        for t in range(self.NUM_TRACKS):
            if self._bank_slot_of(t) is not None:
                self._send_bank_mix(t)

    def chase(self, tape, pos=0.0):
        """Poursuite (§ 17e3 O4) : remet les canaux à l'état GM par défaut,
        puis rejoue, toutes pistes sur slot Banque confondues, les CC0, CC32
        et Program Change de tape (listes d'événements par piste) jusqu'à
        pos (en pas) compris, dans l'ordre des temps puis des pistes ;
        chaque piste reprend le canal de son dernier Program Change (O3).
        Enfin, instruments et mixage envoyés au moteur."""
        self._track_cur_channels = list(self._track_channels)
        self._chan_prog = [0] * 16
        self._chan_msb  = [0] * 16
        self._chan_lsb  = [0] * 16
        found = []
        for t, events in enumerate(tape[:self.NUM_TRACKS]):
            if self._bank_slot_of(t) is None:
                continue
            for seq, ev in enumerate(events):
                if ev.time > pos:
                    continue
                if ev.etype == ETYPE_PGM or (ev.etype == ETYPE_CC
                                             and ev.payload.get("cc_num") in (0, 32)):
                    found.append((ev.time, t, seq, ev))
        for _, t, _, ev in sorted(found, key=lambda f: f[:3]):
            ch = max(0, min(15, ev.channel))
            if ev.etype == ETYPE_PGM:
                self._chan_prog[ch] = max(0, min(127, ev.payload.get("program", 0)))
                self._track_cur_channels[t] = ch
            elif ev.payload.get("cc_num") == 0:
                self._chan_msb[ch] = max(0, min(127, ev.payload.get("value", 0)))
            else:
                self._chan_lsb[ch] = max(0, min(127, ev.payload.get("value", 0)))
        self.sync_banks(force=True)

    def set_master_pan(self, pan):
        """Pan global, ajouté au CC10 des canaux de banque (D13)."""
        self.master_pan = max(-100, min(100, int(pan)))
        if self.bank_engine is not None:
            for t in range(self.NUM_TRACKS):
                if self._bank_slot_of(t) is not None:
                    self._send_bank_mix(t)

    def program_change(self, track_idx, program, channel=None):
        """Program Change d'une piste (rejeu de _tape et réception live).
        Piste sur slot Banque (§ 17e3 O1, O3) : l'instrument du canal change
        (channel, sinon le canal courant de la piste) et la piste passe sur
        ce canal. Sinon le pont provisoire assign_slot(program % 16).
        Retourne True si la piste est sur une banque."""
        slot = self._bank_slot_of(track_idx)
        if slot is None:
            self.assign_slot(track_idx, program % 16)
            return False
        ch = self._track_cur_channels[track_idx] if channel is None \
            else max(0, min(15, channel))
        self._chan_prog[ch] = max(0, min(127, program))
        moved = self._track_cur_channels[track_idx] != ch
        self._track_cur_channels[track_idx] = ch
        if self.bank_engine is not None:
            self._chan_sel[ch] = None             # Program Change : toujours renvoyé
            self._select_channel(ch, slot, track_idx)
            if moved:
                self._send_bank_mix(track_idx)
        return True

    def bank_select(self, track_idx, cc_num, value, channel=None):
        """CC0 (MSB) ou CC32 (LSB) d'une piste sur slot Banque : banque du
        canal (channel, sinon le canal courant de la piste), appliquée au
        prochain Program Change, comme en MIDI."""
        ch = self._track_cur_channels[track_idx] if channel is None \
            else max(0, min(15, channel))
        value = max(0, min(127, value))
        if cc_num == 0:
            self._chan_msb[ch] = value
        else:
            self._chan_lsb[ch] = value
        if self.bank_engine is not None:
            self.bank_engine.cc(ch, cc_num, value)

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
        if self.bank_engine is not None and self._bank_slot_of(track_idx) is not None:
            self._send_bank_mix(track_idx)

    def get_track_pan(self, track_idx):
        return self._track_pans[track_idx]

    def set_track_pan(self, track_idx, pan):
        self._track_pans[track_idx] = max(-100, min(100, pan))
        if self.bank_engine is not None and self._bank_slot_of(track_idx) is not None:
            self._send_bank_mix(track_idx)

    # ------------------------------------------------------------------
    # Canal MIDI par piste (Phase 7 étape 10f1, docs/DESIGN.md § 10a1 D5)
    # ------------------------------------------------------------------

    def get_track_channel(self, track_idx):
        return self._track_channels[track_idx]

    def set_track_channel(self, track_idx, channel):
        """Canal de la piste, qui devient aussi son canal courant. Sur un
        slot Banque, la piste entend aussitôt l'instrument de ce canal
        (§ 17e3 O5, choix B : le canal impose son instrument)."""
        self._track_channels[track_idx] = max(0, min(15, channel))
        self._track_cur_channels[track_idx] = self._track_channels[track_idx]
        if self._bank_slot_of(track_idx) is not None:
            self.sync_banks()                  # instrument et mixage sur le nouveau canal

    def channel_after_slot(self, track_idx, slot_idx, channel):
        """Canal d'une piste à qui l'utilisateur assigne slot_idx : un kit la
        met sur le canal 10 ; une banque garde le canal, 10 compris (la
        batterie, § 17e2 R3) ; un autre slot la ramène à son canal par
        défaut si elle était sur 10 ; sinon le canal ne change pas."""
        slot = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.KIT:
            return Pattern.KIT_CHANNEL
        if slot.type == InstrumentType.BANK:
            return channel
        if channel == Pattern.KIT_CHANNEL:
            return Pattern.default_channel(track_idx)
        return channel

    def assign_slot_by_user(self, track_idx, slot_idx):
        """assign_slot + règle du canal (kit → 10). Réservé aux choix de
        l'utilisateur : le pont Program Change et le chargement d'un projet
        appellent assign_slot seul, sans toucher au canal. Le canal est
        posé d'abord : une banque est synchronisée sur son canal final
        (17d2)."""
        self._track_channels[track_idx] = self.channel_after_slot(
            track_idx, slot_idx, self._track_channels[track_idx])
        self._track_cur_channels[track_idx] = self._track_channels[track_idx]
        self.assign_slot(track_idx, slot_idx)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    def synth_ready(self):
        """Vrai si _synth est chargé et prêt à jouer."""
        return self._synth is not None and self._synth.is_loaded()

    def stop_all_synth_voices(self):
        """Coupe toutes les voix actives de tous les slots synthé (All Notes Off)."""
        if self.bank_engine is not None:
            self.bank_engine.all_notes_off()
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
        if self.bank_engine is not None:
            self.bank_engine.all_sounds_off()

    def reset_all_controls(self):
        """Remet Pitch Bend et Mod Wheel à zéro sur tous les synths (CC#121) ;
        les canaux de banque gardent leur volume et leur pan de piste."""
        if self.bank_engine is not None:
            self.bank_engine.reset_controllers()
            for t in range(self.NUM_TRACKS):
                if self._bank_slot_of(t) is not None:
                    self._send_bank_mix(t)
        seen = set()
        for eng in self._slot_synths.values():
            if eng is not None and id(eng) not in seen:
                eng.reset_all_controls()
                seen.add(id(eng))
        if self._synth is not None and id(self._synth) not in seen:
            self._synth.reset_all_controls()

    def set_sustain(self, on: bool):
        """Active/désactive la pédale sustain sur tous les synths (CC#64)."""
        if self.bank_engine is not None:
            for ch in range(len(self._chan_sel)):
                self.bank_engine.cc(ch, 64, 127 if on else 0)
        seen = set()
        for eng in self._slot_synths.values():
            if eng is not None and id(eng) not in seen:
                eng.sustain = on
                if not on:
                    eng.release_sustain()
                seen.add(id(eng))
        if self._synth is not None and id(self._synth) not in seen:
            self._synth.sustain = on
            if not on:
                self._synth.release_sustain()

    def panic(self):
        """Coupure d'urgence : All Sounds Off + Reset All Controllers."""
        self.stop_all_sounds()
        self.reset_all_controls()

    def on_play(self, track_idx, pad_idx, vol_factor, pan, duration_ms=500):
        """Dispatch sonore lors de la lecture multi-piste (DrumPlayer callback)."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.BANK:
            # D11 : vélocité de l'export (vel × volume du pad), volume et pan
            # de piste au canal (CC7, CC10) ; le pan du pad est ignoré.
            note = self._bank_grid_note(track_idx, pad_idx)
            if note is not None:
                vel = max(1, min(127, round(127 * min(1.0, vol_factor))))
                self.bank_note(self._track_cur_channels[track_idx], note, vel,
                               duration_ms if duration_ms > 0 else 500)
            return
        vol_factor = vol_factor * (self._track_volumes[track_idx] / 100.0)
        pan = max(-100, min(100, pan + self._track_pans[track_idx]))
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
        if self._bank_slot_of(track_idx) is not None:          # 17d1 : note telle quelle
            self.bank_note(self._track_cur_channels[track_idx], midi_note, velocity,
                           duration_ms if duration_ms > 0 else 500)
            return
        vol = min(1.0, self._track_volumes[track_idx] / 100.0 * velocity / 127.0)
        self._snd.play_note(midi_note, vol)

    def on_patch_tape(self, track_idx, midi_note, velocity, duration_ms=0):
        """Lecture d'un événement patch_tape : note MIDI brute pour un synth.
        Joue avec l'état de Pitch Bend courant du moteur (posé par
        on_bend_tape) — plus de bend propre à la note depuis la Phase 7
        étape 7f1."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.BANK:                   # 17d1
            self.bank_note(self._track_cur_channels[track_idx], midi_note, velocity,
                           duration_ms if duration_ms > 0 else 500)
            return
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            vol = min(1.0, self._track_volumes[track_idx] / 100.0 * velocity / 127.0)
            pan = self._track_pans[track_idx]
            dur = duration_ms if duration_ms > 0 else 500
            bend_log(f"PLAY note={midi_note} bend={engine.pitch_bend} "
                      f"({engine.pitch_bend_semitones:+.3f}st) engine_id={id(engine)}")
            engine.play(midi_note, vol, pan, dur)
            threading.Timer(dur / 1000.0, engine.stop, [midi_note]).start()

    def on_bend_tape(self, track_idx, bend_value):
        """Applique un point d'automation pitch bend au moteur du slot de la piste."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.BANK:                   # 17d1 : état du canal
            if self.bank_engine is not None:
                self.bank_engine.pitch_bend(self._track_cur_channels[track_idx], bend_value)
            return
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            engine.pitch_bend = bend_value
            engine.apply_pitch_bend()
            bend_log(f"BEND_AUTO track={track_idx} bend={bend_value} "
                      f"({engine.pitch_bend_semitones:+.3f}st)")

    def on_mod_tape(self, track_idx, mod_value):
        """Applique un point d'automation mod wheel au moteur du slot de la piste."""
        if not self._track_is_audible(track_idx):
            return
        slot_idx = self._track_slots[track_idx]
        slot     = self._rack.get_slot(slot_idx)
        if slot.type == InstrumentType.BANK:                   # 17d1
            if self.bank_engine is not None:
                self.bank_engine.cc(self._track_cur_channels[track_idx], 1, mod_value)
            return
        if slot.type != InstrumentType.SYNTH:
            return
        engine = self._slot_synths.get(slot_idx)
        if engine and engine.is_loaded():
            engine.set_mod_wheel(mod_value)

    def on_cc_tape(self, track_idx, cc_num, value, channel=None):
        """Rejoue un CC générique capturé pendant la lecture (Phase 7 étape
        4g, voir docs/DESIGN.md § Phase 7 étape 4a, décision 2) — même
        effet que la réception live (MidiHandler.on_cc). Effets globaux
        (64/120/121/123) indépendants de track_idx ; volume/pan (7/10) et
        mod wheel (1, délégué à on_mod_tape) appliqués à track_idx, la
        piste d'origine de l'événement (pas de notion de focus UI à la
        lecture). channel : canal de l'événement, pour CC0 / CC32 d'une
        piste Banque (§ 17e3 O3) ; None = canal courant de la piste."""
        if cc_num == 120:                         # CC#120 : All Sounds Off
            self.stop_all_sounds()
            return
        if cc_num == 121:                          # CC#121 : Reset All Controllers
            self.reset_all_controls()
            return
        if cc_num == 123:                          # CC#123 : All Notes Off
            self.stop_all_synth_voices()
            return
        if cc_num == 64:                           # CC#64 : Sustain Pedal
            self.set_sustain(value >= 64)
            return
        if not self._track_is_audible(track_idx):
            return
        if cc_num not in (7, 10) and self._bank_slot_of(track_idx) is not None:
            # Piste Banque (17d1, D18) : CC0 / CC32 changent la banque de
            # leur canal au prochain programme (17f1, § 17e3 O3) ; les autres
            # CC vont au canal courant de la piste, tels quels.
            if cc_num in (0, 32):
                self.bank_select(track_idx, cc_num, value, channel)
            elif self.bank_engine is not None:
                self.bank_engine.cc(self._track_cur_channels[track_idx], cc_num, value)
            return
        if cc_num == 1:                            # CC#1 : Modulation Wheel
            self.on_mod_tape(track_idx, value)
        elif cc_num == 7:                          # CC#7 : Volume standard
            self.set_track_volume(track_idx, round(value * 100 / 127))
        elif cc_num == 10:                         # CC#10 : Pan standard
            self.set_track_pan(track_idx, round((value - 64) * 100 / 63))

    def on_program_change_tape(self, track_idx, program, channel=None):
        """Rejoue un Program Change capturé pendant la lecture (Phase 7
        étape 4g) : même effet provisoire que la réception live
        (MidiHandler.on_program_change) — assign_slot sur le Rack — mais
        ciblant track_idx, la piste d'origine de l'événement, plutôt que
        la piste courante. Piste sur slot Banque : instrument du canal de
        l'événement, où la piste passe (17f1, § 17e3 O1, O3)."""
        self.program_change(track_idx, program, channel)

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
