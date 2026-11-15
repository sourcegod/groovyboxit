#python3
"""
    File: src/audio/audio_takes.py
    Prises audio des pistes audio (Phase 8 étape 14b1, docs/DESIGN.md
    § Phase 8 étape 14a A3, A7) : dossier « Audios » à côté du .gvp, noms
    « projet_pattern01_piste03_take_001.wav », WAV 24 bits mono ou stéréo,
    copie des prises quand le projet change de nom ou de dossier
    (Enregistrer sous). Les clips (ETYPE_AUDIO) gardent le chemin relatif au
    dossier du .gvp (« Audios/… .wav »).
    Date: Sun, 15/11/2026
    Author: Coolbrother
"""
import os
import re
import shutil

import soundfile as sf

AUDIOS_DIR = "Audios"
SUBTYPE    = "PCM_24"          # WAV 24 bits (A7)


def project_stem(project_path):
    """Nom du projet : le nom du .gvp sans extension."""
    return os.path.splitext(os.path.basename(project_path))[0]


def audios_dir(project_path, audio_dir=""):
    """Dossier des prises : audio_dir (« Chemin des fichiers audios » du
    projet, absolu ou relatif au dossier du .gvp, essai de 14b1) ; par
    défaut « Audios » à côté du .gvp."""
    base = os.path.dirname(os.path.abspath(project_path))
    if not audio_dir:
        return os.path.join(base, AUDIOS_DIR)
    return audio_dir if os.path.isabs(audio_dir) else os.path.normpath(os.path.join(base, audio_dir))


def relative_to_project(project_path, path):
    """Chemin d'un fichier relatif au dossier du .gvp, avec « / » (gardé
    dans les clips et le .gvp, projet déplaçable avec son dossier)."""
    base = os.path.dirname(os.path.abspath(project_path))
    return os.path.relpath(os.path.abspath(path), base).replace(os.sep, "/")


def take_name(project_path, pattern_idx, track_idx, number):
    """« projet_pattern01_piste03_take_001.wav » (pattern, piste et prise
    comptés à partir de 1)."""
    return (f"{project_stem(project_path)}_pattern{pattern_idx + 1:02d}"
            f"_piste{track_idx + 1:02d}_take_{number:03d}.wav")


def next_take(project_path, pattern_idx, track_idx, audio_dir=""):
    """(chemin absolu, chemin relatif au dossier du .gvp) de la prochaine
    prise libre de cette piste de ce pattern."""
    folder = audios_dir(project_path, audio_dir)
    n = 1
    while os.path.exists(os.path.join(folder, take_name(project_path, pattern_idx,
                                                       track_idx, n))):
        n += 1
    path = os.path.join(folder, take_name(project_path, pattern_idx, track_idx, n))
    return path, relative_to_project(project_path, path)


def resolve(project_path, rel_path):
    """Chemin absolu d'un fichier de clip (relatif au dossier du .gvp)."""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(os.path.dirname(os.path.abspath(project_path)), rel_path)


def write_take(path, data, samplerate):
    """Écrit la prise en WAV 24 bits (dossier créé au besoin) ; data :
    tableau (trames,) ou (trames, canaux) en float."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, data, samplerate, subtype=SUBTYPE)
    return path


def renamed(rel_path, old_stem, new_stem):
    """Nom d'une prise pour un projet renommé : le préfixe « ancien_ »
    devient « nouveau_ » (toutes les prises gardent la forme
    projet_pattern_piste_take) ; les autres noms ne changent pas."""
    folder, name = os.path.split(rel_path)
    prefix = old_stem + "_"
    if old_stem != new_stem and name.startswith(prefix) and re.search(
            r"_pattern\d+_piste\d+_take_\d+\.wav$", name):
        name = new_stem + "_" + name[len(prefix):]
    return f"{folder}/{name}" if folder else name


def copy_takes(old_project, new_project, rel_paths, new_audio_dir=""):
    """Enregistrer sous (A3) : copie les prises des clips vers le dossier
    des fichiers audios du nouveau projet (new_audio_dir, défaut Audios),
    renommées au nouveau nom. Retourne ({ancien relatif: nouveau relatif},
    [prises introuvables]). Rien n'est effacé à l'ancien emplacement."""
    old_stem, new_stem = project_stem(old_project), project_stem(new_project)
    folder = audios_dir(new_project, new_audio_dir)
    mapping, missing = {}, []
    for rel in dict.fromkeys(rel_paths):
        name = os.path.basename(renamed(rel, old_stem, new_stem))
        src, dst = resolve(old_project, rel), os.path.join(folder, name)
        new_rel = relative_to_project(new_project, dst)
        mapping[rel] = new_rel
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if not os.path.isfile(src):
            missing.append(rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return mapping, missing


def project_folder_path(path):
    """« Créer un nouveau dossier pour ce projet » (A3) :
    /…/MonProjet.gvp → /…/MonProjet/MonProjet.gvp ; inchangé si le .gvp
    est déjà dans un dossier de son nom."""
    stem = project_stem(path)
    folder = os.path.dirname(os.path.abspath(path))
    if os.path.basename(folder) == stem:
        return path
    return os.path.join(folder, stem, stem + ".gvp")
