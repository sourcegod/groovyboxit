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
    def find_loop_points(wav_path,
                         sustain_start=0.25, sustain_end=0.80,
                         min_loop_ms=100, max_loop_ms=3000,
                         min_corr=0.90,
                         tail_ratio=None,   # ignoré (rétrocompat)
                         verbose=True):
        """
        Trouve (loop_start, loop_end, corr_loop) pour wav_path.
        Retourne None si aucun point satisfaisant n'est trouvé.

        Stratégie (v2) :
          1. Autocorrélation → période fondamentale P
          2. Fixer loop_start dans la zone sustain [sustain_start, sustain_end]
          3. Chercher loop_end = zéro montant le plus proche de
             loop_start + n×P  (n dans [min_loop_ms/P, max_loop_ms/P])
             → frac_period minimal garanti par construction
          4. Scorer par corr_loop (Pearson sur 2 périodes à la jonction)
             et pénaliser le reste fractionnaire
          5. Retourner le meilleur si corr_loop ≥ min_corr

        Paramètres
        ----------
        sustain_start : ratio début zone sustain (défaut 0.25)
        sustain_end   : ratio fin   zone sustain (défaut 0.80)
        min_loop_ms   : durée min boucle en ms   (défaut 100)
        max_loop_ms   : durée max boucle en ms   (défaut 3000)
        min_corr      : seuil corr_loop minimum  (défaut 0.90)
        """
        import os
        y, sr = sf.read(wav_path, dtype='float64', always_2d=False)
        mono  = AudioTools.to_mono(y)
        n     = len(mono)

        if verbose:
            print(f"  {os.path.basename(wav_path):<42s} "
                  f"{n} smp  {sr} Hz  {n/sr:.2f} s")

        period = AudioTools.find_fundamental_period(y, sr)
        if period is None or period < 4:
            if verbose:
                print("      → SKIP : période fondamentale non détectée")
            return None
        if verbose:
            print(f"      période : {period} smp  ({sr/period:.1f} Hz)")

        # Zone sustain pour loop_start
        ls_zone_start = int(n * sustain_start)
        ls_zone_end   = int(n * sustain_end)
        zc_starts = AudioTools.zero_crossings_up(mono, ls_zone_start, ls_zone_end)
        if len(zc_starts) == 0:
            if verbose:
                print("      → SKIP : aucun zéro montant dans la zone sustain")
            return None

        min_n = max(1, int(np.ceil(min_loop_ms / 1000 * sr / period)))
        max_n = max(min_n + 1, int(np.floor(max_loop_ms / 1000 * sr / period)))

        best_score = -1.0
        best_ls    = None
        best_le    = None
        best_corr  = -1.0
        best_frac  = 1.0

        corr_len = min(int(period * 2), 4096)

        # Sous-ensemble représentatif de loop_start (max 30 candidats)
        step = max(1, len(zc_starts) // 30)
        for ls in zc_starts[::step]:
            for n_per in range(min_n, max_n + 1):
                ideal_le = int(ls + n_per * period)
                if ideal_le >= int(n * sustain_end):
                    break

                search_r = max(int(period // 2), 64)
                zc_e = AudioTools.zero_crossings_up(
                    mono,
                    max(ls + 2, ideal_le - search_r),
                    min(n - 1, ideal_le + search_r),
                )
                if len(zc_e) == 0:
                    continue
                le = int(zc_e[np.argmin(np.abs(zc_e - ideal_le))])

                llen = le - ls
                if llen <= 0:
                    continue

                # corr_loop : 2 périodes à la jonction, dans la boucle
                corr = AudioTools.cross_correlation(
                    mono, le - corr_len, ls, corr_len
                )
                if corr < 0:
                    continue

                frac  = (llen / period) % 1.0
                frac  = min(frac, 1.0 - frac)
                score = corr * (1.0 - frac * 2)

                if score > best_score:
                    best_score = score
                    best_ls    = ls
                    best_le    = le
                    best_corr  = corr
                    best_frac  = frac

        if best_ls is None or best_corr < min_corr:
            if verbose:
                print(f"      → SKIP : meilleure corr={best_corr:.4f} < {min_corr}")
            return None

        loop_ms = (best_le - best_ls) / sr * 1000
        if verbose:
            print(f"      ls={best_ls}  le={best_le}  {loop_ms:.0f} ms"
                  f"  corr={best_corr:.4f}  frac={best_frac:.4f}")

        return int(best_ls), int(best_le), best_corr

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
