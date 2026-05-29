#!/usr/bin/env python3
"""
    File: tools/extract_organ_sf2.py
    Extrait les samples d'orgue depuis un soundfont SF2 et génère un patch JSON
    compatible avec SynthEngine.

    Les samples sont extraits BRUTS depuis la banque SF2, sans passer par le
    synthétiseur FluidSynth — donc sans effets (reverb, chorus, égaliseur).
    Les loop points sont ceux du SF2, professionnellement calibrés.

    Programmes GM disponibles (--program) :
      16 : Drawbar Organ   (B3-style, le plus commun)
      17 : Percussive Organ
      18 : Rock Organ
      19 : Church Organ
      20 : Reed Organ

    Usage :
        python3 tools/extract_organ_sf2.py
        python3 tools/extract_organ_sf2.py --program 18
        python3 tools/extract_organ_sf2.py --sf2 /chemin/autre.sf2 --out /sortie
        python3 tools/extract_organ_sf2.py --dry-run

    Date: Thu, 29/05/2026
    Author: Coolbrother
"""

import os
import sys
import struct
import wave
import json
import argparse
import numpy as np

SF2_DEFAULT      = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
PATCHES_DEFAULT  = "/home/com/groovybox/PATCHS"
SAMPLES_DEFAULT  = "/home/com/groovybox/SAMPLES/SYNTHS"
PROG_DEFAULT     = 16   # Drawbar Organ

_NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
def midi_to_note(n):
    return f"{_NOTE_NAMES[n % 12]}{n // 12 - 1}"

GM_ORGANS = {
    16: "Drawbar Organ",
    17: "Percussive Organ",
    18: "Rock Organ",
    19: "Church Organ",
    20: "Reed Organ",
}


# ---------------------------------------------------------------------------
# Parser SF2 (SoundFont 2.04)
# ---------------------------------------------------------------------------

