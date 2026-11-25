#python3
"""
    File: src/project_manager.py
    Lecture/écriture des fichiers projet .gvp (GroovyboxIt Project).
    Date: Sat, 20/06/2026
    Author: Coolbrother
"""
import os
import json


class ProjectManager:
    """Utilitaire de sérialisation projet .gvp (JSON sous le capot)."""

    # 2 : fin de boucle EXCLUE (Phase 9 étape 4b1, § 4a B6) ; un projet
    # version 1 (fin incluse) est migré à la lecture, fin + 1
    VERSION = 2
    DEFAULT_NAME = "project_01.gvp"
    WILDCARD = "Projets GroovyboxIt (*.gvp)|*.gvp|Preset JSON (*.json)|*.json|Tous les fichiers (*.*)|*.*"

    @staticmethod
    def load(path):
        with open(path, "r", encoding="utf-8") as f:
            return ProjectManager.migrate(json.load(f))

    @staticmethod
    def migrate(data):
        """Données d'un projet d'une version antérieure mises au format
        courant (version 1 → 2 : fin de boucle + 1, même boucle entendue)."""
        if not isinstance(data, dict):
            return data
        if data.get("version", 1) < 2:
            for pat in data.get("patterns", []):
                if isinstance(pat, dict) and isinstance(pat.get("loop_end"), int):
                    pat["loop_end"] += 1
            data["version"] = 2
        return data

    @staticmethod
    def save(path, data):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(',', ':'))
