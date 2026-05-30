#!/usr/bin/env python3
"""
    File: tools/find_loop_points.py
    Détecte les points de bouclage dans les samples WAV d'un patch
    et les embarque directement dans le chunk 'smpl' de chaque WAV.

    Nouvelle stratégie (v2) :
      - Fixer loop_start dans la zone sustain (25-80% du fichier)
      - Chercher loop_end = zéro montant le plus proche de
        loop_start + n×période → frac_period minimal garanti
      - Scorer par corr_loop (2 périodes à la jonction)

    Usage :
      # Sur un répertoire de patch (patch.json requis)
      python3 tools/find_loop_points.py /chemin/vers/patch_dir
      python3 tools/find_loop_points.py /chemin/vers/patch_dir --dry-run

      # Sur un fichier WAV individuel
      python3 tools/find_loop_points.py /chemin/vers/sample.wav
      python3 tools/find_loop_points.py /chemin/vers/sample.wav --dry-run

      # Ajuster les paramètres
      python3 tools/find_loop_points.py /chemin --sustain-start 0.30 \\
              --sustain-end 0.75 --min-corr 0.85

    Date: Sat, 30/05/2026
    Author: Coolbrother
"""

import os
import sys
import json
import struct
import argparse
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from audio_tools import AudioTools


# ---------------------------------------------------------------------------
# Chunk smpl (réutilisé depuis extract_instruments_sf2.py)
# ---------------------------------------------------------------------------

def _embed_smpl(wav_path, root_midi, loop_start, loop_end, samplerate):
    """Embarque (ou remplace) le chunk smpl dans un WAV existant."""
    with open(wav_path, "rb") as f:
        original = f.read()

    sample_period = int(1_000_000_000 / samplerate)
    smpl_data  = struct.pack("<IIIIIIIII",
        0, 0, sample_period, root_midi, 0, 0, 0, 1, 0)
    smpl_data += struct.pack("<IIIIII", 0, 0, loop_start, loop_end, 0, 0)

    # Reconstruire le RIFF en excluant tout smpl existant
    chunks = bytearray(b"WAVE")
    pos = 12
    while pos < len(original) - 8:
        tag, sz = struct.unpack_from("<4sI", original, pos)
        pos += 8
        if tag != b"smpl":
            chunks += tag + struct.pack("<I", sz) + original[pos:pos + sz]
            if sz % 2:
                chunks += b"\x00"
        pos += sz
        if pos % 2:
            pos += 1

    chunks += b"smpl" + struct.pack("<I", len(smpl_data)) + smpl_data

    with open(wav_path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(chunks)) + bytes(chunks))


# ---------------------------------------------------------------------------
# Traitement d'un WAV individuel
# ---------------------------------------------------------------------------

def process_wav(wav_path, root_midi=60,
                sustain_start=0.25, sustain_end=0.80,
                min_loop_ms=100, max_loop_ms=3000,
                min_corr=0.90, dry_run=False):
    """Détecte les loop points d'un WAV et embarque le chunk smpl."""
    result = AudioTools.find_loop_points(
        wav_path,
        sustain_start = sustain_start,
        sustain_end   = sustain_end,
        min_loop_ms   = min_loop_ms,
        max_loop_ms   = max_loop_ms,
        min_corr      = min_corr,
        verbose       = True,
    )
    if result is None:
        return None

    ls, le, corr = result

    if not dry_run:
        # Lire le samplerate depuis le WAV
        import soundfile as sf
        _, sr = sf.read(wav_path, dtype='float32')
        _embed_smpl(wav_path, root_midi, ls, le, sr)
        print(f"      → chunk smpl embarqué dans {os.path.basename(wav_path)}")
    else:
        print("      → (dry-run : fichier non modifié)")

    return ls, le, corr


# ---------------------------------------------------------------------------
# Traitement d'un répertoire de patch
# ---------------------------------------------------------------------------

