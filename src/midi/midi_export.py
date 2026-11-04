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
    12i2, § 12a4). Carte de tempo : un set_tempo par changement, durées
    converties au tempo en vigueur sur chaque note (Phase 7 étape 19b1,
    § 19a1 T5, T6).
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

# Ordre d'écriture à tick égal (D7) : note-off, Bank Select (CC0 / CC32,
# avant le programme qu'il choisit : 17f1, § 17e3 O8), PGM, autres CC,
# bend, note-on
_ORDER_NOTE_OFF = 0
_ORDER_BANK     = 1
_ORDER_PGM      = 2
_ORDER_CC       = 3
_ORDER_BEND     = 4
_ORDER_NOTE_ON  = 5


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
                       track_audible=None, pad_audible=None, track_is_bank=None,
                       track_is_kit=None, rack_mode=False):
    """Construit le mido.MidiFile du pattern.

    name             : nom de la piste conductor (libellé du pattern)
    bpm              : tempo de départ, celui du player (un temps = 60/bpm,
                       Phase 7 étape 10b1) ; les changements viennent de
                       pattern._tempo_changes (Phase 7 étape 19b1)
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
    track_is_bank    : bool par piste — slot à canaux, Banque ou Synth SFZ
                       (Phase 7 étape 17f1, docs/DESIGN.md § 17e3 O3, O8 ;
                       Phase 8 étape 7d1, § 7a2 Z12) : banque et programme
                       viennent des CC0 / CC32 / Program Change de _tape,
                       écrits sur leur propre canal ; chaque Program Change
                       fait passer la piste sur son canal, où vont les
                       événements suivants ; cases de grille en 36 + pad au
                       canal 10, sinon gamme ; notes KIT telles quelles,
                       PATCH gardées. Un Synth SFZ a en plus le programme
                       GM de son slot (track_programs). None = aucune
    track_is_kit     : bool par piste — slot Kit ; ses notes PATCH sont
                       exportées telles quelles (notes GM, jouées par le kit
                       depuis la Phase 8 étape 5b1, docs/DESIGN.md § 5a M11).
                       None = aucune
    rack_mode        : pattern en mode Rack 16 canaux (Phase 8 étape 5f1,
                       § 5a M18) : le canal de chaque piste suit ses Program
                       Change, quel que soit son slot, et Program Change, CC0
                       et CC32 s'écrivent sur leur propre canal, comme pour
                       une banque ; les autres listes décrivent le slot que
                       joue chaque piste à 1.1.1
    Chaque piste reçoit CC91 et CC93 à 0 au tick 0 : pas de reverb ni de
    chorus, comme dans l'appli (12a1 D3).
    Un pattern est un song d'un seul segment, sans marqueur
    (build_song_midi, Phase 8 étape 2d1, docs/DESIGN.md § 2a E7) : le
    fichier est le même, à l'octet.
    """
    params = dict(bpm=bpm, track_channels=track_channels, track_is_synth=track_is_synth,
                  track_names=track_names, kit_pad_notes=kit_pad_notes,
                  synth_grid_notes=synth_grid_notes, voice_durations=voice_durations,
                  track_programs=track_programs, track_volumes=track_volumes,
                  track_pans=track_pans, kit_gm_map=kit_gm_map, pad_volumes=pad_volumes,
                  track_transposes=track_transposes, track_gain_db=track_gain_db,
                  track_audible=track_audible, pad_audible=pad_audible,
                  track_is_bank=track_is_bank, track_is_kit=track_is_kit,
                  rack_mode=rack_mode)
    return build_song_midi([SongPart(pattern, name, params)], name=name,
                           unmapped=unmapped, markers=False)


# ---------------------------------------------------------------------------
# Song : suite de segments — Phase 8 étape 2d1, docs/DESIGN.md § 2a (E7-E10)
# ---------------------------------------------------------------------------

class SongPart:
    """Un pattern du song pour l'export MIDI : pattern (copie figée), label
    (marqueur) et params, les arguments de build_pattern_midi propres à ce
    pattern (bpm, track_channels, track_names… ; voir sa docstring), calculés
    d'après l'état du pattern (slots, mix, voix, gamme)."""

    __slots__ = ("pattern", "label", "params")

    def __init__(self, pattern, label, params):
        self.pattern = pattern
        self.label   = label
        self.params  = params


