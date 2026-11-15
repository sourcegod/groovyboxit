#python3
"""
    File: src/player/tape_events.py
    Événements de _tape à jouer dans une fenêtre, et jeu d'un événement,
    partagés par la lecture (DrumPlayer) et le rendu hors temps réel de
    l'export WAV (Phase 8 étape 1d1, docs/DESIGN.md § Phase 8 étape 1a,
    W6, W7). Fonctions pures, sans wx ni état du player : la lecture et
    le rendu suivent les mêmes règles.
    Date: Sat, 31/10/2026
    Author: Coolbrother
"""
from pattern import ETYPE_GRID, ETYPE_KIT, ETYPE_PATCH, ETYPE_CC, ETYPE_PGM, ETYPE_BEND, ETYPE_AUDIO, clip_window

# Marqueurs internes des événements (repris par PlaybackLoopMixin)
GRID_EVENT       = -6   # événements grille (etype ETYPE_GRID de _tape)
KIT_TAPE_EVENT   = -2   # événements kit_tape (MIDI brut)
PATCH_TAPE_EVENT = -3   # événements patch_tape (MIDI brut)
BEND_TAPE_EVENT  = -4   # événements Pitch Bend (etype ETYPE_BEND de _tape)
CC_TAPE_EVENT    = -7   # événements CC générique (etype ETYPE_CC de _tape)
PGM_TAPE_EVENT   = -8   # événements Program Change (etype ETYPE_PGM de _tape)
# -9 : changement de tempo (DrumPlayer.TEMPO_EVENT)
AUDIO_TAPE_EVENT = -10  # clip audio d'une piste audio (ETYPE_AUDIO, Phase 8 étape 14d1)

DEFAULT_NOTE_MS  = 500  # durée d'une note sans durée propre (TrackRouter)


def tape_events(tape, lp_start, lp_end, to_sec, min_sec=None):
    """Événements de tape (listes d'événements par piste) dont le temps est
    dans [lp_start, lp_end], en (t_sec, marqueur, données, vélocité) avec
    t_sec = to_sec(temps - lp_start). min_sec : seuls ceux après ce
    temps (en secondes) sont gardés ; None = tous. Ordre de tape (pistes,
    puis rang dans la piste) : le tri par (t_sec, marqueur) est à faire par
    l'appelant, avec les autres événements de la fenêtre."""
    events = []
    for t_idx, note_list in enumerate(tape):
        for ev in note_list:
            float_off = ev.time
            if not (lp_start <= float_off <= lp_end):
                continue
            t_sec = to_sec(float_off - lp_start)
            if min_sec is not None and t_sec <= min_sec:
                continue
            if ev.etype == ETYPE_GRID:
                events.append((t_sec, GRID_EVENT,
                               (t_idx, ev.payload.get("pad"), ev.dur), ev.payload.get("vel")))
            elif ev.etype == ETYPE_KIT:
                events.append((t_sec, KIT_TAPE_EVENT,
                               (t_idx, ev.payload.get("note"), ev.dur), ev.payload.get("vel")))
            elif ev.etype == ETYPE_PATCH:
                events.append((t_sec, PATCH_TAPE_EVENT,
                               (t_idx, ev.payload.get("note"), ev.dur),
                               ev.payload.get("vel")))
            elif ev.etype == ETYPE_CC:
                events.append((t_sec, CC_TAPE_EVENT,
                               (t_idx, ev.payload.get("cc_num"), ev.payload.get("value"),
                                ev.channel), 0))
            elif ev.etype == ETYPE_PGM:
                # canal de l'événement : celui où la piste Banque
                # passe (Phase 7 étape 17f1, docs/DESIGN.md § 17e3 O3)
                events.append((t_sec, PGM_TAPE_EVENT,
                               (t_idx, ev.payload.get("program"), ev.channel), 0))
            elif ev.etype == ETYPE_BEND:
                events.append((t_sec, BEND_TAPE_EVENT,
                               (t_idx, ev.payload.get("value")), 0))
            elif ev.etype == ETYPE_AUDIO:
                events.append((t_sec, AUDIO_TAPE_EVENT, audio_clip_data(t_idx, ev), 0))
    return events


def audio_clip_data(t_idx, ev, offset=0.0):
    """Données d'un clip audio (Phase 8 étape 14d1) : (piste, fichier
    relatif, gain, id du clip, décalage en secondes dans le clip — non
    nul quand la lecture part du milieu du clip —, start, length : fenêtre
    sur le fichier en échantillons du fichier, length None = jusqu'à la
    fin, Phase 8 étape 14e3)."""
    start, length = clip_window(ev.payload)
    return (t_idx, ev.payload.get("file", ""), float(ev.payload.get("gain", 1.0)),
            ev.id, offset, start, length)


