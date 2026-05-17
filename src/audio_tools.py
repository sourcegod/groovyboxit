#python3
"""
    File: src/audio_tools.py
    Utilitaires audio réutilisables : détection de période fondamentale,
    passages à zéro, corrélation croisée et recherche de points de bouclage.
    Utilisé par SynthEngine et par tools/find_loop_points.py.
    Date: Sun, 17/05/2026
    Author: Coolbrother
"""
import numpy as np
import soundfile as sf


class AudioTools:
    """
    Boîte à outils audio (méthodes statiques).
    Couvre la détection de points de bouclage WAV et le re-calage de ces
    points sur le signal après pitch shift.
    """

    # ── Utilitaires signal ───────────────────────────────────────────────────

    @staticmethod
    def to_mono(y):
        """Retourne un tableau 1-D float64 (moyenne des canaux si stéréo)."""
        if y.ndim > 1:
            return np.mean(y, axis=1)
        return y

    @staticmethod
    def find_fundamental_period(y, sr):
        """
        Estime la période fondamentale (en échantillons) par autocorrélation
        sur la portion centrale du signal (zone stable).
        Retourne None si la détection échoue.
        """
        mono = AudioTools.to_mono(y)
        n    = len(mono)

        seg_start = max(0, n // 4)
        seg_end   = min(seg_start + 8192, 3 * n // 4)
        seg = mono[seg_start:seg_end].copy()
        seg -= np.mean(seg)
        if np.max(np.abs(seg)) < 1e-6:
            return None

        corr = np.correlate(seg, seg, mode='full')
        corr = corr[len(corr) // 2:]
        corr /= corr[0] if corr[0] != 0 else 1.0

        lag_min = max(2, sr // 2000)
        lag_max = min(len(corr) - 1, sr // 50)
        sub  = corr[lag_min:lag_max]
        diff = np.diff(sub)
        peaks = np.where((diff[:-1] > 0) & (diff[1:] <= 0))[0] + lag_min + 1
        if len(peaks) == 0:
            return None
        return int(peaks[np.argmax(corr[peaks])])

    @staticmethod
    def zero_crossings_up(mono, start, end):
        """Indices des passages à zéro montants (négatif→positif) dans [start, end[."""
        start = max(0, int(start))
        end   = min(len(mono), int(end))
        seg   = mono[start:end]
        idx   = np.where((seg[:-1] <= 0) & (seg[1:] > 0))[0]
        return idx + start

    @staticmethod
    def cross_correlation(mono, pos1, pos2, length):
        """
        Corrélation de Pearson entre deux fenêtres de longueur `length`
        débutant en pos1 et pos2.  Retourne -1 si impossible.
        """
        n = len(mono)
        if pos1 + length > n or pos2 + length > n or pos1 < 0 or pos2 < 0:
            return -1.0
        s1 = mono[pos1: pos1 + length]
        s2 = mono[pos2: pos2 + length]
        if np.std(s1) < 1e-8 or np.std(s2) < 1e-8:
            return -1.0
        return float(np.corrcoef(s1, s2)[0, 1])

    # ── Détection de points de bouclage ─────────────────────────────────────

    @staticmethod
    def find_loop_points(wav_path, tail_ratio=0.15, min_corr=0.98, verbose=True):
        """
        Trouve (loop_start, loop_end, corrélation) pour wav_path.
        Retourne None si aucun point satisfaisant n'est trouvé.

        Algorithme :
          1. Autocorrélation → période fondamentale
          2. Passages à zéro montants dans les derniers tail_ratio du fichier
          3. Remonter de N × période (boucle ≥ 100 ms) pour loop_start en phase
          4. Valider par corrélation de Pearson ; garder le meilleur candidat
        """
        import os
        y, sr = sf.read(wav_path, dtype='float64', always_2d=False)
        mono  = AudioTools.to_mono(y)
        n     = len(mono)

        if verbose:
            print(f"  {os.path.basename(wav_path):<40s}  "
                  f"{n} samples  {sr} Hz  {n/sr:.2f} s")

        period = AudioTools.find_fundamental_period(y, sr)
        if period is None or period < 4:
            print("      → SKIP : période fondamentale non détectée")
            return None
        if verbose:
            print(f"      période : {period} samples  ({sr / period:.1f} Hz)")

        tail_start = int(n * (1.0 - tail_ratio))
        zc_end     = AudioTools.zero_crossings_up(mono, tail_start, n - period)
        if len(zc_end) == 0:
            print("      → SKIP : aucun passage à zéro dans la queue")
            return None

        best_corr  = -1.0
        best_start = None
        best_end   = None
        half       = period // 4

        min_loop_samples = int(0.100 * sr)
        min_n_per        = max(4, int(np.ceil(min_loop_samples / period)))

        for loop_end in zc_end:
            for n_per in range(min_n_per, min_n_per + 20):
                approx_start = loop_end - n_per * period
                if approx_start < period:
                    continue
                zc_s = AudioTools.zero_crossings_up(mono,
                                                    approx_start - half,
                                                    approx_start + half)
                if len(zc_s) == 0:
                    continue
                loop_start = int(zc_s[np.argmin(np.abs(zc_s - approx_start))])
                corr = AudioTools.cross_correlation(mono, loop_start, loop_end, period)
                if corr > best_corr:
                    best_corr  = corr
                    best_start = loop_start
                    best_end   = loop_end

        if best_start is None or best_corr < min_corr:
            print(f"      → SKIP : corrélation trop faible "
                  f"({best_corr:.4f} < {min_corr})")
            return None

        loop_ms = (best_end - best_start) / sr * 1000
        if verbose:
            print(f"      loop_start={best_start}  loop_end={best_end}  "
                  f"durée={loop_ms:.1f} ms  corr={best_corr:.4f}")

        return int(best_start), int(best_end), best_corr

    # ── Re-calage après pitch shift ──────────────────────────────────────────

    @staticmethod
    def snap_loop_to_zero_crossings(data, loop_start, loop_end, radius=2048):
        """
        Après pitch shift, re-cale loop_start/loop_end sur les passages à zéro
        montants du signal traité.

        Utilise la moyenne L+R pour le stéréo, afin que la discontinuité soit
        minimisée dans les deux canaux simultanément.
        Parmi les candidats pour loop_end, retient celui dont la corrélation
        croisée avec la région autour de loop_start est la meilleure — pas
        simplement le zéro géographiquement le plus proche.
        """
        mono = AudioTools.to_mono(data)
        n    = len(mono)

        # Passages à zéro montants près de loop_start
        zc_starts = AudioTools.zero_crossings_up(
            mono,
            max(0, loop_start - radius),
            min(n - 1, loop_start + radius),
        )
        if len(zc_starts) == 0:
            return loop_start, loop_end
        new_start = int(zc_starts[np.argmin(np.abs(zc_starts - loop_start))])

        # Passages à zéro montants près de loop_end
        zc_ends = AudioTools.zero_crossings_up(
            mono,
            max(0, loop_end - radius),
            min(n - 1, loop_end + radius),
        )
        if len(zc_ends) == 0:
            return new_start, loop_end

        # Parmi les candidats, choisir celui avec la meilleure corrélation
        corr_len  = max(64, min(512, (loop_end - loop_start) // 4))
        best_corr = -2.0
        best_end  = int(zc_ends[np.argmin(np.abs(zc_ends - loop_end))])

        for le in zc_ends:
            if int(le) <= new_start:
                continue
            c = AudioTools.cross_correlation(mono, new_start, int(le), corr_len)
            if c > best_corr:
                best_corr = c
                best_end  = int(le)

        if best_end <= new_start:
            return loop_start, loop_end
        return new_start, best_end