class _Segment:
    """Un SongPart placé dans le temps du song : tick et seconde de début,
    conversions pas ↔ ticks et pas ↔ secondes."""

    def __init__(self, part, start_tick, start_secs):
        p = part.pattern
        self.part       = part
        self.pattern    = p
        self.params     = part.params
        self.num_steps  = p._num_steps
        self.quarters   = p.quarters_per_bar()          # signature (Phase 7 étape 20b1, S9)
        self.tmap       = p.tempo_map(start_bpm=part.params["bpm"])
        self.total      = p._num_bars * p._num_steps
        self.start_tick = start_tick
        self.start_secs = start_secs
        self.length     = self.tick(self.total)          # ticks du segment
        self.end_tick   = start_tick + self.length
        self.end_secs   = start_secs + self.tmap.secs(self.total)
        with p._lock:
            self.tape = [list(track_list) for track_list in p._tape]

    def tick(self, time_steps):
        """Ticks depuis le début du segment."""
        return round(time_steps * PPQ * self.quarters / self.num_steps)


def _place(parts):
    segments, at, secs = [], 0, 0.0
    for part in parts:
        seg = _Segment(part, at, secs)
        segments.append(seg)
        at, secs = seg.end_tick, seg.end_secs
    return segments


def _conductor(segments, name, markers):
    """Piste conductor (E8) : nom ; à chaque segment, marqueur (song),
    tempo s'il change, signature si elle change, puis ses changements de
    tempo."""
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name=name, time=0))
    now = 0
    tempo = signature = None

    def put(msg, at):
        nonlocal now
        conductor.append(msg.copy(time=at - now))
        now = at

    for seg in segments:
        p = seg.pattern
        if markers:
            put(mido.MetaMessage("marker", text=seg.part.label), seg.start_tick)
        if seg.tmap.start_bpm != tempo:
            put(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(seg.tmap.start_bpm)),
                seg.start_tick)
        if (p._num_beats, p._denumerator) != signature:
            put(mido.MetaMessage("time_signature", numerator=p._num_beats,
                                 denominator=p._denumerator), seg.start_tick)
        tempo, signature = seg.tmap.start_bpm, (p._num_beats, p._denumerator)
        for pos, change_bpm in seg.tmap.changes:        # carte de tempo (T6)
            at = seg.tick(pos)
            if at >= seg.length:
                break
            put(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(change_bpm)),
                seg.start_tick + at)
            tempo = change_bpm
    song_end = segments[-1].end_tick if segments else 0
    conductor.append(mido.MetaMessage("end_of_track", time=song_end - now))
    return conductor


def build_song_midi(parts, *, name, unmapped=None, markers=True):
    """Construit le mido.MidiFile d'un song, suite de SongPart joués une fois
    chacun, en entier (E5, E7). name : nom de la piste conductor ;
    unmapped : comme pour build_pattern_midi ; markers : un marqueur au
    libellé de chaque pattern (E8).

    Chaque pattern garde son tempo, sa carte de tempo et sa signature (E6).
    Une piste SMF par piste Groovebox non vide et audible dans au moins un
    pattern ; dans un pattern où elle est vide, muette ou hors solo, rien
    n'est écrit (E10). Au premier pattern où elle joue sur un canal, son
    état complet (programme, CC7, CC10, CC91, CC93) ; ensuite, seulement ce
    qui diffère de l'état laissé sur ce canal par les patterns précédents,
    événements de _tape compris (E9). Une note déborde sur le pattern
    suivant, à son tempo ; elle n'est coupée qu'à la fin du song (E1,
    E10)."""
    segments = _place(parts)
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    mid.tracks.append(_conductor(segments, name, markers))
    if not segments:
        return mid
    song_end = segments[-1].end_tick

    def song_tick_at(secs):
        # Seconde du song → tick du song, au tempo du segment où elle tombe
        # (le dernier au-delà de la fin)
        for seg in segments:
            if secs < seg.end_secs or seg is segments[-1]:
                local = seg.tmap.steps(secs - seg.start_secs)
                return seg.start_tick + seg.tick(local)
        return song_end

    num_tracks = max(len(seg.tape) for seg in segments)
    for t in range(num_tracks):
        plays = []
        for k, seg in enumerate(segments):
            audible = seg.params.get("track_audible")
            if t < len(seg.tape) and seg.tape[t] and not (audible and not audible[t]):
                plays.append(k)      # vide, muette ou hors solo : omise ici (12a3 D7)
        if not plays:
            continue
        timed = []     # (tick, ordre, (segment, rang dans _tape), message)
        notes = []     # (début, fin, note, vélocité, (segment, rang), canal)
        chstate = {}   # canal → {"program", 7, 10, 91, 93} laissés par les patterns précédents
        for k in plays:
            seg_timed = _segment_track(segments[k], k, t, notes, chstate, song_tick_at,
                                       unmapped)
            timed.extend(seg_timed)

        # Chevauchements (D6) : une même note rejouée avant son note-off voit
        # le note-off de la précédente avancé à son note-on ; un doublon au
        # même tick est ignoré.
        by_note = {}
        for n in sorted(notes, key=lambda n: (n[0], n[4])):
            by_note.setdefault((n[5], n[2]), []).append(n)     # (canal, note)
        for same in by_note.values():
            kept = []
            for n in same:
                if kept and kept[-1][0] == n[0]:
                    continue
                if kept and kept[-1][1] > n[0]:
                    kept[-1] = (kept[-1][0], n[0]) + kept[-1][2:]
                kept.append(n)
            for start, stop, note, vel, seq, note_ch in kept:
                # Fin du fichier pile à la fin du song (12a4 D8, E10) :
                # note-off ramené à la fin.
                stop = min(stop, song_end)
                note = _clamp(note, 0, 127)
                timed.append((start, _ORDER_NOTE_ON, seq, mido.Message(
                    "note_on", channel=note_ch, note=note, velocity=_clamp(vel, 1, 127))))
                timed.append((stop, _ORDER_NOTE_OFF, seq, mido.Message(
                    "note_off", channel=note_ch, note=note, velocity=0)))

        timed.sort(key=lambda e: (e[0], e[1], e[2]))
        track = mido.MidiTrack()
        names = segments[plays[0]].params["track_names"]
        label = names[t] or f"Track {t + 1:02d}"
        track.append(mido.MetaMessage("track_name", name=label, time=0))
        now = 0
        for at, _order, _seq, msg in timed:
            track.append(msg.copy(time=at - now))
            now = at
        track.append(mido.MetaMessage("end_of_track", time=max(0, song_end - now)))
        mid.tracks.append(track)
    return mid


