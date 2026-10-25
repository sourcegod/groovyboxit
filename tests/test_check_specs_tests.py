#python3
"""
    File: tests/test_check_specs_tests.py
    Tests de tools/check_specs_tests.py (Phase 7 étape 14d1, docs/DESIGN.md
    § 14a1 D2) sur un faux dépôt (--root) : tout à jour, fichier absent de
    l'arborescence, absent de la table (ligne proposée tirée du docstring),
    cité mais disparu, code de sortie ; lecture des deux listes de
    SPECS.md et du docstring.
    Date: Sun, 25/10/2026
    Author: Coolbrother
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import check_specs_tests as cst


# ---------------------------------------------------------------------------
# Faux dépôt
# ---------------------------------------------------------------------------

def _doc(summary):
    return (f'"""\n    File: tests/x.py\n    {summary}. Suite du texte.\n'
            f'    Date: Sun, 25/10/2026\n    Author: Coolbrother\n"""\n')


def _specs(tree, table):
    lines = ["# SPECS", "", "```", "groovebox/", "├── src/", "└── tests/",
             "    ├── test_all.sh", "    ├── conftest.py"]
    lines += [f"    ├── {name}" for name in tree]
    if tree:
        lines[-1] = lines[-1].replace("├──", "└──")
    lines += ["```", "", "## Tests unitaires", "", "| Fichier | Couvre |", "|---|---|"]
    lines += [f"| `{name}` | description |" for name in table]
    return "\n".join(lines) + "\n"


def _repo(tmp_path, files, tree=None, table=None, others=("conftest.py", "test_all.sh")):
    """files : {nom: docstring résumé} ; tree / table : noms cités (défaut : files)."""
    os.makedirs(tmp_path / "docs")
    os.makedirs(tmp_path / "tests")
    for name, summary in files.items():
        (tmp_path / "tests" / name).write_text(_doc(summary), encoding="utf-8")
    for name in others:
        (tmp_path / "tests" / name).write_text("", encoding="utf-8")
    tree  = sorted(files) if tree  is None else tree
    table = sorted(files) if table is None else table
    (tmp_path / "docs" / "SPECS.md").write_text(_specs(tree, table), encoding="utf-8")
    return str(tmp_path)


FILES = {"test_a.py": "Tests de A", "test_b.py": "Tests de B"}


# ---------------------------------------------------------------------------
# Rapport et code de sortie
# ---------------------------------------------------------------------------

def test_up_to_date_gives_empty_report_and_exit_0(tmp_path, capsys):
    root = _repo(tmp_path, FILES)
    assert cst.check(root) == []
    assert cst.main(["--root", root]) == 0
    assert "SPECS.md à jour : 2 fichiers de tests listés." in capsys.readouterr().out


def test_missing_from_tree_only(tmp_path):
    root = _repo(tmp_path, FILES, tree=["test_a.py"])
    assert cst.check(root) == ["Absents de l'arborescence :", "    ├── test_b.py"]


def test_missing_from_table_proposes_row_from_docstring(tmp_path):
    root = _repo(tmp_path, FILES, table=["test_b.py"])
    assert cst.check(root) == ["Absents de la table (lignes proposées) :",
                               "| `test_a.py` | Tests de A |"]


def test_missing_from_both_lists(tmp_path):
    root = _repo(tmp_path, {**FILES, "test_c.py": "Tests de C"},
                 tree=sorted(FILES), table=sorted(FILES))
    report = cst.check(root)
    assert "    ├── test_c.py" in report
    assert "| `test_c.py` | Tests de C |" in report


def test_stale_entry_reports_where_it_is_cited(tmp_path):
    root = _repo(tmp_path, FILES,
                 tree=["test_a.py", "test_b.py", "test_old.py"],
                 table=["test_a.py", "test_b.py", "test_old.py", "test_gone.py"])
    report = cst.check(root)
    assert report[0] == "Cités dans SPECS.md mais absents de tests/ :"
    assert "    test_gone.py (table)" in report
    assert "    test_old.py (arborescence et table)" in report


def test_report_sections_in_order(tmp_path):
    root = _repo(tmp_path, {**FILES, "test_c.py": "Tests de C"},
                 tree=["test_a.py", "test_b.py", "test_x.py"], table=["test_a.py", "test_b.py"])
    titles = [l for l in cst.check(root) if l.endswith(":")]
    assert titles == ["Absents de l'arborescence :",
                      "Absents de la table (lignes proposées) :",
                      "Cités dans SPECS.md mais absents de tests/ :"]


def test_problem_gives_exit_1_and_prints_report(tmp_path, capsys):
    root = _repo(tmp_path, FILES, table=["test_a.py"])
    assert cst.main(["--root", root]) == 1
    out = capsys.readouterr().out
    assert "| `test_b.py` | Tests de B |" in out
    assert "à jour" not in out


def test_only_test_py_files_count(tmp_path):
    root = _repo(tmp_path, FILES, others=("conftest.py", "test_all.sh", "helper.py",
                                          "test_notes.txt"))
    assert cst.test_files(root) == ["test_a.py", "test_b.py"]
    assert cst.check(root) == []


# ---------------------------------------------------------------------------
# Lecture de SPECS.md
# ---------------------------------------------------------------------------

def test_specs_lists_reads_tree_and_table_separately():
    tree, table = cst.specs_lists(_specs(["test_a.py"], ["test_b.py"]))
    assert tree  == {"test_a.py"}
    assert table == {"test_b.py"}


def test_tree_block_ends_at_first_non_tree_line():
    text = ("└── tests/\n    ├── test_a.py\n    └── test_b.py\n```\n"
            "Plus loin :\n    ├── test_hors_arbre.py\n")
    tree, _ = cst.specs_lists(text)
    assert tree == {"test_a.py", "test_b.py"}


def test_tree_with_comments_and_nested_tests_dir():
    text = ("groovebox/\n│   └── sub/\n└── tests/\n"
            "    ├── test_a.py     # commentaire\n    └── test_b.py\n")
    tree, _ = cst.specs_lists(text)
    assert tree == {"test_a.py", "test_b.py"}


def test_table_ignores_other_backticked_cells():
    text = "| `pattern.py` | x |\n| `test_a.py` | x |\nvoir `test_b.py` dans le texte\n"
    _, table = cst.specs_lists(text)
    assert table == {"test_a.py"}


# ---------------------------------------------------------------------------
# Docstring
# ---------------------------------------------------------------------------

def test_docstring_summary_skips_header_and_keeps_first_sentence(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text('"""\n    File: tests/test_x.py\n    Tests de la v1.2 du module\n'
                 '    sur deux lignes. Deuxième phrase.\n    Date: x\n"""\n', encoding="utf-8")
    assert cst.docstring_summary(str(p)) == "Tests de la v1.2 du module sur deux lignes"


def test_docstring_summary_without_docstring(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text("import os\n", encoding="utf-8")
    assert cst.docstring_summary(str(p)) == "…"


def test_docstring_summary_with_syntax_error(tmp_path):
    p = tmp_path / "test_x.py"
    p.write_text("def (:\n", encoding="utf-8")
    assert cst.docstring_summary(str(p)) == "…"
