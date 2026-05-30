#!/usr/bin/env python3
"""
    File: tools/extract_instruments_sf2.py
    Exportation d'instruments SF2 en WAV via FluidSynth.
    Génère un patch JSON compatible avec SynthEngine.

    Usage :
        # Lister les presets disponibles
        python3 tools/extract_instruments_sf2.py --list
        python3 tools/extract_instruments_sf2.py --list --bank 0

        # Exporter un instrument
        python3 tools/extract_instruments_sf2.py --bank 0 --preset 16
        python3 tools/extract_instruments_sf2.py --bank 0 --preset 48 \\
            --start C2 --stop C6 --duration 4 --folder String_Ensemble

        # Dry-run (affiche sans exporter)
        python3 tools/extract_instruments_sf2.py --bank 0 --preset 19 --dry-run

    Date: Sat, 30/05/2026
    Author: Coolbrother
"""

import os
import sys
import struct
import json
import wave
import tempfile
import argparse
import subprocess
import numpy as np

SF2_DEFAULT     = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
PATCHES_DEFAULT = "/home/com/groovybox/PATCHS"
SAMPLES_DEFAULT = "/home/com/groovybox/SAMPLES/SYNTHS"

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_MAP   = {"Db": "C#", "Eb": "D#", "Fb": "E",  "Gb": "F#",
               "Ab": "G#", "Bb": "A#", "Cb": "B"}


# ---------------------------------------------------------------------------
# Utilitaires note ↔ MIDI
# ---------------------------------------------------------------------------

def note_to_midi(name: str) -> int:
    """'A0'→21, 'C4'→60, 'C8'→108. Accepte dièses (#) et bémols (b)."""
    name = name.strip()
    for flat, sharp in _FLAT_MAP.items():
        if name.upper().startswith(flat.upper()):
            name = sharp + name[len(flat):]
            break
    if len(name) >= 3 and name[1] == "#":
        note, octave = name[:2], int(name[2:])
    else:
        note, octave = name[0].upper(), int(name[1:])
    return 12 * (octave + 1) + _NOTE_NAMES.index(note)


def midi_to_note(n: int) -> str:
    return f"{_NOTE_NAMES[n % 12]}{n // 12 - 1}"


# ---------------------------------------------------------------------------
# MIDI file minimal (format 0, 1 piste, 1 note)
# ---------------------------------------------------------------------------

def _vlq(n: int) -> bytes:
    """Variable-length quantity encoding (MIDI)."""
    if n < 0x80:
        return bytes([n])
    chunks = []
    while n:
        chunks.append(n & 0x7F)
        n >>= 7
    chunks.reverse()
    for i in range(len(chunks) - 1):
        chunks[i] |= 0x80
    return bytes(chunks)


def _write_midi(path: str, bank: int, preset: int, note: int,
                velocity: int, duration_s: float, decay_s: float,
                bpm: int = 80):
    """Écrit un fichier MIDI format 0 qui joue une seule note."""
    tpb          = 480                      # ticks par noire
    us_per_beat  = 60_000_000 // bpm
    ticks_per_s  = tpb * bpm / 60.0
    dur_ticks    = int(duration_s * ticks_per_s)
    decay_ticks  = int(decay_s    * ticks_per_s)

    events = bytearray()

    # Tempo
    events += b"\x00\xFF\x51\x03"
    events += struct.pack(">I", us_per_beat)[1:]   # 3 octets

    # Bank select MSB (CC 0)
    events += b"\x00\xB0\x00" + bytes([min(127, bank >> 7)])
    # Bank select LSB (CC 32)
    events += b"\x00\xB0\x20" + bytes([bank & 0x7F])
    # Program change
    events += b"\x00\xC0" + bytes([preset & 0x7F])
    # Note on
    events += b"\x00\x90" + bytes([note & 0x7F, velocity & 0x7F])
    # Durée
    events += _vlq(dur_ticks)
    # Note off
    events += b"\x80" + bytes([note & 0x7F, 0x00])
    # Decay
    events += _vlq(decay_ticks)
    # End of track
    events += b"\xFF\x2F\x00"

    track_data = bytes(events)
    header = b"MThd\x00\x00\x00\x06\x00\x00\x00\x01" + struct.pack(">H", tpb)
    track  = b"MTrk" + struct.pack(">I", len(track_data)) + track_data

    with open(path, "wb") as f:
        f.write(header + track)


