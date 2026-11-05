#python3
"""
    File: src/sfz_sources.py
    Sources de programmes d'un slot Synth SFZ (Phase 8 étape 7f1,
    docs/DESIGN.md § 7a3 Z16-Z18, Z20, Z21) : un slot est une banque de
    programmes SFZ, lue dans
    - un .sfz seul : un programme, le 0 ;
    - un .bank.xml de Sforzando (AriaBank) : les AriaProgram dans l'ordre,
      leurs <Define> passés à sfizz avant le chargement ;
    - un dossier : ses .sfz qui ne sont pas des fragments, numérotés par le
      préfixe de leur nom (« 001-Acoustic Grand Piano » → 0), sinon par
      ordre alphabétique ;
    - une banque SFZ JSON (.sfzbank.json), composée dans l'appli.

    Module pur (ni sfizz ni wx) : lecture de fichiers seulement, testable
    et transposable en C/C++.
    Date: Thu, 05/11/2026
    Author: Coolbrother
"""

import json
import os
import re
from dataclasses import dataclass, field

MAX_PROGRAMS   = 128
BANK_XML_EXT   = ".bank.xml"
SFZBANK_EXT    = ".sfzbank.json"

KIND_SFZ       = "sfz"
KIND_BANK_XML  = "bank_xml"
KIND_FOLDER    = "folder"
KIND_SFZBANK   = "sfzbank"


PLACEHOLDER_SUFFIX = " (Dummy)"


@dataclass(frozen=True)
class SfzProgram:
    """Un programme : numéro (0..127), nom, chemin absolu du .sfz,
    définitions passées à sfizz ((nom sans $, valeur), triées), et s'il
    est un programme factice (essai de 7h1 : une sinusoïde seule, comme 118
    des 128 programmes de la banque GM Discord, en cours d'écriture, qui
    les marque « //dummy »)."""
    program:     int
    name:        str
    path:        str
    defines:     tuple = ()
    placeholder: bool = field(default=False, compare=False)

    @property
    def shown_name(self):
        """Nom montré dans les listes : signale un programme factice."""
        return self.name + (PLACEHOLDER_SUFFIX if self.placeholder else "")

    @property
    def key(self):
        """Ce qui identifie une instance sfizz chargée : fichier et définitions."""
        return (self.path, self.defines)


@dataclass
class SfzSource:
    """Une source lue : chemin, sorte, nom, programmes triés par numéro,
    messages (fichier absent, au-delà de 128 programmes…)."""
    path:     str
    kind:     str
    name:     str
    programs: list = field(default_factory=list)
    messages: list = field(default_factory=list)

    def program(self, number):
        """Le programme number, ou None."""
        for p in self.programs:
            if p.program == number:
                return p
        return None


def source_kind(path):
    """Sorte de source d'un chemin, ou None (inconnue ou absente)."""
    if not path:
        return None
    low = path.lower()
    if os.path.isdir(path):
        return KIND_FOLDER
    if not os.path.isfile(path):
        return None
    if low.endswith(BANK_XML_EXT):
        return KIND_BANK_XML
    if low.endswith(SFZBANK_EXT):
        return KIND_SFZBANK
    if low.endswith(".sfz"):
        return KIND_SFZ
    return None


def read_source(path):
    """Lit la source path ; une source inconnue ou absente donne une
    source sans programme, avec un message."""
    path = os.path.abspath(path) if path else ""
    kind = source_kind(path)
    if kind == KIND_SFZ:
        name = _stem(path)
        return SfzSource(path, kind, name, [_program(0, name, path)])
    if kind == KIND_BANK_XML:
        return _read_bank_xml(path)
    if kind == KIND_FOLDER:
        return _read_folder(path)
    if kind == KIND_SFZBANK:
        return _read_sfzbank(path)
    return SfzSource(path, None, _stem(path), [], [f"source SFZ introuvable : {path}"])


_PLACEHOLDER_TEXT = "<region> sample=*sine"


