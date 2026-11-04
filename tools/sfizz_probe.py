#!/usr/bin/env python3
"""
    File: tools/sfizz_probe.py
    Essai de libsfizz par ctypes, sans l'appli (Phase 8 étape 7a1,
    docs/sfizz_build.md) : vérifie qu'une libsfizz compilée se charge et
    joue comme le moteur SFZ de l'appli en aura besoin.

    Crée dans un dossier temporaire des WAV synthétiques (cosinus) et de
    petits .sfz, puis vérifie : chargement (et refus d'un fichier absent),
    opcodes inconnus signalés, silence avant la note, hauteur jouée
    (pitch_keycenter, transposition au-dessus et au-dessous), Pitch Bend,
    vélocité, note off et release, délai exact dans le bloc, All Sound Off,
    groupes exclusifs (group / off_by), deux instances indépendantes,
    réponse aux CC 7, 10, 11 et 64, coût du rendu (32 voix).

    Les fonctions C sont déclarées (argtypes / restype) comme dans
    src/engines/fluidsynth_engine.py : c'est l'ébauche du futur
    src/engines/sfizz_engine.py, et de la liaison C/C++.

    Code de sortie : 0 si toutes les vérifications passent, 1 sinon,
    2 si la bibliothèque est introuvable.

    Usage:
        python3 tools/sfizz_probe.py
        python3 tools/sfizz_probe.py --lib /chemin/libsfizz.so.1
        python3 tools/sfizz_probe.py --keep /dossier   # garde WAV et .sfz

    Date: Wed, 04/11/2026
    Author: Coolbrother
"""

import argparse
import ctypes
import ctypes.util
import os
import sys
import tempfile
import time
import wave

import numpy as np

SR    = 48000
BLOCK = 512

DEFAULT_LIBS = (os.path.expanduser("~/.local/lib/libsfizz.so.1"),
                "libsfizz.so.1", "libsfizz.so")


# -- liaison ----------------------------------------------------------------

def load_library(path=None):
    """Charge libsfizz et déclare les signatures utilisées ; None si absente."""
    names = [path] if path else [*DEFAULT_LIBS, ctypes.util.find_library("sfizz")]
    for name in names:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        _declare(lib)
        lib._probe_name = name
        return lib
    return None


def _declare(lib):
    vp, ci, cf, cb, cc = (ctypes.c_void_p, ctypes.c_int, ctypes.c_float,
                          ctypes.c_bool, ctypes.c_char_p)
    fpp = ctypes.POINTER(ctypes.POINTER(cf))
    sigs = {
        "sfizz_create_synth":              ([], vp),
        "sfizz_free":                      ([vp], None),
        "sfizz_load_file":                 ([vp, cc], cb),
        "sfizz_set_sample_rate":           ([vp, cf], None),
        "sfizz_set_samples_per_block":     ([vp, ci], None),
        "sfizz_send_note_on":              ([vp, ci, ci, ci], None),
        "sfizz_send_note_off":             ([vp, ci, ci, ci], None),
        "sfizz_send_cc":                   ([vp, ci, ci, ci], None),
        "sfizz_send_pitch_wheel":          ([vp, ci, ci], None),
        "sfizz_render_block":              ([vp, fpp, ci, ci], None),
        "sfizz_get_num_regions":           ([vp], ci),
        "sfizz_get_num_active_voices":     ([vp], ci),
        "sfizz_get_num_preloaded_samples": ([vp], ctypes.c_size_t),
        "sfizz_all_sound_off":             ([vp], None),
        "sfizz_get_unknown_opcodes":       ([vp], vp),
        "sfizz_free_memory":               ([vp], None),
    }
    for name, (args, res) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = args
        fn.restype  = res


