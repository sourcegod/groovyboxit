#python3
"""
    File: test_sound_cache.py
    Tests du cache disque pour les sons pré-calculés (sound_cache.py).
    Date: Thu, 25/06/2026
    Author: Coolbrother
"""
import sys
import os
import time
import threading
import tempfile
import shutil

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sound_cache
from app_config import AppConfig


# ──────────────────────────────────────────────────────────────────────────────
# Fixture : répertoire cache temporaire isolé pour chaque test
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirige CACHE_DIR vers un répertoire temporaire isolé."""
    from pathlib import Path
    monkeypatch.setattr(sound_cache, "CACHE_DIR", Path(tmp_path) / "precompute")
    yield


# ──────────────────────────────────────────────────────────────────────────────
# init() — configuration du répertoire de cache
# ──────────────────────────────────────────────────────────────────────────────

def test_init_changes_cache_dir(tmp_path):
    """init() doit mettre à jour CACHE_DIR du module."""
    from pathlib import Path
    custom = tmp_path / "my_custom_cache"
    sound_cache.init(str(custom))
    assert sound_cache.CACHE_DIR == custom


def test_init_accepts_path_object(tmp_path):
    from pathlib import Path
    custom = tmp_path / "path_obj_cache"
    sound_cache.init(custom)
    assert sound_cache.CACHE_DIR == custom


def test_init_used_by_save_load(tmp_path):
    """Après init(), save_async et load utilisent le nouveau répertoire."""
    custom = tmp_path / "init_test"
    sound_cache.init(custom)
    # Remettre CACHE_DIR via init pour ce test (la fixture autouse pointe ailleurs,
    # mais init() écrase la valeur).
    sound_cache.CACHE_DIR = custom  # synchronise la fixture aussi

    key  = "init_roundtrip"
    data = np.random.rand(500, 2).astype(np.float32)
    sound_cache.save_async(key, data, None, None)
    path = custom / f"{key}.npz"
    deadline = time.monotonic() + 3.0
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert path.exists(), "Fichier non créé dans le répertoire initialisé"
    result = sound_cache.load(key)
    assert result is not None


# ──────────────────────────────────────────────────────────────────────────────
# AppConfig.sound_cache_dir
# ──────────────────────────────────────────────────────────────────────────────

def test_app_config_sound_cache_dir_default(tmp_path):
    """Sans clé dans config.json, le répertoire par défaut est ~/.cache/groovyboxit/precompute."""
    cfg = AppConfig(str(tmp_path))
    expected = os.path.join(os.path.expanduser("~"), ".cache", "groovyboxit", "precompute")
    assert cfg.sound_cache_dir == expected


def test_app_config_sound_cache_dir_absolute(tmp_path):
    """Un chemin absolu dans config.json est utilisé tel quel."""
    import json
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {"sound_cache_dir": "/tmp/my_cache"}
    (data_dir / "config.json").write_text(json.dumps(config))
    cfg = AppConfig(str(tmp_path))
    assert cfg.sound_cache_dir == "/tmp/my_cache"


def test_app_config_sound_cache_dir_relative(tmp_path):
    """Un chemin relatif dans config.json est résolu depuis base_dir."""
    import json
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = {"sound_cache_dir": "cache/sounds"}
    (data_dir / "config.json").write_text(json.dumps(config))
    cfg = AppConfig(str(tmp_path))
    assert cfg.sound_cache_dir == os.path.join(str(tmp_path), "cache", "sounds")


# ──────────────────────────────────────────────────────────────────────────────
# make_key
# ──────────────────────────────────────────────────────────────────────────────

def test_make_key_returns_hex_string():
    key = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, None, None)
    assert isinstance(key, str)
    assert len(key) == 64


def test_make_key_same_params_same_key():
    k1 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, 0.1, 0.9)
    k2 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, 0.1, 0.9)
    assert k1 == k2


def test_make_key_different_n_steps():
    k1 = sound_cache.make_key("/a/b.wav", 1.0,  2.0, 44100, None, None)
    k2 = sound_cache.make_key("/a/b.wav", 1.0, -2.0, 44100, None, None)
    assert k1 != k2


def test_make_key_different_mtime():
    k1 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, None, None)
    k2 = sound_cache.make_key("/a/b.wav", 2.0, 2.0, 44100, None, None)
    assert k1 != k2


def test_make_key_different_samplerate():
    k1 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, None, None)
    k2 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 48000, None, None)
    assert k1 != k2


def test_make_key_different_loop_points():
    k1 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, 0.1, 0.9)
    k2 = sound_cache.make_key("/a/b.wav", 1.0, 2.0, 44100, 0.2, 0.9)
    assert k1 != k2


# ──────────────────────────────────────────────────────────────────────────────
# load / save_async — round-trip
# ──────────────────────────────────────────────────────────────────────────────

def _wait_for_file(key, timeout=3.0):
    path = sound_cache.CACHE_DIR / f"{key}.npz"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def _make_data(n=1000):
    return np.random.rand(n, 2).astype(np.float32)


def test_load_absent_returns_none():
    assert sound_cache.load("nonexistent_key") is None


def test_save_load_roundtrip_no_loop():
    key  = "test_no_loop"
    data = _make_data()
    sound_cache.save_async(key, data, None, None)
    assert _wait_for_file(key), "Fichier .npz non créé dans le délai"
    result = sound_cache.load(key)
    assert result is not None
    assert result["loop_start"] is None
    assert result["loop_end"]   is None
    np.testing.assert_array_almost_equal(result["data"], data)


def test_save_load_roundtrip_with_loop():
    key  = "test_with_loop"
    data = _make_data()
    sound_cache.save_async(key, data, 0.123456, 0.987654)
    assert _wait_for_file(key)
    result = sound_cache.load(key)
    assert result is not None
    assert result["loop_start"] == pytest.approx(0.123456, abs=1e-9)
    assert result["loop_end"]   == pytest.approx(0.987654, abs=1e-9)
    np.testing.assert_array_almost_equal(result["data"], data)


def test_load_corrupted_returns_none(monkeypatch):
    """Un fichier npz corrompu ne doit pas lever d'exception."""
    from pathlib import Path
    key  = "corrupted"
    path = sound_cache.CACHE_DIR / f"{key}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a valid npz file")
    assert sound_cache.load(key) is None


