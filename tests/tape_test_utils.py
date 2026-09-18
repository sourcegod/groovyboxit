#python3
"""
    File: tests/tape_test_utils.py
    Utilitaires pour manipuler Pattern._tape depuis les tests.

    Phase 7 étape 1c a fait passer _tape d'un dict {(track,bar,step): [TapeEvent]}
    à une liste plate par piste (position = TapeEvent.time). Ces helpers traduisent
    les anciens accès "position-style" (track,bar,step) vers le nouveau stockage,
    pour que les tests restent lisibles sans dupliquer la logique de conversion.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pattern import TapeEvent


def tape_at(p, t, b, s):
    """Liste des TapeEvent à (t,b,s) — équivalent de l'ancien p._tape.get((t,b,s), [])."""
    if t >= len(p._tape):
        return []
    time = p._bar_step_to_time(b, s)
    return [ev for ev in p._tape[t] if ev.time == time]


def has_tape_at(p, t, b, s):
    """Équivalent de l'ancien (t,b,s) in p._tape."""
    return len(tape_at(p, t, b, s)) > 0


def retimed(ev, time):
    """Copie ev avec .time = time (les fixtures construisent souvent l'event sans time)."""
    return TapeEvent(ev.etype, dur=ev.dur, channel=ev.channel, payload=ev.payload, time=time)


def set_tape_at(p, t, b, s, events):
    """Remplace les événements à (t,b,s) — équivalent de l'ancien p._tape[(t,b,s)] = events."""
    p._ensure_track_count(t + 1)
    time = p._bar_step_to_time(b, s)
    track_list = p._tape[t]
    track_list[:] = [ev for ev in track_list if ev.time != time]
    for ev in events:
        track_list.append(retimed(ev, time))


def add_tape_at(p, t, b, s, ev):
    """Ajoute un événement à (t,b,s) — équivalent de l'ancien
    p._tape.setdefault((t,b,s), []).append(ev)."""
    p._ensure_track_count(t + 1)
    time = p._bar_step_to_time(b, s)
    p._tape[t].append(retimed(ev, time))


def all_tape_events(p):
    """Toutes les TapeEvent de toutes les pistes, à plat — équivalent de l'ancien
    (ev for evs in p._tape.values() for ev in evs)."""
    return [ev for track_list in p._tape for ev in track_list]


def _canon(ev):
    """Représentation canonique/triable d'un TapeEvent (celui-ci n'est pas hashable :
    __eq__ est défini sans __hash__, et payload est un dict). Sert à comparer des
    ensembles d'événements sans dépendre de l'ordre ni de set()."""
    return (ev.etype, ev.dur, ev.channel, tuple(sorted(ev.payload.items())))


def same_events(a, b):
    """True si les deux collections de TapeEvent contiennent les mêmes éléments
    (multiset), indépendamment de l'ordre — remplace l'ancien set(...) == set(...)."""
    return sorted(map(_canon, a)) == sorted(map(_canon, b))


def assign_tape(p, spec):
    """Remplace tout p._tape à partir d'un spec {(t,b,s): [TapeEvent,...]} —
    équivalent de l'ancien p._tape = {...} (littéral dict)."""
    max_t = max((t for (t, b, s) in spec), default=-1)
    if max_t + 1 > len(p._tape):
        p._ensure_track_count(max_t + 1)
    new_tape = [[] for _ in range(len(p._tape))]
    for (t, b, s), events in spec.items():
        time = p._bar_step_to_time(b, s)
        for ev in events:
            new_tape[t].append(retimed(ev, time))
    p._tape = new_tape


def flush_tape(dst_pattern, src_pattern):
    """Copie _tape de src_pattern vers dst_pattern (liste de listes) — équivalent
    de l'ancien dst._tape = dict(src._tape)."""
    dst_pattern._tape = [list(track_list) for track_list in src_pattern._tape]


def tapes_equal_strict(a, b):
    """Compare deux _tape (listes de listes de TapeEvent) piste par piste, y
    compris .time (que TapeEvent.__eq__ ignore volontairement) — pour les
    tests d'intégrité round-trip stricts (position ET contenu)."""
    if len(a) != len(b):
        return False
    for track_a, track_b in zip(a, b):
        if len(track_a) != len(track_b):
            return False
        for ea, eb in zip(track_a, track_b):
            if ea != eb or ea.time != eb.time:
                return False
    return True


def tape_positions(p, track=None):
    """Liste des (t, bar, step) où il existe au moins un événement — équivalent de
    l'ancien list(p._tape.keys())."""
    tracks = range(len(p._tape)) if track is None else (track,)
    out = []
    for t in tracks:
        if t >= len(p._tape):
            continue
        for ev in p._tape[t]:
            bar, step = p._time_to_bar_step(ev.time)
            out.append((t, bar, step))
    return out
