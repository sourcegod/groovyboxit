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

    VERSION = 1
    DEFAULT_NAME = "noname_001.gvp"
    WILDCARD = "Projets GroovyboxIt (*.gvp)|*.gvp|Preset JSON (*.json)|*.json|Tous les fichiers (*.*)|*.*"

    @staticmethod
    def load(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save(path, data):
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(',', ':'))
