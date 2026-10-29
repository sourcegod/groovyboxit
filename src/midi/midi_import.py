#python3
"""
    File: src/midi/midi_import.py
    Import d'un fichier MIDI standard (.mid) en pattern — Phase 7 étape
    18b1, docs/DESIGN.md § 18a1 (I4, I6 à I10, I12). Inverse de
    midi_export : une piste Groovebox par couple (piste SMF, canal), notes
    en ETYPE_PATCH arrondies au pas, CC / Pitch Bend / Program Change à leur
    position exacte, entête (CC0, CC32, Program Change) à 1.1.1, CC7 / CC10
    du début en volume / pan de piste. Aucune dépendance à wx ni au player :
    le choix du slot, le remplacement du pattern et l'Undo appartiennent à
    l'UI (ui/mw_project.py). Tous les changements de tempo vont dans la
    carte du pattern, durées au tempo local (Phase 7 étape 19b1, § 19a1).
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
import os
from collections import deque

import mido

from pattern import (Pattern, TapeEvent, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM,
                     ETYPE_BEND)

BEATS_PER_BAR = 4       # une mesure = 4 noires (_num_beats n'est pas sauvé, I10)
DEFAULT_BPM   = 120     # tempo MIDI par défaut, sans set_tempo (I10)
BPM_MIN       = 1       # bornes du SpinCtrl de BPM (main_window.py)
BPM_MAX       = 600

# Métas lus par l'import ; les autres sont ignorés et comptés (I9)
_KNOWN_METAS  = ("track_name", "set_tempo", "time_signature", "end_of_track")

# Libellés du compte rendu pour les messages ignorés (I9)
IGNORED_AFTERTOUCH = "aftertouch"
IGNORED_SYSEX      = "SysEx"
IGNORED_META       = "méta"

# Rangs des événements d'entête à 1.1.1, dans l'ordre de rejeu (I7)
_HEADER_ORDER = {("cc", 0): 0, ("cc", 32): 1, ("pgm", None): 2}


class ImportReport:
    """Compte rendu d'un import (I11) : ce qui a été lu, arrondi ou laissé.

    num_tracks      : pistes Groovebox remplies
    num_bars        : mesures du pattern
    num_steps       : pas par mesure retenus (I4)
    bpm             : tempo du pattern
    moved_notes     : notes déplacées par l'arrondi au pas (I4)
    tempo_changes   : changements de tempo gardés dans la carte du pattern
                      (Phase 7 étape 19b1, § 19a1 T6 ; ignorés avant)
    time_signature  : (numérateur, dénominateur) de la première signature
                      si elle n'est pas 4/4, sinon None (I10)
    merged          : vrai si les pistes d'un même canal ont été fusionnées,
                      faute de place pour plus de 16 pistes (I6)
    lost_events     : événements au-delà de 999 mesures (I10)
    ignored         : {libellé: nombre} des messages ignorés (I9)
    track_names     : nom SMF de chaque piste remplie (I5)
    """

    def __init__(self):
        self.num_tracks     = 0
        self.num_bars       = 1
        self.num_steps      = Pattern.VALID_NUM_STEPS[0]
        self.bpm            = DEFAULT_BPM
        self.moved_notes    = 0
        self.tempo_changes  = 0
        self.time_signature = None
        self.merged         = False
        self.lost_events    = 0
        self.ignored        = {}
        self.track_names    = []

    def details(self):
        """Remarques du compte rendu, en français, dans l'ordre d'affichage."""
        out = []
        if self.moved_notes:
            out.append(f"{self.moved_notes} note{'s' if self.moved_notes > 1 else ''}"
                       f" déplacée{'s' if self.moved_notes > 1 else ''}")
        if self.merged:
            out.append("pistes d'un même canal fusionnées")
        if self.tempo_changes:
            out.append(f"{self.tempo_changes} changement{'s' if self.tempo_changes > 1 else ''}"
                       f" de tempo")
        if self.time_signature:
            num, den = self.time_signature
            out.append(f"signature {num}/{den} lue en 4/4")
        if self.lost_events:
            out.append(f"{self.lost_events} événement{'s' if self.lost_events > 1 else ''}"
                       f" au-delà de {Pattern.MAX_BARS} mesures")
        if self.ignored:
            out.append("ignorés : " + ", ".join(f"{n} {label}"
                                                 for label, n in self.ignored.items()))
        return out


class _Group:
    """Une future piste Groovebox : un canal d'une piste SMF (I6).

    notes  : (début, fin, note, vélocité, rang) en ticks
    others : (tick, rang, message) — CC, Program Change, Pitch Bend
    Le rang (indice de piste SMF, ordre dans la piste) garde l'ordre du
    fichier à tick égal, y compris après une fusion."""

    def __init__(self, channel, name):
        self.channel = channel
        self.name    = name
        self.notes   = []
        self.others  = []


def _read_tracks(mid, report):
    """Lit les pistes SMF en ticks absolus.

    Retourne (groupes dans l'ordre du fichier, tempos [(tick, tempo)],
    signatures [(tick, num, den)], fin la plus tardive en ticks, nom de la
    première piste si elle ne porte aucun événement de canal)."""
    groups  = []
    tempos  = []
    sigs    = []
    end     = 0
    conductor_name = None
    for t_idx, track in enumerate(mid.tracks):
        now       = 0
        name      = ""
        by_chan   = {}           # canal → _Group, dans l'ordre d'apparition
        open_notes = {}          # (canal, note) → deque de (début, vélocité, rang)
        for seq, msg in enumerate(track):
            now += msg.time
            rank = (t_idx, seq)
            if msg.is_meta:
                if msg.type == "track_name":
                    name = name or msg.name.strip()
                elif msg.type == "set_tempo":
                    tempos.append((now, msg.tempo))
                elif msg.type == "time_signature":
                    sigs.append((now, msg.numerator, msg.denominator))
                elif msg.type not in _KNOWN_METAS:
                    report.ignored[IGNORED_META] = report.ignored.get(IGNORED_META, 0) + 1
                continue
            if msg.type == "sysex":
                report.ignored[IGNORED_SYSEX] = report.ignored.get(IGNORED_SYSEX, 0) + 1
                continue
            if msg.type in ("aftertouch", "polytouch"):
                report.ignored[IGNORED_AFTERTOUCH] = report.ignored.get(IGNORED_AFTERTOUCH, 0) + 1
                continue
            if not hasattr(msg, "channel"):
                continue            # messages système : jamais dans un SMF valide
            group = by_chan.get(msg.channel)
            if group is None:
                group = by_chan[msg.channel] = _Group(msg.channel, "")
            if msg.type == "note_on" and msg.velocity > 0:
                open_notes.setdefault((msg.channel, msg.note), deque()).append(
                    (now, msg.velocity, rank))
            elif msg.type in ("note_on", "note_off"):
                # note on de vélocité 0 = note off ; premier entré, premier
                # sorti pour une même note (I9)
                pending = open_notes.get((msg.channel, msg.note))
                if pending:
                    start, vel, r = pending.popleft()
                    group.notes.append((start, now, msg.note, vel, r))
                    end = max(end, now)
            elif msg.type in ("control_change", "program_change", "pitchwheel"):
                group.others.append((now, rank, msg))
        # Notes jamais fermées : fermées à la fin de leur piste (I9)
        for (chan, note), pending in open_notes.items():
            for start, vel, r in pending:
                by_chan[chan].notes.append((start, now, note, vel, r))
        end = max(end, now)
        if t_idx == 0 and not by_chan:
            conductor_name = name
        for group in by_chan.values():
            # SMF de type 0 : une seule piste, son nom est celui du morceau
            # (pattern), pas celui de chaque canal
            group.name = "" if mid.type == 0 else name
            if group.notes or group.others:
                groups.append(group)
    if mid.type == 0 and mid.tracks:
        conductor_name = conductor_name or name
    return groups, tempos, sigs, end, conductor_name


def _merge_by_channel(groups):
    """Plus de 16 pistes : une piste par canal (16 au plus), nom de la
    première ; ordre du fichier gardé par les rangs (I6)."""
    merged = {}
    for g in groups:
        target = merged.get(g.channel)
        if target is None:
            merged[g.channel] = _Group(g.channel, g.name)
            target = merged[g.channel]
        target.notes.extend(g.notes)
        target.others.extend(g.others)
    return list(merged.values())


def _choose_num_steps(groups, bar_ticks):
    """Plus petit nombre de pas par mesure qui place toutes les notes
    exactement ; sinon le plus fin (I4)."""
    for num_steps in Pattern.VALID_NUM_STEPS:
        if all((n[0] * num_steps) % bar_ticks == 0 for g in groups for n in g.notes):
            return num_steps
    return Pattern.VALID_NUM_STEPS[-1]


def _header_kind(msg):
    """Clé d'entête (I7, I8) d'un message, ou None."""
    if msg.type == "program_change":
        return ("pgm", None)
    if msg.type == "control_change" and msg.control in (0, 32, 7, 10):
        return ("cc", msg.control)
    return None


def build_pattern_from_midi(mid, *, name=""):
    """Construit un Pattern neuf depuis le mido.MidiFile `mid`.

    name : nom du pattern sans piste conductor nommée (nom du fichier, I2)
    Retourne (pattern, ImportReport). Lève ValueError pour un SMF de type 2.
    """
    if mid.type == 2:
        raise ValueError("fichier MIDI de type 2 non pris en charge")
    report = ImportReport()
    ppq       = mid.ticks_per_beat
    bar_ticks = ppq * BEATS_PER_BAR

    groups, tempos, sigs, end, conductor_name = _read_tracks(mid, report)
    if len(groups) > Pattern.MAX_TRACKS:
        groups = _merge_by_channel(groups)
        report.merged = True

    # Tempo (I10, carte de tempo en Phase 7 étape 19b1, § 19a1 T6) : tempo
    # de départ = dernier tempo au tick 0, sinon 120 (défaut MIDI) jusqu'au
    # premier ; chaque tempo suivant devient un changement de la carte.
    tempos.sort(key=lambda x: x[0])        # tri stable : ordre du fichier à tick égal
    start = [tp for tick, tp in tempos if tick == 0]
    bpm   = max(BPM_MIN, min(BPM_MAX, round(mido.tempo2bpm(
        start[-1] if start else mido.bpm2tempo(DEFAULT_BPM)))))
    if sigs:
        _tick, num, den = min(sigs, key=lambda s: s[0])
        if (num, den) != (BEATS_PER_BAR, 4):
            report.time_signature = (num, den)

    # Longueur (I10) : arrondie à la mesure supérieure, 1..999
    num_bars = max(1, min(Pattern.MAX_BARS, -(-end // bar_ticks)))
    max_tick = num_bars * bar_ticks       # premier tick hors du pattern
    num_steps = _choose_num_steps(groups, bar_ticks)
    total_steps = num_bars * num_steps

    def exact_time(tick):
        q, r = divmod(tick * num_steps, bar_ticks)
        return q if r == 0 else tick * num_steps / bar_ticks

    pat = Pattern()
    pat._name      = conductor_name or name
    pat._bpm       = bpm
    pat._num_steps = num_steps
    pat._num_bars  = num_bars
    pat.set_tempo_changes([(exact_time(tick), mido.tempo2bpm(tp))
                           for tick, tp in tempos if 0 < tick < max_tick])
    report.tempo_changes = len(pat._tempo_changes)
    tmap = pat.tempo_map()

    def ms(start_tick, stop_tick):
        # Durée au tempo en vigueur sur la note (T5)
        secs = tmap.secs_between(start_tick * num_steps / bar_ticks,
                                 stop_tick * num_steps / bar_ticks)
        return max(1, round(secs * 1000.0))

    for t, g in enumerate(groups):
        events = []
        first_note = min((n[0] for n in g.notes), default=None)
        header = {}                 # clé → (tick, rang, message), le dernier l'emporte
        timed  = []                 # (tick, rang, TapeEvent) hors entête
        for tick, rank, msg in sorted(g.others, key=lambda o: (o[0], o[1])):
            if tick >= max_tick:
                report.lost_events += 1
                continue
            kind = _header_kind(msg)
            if kind is not None and (first_note is None or tick <= first_note):
                header[kind] = (tick, rank, msg)
                continue
            time = exact_time(tick)
            if msg.type == "control_change":
                ev = TapeEvent(ETYPE_CC, channel=g.channel, time=time,
                               payload={"cc_num": msg.control, "value": msg.value})
            elif msg.type == "program_change":
                ev = TapeEvent(ETYPE_PGM, channel=g.channel, time=time,
                               payload={"program": msg.program})
            else:
                ev = TapeEvent(ETYPE_BEND, channel=g.channel, time=time,
                               payload={"value": msg.pitch})
            timed.append((tick, rank, ev))

        # Volume et pan de piste (I8), même conversion que TrackRouter.on_cc_tape
        if ("cc", 7) in header:
            v = header.pop(("cc", 7))[2].value
            pat._track_volumes[t] = max(0, min(100, round(v * 100 / 127)))
        if ("cc", 10) in header:
            v = header.pop(("cc", 10))[2].value
            pat._track_pans[t] = max(-100, min(100, round((v - 64) * 100 / 63)))
        # Entête à 1.1.1 (I7) : CC0, CC32, Program Change, sur leur canal
        for kind in sorted(header, key=_HEADER_ORDER.get):
            msg = header[kind][2]
            if kind[0] == "pgm":
                events.append(TapeEvent(ETYPE_PGM, channel=g.channel, time=0,
                                        payload={"program": msg.program}))
            else:
                events.append(TapeEvent(ETYPE_CC, channel=g.channel, time=0,
                                        payload={"cc_num": msg.control, "value": msg.value}))

        # Notes (I4, I9) : début arrondi au pas, durée en ms au tempo local (T5)
        for start, stop, note, vel, rank in g.notes:
            if start >= max_tick:
                report.lost_events += 1
                continue
            exact = start * num_steps / bar_ticks
            step  = min(int(exact + 0.5), total_steps - 1)
            if step != exact:
                report.moved_notes += 1
            timed.append((start, rank, TapeEvent(
                ETYPE_PATCH, dur=ms(start, stop), channel=g.channel, time=step,
                payload={"note": note, "vel": vel})))

        timed.sort(key=lambda x: (x[0], x[1]))
        events.extend(ev for _tick, _rank, ev in timed)
        pat._tape[t] = events
        pat._track_channels[t] = g.channel
        pat._voices[t]["name"] = g.name                     # I5
        report.track_names.append(g.name)

    report.num_tracks = len(groups)
    report.num_bars   = num_bars
    report.num_steps  = num_steps
    report.bpm        = bpm
    return pat, report


def import_pattern(path):
    """Lit le fichier .mid `path` (voir build_pattern_from_midi) ; nom du
    pattern par défaut = nom du fichier sans extension. Retourne
    (pattern, ImportReport). Lecture tolérante : un octet de données hors
    0..127 (fichier abîmé, que mido refuse sinon) est ramené à 127."""
    mid  = mido.MidiFile(path, clip=True)
    name = os.path.splitext(os.path.basename(path))[0]
    return build_pattern_from_midi(mid, name=name)
