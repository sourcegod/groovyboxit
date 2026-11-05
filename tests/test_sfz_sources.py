#python3
"""
    File: tests/test_sfz_sources.py
    Sources de programmes d'un slot Synth SFZ (Phase 8 étape 7g1,
    docs/DESIGN.md § 7a3 Z17, Z18, Z20, Z21 ; avancement 7f1, 7f2) :
    src/sfz_sources.py, module pur, sur des fichiers fabriqués : sorte de
    source, .sfz seul, .bank.xml de Sforzando (<Key> avant <AriaBank>,
    <Define> sans $, chemins relatifs, fichier absent, commentaires),
    dossier (fragments : inclus ou #include introuvable ; numérotation par
    préfixe à partir de 1 ou de 0, numéros libres, doublons, plus de 128),
    banque SFZ JSON (lecture, écriture, chemins relatifs, entrées
    invalides), nom affiché sans préfixe.
    Date: Thu, 05/11/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import sfz_sources as ss
from sfz_sources import (read_source, source_kind, fragments, number_programs,
                         folder_program_files, write_sfzbank, display_name,
                         SfzProgram, MAX_PROGRAMS)


def _sfz(path, text="<region> sample=a.wav\n"):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


# ---------------------------------------------------------------------------
# Sorte de source, .sfz seul
# ---------------------------------------------------------------------------

def test_source_kind(tmp_path):
    single = _sfz(tmp_path / "piano.sfz")
    bank = _sfz(tmp_path / "Lib.bank.xml", "<AriaBank/>")
    jbank = _sfz(tmp_path / "Mes pianos.sfzbank.json", "{}")
    other = _sfz(tmp_path / "notes.txt", "")
    assert source_kind(single) == ss.KIND_SFZ
    assert source_kind(bank) == ss.KIND_BANK_XML
    assert source_kind(jbank) == ss.KIND_SFZBANK
    assert source_kind(str(tmp_path)) == ss.KIND_FOLDER
    assert source_kind(other) is None
    assert source_kind(str(tmp_path / "absent.sfz")) is None
    assert source_kind("") is None and source_kind(None) is None


def test_single_sfz_is_program_0(tmp_path):
    path = _sfz(tmp_path / "Grand Piano.sfz")
    src = read_source(path)
    assert src.kind == ss.KIND_SFZ and src.name == "Grand Piano"
    assert src.programs == [SfzProgram(0, "Grand Piano", path)]
    assert src.messages == []
    assert src.program(0).path == path and src.program(1) is None


def test_unknown_source_has_no_program_and_a_message(tmp_path):
    src = read_source(str(tmp_path / "absent.sfz"))
    assert src.programs == [] and src.kind is None
    assert "introuvable" in src.messages[0]


def test_program_key_is_file_and_defines():
    p = SfzProgram(3, "x", "/a/b.sfz", (("d", "1"),))
    assert p.key == ("/a/b.sfz", (("d", "1"),))


# ---------------------------------------------------------------------------
# .bank.xml de Sforzando (Z17 a)
# ---------------------------------------------------------------------------

BANK_XML = """<?xml version="1.0" ?>
<Key>8A6D9B5F</Key>
<AriaBank id="1" name="Mon violoncelle" vendor="X">
  <!-- <AriaProgram name="commenté"><AriaElement path="Programs/c.sfz"/></AriaProgram> -->
  <Define name="$sample_dir" value="../Samples"/>
  <Define name="$tune" value="12"/>
  <AriaGUI path="GUI/info.xml" target="*ARIA_INFO" />
  <AriaProgram name="01- Archet" gui="GUI/a.xml"> <AriaElement path="Programs/a.sfz"/> </AriaProgram>
  <AriaProgram  name="02- Pizzicato"  gui="GUI/b.xml">
      <AriaElement  path="Programs\\b.sfz"/>
  </AriaProgram>
  <AriaProgram name="03- Absent"><AriaElement path="Programs/absent.sfz"/></AriaProgram>
