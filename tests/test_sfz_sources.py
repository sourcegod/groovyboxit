#python3
"""
    File: tests/test_sfz_sources.py
    Sources de programmes d'un slot Synth SFZ (Phase 8 étape 7g1,
    docs/DESIGN.md § 7a3 Z17, Z18, Z20, Z21 ; avancement 7f1, 7f2) :
    src/audio/sfz_sources.py, module pur, sur des fichiers fabriqués : sorte de
    source, .sfz seul, .bank.xml de Sforzando (<Key> avant <AriaBank>,
    <Define> sans $, chemins relatifs, fichier absent, commentaires),
    dossier (fragments : inclus ou #include introuvable ; numérotation par
    préfixe à partir de 1 ou de 0, numéros libres, doublons, plus de 128),
    banque SFZ JSON (lecture, écriture, chemins relatifs, entrées
    invalides), nom affiché sans préfixe ; 7i1 : #include imbriqués résolus
    depuis le fichier racine (règle de sfizz), nom « parent — dossier »,
    liste des sources d'un dossier d'instruments, programmes factices ;
    7k1 : composition d'une banque (SfzBankDraft), chemins relatifs ou
    absolus d'une banque enregistrée, empreinte d'une source.
    Date: Thu, 05/11/2026
    Author: Coolbrother
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from audio import sfz_sources as ss
from audio.sfz_sources import (read_source, source_kind, fragments, number_programs,
                         folder_program_files, write_sfzbank, display_name,
                         SfzProgram, MAX_PROGRAMS, list_sources, source_entry,
                         folder_name, is_placeholder, SfzBankDraft, source_stamp)


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
    # nom « parent — dossier » (Phase 8 étape 7h1)
    assert src.kind == ss.KIND_FOLDER and src.name == f"{tmp_path.name} — Melodic"
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


# ---------------------------------------------------------------------------
# Fragments : #include résolus depuis le fichier racine (Phase 8 étape 7h1)
# ---------------------------------------------------------------------------

def test_nested_include_resolved_from_root_folder(tmp_path):
    # Comme big-rusty-drums : Programs/01-full.sfz inclut
    # mappings/kick_map.sfz, qui inclut "mappings/kick/k.sfz", relatif à
    # Programs/ (dossier de la racine), pas à mappings/.
    root = _sfz(tmp_path / "Programs" / "01-full.sfz", '#include "mappings/kick_map.sfz"\n')
    mapping = _sfz(tmp_path / "Programs" / "mappings" / "kick_map.sfz",
                   '#include "mappings/kick/k.sfz"\n')
    leaf = _sfz(tmp_path / "Programs" / "mappings" / "kick" / "k.sfz")
    frag = fragments(str(tmp_path))
    assert os.path.normpath(leaf) in frag and os.path.normpath(mapping) in frag
    assert os.path.normpath(root) not in frag


def test_nested_missing_include_does_not_mark_root(tmp_path):
    root = _sfz(tmp_path / "a.sfz", '#include "inc/b.sfz"\n<region>\n')
    _sfz(tmp_path / "inc" / "b.sfz", '#include "absent.sfz"\n')
    assert os.path.normpath(root) not in fragments(str(tmp_path))


def test_include_cycle_terminates(tmp_path):
    a = _sfz(tmp_path / "a.sfz", '#include "b.sfz"\n')
    b = _sfz(tmp_path / "b.sfz", '#include "a.sfz"\n')
    assert {os.path.normpath(a), os.path.normpath(b)} <= fragments(str(tmp_path))


def test_folder_name_is_parent_and_folder(tmp_path):
    assert folder_name(str(tmp_path / "Discord GM" / "Melodic")) == "Discord GM — Melodic"
    assert folder_name(str(tmp_path / "Melodic") + os.sep) == f"{tmp_path.name} — Melodic"


# ---------------------------------------------------------------------------
# Liste des sources (dialogue du slot, Z26)
# ---------------------------------------------------------------------------

@pytest.fixture
def library(tmp_path):
    """Dossier d'instruments : une bibliothèque à .bank.xml et dossier
    Programs (3 programmes, un dossier de morceaux inclus), un dossier GM
    numéroté, un .sfz seul, une banque JSON, un fragment cassé."""
    lib = tmp_path / "Cello"
    _sfz(lib / "Programs" / "01- Archet.sfz", '#include "maps/a_map.sfz"\n')
    _sfz(lib / "Programs" / "02- Molette.sfz", '#include "maps/a_map.sfz"\n')
    _sfz(lib / "Programs" / "03- Pizz.sfz", '#include "maps/parts/p1.sfz"\n')
    _sfz(lib / "Programs" / "maps" / "a_map.sfz", '#include "maps/parts/p1.sfz"\n')
    _sfz(lib / "Programs" / "maps" / "parts" / "p1.sfz")
    _sfz(lib / "Programs" / "maps" / "parts" / "p2.sfz")        # morceau isolé
    _sfz(lib / "Programs" / "maps" / "parts" / "p3.sfz")
    _sfz(lib / "Programs" / "default" / "01- Archet.sfz", '#include "keymap/k.sfz"\n')
    _sfz(lib / "Cello.bank.xml",
         '<AriaBank name="Mon violoncelle">'
         '<AriaProgram name="Archet"><AriaElement path="Programs/01- Archet.sfz"/></AriaProgram>'
         '<AriaProgram name="Pizz"><AriaElement path="Programs/03- Pizz.sfz"/></AriaProgram>'
         '</AriaBank>')
    _sfz(tmp_path / "GM" / "Melodic" / "001-Piano.sfz")
    _sfz(tmp_path / "GM" / "Melodic" / "005-Rhodes.sfz")
    _sfz(tmp_path / "Solo" / "Sax.sfz")
    write_sfzbank(str(tmp_path / "Mes sons.sfzbank.json"), "Mes sons",
                  [(0, "Sax", str(tmp_path / "Solo" / "Sax.sfz"))])
    return tmp_path


def test_list_sources_kinds_labels_and_order(library):
    labels = [e.label for e in list_sources(str(library))]
    assert labels == [
        "Cello/Cello.bank.xml — banque Sforzando, 2 programmes",
        "Cello/Programs — dossier, 3 programmes",
        "Cello/Programs/01- Archet — SFZ",
        "Cello/Programs/02- Molette — SFZ",
        "Cello/Programs/03- Pizz — SFZ",
        "Cello/Programs/maps/parts/p2 — SFZ",
        "Cello/Programs/maps/parts/p3 — SFZ",
        "GM/Melodic — dossier, 2 programmes",
        "GM/Melodic/001-Piano — SFZ",
        "GM/Melodic/005-Rhodes — SFZ",
        "Mes sons.sfzbank.json — banque SFZ, 1 programme",
        "Solo/Sax — SFZ",
    ]


def test_list_sources_excludes_fragments_and_part_folders(library):
    paths = {os.path.relpath(e.path, str(library)) for e in list_sources(str(library))}
    assert "Cello/Programs/maps/a_map.sfz" not in paths          # inclus
    assert "Cello/Programs/maps/parts/p1.sfz" not in paths       # inclus, imbriqué
    assert "Cello/Programs/default/01- Archet.sfz" not in paths  # #include cassé
    # le dossier de morceaux n'est pas une banque : ses fichiers p2 et p3 sont
    # des programmes seuls, mais p1 y est inclus depuis Programs/
    assert "Cello/Programs/maps/parts" not in paths
    assert "Solo" not in paths                                     # un seul programme


def test_list_sources_entries(library):
    entry = next(e for e in list_sources(str(library)) if e.kind == ss.KIND_FOLDER
                 and e.path.endswith("Melodic"))
    assert entry.count == 2 and entry.name == "GM — Melodic"
    assert entry.path == str(library / "GM" / "Melodic")


@pytest.mark.parametrize("root", [None, "", "/nexiste/pas"])
def test_list_sources_without_folder(root):
    assert list_sources(root) == []


def test_source_entry_outside_root_and_empty(tmp_path):
    path = _sfz(tmp_path / "x" / "Seul.sfz")
    entry = source_entry(path)
    assert entry.label == f"{path[:-4]} — SFZ" and entry.count == 1
    os.makedirs(tmp_path / "vide")
    assert source_entry(str(tmp_path / "vide")) is None


# ---------------------------------------------------------------------------
# Programmes factices (essai de 7h1 : banque GM Discord)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, dummy", [
    ("//dummy\n<region> sample=*sine\n", True),
    ("<region>   sample=*sine", True),
    ("/* bloc */\n<region> sample=*sine // fin\n", True),
    ("<region> sample=*sine pitch_keycenter=60\n", False),     # vrai oscillateur réglé
    ("<region> sample=*saw\n", False),
    ("<region> sample=*sine\n<region> sample=*sine\n", False),
    ("<region> sample=piano.wav\n", False),
    ("", False),
])
def test_is_placeholder(tmp_path, text, dummy):
    assert is_placeholder(_sfz(tmp_path / "p.sfz", text)) is dummy


def test_is_placeholder_missing_file(tmp_path):
    assert not is_placeholder(str(tmp_path / "absent.sfz"))


def test_placeholder_flag_and_shown_name(tmp_path):
    _sfz(tmp_path / "GM" / "001-Piano.sfz")
    _sfz(tmp_path / "GM" / "020-Church Organ.sfz", "//dummy\n<region> sample=*sine\n")
    src = read_source(str(tmp_path / "GM"))
    piano, organ = src.programs
    assert not piano.placeholder and piano.shown_name == "001-Piano"
    assert organ.placeholder and organ.shown_name == "020-Church Organ (Dummy)"
    assert organ.name == "020-Church Organ"               # le nom lui-même ne change pas
    assert organ == SfzProgram(19, "020-Church Organ", organ.path)   # comparaison sans le drapeau
    assert display_name(organ.shown_name) == "Church Organ (Dummy)"  # nom de piste


# ---------------------------------------------------------------------------
# Composition d'une banque (Phase 8 étape 7j1, Z21)
# ---------------------------------------------------------------------------

def test_draft_add_numbers_after_the_last():
    d = SfzBankDraft("Pianos")
    assert d.add("/a/Piano.sfz") == 0
    assert d.add("/b/Rhodes.sfz", "Mon Rhodes") == 1
    assert d.add("/c/Orgue.sfz", number=20) == 2          # numéro libre demandé
    assert d.add("/d/Sax.sfz") == 3                        # après le dernier : 21
    assert d.programs == [[0, "Piano", "/a/Piano.sfz"], [1, "Mon Rhodes", "/b/Rhodes.sfz"],
                          [20, "Orgue", "/c/Orgue.sfz"], [21, "Sax", "/d/Sax.sfz"]]


def test_draft_add_taken_or_invalid_number_takes_next_free():
    d = SfzBankDraft("", [(0, "A", "/a.sfz"), (1, "B", "/b.sfz")])
    assert d.add("/c.sfz", number=0) == 2 and d.numbers() == [0, 1, 2]
    assert d.add("/d.sfz", number=500) == 3 and d.numbers()[-1] == 3


def test_draft_add_wraps_and_full_bank():
    d = SfzBankDraft("", [(127, "Fin", "/z.sfz")])
    assert d.add("/a.sfz") == 0                            # après 127 : le premier libre
    d = SfzBankDraft("", [(n, f"p{n}", f"/{n}.sfz") for n in range(MAX_PROGRAMS)])
    assert d.add("/x.sfz") is None and len(d) == MAX_PROGRAMS


def test_draft_remove_and_rename():
    d = SfzBankDraft("", [(0, "A", "/a.sfz"), (5, "B", "/b.sfz")])
    d.rename(1, "  Basse  ")
    d.rename(0, "   ")                                     # nom vide : ignoré
    assert [p[1] for p in d.programs] == ["A", "Basse"]
    d.remove(0)
    assert d.programs == [[5, "Basse", "/b.sfz"]]


def test_draft_set_number_swaps_and_clamps():
    d = SfzBankDraft("", [(0, "A", "/a.sfz"), (1, "B", "/b.sfz"), (9, "C", "/c.sfz")])
    assert d.set_number(0, 9) == 2                         # A prend 9, C prend 0
    assert d.programs == [[0, "C", "/c.sfz"], [1, "B", "/b.sfz"], [9, "A", "/a.sfz"]]
    assert d.set_number(1, 300) == 2 and d.numbers() == [0, 9, 127]
    assert d.set_number(0, -5) == 0 and d.numbers() == [0, 9, 127]


def test_draft_move_swaps_with_neighbour_or_adjacent_number():
    d = SfzBankDraft("", [(0, "A", "/a.sfz"), (1, "B", "/b.sfz"), (5, "C", "/c.sfz")])
    assert d.move(0, +1) == 1 and [p[1] for p in d.programs] == ["B", "A", "C"]
    assert d.move(2, -1) == 1 and [p[1] for p in d.programs] == ["B", "C", "A"]
    assert d.numbers() == [0, 1, 5]
    assert d.move(2, +1) == 2 and d.numbers() == [0, 1, 6]     # sans voisin : +1
    assert d.move(0, -1) == 0 and d.numbers() == [0, 1, 6]     # déjà au 0


def test_draft_save_and_from_file(tmp_path):
    a = _sfz(tmp_path / "lib" / "a.sfz")
    b = _sfz(tmp_path / "lib" / "b.sfz")
    d = SfzBankDraft("Mes sons", [(3, "B", b), (0, "A", a)])
    path = str(tmp_path / "Mes sons.sfzbank.json")
    d.save(path)
    again = SfzBankDraft.from_file(path)
    assert again.name == "Mes sons"
    assert again.programs == [[0, "A", a], [3, "B", b]]


def test_draft_save_without_name_uses_file_name(tmp_path):
    a = _sfz(tmp_path / "a.sfz")
    path = str(tmp_path / "Anonyme.sfzbank.json")
    SfzBankDraft("", [(0, "A", a)]).save(path)
    assert read_source(path).name == "Anonyme"


def test_write_sfzbank_relative_only_below_a_shared_folder(tmp_path):
    inside = _sfz(tmp_path / "lib" / "a.sfz")
    path = str(tmp_path / "banks" / "b.sfzbank.json")
    os.makedirs(tmp_path / "banks")
    write_sfzbank(path, "b", [(0, "in", inside), (1, "root", "/opt/elsewhere/x.sfz")])
    with open(path, encoding="utf-8") as f:
        progs = json.load(f)["programs"]
    assert progs[0]["path"] == "../lib/a.sfz"
    # seul « / » en commun : chemin absolu (pas de « ../../opt/… »)
    assert progs[1]["path"] == "/opt/elsewhere/x.sfz"


# ---------------------------------------------------------------------------
# Empreinte d'une source (correction de l'essai de 7j1)
# ---------------------------------------------------------------------------

def _touch_later(path, text):
    before = os.stat(path).st_mtime_ns
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(path, ns=(before + 10 ** 9, before + 10 ** 9))


def test_source_stamp_of_a_file(tmp_path):
    path = _sfz(tmp_path / "b.sfzbank.json", "{}")
    stamp = source_stamp(path)
    assert source_stamp(path) == stamp
    _touch_later(path, '{"programs": []}')
    assert source_stamp(path) != stamp


def test_source_stamp_of_a_folder(tmp_path):
    _sfz(tmp_path / "GM" / "001-a.sfz")
    _sfz(tmp_path / "GM" / "notes.txt", "x")
    stamp = source_stamp(str(tmp_path / "GM"))
    _sfz(tmp_path / "GM" / "autre.txt", "y")              # pas un .sfz : sans effet
    assert source_stamp(str(tmp_path / "GM")) == stamp
    _sfz(tmp_path / "GM" / "002-b.sfz")
    assert source_stamp(str(tmp_path / "GM")) != stamp


def test_source_stamp_missing(tmp_path):
    assert source_stamp(str(tmp_path / "absent.sfz")) is None

