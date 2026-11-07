#python3
"""
    File: src/audio/live_limiter.py
    Limiteur du mix à l'écoute (Phase 8 étape 8c1, docs/DESIGN.md § 8a
    L1, L2, L5) : brickwall sans anticipation, traité bloc par bloc dans le
    callback du pilote audio, à la place de l'écrêtage.

    - Seuil −0,3 dBFS en crête d'échantillon, comme le limiteur de l'export
      WAV (PEAK_DB d'audio_export) ; même gain sur les deux canaux (stéréo
      liée) : l'image ne bouge pas.
    - Sans anticipation (aucune latence ajoutée) : le gain baisse à
      l'échantillon même de la crête (attaque immédiate), puis revient vers
      1 par un retour exponentiel de 50 ms.
    - Garantie : aucun échantillon ne dépasse le seuil.

    g[n] = min(demandé[n], 1 − (1 − g[n−1]) · c), c = exp(−1 / τ),
    demandé[n] = min(1, seuil / max(|G[n]|, |D[n]|)).
    Avec z = 1 − g : z[n] = max(1 − demandé[n], c · z[n−1]), soit
    z[n] = max sur k ≤ n de (1 − demandé[k]) · c^(n−k), le bloc précédent
    entrant par son dernier z : un maximum cumulé en logarithmes, vectorisé
    par bloc (même astuce que _release de l'export).

    Module pur (numpy), sans pilote ni wx ; prototype, cible C/C++ (une
    récurrence par échantillon).
    Date: Sat, 07/11/2026
    Author: Coolbrother
"""

import math

import numpy as np

THRESHOLD_DB = -0.3     # comme PEAK_DB de l'export WAV (L2)
RELEASE_S    = 0.05     # constante de temps du retour, comme l'export


class LiveLimiter:
    """Limiteur en flux : process(block) traite un bloc en place et garde
    son état (réduction en cours) pour le bloc suivant."""

    def __init__(self, samplerate=44100, threshold_db=THRESHOLD_DB, release_s=RELEASE_S):
        self.samplerate = samplerate
        self.threshold  = 10.0 ** (threshold_db / 20.0)
        # visé un rien sous le seuil : l'arrondi en float32 du gain ne fait
        # jamais dépasser le seuil (garantie stricte)
        self._target    = self.threshold * (1.0 - 1e-6)
        self._tau       = max(1e-9, release_s * samplerate)   # en échantillons
        self._z         = 0.0      # 1 − gain du dernier échantillon traité
        self._min_gain  = 1.0      # plus faible gain depuis la dernière lecture

    def reset(self):
        """Oublie la réduction en cours (arrêt, changement de pilote)."""
        self._z = 0.0
        self._min_gain = 1.0

    @property
    def gain(self):
        """Gain du dernier échantillon traité (1 : aucune réduction)."""
        return 1.0 - self._z

    def reduction_db(self, reset=True):
        """Plus forte réduction (dB, ≤ 0) depuis la dernière lecture."""
        db = 20.0 * math.log10(max(self._min_gain, 1e-12))
        if reset:
            self._min_gain = 1.0
        return db

    def process(self, block):
        """Limite en place block, tableau float32 (frames, 2). Retourne le
        plus faible gain appliqué au bloc."""
        n = len(block)
        if n == 0:
            return 1.0
        peak = np.max(np.abs(block), axis=1)
        over = peak > self.threshold
        if not over.any() and self._z < 1e-7:
            self._z = 0.0                      # rien à limiter, réduction finie
            return 1.0
        k = np.arange(n, dtype=np.float64)
        with np.errstate(divide="ignore"):
            req = np.where(over, self._target / np.maximum(peak, 1e-30), 1.0)
            logd = np.log(1.0 - req)            # −inf là où rien n'est demandé
            # réduction héritée du bloc précédent, vue à l'échantillon −1
            prev = math.log(self._z) - 1.0 / self._tau if self._z > 0.0 else -np.inf
        acc = np.maximum.accumulate(np.maximum(logd + k / self._tau, prev))
        z = np.exp(acc - k / self._tau)
        gain = (1.0 - z).astype(np.float32)
        block *= gain[:, None]
        self._z = float(z[-1])
        low = float(gain.min())
        self._min_gain = min(self._min_gain, low)
        return low
