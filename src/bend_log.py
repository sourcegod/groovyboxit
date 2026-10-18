#python3
"""
    File: src/bend_log.py
    Traces de débogage du pitch bend dans bend_log.txt (racine du dépôt),
    activées si GROOVY_BEND_LOG=1 au lancement. Remplace les quatre copies
    de _bend_log (Phase 7 étape 9b1).
    Date: Sun, 18/10/2026
    Author: Coolbrother
"""

import os
import time

_ENABLED  = os.environ.get("GROOVY_BEND_LOG") == "1"
_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "bend_log.txt")


def bend_log(msg):
    if not _ENABLED:
        return
    ts = time.strftime("%H:%M:%S")
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