class SF2Parser:
    """
    Lit un fichier SF2 et expose les samples d'un programme GM.

    Chaîne SF2 suivie :
      PHDR (preset) → PBAG → PGEN (instrument index)
      → INST → IBAG → IGEN (sampleID, keyRange, velRange)
      → SHDR (nom, start, end, loopstart, loopend, sr, pitch)
      → smpl (audio int16 brut)
    """

    SHDR_SIZE = 46
    PHDR_SIZE = 38
    PBAG_SIZE =  4
    PGEN_SIZE =  4
    INST_SIZE = 22
    IBAG_SIZE =  4
    IGEN_SIZE =  4

    def __init__(self, path):
        with open(path, "rb") as f:
            self._data = f.read()
        self._chunks = {}
        self._parse_riff()

    # ------------------------------------------------------------------
    # Parsing RIFF
    # ------------------------------------------------------------------

    def _parse_riff(self):
        riff, size, sfbk = struct.unpack_from("<4sI4s", self._data, 0)
        assert riff == b"RIFF" and sfbk == b"sfbk", "Pas un fichier SF2 valide"
        pos = 12
        while pos < len(self._data) - 8:
            tag, sz = struct.unpack_from("<4sI", self._data, pos)
            tag = tag.decode("latin-1")
            pos += 8
            if tag == "LIST":
                self._parse_list(pos, pos + sz)
            pos += sz
            if pos % 2:
                pos += 1

    def _parse_list(self, start, end):
        pos = start + 4   # sauter le list-type (ex: "pdta", "sdta")
        while pos < end - 8:
            tag, sz = struct.unpack_from("<4sI", self._data, pos)
            tag = tag.decode("latin-1")
            pos += 8
            self._chunks[tag] = (pos, sz)
            pos += sz
            if pos % 2:
                pos += 1

    # ------------------------------------------------------------------
    # Lecture des sous-chunks pdta
    # ------------------------------------------------------------------

    def _read_phdr(self):
        start, size = self._chunks["phdr"]
        n = size // self.PHDR_SIZE
        result = []
        for i in range(n):
            o = start + i * self.PHDR_SIZE
            name = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            preset, bank, bag_idx = struct.unpack_from("<HHH", self._data, o + 20)
            result.append((name, bank, preset, bag_idx))
        return result

    def _read_pbag(self):
        start, size = self._chunks["pbag"]
        n = size // self.PBAG_SIZE
        return [struct.unpack_from("<HH", self._data, start + i * self.PBAG_SIZE)
                for i in range(n)]

    def _read_pgen(self):
        start, size = self._chunks["pgen"]
        n = size // self.PGEN_SIZE
        return [struct.unpack_from("<Hh", self._data, start + i * self.PGEN_SIZE)
                for i in range(n)]

    def _read_inst(self):
        start, size = self._chunks["inst"]
        n = size // self.INST_SIZE
        result = []
        for i in range(n):
            o = start + i * self.INST_SIZE
            name = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            bag_idx = struct.unpack_from("<H", self._data, o + 20)[0]
            result.append((name, bag_idx))
        return result

    def _read_ibag(self):
        start, size = self._chunks["ibag"]
        n = size // self.IBAG_SIZE
        return [struct.unpack_from("<HH", self._data, start + i * self.IBAG_SIZE)
                for i in range(n)]

    def _read_igen(self):
        start, size = self._chunks["igen"]
        n = size // self.IGEN_SIZE
        return [struct.unpack_from("<HH", self._data, start + i * self.IGEN_SIZE)
                for i in range(n)]

    def _read_shdr(self):
        start, size = self._chunks["shdr"]
        n = size // self.SHDR_SIZE
        result = []
        for i in range(n):
            o = start + i * self.SHDR_SIZE
            name = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            (dw_start, dw_end, dw_loopstart, dw_loopend, dw_sr,
             orig_pitch, pitch_corr, sample_link, sample_type) = \
                struct.unpack_from("<IIIIIBbHH", self._data, o + 20)
            result.append({
                "name":       name,
                "start":      dw_start,
                "end":        dw_end,
                "loopstart":  dw_loopstart,
                "loopend":    dw_loopend,
                "samplerate": dw_sr,
                "orig_pitch": orig_pitch,
                "pitch_corr": pitch_corr,
                "type":       sample_type,  # 1=mono,2=right,4=left,32768=ROM
            })
        return result

    def _read_smpl(self):
        start, size = self._chunks["smpl"]
        return np.frombuffer(self._data[start:start+size], dtype=np.int16)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def get_program_samples(self, bank=0, program=16):
        """Retourne (preset_name, [sample_dicts]) pour (bank, program)."""
        presets = self._read_phdr()
        pbags   = self._read_pbag()
        pgens   = self._read_pgen()
        insts   = self._read_inst()
        ibags   = self._read_ibag()
        igens   = self._read_igen()
        shdrs   = self._read_shdr()
        smpl    = self._read_smpl()

        # Trouver le preset ciblé
        preset_entry = None
        for idx, (name, b, p, bag_idx) in enumerate(presets):
            if b == bank and p == program:
                preset_entry = (idx, name, bag_idx)
                break
        if preset_entry is None:
            raise ValueError(f"Programme {program} (bank {bank}) introuvable")

        p_idx, preset_name, pbag_start = preset_entry
        pbag_end = presets[p_idx + 1][3]   # bag_idx du preset suivant

        # Instruments référencés par le preset
        inst_indices = set()
        for bi in range(pbag_start, pbag_end):
            gen_start = pbags[bi][0]
            gen_end   = pbags[bi + 1][0] if bi + 1 < len(pbags) else len(pgens)
            for gi in range(gen_start, gen_end):
                oper, amount = pgens[gi]
                if oper == 41:   # instrument
                    inst_indices.add(amount)

        # Samples de chaque instrument
        results = []
        seen   = set()

        for inst_idx in sorted(inst_indices):
            _, ibag_start = insts[inst_idx]
            ibag_end = insts[inst_idx + 1][1] if inst_idx + 1 < len(insts) \
                       else len(ibags)

            for bi in range(ibag_start, ibag_end):
                gen_start = ibags[bi][0]
                gen_end   = ibags[bi + 1][0] if bi + 1 < len(ibags) \
                            else len(igens)

                sample_id        = None
                key_lo, key_hi   = 0, 127
                vel_lo, vel_hi   = 0, 127

                for gi in range(gen_start, gen_end):
                    oper, amount = igens[gi]
                    if oper == 53:    sample_id = amount
                    elif oper == 43:  key_lo, key_hi = amount & 0xFF, (amount >> 8) & 0xFF
                    elif oper == 44:  vel_lo, vel_hi = amount & 0xFF, (amount >> 8) & 0xFF

                if sample_id is None or sample_id in seen:
                    continue
                if sample_id >= len(shdrs):
                    continue

                shdr = shdrs[sample_id]

                # Ignorer ROM, EOS et samples vides
                if shdr["type"] & 0x8000 or shdr["name"] == "EOS":
                    continue
                if shdr["end"] <= shdr["start"]:
                    continue

                seen.add(sample_id)
                s, e = shdr["start"], shdr["end"]
                audio = smpl[s:e].astype(np.float32) / 32768.0

                # loop_start/loop_end relatifs au début du sample
                ls = shdr["loopstart"] - s
                le = shdr["loopend"]   - s
                has_loop = (0 <= ls < le <= len(audio))

                results.append({
                    "name":       shdr["name"],
                    "orig_pitch": shdr["orig_pitch"],
                    "pitch_corr": shdr["pitch_corr"],
                    "samplerate": shdr["samplerate"],
                    "loopstart":  ls,
                    "loopend":    le,
                    "has_loop":   has_loop,
                    "key_lo":     key_lo,
                    "key_hi":     key_hi,
                    "audio":      audio,
                })

        # Trier par note fondamentale
        results.sort(key=lambda x: x["orig_pitch"])

        # Correction : quand orig_pitch == 60 (C4) pour tous les samples,
        # le SF2 stocke la note réelle dans le nom du sample (ex: "B3 A3")
        pitches = [r["orig_pitch"] for r in results]
        if len(set(pitches)) == 1 and pitches[0] == 60:
            for r in results:
                note = self._note_from_name(r["name"])
                if note is not None:
                    r["orig_pitch"] = note

        return preset_name, results

    @staticmethod
    def _note_from_name(name):
        """Tente d'extraire la note MIDI depuis le nom du sample (ex: 'B3 A3' → A3=57)."""
        import re
        notes = {"C":0,"D":2,"E":4,"F":5,"G":7,"A":9,"B":11}
        # Chercher la dernière note dans le nom (ex: "Rock Organ F5", "B3 A3")
        matches = re.findall(r'\b([A-G]#?)(\d)\b', name)
        if not matches:
            return None
        note_name, octave = matches[-1]
        base = notes.get(note_name[0])
        if base is None:
            return None
        if "#" in note_name:
            base += 1
        return 12 * (int(octave) + 1) + base


