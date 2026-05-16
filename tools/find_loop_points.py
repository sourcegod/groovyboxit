#python3
"""
    File: tools/find_loop_points.py
    Détecte les points de bouclage (loop_start, loop_end) dans les samples
    WAV d'un patch et met à jour patch.json.

    Algorithme :
      1. Autocorrélation sur la zone centrale → période fondamentale
      2. Chercher loop_end dans les derniers --tail % du fichier
         (passage à zéro montant)
      3. Remonter de N × période pour trouver loop_start en phase
      4. Valider par corrélation croisée ; garder le meilleur candidat
      5. Écrire loop_start / loop_end par sample dans patch.json

    Usage :
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast --dry-run
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast --tail 0.20 --min-corr 0.95

    Date: Sat, 17/05/2026
    Author: Coolbrother
"""
import os
import sys
import json
import argparse
import numpy as np
import soundfile as sf


# ──────────────────────────────────────────────────────────────────────────────
# Utilitaires signal
# ──────────────────────────────────────────────────────────────────────────────

def _to_mono(y):
    """Retourne un tableau 1-D float64."""
    if y.ndim > 1:
        return y[:, 0]
    return y


def find_fundamental_period(y, sr):
    """
    Estime la période fondamentale (en échantillons) par autocorrélation
    sur la portion centrale du signal (zone stable, hors attaque et relâche).
    Retourne None si la détection échoue.
    """
    mono = _to_mono(y)
    n    = len(mono)

    # Fenêtre d'analyse : 25 %–75 % du signal, max 8 192 samples
    seg_start = max(0, n // 4)
    seg_end   = min(seg_start + 8192, 3 * n // 4)
    seg = mono[seg_start:seg_end].copy()
    seg -= np.mean(seg)

    if np.max(np.abs(seg)) < 1e-6:
        return None     # signal quasi-silencieux

    # Autocorrélation (normalisée)
    corr = np.correlate(seg, seg, mode='full')
    corr = corr[len(corr) // 2:]          # partie causale (lag ≥ 0)
    corr /= corr[0] if corr[0] != 0 else 1.0

    # Plage de recherche : 50 Hz … 2 000 Hz
    lag_min = max(2, sr // 2000)
    lag_max = min(len(corr) - 1, sr // 50)

    sub  = corr[lag_min:lag_max]
    diff = np.diff(sub)

    # Premiers pics locaux (signe de diff change de + à -)
    peaks = np.where((diff[:-1] > 0) & (diff[1:] <= 0))[0] + lag_min + 1
    if len(peaks) == 0:
        return None

    # Pic de corrélation maximale dans la plage
    best = peaks[np.argmax(corr[peaks])]
    return int(best)


def zero_crossings_up(mono, start, end):
    """Indices des passages à zéro montants (négatif→positif) dans [start, end[."""
    start = max(0, start)
    end   = min(len(mono), end)
    seg   = mono[start:end]
    idx   = np.where((seg[:-1] <= 0) & (seg[1:] > 0))[0]
    return idx + start


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


# ──────────────────────────────────────────────────────────────────────────────
# Détection principale
# ──────────────────────────────────────────────────────────────────────────────

def find_loop_points(wav_path, tail_ratio=0.15, min_corr=0.98, verbose=True):
    """
    Trouve (loop_start, loop_end, corrélation) pour wav_path.
    Retourne None si aucun point satisfaisant n'est trouvé.

    loop_end   : passage à zéro montant dans les derniers tail_ratio du fichier
    loop_start : loop_end − N × période (N ∈ [2, 8]), même type de passage à zéro
    """
    y, sr = sf.read(wav_path, dtype='float64', always_2d=False)
    mono  = _to_mono(y)
    n     = len(mono)

    if verbose:
        print(f"  {os.path.basename(wav_path):<40s}  "
              f"{n} samples  {sr} Hz  {n/sr:.2f} s")

    # 1. Période fondamentale
    period = find_fundamental_period(y, sr)
    if period is None or period < 4:
        print(f"      → SKIP : période fondamentale non détectée")
        return None
    if verbose:
        print(f"      période : {period} samples  ({sr / period:.1f} Hz)")

    # 2. Passages à zéro montants dans les tail_ratio finaux
    tail_start = int(n * (1.0 - tail_ratio))
    zc_end     = zero_crossings_up(mono, tail_start, n - period)
    if len(zc_end) == 0:
        print(f"      → SKIP : aucun passage à zéro dans la queue")
        return None

    # 3. Chercher le meilleur couple (loop_start, loop_end)
    best_corr  = -1.0
    best_start = None
    best_end   = None
    half       = period // 4   # rayon de recherche du ZC voisin

    for loop_end in zc_end:
        for n_per in range(2, 9):
            approx_start = loop_end - n_per * period
            if approx_start < period:
                continue
            # Passage à zéro montant le plus proche de approx_start
            zc_s = zero_crossings_up(mono,
                                     approx_start - half,
                                     approx_start + half)
            if len(zc_s) == 0:
                continue
            loop_start = int(zc_s[np.argmin(np.abs(zc_s - approx_start))])
            corr = cross_correlation(mono, loop_start, loop_end, period)
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


# ──────────────────────────────────────────────────────────────────────────────
# Traitement d'un patch complet
# ──────────────────────────────────────────────────────────────────────────────

def process_patch(patch_dir, tail_ratio=0.15, min_corr=0.98, dry_run=False):
    """Analyse tous les samples d'un patch et met à jour patch.json."""
    json_path = os.path.join(patch_dir, "patch.json")
    if not os.path.exists(json_path):
        print(f"ERREUR : {json_path} introuvable")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    print(f"\n=== Patch : {meta.get('name', os.path.basename(patch_dir))} ===\n")

    found = 0
    for s in meta.get("samples", []):
        wav_path = os.path.join(patch_dir, s["file"])
        if not os.path.exists(wav_path):
            print(f"  MANQUANT : {s['file']}")
            continue
        result = find_loop_points(wav_path,
                                  tail_ratio=tail_ratio,
                                  min_corr=min_corr)
        if result:
            s["loop_start"] = result[0]
            s["loop_end"]   = result[1]
            found += 1
        else:
            # Effacer d'éventuels points précédents invalides
            s.pop("loop_start", None)
            s.pop("loop_end",   None)

    print(f"\n{found}/{len(meta.get('samples', []))} samples avec points de boucle.")

    if found > 0:
        meta["loop"] = True
    # (on ne force pas loop=False si aucun trouvé — l'utilisateur décide)

    if dry_run:
        print("(dry-run : patch.json non modifié)")
    else:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"patch.json mis à jour : {json_path}")


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Détecte les points de bouclage d'un patch multi-sample."
    )
    ap.add_argument("patch_dir",
                    help="Répertoire du patch (contenant patch.json)")
    ap.add_argument("--tail", type=float, default=0.15,
                    metavar="RATIO",
                    help="Portion finale analysée (défaut : 0.15 = 15%%)")
    ap.add_argument("--min-corr", type=float, default=0.98,
                    metavar="CORR",
                    help="Corrélation minimale acceptée (défaut : 0.98)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche les résultats sans modifier patch.json")
    args = ap.parse_args()

    process_patch(args.patch_dir,
                  tail_ratio=args.tail,
                  min_corr=args.min_corr,
                  dry_run=args.dry_run)