# ---------------------------------------------------------------------------
# Chunk smpl WAV
# ---------------------------------------------------------------------------

def _make_smpl_chunk(loop_start: int, loop_end: int,
                     root_midi: int, samplerate: int) -> bytes:
    sample_period = int(1_000_000_000 / samplerate)
    header = struct.pack("<IIIIIIIII",
        0, 0, sample_period, root_midi, 0, 0, 0, 1, 0)
    loop_rec = struct.pack("<IIIIII", 0, 0, loop_start, loop_end, 0, 0)
    return header + loop_rec


def _embed_smpl(wav_path: str, root_midi: int,
                loop_start: int, loop_end: int, samplerate: int):
    """Relit le WAV et lui ajoute (ou remplace) le chunk smpl."""
    with open(wav_path, "rb") as f:
        original = f.read()

    # Extraire les chunks existants sauf smpl
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

    smpl_data = _make_smpl_chunk(loop_start, loop_end, root_midi, samplerate)
    chunks += b"smpl" + struct.pack("<I", len(smpl_data)) + smpl_data

    with open(wav_path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(chunks)) + bytes(chunks))


# ---------------------------------------------------------------------------
# SF2 Parser minimal (loop points par note)
# ---------------------------------------------------------------------------

class _SF2LoopFinder:
    """Lit les SHDR du SF2 pour récupérer les loop points d'un sample donné."""

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
        self._parse()

    def _parse(self):
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
        pos = start + 4
        while pos < end - 8:
            tag, sz = struct.unpack_from("<4sI", self._data, pos)
            tag = tag.decode("latin-1")
            pos += 8
            self._chunks[tag] = (pos, sz)
            pos += sz
            if pos % 2:
                pos += 1

    def _read(self, chunk, size, fmt):
        start, total = self._chunks[chunk]
        n = total // size
        return [struct.unpack_from(fmt, self._data, start + i * size)
                for i in range(n)]

    def get_loop_for_note(self, bank: int, preset: int, note: int):
        """Retourne (loop_start, loop_end, samplerate) ou None."""
        try:
            phdrs = self._read_phdr()
            pbags = self._read("pbag", self.PBAG_SIZE, "<HH")
            pgens = self._read("pgen", self.PGEN_SIZE, "<Hh")
            insts = self._read_inst()
            ibags = self._read("ibag", self.IBAG_SIZE, "<HH")
            igens = self._read("igen", self.IGEN_SIZE, "<Hh")
            shdrs = self._read_shdr()
        except KeyError:
            return None

        # Trouver le preset
        target = None
        for idx, (nm, b, p, bag) in enumerate(phdrs):
            if b == bank and p == preset:
                target = (idx, bag)
                break
        if target is None:
            return None

        p_idx, pbag_start = target
        pbag_end = phdrs[p_idx + 1][3]

        inst_indices = set()
        for bi in range(pbag_start, pbag_end):
            gs, ge = pbags[bi][0], pbags[bi + 1][0] if bi + 1 < len(pbags) else len(pgens)
            for gi in range(gs, ge):
                if pgens[gi][0] == 41:
                    inst_indices.add(pgens[gi][1])

        for inst_idx in sorted(inst_indices):
            _, ibag_start = insts[inst_idx]
            ibag_end = insts[inst_idx + 1][1] if inst_idx + 1 < len(insts) else len(ibags)
            for bi in range(ibag_start, ibag_end):
                gs, ge = ibags[bi][0], ibags[bi + 1][0] if bi + 1 < len(ibags) else len(igens)
                sample_id = None
                key_lo, key_hi = 0, 127
                for gi in range(gs, ge):
                    op, am = igens[gi]
                    if op == 53: sample_id = am
                    elif op == 43: key_lo, key_hi = am & 0xFF, (am >> 8) & 0xFF
                if sample_id is None or not (key_lo <= note <= key_hi):
                    continue
                if sample_id >= len(shdrs):
                    continue
                shdr = shdrs[sample_id]
                if shdr["type"] & 0x8000 or shdr["name"] == "EOS":
                    continue
                s = shdr["start"]
                ls = shdr["loopstart"] - s
                le = shdr["loopend"]   - s
                if ls >= 0 and le > ls:
                    return ls, le, shdr["samplerate"]
        return None

    def _read_phdr(self):
        start, size = self._chunks["phdr"]
        result = []
        for i in range(size // self.PHDR_SIZE):
            o = start + i * self.PHDR_SIZE
            nm = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            preset, bank, bag = struct.unpack_from("<HHH", self._data, o + 20)
            result.append((nm, bank, preset, bag))
        return result

    def _read_inst(self):
        start, size = self._chunks["inst"]
        result = []
        for i in range(size // self.INST_SIZE):
            o = start + i * self.INST_SIZE
            nm = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            bag = struct.unpack_from("<H", self._data, o + 20)[0]
            result.append((nm, bag))
        return result

    def _read_shdr(self):
        start, size = self._chunks["shdr"]
        result = []
        for i in range(size // self.SHDR_SIZE):
            o = start + i * self.SHDR_SIZE
            nm = self._data[o:o+20].split(b"\x00")[0].decode("latin-1")
            (ds, de, dls, dle, sr, op, pc, sl, st) = \
                struct.unpack_from("<IIIIIBbHH", self._data, o + 20)
            result.append({"name": nm, "start": ds, "end": de,
                           "loopstart": dls, "loopend": dle,
                           "samplerate": sr, "orig_pitch": op, "type": st})
        return result

    def list_presets(self):
        """Retourne [(bank, preset, name)] triés."""
        phdrs = self._read_phdr()
        result = [(b, p, nm) for nm, b, p, _ in phdrs if nm != "EOP"]
        return sorted(result)


# ---------------------------------------------------------------------------
# SF2Loader
# ---------------------------------------------------------------------------

class SF2Loader:
    """
    Chargeur SF2 — exporte des instruments en WAV via FluidSynth.

    Usage :
        loader = SF2Loader("/usr/share/sounds/sf2/FluidR3_GM.sf2")
        loader.list_presets()
        loader.export_instruments(bank=0, preset=19, start='C2', stop='C6',
                                  duration=6, folder_name='Church_Organ')
    """

    def __init__(self, sf2_path: str,
                 patches_dir: str = PATCHES_DEFAULT,
                 samples_dir: str = SAMPLES_DEFAULT):
        if not os.path.isfile(sf2_path):
            raise FileNotFoundError(f"SF2 introuvable : {sf2_path}")
        self.sf2_path    = os.path.abspath(sf2_path)
        self.patches_dir = patches_dir
        self.samples_dir = samples_dir
        self._finder     = _SF2LoopFinder(self.sf2_path)

    # ------------------------------------------------------------------

    def list_presets(self, bank: int = None):
        """Affiche et retourne la liste des presets disponibles."""
        presets = self._finder.list_presets()
        if bank is not None:
            presets = [(b, p, nm) for b, p, nm in presets if b == bank]
        print(f"\n{'Bank':>5}  {'Preset':>6}  Nom")
        print("─" * 40)
        for b, p, nm in presets:
            print(f"{b:>5}  {p:>6}  {nm}")
        print(f"{'─'*40}\n{len(presets)} preset(s)\n")
        return presets

    # ------------------------------------------------------------------

    def export_instruments(self,
                           file_path: str  = None,
                           bank: int       = 0,
                           preset: int     = 0,
                           start: str      = "A0",
                           stop: str       = "C8",
                           duration: float = 6,
                           decay: float    = 1,
                           volume: int     = 127,
                           sample_width: int = 2,
                           channels: int   = 2,
                           frame_rate: int = 44100,
                           format: str     = "wav",
                           folder_name: str = "Untitled",
                           bpm: int        = 80,
                           name: str       = None,
                           effects: bool   = False,
                           dry_run: bool   = False,
                           **kwargs):
        """
        Exporte chaque note de [start, stop] en WAV via FluidSynth.

        Paramètres principaux
        ---------------------
        file_path   : chemin du SF2 (remplace self.sf2_path si fourni)
        bank        : numéro de banque MIDI (défaut 0)
        preset      : numéro de preset MIDI (défaut 0)
        start / stop: plage de notes (ex. 'A0'–'C8')
        duration    : durée de tenue en secondes
        decay       : durée de release en secondes
        volume      : vélocité MIDI (0–127)
        channels    : 1=mono, 2=stéréo
        frame_rate  : fréquence d'échantillonnage Hz
        format      : 'wav' uniquement
        folder_name : nom du sous-répertoire dans samples_dir
        name        : nom du patch (défaut = nom SF2 du preset)
        effects     : True = reverb/chorus FluidSynth activés (défaut False)
        dry_run     : affiche sans exporter
        """
        sf2 = os.path.abspath(file_path) if file_path else self.sf2_path

        midi_lo = note_to_midi(start)
        midi_hi = note_to_midi(stop)
        if midi_lo > midi_hi:
            midi_lo, midi_hi = midi_hi, midi_lo

        notes = list(range(midi_lo, midi_hi + 1))

        # Répertoires de sortie
        wav_dir   = os.path.join(self.samples_dir, folder_name)
        json_name = (name or folder_name).replace(" ", "_") + ".json"
        json_path = os.path.join(self.patches_dir, json_name)

        if not dry_run:
            os.makedirs(wav_dir, exist_ok=True)
            os.makedirs(self.patches_dir, exist_ok=True)

        print(f"\nSF2     : {sf2}")
        print(f"Preset  : bank={bank}  preset={preset}")
        print(f"Plage   : {start} (MIDI {midi_lo}) → {stop} (MIDI {midi_hi})"
              f"  ({len(notes)} notes)")
        print(f"WAV     : {wav_dir}/")
        print(f"Patch   : {json_path}")
        print(f"Options : duration={duration}s  decay={decay}s"
              f"  vol={volume}  {channels}ch  {frame_rate}Hz"
              f"  effects={'on' if effects else 'off'}\n")

        patch_samples = []
        has_loop      = False

        with tempfile.TemporaryDirectory() as tmp:
            for midi_note in notes:
                note_name = midi_to_note(midi_note)
                wav_name  = f"{note_name.replace('#', 's')}.wav"
                wav_path  = os.path.join(wav_dir, wav_name)
                midi_path = os.path.join(tmp, "note.mid")

                # Chercher les loop points SF2 pour cette note
                loop_info = self._finder.get_loop_for_note(bank, preset, midi_note)
                loop_tag  = f"loop {loop_info[0]}→{loop_info[1]}" \
                            if loop_info else "one-shot"
                print(f"  {note_name:<4} (MIDI {midi_note:3d})  {loop_tag}",
                      end="", flush=True)

                if dry_run:
                    print("  [dry-run]")
                    continue

                # Écrire le fichier MIDI
                _write_midi(midi_path, bank, preset, midi_note,
                            volume, duration, decay, bpm)

                # Lancer FluidSynth
                cmd = [
                    "fluidsynth", "-ni",
                    "-g", "1",
                    "-r", str(frame_rate),
                    "-F", wav_path,
                ]
                if not effects:
                    cmd += ["-o", "synth.reverb.active=0",
                            "-o", "synth.chorus.active=0"]
                cmd += [sf2, midi_path]

                result = subprocess.run(cmd, capture_output=True)
                if result.returncode != 0 or not os.path.isfile(wav_path):
                    print(f"  [ERREUR FluidSynth]")
                    continue

                # Convertir mono si demandé
                if channels == 1:
                    self._to_mono(wav_path, frame_rate, sample_width)

                # Embarquer les loop points dans le chunk smpl
                if loop_info:
                    ls, le, _ = loop_info
                    _embed_smpl(wav_path, midi_note, ls, le, frame_rate)
                    has_loop = True

                print(f"  ✓")
                patch_samples.append({
                    "file": wav_path,
                    "root": note_name,
                    **({"loop_start": loop_info[0],
                        "loop_end":   loop_info[1]} if loop_info else {}),
                })

        if dry_run:
            print(f"\n(dry-run) {len(notes)} notes — rien écrit.")
            return None

        # Écrire le patch JSON
        patch = {
            "name":       name or folder_name,
            "loop":       has_loop,
            "loop_start": None,
            "loop_end":   None,
            "samples":    patch_samples,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(patch, f, indent=2, ensure_ascii=False)

        print(f"\n→ {len(patch_samples)} notes exportées")
        print(f"→ patch : {json_path}")
        return json_path

    # ------------------------------------------------------------------

    @staticmethod
    def _to_mono(wav_path: str, frame_rate: int, sample_width: int):
        """Convertit un WAV stéréo en mono (moyenne L+R)."""
        with wave.open(wav_path, "rb") as w:
            nch = w.getnchannels()
            if nch == 1:
                return
            raw = w.readframes(w.getnframes())
        dtype = np.int16 if sample_width == 2 else np.int8
        data  = np.frombuffer(raw, dtype=dtype).reshape(-1, nch)
        mono  = data.mean(axis=1).astype(dtype)
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(sample_width)
            w.setframerate(frame_rate)
            w.writeframes(mono.tobytes())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Exportation d'instruments SF2 en WAV via FluidSynth."
    )
    ap.add_argument("--sf2",     default=SF2_DEFAULT,
                    help=f"Fichier SF2 (défaut : {SF2_DEFAULT})")
    ap.add_argument("--patches", default=PATCHES_DEFAULT,
                    help="Répertoire des patch JSON")
    ap.add_argument("--samples", default=SAMPLES_DEFAULT,
                    help="Répertoire racine des WAV")

    ap.add_argument("--list",    action="store_true",
                    help="Lister les presets disponibles")
    ap.add_argument("--bank",    type=int, default=0)
    ap.add_argument("--preset",  type=int, default=0)
    ap.add_argument("--start",   default="A0")
    ap.add_argument("--stop",    default="C8")
    ap.add_argument("--duration",type=float, default=6)
    ap.add_argument("--decay",   type=float, default=1)
    ap.add_argument("--volume",  type=int,   default=127)
    ap.add_argument("--channels",type=int,   default=2, choices=[1, 2])
    ap.add_argument("--rate",    type=int,   default=44100, dest="frame_rate")
    ap.add_argument("--folder",  default=None,  dest="folder_name",
                    help="Nom du dossier de sortie (défaut : nom du preset)")
    ap.add_argument("--name",    default=None,
                    help="Nom du patch JSON (défaut : folder)")
    ap.add_argument("--effects", action="store_true",
                    help="Activer reverb/chorus FluidSynth (défaut : off)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    loader = SF2Loader(args.sf2, args.patches, args.samples)

    if args.list:
        loader.list_presets(bank=args.bank if args.bank else None)
        return

    # Déterminer le nom du preset pour folder_name par défaut
    presets = loader._finder.list_presets()
    preset_name = next((nm for b, p, nm in presets
                        if b == args.bank and p == args.preset), None)
    folder = args.folder_name or (preset_name.replace(" ", "_")
                                  if preset_name else f"bank{args.bank}_preset{args.preset}")

    loader.export_instruments(
        bank        = args.bank,
        preset      = args.preset,
        start       = args.start,
        stop        = args.stop,
        duration    = args.duration,
        decay       = args.decay,
        volume      = args.volume,
        channels    = args.channels,
        frame_rate  = args.frame_rate,
        folder_name = folder,
        name        = args.name or preset_name,
        effects     = args.effects,
        dry_run     = args.dry_run,
    )


if __name__ == "__main__":
    main()