# ---------------------------------------------------------------------------
# Chunk smpl (WAV Sampler Chunk — spec RIFF, section 'smpl')
# ---------------------------------------------------------------------------

def _make_smpl_chunk(loop_start, loop_end, root_midi, samplerate):
    """Construit le contenu binaire du chunk 'smpl' (sans l'en-tête chunk).

    Structure (tous little-endian uint32) :
      Manufacturer   Product   SamplePeriod   MIDIUnityNote
      MIDIPitchFraction   SMPTEFormat   SMPTEOffset
      NumSampleLoops   SamplerData
      [Loop: CuePointID  Type  Start  End  Fraction  PlayCount]
    """
    sample_period = int(1_000_000_000 / samplerate)  # nanosecondes
    num_loops     = 1
    header = struct.pack("<IIIIIIIII",
        0,              # Manufacturer
        0,              # Product
        sample_period,  # SamplePeriod (ns)
        root_midi,      # MIDIUnityNote
        0,              # MIDIPitchFraction
        0,              # SMPTEFormat
        0,              # SMPTEOffset
        num_loops,
        0,              # SamplerData (extra bytes)
    )
    loop_rec = struct.pack("<IIIIII",
        0,          # CuePointID
        0,          # Type : 0 = forward loop
        loop_start, # Start (en échantillons)
        loop_end,   # End   (en échantillons)
        0,          # Fraction
        0,          # PlayCount : 0 = infini
    )
    return header + loop_rec


def _read_smpl_chunk(wav_path):
    """Lit le chunk 'smpl' d'un fichier WAV s'il existe.

    Retourne (root_midi, loop_start, loop_end) ou (None, None, None).
    """
    with open(wav_path, "rb") as f:
        data = f.read()

    pos = 12   # sauter RIFF header
    while pos < len(data) - 8:
        tag, sz = struct.unpack_from("<4sI", data, pos)
        pos += 8
        if tag == b"smpl" and sz >= 36:
            # Lire les champs de l'en-tête smpl
            (_, _, _, root_midi, _, _, _, num_loops, _) = \
                struct.unpack_from("<IIIIIIIII", data, pos)
            if num_loops >= 1 and sz >= 60:
                # Premier loop record (24 octets à offset 36)
                loop_off = pos + 36
                _, _, ls, le, _, _ = struct.unpack_from("<IIIIII", data, loop_off)
                return int(root_midi), int(ls), int(le)
        pos += sz
        if pos % 2:
            pos += 1
    return None, None, None


# ---------------------------------------------------------------------------
# Écriture WAV + patch.json
# ---------------------------------------------------------------------------

