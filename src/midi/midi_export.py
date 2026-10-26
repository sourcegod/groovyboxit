#python3
"""
    File: src/midi/midi_export.py
    Export du pattern courant en fichier MIDI standard (.mid) — Phase 7
    étape 10h1, docs/DESIGN.md § 10a1 (D4, D6, D7, D9). SMF de type 1,
    PPQ 480 : une piste conductor (nom, tempo, signature) puis une piste
    SMF par piste Groovebox non vide, chaque événement sur le canal de sa
    piste (D5). Aucune dépendance à wx ni au player : les états qui ne
    vivent pas dans Pattern sont passés en paramètres. Les notes de kit
    sont converties en notes GM (Phase 7 étape 11f1, docs/DESIGN.md
    § 11a1). Vélocité des cases de grille d'après le gain joué, CC91 et
    CC93 à 0 (Phase 7 étape 12d1, docs/DESIGN.md § 12a1). Transposition et
    gain GM du slot de chaque piste (Phase 7 étape 12f1, § 12a2). Pistes et
    pads muets ou hors solo omis, comme au rejeu (Phase 7 étape 12f2,
    § 12a3). Chaque piste finit pile à la fin du pattern (Phase 7 étape
    12i2, § 12a4).
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import mido

from pattern import (Pattern, ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC, ETYPE_PGM, ETYPE_BEND)

PPQ                = 480
PATCH_DEFAULT_MS   = 500   # comme au rejeu (TrackRouter.on_patch_tape)
CC_REVERB          = 91
CC_CHORUS          = 93
KIT_CHANNEL         = Pattern.KIT_CHANNEL   # canal 10 (0-based 9)
BANK_DRUM_GRID_BASE = 36    # pad i d'une banque au canal 10 = note 36 + i (17d1, D12)

# Ordre d'écriture à tick égal (D7) : note-off, PGM, CC, bend, note-on
_ORDER_NOTE_OFF = 0
_ORDER_PGM      = 1
_ORDER_CC       = 2
_ORDER_BEND     = 3
_ORDER_NOTE_ON  = 4


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def volume_to_cc7(volume):
    """Volume de piste 0..100 → CC#7 0..127, inverse exact de
    TrackRouter.on_cc_tape (round(value * 100 / 127))."""
    return _clamp(round(volume * 127 / 100), 0, 127)


def pan_to_cc10(pan):
    """Pan de piste -100..+100 → CC#10 1..127, 64 au centre, inverse de
    TrackRouter.on_cc_tape (round((value - 64) * 100 / 63)) à ±1 près :
    127 valeurs pour 201 positions."""
    return _clamp(64 + round(pan * 63 / 100), 1, 127)


def apply_gain_db(cc7, db):
    """CC7 atténué de `db` dB (≤ 0) pour un lecteur GM, dont le volume
    suit 40·log10(CC7/127) : CC7 · 10^(db/40), borné à 0..127.
    Phase 7 étape 12f1, docs/DESIGN.md § 12a2 D5."""
    return _clamp(round(cc7 * 10 ** (db / 40.0)), 0, 127)


def grid_velocity(vel, pad_volume=100):
    """Vélocité MIDI d'une case de grille : le facteur du rejeu
    min(1, vel/100 · volume du pad/100) (DrumPlayer._dispatch_event),
    ramené à 1..127. Avec la courbe GM de l'appli, un lecteur GM rend alors
    le même gain. Phase 7 étape 12d1, docs/DESIGN.md § 12a1 D2."""
    factor = min(1.0, vel / 100.0 * pad_volume / 100.0)
    return _clamp(round(127 * factor), 1, 127)


def build_pattern_midi(pattern, *, name, bpm, track_channels, track_is_synth,
                       track_names, kit_pad_notes, synth_grid_notes,
                       voice_durations, track_programs=None,
                       track_volumes=None, track_pans=None,
                       kit_gm_map=None, unmapped=None, pad_volumes=None,
                       track_transposes=None, track_gain_db=None,
                       track_audible=None, pad_audible=None, track_banks=None):
    """Construit le mido.MidiFile du pattern.

    name             : nom de la piste conductor (libellé du pattern)
    bpm              : tempo du player (un temps = 60/bpm, Phase 7 étape 10b1)
    track_channels   : canal 0..15 de chaque piste (TrackRouter, D5)
    track_is_synth   : bool par piste — slot SYNTH (note GRID = gamme ; sans
                       SYNTH, les notes PATCH, muettes au rejeu, sont omises)
    track_names      : nom de chaque piste ("" = "Track NN")
    kit_pad_notes    : note de kit du son de chaque pad (snd.pad_notes), note
                       GRID d'une piste kit avant conversion GM (11a1 D1)
    synth_grid_notes : notes de lecture du pad sur une piste SYNTH
                       (TrackRouter._kb_notes_play)
    voice_durations  : durée en ms de chaque pad (GRID sans dur propre)
    track_programs   : programme (0-127) écrit au tick 0 de chaque piste, ou
                       None (slot vide) — Phase 7 étape 10h3 ; None = aucun
    track_volumes    : volume 0..100 de chaque piste → CC#7 au tick 0
    track_pans       : pan -100..+100 de chaque piste → CC#10 au tick 0
                       (Phase 7 étape 10h5 ; None = rien d'écrit)
    kit_gm_map       : {note de kit: note GM} (snd.gm_note_map), appliqué aux
                       GRID d'une piste kit et aux KIT ; None = notes de kit
                       écrites telles quelles (11a1 D2, D5)
    unmapped         : set rempli des notes de kit écrites sans conversion,
                       faute de correspondance GM (11a1 D4) ; None = ignoré
    pad_volumes      : volume 0..100 de chaque pad (VoiceManager), compté
                       dans la vélocité des cases de grille (12a1 D2) ;
                       None = 100
    track_transposes : demi-tons ajoutés aux notes PATCH et GRID d'une piste
                       synthé (slot.gm_transpose(), 12a2 D4) ; None = 0
    track_gain_db    : gain en dB (≤ 0) appliqué à tout CC7 de la piste
                       (slot.gm_gain_db(), 12a2 D5) ; None = 0
    track_audible    : bool par piste (TrackRouter._track_is_audible) ; une
                       piste muette ou hors solo est omise (12a3 D7) ;
                       None = toutes
    pad_audible      : bool par pad (VoiceManager.is_audible) ; les cases
                       de grille d'un pad muet ou hors solo sont omises ;
                       None = tous
    track_banks      : par piste, None ou (msb, lsb, drums) d'un slot Banque
                       (Phase 7 étape 17d1, D12, D18) : CC0 et CC32 avant le
                       Program Change au tick 0 (sauf batterie) ; cases de
                       grille en 36 + pad au canal 10, sinon gamme ; notes
                       KIT telles quelles, PATCH gardées. None = aucune
    Chaque piste reçoit CC91 et CC93 à 0 au tick 0 : pas de reverb ni de
    chorus, comme dans l'appli (12a1 D3).
    """
    num_steps = pattern._num_steps
    num_beats = pattern._num_beats
    with pattern._lock:
        tape = [list(track_list) for track_list in pattern._tape]

    def tick(time_steps):
        return round(time_steps * PPQ * num_beats / num_steps)

    def ms_ticks(ms):
        return max(1, round(ms / 1000.0 * bpm / 60.0 * PPQ))

    def kit_note(note):
        # Note de kit → note GM ; sans correspondance, gardée et signalée (D4)
        if kit_gm_map is None:
            return note
        gm = kit_gm_map.get(note)
        if gm is None:
            if unmapped is not None:
                unmapped.add(note)
            return note
        return gm

    end_tick = tick(pattern._num_bars * num_steps)

    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name=name, time=0))
    conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=num_beats,
                                      denominator=4, time=0))
    conductor.append(mido.MetaMessage("end_of_track", time=end_tick))
    mid.tracks.append(conductor)

    for t, events in enumerate(tape):
        if not events:
            continue
        if track_audible and not track_audible[t]:
            continue      # muette ou hors solo au rejeu (12a3 D7)
        ch = track_channels[t]
        transpose = track_transposes[t] if track_transposes else 0
        gain_db   = track_gain_db[t] if track_gain_db else 0
        timed = []     # (tick, ordre, rang dans _tape, message)
        bank    = track_banks[t] if track_banks else None
        plays_notes = track_is_synth[t] or bank is not None
        program = track_programs[t] if track_programs else None
        if bank is not None and not bank[2]:
            # Bank Select avant le programme (rangs -3, -2 < -1), D18
            timed.append((0, _ORDER_PGM, -3, mido.Message(
                "control_change", channel=ch, control=0, value=_clamp(bank[0], 0, 127))))
            timed.append((0, _ORDER_PGM, -2, mido.Message(
                "control_change", channel=ch, control=32, value=_clamp(bank[1], 0, 127))))
        if program is not None:
            # rang -1 : avant un ETYPE_PGM capturé au tick 0, qui l'emporte
            timed.append((0, _ORDER_PGM, -1, mido.Message(
                "program_change", channel=ch, program=_clamp(program, 0, 127))))
        # Volume, pan, puis reverb et chorus à 0 (12a1 D3) au tick 0, après
        # le programme et avant les CC de _tape au même tick (rangs
        # négatifs), qui l'emportent donc.
        if track_volumes:
            timed.append((0, _ORDER_CC, -4, mido.Message(
                "control_change", channel=ch, control=7,
                value=apply_gain_db(volume_to_cc7(track_volumes[t]), gain_db))))
        if track_pans:
            timed.append((0, _ORDER_CC, -3, mido.Message(
                "control_change", channel=ch, control=10,
                value=pan_to_cc10(track_pans[t]))))
        timed.append((0, _ORDER_CC, -2, mido.Message(
            "control_change", channel=ch, control=CC_REVERB, value=0)))
        timed.append((0, _ORDER_CC, -1, mido.Message(
            "control_change", channel=ch, control=CC_CHORUS, value=0)))
        notes = []     # (début, fin, note, vélocité, rang) avant chevauchements
        for seq, ev in enumerate(events):
            start = tick(ev.time)
            if start >= end_tick:
                continue   # hors du pattern : jamais rejoué (12a4 D8)
            p = ev.payload
            if ev.etype == ETYPE_GRID:
                pad = p.get("pad", 0)
                if pad_audible and not pad_audible[pad]:
                    continue  # pad muet ou hors solo au rejeu (12a3 D7)
                if bank is not None and ch == KIT_CHANNEL:
                    note = BANK_DRUM_GRID_BASE + pad          # D12
                elif plays_notes:
                    note = synth_grid_notes[pad] + transpose
                else:
                    note = kit_note(kit_pad_notes[pad])
                ms = ev.dur if ev.dur > 0 else voice_durations[pad]
                vel = grid_velocity(p.get("vel", 100),
                                    pad_volumes[pad] if pad_volumes else 100)
                notes.append((start, start + ms_ticks(ms), note, vel, seq))
            elif ev.etype == ETYPE_KIT:
                # one-shot (dur toujours 0) : un pas
                note = p.get("note", 0)
                notes.append((start, start + max(1, tick(1)),
                              note if bank is not None else kit_note(note),
                              p.get("vel", 100), seq))
            elif ev.etype == ETYPE_PATCH:
                # Muette au rejeu sur une piste sans slot SYNTH
                # (TrackRouter.on_patch_tape) : non exportée (Phase 7 étape 10h5)
                if not plays_notes:
                    continue
                ms = ev.dur if ev.dur > 0 else PATCH_DEFAULT_MS
                notes.append((start, start + ms_ticks(ms), p.get("note", 0) + transpose,
                              p.get("vel", 100), seq))
            elif ev.etype == ETYPE_PGM:
                timed.append((start, _ORDER_PGM, seq, mido.Message(
                    "program_change", channel=ch,
                    program=_clamp(p.get("program", 0), 0, 127))))
            elif ev.etype == ETYPE_CC:
                control = _clamp(p.get("cc_num", 0), 0, 127)
                value   = _clamp(p.get("value", 0), 0, 127)
                if control == 7:
                    value = apply_gain_db(value, gain_db)
                timed.append((start, _ORDER_CC, seq, mido.Message(
                    "control_change", channel=ch, control=control, value=value)))
            elif ev.etype == ETYPE_BEND:
                timed.append((start, _ORDER_BEND, seq, mido.Message(
                    "pitchwheel", channel=ch,
                    pitch=_clamp(p.get("value", 0), -8192, 8191))))

        # Chevauchements (D6) : une même note rejouée avant son note-off voit
        # le note-off de la précédente avancé à son note-on ; un doublon au
        # même tick est ignoré.
        by_note = {}
        for n in sorted(notes, key=lambda n: (n[0], n[4])):
            by_note.setdefault(n[2], []).append(n)
        for same in by_note.values():
            kept = []
            for n in same:
                if kept and kept[-1][0] == n[0]:
                    continue
                if kept and kept[-1][1] > n[0]:
                    kept[-1] = (kept[-1][0], n[0]) + kept[-1][2:]
                kept.append(n)
            for start, stop, note, vel, seq in kept:
                # Fin du fichier pile à la fin du pattern (12a4 D8) : note-off
                # ramené à la fin.
                stop = min(stop, end_tick)
                note = _clamp(note, 0, 127)
                timed.append((start, _ORDER_NOTE_ON, seq, mido.Message(
                    "note_on", channel=ch, note=note, velocity=_clamp(vel, 1, 127))))
                timed.append((stop, _ORDER_NOTE_OFF, seq, mido.Message(
                    "note_off", channel=ch, note=note, velocity=0)))

        timed.sort(key=lambda e: (e[0], e[1], e[2]))
        track = mido.MidiTrack()
        label = track_names[t] or f"Track {t + 1:02d}"
        track.append(mido.MetaMessage("track_name", name=label, time=0))
        now = 0
        for at, _order, _seq, msg in timed:
            track.append(msg.copy(time=at - now))
            now = at
        track.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - now)))
        mid.tracks.append(track)
    return mid


def export_pattern(path, pattern, **kwargs):
    """Écrit le pattern dans le fichier .mid `path` (voir build_pattern_midi).
    Retourne le mido.MidiFile écrit."""
    mid = build_pattern_midi(pattern, **kwargs)
    mid.save(path)
    return mid
