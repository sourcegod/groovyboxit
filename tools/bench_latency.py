#!/usr/bin/env python3
"""
    File: tools/bench_latency.py
    Comparaison de latence entre PygameDriver et SoundDeviceDriver.

    Métriques mesurées
    ------------------
    1. Overhead du call play()          — temps pur du call API (µs)
    2. Latence théorique du buffer      — frames / samplerate (ms)
    3. Latence PortAudio reportée       — SoundDevice uniquement (ms)
    4. Temps play() → fin d'un son court — SoundDevice uniquement (ms)

    Usage:
        python3 tools/bench_latency.py
        python3 tools/bench_latency.py --runs 1000

    Date: Thu, 28/05/2026
    Author: Coolbrother
"""

import sys
import os
import time
import argparse
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pygame
import sounddevice as sd
from pygame_driver        import PygameDriver
from sound_device_driver  import SoundDeviceDriver, SdSound


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SR         = 44100
BLOCKSIZE  = 512
PG_BUFFER  = 512   # frames — valeur par défaut de pygame.mixer


# ---------------------------------------------------------------------------
# Préparation des sons de test
# ---------------------------------------------------------------------------

def _make_pg_sound_1s():
    """pygame.Sound d'une seconde (silence)."""
    arr = np.zeros((SR, 2), dtype=np.int16)
    return pygame.sndarray.make_sound(arr)


def _make_sd_sound_1s():
    """SdSound d'une seconde (silence)."""
    return SdSound(np.zeros((SR, 2), dtype=np.float32), SR)


def _make_sd_sound_short(drv):
    """SdSound très court = 2 × blocksize (se consomme en ~23 ms)."""
    return SdSound(np.zeros((drv._blocksize * 2, 2), dtype=np.float32), SR)


# ---------------------------------------------------------------------------
# Benchmark 1 : overhead du call play()
# ---------------------------------------------------------------------------

def bench_play_overhead(driver, sound, label, n_runs):
    """
    Mesure le temps entre l'appel de play() et son retour.
    C'est le délai minimal avant que le son soit *soumis* au moteur.
    """
    times = []
    for _ in range(n_runs):
        driver.stop_all()
        t0 = time.perf_counter()
        driver.play(sound)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1_000_000)   # µs
    driver.stop_all()
    times.sort()
    return {
        "min":    times[0],
        "median": statistics.median(times),
        "p95":    times[int(n_runs * 0.95)],
        "p99":    times[int(n_runs * 0.99)],
        "max":    times[-1],
    }


# ---------------------------------------------------------------------------
# Benchmark 2 : temps play() → fin du son (SoundDevice uniquement)
# ---------------------------------------------------------------------------

def bench_sd_roundtrip(drv, n_runs=100):
    """
    Mesure le temps entre play() et la disparition de la voix du callback.
    Pour un son de durée = 2 × blocksize, ce délai ≈ 1–3 appels de callback
    = 1–3 × blocksize / sr ≈ 12–35 ms.
    Donne une estimation concrète de la latence de démarrage.
    """
    short = _make_sd_sound_short(drv)
    times = []
    for _ in range(n_runs):
        drv.stop_all()
        t0 = time.perf_counter()
        drv.play(short)
        while drv.voice_count() > 0:
            pass
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)   # ms
    times.sort()
    return {
        "min":    times[0],
        "median": statistics.median(times),
        "p95":    times[int(n_runs * 0.95)],
        "max":    times[-1],
    }


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

def _fmt_overhead(stats):
    return (f"médiane={stats['median']:6.1f}µs  "
            f"p95={stats['p95']:6.1f}µs  "
            f"p99={stats['p99']:6.1f}µs  "
            f"max={stats['max']:7.1f}µs")


def _fmt_roundtrip(stats):
    return (f"médiane={stats['median']:5.1f}ms  "
            f"p95={stats['p95']:5.1f}ms  "
            f"max={stats['max']:5.1f}ms")