class Synth:
    """Une instance sfizz (= un instrument) et ses deux tampons de rendu."""

    def __init__(self, lib):
        self.lib = lib
        self.s = lib.sfizz_create_synth()
        lib.sfizz_set_sample_rate(self.s, SR)
        lib.sfizz_set_samples_per_block(self.s, BLOCK)
        self.L = np.zeros(BLOCK, np.float32)
        self.R = np.zeros(BLOCK, np.float32)
        p = ctypes.POINTER(ctypes.c_float)
        self.chans = (p * 2)(self.L.ctypes.data_as(p), self.R.ctypes.data_as(p))

    def load(self, path):
        return bool(self.lib.sfizz_load_file(self.s, path.encode()))

    def unknown_opcodes(self):
        p = self.lib.sfizz_get_unknown_opcodes(self.s)
        if not p:
            return ""
        text = ctypes.cast(p, ctypes.c_char_p).value.decode()
        self.lib.sfizz_free_memory(p)
        return text

    def render(self, frames):
        """frames échantillons stéréo (frames, 2), par blocs de BLOCK."""
        out = []
        for _ in range(-(-frames // BLOCK)):
            self.lib.sfizz_render_block(self.s, self.chans, 2, BLOCK)
            out.append(np.column_stack([self.L, self.R]))
        return np.concatenate(out)[:frames]

    def voices(self):
        return self.lib.sfizz_get_num_active_voices(self.s)

    def silence(self):
        self.lib.sfizz_all_sound_off(self.s)
        self.render(4 * BLOCK)

    def free(self):
        self.lib.sfizz_free(self.s)


# -- fichiers d'essai ---------------------------------------------------------

def write_wav(path, freq, seconds=2.0, amp=0.5):
    """Cosinus mono 16 bits : le premier échantillon n'est pas nul, ce qui
    permet de voir l'échantillon exact où une note commence."""
    t = np.arange(int(seconds * SR)) / SR
    pcm = (np.cos(2 * np.pi * freq * t) * amp * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def write_files(d):
    write_wav(os.path.join(d, "a440.wav"), 440.0)
    write_wav(os.path.join(d, "e660.wav"), 660.0)
    files = {
        # une région sur tout le clavier, la 440 Hz à la note 69
        "sine.sfz": "<region> sample=a440.wav pitch_keycenter=69 "
                    "lokey=0 hikey=127 ampeg_release=0.05 foo_unknown=1\n",
        # groupes exclusifs : la note 61 (groupe 2) coupe la note 60 (groupe 1)
        "hats.sfz": "<group> loop_mode=one_shot\n"
                    "<region> sample=a440.wav key=60 group=1 off_by=2\n"
                    "<region> sample=e660.wav key=61 group=2\n",
    }
    for name, text in files.items():
        with open(os.path.join(d, name), "w") as f:
            f.write(text)
    return {k: os.path.join(d, k) for k in files}


# -- mesures --------------------------------------------------------------------

def freq_of(x):
    """Fréquence dominante (pic de FFT avec interpolation parabolique)."""
    x = x[:, 0] if x.ndim == 2 else x
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    k = int(np.argmax(spec[1:-1])) + 1
    a, b, c = np.log(spec[k - 1:k + 2] + 1e-12)
    k += 0.5 * (a - c) / (a - 2 * b + c)
    return k * SR / len(x)


def peak(x):
    return float(np.abs(x).max())


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


# -- vérifications ----------------------------------------------------------------

class Report:
    def __init__(self):
        self.failed = 0

    def check(self, label, ok, detail=""):
        print(f"[{'OK ' if ok else 'ÉCHEC'}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            self.failed += 1

    def info(self, label, detail):
        print(f"[info] {label} — {detail}")


def close(f, target, tol=0.01):
    return abs(f - target) <= target * tol


def run(lib, d):
    rep = Report()
    files = write_files(d)
    s = Synth(lib)

    # chargement
    t0 = time.perf_counter()
    ok = s.load(files["sine.sfz"])
    dt = (time.perf_counter() - t0) * 1000
    rep.check("chargement d'un .sfz", ok and lib.sfizz_get_num_regions(s.s) == 1,
              f"{dt:.1f} ms, {lib.sfizz_get_num_regions(s.s)} région(s), "
              f"{lib.sfizz_get_num_preloaded_samples(s.s)} sample(s) préchargé(s)")
    rep.check("opcode inconnu signalé", "foo_unknown" in s.unknown_opcodes(),
              repr(s.unknown_opcodes()))
    bad = Synth(lib)
    rep.check("fichier absent refusé", not bad.load(os.path.join(d, "absent.sfz")))
    bad.free()

    # silence, hauteur, vélocité
    rep.check("silence avant toute note", peak(s.render(4 * BLOCK)) == 0.0)
    for note, target, label in ((69, 440.0, "note 69 = pitch_keycenter"),
                                (81, 880.0, "note 81, une octave au-dessus"),
                                (57, 220.0, "note 57, une octave au-dessous")):
        lib.sfizz_send_note_on(s.s, 0, note, 100)
        x = s.render(SR // 2)
        f = freq_of(x[4096:])
        rep.check(label, close(f, target), f"{f:.1f} Hz (attendu {target:.0f})")
        s.silence()
    lib.sfizz_send_note_on(s.s, 0, 69, 100)
    lv100 = rms(s.render(SR // 4)[2048:])
    s.silence()
    lib.sfizz_send_note_on(s.s, 0, 69, 50)
    lv50 = rms(s.render(SR // 4)[2048:])
    s.silence()
    rep.check("vélocité 50 plus douce que 100", 0 < lv50 < lv100,
              f"RMS {lv50:.4f} < {lv100:.4f}")
    rep.info("niveau à vélocité 100", f"cosinus d'amplitude 0,5 rendu en RMS "
             f"{lv100:.4f} (gain à régler dans l'appli)")

    # Pitch Bend (±200 cents par défaut en SFZ)
    lib.sfizz_send_note_on(s.s, 0, 69, 100)
    lib.sfizz_send_pitch_wheel(s.s, 0, 8191)
    f = freq_of(s.render(SR // 2)[4096:])
    target = 440.0 * 2 ** (2 / 12)
    rep.check("Pitch Bend +8191 = +2 demi-tons", close(f, target),
              f"{f:.1f} Hz (attendu {target:.1f})")
    lib.sfizz_send_pitch_wheel(s.s, 0, 0)
    s.silence()

    # note off, release
    lib.sfizz_send_note_on(s.s, 0, 69, 100)
    s.render(8 * BLOCK)
    lib.sfizz_send_note_off(s.s, 0, 69, 0)
    s.render(SR // 5)       # ampeg_release = 50 ms
    rep.check("note off : voix libérée après le release",
              s.voices() == 0 and peak(s.render(BLOCK)) == 0.0,
              f"{s.voices()} voix")

    # délai exact dans le bloc
    lib.sfizz_send_note_on(s.s, 300, 69, 100)
    x = s.render(BLOCK)
    nz = np.nonzero(np.abs(x[:, 0]) > 1e-6)[0]
    first = int(nz[0]) if len(nz) else None
    rep.check("note_on avec delay=300 commence à l'échantillon 300", first == 300,
              f"premier échantillon non nul : {first}")

    # All Sound Off
    lib.sfizz_send_note_on(s.s, 0, 72, 100)
    s.render(BLOCK)
    lib.sfizz_all_sound_off(s.s)
    s.render(BLOCK)
    rep.check("All Sound Off coupe toutes les voix", s.voices() == 0,
              f"{s.voices()} voix")

    # CC 7 / 11 / 10 / 64 : comportement par défaut de sfizz
    def level_with(cc, value, note=69):
        s.silence()
        lib.sfizz_send_cc(s.s, 0, cc, value)
        lib.sfizz_send_note_on(s.s, 0, note, 100)
        x = s.render(SR // 4)[2048:]
        lib.sfizz_send_cc(s.s, 0, cc, {7: 100, 11: 127, 10: 64}.get(cc, 0))
        return x
    for cc, label in ((7, "CC7 volume"), (11, "CC11 expression")):
        lo = rms(level_with(cc, 20))
        rep.info(f"{label} à 20 au lieu du défaut",
                 f"RMS {lo:.4f} contre {lv100:.4f}"
                 + (" : répond" if lo < lv100 * 0.9 else " : NE répond PAS"))
    x = level_with(10, 0)
    l, r = rms(x[:, 0]), rms(x[:, 1])
    rep.info("CC10 pan à 0 (gauche)", f"RMS G {l:.4f}, D {r:.4f}"
             + (" : répond" if r < l * 0.5 else " : NE répond PAS"))
    s.silence()
    lib.sfizz_send_cc(s.s, 0, 64, 127)
    lib.sfizz_send_note_on(s.s, 0, 69, 100)
    s.render(4 * BLOCK)
    lib.sfizz_send_note_off(s.s, 0, 69, 0)
    s.render(SR // 5)
    held = s.voices()
    lib.sfizz_send_cc(s.s, 0, 64, 0)
    s.render(SR // 5)
    rep.check("CC64 : la pédale tient la note, la relâcher la libère",
              held == 1 and s.voices() == 0, f"{held} voix tenue(s), puis {s.voices()}")
    s.silence()

    # groupes exclusifs
    h = Synth(lib)
    h.load(files["hats.sfz"])
    lib.sfizz_send_note_on(h.s, 0, 60, 100)
    h.render(4 * BLOCK)
    lib.sfizz_send_note_on(h.s, 0, 61, 100)
    h.render(SR // 10)
    f = freq_of(h.render(SR // 4))
    rep.check("group / off_by : la note 61 coupe la note 60",
              h.voices() == 1 and close(f, 660.0),
              f"{h.voices()} voix, {f:.1f} Hz")
    h.free()

    # deux instances = deux instruments indépendants
    s2 = Synth(lib)
    s2.load(files["sine.sfz"])
    lib.sfizz_send_note_on(s.s, 0, 69, 100)
    lib.sfizz_send_note_on(s2.s, 0, 76, 100)
    fa = freq_of(s.render(SR // 2)[4096:])
    fb = freq_of(s2.render(SR // 2)[4096:])
    rep.check("deux instances indépendantes", close(fa, 440.0) and close(fb, 659.26),
              f"{fa:.1f} Hz et {fb:.1f} Hz")
    s2.free()
    s.silence()

    # coût du rendu
    for n in range(40, 72):
        lib.sfizz_send_note_on(s.s, 0, n, 100)
    nblocks = 200
    t0 = time.perf_counter()
    s.render(nblocks * BLOCK)
    dt = time.perf_counter() - t0
    share = dt / (nblocks * BLOCK / SR) * 100
    rep.check("32 voix rendues bien plus vite que le temps réel", share < 50,
              f"{share:.1f} % du temps réel ({dt * 1000:.1f} ms pour "
              f"{nblocks * BLOCK / SR:.2f} s de son)")
    s.free()
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Essai de libsfizz par ctypes.")
    ap.add_argument("--lib", help="chemin de libsfizz.so (défaut : ~/.local/lib, puis le système)")
    ap.add_argument("--keep", help="dossier où écrire et garder les WAV et .sfz d'essai")
    args = ap.parse_args(argv)

    lib = load_library(args.lib)
    if lib is None:
        print("libsfizz introuvable (voir docs/sfizz_build.md)", file=sys.stderr)
        return 2
    print(f"libsfizz : {lib._probe_name}")
    if args.keep:
        os.makedirs(args.keep, exist_ok=True)
        rep = run(lib, args.keep)
    else:
        with tempfile.TemporaryDirectory() as d:
            rep = run(lib, d)
    print("Résultat :", "tout est bon" if rep.failed == 0 else f"{rep.failed} échec(s)")
    return 0 if rep.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
