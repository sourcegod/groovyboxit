#python3
"""
    File: src/midi/track_midi_out.py
    Mixin TrackRouter — sortie MIDI externe des pistes (Phase 8 étape 12b1,
    docs/DESIGN.md § Phase 8 étape 12a T1, T8, T10).
    Une piste dont la sortie MIDI est un port externe ouvert envoie ses
    événements à ce port, sur son canal courant, traduits comme à l'export
    (grille d'un kit → note GM du son du pad ; grille d'une banque au canal
    10 → 36 + pad ; synthé → gamme du clavier ; KIT / PATCH, CC, Pitch Bend,
    Program Change tels quels), et son son interne se tait. Port absent ou
    sortie « Interne » ("") : son interne (repli, T10).
    - _track_midi_outs : nom du port de chaque piste ("" = interne), posé
      depuis le pattern comme les canaux ;
    - midi_out_lookup(nom) → port ouvert (objet avec send_message) ou None,
      fourni par la fenêtre ; None (rendu WAV, tests) = toujours interne ;
    - Stop, Mute / Solo, changement de son, Panic : All Notes Off (CC123)
      sur les canaux des ports utilisés.
    Date: Thu, 12/11/2026
    Author: Coolbrother
"""
from midi.midi_export import volume_to_cc7, pan_to_cc10

NOTE_ON, NOTE_OFF, CC, PGM, BEND = 0x90, 0x80, 0xB0, 0xC0, 0xE0
CC_VOLUME, CC_PAN, CC_ALL_SOUND_OFF, CC_RESET, CC_ALL_NOTES_OFF = 7, 10, 120, 121, 123