def print_separator():
    print("-" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Benchmark latence PygameDriver vs SoundDeviceDriver")
    ap.add_argument("--runs", type=int, default=500,
                    help="Nombre d'itérations pour le benchmark play() (défaut : 500)")
    args = ap.parse_args()

    print("\n" + "=" * 70)
    print("  Benchmark latence audio — PygameDriver vs SoundDeviceDriver")
    print("=" * 70)

    # ── Initialisation des drivers ──────────────────────────────────────────
    pg_drv = PygameDriver()
    sd_drv = SoundDeviceDriver(samplerate=SR, blocksize=BLOCKSIZE)

    pg_sound = _make_pg_sound_1s()
    sd_sound = _make_sd_sound_1s()

    # ── 1. Overhead du call play() ──────────────────────────────────────────
    print(f"\n[1] Overhead du call play()  (N={args.runs})")
    print_separator()

    pg_stats = bench_play_overhead(pg_drv, pg_sound, "PygameDriver",       args.runs)
    sd_stats = bench_play_overhead(sd_drv, sd_sound, "SoundDeviceDriver",  args.runs)

    print(f"  PygameDriver      : {_fmt_overhead(pg_stats)}")
    print(f"  SoundDeviceDriver : {_fmt_overhead(sd_stats)}")

    ratio = pg_stats["median"] / sd_stats["median"] if sd_stats["median"] > 0 else float("inf")
    if abs(ratio - 1.0) < 0.3:
        print(f"\n  → overhead pratiquement identique ({ratio:.1f}×) — la différence")
        print(f"     de réactivité perçue vient de l'architecture, pas de ce call")
    elif ratio > 1.0:
        print(f"\n  → pygame {ratio:.1f}× plus lent que SoundDevice (médiane)")
    else:
        print(f"\n  → SoundDevice {1/ratio:.1f}× plus lent que pygame (médiane)")

    # ── 2. Latence théorique du buffer ──────────────────────────────────────
    pg_buf_ms = PG_BUFFER / SR * 1000
    sd_buf_ms = BLOCKSIZE  / SR * 1000

    print(f"\n[2] Latence théorique du buffer")
    print_separator()
    print(f"  PygameDriver      : {PG_BUFFER} frames / {SR} Hz"
          f"  = {pg_buf_ms:.1f} ms")
    print(f"  SoundDeviceDriver : {BLOCKSIZE} frames / {SR} Hz"
          f"  = {sd_buf_ms:.1f} ms")
    print(f"  (même blocksize ici — pygame peut être initialisé avec un buffer plus grand)")

    # ── 3. Latence PortAudio reportée ──────────────────────────────────────
    pa_latency_ms = sd_drv._stream.latency * 1000

    print(f"\n[3] Latence output reportée par PortAudio")
    print_separator()
    print(f"  PygameDriver      : non disponible (SDL gère le buffer en interne)")
    print(f"  SoundDeviceDriver : {pa_latency_ms:.1f} ms  "
          f"(buffer théorique + overhead OS)")

    # ── 4. Temps play() → fin du son (SoundDevice) ─────────────────────────
    print(f"\n[4] Temps play() → fin du son court ({BLOCKSIZE * 2} frames = {sd_buf_ms * 2:.0f} ms)")
    print_separator()
    print("  Mesure le délai concret avant que le son ait démarré ET fini")
    print("  (≈ latence de démarrage + durée du son)")

    rt = bench_sd_roundtrip(sd_drv, n_runs=100)
    print(f"  SoundDeviceDriver : {_fmt_roundtrip(rt)}")

    theoretical_start = pa_latency_ms + sd_buf_ms
    print(f"  Latence de démarrage estimée ≈ {theoretical_start:.1f} ms "
          f"(PortAudio {pa_latency_ms:.1f} + buffer {sd_buf_ms:.1f})")

    # ── Résumé ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  Résumé")
    print(f"{'=' * 70}")
    print(f"  call play()   PG={pg_stats['median']:.1f}µs   SD={sd_stats['median']:.1f}µs")
    print(f"  buffer        PG≥{pg_buf_ms:.1f}ms   SD={sd_buf_ms:.1f}ms (PortAudio={pa_latency_ms:.1f}ms)")
    print(f"  avantage SD   overhead {ratio:.1f}× plus rapide, latence mesurée {pa_latency_ms:.1f}ms")
    print()

    # ── Interprétation ──────────────────────────────────────────────────────
    print("  Pourquoi SoundDevice semble plus réactif malgré une latence similaire :")
    print("  - pygame alloue un 'channel' libre à chaque play() → contention")
    print("    si beaucoup de sons jouent simultanément (max 8 par défaut)")
    print("  - SoundDevice ajoute simplement une _Voice à une liste → illimité")
    print("  - Le thread audio PortAudio a généralement une priorité OS plus")
    print("    élevée que le thread SDL de pygame")
    print("  - La latence PortAudio (34 ms ici) inclut le stack PulseAudio/ALSA ;")
    print("    avec JACK ou en mode direct ALSA elle tomberait à ~5-10 ms")
    print()

    sd_drv.close()


if __name__ == "__main__":
    main()
