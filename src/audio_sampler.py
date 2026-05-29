#python3
"""
    File: src/audio_sampler.py
    Rendu audio d'un sample : points de bouclage avec zero-crossfading
    (inspiré de FluidSynth), enveloppe ADSR linéaire, trois modes de jeu.

    Données internes : numpy float32 stéréo (shape N×2).
    Indépendant du driver audio — retourne toujours un np.ndarray.

    Modes
    -----
    ONESHOT : joue du début à la fin, s'arrête seul
    LOOP    : boucle jusqu'à SUSTAIN_SECONDS, fadeout final automatique
    GATE    : boucle tant que la note est tenue (note_on/note_off) ;
              pas de fadeout final — la voix est coupée par SynthEngine.stop()

    Prévu plus tard (fichiers séparés)
    -----------------------------------
    FadeShape : courbes linéaire / exp / inv_exp pour attack et release
    ADSR      : enveloppe complète paramétrée (utilisée dans l'éditeur de sample)
    Filtres   : passe-bas, passe-haut, etc.

    Date: Thu, 29/05/2026
    Author: Coolbrother
"""

import numpy as np


class PlayMode:
    ONESHOT = "oneshot"
    LOOP    = "loop"
    GATE    = "gate"


class AudioSampler:
    """
    Gère le rendu d'un sample audio en trois modes.

    Crossfade (style FluidSynth)
    ----------------------------
    Les xf_len derniers échantillons avant loop_end sont fondus avec les
    xf_len premiers après loop_start → le saut loop_end→loop_start est inaudible.
    Les points sont snappés aux passages à zéro avant application.

    ADSR (linéaire — courbes configurables prévues dans FadeShape)
    ---------------------------------------------------------------
    attack_ms  : fondu d'entrée linéaire
    decay_ms   : descente de 1.0 vers sustain
    sustain    : niveau maintenu (0.0..1.0)
    release_ms : fondu de sortie linéaire (non appliqué en mode GATE —
                 c'est SynthEngine.stop() qui coupe la voix)

    Usage minimal
    -------------
    s = AudioSampler.from_file("organ.wav")
    s.set_mode(PlayMode.GATE)
    s.set_loop(1.2, 3.8, crossfade_ms=10)
    s.set_adsr(attack_ms=5, sustain=0.9)
    buf = s.render()   # float32 stéréo → SoundDeviceDriver.play()
    """

    SUSTAIN_SECONDS = 8      # durée max du buffer loop/gate pré-rendu
    FADEOUT_MS      = 50     # fadeout final automatique (mode LOOP uniquement)

    def __init__(self, data: np.ndarray, samplerate: int):
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = np.column_stack([data, data])
        elif data.ndim == 2 and data.shape[1] == 1:
            data = np.column_stack([data[:, 0], data[:, 0]])
        self.data       = data          # (N, 2) float32
        self.samplerate = samplerate

        self._mode         = PlayMode.ONESHOT
        self._looping      = False
        self._loop_start   = None       # secondes
        self._loop_end     = None       # secondes
        self._crossfade_ms = 150.0      # ms — long crossfade style Gemini/FluidSynth

        self._attack_ms  = 0.0
        self._decay_ms   = 0.0
        self._sustain    = 1.0
        self._release_ms = 50.0

    # ------------------------------------------------------------------
    # Constructeur alternatif
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, wav_path: str) -> "AudioSampler":
        """Charge un fichier WAV (float32 stéréo normalisé)."""
        import soundfile as sf
        data, sr = sf.read(wav_path, dtype="float32", always_2d=True)
        return cls(data, sr)

    # ------------------------------------------------------------------
    # Configuration — mode
    # ------------------------------------------------------------------

    def set_mode(self, mode: str):
        """Définit le mode de jeu : PlayMode.ONESHOT | LOOP | GATE."""
        if mode not in (PlayMode.ONESHOT, PlayMode.LOOP, PlayMode.GATE):
            raise ValueError(f"Mode inconnu : {mode!r}")
        self._mode = mode

    # ------------------------------------------------------------------
    # Configuration — boucle
    # ------------------------------------------------------------------

    def set_loop(self, loop_start: float, loop_end: float,
                 crossfade_ms: float = None):
        """Configure les points de bouclage (secondes) et le crossfade.
        crossfade_ms=None conserve la valeur courante de _crossfade_ms (150ms par défaut).
        Activer le bouclage n'affecte pas le mode (ONESHOT reste ONESHOT).
        """
        self._looping    = True
        self._loop_start = float(loop_start)
        self._loop_end   = float(loop_end)
        if crossfade_ms is not None:
            self._crossfade_ms = max(0.0, crossfade_ms)

    def clear_loop(self):
        """Supprime les points de bouclage."""
        self._looping    = False
        self._loop_start = None
        self._loop_end   = None

    # ------------------------------------------------------------------
    # Configuration — ADSR (linéaire)
    # ------------------------------------------------------------------

    def set_adsr(self, attack_ms: float = 0.0, decay_ms: float = 0.0,
                 sustain: float = 1.0, release_ms: float = 50.0):
        """Configure l'enveloppe ADSR (courbes linéaires).
        release_ms ignoré en mode GATE (la voix est stoppée par SynthEngine).
        """
        self._attack_ms  = max(0.0, attack_ms)
        self._decay_ms   = max(0.0, decay_ms)
        self._sustain    = max(0.0, min(1.0, sustain))
        self._release_ms = max(0.0, release_ms)

    # ------------------------------------------------------------------
    # Zero-crossing snap
    # ------------------------------------------------------------------

    def snap_to_zero_crossing(self, pos_samples: int,
                               window: int = 512,
                               direction: str = "nearest") -> int:
        """Déplace pos_samples vers le passage à zéro le plus proche.

        direction : "nearest" | "before" | "after"
        Retourne pos_samples inchangé si aucun passage à zéro trouvé.
        """
        n     = len(self.data)
        start = max(0, pos_samples - window // 2)
        end   = min(n, pos_samples + window // 2)
        mono  = self.data[start:end, 0]

        signs     = np.sign(mono)
        crossings = np.where(np.diff(signs) != 0)[0] + start

        if len(crossings) == 0:
            return pos_samples

        if direction == "before":
            before = crossings[crossings <= pos_samples]
            return int(before[-1]) if len(before) else pos_samples
        if direction == "after":
            after = crossings[crossings >= pos_samples]
            return int(after[0]) if len(after) else pos_samples
        return int(crossings[np.argmin(np.abs(crossings - pos_samples))])

    # ------------------------------------------------------------------
    # Crossfade FluidSynth-style
    # ------------------------------------------------------------------

    def _apply_crossfade(self, data: np.ndarray,
                          ls: int, le: int) -> np.ndarray:
        """Crossfade FluidSynth-style : fond la fin de la boucle avec la région
        qui PRÉCÈDE loop_start (data[ls-N : ls]).

        Pourquoi data[ls-N:ls] et non data[ls:ls+N] ?
        -----------------------------------------------
        Avec data[ls:ls+N], le blend se termine à ~data[ls+N-1] puis saute à
        data[ls] → discontinuité (clic).
        Avec data[ls-N:ls], le blend se termine à ~data[ls-1] puis enchaîne sur
        data[ls] → transition normale entre échantillons consécutifs (inaudible).

        Contrainte : ls >= xf_len (garanti par le min() ci-dessous).
        """
        sr     = self.samplerate
        xf_len = int(self._crossfade_ms / 1000.0 * sr)
        xf_len = min(xf_len, le - ls, ls, len(data) - le)
        if xf_len < 2:
            return data

        data     = data.copy()
        fade_out = np.linspace(1.0, 0.0, xf_len, dtype=np.float32)[:, np.newaxis]
        fade_in  = np.linspace(0.0, 1.0, xf_len, dtype=np.float32)[:, np.newaxis]

        end_region = data[le - xf_len : le]     # fin de boucle (fade out)
        pre_start  = data[ls - xf_len : ls]     # juste avant loop_start (fade in)
        data[le - xf_len : le] = end_region * fade_out + pre_start * fade_in
        return data

    # ------------------------------------------------------------------
    # Pitch shifting
    # ------------------------------------------------------------------

    def pitch_shift(self, n_steps: float,
                    method: str = "rubberband") -> "AudioSampler":
        """Retourne un nouvel AudioSampler transposé de n_steps demi-tons.

        Paramètres
        ----------
        n_steps : float   nombre de demi-tons (positif = aigu, négatif = grave)
        method  : str     algorithme utilisé :
                          "rubberband"    — pyrubberband (actuel, qualité référence)
                          "wsola"         — WSOLA pur Python (à implémenter)
                          "phase_vocoder" — Phase Vocoder FFT (à implémenter)

        Retourne
        --------
        Nouvel AudioSampler avec les mêmes réglages (mode, loop, ADSR).
        """
        if n_steps == 0:
            # Notes root : conserver les loop points tels quels.
            # Ils ont été calibrés professionnellement (SF2) ou via find_loop_points.
            # Tout ajustement risque de les dégrader (period estimate imprécis).
            return self._clone(self.data)

        if method == "rubberband":
            shifted = self._pitch_shift_rubberband(self.data, n_steps)
        elif method == "wsola":
            shifted = self._pitch_shift_wsola(self.data, n_steps)
        elif method == "phase_vocoder":
            shifted = self._pitch_shift_phase_vocoder(self.data, n_steps)
        else:
            raise ValueError(f"Méthode de pitch shifting inconnue : {method!r}")

        cloned = self._clone(shifted)

        # Après pitch shift, les points de bouclage (en secondes) pointent vers
        # des positions dont la phase a changé dans l'audio pitché.
        # On re-snap ls et le sur des passages à zéro montants CORRÉLÉS dans
        # l'audio pitché (même logique que l'ancien SynthEngine._get_raw).
        if cloned._looping and cloned._loop_start is not None:
            from audio_tools import AudioTools
            sr   = cloned.samplerate
            mono = AudioTools.to_mono(shifted)
            n    = len(mono)
            ls_raw = int(cloned._loop_start * sr)
            le_raw = int(cloned._loop_end   * sr)

            # Étape 1 : snap loop_start sur le zéro montant le plus proche
            zc_starts = AudioTools.zero_crossings_up(
                mono, max(0, ls_raw - 2048), min(n - 1, ls_raw + 2048)
            )
            new_ls = int(zc_starts[np.argmin(np.abs(zc_starts - ls_raw))]) \
                     if len(zc_starts) else ls_raw

            # Étape 2 : trouver le loop_end qui minimise le reste fractionnaire
            # (le - new_ls) / période  →  zéro montant le plus proche d'un
            # multiple entier de la période.
            # Sans ça, un déphasage résiduel crée un battement audible pour
            # les notes pitchées (ex: F5 depuis root Gb5 → 73.93 périodes).
            period = AudioTools.find_fundamental_period(shifted, sr)
            if period and period >= 2:
                search_r = max(4096, int(period * 4))
                zc_ends  = AudioTools.zero_crossings_up(
                    mono,
                    max(0,    le_raw - search_r),
                    min(n - 1, le_raw + search_r),
                )
                if len(zc_ends):
                    fracs  = (zc_ends - new_ls) / period % 1
                    fracs  = np.minimum(fracs, 1.0 - fracs)   # symétrie mod 1
                    new_le = int(zc_ends[np.argmin(fracs)])
                else:
                    new_le = le_raw
            else:
                _, new_le = AudioTools.snap_loop_to_zero_crossings(
                    shifted, new_ls, le_raw
                )

            cloned._loop_start = new_ls / sr
            cloned._loop_end   = new_le / sr

        return cloned

    def _clone(self, data: np.ndarray) -> "AudioSampler":
        """Crée un nouvel AudioSampler avec data et les mêmes réglages."""
        s = AudioSampler(data, self.samplerate)
        s._mode         = self._mode
        s._looping      = self._looping
        s._loop_start   = self._loop_start
        s._loop_end     = self._loop_end
        s._crossfade_ms = self._crossfade_ms
        s._attack_ms    = self._attack_ms
        s._decay_ms     = self._decay_ms
        s._sustain      = self._sustain
        s._release_ms   = self._release_ms
        return s

    def _pitch_shift_rubberband(self, data: np.ndarray,
                                 n_steps: float) -> np.ndarray:
        """Pitch shifting via pyrubberband (implémentation actuelle).

        Algorithme : Rubber Band (C++), phase vocoder de qualité professionnelle.
        Pitch pur : la durée est préservée.
        """
        import pyrubberband as rb
        mono = data[:, 0] if data.ndim == 2 else data
        shifted = rb.pitch_shift(mono, self.samplerate, n_steps=n_steps)
        shifted = shifted.astype(np.float32)
        return np.column_stack([shifted, shifted])

    def _pitch_shift_wsola(self, data: np.ndarray,
                            n_steps: float) -> np.ndarray:
        """Pitch shifting WSOLA (Waveform Similarity Overlap-Add) — pur Python.

        Principe
        --------
        1. Rééchantillonner data avec un ratio r = 2^(n_steps/12)
           (change la hauteur ET la durée).
        2. Étirer temporellement par 1/r avec WSOLA pour rétablir la durée
           originale (cherche le meilleur alignement waveform dans une fenêtre
           de recherche via corrélation croisée).

        Avantages vs Phase Vocoder : peu d'artefacts sur les transitoires,
        adapté aux samples monophoniques (voix, instruments solo).

        À implémenter — références
        --------------------------
        Verhelst & Roelands (1993) : "An overlap-add technique based on
        waveform similarity (WSOLA) for high quality time-scale modification"
        """
        raise NotImplementedError(
            "WSOLA non encore implémenté — utiliser method='rubberband'"
        )

    def _pitch_shift_phase_vocoder(self, data: np.ndarray,
                                    n_steps: float) -> np.ndarray:
        """Pitch shifting par Phase Vocoder (FFT) — pur Python.

        Principe
        --------
        1. STFT (Short-Time Fourier Transform) avec fenêtre de Hann.
        2. Accumuler les phases de façon cohérente selon le ratio de pitch.
        3. ISTFT pour reconstruire le signal temporel.
        4. Rééchantillonner pour rétablir la durée originale.

        Avantages vs WSOLA : meilleur rendu sur le contenu harmonique complexe
        (piano, cordes, sons tenus polyphoniques).
        Inconvénient : artefacts de « phasiness » sur les transitoires.

        À implémenter — références
        --------------------------
        Laroche & Dolson (1999) : "Improved phase vocoder time-scale modification
        of audio" — IEEE Trans. Speech Audio Processing.
        librosa.effects.pitch_shift() pour une implémentation de référence.
        """
        raise NotImplementedError(
            "Phase Vocoder non encore implémenté — utiliser method='rubberband'"
        )

    # ------------------------------------------------------------------
    # Enveloppe ADSR (linéaire)
    # ------------------------------------------------------------------

    def _apply_adsr(self, data: np.ndarray,
                    apply_release: bool = True) -> np.ndarray:
        """Applique l'enveloppe ADSR linéaire sur le buffer.
        apply_release=False en mode GATE (la voix est coupée par stop()).
        """
        sr  = self.samplerate
        n   = len(data)
        env = np.ones(n, dtype=np.float32)

        # Attack
        a_n = min(int(self._attack_ms / 1000.0 * sr), n)
        if a_n > 0:
            env[:a_n] = np.linspace(0.0, 1.0, a_n, dtype=np.float32)

        # Decay
        d_n   = min(int(self._decay_ms / 1000.0 * sr), n - a_n)
        d_end = a_n + d_n
        if d_n > 0:
            env[a_n:d_end] = np.linspace(1.0, self._sustain, d_n, dtype=np.float32)

        # Release (à la fin du buffer, sauf en mode GATE)
        r_start = n
        if apply_release:
            r_n     = min(int(self._release_ms / 1000.0 * sr), n)
            r_start = n - r_n
            if r_n > 0 and r_start > d_end:
                env[r_start:] = np.linspace(self._sustain, 0.0, r_n, dtype=np.float32)

        # Sustain entre Decay et Release
        s_end = max(d_end, r_start)
        if s_end > d_end:
            env[d_end:s_end] = self._sustain

        return (data * env[:, np.newaxis]).astype(np.float32)

    # ------------------------------------------------------------------
    # Construction du buffer de sustain (loop / gate)
    # ------------------------------------------------------------------

    def _build_loop_buffer(self, duration_ms: float = 0,
                            fadeout: bool = True) -> np.ndarray:
        """Construit le buffer de sustain avec crossfade et snap zéro-crossings.
        fadeout=False en mode GATE (pas de fondu de sortie automatique).
        """
        sr = self.samplerate

        ls_raw = int(self._loop_start * sr)
        le_raw = int(self._loop_end   * sr)
        ls = self.snap_to_zero_crossing(ls_raw, direction="nearest")
        le = self.snap_to_zero_crossing(le_raw, direction="nearest")

        if le <= ls:
            return self.data.copy()

        target = int(duration_ms / 1000.0 * sr) if duration_ms > 0 \
                 else int(self.SUSTAIN_SECONDS * sr)

        xf_data     = self._apply_crossfade(self.data, ls, le)
        attack      = xf_data[:le]
        loop_region = xf_data[ls:le]
        loop_len    = len(loop_region)

        if loop_len == 0:
            return attack

        remaining = target - len(attack)
        if remaining <= 0:
            return attack[:target].copy()

        n_rep     = max(1, (remaining + loop_len - 1) // loop_len)
        sustained = np.concatenate([attack] + [loop_region] * n_rep)[:target].copy()

        if fadeout:
            fade_n = min(int(self.FADEOUT_MS / 1000.0 * sr), len(sustained) // 8)
            if fade_n > 1:
                fade = np.linspace(1.0, 0.0, fade_n, dtype=np.float32)[:, np.newaxis]
                sustained[-fade_n:] *= fade

        return sustained

    # ------------------------------------------------------------------
    # Rendu final
    # ------------------------------------------------------------------

    def render(self, duration_ms: float = 0) -> np.ndarray:
        """Génère le buffer audio final (float32 stéréo).

        ONESHOT : sample entier ou tronqué à duration_ms ; ADSR complet
        LOOP    : buffer de sustain avec fadeout final ; ADSR complet
        GATE    : buffer de sustain sans fadeout ; release ADSR omis
                  (la voix est coupée par SynthEngine.stop() sur note_off)

        Retourne np.ndarray (N, 2) float32 prêt pour SoundDeviceDriver.
        """
        if self._mode == PlayMode.ONESHOT or not self._looping:
            if duration_ms > 0:
                n    = int(duration_ms / 1000.0 * self.samplerate)
                data = self.data[:n].copy() if n < len(self.data) else self.data.copy()
            else:
                data = self.data.copy()
            return self._apply_adsr(data, apply_release=True)

        if self._mode == PlayMode.LOOP:
            data = self._build_loop_buffer(duration_ms, fadeout=True)
            return self._apply_adsr(data, apply_release=True)

        # GATE
        data = self._build_loop_buffer(duration_ms, fadeout=False)
        return self._apply_adsr(data, apply_release=False)

    # ------------------------------------------------------------------
    # Informations
    # ------------------------------------------------------------------

    def get_loop_params(self) -> tuple:
        """Retourne (ls, le, xf_samples) en échantillons si _looping, sinon (None, None, 0).
        ls et le sont snappés au passage à zéro le plus proche.

        xf est capé à min(ls, llen) comme Gemini/FluidSynth :
          - xf <= ls  : prev = pos - llen >= 0 toujours valide
          - xf <= llen: crossfade ne dépasse jamais un cycle de boucle
        """
        if not self._looping or self._loop_start is None:
            return None, None, 0
        sr     = self.samplerate
        ls_raw = int(self._loop_start * sr)
        le_raw = int(self._loop_end   * sr)
        ls   = self.snap_to_zero_crossing(ls_raw, direction="nearest")
        le   = self.snap_to_zero_crossing(le_raw, direction="nearest")
        llen = le - ls
        xf   = max(2, int(self._crossfade_ms / 1000.0 * sr))
        xf   = min(xf, ls, llen)          # bornes Gemini-style
        return ls, le, xf

    @property
    def duration_s(self) -> float:
        return len(self.data) / self.samplerate

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_looping(self) -> bool:
        return self._looping

    def __repr__(self):
        loop_info = ""
        if self._looping and self._loop_start is not None:
            loop_info = (f", loop({self._loop_start:.3f}s–{self._loop_end:.3f}s"
                         f", xf={self._crossfade_ms}ms)")
        return (f"AudioSampler(sr={self.samplerate}, "
                f"dur={self.duration_s:.3f}s, mode={self._mode}{loop_info})")