# ──────────────────────────────────────────────────────────────────────────────
# clear / cache_size_mb
# ──────────────────────────────────────────────────────────────────────────────

def test_clear_removes_all_files():
    for i in range(3):
        key  = f"key_{i}"
        sound_cache.save_async(key, _make_data(), None, None)
        assert _wait_for_file(key)
    sound_cache.clear()
    assert sound_cache.cache_size_mb() == pytest.approx(0.0)


def test_cache_size_mb_empty():
    assert sound_cache.cache_size_mb() == pytest.approx(0.0)


def test_cache_size_mb_grows_after_save():
    key = "size_test"
    sound_cache.save_async(key, _make_data(50000), None, None)
    assert _wait_for_file(key)
    assert sound_cache.cache_size_mb() > 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Éviction automatique
# ──────────────────────────────────────────────────────────────────────────────

def test_eviction_reduces_size(monkeypatch):
    """Quand le cache dépasse MAX_CACHE_MB les fichiers les plus anciens sont supprimés.

    Strategie : eviction AVANT ecriture.
    key1 ecrit en premier (cache vide -> pas d'eviction).
    key2 provoque l'eviction de key1 (cache > seuil) puis est ecrit.
    Au final, seul key2 subsiste.
    """
    monkeypatch.setattr(sound_cache, "MAX_CACHE_MB", 0.001)  # seuil 1 Ko
    key1, key2 = "evict_old", "evict_new"
    data = _make_data(5000)  # ~40 Ko > seuil

    sound_cache.save_async(key1, data, None, None)
    assert _wait_for_file(key1), "key1 non cree"

    sound_cache.save_async(key2, data, None, None)
    assert _wait_for_file(key2), "key2 non cree"

    remaining = list(sound_cache.CACHE_DIR.glob("*.npz"))
    assert len(remaining) <= 1


# ──────────────────────────────────────────────────────────────────────────────
# Intégration SynthEngine — cache disque utilisé à la 2ème instanciation
# ──────────────────────────────────────────────────────────────────────────────

WAV_SRC   = "/home/com/audiotest/a440.wav"
ROOT_NOTE = "A4"


def _make_patch(wav_src, root_note):
    import json
    patch_dir = tempfile.mkdtemp(prefix="grv_cache_test_")
    dst = os.path.join(patch_dir, f"{root_note}.wav")
    shutil.copy(wav_src, dst)
    meta = {
        "name": "CacheTestPatch", "loop": False,
        "loop_start": None, "loop_end": None,
        "samples": [{"file": f"{root_note}.wav", "root": root_note}],
    }
    with open(os.path.join(patch_dir, "patch.json"), "w") as f:
        json.dump(meta, f)
    return patch_dir


@pytest.mark.skipif(not os.path.exists(WAV_SRC), reason=f"WAV introuvable : {WAV_SRC}")
def test_synth_engine_uses_disk_cache():
    """_get_pitched_sampler doit écrire puis relire depuis le cache disque."""
    from synth_engine import SynthEngine
    from sound_device_driver import SoundDeviceDriver

    patch_dir = _make_patch(WAV_SRC, ROOT_NOTE)
    try:
        drv = SoundDeviceDriver()
        eng = SynthEngine(os.path.dirname(patch_dir), driver=drv)
        eng.load_patch(os.path.basename(patch_dir))

        midi_note = 71  # A4+2 → n_steps=2, rubberband activé

        # Premier appel — calcul rubberband + écriture cache
        pitched1 = eng._get_pitched_sampler(midi_note)
        assert pitched1 is not None

        # Attendre l'écriture asynchrone
        entry = eng._find_nearest_sample(midi_note)
        mtime = os.path.getmtime(entry["path"])
        src   = entry["sampler"]
        n_steps = midi_note - entry["root_midi"]
        key = sound_cache.make_key(
            entry["path"], mtime, n_steps, src.samplerate,
            src._loop_start, src._loop_end,
        )
        assert _wait_for_file(key), "Cache disque non créé"

        # Vider le cache mémoire pour forcer la relecture disque
        eng._raw_cache.clear()

        pitched2 = eng._get_pitched_sampler(midi_note)
        assert pitched2 is not None
        np.testing.assert_array_almost_equal(pitched1.data, pitched2.data)

        drv.close()
    finally:
        shutil.rmtree(patch_dir, ignore_errors=True)