</AriaBank>
"""


def test_bank_xml_programs_in_order(tmp_path):
    a = _sfz(tmp_path / "Programs" / "a.sfz")
    b = _sfz(tmp_path / "Programs" / "b.sfz")
    path = _sfz(tmp_path / "Cello.bank.xml", BANK_XML)
    src = read_source(path)
    assert src.kind == ss.KIND_BANK_XML and src.name == "Mon violoncelle"
    defines = (("sample_dir", "../Samples"), ("tune", "12"))     # sans $
    assert src.programs == [SfzProgram(0, "01- Archet", a, defines),
                            SfzProgram(1, "02- Pizzicato", b, defines)]


def test_bank_xml_missing_program_file_reported(tmp_path):
    _sfz(tmp_path / "Programs" / "a.sfz")
    _sfz(tmp_path / "Programs" / "b.sfz")
    src = read_source(_sfz(tmp_path / "Cello.bank.xml", BANK_XML))
    assert src.messages == ["programme « 03- Absent » : fichier introuvable"]
    assert "commenté" not in [p.name for p in src.programs]


def test_bank_xml_without_name_uses_file_name(tmp_path):
    a = _sfz(tmp_path / "a.sfz")
    path = _sfz(tmp_path / "Lib.bank.xml",
                '<AriaBank><AriaProgram><AriaElement path="a.sfz"/></AriaProgram></AriaBank>')
    src = read_source(path)
    assert src.name == "Lib"
    assert src.programs == [SfzProgram(0, "Programme 1", a)]


def test_bank_xml_unreadable(tmp_path, monkeypatch):
    path = _sfz(tmp_path / "Lib.bank.xml", "")
    def boom(*a, **k):
        raise OSError("refusé")
    monkeypatch.setattr("builtins.open", boom)
    src = ss._read_bank_xml(path)
    assert src.programs == [] and "illisible" in src.messages[0]


# ---------------------------------------------------------------------------
# Fragments (Z6)
# ---------------------------------------------------------------------------

def test_fragments_included_and_broken_include(tmp_path):
    main = _sfz(tmp_path / "Programs" / "main.sfz",
                '#include "maps/map.sfz"\n// #include "maps/commente.sfz"\n<region>\n')
    mapping = _sfz(tmp_path / "Programs" / "maps" / "map.sfz")
    commented = _sfz(tmp_path / "Programs" / "maps" / "commente.sfz")
    broken = _sfz(tmp_path / "Programs" / "default" / "main.sfz", '#include "keymap/k.sfz"\n')
    variable = _sfz(tmp_path / "Programs" / "var.sfz", '#include "$dir/x.sfz"\n<region>\n')
    frag = fragments(str(tmp_path))
    assert os.path.normpath(mapping) in frag
    assert os.path.normpath(broken) in frag        # #include introuvable
    assert os.path.normpath(main) not in frag
    assert os.path.normpath(commented) not in frag  # include en commentaire ignoré
    assert os.path.normpath(variable) not in frag   # variable : non résoluble, gardé


def test_folder_program_files_skip_fragments_and_subfolders(tmp_path):
    a = _sfz(tmp_path / "01-a.sfz", '#include "inc.sfz"\n')
    _sfz(tmp_path / "inc.sfz")
    _sfz(tmp_path / "sub" / "02-b.sfz")
    _sfz(tmp_path / "notes.txt")
    assert folder_program_files(str(tmp_path)) == [a]


# ---------------------------------------------------------------------------
# Numérotation d'un dossier (Z18)
# ---------------------------------------------------------------------------

def test_prefix_from_one():
    numbers, dropped = number_programs(["001-Piano", "002-Bright", "128-Gunshot"])
    assert numbers == {"001-Piano": 0, "002-Bright": 1, "128-Gunshot": 127}
    assert dropped == []


def test_prefix_from_zero_when_a_file_has_0():
    numbers, _ = number_programs(["000-Piano", "001-Bright", "5 Flute"])
    assert numbers == {"000-Piano": 0, "001-Bright": 1, "5 Flute": 5}


def test_unprefixed_take_free_numbers_alphabetically():
    numbers, _ = number_programs(["Zeta", "002-Two", "alpha", "001-One"])
    assert numbers == {"001-One": 0, "002-Two": 1, "alpha": 2, "Zeta": 3}


def test_duplicate_or_out_of_range_prefix_takes_a_free_number():
    numbers, _ = number_programs(["001-a", "001-b", "300-c", "2nd Violin"])
    assert numbers["001-a"] == 0
    # Les autres prennent les numéros libres, par ordre alphabétique :
    # 001-b (doublon), 2nd Violin (« 2nd » n'est pas un préfixe), 300-c (hors plage)
    assert numbers["001-b"] == 1
    assert numbers["2nd Violin"] == 2
    assert numbers["300-c"] == 3


def test_prefix_needs_a_separator():
    numbers, _ = number_programs(["10Piano", "3.Flute", "7_Organ", "9 Harp"])
    assert numbers["3.Flute"] == 2 and numbers["7_Organ"] == 6 and numbers["9 Harp"] == 8
    assert numbers["10Piano"] == 0           # pas de séparateur : numéro libre


def test_more_than_128_programs_dropped():
    names = [f"p{i:03d}" for i in range(130)]
    numbers, dropped = number_programs(names)
    assert len(numbers) == MAX_PROGRAMS and dropped == ["p128", "p129"]


def test_folder_source(tmp_path):
    p1 = _sfz(tmp_path / "Melodic" / "001-Acoustic Grand Piano.sfz")
    p2 = _sfz(tmp_path / "Melodic" / "049-String Ensemble 1.sfz")
    src = read_source(str(tmp_path / "Melodic"))
    assert src.kind == ss.KIND_FOLDER and src.name == "Melodic"
    assert src.programs == [SfzProgram(0, "001-Acoustic Grand Piano", p1),
                            SfzProgram(48, "049-String Ensemble 1", p2)]
    assert src.program(48).path == p2 and src.program(1) is None


def test_empty_folder_and_too_many(tmp_path):
    os.makedirs(tmp_path / "vide")
    assert read_source(str(tmp_path / "vide")).messages == [
        f"aucun programme SFZ dans {tmp_path / 'vide'}"]
    for i in range(130):
        _sfz(tmp_path / "plein" / f"p{i:03d}.sfz")
    src = read_source(str(tmp_path / "plein"))
    assert len(src.programs) == MAX_PROGRAMS
    assert src.messages == ["2 programme(s) au-delà de 128 ignoré(s)"]


# ---------------------------------------------------------------------------
# Banque SFZ JSON (Z17 c, Z21)
# ---------------------------------------------------------------------------

def test_sfzbank_round_trip_with_relative_paths(tmp_path):
    a = _sfz(tmp_path / "libs" / "A" / "piano.sfz")
    b = _sfz(tmp_path / "libs" / "B" / "rhodes.sfz")
    path = str(tmp_path / "banks" / "Mes pianos.sfzbank.json")
    os.makedirs(tmp_path / "banks")
    write_sfzbank(path, "Mes pianos", [(5, "Rhodes", b), (0, "Piano", a)])
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"name": "Mes pianos", "programs": [
        {"program": 0, "name": "Piano", "path": "../libs/A/piano.sfz"},
        {"program": 5, "name": "Rhodes", "path": "../libs/B/rhodes.sfz"}]}
    src = read_source(path)
    assert src.kind == ss.KIND_SFZBANK and src.name == "Mes pianos"
    assert src.programs == [SfzProgram(0, "Piano", a), SfzProgram(5, "Rhodes", b)]
    assert src.messages == []


def test_sfzbank_invalid_entries_reported(tmp_path):
    a = _sfz(tmp_path / "a.sfz")
    path = _sfz(tmp_path / "x.sfzbank.json", json.dumps({"programs": [
        {"program": 0, "path": "a.sfz"},
        {"program": 0, "name": "double", "path": "a.sfz"},
        {"program": 200, "path": "a.sfz"},
        {"program": True, "path": "a.sfz"},
        {"program": 1},
        {"program": 2, "path": "absent.sfz"},
        "pas un dict"]}))
    src = read_source(path)
    assert src.name == "x"                          # pas de nom : celui du fichier
    assert src.programs == [SfzProgram(0, "a", a)]  # nom vide : celui du .sfz
    assert len(src.messages) == 5


@pytest.mark.parametrize("text", ["pas du json", "[1, 2]"])
def test_sfzbank_unreadable(tmp_path, text):
    src = read_source(_sfz(tmp_path / "x.sfzbank.json", text))
    assert src.programs == [] and "illisible" in src.messages[0]


def test_sfzbank_absolute_path_kept(tmp_path):
    a = _sfz(tmp_path / "abs" / "a.sfz")
    path = _sfz(tmp_path / "b" / "x.sfzbank.json",
                json.dumps({"programs": [{"program": 3, "name": "A", "path": a}]}))
    assert read_source(path).programs == [SfzProgram(3, "A", a)]


# ---------------------------------------------------------------------------
# Nom affiché dans les noms des pistes (7f2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, shown", [
    ("001-Acoustic Grand Piano", "Acoustic Grand Piano"),
    ("01- Bowed (velocity layer)", "Bowed (velocity layer)"),
    ("007 Harpsichord", "Harpsichord"),
    ("10_Piano", "Piano"),
    ("03.Flute", "Flute"),
    ("SamsSonor", "SamsSonor"),
    ("2nd Violin", "2nd Violin"),
    ("128", "128"),
    ("", ""),
    (None, ""),
])
def test_display_name(name, shown):
    assert display_name(name) == shown
