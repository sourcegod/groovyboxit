#python3
"""
    File: tests/test_bend_log.py
    Tests unitaires de src/bend_log.py (Phase 7 étape 9b1) : drapeau éteint
    ou allumé, format des lignes, chemin par défaut, et module partagé par
    les quatre fichiers qui avaient leur propre copie de _bend_log.
    Date: Sun, 18/10/2026
    Author: Coolbrother
"""
import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bend_log
from player import dp_recording
import track_router
import synth_engine
import ui.midi_handler_window as midi_handler_window

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_LINE_RE   = re.compile(r"^\[\d\d:\d\d:\d\d\] (.*)$")
_USERS     = (dp_recording, track_router, synth_engine, midi_handler_window)


def _log_to(monkeypatch, tmp_path, enabled):
    path = tmp_path / "bend_log.txt"
    monkeypatch.setattr(bend_log, "_ENABLED", enabled)
    monkeypatch.setattr(bend_log, "_LOG_PATH", str(path))
    return path


# ---------------------------------------------------------------------------
# bend_log()
# ---------------------------------------------------------------------------

def test_disabled_writes_nothing(monkeypatch, tmp_path):
    path = _log_to(monkeypatch, tmp_path, enabled=False)
    bend_log.bend_log("ne doit pas apparaître")
    assert not path.exists()
    print("  bend_log éteint : aucun fichier créé : OK")

def test_enabled_writes_one_timestamped_line(monkeypatch, tmp_path):
    path = _log_to(monkeypatch, tmp_path, enabled=True)
    bend_log.bend_log("BEND_SET bend=+1234")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    m = _LINE_RE.match(lines[0])
    assert m and m.group(1) == "BEND_SET bend=+1234", lines[0]
    print("  bend_log allumé : une ligne [HH:MM:SS] message : OK")

def test_enabled_appends_after_existing_content(monkeypatch, tmp_path):
    path = _log_to(monkeypatch, tmp_path, enabled=True)
    path.write_text("[00:00:00] ancienne ligne\n", encoding="utf-8")
    bend_log.bend_log("premier")
    bend_log.bend_log("second")
    msgs = [_LINE_RE.match(l).group(1)
            for l in path.read_text(encoding="utf-8").splitlines()]
    assert msgs == ["ancienne ligne", "premier", "second"]
    print("  bend_log allumé : lignes ajoutées à la suite, ordre conservé : OK")

def test_enabled_keeps_non_ascii_text(monkeypatch, tmp_path):
    path = _log_to(monkeypatch, tmp_path, enabled=True)
    bend_log.bend_log("ENGINE_PLAY → sound=None (pas de voix créée!)")
    assert "→" in path.read_text(encoding="utf-8")
    print("  bend_log : texte non ASCII écrit en UTF-8 : OK")

def test_default_path_is_repo_root():
    assert os.path.normpath(bend_log._LOG_PATH) == os.path.join(_REPO_ROOT, "bend_log.txt")
    print("  bend_log : fichier par défaut à la racine du dépôt : OK")

def test_flag_reads_groovy_bend_log_env_var():
    """Le drapeau vaut ce que dit GROOVY_BEND_LOG au moment de l'import."""
    assert bend_log._ENABLED == (os.environ.get("GROOVY_BEND_LOG") == "1")
    print("  bend_log : drapeau lu depuis GROOVY_BEND_LOG : OK")


# ---------------------------------------------------------------------------
# Module partagé (plus de copie locale)
# ---------------------------------------------------------------------------

def test_all_users_share_the_same_function():
    for mod in _USERS:
        assert mod.bend_log is bend_log.bend_log, mod.__name__
    print("  dp_recording, track_router, synth_engine, midi_handler_window : même bend_log : OK")

def test_no_local_copy_left():
    for mod in _USERS:
        for name in ("_bend_log", "_BEND_LOG", "_BEND_LOG_PATH"):
            assert not hasattr(mod, name), f"{mod.__name__}.{name}"
    print("  plus de copie locale de _bend_log : OK")

def test_users_write_into_the_shared_file(monkeypatch, tmp_path):
    path = _log_to(monkeypatch, tmp_path, enabled=True)
    for mod in _USERS:
        mod.bend_log(mod.__name__)
    msgs = [_LINE_RE.match(l).group(1)
            for l in path.read_text(encoding="utf-8").splitlines()]
    assert msgs == [mod.__name__ for mod in _USERS]
    print("  les quatre modules écrivent dans le même fichier : OK")