AUDIO_RESYNC_SECS = 0.25   # pas des rappels « clip en cours » (14d1, essai)


def audio_clip_resyncs(tape, lp_start, lp_end, to_sec, elapsed, end_sec, duration_of,
                       step=AUDIO_RESYNC_SECS):
    """Rappels « clip en cours » (essai de 14d1) : pour chaque clip de la
    fenêtre, un événement tous les step secondes tant que le clip doit
    sonner (jusqu'à sa fin ou celle de la fenêtre), avec son décalage. Le
    routeur ignore un clip qui sonne déjà ; un clip coupé (Mute, Solo, F5)
    reprend ainsi au bon endroit, au plus step secondes plus tard.
    duration_of(fichier, start, length) → durée de la fenêtre du clip en
    secondes (0 : inconnue, pas de rappel ; 14e3).
    Boucles simples sur des nombres : portable tel quel en C/C++."""
    events = []
    for t_idx, note_list in enumerate(tape):
        for ev in note_list:
            if ev.etype != ETYPE_AUDIO or not (lp_start <= ev.time <= lp_end):
                continue
            t0  = to_sec(ev.time - lp_start)
            start, length = clip_window(ev.payload)
            end = min(t0 + duration_of(ev.payload.get("file", ""), start, length), end_sec)
            k = 1
            while t0 + k * step < end:
                t = t0 + k * step
                if t > elapsed - 0.002:
                    events.append((t, AUDIO_TAPE_EVENT, audio_clip_data(t_idx, ev, t - t0), 0))
                k += 1
    return events


def audio_clips_under_way(tape, lp_start, lp_end, to_sec, elapsed):
    """Clips audio de la fenêtre déjà commencés à elapsed (lecture partie du
    milieu, retour de Mute…) : événements à elapsed, avec le décalage dans le
    fichier ; le routeur ne relance pas un clip qui sonne déjà (14d1)."""
    events = []
    for t_idx, note_list in enumerate(tape):
        for ev in note_list:
            if ev.etype != ETYPE_AUDIO or not (lp_start <= ev.time <= lp_end):
                continue
            t_sec = to_sec(ev.time - lp_start)
            if t_sec <= elapsed - 0.002:
                events.append((elapsed, AUDIO_TAPE_EVENT,
                               audio_clip_data(t_idx, ev, elapsed - t_sec), 0))
    return events


def sort_events(events):
    """Tri stable sur (temps, marqueur) seulement : à temps égal, les
    événements gardent l'ordre de _tape (pistes, puis rang dans la
    piste). Trier aussi sur les données classait les CC par numéro :
    un CC121 (Reset All Controllers) passait après le CC64 qui le
    suit, et relâchait la pédale (Phase 7 étape 18d3, § 18d2)."""
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def grid_hit(voice_manager, pad_idx, velocity, dur_override, master_pan):
    """(volume, pan, durée en ms) d'une case de grille, None si le pad est
    muet ou hors solo. dur_override > 0 (Numpad1/3, Phase 7 étape 1k)
    prime sur la durée de la voix, pour cette occurrence uniquement ;
    pan = pan du pad + pan global, borné à ±100."""
    if not voice_manager.is_audible(pad_idx):
        return None
    vol = min(1.0, voice_manager.get_volume_factor(pad_idx) * velocity / 100.0)
    pan = max(-100, min(100, master_pan + voice_manager.get_pan(pad_idx)))
    dur = dur_override if dur_override > 0 else voice_manager.get_duration_ms(pad_idx)
    return vol, pan, dur


def play_event(router, voice_manager, master_pan, marker, data, velocity):
    """Joue un événement de tape_events sur router (TrackRouter), comme la
    lecture le fait par ses callbacks, sans effacement ni enregistrement."""
    if marker == GRID_EVENT:
        t_idx, pad_idx, dur_override = data
        hit = grid_hit(voice_manager, pad_idx, velocity, dur_override, master_pan)
        if hit is not None:
            router.on_play(t_idx, pad_idx, *hit)
    elif marker == KIT_TAPE_EVENT:
        t_idx, midi_note, dur = data
        router.on_kit_tape(t_idx, midi_note, velocity, dur)
    elif marker == PATCH_TAPE_EVENT:
        t_idx, midi_note, dur = data
        router.on_patch_tape(t_idx, midi_note, velocity, dur)
    elif marker == BEND_TAPE_EVENT:
        router.on_bend_tape(*data)
    elif marker == CC_TAPE_EVENT:
        router.on_cc_tape(*data)
    elif marker == PGM_TAPE_EVENT:
        router.on_program_change_tape(*data)
    elif marker == AUDIO_TAPE_EVENT:
        router.on_audio_clip(*data)
