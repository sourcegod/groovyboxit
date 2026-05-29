#python3
"""
    File: src/app_config.py
    Chargement de la configuration applicative depuis data/config.json.
    Les chemins manquants tombent back sur des sous-dossiers relatifs au projet.
    Date: Mon, 26/05/2026
    Author: Coolbrother
"""
import os
import json


class AppConfig:
    """
    Charge data/config.json depuis la racine du projet.
    Fournit les chemins configurables avec fallback relatif si absent.
    """

    CONFIG_RELATIVE = os.path.join("data", "config.json")

    def __init__(self, base_dir):
        self._base_dir = base_dir
        self._data = {}
        config_path = os.path.join(base_dir, self.CONFIG_RELATIVE)
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def _get_dir(self, key, default_name):
        """Retourne le chemin pour 'key'.

        - Chemin absolu → utilisé tel quel.
        - Chemin relatif → résolu depuis base_dir.
        - Clé absente ou vide → <base_dir>/<default_name>.
        """
        value = self._data.get(key, "").strip()
        if not value:
            return os.path.join(self._base_dir, default_name)
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    def _get_file(self, key):
        """Retourne le chemin de fichier pour 'key'.

        - Chemin absolu dans config.json → utilisé tel quel.
        - Chemin relatif → résolu depuis base_dir (racine du projet).
        - Clé absente ou vide → retourne "".
        """
        value = self._data.get(key, "").strip()
        if not value:
            return ""
        if os.path.isabs(value):
            return value
        return os.path.join(self._base_dir, value)

    @property
    def media_dir(self):
        return self._get_dir("media_dir", "media")

    @property
    def patches_dir(self):
        return self._get_dir("patches_dir", "patches")

    @property
    def samples_dir(self):
        return self._get_dir("samples_dir", "samples")

    @property
    def kits_dir(self):
        return self._get_dir("kits_dir", "kits")

    @property
    def presets_dir(self):
        return self._get_dir("presets_dir", "presets")

    @property
    def click1_file(self):
        return self._get_file("click1_file")

    @property
    def click2_file(self):
        return self._get_file("click2_file")
