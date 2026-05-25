#!/usr/bin/env python3
"""
    File: tools/extract_gm_drums.py
    Extrait tous les sons de batterie GM (notes 35-81) depuis un soundfont SF2
    en utilisant fluidsynth, et génère le fichier kit JSON correspondant.

    Usage:
        python3 tools/extract_gm_drums.py
        python3 tools/extract_gm_drums.py --sf2 /chemin/vers/soundfont.sf2
        python3 tools/extract_gm_drums.py --out /répertoire/de/sortie
        python3 tools/extract_gm_drums.py --duration 3000

    Date: Mon, 26/05/2026
    Author: Coolbrother
"""
import os
import sys
import json
import argparse
import subprocess
import tempfile

# ──────────────────────────────────────────────
# Table complète GM drums (notes 35–81)
# ──────────────────────────────────────────────
GM_DRUMS = {
    35: "Bass_Drum_2",
    36: "Bass_Drum_1",
    37: "Side_Stick",
    38: "Snare_1",
    39: "Hand_Clap",
    40: "Snare_2",
    41: "Low_Floor_Tom",
    42: "HH_Closed",
    43: "High_Floor_Tom",
    44: "HH_Pedal",
    45: "Low_Tom",
    46: "HH_Open",
    47: "Low_Mid_Tom",
    48: "Hi_Mid_Tom",
    49: "Crash_1",
    50: "High_Tom",
    51: "Ride_1",
    52: "Chinese_Cymbal",
    53: "Ride_Bell",
    54: "Tambourine",
    55: "Splash_Cymbal",
    56: "Cowbell",
    57: "Crash_2",
    58: "Vibraslap",
    59: "Ride_2",
    60: "Hi_Bongo",
    61: "Low_Bongo",
    62: "Mute_Hi_Conga",
    63: "Open_Hi_Conga",
    64: "Low_Conga",
    65: "High_Timbale",
    66: "Low_Timbale",
    67: "High_Agogo",
    68: "Low_Agogo",
    69: "Cabasa",
    70: "Maracas",
    71: "Short_Whistle",
    72: "Long_Whistle",
    73: "Short_Guiro",
    74: "Long_Guiro",
    75: "Claves",
    76: "Hi_Wood_Block",
    77: "Low_Wood_Block",
    78: "Mute_Cuica",
    79: "Open_Cuica",
    80: "Mute_Triangle",
    81: "Open_Triangle",
}

SF2_DEFAULT    = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
OUT_DEFAULT    = "/home/com/groovybox/samples/DRUMS/gm"
KITS_DEFAULT   = "/home/com/groovybox/KITS"
DURATION_MS    = 3000    # durée de rendu par note (ms)
SAMPLE_RATE    = 44100


def render_note(sf2_path, note, out_wav, duration_ms, sample_rate):
    """Rend une note MIDI (canal 9 = GM drums) vers un fichier WAV."""
    commands = (
        f"noteon 9 {note} 127\n"
        f"sleep {duration_ms}\n"
        f"noteoff 9 {note}\n"
        f"quit\n"
    )
    result = subprocess.run(
        [
            "fluidsynth",
            "-o", f"audio.driver=file",
            "-o", f"audio.file.name={out_wav}",
            "-o", "audio.file.type=wav",
            "-r", str(sample_rate),
            "-q", "-n",
            sf2_path,
        ],
        input=commands.encode(),
        capture_output=True,
    )
    return result.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 44


def main():
    parser = argparse.ArgumentParser(description="Extrait les sons GM drums depuis un SF2.")
    parser.add_argument("--sf2",      default=SF2_DEFAULT,  help="Chemin du soundfont SF2")
    parser.add_argument("--out",      default=OUT_DEFAULT,   help="Répertoire de sortie des WAVs")
    parser.add_argument("--kits",     default=KITS_DEFAULT,  help="Répertoire des fichiers kit JSON")
    parser.add_argument("--duration", default=DURATION_MS,   type=int,
                        help="Durée de rendu par note en ms (défaut: 3000)")
    parser.add_argument("--rate",     default=SAMPLE_RATE,   type=int,
                        help="Fréquence d'échantillonnage (défaut: 44100)")
    args = parser.parse_args()

    if not os.path.isfile(args.sf2):
        print(f"Erreur: soundfont introuvable: {args.sf2}")
        sys.exit(1)

    os.makedirs(args.out,  exist_ok=True)
    os.makedirs(args.kits, exist_ok=True)

    sf2_name = os.path.splitext(os.path.basename(args.sf2))[0]
    print(f"Soundfont : {args.sf2}")
    print(f"Sortie WAV: {args.out}")
    print(f"Durée/note: {args.duration} ms\n")

    extracted = []   # [(note, name, wav_filename)]
    failed    = []

    total = len(GM_DRUMS)
    for i, (note, name) in enumerate(sorted(GM_DRUMS.items()), 1):
        wav_name = f"{note}_{name}.wav"
        out_wav  = os.path.join(args.out, wav_name)
        print(f"[{i:02d}/{total}] note {note:02d} — {name} ... ", end="", flush=True)

        ok = render_note(args.sf2, note, out_wav, args.duration, args.rate)
        if ok:
            size_kb = os.path.getsize(out_wav) // 1024
            print(f"OK ({size_kb} Ko)")
            extracted.append((note, name, wav_name))
        else:
            print("ÉCHEC")
            failed.append((note, name))

    # ── Génération du kit JSON ──────────────────────────────────────────
    kit_name    = f"GM ({sf2_name})"
    json_name   = "gm.json"
    json_path   = os.path.join(args.kits, json_name)
    wav_rel_dir = os.path.relpath(args.out, args.kits)

    pads = []
    for note, name, wav_name in extracted:
        label = name.replace("_", " ")
        pads.append({
            "note":     note,
            "filename": f"{wav_rel_dir}/{wav_name}".replace("\\", "/"),
            "label":    label,
        })

    kit = {"name": kit_name, "pads": pads}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(kit, f, indent=2, ensure_ascii=False)

    # ── Résumé ─────────────────────────────────────────────────────────
    print(f"\n{'─' * 50}")
    print(f"Extraits : {len(extracted)}/{total}")
    if failed:
        print(f"Échecs   : {[f'{n} {nm}' for n,nm in failed]}")
    print(f"Kit JSON : {json_path}")
    print(f"{'─' * 50}")


if __name__ == "__main__":
    main()
