#!/usr/bin/env python3
"""
    File: tools/check_specs_tests.py
    Vérifie que docs/SPECS.md liste tous les fichiers tests/test_*.py
    (Phase 7 étape 14c1, docs/DESIGN.md § 14a1 D2), dans l'arborescence du
    projet et dans la table « Tests unitaires ».

    Signale les fichiers absents de l'arborescence, ceux absents de la
    table, et ceux cités mais qui n'existent plus. Pour un fichier absent
    de la table, propose une ligne prête à coller, tirée de la première
    phrase de son docstring.

    Code de sortie : 0 si tout est à jour, 1 sinon.

    Usage:
        python3 tools/check_specs_tests.py
        python3 tools/check_specs_tests.py --root /autre/dépôt

    Date: Sun, 25/10/2026
    Author: Coolbrother
"""

import argparse
import ast
import os
import re
import sys

TEST_RE      = re.compile(r"^test_\w+\.py$")
TREE_HEAD_RE = re.compile(r"^\s*[├└]── tests/\s*$")
TREE_LINE_RE = re.compile(r"^\s+[├└│]")
TREE_FILE_RE = re.compile(r"── (test_\w+\.py)\s*$")
TABLE_RE     = re.compile(r"^\| `(test_\w+\.py)` \|")
DOC_SKIP_RE  = re.compile(r"^(File|Date|Author)\s*:")


def test_files(root):
    """Noms des tests/test_*.py présents sur le disque, triés."""
    tests_dir = os.path.join(root, "tests")
    return sorted(f for f in os.listdir(tests_dir) if TEST_RE.match(f))


def specs_lists(text):
    """(arborescence, table) : ensembles des test_*.py cités dans SPECS.md."""
    tree, table = set(), set()
    in_tree = False
    for line in text.splitlines():
        if TREE_HEAD_RE.match(line):
            in_tree = True
            continue
        if in_tree:
            if not TREE_LINE_RE.match(line):
                in_tree = False
            else:
                m = TREE_FILE_RE.search(line)
                if m:
                    tree.add(m.group(1))
                continue
        m = TABLE_RE.match(line)
        if m:
            table.add(m.group(1))
    return tree, table


def docstring_summary(path):
    """Première phrase du docstring d'en-tête, sans File/Date/Author."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = ast.get_docstring(ast.parse(f.read()))
    except (OSError, SyntaxError, ValueError):
        doc = None
    if not doc:
        return "…"
    lines = [l.strip() for l in doc.splitlines()
             if l.strip() and not DOC_SKIP_RE.match(l.strip())]
    text = " ".join(lines)
    m = re.search(r"\.(\s|$)", text)
    return text[:m.start()] if m else text


def check(root):
    """Liste des lignes du rapport ; vide si tout est à jour."""
    with open(os.path.join(root, "docs", "SPECS.md"), encoding="utf-8") as f:
        tree, table = specs_lists(f.read())
    files = set(test_files(root))
    report = []

    missing_tree = sorted(files - tree)
    if missing_tree:
        report.append("Absents de l'arborescence :")
        report += [f"    ├── {name}" for name in missing_tree]

    missing_table = sorted(files - table)
    if missing_table:
        report.append("Absents de la table (lignes proposées) :")
        for name in missing_table:
            summary = docstring_summary(os.path.join(root, "tests", name))
            report.append(f"| `{name}` | {summary} |")

    stale = sorted((tree | table) - files)
    if stale:
        report.append("Cités dans SPECS.md mais absents de tests/ :")
        for name in stale:
            where = " et ".join(w for w, s in (("arborescence", tree), ("table", table))
                                if name in s)
            report.append(f"    {name} ({where})")
    return report


def main(argv=None):
    default_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    parser = argparse.ArgumentParser(
        description="Vérifie que docs/SPECS.md liste tous les tests/test_*.py.")
    parser.add_argument("--root", default=default_root,
                        help="racine du dépôt (défaut : parent de tools/)")
    args = parser.parse_args(argv)

    report = check(os.path.normpath(args.root))
    if report:
        print("\n".join(report))
        return 1
    print(f"SPECS.md à jour : {len(test_files(args.root))} fichiers de tests listés.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
