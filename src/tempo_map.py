#python3
"""
    File: src/tempo_map.py
    Carte de tempo d'un pattern — Phase 7 étape 19b1, docs/DESIGN.md § 19a1
    (T2-T4). Un tempo de départ et des changements instantanés (position en
    pas, BPM entier) ; conversion pas ↔ secondes linéaire par morceaux.
    Sans dépendance à wx ni au player : interface étroite, portable C/C++.
    Tempos décimaux à 0,01 près depuis la Phase 7 étape 19d3 (§ 19d2 R1).
    Date: Thu, 29/10/2026
    Author: Coolbrother
"""
from bisect import bisect_right

BPM_MIN = 1
BPM_MAX = 600


def clamp_bpm(bpm):
    """BPM borné à 1..600 et arrondi à 0,01 (§ 19d2 R1) ; entier s'il n'a pas
    de décimales (.gvp et affichage plus lisibles)."""
    value = round(max(BPM_MIN, min(BPM_MAX, float(bpm))), 2)
    return int(value) if value == int(value) else value


def format_bpm(bpm):
    """Tempo pour l'affichage : décimales seulement s'il en a, virgule
    française (« 92 », « 46,5 », « 93,75 ») — § 19d2 R1."""
    value = clamp_bpm(bpm)
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}".rstrip("0").replace(".", ",")


def normalize_changes(start_bpm, changes):
    """Liste triée [(position, bpm)] : positions > 0, BPM entiers bornés, à
    position égale le dernier l'emporte, un changement égal au tempo qui le
    précède retiré (comme Sonar, T2)."""
    by_pos = {}
    for pos, bpm in changes:
        if pos > 0:
            by_pos[pos] = clamp_bpm(bpm)
    out  = []
    prev = clamp_bpm(start_bpm)
    for pos in sorted(by_pos):
        bpm = by_pos[pos]
        if bpm != prev:
            out.append((pos, bpm))
            prev = bpm
    return out


class TempoMap:
    """Tempo de départ + changements ; steps_per_beat = pas par noire.

    secs(pas)   : secondes depuis la position 0
    steps(secs) : position en pas atteinte après secs secondes (inverse)
    bpm_at(pas) : tempo en vigueur à la position (un changement s'applique
                  à partir de sa position, comprise)
    """

    def __init__(self, start_bpm, changes=(), steps_per_beat=4.0):
        self.start_bpm      = clamp_bpm(start_bpm)
        self.changes        = normalize_changes(self.start_bpm, changes)
        self.steps_per_beat = float(steps_per_beat)
        # Segments : position de début, seconde de début, secondes par pas
        self._pos  = [0.0]
        self._sec  = [0.0]
        self._rate = [self._sec_per_step(self.start_bpm)]
        for pos, bpm in self.changes:
            self._sec.append(self._sec[-1] + (pos - self._pos[-1]) * self._rate[-1])
            self._pos.append(float(pos))
            self._rate.append(self._sec_per_step(bpm))

    def _sec_per_step(self, bpm):
        return 60.0 / (bpm * self.steps_per_beat)

    @property
    def is_constant(self):
        return not self.changes

    def secs(self, steps):
        """Secondes depuis 0 jusqu'à la position steps (≥ 0)."""
        i = max(0, bisect_right(self._pos, steps) - 1)
        return self._sec[i] + (steps - self._pos[i]) * self._rate[i]

    def steps(self, secs):
        """Position atteinte après secs secondes depuis 0."""
        i = max(0, bisect_right(self._sec, secs) - 1)
        return self._pos[i] + (secs - self._sec[i]) / self._rate[i]

    def secs_between(self, start, end):
        """Durée en secondes de la position start à la position end."""
        return self.secs(end) - self.secs(start)

    def bpm_at(self, steps):
        """Tempo en vigueur à la position steps."""
        i = max(0, bisect_right(self._pos, steps) - 1)
        return self.start_bpm if i == 0 else self.changes[i - 1][1]