def is_placeholder(sfz_path):
    """Vrai si le .sfz n'est qu'une sinusoïde : commentaires ôtés, il se
    réduit exactement à « <region> sample=*sine » (programme factice de la
    banque GM Discord). Un instrument qui utilise un oscillateur de sfizz
    avec d'autres réglages n'est pas concerné."""
    try:
        with open(sfz_path, encoding="utf-8", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return False
    return " ".join(_COMMENT_RE.sub(" ", text).split()) == _PLACEHOLDER_TEXT


def _program(number, name, path, defines=()):
    return SfzProgram(number, name, path, defines, is_placeholder(path))


def _stem(path):
    base = os.path.basename(os.path.normpath(path)) if path else ""
    for ext in (BANK_XML_EXT, SFZBANK_EXT, ".sfz"):
        if base.lower().endswith(ext):
            return base[:-len(ext)]
    return base


# ---------------------------------------------------------------------------
# Fragments : .sfz inclus par un autre, ou dont un #include est introuvable
# (Phase 8 étape 7a2 Z6)
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r'^\s*#include\s+"([^"]+)"', re.MULTILINE)
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def _includes(sfz_path):
    """Chemins #include d'un .sfz (commentaires ôtés), tels qu'écrits."""
    try:
        with open(sfz_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    return _INCLUDE_RE.findall(_COMMENT_RE.sub("", text))


def _resolve_include(base_dir, target):
    """Chemin absolu d'un #include. sfizz le résout depuis le dossier du
    fichier racine (celui qu'on charge), y compris pour un #include écrit
    dans un fichier lui-même inclus : base_dir est ce dossier. None si le
    chemin contient une variable ($…), non résoluble ici."""
    if "$" in target:
        return None
    target = target.replace("\\", "/")
    return os.path.normpath(os.path.join(base_dir, target))


def fragments(root):
    """Ensemble des .sfz de l'arborescence root qui ne sont pas des
    programmes (Z6, révisé en 7h1) :
    - inclus par un autre : chaque .sfz est pris comme racine, et la chaîne
      de ses #include est suivie, tous résolus depuis le dossier de cette
      racine, comme le fait sfizz ;
    - ou dont un #include direct est introuvable depuis son propre dossier
      (il ne se charge pas seul : big-rusty-drums/Programs/default/)."""
    files = [os.path.normpath(os.path.join(dp, f)) for dp, _, fs in os.walk(root)
             for f in fs if f.lower().endswith(".sfz")]
    cache = {}

    def includes(path):
        if path not in cache:
            cache[path] = _includes(path)
        return cache[path]

    out = set()
    for f in files:
        base = os.path.dirname(f)
        todo, seen = [f], {f}
        while todo:
            current = todo.pop()
            for target in includes(current):
                resolved = _resolve_include(base, target)
                if resolved is None:
                    continue
                if os.path.isfile(resolved):
                    out.add(resolved)
                    if resolved not in seen:
                        seen.add(resolved)
                        todo.append(resolved)
                elif current == f:
                    out.add(f)                     # #include direct introuvable
    return out


# ---------------------------------------------------------------------------
# Dossier (Z17 b, Z18)
# ---------------------------------------------------------------------------

_PREFIX_RE = re.compile(r"^(\d+)(?=[\s\-_.])")


# Nombre entier en tête, suivi d'un séparateur (-, _, .) ou d'espaces, puis
# du nom : « 2nd Violin » et « 128 » restent tels quels
_DISPLAY_PREFIX_RE = re.compile(r"^\d+(?:\s*[-_.]\s*|\s+)(?=\S)")


def display_name(name):
    """Nom d'un programme sans son préfixe numérique, pour les noms des
    pistes (Phase 8 étape 7f2) : « 001-Acoustic Grand Piano » → « Acoustic
    Grand Piano ». Un nom fait seulement de chiffres reste tel quel."""
    stripped = _DISPLAY_PREFIX_RE.sub("", name or "", count=1)
    return stripped or (name or "")


def number_programs(names):
    """Numéros de programme d'une liste de noms de fichiers (Z18) :
    {nom: numéro}, au plus MAX_PROGRAMS, et la liste des noms écartés.
    Préfixe numérique (« 001-… ») : numérotation à partir de 1 (001 → 0),
    ou à partir de 0 si un nom porte le préfixe 0 ; les noms sans préfixe
    (ou à préfixe hors plage, ou en double) prennent ensuite les numéros
    libres, par ordre alphabétique."""
    names = sorted(names, key=lambda n: n.lower())
    prefixes = {}
    for n in names:
        m = _PREFIX_RE.match(n)
        if m:
            prefixes[n] = int(m.group(1))
    zero_based = 0 in prefixes.values()
    taken, numbers, rest = set(), {}, []
    for n in names:
        if n in prefixes:
            p = prefixes[n] if zero_based else prefixes[n] - 1
            if 0 <= p < MAX_PROGRAMS and p not in taken:
                numbers[n] = p
                taken.add(p)
                continue
        rest.append(n)
    free = (p for p in range(MAX_PROGRAMS) if p not in taken)
    dropped = []
    for n in rest:
        p = next(free, None)
        if p is None:
            dropped.append(n)
        else:
            numbers[n] = p
    return numbers, dropped


def folder_program_files(folder, frag=None):
    """.sfz du dossier (sans ses sous-dossiers) qui sont des programmes.
    frag : fragments déjà calculés pour une arborescence qui contient le
    dossier (list_sources), sinon calculés pour le dossier."""
    frag = fragments(folder) if frag is None else frag
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return []
    return [os.path.join(folder, f) for f in entries
            if f.lower().endswith(".sfz")
            and os.path.isfile(os.path.join(folder, f))
            and os.path.normpath(os.path.join(folder, f)) not in frag]


def _read_folder(folder):
    files = folder_program_files(folder)
    by_name = {_stem(f): f for f in files}
    numbers, dropped = number_programs(list(by_name))
    programs = sorted((_program(numbers[n], n, by_name[n]) for n in numbers),
                      key=lambda p: p.program)
    messages = [f"{len(dropped)} programme(s) au-delà de {MAX_PROGRAMS} ignoré(s)"] \
        if dropped else []
    if not programs:
        messages.append(f"aucun programme SFZ dans {folder}")
    return SfzSource(folder, KIND_FOLDER, folder_name(folder), programs, messages)


def folder_name(folder):
    """Nom d'une source dossier : « parent — dossier » (Phase 8 étape 7h1) ;
    « Melodic » ou « Programs » seuls ne disent pas de quel instrument il
    s'agit (« Discord GM — Melodic »)."""
    folder = os.path.normpath(folder)
    parent = os.path.basename(os.path.dirname(folder))
    return f"{parent} — {_stem(folder)}" if parent else _stem(folder)


# ---------------------------------------------------------------------------
# .bank.xml de Sforzando (Z17 a)
# ---------------------------------------------------------------------------

def _read_bank_xml(path):
    """AriaBank : le fichier commence souvent par <Key> avant <AriaBank>
    (deux éléments racines, XML mal formé pour ElementTree) : lu par
    expressions régulières, attribut par attribut."""
    name = _stem(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return SfzSource(path, KIND_BANK_XML, name, [], [f"banque illisible : {e}"])
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    bank = re.search(r"<AriaBank\b([^>]*)>", text)
    if bank:
        name = _attr(bank.group(1), "name") or name
    defines = []
    for m in re.finditer(r"<Define\b([^>]*)/?>", text):
        dname, value = _attr(m.group(1), "name"), _attr(m.group(1), "value")
        if dname:
            defines.append((dname.lstrip("$"), value or ""))   # sfizz : nom sans $
    defines = tuple(sorted(defines))
    base = os.path.dirname(path)
    programs, messages = [], []
    for m in re.finditer(r"<AriaProgram\b([^>]*)>(.*?)</AriaProgram>", text, re.DOTALL):
        number = len(programs) + len(messages)
        pname = _attr(m.group(1), "name") or f"Programme {number + 1}"
        elem = re.search(r"<AriaElement\b([^>]*)/?>", m.group(2))
        rel = _attr(elem.group(1), "path") if elem else None
        sfz = os.path.normpath(os.path.join(base, rel.replace("\\", "/"))) if rel else None
        if number >= MAX_PROGRAMS:
            messages.append(f"programme « {pname} » au-delà de {MAX_PROGRAMS} ignoré")
        elif sfz and os.path.isfile(sfz):
            programs.append(_program(number, pname, sfz, defines))
        else:
            messages.append(f"programme « {pname} » : fichier introuvable")
    return SfzSource(path, KIND_BANK_XML, name, programs, messages)


def _attr(attrs, key):
    m = re.search(r'\b%s\s*=\s*"([^"]*)"' % re.escape(key), attrs)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Banque SFZ JSON (Z17 c, Z21)
# ---------------------------------------------------------------------------

def _read_sfzbank(path):
    name = _stem(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return SfzSource(path, KIND_SFZBANK, name, [], [f"banque SFZ illisible : {e}"])
    if not isinstance(data, dict):
        return SfzSource(path, KIND_SFZBANK, name, [], ["banque SFZ illisible"])
    name = data.get("name") if isinstance(data.get("name"), str) and data.get("name") else name
    base = os.path.dirname(path)
    programs, messages, taken = [], [], set()
    for entry in data.get("programs", []) if isinstance(data.get("programs"), list) else []:
        if not isinstance(entry, dict):
            continue
        number, rel = entry.get("program"), entry.get("path")
        pname = entry.get("name") if isinstance(entry.get("name"), str) else ""
        if not isinstance(number, int) or isinstance(number, bool) \
                or not 0 <= number < MAX_PROGRAMS or number in taken:
            messages.append(f"programme « {pname or rel} » : numéro invalide ou en double")
            continue
        if not isinstance(rel, str) or not rel:
            messages.append(f"programme {number} : sans fichier")
            continue
        sfz = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))
        if not os.path.isfile(sfz):
            messages.append(f"programme {number} « {pname or _stem(sfz)} » : fichier introuvable")
            continue
        taken.add(number)
        programs.append(_program(number, pname or _stem(sfz), sfz))
    programs.sort(key=lambda p: p.program)
    return SfzSource(path, KIND_SFZBANK, name, programs, messages)


def write_sfzbank(path, name, programs):
    """Écrit une banque SFZ JSON : programs = [(numéro, nom, chemin .sfz)],
    chemins rendus relatifs au fichier (portable) quand c'est possible."""
    base = os.path.dirname(os.path.abspath(path))
    entries = []
    for number, pname, sfz in sorted(programs):
        try:
            rel = os.path.relpath(sfz, base)
        except ValueError:              # autre lecteur (Windows)
            rel = sfz
        entries.append({"program": int(number), "name": pname, "path": rel})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "programs": entries}, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Liste des sources d'un dossier d'instruments (Phase 8 étape 7h1, § 7a3 Z26)
