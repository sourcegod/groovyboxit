#python3
"""
    File: src/midi/midi_export.py
    Export du pattern courant en fichier MIDI standard (.mid) — Phase 7
    étape 10h1, docs/DESIGN.md § 10a1 (D4, D6, D7, D9). SMF de type 1,
    PPQ 480 : une piste conductor (nom, tempo, signature) puis une piste
    SMF par piste Groovebox non vide, chaque événement sur le canal de sa
    piste (D5). Aucune dépendance à wx ni au player : les états qui ne
    vivent pas dans Pattern sont passés en paramètres.
    Date: Tue, 20/10/2026
    Author: Coolbrother
"""
import mido

from pattern import (ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH,
                     ETYPE_CC, ETYPE_PGM, ETYPE_BEND)

PPQ                = 480
PATCH_DEFAULT_MS   = 500   # comme au rejeu (TrackRouter.on_patch_tape)

# Ordre d'écriture à tick égal (D7) : note-off, PGM, CC, bend, note-on
_ORDER_NOTE_OFF = 0
_ORDER_PGM      = 1
_ORDER_CC       = 2
_ORDER_BEND     = 3
_ORDER_NOTE_ON  = 4


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def build_pattern_midi(pattern, *, name, bpm, track_channels, track_is_synth,
                       track_names, kit_note_base, synth_grid_notes,
                       voice_durations, track_programs=None):
    """Construit le mido.MidiFile du pattern.

    name             : nom de la piste conductor (libellé du pattern)
    bpm              : tempo du player (un temps = 60/bpm, Phase 7 étape 10b1)
    track_channels   : canal 0..15 de chaque piste (TrackRouter, D5)
    track_is_synth   : bool par piste — slot SYNTH (note GRID = gamme)
    track_names      : nom de chaque piste ("" = "Track NN")
    kit_note_base    : snd.kit_base + snd.kit_offset (note GRID d'une piste kit)
    synth_grid_notes : notes de lecture du pad sur une piste SYNTH
                       (TrackRouter._kb_notes_play)
    voice_durations  : durée en ms de chaque pad (GRID sans dur propre)
    track_programs   : programme (0-127) écrit au tick 0 de chaque piste, ou
                       None (slot vide) — Phase 7 étape 10h3 ; None = aucun
    """
    num_steps = pattern._num_steps
    num_beats = pattern._num_beats
    with pattern._lock:
        tape = [list(track_list) for track_list in pattern._tape]

    def tick(time_steps):
        return round(time_steps * PPQ * num_beats / num_steps)

    def ms_ticks(ms):
        return max(1, round(ms / 1000.0 * bpm / 60.0 * PPQ))

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
        ch = track_channels[t]
        timed = []     # (tick, ordre, rang dans _tape, message)
        program = track_programs[t] if track_programs else None
        if program is not None:
            # rang -1 : avant un ETYPE_PGM capturé au tick 0, qui l'emporte
            timed.append((0, _ORDER_PGM, -1, mido.Message(
                "program_change", channel=ch, program=_clamp(program, 0, 127))))
        notes = []     # (début, fin, note, vélocité, rang) avant chevauchements
        for seq, ev in enumerate(events):
            start = tick(ev.time)
            p = ev.payload
            if ev.etype == ETYPE_GRID:
                pad = p.get("pad", 0)
                if track_is_synth[t]:
                    note = synth_grid_notes[pad]
                else:
                    note = kit_note_base + pad
                ms = ev.dur if ev.dur > 0 else voice_durations[pad]
                notes.append((start, start + ms_ticks(ms), note, p.get("vel", 100), seq))
            elif ev.etype == ETYPE_KIT:
                # one-shot (dur toujours 0) : un pas
                notes.append((start, start + max(1, tick(1)), p.get("note", 0),
                              p.get("vel", 100), seq))
            elif ev.etype == ETYPE_PATCH:
                ms = ev.dur if ev.dur > 0 else PATCH_DEFAULT_MS
                notes.append((start, start + ms_ticks(ms), p.get("note", 0),
                              p.get("vel", 100), seq))
            elif ev.etype == ETYPE_PGM:
                timed.append((start, _ORDER_PGM, seq, mido.Message(
                    "program_change", channel=ch,
                    program=_clamp(p.get("program", 0), 0, 127))))
            elif ev.etype == ETYPE_CC:
                timed.append((start, _ORDER_CC, seq, mido.Message(
                    "control_change", channel=ch,
                    control=_clamp(p.get("cc_num", 0), 0, 127),
                    value=_clamp(p.get("value", 0), 0, 127))))
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