def _segment_track(seg, k, t, notes, chstate, song_tick_at, unmapped):
    """Événements de la piste t dans le segment k : état de départ (E9),
    puis _tape ; les notes vont dans notes (chevauchements traités sur tout
    le song), le reste est rendu en liste (tick, ordre, (k, rang), message).
    chstate est mis à jour avec l'état laissé par ce segment."""
    prm = seg.params
    events = seg.tape[t]
    track_channels   = prm["track_channels"]
    track_is_bank    = prm.get("track_is_bank")
    track_is_synth   = prm["track_is_synth"]
    track_programs   = prm.get("track_programs")
    track_volumes    = prm.get("track_volumes")
    track_pans       = prm.get("track_pans")
    track_transposes = prm.get("track_transposes")
    track_gain_db    = prm.get("track_gain_db")
    pad_audible      = prm.get("pad_audible")
    pad_volumes      = prm.get("pad_volumes")
    kit_gm_map       = prm.get("kit_gm_map")
    kit_pad_notes    = prm["kit_pad_notes"]
    synth_grid_notes = prm["synth_grid_notes"]
    voice_durations  = prm["voice_durations"]
    base = seg.start_tick

    def tick(time_steps):
        return base + seg.tick(time_steps)

    def end_tick(time_steps, ms):
        # Fin d'une note de ms millisecondes partant de time_steps, au tempo
        # en vigueur sur la note (T5), et au-delà du segment au tempo du
        # suivant (E10) ; au moins un tick
        secs = seg.start_secs + seg.tmap.secs(time_steps) + ms / 1000.0
        return max(tick(time_steps) + 1, song_tick_at(secs))

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

    is_bank = bool(track_is_bank and track_is_bank[t])
    is_kit  = bool(prm.get("track_is_kit") and prm["track_is_kit"][t])
    # Canal courant de la piste à chaque instant (O3) : celui de son
    # dernier Program Change sur une banque, ou sur tout slot en mode Rack
    # (5f1, M18), à temps égal compris. Au début de chaque pattern, le
    # canal de la piste dans ce pattern.
    follows = is_bank or bool(prm.get("rack_mode"))
    changes = sorted((ev.time, seq, _clamp(ev.channel, 0, 15))
                     for seq, ev in enumerate(events)
                     if follows and ev.etype == ETYPE_PGM)

    def chan_at(time_steps, base_ch=track_channels[t]):
        ch_now = base_ch
        for when, _seq, c in changes:
            if when > time_steps:
                break
            ch_now = c
        return ch_now

    ch = chan_at(0)
    transpose = track_transposes[t] if track_transposes else 0
    gain_db   = track_gain_db[t] if track_gain_db else 0
    timed = []
    plays_notes = track_is_synth[t] or is_bank
    seg_end = seg.length
    # État de départ (E9) : complet au premier pattern joué sur ce canal,
    # sinon ce qui diffère. Rangs négatifs : avant les événements de _tape
    # au même tick, qui l'emportent donc.
    before = chstate.get(ch)
    want = {}
    program = track_programs[t] if track_programs else None
    if program is not None:
        want["program"] = _clamp(program, 0, 127)
    if track_volumes:
        want[7] = apply_gain_db(volume_to_cc7(track_volumes[t]), gain_db)
    if track_pans:
        want[10] = pan_to_cc10(track_pans[t])
    want[CC_REVERB] = 0        # pas de reverb ni de chorus (12a1 D3)
    want[CC_CHORUS] = 0
    for key, rank in (("program", -1), (7, -4), (10, -3), (CC_REVERB, -2), (CC_CHORUS, -1)):
        if key not in want or (before is not None and before.get(key) == want[key]):
            continue
        if key == "program":
            # rang -1 : avant un ETYPE_PGM capturé au tick 0, qui l'emporte
            timed.append((base, _ORDER_PGM, (k, rank), mido.Message(
                "program_change", channel=ch, program=want[key])))
        else:
            timed.append((base, _ORDER_CC, (k, rank), mido.Message(
                "control_change", channel=ch, control=key, value=want[key])))
    for seq, ev in enumerate(events):
        local = seg.tick(ev.time)
        if local >= seg_end:
            continue   # hors du pattern : jamais rejoué (12a4 D8)
        start = base + local
        rank = (k, seq)
        p = ev.payload
        ev_ch = chan_at(ev.time)
        if ev.etype == ETYPE_GRID:
            pad = p.get("pad", 0)
            if pad_audible and not pad_audible[pad]:
                continue  # pad muet ou hors solo au rejeu (12a3 D7)
            if is_bank and ev_ch == KIT_CHANNEL:
                note = BANK_DRUM_GRID_BASE + pad          # D12
            elif plays_notes:
                note = synth_grid_notes[pad] + transpose
            else:
                note = kit_note(kit_pad_notes[pad])
            ms = ev.dur if ev.dur > 0 else voice_durations[pad]
            vel = grid_velocity(p.get("vel", 100),
                                pad_volumes[pad] if pad_volumes else 100)
            notes.append((start, end_tick(ev.time, ms), note, vel, rank, ev_ch))
        elif ev.etype == ETYPE_KIT:
            # one-shot (dur toujours 0) : un pas
            note = p.get("note", 0)
            notes.append((start, start + max(1, seg.tick(1)),
                          note if is_bank else kit_note(note),
                          p.get("vel", 100), rank, ev_ch))
        elif ev.etype == ETYPE_PATCH:
            # Muette au rejeu sur une piste sans slot SYNTH, banque ou kit
            # (TrackRouter.on_patch_tape) : non exportée (Phase 7 étape
            # 10h5) ; sur un kit, jouée par sa note GM (5b1, M11)
            if not (plays_notes or is_kit):
                continue
            ms = ev.dur if ev.dur > 0 else PATCH_DEFAULT_MS
            notes.append((start, end_tick(ev.time, ms), p.get("note", 0) + transpose,
                          p.get("vel", 100), rank, ev_ch))
        elif ev.etype == ETYPE_PGM:
            timed.append((start, _ORDER_PGM, rank, mido.Message(
                "program_change", channel=_clamp(ev.channel, 0, 15) if follows else ev_ch,
                program=_clamp(p.get("program", 0), 0, 127))))
        elif ev.etype == ETYPE_CC:
            control = _clamp(p.get("cc_num", 0), 0, 127)
            value   = _clamp(p.get("value", 0), 0, 127)
            if control == 7:
                value = apply_gain_db(value, gain_db)
            bank_select = control in (0, 32)
            timed.append((start, _ORDER_BANK if bank_select else _ORDER_CC, rank,
                          mido.Message("control_change",
                                       channel=_clamp(ev.channel, 0, 15)
                                       if follows and bank_select else ev_ch,
                                       control=control, value=value)))
        elif ev.etype == ETYPE_BEND:
            timed.append((start, _ORDER_BEND, rank, mido.Message(
                "pitchwheel", channel=ev_ch,
                pitch=_clamp(p.get("value", 0), -8192, 8191))))

    # État laissé sur chaque canal par ce segment, dans l'ordre d'écriture
    for _at, _order, _rank, msg in sorted(timed, key=lambda e: (e[0], e[1], e[2])):
        st = chstate.setdefault(msg.channel, {})
        if msg.type == "program_change":
            st["program"] = msg.program
        elif msg.type == "control_change" and msg.control in (7, 10, CC_REVERB, CC_CHORUS):
            st[msg.control] = msg.value
    return timed


def export_pattern(path, pattern, **kwargs):
    """Écrit le pattern dans le fichier .mid `path` (voir build_pattern_midi).
    Retourne le mido.MidiFile écrit."""
    mid = build_pattern_midi(pattern, **kwargs)
    mid.save(path)
    return mid


def export_song(path, parts, **kwargs):
    """Écrit le song (liste de SongPart) dans le fichier .mid `path` (voir
    build_song_midi). Retourne le mido.MidiFile écrit."""
    mid = build_song_midi(parts, **kwargs)
    mid.save(path)
    return mid
