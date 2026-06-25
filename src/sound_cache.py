#python3
"""
    File: sound_cache.py
    Cache disque pour les buffers audio pré-calculés (pitch shifting rubberband).
    Stockage : <CACHE_DIR>/<sha256>.npz  (défaut : ~/.cache/groovyboxit/precompute)
    Écriture asynchrone (thread daemon) pour ne pas bloquer le moteur.

    Le répertoire de cache est configurable via init() au démarrage de l'application,
    ce qui permet à l'utilisateur de le modifier dans les préférences (AppConfig).
    Date: Thu, 25/06/2026
    Author: Coolbrother
"""
import hashlib
import threading
import numpy as np
from pathlib import Path

# Valeur par défaut — remplacée par init() au démarrage de l'application.
CACHE_DIR    = Path.home() / ".cache" / "groovyboxit" / "precompute"
MAX_CACHE_MB = 200


def init(cache_dir) -> None:
    """Fixe le répertoire de cache utilisé par toutes les fonctions du module.

    À appeler une seule fois au démarrage, après lecture de AppConfig :
        sound_cache.init(cfg.sound_cache_dir)
    """
    global CACHE_DIR
    CACHE_DIR = Path(cache_dir)


def make_key(wav_path: str, mtime: float, n_steps: float,
             samplerate: int, loop_start, loop_end) -> str:
    """Retourne le sha256 hex identifiant un buffer pitché unique."""
    h = hashlib.sha256()
    h.update(str(wav_path).encode())
    h.update(str(mtime).encode())
    h.update(f"{n_steps:.6f}".encode())
    h.update(str(samplerate).encode())
    h.update(str(loop_start).encode())
    h.update(str(loop_end).encode())
    return h.hexdigest()


def load(key: str):
    """Charge un buffer depuis le cache.

    Retourne un dict {"data": ndarray, "loop_start": float|None, "loop_end": float|None}
    ou None si absent / corrompu.
    """
    path = CACHE_DIR / f"{key}.npz"
    if not path.exists():
        return None
    try:
        d = np.load(str(path))
        ls = float(d["loop_start"])
        le = float(d["loop_end"])
        return {
            "data":       d["data"],
            "loop_start": None if np.isnan(ls) else ls,
            "loop_end":   None if np.isnan(le) else le,
        }
    except Exception:
        return None


def save_async(key: str, data: np.ndarray, loop_start, loop_end) -> None:
    """Écrit le buffer dans le cache en arrière-plan (thread daemon).

    L'écriture est atomique (tmp → rename) pour éviter les lectures partielles.
    L'éviction se fait avant l'écriture pour protéger le fichier qui vient d'être créé.
    """
    ls = float("nan") if loop_start is None else float(loop_start)
    le = float("nan") if loop_end   is None else float(loop_end)
    arr = data

    def _write():
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _evict_if_needed()
            final_path = CACHE_DIR / f"{key}.npz"
            tmp_path   = CACHE_DIR / f"{key}.tmp.npz"
            np.savez_compressed(
                str(tmp_path),
                data=arr,
                loop_start=np.float64(ls),
                loop_end=np.float64(le),
            )
            tmp_path.rename(final_path)
        except Exception:
            pass

    t = threading.Thread(target=_write, daemon=True)
    t.start()


def clear() -> None:
    """Supprime tous les fichiers du cache."""
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("*.npz"):
            try:
                f.unlink()
            except OSError:
                pass


def cache_size_mb() -> float:
    """Retourne la taille totale du cache en mégaoctets."""
    if not CACHE_DIR.exists():
        return 0.0
    total = sum(f.stat().st_size for f in CACHE_DIR.glob("*.npz") if f.is_file())
    return total / (1024 * 1024)


def _evict_if_needed() -> None:
    """Supprime les fichiers les plus anciens si le cache dépasse MAX_CACHE_MB."""
    if not CACHE_DIR.exists():
        return
    files = [(f, f.stat()) for f in CACHE_DIR.glob("*.npz") if f.is_file()]
    total = sum(st.st_size for _, st in files) / (1024 * 1024)
    if total <= MAX_CACHE_MB:
        return
    files.sort(key=lambda x: x[1].st_atime)
    for path, st in files:
        if total <= MAX_CACHE_MB * 0.8:
            break
        try:
            path.unlink()
            total -= st.st_size / (1024 * 1024)
        except OSError:
            pass