class TrackMidiOutMixin:

    def _init_midi_out(self):
        self._track_midi_outs = [""] * self.NUM_TRACKS
        self._track_midi_ins  = [""] * self.NUM_TRACKS   # filtre du jeu en direct (12d1)
        self.midi_out_lookup  = None
        self._ext_used        = set()        # (nom du port, canal) qui ont reçu des notes

    # ------------------------------------------------------------------
    # Port de la piste
    # ------------------------------------------------------------------

    def track_midi_out(self, track_idx):
        """Nom de la sortie MIDI de la piste ("" = interne)."""
        outs = getattr(self, "_track_midi_outs", None)
        return outs[track_idx] if outs and 0 <= track_idx < len(outs) else ""

    def _ext_port(self, track_idx):
        """(nom, port) de la sortie externe ouverte de la piste, ou None
        (sortie interne, port absent ou pas de fournisseur : son interne)."""
        name = self.track_midi_out(track_idx)
        lookup = getattr(self, "midi_out_lookup", None)
        if not name or lookup is None:
            return None
        port = lookup(name)
        return (name, port) if port is not None else None

    def missing_midi_outs(self):
        """[(piste, nom)] des pistes dont la sortie externe n'est pas ouverte
        (repli sur le son interne, T10)."""
        lookup = getattr(self, "midi_out_lookup", None)
        if lookup is None:
            return []
        return [(t, name) for t, name in enumerate(getattr(self, "_track_midi_outs", []))
                if name and lookup(name) is None]

    # ------------------------------------------------------------------
    # Envoi
    # ------------------------------------------------------------------

    @staticmethod
    def _send(port, message):
        try:
            port.send_message(message)
        except Exception:                     # port débranché en cours de route
            pass

    def _ext_channel(self, track_idx):
        return max(0, min(15, self._track_cur_channels[track_idx]))

    def _ext_note(self, track_idx, ext, note, velocity, duration_ms):
        name, port = ext
        ch = self._ext_channel(track_idx)
        note = max(0, min(127, int(note)))
        velocity = max(1, min(127, int(velocity)))
        self._send(port, [NOTE_ON | ch, note, velocity])
        self._ext_used.add((name, ch))
        dur = duration_ms if duration_ms > 0 else 500
        self._schedule(dur, self._send, port, [NOTE_OFF | ch, note, 0])

    def _ext_cc(self, track_idx, ext, cc_num, value, channel=None):
        ch = self._ext_channel(track_idx) if channel is None else max(0, min(15, channel))
        self._send(ext[1], [CC | ch, max(0, min(127, cc_num)), max(0, min(127, int(value)))])

    def _ext_kit_note(self, note):
        """Note de kit → note GM (gm_note_map du kit chargé), comme l'export."""
        gm_map = getattr(self._snd, "gm_note_map", None) or {}
        return gm_map.get(note, note)

    def _ext_grid_note(self, track_idx, pad_idx):
        """Note d'un pad de grille, comme l'export : banque ou SFZ au canal 10
        → 36 + pad ; slot qui joue des notes → gamme du clavier ; kit → note
        GM du son du pad. None hors gamme."""
        _slot_idx, slot = self._eff_slot(track_idx)
        if slot.type in self.CHAN_TYPES:
            return self._bank_grid_note(track_idx, pad_idx)
        if slot.plays_notes:
            return self._kb_notes_play[pad_idx] if pad_idx < len(self._kb_notes_play) else None
        pad_notes = getattr(self._snd, "pad_notes", None) or []
        if pad_idx < len(pad_notes):
            return self._ext_kit_note(pad_notes[pad_idx])
        return None

    # ------------------------------------------------------------------
    # Événements de lecture (appelés en tête des on_*_tape du routeur)
    # ------------------------------------------------------------------

    def ext_grid(self, track_idx, pad_idx, vol_factor, duration_ms):
        """True si la note de grille est partie vers un port externe."""
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        note = self._ext_grid_note(track_idx, pad_idx)
        if note is not None:
            vel = round(127 * min(1.0, vol_factor))
            self._ext_note(track_idx, ext, note, vel, duration_ms)
        return True

    def ext_kit(self, track_idx, midi_note, velocity, duration_ms):
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        _slot_idx, slot = self._eff_slot(track_idx)
        note = midi_note if slot.type in self.CHAN_TYPES else self._ext_kit_note(midi_note)
        self._ext_note(track_idx, ext, note, velocity, duration_ms)
        return True

    def ext_patch(self, track_idx, midi_note, velocity, duration_ms):
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        self._ext_note(track_idx, ext, midi_note, velocity, duration_ms)
        return True

    def ext_cc(self, track_idx, cc_num, value, channel=None):
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        self._ext_cc(track_idx, ext, cc_num, value, channel)
        return True

    def ext_bend(self, track_idx, bend_value):
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        v = max(0, min(16383, int(bend_value) + 8192))
        self._send(ext[1], [BEND | self._ext_channel(track_idx), v & 0x7F, v >> 7])
        return True

    def ext_program(self, track_idx, program, channel=None):
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        ch = self._ext_channel(track_idx) if channel is None else max(0, min(15, channel))
        self._send(ext[1], [PGM | ch, max(0, min(127, int(program)))])
        return True

    def ext_mix(self, track_idx):
        """Volume et pan de la piste en CC7 / CC10 sur son port (départ de la
        lecture, réglage changé)."""
        ext = self._ext_port(track_idx)
        if ext is None:
            return False
        self._ext_cc(track_idx, ext, CC_VOLUME, volume_to_cc7(self._track_volumes[track_idx]))
        self._ext_cc(track_idx, ext, CC_PAN, pan_to_cc10(self._track_pans[track_idx]))
        return True

    def ext_chase(self):
        """Départ de la lecture (chase) : banque, programme, volume et pan de
        chaque piste externe, à l'état de la poursuite (canal courant, CC0,
        CC32, programme)."""
        for t in range(self.NUM_TRACKS):
            ext = self._ext_port(t)
            if ext is None:
                continue
            ch = self._ext_channel(t)
            self._ext_cc(t, ext, 0, self._chan_msb[ch])
            self._ext_cc(t, ext, 32, self._chan_lsb[ch])
            self.ext_program(t, self._chan_prog[ch])
            self.ext_mix(t)

    # ------------------------------------------------------------------
    # Coupures
    # ------------------------------------------------------------------

    def ext_notes_off(self, track_idx=None, panic=False):
        """All Notes Off (CC123) sur les canaux des ports utilisés — d'une
        piste, ou de toutes ; Panic ajoute All Sound Off et Reset All
        Controllers."""
        lookup = getattr(self, "midi_out_lookup", None)
        if lookup is None:
            return
        if track_idx is None:
            targets = set(self._ext_used)
        else:
            ext = self._ext_port(track_idx)
            targets = {(ext[0], self._ext_channel(track_idx))} if ext else set()
        for name, ch in targets:
            port = lookup(name)
            if port is None:
                continue
            self._send(port, [CC | ch, CC_ALL_NOTES_OFF, 0])
            if panic:
                self._send(port, [CC | ch, CC_ALL_SOUND_OFF, 0])
                self._send(port, [CC | ch, CC_RESET, 0])
        if track_idx is None:
            self._ext_used.clear()