def save_wav(path, audio_f32, samplerate, root_midi=60,
             loop_start=None, loop_end=None):
    """Sauvegarde float32 → WAV 16-bit mono avec chunk 'smpl' si loop fourni."""
    pcm = np.clip(audio_f32 * 32767, -32768, 32767).astype(np.int16)
    pcm_bytes = pcm.tobytes()

    if loop_start is not None and loop_end is not None:
        # Construire le RIFF manuellement pour insérer le chunk smpl
        smpl_data  = _make_smpl_chunk(loop_start, loop_end, root_midi, samplerate)
        smpl_chunk = b"smpl" + struct.pack("<I", len(smpl_data)) + smpl_data

        # fmt chunk (PCM 16-bit mono)
        fmt_data  = struct.pack("<HHIIHH",
            1,          # PCM
            1,          # canaux
            samplerate,
            samplerate * 2,   # ByteRate
            2,          # BlockAlign
            16,         # BitsPerSample
        )
        fmt_chunk  = b"fmt " + struct.pack("<I", len(fmt_data)) + fmt_data
        data_chunk = b"data" + struct.pack("<I", len(pcm_bytes)) + pcm_bytes

        body = b"WAVE" + fmt_chunk + data_chunk + smpl_chunk
        with open(path, "wb") as f:
            f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    else:
        # Pas de loop : écriture standard via wave module
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(samplerate)
            w.writeframes(pcm_bytes)


def build_patch(preset_name, samples, patches_dir, samples_dir, dry_run=False):
    """
    Écrit les WAV dans samples_dir/<preset_name>/
    et le patch.json dans patches_dir/<preset_name>.json
    Les chemins dans le JSON sont absolus.
    """
    wav_dir   = os.path.join(samples_dir, preset_name.replace(" ", "_"))
    json_path = os.path.join(patches_dir, preset_name.replace(" ", "_") + ".json")

    if not dry_run:
        os.makedirs(wav_dir, exist_ok=True)
        os.makedirs(patches_dir, exist_ok=True)

    patch_samples = []

    for s in samples:
        note_name = midi_to_note(s["orig_pitch"])
        wav_name  = f"{s['name'].replace(' ', '_')}.wav"
        wav_path  = os.path.join(wav_dir, wav_name)
        loop_info = (f"loop {s['loopstart']}→{s['loopend']} "
                     f"({(s['loopend']-s['loopstart'])/s['samplerate']*1000:.0f}ms)"
                     if s["has_loop"] else "no loop")

        tag = "✓" if s["has_loop"] else "–"
        print(f"  {tag} {s['name']:35s}  root={note_name:<4}  "
              f"sr={s['samplerate']}  {loop_info}")

        if not s["has_loop"]:
            continue

        if not dry_run:
            save_wav(wav_path, s["audio"], s["samplerate"],
                     root_midi=s["orig_pitch"],
                     loop_start=s["loopstart"],
                     loop_end=s["loopend"])

        patch_samples.append({
            "file":       wav_path,    # chemin absolu
            "root":       note_name,
            "loop_start": s["loopstart"],
            "loop_end":   s["loopend"],
        })

    patch = {
        "name":       preset_name,
        "loop":       True,
        "loop_start": None,
        "loop_end":   None,
        "samples":    patch_samples,
    }

    if not dry_run:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(patch, f, indent=2, ensure_ascii=False)

    status = "(dry-run) " if dry_run else ""
    print(f"\n{status}WAV     → {wav_dir}/")
    print(f"{status}patch   → {json_path}")
    print(f"{status}total   : {len(patch_samples)} samples avec loop")
    return json_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Extrait les samples d'orgue GM depuis un SF2 (sans effets)."
    )
    ap.add_argument("--sf2",     default=SF2_DEFAULT,
                    help=f"Fichier SF2 (défaut : {SF2_DEFAULT})")
    ap.add_argument("--program", type=int, default=PROG_DEFAULT,
                    choices=list(GM_ORGANS),
                    help="Programme GM : " + str(GM_ORGANS))
    ap.add_argument("--patches", default=PATCHES_DEFAULT,
                    help=f"Répertoire des patch.json (défaut : {PATCHES_DEFAULT})")
    ap.add_argument("--samples", default=SAMPLES_DEFAULT,
                    help=f"Répertoire racine des WAV (défaut : {SAMPLES_DEFAULT})")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche sans écrire de fichiers")
    args = ap.parse_args()

    if not os.path.isfile(args.sf2):
        print(f"SF2 introuvable : {args.sf2}")
        sys.exit(1)

    print(f"\nSF2     : {args.sf2}")
    print(f"Programme {args.program} : {GM_ORGANS[args.program]}\n")

    parser = SF2Parser(args.sf2)
    preset_name, samples = parser.get_program_samples(bank=0, program=args.program)

    print(f"Preset  : {preset_name!r}  ({len(samples)} samples)\n")

    print(f"WAV     : {args.samples}/<preset>/")
    print(f"Patch   : {args.patches}/<preset>.json\n")
    build_patch(preset_name, samples, args.patches, args.samples,
                dry_run=args.dry_run)


if __name__ == "__main__":
    main()
