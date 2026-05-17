#python3
"""
    File: tools/find_loop_points.py
    Détecte les points de bouclage (loop_start, loop_end) dans les samples
    WAV d'un patch et met à jour patch.json.
    La logique de détection est dans src/audio_tools.AudioTools.

    Usage :
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast --dry-run
      python3 tools/find_loop_points.py synths/Organ_B3_Basic_Fast --tail 0.20 --min-corr 0.95

    Date: Sun, 17/05/2026
    Author: Coolbrother
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from audio_tools import AudioTools


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
        result = AudioTools.find_loop_points(wav_path,
                                             tail_ratio=tail_ratio,
                                             min_corr=min_corr)
        if result:
            s["loop_start"] = result[0]
            s["loop_end"]   = result[1]
            found += 1
        else:
            s.pop("loop_start", None)
            s.pop("loop_end",   None)

    print(f"\n{found}/{len(meta.get('samples', []))} samples avec points de boucle.")

    if found > 0:
        meta["loop"] = True

    if dry_run:
        print("(dry-run : patch.json non modifié)")
    else:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"patch.json mis à jour : {json_path}")


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