# ---------------------------------------------------------------------------

KIND_LABELS = {KIND_BANK_XML: "banque Sforzando", KIND_SFZBANK: "banque SFZ",
               KIND_FOLDER: "dossier", KIND_SFZ: "SFZ"}


@dataclass(frozen=True)
class SourceEntry:
    """Une source proposée par le dialogue du slot : chemin absolu, sorte,
    nom, nombre de programmes, libellé (chemin relatif d'abord, pour la
    recherche au clavier dans la liste)."""
    path:  str
    kind:  str
    name:  str
    count: int
    label: str


def _plural(n):
    return f"{n} programme{'s' if n > 1 else ''}"


def source_entry(path, root=None):
    """SourceEntry d'un chemin (None s'il n'a aucun programme)."""
    src = read_source(path)
    if not src.programs:
        return None
    rel = os.path.relpath(src.path, root) if root else src.path
    if src.kind in (KIND_SFZ, KIND_BANK_XML, KIND_SFZBANK):
        rel = rel[:-len(".sfz")] if src.kind == KIND_SFZ else rel
    label = f"{rel} — {KIND_LABELS[src.kind]}"
    if src.kind != KIND_SFZ:
        label += f", {_plural(len(src.programs))}"
    return SourceEntry(src.path, src.kind, src.name, len(src.programs), label)


def list_sources(root):
    """Sources de l'arborescence root, triées par chemin : chaque .bank.xml,
    chaque banque SFZ JSON, chaque dossier d'au moins deux programmes et
    chaque .sfz qui est un programme (pas un fragment).
    Un dossier n'est proposé que si ses programmes sont les mêmes, analysé
    seul (comme le lira le moteur) ou dans toute l'arborescence : un dossier
    dont des fichiers sont inclus depuis ailleurs est un dossier de
    morceaux (big-rusty-drums/Programs/mappings/kick_24), pas une banque."""
    if not root or not os.path.isdir(root):
        return []
    frag = fragments(root)
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        programs = folder_program_files(dirpath, frag)
        if len(programs) >= 2 and programs == folder_program_files(dirpath):
            entry = source_entry(dirpath, root)
            if entry is not None:
                entries.append(entry)
        for f in sorted(filenames):
            path = os.path.join(dirpath, f)
            low = f.lower()
            if low.endswith(BANK_XML_EXT) or low.endswith(SFZBANK_EXT) \
                    or path in programs:
                entry = source_entry(path, root)
                if entry is not None:
                    entries.append(entry)
    return sorted(entries, key=lambda e: e.label.lower())