def process_patch(patch_path, sustain_start=0.25, sustain_end=0.80,
                  min_loop_ms=100, max_loop_ms=3000,
                  min_corr=0.90, dry_run=False, json_only=False):
    """Analyse tous les WAV d'un patch.json et met à jour le JSON + les smpl."""
    import soundfile as sf
    from synth_engine import note_name_to_midi

    # patch_path peut être un répertoire ou le JSON directement
    if os.path.isdir(patch_path):
        json_path = os.path.join(patch_path, "patch.json")
    else:
        json_path = patch_path
        patch_path = os.path.dirname(patch_path)

    if not os.path.exists(json_path):
        # Pas de patch.json → chercher les WAVs dans le répertoire
        wavs = sorted(glob.glob(os.path.join(patch_path, "*.wav")))
        if not wavs:
            print(f"Aucun WAV trouvé dans : {patch_path}")
            sys.exit(1)
        print(f"\n=== Répertoire (sans patch.json) : {patch_path} ===\n")
        found = 0
        for wav_path in wavs:
            r = process_wav(wav_path, root_midi=60,
                            sustain_start=sustain_start,
                            sustain_end=sustain_end,
                            min_loop_ms=min_loop_ms,
                            max_loop_ms=max_loop_ms,
                            min_corr=min_corr,
                            dry_run=dry_run)
            if r:
                found += 1
        print(f"\n{found}/{len(wavs)} samples avec points de boucle.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    print(f"\n=== Patch : {meta.get('name', os.path.basename(patch_path))} ===\n")

    sounds = meta.get("sounds", meta.get("samples", []))
    found  = 0

    for s in sounds:
        filename = s.get("filename", s.get("file", ""))
        wav_path = filename if os.path.isabs(filename) \
                   else os.path.join(patch_path, filename)

        if not os.path.exists(wav_path):
            print(f"  MANQUANT : {filename}")
            continue

        # Deviner la note root depuis le champ du JSON ou le nom du fichier
        rootnote = s.get("rootnote", s.get("root", ""))
        try:
            root_midi = note_name_to_midi(rootnote) if rootnote else 60
        except Exception:
            root_midi = 60

        _, sr_file = sf.read(wav_path, dtype='float32')
        result = AudioTools.find_loop_points(
            wav_path,
            sustain_start = sustain_start,
            sustain_end   = sustain_end,
            min_loop_ms   = min_loop_ms,
            max_loop_ms   = max_loop_ms,
            min_corr      = min_corr,
            verbose       = True,
        )

        if result:
            ls, le, corr = result
            s["loop_start"] = ls
            s["loop_end"]   = le
            found += 1
            if not dry_run and not json_only:
                _embed_smpl(wav_path, root_midi, ls, le, sr_file)
                print(f"      → smpl embarqué")
        else:
            s.pop("loop_start", None)
            s.pop("loop_end",   None)

    print(f"\n{found}/{len(sounds)} samples avec points de boucle.")

    if found > 0:
        meta["loop"] = True

    if dry_run:
        print("(dry-run : patch.json et WAVs non modifiés)")
    elif json_only:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"patch.json mis à jour (WAVs non modifiés) : {json_path}")
    else:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(f"patch.json mis à jour : {json_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Détecte les points de bouclage et embarque le chunk smpl dans les WAVs."
    )
    ap.add_argument("path",
                    help="Répertoire de patch, chemin patch.json, ou fichier WAV")

    ap.add_argument("--sustain-start", type=float, default=0.25,
                    metavar="RATIO",
                    help="Début zone sustain pour loop_start (défaut 0.25 = 25%%)")
    ap.add_argument("--sustain-end",   type=float, default=0.80,
                    metavar="RATIO",
                    help="Fin zone sustain pour loop_end (défaut 0.80 = 80%%)")
    ap.add_argument("--min-loop-ms",   type=float, default=100,
                    metavar="MS",
                    help="Durée minimale de boucle en ms (défaut 100)")
    ap.add_argument("--max-loop-ms",   type=float, default=3000,
                    metavar="MS",
                    help="Durée maximale de boucle en ms (défaut 3000)")
    ap.add_argument("--min-corr",      type=float, default=0.90,
                    metavar="CORR",
                    help="Corrélation minimale acceptée (défaut 0.90)")
    ap.add_argument("--dry-run",       action="store_true",
                    help="Affiche les résultats sans modifier les fichiers")
    ap.add_argument("--json-only",     action="store_true",
                    help="Met à jour le patch.json sans modifier les WAVs")

    # Rétrocompat avec l'ancien paramètre --tail
    ap.add_argument("--tail", type=float, default=None,
                    help=argparse.SUPPRESS)

    args = ap.parse_args()

    kwargs = dict(
        sustain_start = args.sustain_start,
        sustain_end   = args.sustain_end,
        min_loop_ms   = args.min_loop_ms,
        max_loop_ms   = args.max_loop_ms,
        min_corr      = args.min_corr,
        dry_run       = args.dry_run,
        json_only     = args.json_only,
    )

    path = args.path
    if path.endswith(".wav"):
        wav_kwargs = {k: v for k, v in kwargs.items() if k != "json_only"}
        process_wav(path, **wav_kwargs)
    else:
        process_patch(path, **kwargs)
