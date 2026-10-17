# Design — GroovyboxIt

Historique des plans de conception discutés avant implémentation, chantier
par chantier. Complète `SPECS.md` (état d'avancement) et les commits (le
« comment ») en gardant la trace du « pourquoi » et des alternatives écartées.

---

## Phase 7 étape 1a — Standardisation de `TapeEvent`

### Origine du besoin

`TapeEvent = namedtuple("etype", "note", "vel", "dur", "bend")` (`pattern.py`)
traite GRID différemment de KIT/PATCH : la durée d'une note GRID vient de
`voice_manager.get_duration_ms(pad)` (réglage global de la voix, partagé par
toutes ses occurrences dans tout pattern qui utilise ce banc de voix), pas
d'un champ propre à l'événement — contrairement à KIT/PATCH où `dur` est un
champ par-événement. Ça a bloqué Numpad1/3 (raccourcir/rallonger une note
dans l'éditeur MIDI, Phase 6 étape 7d) sur les notes GRID.

Par ailleurs, un champ « canal » MIDI manque à tous les `etype` (utile pour
la conformité norme MIDI et un futur Import/Export MIDI).

Décision du 2026-07-24 : reporter volontairement ce chantier ("nettement
plus tard"), terminer l'étape 7 sans durée par-événement pour GRID,
documenter le manque, ne pas relancer tant que l'utilisateur ne le
redemande pas lui-même. Remis sur la table le 2026-09-17, juste après la
clôture de la Phase 6 étape 12a (refactorisation `midi_editor_window.py`).

### État des lieux constaté en code (2026-09-18)

- `_tape = {(track, bar, step): [TapeEvent, ...]}` — la position est la
  **clé du dict**, pas un champ de l'événement.
- `_bend_tape`/`_mod_tape` utilisent déjà un modèle différent : liste plate
  par piste de tuples `(offset_float, valeur)` — le temps est un **champ**,
  offset cumulé sur tout le pattern (`bar * num_steps + step`), pas un
  couple `(bar, step)` séparé.
- L'éditeur MIDI (`midi_editor.py`, mode « Tous les événements ») a déjà une
  3ᵉ représentation : des dicts `{"etype":, "pad"/"note":, "vel":, "dur":,
  "bend":...}` utilisés pour l'édition avant reconversion en `TapeEvent`.
- `dialogs_temporal.py` (`_EVT_TYPE_LABELS`) anticipe déjà 5 types futurs :
  CC générique, Program Change, Poly Aftertouch, Channel Pressure,
  SysEx/Meta — la nouvelle structure doit les accueillir sans nouveau
  refactor.
- 58 sites de construction/lecture de `TapeEvent`, répartis sur 6 fichiers
  source (`pattern.py`, `drum_player.py`, `track_editor.py`,
  `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py`) + 8 fichiers
  de tests.
- Aucun champ `channel` nulle part actuellement.

### Décisions de design validées

**1. Modèle de stockage `_tape`** → passer à des **listes plates par
piste**, alignées sur le modèle déjà utilisé par `_bend_tape`/`_mod_tape`
(temps = champ `time`, pas une clé de dict). `time` = offset flottant
cumulé sur tout le pattern, même convention que `_bend_tape`/`_mod_tape`.

Alternative écartée : garder le dict `{(track,bar,step): [...]}` en
ajoutant juste `channel` sur `TapeEvent` — changement minimal, mais `time`
resterait implicite (clé du dict), ce qui ne répond pas vraiment à la
demande d'un champ `time` uniforme sur tout événement.

Conséquence à traiter en implémentation : `get_cell`/`set_cell` (accès
grille 16×16, très fréquents côté UI) perdent le lookup O(1) par clé dict
direct. Prévoir un **index secondaire** `{(track, time): [événements]}`
maintenu à côté de la liste plate (reconstruit incrémentalement à
l'insertion/suppression, jamais recalculé en entier sauf
`copy_from`/`load_pattern`), pour ne pas introduire de régression de perf
sur la grille.

**Écart constaté à l'implémentation (étape 1c, 2026-09-19)** : l'index
secondaire n'a PAS été construit. Pendant 1c, l'analyse du vrai périmètre
(correctif 1b ci-dessous) a montré que `_tape` est pokée directement en
style dict par de nombreux fichiers (pas seulement via `get_cell`/`set_cell`)
— un index tenu à jour de façon incrémentale serait désynchronisé à chaque
poke direct externe (`pattern._tape[t].append(...)`, filtrage in-place,
etc.), ce qui aurait introduit des bugs de correction silencieux, pires
qu'une régression de perf. Choix fait : `get_cell`/`set_cell`/etc. font un
scan linéaire de la liste de la piste (`O(événements de la piste)` au lieu
de `O(1)`). Accepté comme compromis pragmatique pour une appli desktop
Python (pas de contrainte temps réel dur sur le rendu de grille) ; à
reconsidérer seulement si un vrai problème de perf est mesuré — la bonne
prochaine étape serait alors de centraliser les mutations de `_tape`
derrière une API `Pattern` unique (au lieu du style actuel où les fichiers
consommateurs accèdent à l'attribut directement) avant de pouvoir tenir un
index de façon sûre.

**2. Structure Python de l'événement** → **dataclass** avec champs communs
+ payload en dict :

```python
@dataclass
class TapeEvent:
    time: float                    # offset en steps cumulés (piste)
    etype: str                     # ETYPE_GRID / ETYPE_KIT / ETYPE_PATCH / futurs
    dur: float = 0
    channel: int = 0
    payload: dict = field(default_factory=dict)
    # ex. payload GRID:  {"pad": int, "vel": int}
    #     payload KIT:   {"note": int, "vel": int}
    #     payload PATCH: {"note": int, "vel": int, "bend": int}
    #     futurs CC/Aftertouch/SysEx : champs propres dans payload
```

Alternatives écartées : namedtuple élargi (s'alourdirait à chaque type
futur, champs `None` non pertinents selon le type) ; dict à deux niveaux
`{"time":, "payload": {...}}` (cohérent avec la représentation déjà
utilisée dans `midi_editor.py`, mais perd l'accès par attribut `ev.note`
utilisé partout ailleurs dans le code).

**3. Précédence durée GRID** → la **voix reste la référence par défaut**
(`dur=0`/`None` sur l'événement → fallback `voice_manager.get_duration_ms(pad)`
comme aujourd'hui) ; si l'événement porte une durée explicite (réglée via
Numpad1/3 dans l'éditeur), elle prime **pour cette occurrence uniquement**.
Rétrocompatible avec le comportement actuel (changer la durée du pad
change toujours toutes ses occurrences par défaut) et débloque Numpad1/3
sur GRID.

Alternative écartée : l'événement copie systématiquement la durée de la
voix à sa création — romprait le comportement actuel où changer la durée
du pad affecte toutes ses occurrences déjà posées.

**4. Identifiant unique `id` (ajouté 2026-09-19, demande explicite)** →
`TapeEvent` porte un `id` auto-incrémenté à la création (`TapeEvent._counter`,
même convention que `Pattern._id`). Décisions validées avec l'utilisateur :
- **Jamais préservé** lors d'une reconstruction représentant la même note
  modifiée (quantize déplace, resize retemporise, l'éditeur MIDI change
  durée/vélocité/pitch/position) : chaque construction obtient un id neuf,
  comme `Pattern._id` qui n'est jamais préservé non plus entre deux
  instances. Alternative écartée : préserver l'id à travers ces
  reconstructions pour une identité de note stable — aurait demandé de
  retoucher tous les sites qui reconstruisent un `TapeEvent` (quantize,
  resize, double_bars, édition), pour un besoin qui n'existe pas
  aujourd'hui (rien dans l'architecture actuelle ne dépend d'une identité
  stable across edits — les appelants se resynchronisent déjà via les
  dicts `event_info` retournés par les méthodes d'édition).
- **Jamais sérialisé** dans `.gvp`/`tape_v2` — identifiant de session
  uniquement, comme `Pattern._id`.
- `__eq__`/`__hash__` ignorent `id` (et `time`) : la comparaison reste par
  valeur, comme avant.
- Motivation explicite de l'utilisateur : une bonne partie du cœur
  audio/MIDI sera réimplémentée en C/C++ plus tard pour la performance —
  choisir des structures faciles à porter sans trop casser la
  compatibilité. Un entier auto-incrémenté est l'équivalent direct d'une
  clé d'entité dans une table/array C (`static uint64_t next_id; id =
  next_id++;`), contrairement par exemple à l'identité d'objet Python.
  Appliqué immédiatement : `drum_player.py` suivait les notes patch en
  cours d'enregistrement (`_pending_patch`, note_on → note_off) par
  identité d'objet Python (`is`) — remplacé par un suivi par `id`, qui a un
  sens dans un futur portage C/C++.
- Reste un point de vigilance général pour la suite du chantier (pas
  retouché aujourd'hui) : `payload` en dict Python (clé→valeur arbitraire)
  est un choix pratique côté Python mais n'a pas d'équivalent direct en C
  (qui préférerait une union taguée ou des champs fixes par type) — à
  garder en tête si/quand le portage C/C++ du cœur audio/MIDI est
  réellement entrepris, sans le anticiper inutilement maintenant.

### Portée explicitement exclue de ce chantier

Les nouveaux types eux-mêmes (CC générique, Program Change, Poly
Aftertouch, Channel Pressure, SysEx/Meta) ne sont **pas** dans le périmètre
de cette standardisation — juste s'assurer que la structure les accueille
sans nouveau refactor plus tard.

### Suite prévue (après ce chantier)

Revenir sur l'affichage de la liste d'événements de `MidiEditorWindow`
(mode Ctrl+2 « Tous les événements ») pour la mettre à jour — notamment le
format de ligne par type (note/CC/etc.) et le champ « canal », qui n'existe
pas encore dans le modèle actuel. Ne pas retravailler ce format avant que
cette standardisation soit faite.

---

## Phase 7 étape 1b — Format `.gvp` et découpage en commits

### Format `.gvp` (nouveau)

- Nouvelle clé `"tape_v2"` : liste par piste (même convention que
  `bend_tape`/`mod_tape`), chaque piste = liste d'événements
  `[time, etype, dur, channel, payload]`.
- `payload` est un dict JSON-natif : `{"pad": int, "vel": int}` pour GRID,
  `{"note": int, "vel": int}` pour KIT, `{"note": int, "vel": int, "bend":
  int}` pour PATCH.
- `to_dict()` n'écrit **plus** `curpattern`/`kit_tape`/`patch_tape` une fois
  la bascule faite — un seul format en écriture, pas de dual-write
  permanent.
- `from_dict()` : si `"tape_v2"` présent → chargement direct. Sinon (vieux
  fichier) → upgrade en mémoire depuis `curpattern`/`kit_tape`/`patch_tape`
  comme aujourd'hui, avec `channel=0` et la même règle `dur=0` pour GRID
  (fallback voix).

### Découpage en commits (version initiale — voir correction ci-dessous)

| Étape | Contenu | Fichiers/tests touchés |
|---|---|---|
| **1c** | `Pattern` : dataclass `TapeEvent` + `_tape` → liste plate par piste + index `{(track,time): [...]}` pour perf grille. API publique de `Pattern` inchangée en signature (aucun appelant externe cassé à ce stade). | `pattern.py`, `test_pattern.py`, `test_pattern_grid_api.py`, `test_pattern_properties_bug.py`, `test_tape.py` |
| **1d** | `to_dict`/`from_dict` : écriture `tape_v2`, lecture rétrocompat ancien format + test explicite de rétrocompat (charger un vieux dict/fichier). | `pattern.py` + fixture de test dédiée |
| **1e** | Migration des 5 consommateurs directs (`ev.note`/`ev.vel`/`ev.bend` → `ev.payload[...]`, nouveau `ev.channel`), un fichier à la fois, tests après chacun. | `drum_player.py`, `track_editor.py`, `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py` + `test_midi_editor.py`, `test_quantize.py`, `test_track_editor.py`, `test_transport.py` |
| **1f** | Brancher `channel` côté UI là où c'est pertinent (à évaluer une fois 1c-1e faits). | à déterminer |
| **1g** | Durée GRID par événement (override Numpad1/3) — le vrai déclencheur initial de ce chantier (étape 7d, 2026-07-24). | `midi_editor.py` + `mew_numpad.py` |

### Correction du découpage (2026-09-18, avant le début du code)

Au moment d'attaquer 1c, vérification de l'empreinte réelle de l'accès
direct à `_tape` en style dict (`_tape[(track,bar,step)]`, `.setdefault`,
`.items()`, `.get()`, `del`, `in`, `.pop()`, `.keys()`) — pas seulement les
appels au constructeur `TapeEvent(...)` comptés dans le tableau ci-dessus.
Résultat : bien plus large que prévu.

- **6 fichiers source** : `pattern.py`, `midi_editor.py`, `track_editor.py`,
  `quantize_manager.py`, `drum_player.py`, **`ui/mw_project.py`** (via
  `cb.tape` — presse-papier `TrackEditor`, même structure dict-keyée,
  non identifié dans le découpage initial).
- **7 fichiers de tests** : `test_pattern.py`, `test_pattern_grid_api.py`,
  `test_pattern_properties_bug.py`, `test_tape.py` (à lui seul ~90
  occurrences), `test_track_editor.py`, `test_midi_editor.py`,
  `test_quantize.py`.

Décision (2026-09-18) : élargir 1c à tous les fichiers source touchés par
le changement de stockage (pas seulement `pattern.py`), et séparer
clairement Implémentation / Tests à chaque étape — rythme déjà utilisé en
Phase 6 (ex. étapes 10e/10f, 11a-11c). `ev.note`/`ev.vel`/`ev.bend` restent
lisibles via des propriétés de compatibilité sur `TapeEvent` pendant la
transition (voir design de la dataclass ci-dessus) : la migration réelle
des accès (`ev.note` → `ev.payload["note"]`) dans les fichiers consommateurs
reste une étape séparée (1g), et n'est donc pas bloquée par l'élargissement
de 1c.

**Découpage en commits (version corrigée, à suivre) :**

| Étape | Contenu | Fichiers touchés |
|---|---|---|
| **1c** | Implémentation — `Pattern` : dataclass `TapeEvent` (constructeur compatible avec l'ancien positionnel + propriétés `note`/`vel`/`bend` de compat) + `_tape` → liste plate par piste + index `{(track,time): [...]}` ; adaptation des accès directs dict-style à `_tape`/`cb.tape` dans les 5 autres fichiers source touchés. Signatures publiques de `Pattern` inchangées. | `pattern.py`, `midi_editor.py`, `track_editor.py`, `quantize_manager.py`, `drum_player.py`, `ui/mw_project.py` |
| **1d** | Tests — adaptation des 7 fichiers de tests à la nouvelle structure de `_tape`/`cb.tape`. | `test_pattern.py`, `test_pattern_grid_api.py`, `test_pattern_properties_bug.py`, `test_tape.py`, `test_track_editor.py`, `test_midi_editor.py`, `test_quantize.py` |
| **1e** | Implémentation — `to_dict`/`from_dict` : écriture `tape_v2`, lecture rétrocompat ancien format. | `pattern.py` |
| **1f** | Tests — rétrocompat de chargement (vieux dict/fichier `.gvp`), tests `to_dict`/`from_dict`. | `test_pattern.py` + fixture dédiée |
| **1g** | Implémentation — migration réelle des consommateurs (`ev.note`/`ev.vel`/`ev.bend` → `ev.payload[...]`, `ev.channel`), suppression des propriétés de compat une fois tout migré. | `drum_player.py`, `track_editor.py`, `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py` |
| **1h** | Tests — ajustements suite à 1g. | fichiers de tests correspondants |
| **1i** | Implémentation — brancher `channel` côté UI. | à déterminer |
| **1j** | Tests — idem. | à déterminer |
| **1k** | Implémentation — durée GRID par événement (override Numpad1/3), le vrai déclencheur initial (étape 7d, 2026-07-24). | `midi_editor.py`, `mew_numpad.py` |
| **1l** | Tests — idem. | fichiers de tests correspondants |

### Avancement (mise à jour 2026-09-19)

1c–1j **FAITS** (commits `ed07a52` à `25b4aa7`, 1487 tests passed). 1i a
été précisé en deux passes avec l'utilisateur au moment de coder :
- Portée : capture (canal MIDI entrant, déjà parsé par `midi_manager.py`
  mais jeté par `midi_handler.py`) + affichage (liste Ctrl+2, remplace le
  placeholder `track+1`) + édition (`SpinCtrl` dans `_NoteEditDialog`/
  `_MidiEventEditDialog`).
- Numérotation 0-15 (pas 1-16), cohérente avec `midi_manager.py`/`note.py`.
  Pas d'option « tous les canaux » dans les dialogs d'édition (une note a
  toujours exactement un canal) ; pas de nouveau filtre canal dans
  `EventFilterDialog` ni d'UI pour `MidiManager.channel` (gap préexistant
  découvert en creusant, séparé de ce chantier).
- Bugs de perte de canal trouvés et corrigés en vérifiant la chaîne
  complète : `track_editor.py` `paste_events` et `ui/mw_project.py`
  `_clipboard_to_dict`/`_clipboard_from_dict`.

**1k/1l FAITS** (commits `45559cc`, `793489d`, 1497 tests passed) —
**chantier Phase 7 complet (1a–1l)**. `Pattern.set_cell` gagne `dur=0`
(0 = pas d'override) ; `midi_editor.py` expose `"dur"` (effective :
override sinon voix) et `"dur_override"` (brut, pour préservation à
travers les autres edits) ; `change_duration` accepte `ETYPE_GRID` en plus
de `ETYPE_KIT`/`ETYPE_PATCH` ; `drum_player.py` fait primer l'override sur
`voice_manager.get_duration_ms` à la lecture. Décision explicite :
`insert_note` (GRID) ne pose jamais d'override — seule l'édition d'une
note existante (Numpad1/3) en pose un, pour éviter qu'une simple insertion
écrase silencieusement le réglage de voix.

### Conformité avec le but final (Import/Export MIDI)

Vérifié le 2026-09-18, à la demande de l'utilisateur, que ce redesign sert
bien l'objectif final (non encore formalisé comme phase dans `SPECS.md`)
d'import/export de fichiers MIDI standard (SMF), sans refactoriser le
format général des données de `Pattern` au-delà du nécessaire :

- Un SMF stocke, par piste, des événements avec un **delta-time
  arbitraire** (ticks), jamais quantifié sur une grille fixe. Le modèle
  actuel de `_tape` (clé `(track,bar,step)`) force chaque événement sur une
  division de `num_steps` — incompatible avec un import fidèle d'un fichier
  à timing libre. `time` en champ flottant par événement (liste plate) est
  le changement minimal qui débloque ça.
- `channel` est un concept MIDI de premier niveau, nécessaire à l'import
  (préserver le canal d'origine) et à l'export.
- `payload` en dict permet à chaque type (CC, Program Change, Aftertouch,
  SysEx — déjà anticipés dans `dialogs_temporal.py`) de porter exactement
  ses propres champs.

Ce qui reste **hors périmètre** de ce chantier, pour un import/export MIDI
complet (à traiter plus tard, séparément) :
- Tempo/signature rythmique variables en cours de pattern (SMF permet des
  meta-événements tempo/signature à tout moment ; `Pattern` n'a qu'un
  BPM/signature unique) — nécessiterait une automation dédiée, sur le
  modèle `bend_tape`/`mod_tape`.
- Le mapping d'un fichier MIDI de durée/nombre de pistes arbitraires sur la
  structure fixe de Groovebox (99 patterns × 999 mesures × 8 pistes) — un
  sujet d'orchestration séparé, pas un sujet `TapeEvent`.
- Le codec SMF lui-même (lecture/écriture du fichier `.mid`) — pas encore
  implémenté, pas dans ce chantier.

Ce qui **ne change pas** dans `Pattern` (pas de refactor du format
général) : `num_bars`, `num_steps`, `bpm`, `voices`, loop points, structure
`Song`/`ProjectManager` — tous inchangés.

---

## Phase 7 étape 2a — Fondations d'un parser MIDI dédié (`midi_parser.py` + `midi_constants.py`)

### Origine du besoin

`EventFilterDialog` (`dialogs_temporal.py`) liste depuis longtemps 5 types
d'événements marqués « (à venir) » dans `_EVT_TYPE_LABELS` : CC générique,
Program Change, Poly Aftertouch, Channel Pressure, SysEx/Meta —
sélection bloquée (`_TYPES_TO_COME`, snap-back sur le dernier type valide).
[[project_event_list_window_todo]] notait déjà « reste reporté :
canal/CC arbitraire » (canal fait en Phase 7 étape 1i). L'utilisateur a
demandé de compléter ce filtre avec ces messages reportés.

### État des lieux constaté en code (2026-09-20)

Aucun des 5 types n'existe à un seul niveau de la chaîne aujourd'hui :

- **`midi_manager.py::_callback`** décode les octets bruts **inline**
  (pas de module dédié) et ne reconnaît que 4 types de statut MIDI :
  `0x90` (Note On), `0x80` (Note Off), `0xB0` (Control Change), `0xE0`
  (Pitch Bend). `0xC0` (Program Change), `0xA0` (Poly Aftertouch), `0xD0`
  (Channel Pressure) ne sont **pas reconnus** — messages silencieusement
  ignorés. Pire pour SysEx : `self._midi_in.ignore_types(sysex=True, ...)`
  est posé à l'ouverture du port — ces messages sont jetés par `rtmidi`
  **avant même** d'atteindre `_callback`.
- **CC générique** est le type le plus proche d'être prêt : le parsing
  `0xB0` existe déjà et `midi_handler.py::on_cc` reçoit **tout** `cc_num`,
  mais seuls CC#1/7/10/64/120/121/123 ont un effet câblé en dur, et seul
  CC#1 (mod wheel) est **enregistré** (dans `_mod_tape`, séparé de
  `_tape`). Un CC arbitraire reçu aujourd'hui ne fait rien et n'est jamais
  capturé.
- **Program Change** : aucune notion de « program » MIDI dans l'app (le
  `Rack` a des slots d'instrument, pas des program numbers GM) — aucun
  effet live possible, capture pure si implémenté.
- **Poly Aftertouch / Channel Pressure** : parsing absent ; incertain que
  le MPK mini Plus envoie même de l'aftertouch (à vérifier avant d'y
  investir du temps).
- **SysEx/Meta** : bloqué au niveau `rtmidi`, valeur d'usage la plus
  incertaine des 5 dans cette app (pas de sortie MIDI, pas de moteur
  consommateur).
- **Descriptions existantes** : `midi_handler.py` a déjà un dict
  `CC_NAMES` (partiel, noms CC standard MIDI 1.0) utilisé uniquement pour
  le statut MIDI live (`format_midi_status`/`_notify_editor_midi`).
  `synth_engine.py::midi_to_note_name` donne déjà les noms de note
  (`60 → "C4"`). Aucune table General MIDI (noms des 128 programs)
  n'existe nulle part — fournie par l'utilisateur pour ce chantier (voir
  Conception ci-dessous).

### Décision : construire un module `midi_parser.py` dédié, fondations d'abord

Décision de l'utilisateur (2026-09-20) : commencer par les **fondations
d'un parser MIDI** plutôt que par le branchement direct
capture/stockage/filtre. Proposition initiale de l'utilisateur pour la
taxonomie, reprise telle quelle :

```python
class CVoice:
    NoteOff               = 0x80
    NoteOn                = 0x90
    PolyphonicKeyPressure = 0xA0   # note aftertouch
    ControllerChange      = 0xB0
    ProgramChange         = 0xC0
    ChannelPressure       = 0xD0
    PitchBend             = 0xE0


class CMeta:
    FileMetaEvent              = 0xFF
    SMPTEOffsetMetaEvent       = 0x54
    SystemExclusive            = 0xF0
    SystemExclusivePacket      = 0xF7
    SequenceNumber             = 0x00
    TextMetaEvent              = 0x01
    CopyrightMetaEvent         = 0x02
    TrackName                  = 0x03
    InstrumentName             = 0x04
    Lyric                      = 0x05
    Marker                     = 0x06
    CuePoint                   = 0x07
    ChannelPrefix              = 0x20
    MidiPort                   = 0x21
    EndTrack                   = 0x2F
    SetTempo                   = 0x51
    TimeSignature              = 0x58
    KeySignature               = 0x59
    SequencerSpecificMetaEvent = 0x7F
```

`CMeta` reprend la taxonomie standard des méta-événements d'un fichier
MIDI (SMF) — ce qui confirme que ce module sert **double emploi** :
décodage des messages MIDI temps réel reçus aujourd'hui (`CVoice`), et
fondation pour la lecture/écriture d'un fichier `.mid` plus tard
(`CMeta`), sans dupliquer la taxonomie entre les deux usages.

**Portée retenue pour ce module** (ce que 2a couvre vraiment, vs. les
fondations posées sans implémentation) :

| Catégorie | Dans ce chantier | Détail |
|---|---|---|
| Notes | Description seulement | Réutilise `synth_engine.midi_to_note_name` (pas de duplication) ; le décodage `0x80`/`0x90` reste largement ce qui existe déjà. |
| CC (Control Change) | Parsing + descriptions | `CC_NAMES` déplacé (pas dupliqué) depuis `midi_handler.py`. |
| Program Change | Parsing nouveau + descriptions GM | Tables fournies par l'utilisateur (patchs mélodiques + kits GM2), voir Conception. |
| Pitch Bend | Parsing (déjà fait) centralisé | Décodage 14 bits déplacé dans le module dédié. |
| Poly Aftertouch, Channel Pressure | **Fondations seulement** | Constantes `CVoice` posées ; pas de décodage ni de capture dans ce chantier. |
| Meta, SysEx, Text | **Fondations seulement** | Constantes `CMeta` posées ; `ignore_types(sysex=True)` **pas retiré** dans ce chantier. |

### Conception

**Deux fichiers séparés** (données vs. logique) :

- **`src/midi_constants.py`** (nouveau) : tables de description pures,
  aucune dépendance. Contenu :
  - `CC_NAMES` : fusionné (déplacé, pas dupliqué) depuis
    `midi_handler.py`.
  - `GM_PATCH_NAMES` : 128 noms d'instruments General MIDI (liste fournie
    par l'utilisateur, `_gm_patch_lst` renommé selon la convention du
    projet).
  - `GM2_DRUMKIT_NAMES` : noms des kits de batterie GM2 par program
    number (liste fournie par l'utilisateur, `_gm2_drumkit` renommé) —
    seuls certains index ont un nom ; les autres restent l'entier
    lui-même (convention reprise telle quelle de la source fournie).
- **`src/midi_parser.py`** (nouveau) : logique de décodage, aucune
  dépendance à `rtmidi` ni `wx` — pur et testable unitairement sans port
  MIDI ni interface graphique (alternative écartée : garder le décodage
  inline dans `midi_manager.py::_callback` comme aujourd'hui — pas
  réutilisable pour un futur import `.mid`, pas testable isolément).
  - `CVoice`/`CMeta` : classes-namespaces de constantes, telles que
    proposées par l'utilisateur.
  - Fonction(s) de décodage bas niveau : prennent les octets bruts d'un
    message et retournent une structure décrivant le message (type,
    canal, données) — remplace la logique actuellement inline dans
    `MidiManager._callback` pour les 4 types déjà gérés, **plus**
    `ProgramChange` (nouveau).
  - Importe les tables de description depuis `midi_constants.py` (ne les
    redéfinit pas).
  - Note : `GM2_DRUMKIT_NAMES` n'est consulté que si l'appelant sait déjà
    qu'un canal/piste est un kit de batterie (typiquement canal 10) —
    `midi_parser.py` ne devine pas ça tout seul à ce stade ; c'est
    `describe_program(program, is_drum=False)` (ou équivalent) qui
    choisit la table.

### Intégration avec l'existant

- `midi_manager.py::_callback` délègue le décodage octet-par-octet à
  `midi_parser.py` ; garde la gestion de port `rtmidi`, le threading, le
  filtrage de canal (`self.channel`).
- Nouveau callback `on_program_change(program, chan)` (miroir de
  `on_note_on`/`on_cc`/`on_pitch_bend`), câblé dans `midi_handler.py`.
- `midi_handler.py::CC_NAMES` supprimé au profit de l'import depuis
  `midi_constants.py` (`format_midi_status` l'utilise déjà pour le statut
  live — comportement inchangé, juste la source de la table qui change).
- Program Change reçu : au minimum, statut live affiché (comme les autres
  types déjà gérés par `_notify_editor_midi`) ; la **capture/stockage**
  dans `_tape` (nouveau `ETYPE_PROGRAM_CHANGE`, payload `{"program": int}`,
  cohérent avec la conception `TapeEvent` de la Phase 7 1a-1l) et le
  branchement `EventFilterDialog`/affichage Ctrl+2 sont un **chantier
  séparé, ultérieur** (à numéroter une fois le parser posé — pas dans
  2a-2i).

### Portée explicitement exclue de ce chantier

- Retirer `ignore_types(sysex=True)` et décoder les SysEx.
- Décoder Poly Aftertouch / Channel Pressure.
- Décoder les méta-événements SMF (`CMeta`) — les constantes existent,
  rien ne les lit encore (utile seulement quand le codec `.mid`
  lecture/écriture sera entrepris).
- Câbler la capture (`_tape`), l'affichage (liste Ctrl+2) et le filtre
  (`EventFilterDialog`) de Program Change/CC générique — fondations du
  parser uniquement dans ce chantier ; le branchement est un chantier
  séparé qui suivra.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **2a** | Doc — ce plan. | `docs/DESIGN.md` |
| **2b** | Implémentation — `midi_constants.py` : `CC_NAMES` (fusionné), `GM_PATCH_NAMES`, `GM2_DRUMKIT_NAMES`. | `midi_constants.py` (nouveau) |
| **2c** | Tests — `midi_constants.py` (tailles de table, quelques valeurs connues). | `test_midi_constants.py` (nouveau) |
| **2d** | Implémentation — `midi_parser.py` : `CVoice`/`CMeta`, décodage bas niveau (Note On/Off, CC, Program Change, Pitch Bend), fonctions de description important `midi_constants.py`. | `midi_parser.py` (nouveau) |
| **2e** | Tests — `midi_parser.py` en isolation (pas de dépendance rtmidi/wx, tests purs sur des octets construits à la main). | `test_midi_parser.py` (nouveau) |
| **2f** | Implémentation — `midi_manager.py` délègue à `midi_parser.py` ; ajoute la reconnaissance `0xC0` + callback `on_program_change`. | `midi_manager.py` |
| **2g** | Tests — mise à jour/ajout pour la délégation + Program Change. | `test_midi_manager.py` |
| **2h** | Implémentation — `midi_handler.py` : câble `on_program_change` (statut live minimum), retire `CC_NAMES` local au profit de l'import. | `midi_handler.py` |
| **2i** | Tests — idem. | `test_midi_handler.py` |

Suite (hors périmètre 2a-2i, à renuméroter plus tard) : capture/stockage
de Program Change et CC générique dans `_tape` + branchement
`EventFilterDialog`/affichage Ctrl+2 — une fois le parser posé.

**2b-2i FAITS** (commits `2a98f2f`..`4382a9b`, 1549 tests passed) —
**chantier Phase 7 complet (2a-2i)**. `midi_constants.py` (CC_NAMES
déplacé, GM_PATCH_NAMES/GM2_DRUMKIT_NAMES = tables standard officielles,
faute de liste spécifique fournie — voir commit `2a98f2f`) ;
`midi_parser.py` (CVoice/CMeta, `decode_message` littéral,
`describe_note`/`describe_cc`/`describe_program`) ; `MidiManager._callback`
délègue à `decode_message` et reconnaît Program Change ; `MidiHandler`
câble `on_program_change` (statut live minimum, `_tape` hors périmètre).

---

## Phase 7 étape 3a — Réorganisation des fichiers MIDI (`src/midi/`)

### Origine du besoin

Après les étapes 2a-2j, 4 fichiers MIDI « cœur » (logique, hors UI)
cohabitent en vrac à la racine de `src/` avec des fichiers non-MIDI
(`pattern.py`, `synth_engine.py`, etc.) : `midi_constants.py`,
`midi_editor.py`, `midi_manager.py`, `midi_parser.py`. L'utilisateur
demande de les regrouper dans un nouveau dossier `src/midi/` pour mieux
ranger le code.

### Décision de scope (utilisateur, 2026-09-21)

- **4 fichiers déplacés** : `midi_constants.py`, `midi_editor.py`,
  `midi_manager.py` (inclus après clarification — même domaine « cœur
  MIDI non-UI » que les 3 cités initialement), `midi_parser.py`.
- **Fichiers `ui/*.py` liés au MIDI laissés en place** (`midi_handler.py`,
  `midi_editor_window.py`, `mw_midi_editor.py`, `midi_editor_dialogs.py`,
  `midi_virtual_keyboard.py`) : la convention existante range tout le GUI
  wx sous `src/ui/` indépendamment du domaine métier — pas de mélange
  UI/logique dans `src/midi/`.
- **Pas de renommage de fichier** : seul le dossier change
  (`src/midi_parser.py` → `src/midi/midi_parser.py`), même convention que
  `src/ui/` lors du refactor Phase 6 (fichiers déplacés tels quels).

### Conception : package `src/midi/`, imports absolus pointés

- Nouveau `src/midi/__init__.py` (vide) — même convention que
  `src/ui/__init__.py` (vide, package pur, pas de ré-export).
- Tous les imports vers ces 4 fichiers passent de la forme plate
  (`from midi_parser import X`, `import midi_manager as mm`) à la forme
  pointée `from midi.midi_parser import X`, `import midi.midi_manager as
  mm` — même convention que `src/ui/` (`from ui.midi_handler import
  MidiHandler`), **pas d'imports relatifs** (`.xxx`).
- Imports internes entre les 4 fichiers déplacés (`midi_parser.py` →
  `midi_constants.py`, `midi_manager.py` → `midi_parser.py`) : même forme
  pointée `from midi.midi_constants import ...`, pas de raccourci
  relatif — cohérent avec le style du reste du projet.

### État des lieux des importeurs (avant déplacement)

| Fichier déplacé | Importé par (code) | Importé par (tests) |
|---|---|---|
| `midi_constants.py` | `src/midi_parser.py`, `src/ui/midi_handler.py` | `tests/test_midi_constants.py` |
| `midi_parser.py` | `src/midi_manager.py`, `src/ui/midi_handler.py` | `tests/test_midi_parser.py` |
| `midi_manager.py` | `src/ui/main_window.py` | `tests/test_midi_manager.py` |
| `midi_editor.py` | `src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py` (import local différé dans une méthode) | `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` |

### Ordre de déplacement (dépendances internes)

`midi_constants.py` (aucune dépendance `midi_*`) → `midi_parser.py`
(dépend de `midi_constants`) → `midi_manager.py` (dépend de
`midi_parser`) → `midi_editor.py` (indépendant, dépend seulement de
`pattern.py` — déplacé en dernier, aucune contrainte d'ordre avec les 3
autres).

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **3a** | Doc — ce plan. | `docs/DESIGN.md` |
| **3b** | Implémentation — `src/midi/__init__.py` + déplace `midi_constants.py` ; met à jour les imports non-tests (`src/midi_parser.py`, `src/ui/midi_handler.py`). | `src/midi/__init__.py` (nouveau), `src/midi/midi_constants.py` (déplacé), `src/midi_parser.py`, `src/ui/midi_handler.py` |
| **3c** | Tests — `tests/test_midi_constants.py` (import pointé `midi.midi_constants`), suite verte. | `tests/test_midi_constants.py` |
| **3d** | Implémentation — déplace `midi_parser.py` ; met à jour les imports non-tests (`src/midi_manager.py`, `src/ui/midi_handler.py`). | `src/midi/midi_parser.py` (déplacé), `src/midi_manager.py`, `src/ui/midi_handler.py` |
| **3e** | Tests — `tests/test_midi_parser.py` (import pointé), suite verte. | `tests/test_midi_parser.py` |
| **3f** | Implémentation — déplace `midi_manager.py` ; met à jour l'import non-test (`src/ui/main_window.py`). | `src/midi/midi_manager.py` (déplacé), `src/ui/main_window.py` |
| **3g** | Tests — `tests/test_midi_manager.py` (import pointé), suite verte. | `tests/test_midi_manager.py` |
| **3h** | Implémentation — déplace `midi_editor.py` ; met à jour les imports non-tests (`src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py`). | `src/midi/midi_editor.py` (déplacé), `src/ui/midi_editor_window.py`, `src/ui/dialogs_temporal.py` |
| **3i** | Tests — `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` (imports pointés), suite verte. | `tests/test_midi_editor.py`, `tests/test_midi_editor_filter.py` |
| **3j** | Implémentation — renomme `src/ui/midi_handler.py` en `src/ui/midi_handler_window.py` ; met à jour l'import non-test (`src/ui/main_window.py`). | `src/ui/midi_handler_window.py` (déplacé), `src/ui/main_window.py` |
| **3k** | Tests — renomme `tests/test_midi_handler.py` en `tests/test_midi_handler_window.py` (import pointé), suite verte. | `tests/test_midi_handler_window.py` (déplacé) |
| **3l** | Doc — chantier complet (3a-3k). | `docs/DESIGN.md` |

**Extension de scope (décision utilisateur, 2026-09-21)** : une fois
les 4 fichiers regroupés sous `src/midi/`, `src/midi/midi_manager.py`
et `src/ui/midi_handler.py` sont apparus comme deux noms trop proches
pour être distingués d'un coup d'œil (aucune collision réelle — modules
`midi.midi_manager` et `ui.midi_handler` distincts — mais confusion
plausible). Décision : renommer `src/ui/midi_handler.py` en
`src/ui/midi_handler_window.py` (3j/3k, ajoutés après coup). Seul le
nom de fichier change — la classe `MidiHandler` et l'attribut
`win._midi_handler` ne sont pas renommés (hors scope, aucune ambiguïté
sur ces deux-là).

**Remarque sur les commits impl-only (3b/3d/3f/3h)** : chaque commit
d'implémentation laisse volontairement le(s) fichier(s) de test
correspondant(s) rouge(s) (`ModuleNotFoundError` sur l'ancien import
plat) jusqu'au commit Tests qui suit immédiatement — titré en
conséquence (« travail incomplet — tests à suivre »), même convention
que Phase 7 étape 1k (commit `45559cc`). La suite complète (`pytest
tests/`) n'est vérifiée verte qu'à l'issue de chaque paire impl+tests,
jamais laissée rouge entre deux paires distinctes.

### Portée explicitement exclue de ce chantier

- Renommer les 4 fichiers déplacés eux-mêmes (ex. `midi_parser.py` →
  `parser.py`) : seul le dossier change. Ne s'applique pas à
  `src/ui/midi_handler.py` → `midi_handler_window.py` (3j/3k) : ce
  fichier n'est pas déplacé, seulement renommé, pour lever l'ambiguïté
  avec `src/midi/midi_manager.py` (voir Extension de scope ci-dessus).
- Déplacer les fichiers MIDI de `src/ui/` (`midi_handler_window.py`,
  `midi_editor_window.py`, `mw_midi_editor.py`, `midi_editor_dialogs.py`,
  `midi_virtual_keyboard.py`) : restent sous `src/ui/` (décision
  utilisateur).
- Toute modification de comportement : chantier de rangement pur, aucun
  changement fonctionnel attendu (suite de tests inchangée en
  nombre/contenu, seuls les imports changent).

**3b-3k FAITS** (commits `c0e88af`..`9fe5055`, 1549 tests passed) —
**chantier Phase 7 complet (3a-3l)**. `midi_constants.py`,
`midi_parser.py`, `midi_manager.py`, `midi_editor.py` regroupés sous
`src/midi/` (nouveau package, `src/midi/__init__.py` vide) ; tous les
imports pointent `midi.midi_xxx`, aucun import plat résiduel.
`src/ui/midi_handler.py` renommé en `midi_handler_window.py` (3j/3k,
extension de scope décidée en cours de chantier) pour lever
l'ambiguïté avec `src/midi/midi_manager.py` — classe `MidiHandler` et
attribut `win._midi_handler` inchangés. Comportement inchangé
(rangement/renommage purs), suite verte à l'issue de chaque paire
impl+tests.

Point de process noté : le commit `83c2e38` (3k) a d'abord manqué 2
lignes (docstring + import) à cause d'un `git add -A <chemins
explicites>` lancé juste après un `git mv` sans re-vérifier le statut —
la suite tournait verte sur le fichier de travail non committé,
masquant l'écart. Corrigé par un commit correctif immédiat (`9fe5055`)
plutôt qu'un `--amend`. Réflexe à prendre : après `git mv` + édition,
toujours `git status`/`git diff HEAD` avant de committer, pas seulement
lancer la suite de tests.

---

## Phase 7 étape 4a — Capture, filtre et affichage de CC générique / Program Change

### Origine du besoin

Suite directe de [[project_midi_parser_todo]] (2a-2j, parser dédié) et
[[project_midi_files_reorg]] (3a-3l, rangement sans lien fonctionnel).
`midi_manager.py`/`midi_parser.py` reconnaissent déjà Program Change
(`on_program_change`) et tout Control Change (`on_cc`) — mais aucun des
deux n'est capturé dans `_tape`, ni filtrable dans `EventFilterDialog`
(`_TYPES_TO_COME` bloque encore leurs entrées), ni affiché dans la liste
Ctrl+2. Décidé en 2a : « branchement capture/stockage/filtre : chantier
séparé, ultérieur » (voir docs/DESIGN.md § Phase 7 étape 2a, section
« Intégration avec l'existant »). C'est ce chantier.

### État des lieux constaté en code (2026-09-21) — un piège identifié

Un `else` catch-all traite aujourd'hui silencieusement **tout** etype de
`_tape` différent de `ETYPE_GRID`/`ETYPE_KIT` comme un `ETYPE_PATCH` :

- `drum_player.py` (~L474, boucle de lecture) : `else: events.append((…
  self.PATCH_TAPE_EVENT, (t_idx, ev.payload.get("note"), …,
  ev.payload.get("bend", 0)), …))`. Un `ETYPE_PGM`/`ETYPE_CC` non
  reconnu explicitement y serait lu comme une note PATCH avec
  `note=None`, `bend=0` — au mieux un événement fantôme silencieux, au
  pire un plantage en aval (`TrackRouter.on_patch_tape` attend un
  `midi_note` entier).
- `midi/midi_editor.py::get_note_events` (~L72) : même `else`, avec en
  plus `events.sort(key=lambda e: (e["offset"], e["pad"]))` (L88) — un
  `pad=None` ferait lever un `TypeError` dès qu'il faut comparer `None`
  à un entier (liste mixte).
- `ui/mw_project.py::_clipboard_to_dict`/`_clipboard_from_dict`
  (~L274-309, presse-papier `TrackEditor` cross-pattern Ctrl+C/X/V) :
  même schéma `if GRID / elif KIT / else PATCH`.

Chaque nouveau etype introduit ici **doit** donc remplacer ces `else`
par un `elif ETYPE_PATCH` explicite avant d'ajouter ses propres
branches — pas une option, un correctif de sécurité préalable.

Points sans piège (déjà sûrs par inclusion, pas par exclusion) :
`quantize_manager.py` (`if etype not in (KIT, PATCH): continue`) et
`track_editor.py::paste_events` (`elif etype in (KIT, PATCH)`) ignorent
déjà silencieusement tout etype inconnu — pas de correctif requis, mais
CC/Program Change y resteront non quantifiables et non collables via
Ctrl+V « niveau événement » (`copy_events`/`paste_events`) tant qu'ils
n'y sont pas explicitement ajoutés (voir Portée exclue).

### Décisions validées (utilisateur, 2026-09-21)

1. **CC#1 dupliqué, migration notée pour plus tard.** Le nouveau
   « CC générique » capture **tous** les CC reçus, y compris CC#1 — en
   plus de `_mod_tape` (qui continue, inchangé, à piloter le vibrato en
   lecture via `on_mod_tape`). Doublon assumé : `_mod_tape` est
   candidat à être remplacé par une lecture de `_tape`/`ETYPE_CC`
   filtrée sur `cc_num==1` dans un chantier ultérieur (non fait ici).
2. **Effet réellement rejoué à la lecture (Play), pas seulement une
   capture passive** — pour CC générique **et** pour Program Change.
   Revient sur la position prise en 2a (« aucun effet live possible »
   pour Program Change) : c'était une simplification volontaire pour
   avancer sur les fondations du parser, pas une limite définitive.
   Décision révisée (2026-09-21) : en attendant le vrai mode Rack
   Synth/GM (16 canaux MIDI → 16 slots avec leurs patchs, lecture de
   fichiers `.mid` — chantier futur distinct, motivant de garder la
   souplesse du format MIDI, qui peut envoyer un Program Change à tout
   moment), Program Change pilote **provisoirement** le `Rack` existant
   à 16 slots :
   - CC générique capturé → même effet que sa réception live via
     `on_cc` (volume/pan/sustain/mod wheel/all-notes-off/all-sounds-off/
     reset), appliqué à la piste d'origine (pas à la piste/pad ayant le
     focus UI — cette notion de focus n'existe pas pendant la lecture).
   - Program Change (live **et** rejoué à la lecture) → réassigne le
     slot du `Rack` de la piste concernée : `TrackRouter.assign_slot(
     track_idx, program % 16)` (`assign_slot` existe déjà — chargement
     du `SynthEngine`/patch en tâche de fond si le slot est SYNTH, non
     bloquant). Valeurs 16-127 repliées par modulo 16 en attendant le
     vrai adressage par canal du futur mode GM. Live : cible la piste
     courante (`win._player._cur_track`, comme les autres effets CC
     live) ; lecture : cible `track_idx`, la piste d'origine de
     l'événement (comme `on_cc_tape`).
3. **Édition via Entrée (Ctrl+2) incluse dans ce chantier**, en
   réutilisant `_CcEventEditDialog` (déjà utilisé pour bend/mod) :
   valeur éditable pour CC générique et pour Program Change ; le numéro
   de CC (`cc_num`) reste non éditable dans ce chantier (seule sa
   valeur l'est, comme le pad/note n'est pas éditable pour bend/mod
   aujourd'hui).
4. **Groupe de plage dédié dans `EventFilterDialog`**, symétrique à
   Pitch Bend : un groupe « CC générique » (Numéro CC Bas/Haut + Valeur
   Bas/Haut, sur le modèle Notes qui combine déjà deux paires
   Note/Vélocité) et un groupe « Program Change » (Program Bas/Haut,
   sur le modèle Pitch Bend à une seule paire).

### Conception

**Deux nouveaux etypes dans `_tape`** (pattern.py), cohérents avec la
conception `TapeEvent` unifiée de la Phase 7 1a-1l — pas de structure
parallèle façon `_bend_tape`/`_mod_tape` :

```python
ETYPE_CC  = "CC"    # payload {"cc_num": int, "value": int}, dur=0
ETYPE_PGM = "PGM"   # payload {"program": int},              dur=0
```

Pas de dédoublonnage à la capture (contrairement à
`record_kit_note`/`record_patch_note` qui évitent les doublons exacts à
la même position) : deux CC de même valeur au même tick sont des
données valides (un contrôleur physique peut légitimement renvoyer deux
fois la même valeur), donc simple `append`.

**Capture** (`drum_player.py`, miroir de `record_kit_note`) :
- `record_cc(cc_num, value, channel=0)` → `TapeEvent(ETYPE_CC, …)`
  append dans `_tape[cur_track]`.
- `record_program_change(program, channel=0)` → `TapeEvent(ETYPE_PGM,
  …)` append dans `_tape[cur_track]`.

Branchées dans `midi_handler_window.py` :
- `on_cc` : ajoute `if win._player.recording:
  win._player.record_cc(cc_num, value, channel)`, **avant ou après**
  les branches d'effet existantes (7/10/64/120/121/123/1) — celles-ci
  restent inchangées pour la réception live, la capture est
  orthogonale.
- `on_program_change` : ajoute l'appel `record_program_change`
  équivalent, **et** l'effet live (décision 2 révisée) :
  `win._router.assign_slot(win._player._cur_track, program % 16)` —
  le commentaire actuel (« aucun effet live possible, capture pure »)
  est obsolète et à retirer.

**Lecture (rejeu de l'effet, décision 2)** — deux nouveaux marqueurs
internes `DrumPlayer.CC_TAPE_EVENT`/`PGM_TAPE_EVENT`, deux nouveaux
callbacks `_on_cc_tape_cb`/`_on_program_change_tape_cb` (même
convention que `_on_bend_tape_cb`), wirés dans `main_window.py` vers
deux nouvelles méthodes `TrackRouter.on_cc_tape`/`on_program_change_tape` :
- `on_cc_tape(track_idx, cc_num, value)` : CC#64/120/121/123 → effet
  global (sustain/all sounds off/reset/all notes off), indépendant de
  `track_idx`. CC#1 → délègue à `on_mod_tape` existant (même moteur
  cible que le vibrato live). CC#7/10 → `set_track_volume`/
  `set_track_pan` **de `track_idx`** (pas de piste focus à la lecture).
  Piste non audible (`_track_is_audible`) → ignoré, sauf les 4 effets
  globaux.
- `on_program_change_tape(track_idx, program)` : `assign_slot(track_idx,
  program % 16)` (décision 2 révisée) — même appel que l'effet live,
  ciblant la piste d'origine de l'événement plutôt que la piste
  courante.

**Filtre/sélection/affichage** — le point délicat est `event_idx` :
`_delete_tape_event`/`edit_tape_note` le résolvent comme *position
parmi tous les événements de `_tape[track]` au même `time`, tous etypes
confondus* (`matches = [i for i,e in enumerate(track_list) if e.time ==
time]`), exactement la construction déjà faite par
`get_note_events::by_time`. Pour que CC/PGM restent éditables/
supprimables avec la même convention d'index, `get_all_events` ne doit
**pas** re-scanner `_tape[t]` indépendamment pour CC/PGM (ça
recalculerait un `event_idx` local à CC/PGM seul, incohérent avec
`_delete_tape_event`) : il doit dériver ses entrées "cc"/"pgm" de la
**même** construction `by_time` que `get_note_events`, avec le même `i`
partagé entre tous les etypes présents à cet offset.
→ Refactor proposé : extraire de `get_note_events` la construction
`by_time` (groupement `_tape[track_idx]` par `.time`, tous etypes) dans
un petit helper privé partagé, réutilisé par `get_note_events` (filtre
GRID/KIT/PATCH, comportement inchangé) et par une nouvelle collecte
CC/PGM appelée depuis `get_all_events` (filtre CC/PGM, même `i`).

Nouveaux champs d'event dict : `{"type": "cc", "track", "bar", "step",
"offset", "cc_num", "value", "channel", "event_idx"}` et `{"type":
"pgm", "track", "bar", "step", "offset", "program", "channel",
"event_idx"}`.

`MidiEditor` : deux nouvelles méthodes `edit_cc_event`/`edit_pgm_event`
(miroir de `edit_tape_note`, retrouvent l'événement via
`time`+`event_idx` dans `_tape[track]`, remplacent `value`/`program`
et/ou repositionnent). `delete_event` couvre déjà CC/PGM sans
changement (`_delete_tape_event` est générique par `event_idx`).

**Correction en cours de chantier (4i)** : la phrase ci-dessus était
fausse — `delete_event` commence par `if ev.get("type") != "note":
return False`, donc un CC/PGM était rejeté avant même d'atteindre
`_delete_tape_event` (lui bien générique). Corrigé en 4i : dispatch sur
`ev["type"]`, les types `"cc"`/`"pgm"` passant par `_delete_tape_event`
comme les notes KIT/PATCH.

`filter_events` : nouvelles clés critères `cc_num_lo/hi`, `cc_val_lo/hi`,
`pgm_lo/hi` ; nouvelles branches `e["type"] == "cc"`/`"pgm"` bornées en
plus du test `etype_filter`.

`EventFilterDialog` (`dialogs_temporal.py`) : `_EVT_TYPE_LABELS`
perd ses deux entrées « (à venir) » pour CC générique/Program Change
(sortent de `_TYPES_TO_COME`, qui garde Poly Aftertouch/Channel
Pressure/SysEx-Meta) ; nouveaux `_TYPE_CC`/`_TYPE_PGM` + entrées
`_TYPE_KEY` ; deux nouveaux `StaticBoxSizer` (« CC générique » : Numéro
CC Bas/Haut + Valeur Bas/Haut ; « Program Change » : Program Bas/Haut),
activés/désactivés dans `_update_group_enabled` comme les groupes
existants ; `_type_unavailable` étendu pour bloquer aussi CC/PGM en
mode Notes (`view_mode == 0`), comme Bend/Mod aujourd'hui.

`mew_display.py` (`_event_label_all`, liste Ctrl+2) : deux nouvelles
branches `elif e["type"] == "cc"`/`"pgm"` (format `"Canal {ch}, CC,
Numéro {cc_num}, Valeur {value}"` / `"Canal {ch}, Program Change,
Program {program} ({nom GM si connu via describe_program})"` —
réutilise `midi.midi_parser.describe_program`, pas de table dupliquée).

`mew_editing.py::_edit_note_dialog` : le test `ev.get("type") in
("bend", "mod")` devient `("bend", "mod", "cc", "pgm")`, délégué à
`_edit_cc_dialog` généralisé (dispatch par `ev["type"]` plutôt que le
booléen `is_bend` actuel, vers `edit_bend_event`/`edit_mod_event`/
`edit_cc_event`/`edit_pgm_event`).

`midi_editor_dialogs.py::_CcEventEditDialog` : `is_bend` (booléen)
remplacé par dispatch sur `ev["type"]` (4 branches titre+label+bornes ;
CC générique reprend les bornes 0-127 déjà utilisées pour Mod, Program
Change ajoute une borne 0-127 avec le libellé « Program »).

**Persistance (`.gvp`) et presse-papier `TrackEditor`** :
- `pattern.py::to_dict`/`from_dict` sérialisent déjà `_tape` de façon
  générique par `TapeEvent` (etype/dur/channel/payload) — à vérifier
  qu'aucun filtre implicite sur les 3 etypes existants n'y traîne
  (lecture rapide du code de sauvegarde needed avant 4h, voir
  découpage).
- `ui/mw_project.py::_clipboard_to_dict`/`_clipboard_from_dict` : le
  `else → PATCH` (piège identifié plus haut) devient `elif ETYPE_PATCH`
  + deux nouvelles branches CC/PGM (format `[ETYPE_CC, t, b, s, cc_num,
  value, channel]` / `[ETYPE_PGM, t, b, s, program, channel]`).

### Portée explicitement exclue de ce chantier

- Éditer `cc_num` d'un événement CC générique existant (seule sa valeur
  l'est, décision 3).
- Migrer `_mod_tape`/`on_mod_tape` pour qu'il lise `_tape`/`ETYPE_CC`
  au lieu de sa structure dédiée (doublon CC#1 assumé, décision 1) —
  chantier ultérieur distinct.
- Le vrai mode Rack Synth/GM (adressage par canal MIDI plutôt que par
  piste, lecture de fichiers `.mid` sur 16 canaux avec leurs patchs) —
  `assign_slot(track_idx, program % 16)` n'est qu'un pont provisoire
  vers le `Rack` existant (décision 2 révisée), pas ce mode complet.
- `copy_events`/`paste_events` (presse-papier « niveau événement »,
  Ctrl+C/V dans la liste Ctrl+2, distinct du presse-papier
  `TrackEditor`) : reste limité à `ETYPE_GRID`/`KIT`/`PATCH` comme
  aujourd'hui — CC/PGM non copiables-collables à ce niveau dans ce
  chantier (silencieusement ignorés par le filtre `in (ETYPE_KIT,
  ETYPE_PATCH)` existant, pas de régression, juste pas d'extension).
- Quantisation (`quantize_manager.py`) de CC/PGM — reste hors du filtre
  `(ETYPE_KIT, ETYPE_PATCH)` existant, sans changement.
- Poly Aftertouch / Channel Pressure / SysEx-Meta — toujours hors
  périmètre (constantes `CVoice`/`CMeta` posées en 2a, décodage non
  fait), restent dans `_TYPES_TO_COME`.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **4a** | Doc — ce plan. | `docs/DESIGN.md` |
| **4b** | Implémentation — `pattern.py` : `ETYPE_CC`/`ETYPE_PGM` ; vérifie que `to_dict`/`from_dict` les sérialisent sans changement (générique par construction). | `pattern.py` |
| **4c** | Tests — `pattern.py` (round-trip `to_dict`/`from_dict` avec un `TapeEvent` CC et un PGM). | `test_pattern.py` |
| **4d** | Implémentation — `drum_player.py` : `record_cc`/`record_program_change` ; corrige le piège `else→PATCH` de la boucle de lecture (`elif ETYPE_PATCH` explicite) ; ajoute `CC_TAPE_EVENT`/`PGM_TAPE_EVENT` + callbacks. | `drum_player.py` |
| **4e** | Tests — capture (`record_cc`/`record_program_change`) + non-régression boucle de lecture (un `ETYPE_PGM`/`ETYPE_CC` dans `_tape` ne casse plus la lecture d'un `ETYPE_PATCH` voisin). | `test_pattern.py` ou nouveau `test_drum_player_cc.py` |
| **4f** | Implémentation — `midi_handler_window.py` : branche `record_cc`/`record_program_change` dans `on_cc`/`on_program_change`, **et** l'effet live Program Change (`assign_slot(cur_track, program % 16)`). | `midi_handler_window.py` |
| **4g** | Implémentation — `track_router.py` + `main_window.py` : `on_cc_tape`/`on_program_change_tape` (celui-ci appelle aussi `assign_slot`), wiring des callbacks. | `track_router.py`, `main_window.py` |
| **4h** | Tests — `on_cc_tape` (volume/pan/sustain/mod/all-notes-off/all-sounds-off/reset appliqués correctement, piste non audible ignorée sauf effets globaux) ; `on_program_change_tape` (`assign_slot` appelé avec le bon slot, modulo 16) ; effet live Program Change dans `on_program_change`. | `test_track_router.py`, `test_midi_handler_window.py` |
| **4i** | Implémentation — `midi_editor.py` : refactor `by_time` partagé, `get_note_events` restreint à GRID/KIT/PATCH, collecte CC/PGM dans `get_all_events` (même `event_idx`), `filter_events` étendu, `edit_cc_event`/`edit_pgm_event`. | `midi/midi_editor.py` |
| **4j** | Tests — `get_all_events` (event_idx cohérent avec un GRID+CC au même offset), `filter_events` (cc/pgm), `edit_cc_event`/`edit_pgm_event`, `delete_event` sur CC/PGM. | `test_midi_editor.py` |
| **4k** | Implémentation — `dialogs_temporal.py` (`EventFilterDialog`) : sort `_TYPES_TO_COME`, groupes CC générique/Program Change, `_type_unavailable`. | `ui/dialogs_temporal.py` |
| **4l** | Tests — `EventFilterDialog` (sélection type CC/PGM disponible, groupes activés/désactivés, critères transmis). | `test_*` (dialog existant) |
| **4m** | Implémentation — `mew_display.py` (labels Ctrl+2), `mew_editing.py` (dispatch 4 types), `midi_editor_dialogs.py` (`_CcEventEditDialog` généralisé). | `ui/mew_display.py`, `ui/mew_editing.py`, `ui/midi_editor_dialogs.py` |
| **4n** | Tests — affichage Ctrl+2 (labels CC/PGM), édition via Entrée (valeur CC, valeur Program). | `test_midi_editor_window.py` |
| **4o** | Implémentation — `mw_project.py` : corrige le piège `else→PATCH` du presse-papier `TrackEditor` (`elif ETYPE_PATCH` + branches CC/PGM). | `ui/mw_project.py` |
| **4p** | Tests — presse-papier `TrackEditor` (Ctrl+C/X/V) avec un CC/PGM dans la plage copiée. | `test_track_editor.py` |
| **4q** | Doc — mise à jour mémoire (chantier clos), `pytest tests/` complet vérifié vert. | — |

**4b-4q FAITS** (commits `8547793`..`c309bac`, 1649 tests passed) —
**chantier Phase 7 étape 4 complet**. CC générique et Program Change sont
capturés dans `_tape` (`ETYPE_CC`/`ETYPE_PGM`), rejoués à la lecture avec
leur effet réel, filtrables par type et par plage (numéro/valeur de CC,
numéro de program), affichés dans la liste Ctrl+2 avec leur vrai canal et
leur nom MIDI/GM, éditables par Entrée, et traversent la sérialisation
`.gvp` (pattern et presse-papier `TrackEditor`). Suite verte à l'issue de
chaque paire impl+tests.

Les **trois pièges `else → PATCH`** annoncés en tête de ce plan ont tous
été corrigés avant d'introduire les nouveaux etypes : `drum_player.py`
(boucle de lecture, 4d), `midi/midi_editor.py::get_note_events` (4i) et
`ui/mw_project.py` (presse-papier, 4o). Deux corrections de plan notées en
cours de route : `delete_event` ne couvrait pas CC/PGM contrairement à ce
qu'affirmait la section Conception (corrigé en 4i, voir la note dédiée), et
l'effet live de Program Change a été décidé après coup (décision 2
révisée) alors que 2a l'avait écarté.

Point de conception à retenir pour la suite : `event_idx` compte parmi
**tous** les etypes d'une même position de `_tape`. C'est pour ça que les
notes et les CC/PGM dérivent du même helper `_events_by_time` — toute
nouvelle famille d'etype ajoutée à `_tape` devra faire pareil, sous peine
de viser le mauvais événement à la suppression/édition.

---

## Phase 7 étape 5a — Migration `_mod_tape` → `_tape`/`ETYPE_CC` (CC#1)

### Origine du besoin

Décision 1 de la Phase 7 étape 4a : CC#1 (Mod Wheel) est capturé **deux
fois** depuis l'étape 4f — dans `_mod_tape` (structure historique dédiée)
et dans `_tape` sous forme d'`ETYPE_CC` `cc_num=1`. Doublon assumé à
l'époque, migration notée comme chantier ultérieur (demandée le
2026-10-15). But : une seule source de vérité pour le mod wheel, comme
GRID/KIT/PATCH l'ont déjà pour les notes.

### État des lieux constaté en code (2026-10-16, 1649 tests verts)

**Où vit `_mod_tape`** (liste par piste de tuples `(float_offset, value)`,
pas de `TapeEvent`, pas de canal) :
- `pattern.py` : `__init__` (L161), `copy_from`, `new_pattern`,
  `reset_pattern`, `clear_track`, `double_bars`, `halve_bars`, `resize`,
  `to_dict` (clé `"mod_tape"`), `from_dict` (lecture tolérante, clé
  absente → listes vides).
- `drum_player.py` : `MOD_TAPE_EVENT = -5`, `_on_mod_tape_cb`, boucle
  `_run_thread` qui construit les `MOD_TAPE_EVENT` (L495-501) et les
  dispatche (L569-572), `record_mod()` (L1053).
- `ui/main_window.py:132` : `_on_mod_tape_cb = self._router.on_mod_tape`.
- `ui/midi_handler_window.py::on_cc` : `record_cc` pour **tous** les CC
  (L213), **plus** `record_mod(value)` dans la branche CC#1 (L238).
- `track_editor.py::_erase_tape_range` : efface la plage dans `_mod_tape`.
- `midi/midi_editor.py` : `get_all_events` produit des entrées
  `type="mod"` depuis `_mod_tape` en plus des `type="cc"` depuis `_tape`
  (donc **chaque mouvement de molette apparaît deux fois** dans Ctrl+2) ;
  `edit_mod_event` ; `filter_events` (`etype_filter="mod"`) ;
  `delete_event` ne gère pas `"mod"` (point mod non supprimable, alors
  que son jumeau `"cc"` l'est depuis 4i).
- UI : `mew_display.py` (2 branches `"mod"`), `mew_editing.py` (dispatch
  `"mod"` → `edit_mod_event`), `midi_editor_dialogs.py::_CcEventEditDialog`
  (branche `"mod"`), `dialogs_temporal.py::EventFilterDialog` (`_TYPE_MOD`,
  entrée « Mod Wheel (CC1) »).
- Tests : ~20 tests `_mod_tape` dans `test_tape.py` (L1401-1643), plus
  `test_pattern_properties_bug.py`, `test_pattern_grid_api.py`,
  `test_track_editor.py`, `test_midi_editor.py`, `test_midi_editor_filter.py`,
  `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`,
  `test_event_filter_dialog.py`.

**Lecture : CC#1 déjà rejoué deux fois.** `TrackRouter.on_cc_tape` délègue
CC#1 à `on_mod_tape` (4g) ; la boucle rejoue donc chaque point une fois
via `MOD_TAPE_EVENT` et une fois via `CC_TAPE_EVENT`. Inoffensif (même
valeur, même moteur) mais confirme que `_tape` suffit déjà à piloter le
vibrato : supprimer `MOD_TAPE_EVENT` ne demande **aucun** changement dans
`TrackRouter`.

**Le vrai piège : la résolution temporelle.** Les deux copies n'ont pas
la même précision :
- `record_mod` (comme `record_bend`) stocke l'offset **flottant brut**
  (sous-pas), jamais quantifié.
- `record_cc` passe par `_compute_record_offset` et stocke
  `_bar_step_to_time(bar_idx, step_idx)` — un **pas entier**, arrondi au
  plus proche, et en plus quantifié à la grille si
  `_quant_in_recording` est actif.

Conséquence : un balayage de molette (des dizaines de valeurs par pas)
est aujourd'hui fidèle dans `_mod_tape`, mais tassé sur la copie
`ETYPE_CC` : tous les points d'un même pas tombent au même instant à la
lecture → seule la dernière valeur est audible, effet « escalier ».
Supprimer `_mod_tape` sans traiter ça serait une **régression audible**.

Or plusieurs chemins supposent aujourd'hui un `TapeEvent.time` entier, et
perdraient ou rateraient une partie fractionnaire :
- `MidiEditor._delete_tape_event` / `_replace_tape_event` : retrouvent
  l'événement par `time = _bar_step_to_time(ev["bar"], ev["step"])` puis
  `e.time == time` → un CC à `time=3.4` serait **introuvable** (ou pire,
  `event_idx` résolu parmi les événements du temps 3).
- `Pattern.resize` : `divmod(int(ev.time), old_steps)` puis ré-encodage
  `bar*num_steps+step` → fraction perdue.
- `TrackEditor._extract`/`paste` (clé `(rel, bar, step)` puis
  `_bar_step_to_time`) et `ui/mw_project.py::_clipboard_to_dict`/
  `_clipboard_from_dict` (enregistrements `[etype, t, b, s, …]`) →
  fraction perdue au copier-coller de piste.
- Sans risque : `_run_thread` (utilise `ev.time` tel quel), `double_bars`/
  `halve_bars` (additions/comparaisons), `to_dict`/`from_dict` (`time`
  sérialisé tel quel en JSON), `_events_by_time` (groupe par `ev.time`
  exact, `_time_to_bar_step` fait `int()` pour l'affichage BBT).

### Décisions proposées (à valider par l'utilisateur)

1. **CC capturés en temps flottant non quantifié — pour tous les CC, pas
   seulement CC#1.** `record_cc` stocke l'offset brut de
   `_compute_record_offset` (sans arrondi au pas ni quantisation
   d'enregistrement), comme `record_bend`/`record_mod` aujourd'hui. Les
   CC sont des contrôleurs continus (volume, pan, mod…) : les tasser sur
   la grille n'a pas de sens musical, la quantisation reste réservée aux
   notes. `record_program_change` reste au pas entier (événement
   ponctuel, rien à lisser).
   - *Écarté* : garder CC au pas entier (régression audible du vibrato,
     voir ci-dessus) ; traiter CC#1 seul en flottant (deux règles pour un
     même etype, piège pour la future migration de `_bend_tape`).
   - Implique de rendre **sûrs vis-à-vis d'un `time` fractionnaire** les
     chemins listés plus haut : repérage par `ev["offset"]` (déjà fourni
     par `_events_by_time`, égal à `ev.time` exact) plutôt que par
     `bar/step` dans `_delete_tape_event`/`_replace_tape_event` ;
     conservation de la fraction dans `resize` et dans les deux
     presse-papiers `TrackEditor` (champ fraction optionnel en fin
     d'enregistrement, absent = 0, rétrocompatible).
   - Édition Entrée d'un CC (Ctrl+2) : si la position bar/step n'est pas
     changée, le `time` fractionnaire d'origine est conservé ; si elle
     l'est, l'événement est posé sur le pas entier choisi.
2. **Suppression complète de `_mod_tape`** : attribut, `record_mod`,
   `MOD_TAPE_EVENT`, `_on_mod_tape_cb` et son wiring, appel `record_mod`
   dans `on_cc`, branches `_mod_tape` de `Pattern`/`TrackEditor`.
   `TrackRouter.on_mod_tape` **reste** (appelé par `on_cc_tape` pour
   CC#1). Corrige au passage le double rejeu.
3. **Rétrocompatibilité `.gvp` : migration à l'ouverture.** `to_dict`
   n'écrit plus `"mod_tape"`. `from_dict`, si la clé est présente et
   non vide pour une piste, convertit chaque `(off, val)` en
   `TapeEvent(ETYPE_CC, channel=0, payload={"cc_num": 1, "value": val},
   time=off)` **et retire d'abord les `ETYPE_CC` `cc_num==1` déjà
   présents dans `tape_v2` pour cette piste** — les presets sauvés depuis
   4f contiennent les deux copies ; `_mod_tape` gagne car c'est la copie
   précise (temps flottant). Piste dont `mod_tape` est vide → ses
   `ETYPE_CC#1` sont gardés tels quels.
   - Limite assumée : un CC#1 supprimé à la main via Ctrl+2 (possible
     depuis 4i sur la copie `cc`) mais toujours présent dans `mod_tape`
     réapparaît à la première réouverture de ce preset ancien. Cas rare,
     une seule fois, documenté plutôt que traité.
   - *Écarté* : fusionner les deux sources (doublons garantis) ; ignorer
     `mod_tape` (perte de la précision temporelle des presets existants).
4. **Éditeur MIDI : un seul type `"cc"`.** `get_all_events` ne produit
   plus d'entrées `"mod"` ; un point de molette s'affiche comme n'importe
   quel CC (`describe_cc(1)` → « Modulation Wheel » déjà fourni par le
   libellé Ctrl+2 de 4m), est éditable par Entrée et supprimable.
   `edit_mod_event` et les branches `"mod"` de `mew_display`,
   `mew_editing`, `_CcEventEditDialog` disparaissent.
   - **`EventFilterDialog` garde l'entrée « Mod Wheel (CC1) »** comme
     raccourci de filtre : `etype_filter="mod"` est traduit dans
     `filter_events` en `type=="cc" and cc_num==1` (habitude conservée,
     pas besoin de passer par CC générique + numéro 1..1).
   - *Écarté* : retirer l'entrée du dialog (perte d'un raccourci
     accessible déjà connu, pour aucun gain).

### Portée explicitement exclue de ce chantier

- Migration de `_bend_tape` vers `_tape` (Pitch Bend n'a pas encore
  d'etype ; même schéma probable, que la décision 1 prépare) — chantier
  distinct.
- Quantisation des CC (`quantize_manager.py` les ignore toujours).
- Édition du `cc_num` d'un CC existant, `copy_events`/`paste_events`
  « niveau événement » pour CC/PGM (inchangé depuis 4a).
- Conversion du `time` flottant des CC déjà enregistrés au pas entier
  dans les presets existants (hors CC#1 remplacé par `mod_tape`) : ils
  restent tels quels.

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **5a** | Doc — ce plan. | `docs/DESIGN.md` |
| **5b** | Implémentation — temps flottant des CC (décision 1) : `record_cc` non quantifié ; `_delete_tape_event`/`_replace_tape_event` repèrent par `ev["offset"]` ; `edit_cc_event` conserve la fraction si position inchangée ; `Pattern.resize` conserve la fraction. | `drum_player.py`, `midi/midi_editor.py`, `pattern.py` |
| **5c** | Tests — `record_cc` hors pas entier même avec quantisation active ; suppression/édition d'un CC à `time` fractionnaire (dont cohabitation avec une note au pas entier voisin) ; `resize` préserve la fraction. | `test_drum_player_cc.py`, `test_midi_editor.py`, `test_tape.py` |
| **5d** | Implémentation — presse-papiers `TrackEditor` (`_extract`/`paste`) et `mw_project` (`_clipboard_to_dict`/`_from_dict`) : fraction de `time` conservée (champ optionnel, rétrocompatible). | `track_editor.py`, `ui/mw_project.py` |
| **5e** | Tests — copier/coller de piste et round-trip dict avec un CC fractionnaire ; ancien format sans fraction relu à l'identique. | `test_track_editor.py` |
| **5f** | Implémentation — éditeur MIDI un seul type `"cc"` (décision 4) : `get_all_events` sans `"mod"`, `edit_mod_event` supprimé, alias `"mod"` dans `filter_events`, branches `"mod"` retirées de `mew_display`/`mew_editing`/`_CcEventEditDialog`. | `midi/midi_editor.py`, `ui/mew_*.py`, `ui/midi_editor_dialogs.py` |
| **5g** | Tests — Ctrl+2 ne montre plus de doublon CC#1 ; filtre « Mod Wheel » = CC#1 seul ; tests `"mod"` existants adaptés. | `test_midi_editor*.py`, `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`, `test_event_filter_dialog.py` |
| **5h** | Implémentation — suppression de `_mod_tape` (décision 2) + migration `.gvp` à l'ouverture (décision 3). Suite rouge jusqu'à 5i (tests `_mod_tape` de `test_tape.py` obsolètes) — à signaler dans le titre du commit. | `pattern.py`, `drum_player.py`, `ui/main_window.py`, `ui/midi_handler_window.py`, `track_editor.py` |
| **5i** | Tests — retrait/adaptation des tests `_mod_tape` ; migration `from_dict` (mod_tape seul, mod_tape + doublon CC#1, mod_tape vide qui garde les CC#1) ; `to_dict` sans `"mod_tape"` ; CC#1 rejoué une seule fois ; `on_cc` n'appelle plus `record_mod`. | `test_tape.py`, `test_pattern_*.py`, `test_track_editor.py`, `test_midi_handler_window.py` |
| **5j** | Doc — clôture (DESIGN.md, mémoire), `pytest tests/` complet vert. | `docs/DESIGN.md` |

**5b-5j FAITS** (commits `37e9441`..`4b85a6b`, 1656 tests passed) —
**chantier Phase 7 étape 5 complet**. Les 4 décisions sont en place : CC en
temps flottant non quantifié (5b/5c, `ev["offset"]` plutôt que bar/step
reconstruit partout où ça comptait) ; presse-papiers `TrackEditor`/
`mw_project.py` sûrs vis-à-vis de la fraction (5d/5e) ; éditeur MIDI un seul
type `"cc"`, `"mod"` devenu un simple alias de filtre (5f/5g) ;
`_mod_tape` entièrement supprimé avec migration `.gvp` à l'ouverture (5h/5i).
CC#1 (Mod Wheel) n'a plus qu'une seule source de vérité, dans `_tape`, comme
GRID/KIT/PATCH/PGM l'ont déjà pour le reste.

Deux pièges trouvés en cours de route, hors plan d'origine, tous deux
corrigés immédiatement :
- En 5d : le nettoyage en mode remplace/fusion des presse-papiers comparait
  `ev.time` par égalité exacte — un CC fractionnaire déjà présent à
  destination aurait survécu à un collage "remplace". Comparaison par pas
  entier (`int(ev.time) != time`) à la place.
- En 5i : `test_track_editor.py::_make_pattern` posait encore
  `p._mod_tape = [...]`, une assignation qui aurait recréé l'attribut sans
  lever (contrairement à une lecture) — repéré en relisant tout le dépôt
  après coup, pas par un échec de test. Réflexe à garder : `grep -rn` sur le
  nom complet de la structure supprimée avant de clore un chantier de ce
  genre, ne pas se fier uniquement à la suite de tests.

5h et 5i ont été committés séparément bien que faits dans la même session
(impl rouge connue, puis tests qui ramènent au vert), pour garder le
découpage du plan lisible dans l'historique — convention à reprendre pour
un futur chantier de suppression de structure. La migration de `_bend_tape`
vers `_tape` (même schéma probable) reste explicitement hors périmètre de
ce chantier (voir Portée exclue ci-dessus), à numéroter séparément si elle
est un jour entreprise.

---

## Phase 7 étape 6a1 — Migration `_bend_tape` → `_tape`/`ETYPE_BEND` (Pitch Bend)

### Numérotation des commits de ce chantier

À partir de ce chantier, chaque étape prévue porte un suffixe numérique :
`6a1`, `6b1`, `6c1`… Un commit non prévu qui s'avère nécessaire en cours
de route se range sous l'étape à laquelle il se rattache avec le suffixe
suivant (`6a2`, `6b2`, `6b3`…), sans décaler les lettres des étapes
suivantes (décidé le 2026-10-17).

### Origine du besoin

Suite directe de l'étape 5 (demandée le 2026-10-17) : après CC#1, le
Pitch Bend est la **dernière automation** qui vit hors de `_tape`, dans une
structure parallèle `_bend_tape`. But : une seule source de vérité pour
tous les événements d'une piste (GRID/KIT/PATCH/CC/PGM/BEND), préalable à
l'import/export MIDI.

Différence avec l'étape 5 : il n'existe **aucune copie** du Pitch Bend dans
`_tape` aujourd'hui (pas de doublon à arbitrer), mais **aucun etype** non
plus — il faut en créer un. Et le Pitch Bend n'est pas un CC (statut MIDI
`0xE0`, valeur 14 bits signée, pas de `cc_num`) : il ne peut pas se fondre
dans `ETYPE_CC` comme CC#1 l'a fait.

### État des lieux constaté en code (2026-10-17, 1656 tests verts)

**Où vit `_bend_tape`** (liste par piste de tuples `(float_offset, value)`,
`value` dans -8192..+8191, ni `TapeEvent`, ni canal, ni verrou) :
- `pattern.py` : `__init__` (L159), `copy_from`, `new_pattern`,
  `reset_pattern`, `clear_track`, `double_bars`, `halve_bars`, `resize`,
  `to_dict` (clé `"bend_tape"`), `from_dict` (lecture tolérante, complétée
  à `_num_tracks`).
- `drum_player.py` : `BEND_TAPE_EVENT = -4`, `_on_bend_tape_cb`, boucle
  `_run_thread` qui construit les `BEND_TAPE_EVENT` (L488-494) **hors du
  snapshot sous verrou** de `_tape`, et les dispatche (L558-561) ;
  `record_bend()` (L1030), sans canal ni verrou.
- `ui/main_window.py:131` : `_on_bend_tape_cb = self._router.on_bend_tape`.
- `ui/midi_handler_window.py::on_pitch_bend` (L203) : `record_bend(bend)`
  (le canal reçu n'est pas transmis).
- `track_router.py::on_bend_tape` (L396) : applique la valeur au moteur
  du slot de la piste — inchangé par ce chantier.
- `track_editor.py::_erase_tape_range` : efface la plage dans `_bend_tape`.
- `midi/midi_editor.py` : `get_all_events` produit des entrées
  `type="bend"` (sans `etype`, `channel` ni `event_idx`) ;
  `edit_bend_event` (chirurgie directe sur la liste de tuples) ;
  `filter_events` (`etype_filter="bend"`, bornes `bend_lo/hi`) ;
  `delete_event` **ne gère pas** `"bend"` (point non supprimable).
- UI : `mew_display.py` (2 branches `"bend"`, format Ctrl+2 sans index ni
  canal, contrairement à CC/PGM), `mew_editing.py` (dispatch
  `"bend"` → `edit_bend_event`), `midi_editor_dialogs.py::_CcEventEditDialog`
  (branche `"bend"`, bornes -8192..8191), `dialogs_temporal.py::EventFilterDialog`
  (`_TYPE_BEND`, groupe de bornes Pitch Bend Bas/Haut).
- Tests : ~25 tests `_bend_tape`/`record_bend` dans `test_tape.py`
  (L1166-1476), plus `test_pattern_properties_bug.py`,
  `test_pattern_grid_api.py`, `test_track_editor.py` (fixture
  `_make_pattern` qui **assigne** `p._bend_tape` — le même piège que
  `_mod_tape` en 5i), `test_midi_editor.py`, `test_midi_editor_filter.py`,
  `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`,
  `test_event_filter_dialog.py`.

**Hors `_bend_tape`, sans rapport avec ce chantier** : le champ `"bend"`
du payload `ETYPE_PATCH` (valeur du bend au moment du note-on, rejouée par
`on_patch_tape`) et le payload `{"bend":}` de `MidiMessage` PitchBend
(`midi_parser.py`). Restent tels quels.

**Bugs existants que la migration corrige d'elle-même** (constatés en
relisant, aucun test ne les couvre aujourd'hui) :
1. **`Pattern.resize` ne ré-encode pas `_bend_tape`** quand `num_steps`
   change : il filtre seulement `off < total_steps`. Passer de 16 à 32 pas
   par mesure déplace un bend posé à la mesure 2 pas 1 (`off=16`) vers la
   mesure 1 pas 17. `_tape` passe déjà par le décodage/ré-encodage bar/step
   avec fraction (5b).
2. **Ctrl+X avec limiteurs perd les bends** : `_erase_tape_range` les
   efface, mais `_extract` ne les met pas dans le presse-papier (il ne lit
   que `_tape`). Même chose pour Ctrl+C/Ctrl+V de piste : les bends ne
   suivent pas. Une fois dans `_tape`, `_extract`/`paste` (génériques par
   etype, fraction conservée depuis 5d) les prennent en charge.
3. **`edit_bend_event` perd la fraction même si la position ne change
   pas** : il recalcule toujours `n_off = bar*num_steps+step` (entier).
   `_replace_tape_event` conserve déjà le `time` d'origine dans ce cas (5b).
4. **Itération de `_bend_tape` sans verrou** dans `_run_thread` pendant
   que `record_bend` y ajoute : le snapshot sous `_pattern._lock` couvrira
   les bends comme le reste.

**Chemins génériques qui fonctionneront sans modification** (ils
recopient `ev.etype`/`ev.payload` sans dispatch) : `copy_from`,
`double_bars`, `halve_bars`, `resize`, `to_dict`/`from_dict` (`tape_v2`),
`clear_track`, `TrackEditor._extract`/`paste`/fusion,
`_erase_tape_range` (partie `_tape`), `_events_by_time`,
`quantize_manager` (ne traite que KIT/PATCH, ignore le reste).

**Chemins à dispatch explicite à compléter** :
- `drum_player._run_thread` : nouvelle branche `ETYPE_BEND`.
- `ui/mw_project.py::_clipboard_to_dict` (ignore silencieusement un etype
  inconnu → bend perdu à la sauvegarde du presse-papier) et
  `_clipboard_from_dict` (sa branche `else` finale traite tout etype
  inconnu comme KIT/PATCH → enregistrement BEND **mal relu**). Branches
  `ETYPE_BEND` explicites dans les deux.
- `midi/midi_editor.py` : `get_cc_pgm_events` (ou équivalent) pour
  remonter les `ETYPE_BEND`, `delete_event`, `edit_bend_event`.

**Changement de comportement assumé** : `Pattern.is_empty()` (`not
any(self._tape)`) deviendra faux pour un pattern ne contenant que du
Pitch Bend — cohérent avec CC/PGM, qui sont déjà dans ce cas.

### Décisions validées (utilisateur, 2026-10-17)

1. **Nouvel etype `ETYPE_BEND = "BEND"`, payload `{"value": bend}`**
   (-8192..+8191, 0 = centre), `dur=0`, `channel` = canal MIDI d'origine
   (comme CC/PGM). Pas de `cc_num`.
   - `"value"` plutôt que `"bend"` : même clé que `ETYPE_CC`, que le dict
     d'événement de l'éditeur (`e["value"]`, déjà utilisé par le filtre
     `bend_lo/hi` et `_CcEventEditDialog`), et que la future traduction
     export MIDI (etype → statut, `value` → octets de données). La clé
     `"bend"` reste réservée au payload PATCH (bend au note-on), ce qui
     évite toute confusion entre les deux.
   - *Écarté* : réutiliser `ETYPE_CC` avec un `cc_num` fictif (ex. -1 ou
     128) — fausserait le filtre CC 0..127, `describe_cc`, l'édition Entrée
     (bornes 0..127) et l'export MIDI ; le Pitch Bend est un type de
     message MIDI à part entière.
2. **Capture en temps flottant non quantifié** (règle de 5a décision 1,
   déjà celle de `record_bend` aujourd'hui) : `record_bend(bend, channel=0)`
   ajoute un `TapeEvent(ETYPE_BEND, …)` sous `_pattern._lock`. Le calcul
   de l'offset flottant (dont la garde `time_val >= total_steps` que
   `record_bend` n'a pas) est **factorisé** avec `record_cc` dans un helper
   privé `_compute_float_offset()` plutôt que dupliqué une troisième fois.
   `on_pitch_bend` transmet le canal reçu.
3. **Lecture : on garde `BEND_TAPE_EVENT`, `_on_bend_tape_cb` et
   `TrackRouter.on_bend_tape`** — seule la source change (branche
   `ETYPE_BEND` dans la boucle sur le snapshot de `_tape`, la boucle
   séparée sur `_bend_tape` disparaît). Aucun changement dans
   `TrackRouter` ni dans le câblage de `main_window`.
   - *Écarté* : router via `CC_TAPE_EVENT` (le Pitch Bend n'est pas un CC,
     voir décision 1).
4. **Suppression complète de `_bend_tape`** : attribut et toutes ses
   branches dans `Pattern`, `TrackEditor._erase_tape_range`,
   `drum_player._run_thread`, `MidiEditor`. Avant de clore : `grep -rn
   _bend_tape` sur **tout** le dépôt, tests compris (leçon de 5i).
5. **Rétrocompatibilité `.gvp` : migration à l'ouverture.** `to_dict`
   n'écrit plus `"bend_tape"`. `from_dict` convertit chaque `(off, val)`
   de `"bend_tape"` (si présente) en `TapeEvent(ETYPE_BEND, channel=0,
   payload={"value": val}, time=off)` ajouté à `_tape[t]`. Pas de doublon
   à retirer (contrairement à `mod_tape`) ; `channel=0` faute
   d'information dans l'ancien format.
6. **Éditeur MIDI : `"bend"` reste un type réel** (pas un alias comme
   `"mod"`) — le filtre `etype_filter="bend"` et ses bornes `bend_lo/hi`,
   le groupe Pitch Bend de `EventFilterDialog`, la branche `"bend"` de
   `_CcEventEditDialog` restent inchangés.
   - Les entrées `"bend"` sont produites depuis `_tape` (par la même
     passe `_events_by_time` que CC/PGM, donc `event_idx` cohérent tous
     etypes confondus) et gagnent `etype`, `channel`, `event_idx`.
   - `edit_bend_event` passe par `_replace_tape_event` (fraction
     conservée si position inchangée — corrige le bug 3).
   - `delete_event` accepte `"bend"` (via `_delete_tape_event`) : un
     point de bend devient supprimable, comme CC/PGM depuis 4i.
   - Ctrl+2 : la ligne bend adopte le format des autres types
     (« `i: position, Canal c, Pitch Bend, Valeur +v` ») au lieu de
     l'ancien `Tr01  Bend:+v` sans index ni canal. Le format Ctrl+1
     (mode Notes) n'affiche pas les bends, inchangé.

### Portée explicitement exclue de ce chantier

- Le champ `"bend"` du payload `ETYPE_PATCH` (bend figé au note-on) :
  inchangé, sa coexistence avec l'automation `ETYPE_BEND` est un sujet
  musical distinct.
- `TrackRouter.on_bend_tape` et le moteur synthé (application du bend).
- Quantisation des bends (comme les CC, ignorés par `quantize_manager`).
- `copy_events`/`paste_events` « niveau événement » pour bend/CC/PGM
  (inchangé depuis 4a, notes seulement).
- Changement de canal d'un bend existant à l'édition (comme CC/PGM).
- Bends déjà enregistrés dans des presets existants : migrés tels quels
  avec `channel=0`, aucun recalage.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **6a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **6b1** | Implémentation — `ETYPE_BEND` (constante + docstring `TapeEvent`) ; helper `_compute_float_offset` partagé par `record_cc`/`record_bend` ; `record_bend(bend, channel)` écrit dans `_tape` ; `on_pitch_bend` passe le canal ; branche `ETYPE_BEND` dans `_run_thread` (boucle `_bend_tape` retirée). Suite rouge jusqu'à 6c1 (tests `record_bend`/`_run_thread` de `test_tape.py`) — à signaler dans le titre. | `pattern.py`, `drum_player.py`, `ui/midi_handler_window.py` |
| **6c1** | Tests — `record_bend` crée un `ETYPE_BEND` flottant non quantifié avec canal, sur la piste courante ; garde de fin de boucle ; `record_cc` inchangé après factorisation ; lecture d'un `ETYPE_BEND` → `_on_bend_tape_cb(track, value)` une seule fois ; adaptation des tests `record_bend` existants. | `test_tape.py`, `test_drum_player_cc.py`, `test_midi_handler_window.py` |
| **6d1** | Implémentation — éditeur MIDI (décision 6) : bends remontés depuis `_tape` avec `event_idx`/`channel`/`etype`, `edit_bend_event` via `_replace_tape_event`, `delete_event` accepte `"bend"`, nouveau format Ctrl+2. | `midi/midi_editor.py`, `ui/mew_display.py` |
| **6e1** | Tests — bend listé avec `event_idx` cohérent à côté d'une note/CC au même `time` ; édition valeur seule conserve la fraction ; déplacement → pas entier ; suppression ; filtre `"bend"` + bornes ; libellé Ctrl+2. Adaptation des tests qui posaient `_bend_tape` à la main. | `test_midi_editor*.py`, `test_cc_event_edit_dialog.py`, `test_midi_editor_window.py`, `test_event_filter_dialog.py` |
| **6f1** | Implémentation — presse-papiers `mw_project` : branches `ETYPE_BEND` dans `_clipboard_to_dict`/`_clipboard_from_dict` (avec fraction). | `ui/mw_project.py` |
| **6g1** | Tests — Ctrl+X/Ctrl+C/Ctrl+V de piste transportent les bends (fraction comprise, corrige le bug 2) ; round-trip dict du presse-papier avec un bend ; enregistrement BEND non relu comme KIT/PATCH. | `test_track_editor.py`, test presse-papier `mw_project` existant |
| **6h1** | Implémentation — suppression de `_bend_tape` (décision 4) + migration `.gvp` à l'ouverture (décision 5). Suite rouge jusqu'à 6i1 — à signaler dans le titre. | `pattern.py`, `track_editor.py`, `drum_player.py` |
| **6i1** | Tests — retrait/adaptation des tests `_bend_tape` (dont la fixture `test_track_editor.py::_make_pattern`) ; migration `from_dict` (`bend_tape` seul, avec notes/CC existants, absente) ; `to_dict` sans `"bend_tape"` ; `resize` 16→32 pas garde la position musicale d'un bend (corrige le bug 1) ; `double_bars`/`halve_bars`/`copy_from` sur `ETYPE_BEND`. | `test_tape.py`, `test_pattern_*.py`, `test_track_editor.py` |
| **6j1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` si concerné, mémoire), `grep -rn _bend_tape` sur tout le dépôt, `pytest tests/` complet vert. | `docs/DESIGN.md` |

Ordre choisi : capture/lecture d'abord (6b1-6c1), pendant que `_bend_tape`
existe encore comme attribut vide — l'éditeur (6d1) et le presse-papier
(6f1) peuvent alors être testés sur `ETYPE_BEND` seul, et la suppression
de la structure (6h1) n'arrive qu'en dernier, comme en 5h.

### Avancement et écarts constatés

- **6b1** (`61eb827`) — conforme au plan.
- **6c1** — un écart : la garde « fin de boucle » de
  `_compute_float_offset` (`time_val >= total_steps` → 0.0) **n'est pas
  testée**. Une recherche numérique (tous les BPM entiers 40-300, et
  200 000 durées de pas aléatoires, avec la plus grande valeur flottante
  inférieure à la durée de boucle) n'a trouvé aucun cas où
  `((now-ref) % measure_secs) / step_duration` atteint `total_steps`. La
  garde reste en place par prudence (elle existait déjà dans `record_cc`),
  sans test qui la déclenche. Le rejeu est testé sur la vraie boucle
  `_run_thread` (`play_pattern` à 600 BPM), pas sur une copie de sa
  logique comme l'ancien test `test_run_thread_build_bend_tape_events`.
- **6d1-6g1** — conformes au plan. Constaté en 6d1 : Suppr dans l'interface
  de l'éditeur ne supprime que les notes (CC/PGM/bend supprimables
  seulement via `MidiEditor.delete_event`) — inchangé, hors périmètre.
- **6g2** (commit imprévu, correction + tests) — bug pré-existant trouvé en
  6g1 : le limiteur droit, censé inclure son pas, était comparé par
  `ev.time <= lim_r`. Un CC (depuis 5b) ou un bend à 5.4 avec limiteur
  droit sur 5 n'était ni effacé (`TrackEditor._erase_tape_range`) ni
  listé dans Ctrl+2 (`MidiEditor._events_by_time`) ; même défaut pour la
  borne `pos_to` de `filter_events`. Correction : comparaison au pas
  entier (`ev.time < lim_r + 1`, `offset >= int(pos_to) + 1`), même règle
  que le collage en 5d. Les notes (toujours au pas entier) ne changent
  pas de comportement.
- **6h1-6i1** — conformes au plan. En 6i1, vérifié en plus en lecture
  seule que les `.gvp`/preset du dépôt (`data/`) se chargent ; aucun ne
  contient de point `bend_tape`, la conversion n'est donc éprouvée que
  par les tests (`project_01.gvp` garde une clé `"bend_tape"` vide,
  convertie et retirée à sa prochaine sauvegarde).

### Clôture (6j1)

**6a1-6i1 FAITS** (commits `737497e`..`76cec7a`, 1689 tests passed) —
**chantier Phase 7 étape 6 complet**. Les 6 décisions sont en place :
`ETYPE_BEND` (payload `{"value"}` + canal) capturé en temps flottant via
`_compute_float_offset` partagé avec `record_cc` (6b1/6c1) ; rejoué par le
même chemin `BEND_TAPE_EVENT` → `on_bend_tape` depuis le snapshot sous verrou
de `_tape` ; éditeur MIDI sur `_tape`, `"bend"` type réel, supprimable,
même format Ctrl+2 que CC/PGM (6d1/6e1) ; presse-papier de piste et sa
sérialisation (6f1/6g1) ; `_bend_tape` supprimé + migration `.gvp` (6h1/6i1).

**Toutes les automations vivent désormais dans `_tape`** (GRID/KIT/PATCH/
CC/PGM/BEND) : plus aucune structure parallèle, préalable à l'import/export
MIDI.

Les 4 bugs pré-existants du plan sont corrigés et testés (resize 16→32 pas,
Ctrl+X avec limiteurs, fraction perdue à l'édition, itération sans verrou —
ce dernier par construction, sans test dédié). Un 5e, hors plan, corrigé en
6g2 (limiteur droit / `pos_to` excluant la fraction de leur pas).

`grep -rn _bend_tape` final sur tout le dépôt : dans `src/`, plus que des
commentaires historiques et la lecture de l'ancienne clé `"bend_tape"` par
`from_dict` ; dans `tests/`, idem plus les tests de migration ; aucune
assignation résiduelle (fixture `test_track_editor.py` nettoyée en 6i1).
`docs/SPECS.md` mis à jour (Pitch Bend, format Ctrl+2, édition, limiteurs).

**Restent hors périmètre** (inchangés, voir Portée exclue) : champ `"bend"`
des notes PATCH, Suppr de CC/PGM/bend depuis l'interface de l'éditeur,
`on_pitch_bend` qui ne capture rien si aucun synthé n'est prêt (retour
anticipé avant `record_bend`, comportement antérieur à ce chantier).

Convention de numérotation `6a1`/`6b1`… (suffixe numérique pour les commits
imprévus) éprouvée : un seul commit imprévu, `6g2`.

---

## Phase 7 étape 7a1 — Points restants du Pitch Bend : Suppr, capture sans synthé, champ `"bend"` des notes PATCH

### Numérotation des commits de ce chantier

Même convention qu'en 6 : `7a1`, `7b1`, `7c1`… ; un commit imprévu inséré
après `7b1` s'appelle `7b2`, `7b3`, etc.

### Origine du besoin

Le chantier 6 a laissé trois points hors périmètre (voir sa section
« Clôture (6j1) »). Ce chantier les traite, plus un bug trouvé en écrivant
ce plan.

### État des lieux constaté en code (2026-10-17, 1689 tests verts)

**Point 1 — Suppr dans l'éditeur MIDI** (`ui/mew_delete_clipboard.py::_delete_event`).
- Avec une sélection, seules les notes (`type == "note"`) sont gardées ;
  sinon le message est « Aucune note sélectionnée supprimable ».
- Sans sélection, c'est le groupe au même offset (`group_indices`), filtré
  sur les notes ; sinon le message est « Suppression non disponible pour ce
  type ».
- Pourtant, `MidiEditor.delete_event` sait déjà supprimer `"cc"`, `"pgm"` et
  `"bend"` (depuis 4i et 6d1). Il ne manque que l'interface.
- En Ctrl+1 (`MODE_NOTES`), la liste ne contient que des notes.
- En Ctrl+2 (`MODE_ALL`), elle contient aussi CC, PGM et Pitch Bend.
- Entrée en Ctrl+2 édite l'événement sous le curseur, quel que soit son type.

**Bug pré-existant trouvé (bug A) — suppression d'un accord KIT/PATCH.**
- `_delete_tape_event` retrouve un événement par `time` + `event_idx`.
  `event_idx` est sa position parmi tous les événements de la piste à ce
  `time`, dans l'ordre de `_tape`.
- `get_note_events` trie l'affichage par `(offset, pad)`, donc dans un ordre
  qui peut différer de `event_idx`.
- `_delete_event` supprime « à l'envers de l'affichage ». Après la première
  suppression, les `event_idx` restants sont décalés.
- Reproduit hors suite : deux notes PATCH au temps 0, 67 puis 60 dans
  `_tape`. Affichage : 60 (idx 1), 67 (idx 0). `delete_event` sur les deux
  à l'envers de l'affichage → `[True, False]`, **la note 60 reste**.
- Pas de souci pour les notes GRID seules (elles passent par `set_cell`,
  par pad). Mais un mélange GRID + KIT/PATCH, ou demain note + bend au
  même pas, est touché.

**Point 2 — `on_pitch_bend` sans synthé** (`ui/midi_handler_window.py`).
- `if not win._router.synth_ready(): return` arrive **avant**
  `record_bend`.
- Si la piste courante n'a pas de synthé chargé, la molette n'est donc pas
  enregistrée.
- À l'inverse, `on_cc` enregistre (`record_cc`) avant tout effet live.
- La relecture (`TrackRouter.on_bend_tape`) ignore déjà proprement une
  piste dont le slot n'est pas un synthé.

**Point 3 — champ `"bend"` des notes PATCH.**
- À la capture, `_handle_synth_note_on` lit `synth.pitch_bend` (0 si pas de
  synthé) et le passe à `record_patch_note(…, bend=)`, qui l'écrit dans le
  payload `{"note","vel","bend"}`.
- À la relecture, `_run_thread` le passe à `on_patch_tape(…, bend)`.
  `on_patch_tape` pose `engine.pitch_bend = bend` le temps du `play()`,
  puis **restaure l'ancienne valeur**. Le bend est donc propre à la note,
  pas un état de canal.
- Il y a deux sources de vérité pour le bend :
  - le payload de la note, valeur figée à son départ ;
  - les `ETYPE_BEND`, état du canal.
  Elles peuvent se contredire au même pas.
- Le MIDI ne connaît que l'état de canal : un fichier `.mid` n'a pas de
  bend par note. C'est un frein pour l'import/export et le mode Rack GM.
- Ordre de rejeu à `t_sec` égal : `events.sort()` trie sur le marqueur, donc
  `BEND_TAPE_EVENT` (-4) passe avant `PATCH_TAPE_EVENT` (-3). Un bend posé au
  même temps qu'une note s'applique donc avant elle.
- Autres porteurs du champ :
  - `MidiEditor` (dicts de notes, `edit_tape_note`, insertion,
    duplication) ;
  - presse-papier `mw_project` (`rec[7]` pour PATCH) ;
  - `TrackEditor` (collage) ;
  - `Pattern.from_dict` (ancien format `patch_tape`, `rec[6]`) ;
  - le docstring `TapeEvent`.
- Données réelles : les `.gvp` et le preset de `data/` ne contiennent
  **aucun** `"bend"` non nul.

### Décisions proposées (à valider par l'utilisateur)

**D1 — Suppr dans l'éditeur supprime tout type d'événement.**
- Avec une sélection : tous les événements sélectionnés sont supprimés,
  quel que soit leur type.
- Sans sélection, curseur sur une note : comportement inchangé, l'accord
  entier est supprimé. Les CC, PGM et bends au même offset sont conservés.
- Sans sélection, curseur sur un CC, un PGM ou un bend : seul cet événement
  est supprimé (même logique qu'Entrée, qui édite la ligne sous le
  curseur).
- Messages et libellés d'undo :
  - « Pitch Bend supprimé » ;
  - « CC#7 supprimé » ;
  - « Program Change supprimé » ;
  - « N événement(s) supprimé(s) » pour une sélection mixte ;
  - les messages actuels sont gardés quand la sélection ne contient que
    des notes.
- Correction du bug A au même endroit :
  - nouvelle méthode `MidiEditor.delete_events(pattern, evs)` ;
  - elle supprime dans l'ordre `(track, time, event_idx)` décroissant, si
    bien qu'aucune suppression ne décale un `event_idx` encore à traiter ;
  - elle s'applique aussi aux notes GRID (`set_cell` retire l'entrée `_tape`
    à son propre index) ;
  - elle retourne le nombre d'événements supprimés ;
  - `_delete_event` l'utilise dans les deux branches.

**D2 — `on_pitch_bend` enregistre même sans synthé.**
- `record_bend(bend, channel)` est appelé si `recording`, **avant** le test
  `synth_ready()`, comme dans `on_cc`.
- Sans synthé, le message de statut devient « Pitch Bend: +1234 » (valeur
  brute). Les demi-tons dépendent du moteur.
- L'effet live et le log sont inchangés quand un synthé est prêt.

**D3 — le bend devient un état de canal uniquement (option B, recommandée).**
- **Capture.** `record_patch_note` n'écrit plus `"bend"` dans le payload.
  Si la valeur de bend reçue diffère de l'état de bend de la piste à cet
  instant, il pose d'abord un `ETYPE_BEND` (même canal) **au temps de la
  note**. L'état de bend est la valeur du dernier `ETYPE_BEND` de la piste
  de temps ≤ celui de la note, ou 0 s'il n'y en a pas.
  - Un bend tenu *avant* d'armer l'enregistrement est ainsi conservé (c'est
    ce que le champ servait à faire).
  - Il n'y a pas de doublon quand `on_pitch_bend` (D2) a déjà enregistré
    la même valeur.
- **Relecture.**
  - `on_patch_tape` perd le paramètre `bend` et l'écrasement/restauration
    de `engine.pitch_bend` : la note joue avec l'état courant du moteur ;
  - le tuple `PATCH_TAPE_EVENT` de `_run_thread` perd le bend ;
  - l'ordre de tri (-4 avant -3) garantit qu'un bend au même temps
    s'applique avant la note.
- **Éditeur et presse-papier.**
  - Le champ `"bend"` disparaît des dicts de notes et des payloads créés
    par l'insertion, la duplication et l'édition.
  - Le presse-papier `mw_project` garde la même position d'enregistrement,
    pour lire un presse-papier sauvé avant ce chantier. Il y écrit 0 et
    ignore la valeur à la lecture.
  - Même chose pour le collage de `TrackEditor`.
- **Migration à l'ouverture (`from_dict`, `tape_v2` et ancien
  `patch_tape`).**
  - Pour chaque piste, on parcourt ses notes PATCH par temps croissant et on
    applique la même règle qu'à la capture. Les `ETYPE_BEND` qui
    reproduisent le bend de départ de chaque note sont posés : une note
    à 0 après une note pliée remet donc l'état à 0.
  - Puis `"bend"` est retiré des payloads.
  - Seule différence assumée : deux notes qui se chevauchent partagent
    désormais le même bend, comme en MIDI.
  - Aucune donnée réelle n'est concernée, la conversion n'est éprouvée que
    par les tests.

Alternatives écartées :
- **A — garder le champ tel quel.** Deux sources de vérité qui peuvent se
  contredire, et rien à exporter en MIDI.
- **C — retirer le champ sans poser de bend au note-on.** Un bend tenu avant
  d'armer l'enregistrement serait perdu, alors qu'il est capturé
  aujourd'hui.

### Portée explicitement exclue de ce chantier

- Suppr en Ctrl+1 (`MODE_NOTES`) : la liste ne contient que des notes, donc
  le comportement ne change pas (hors correction du bug A).
- `copy_events`/`paste_events` « niveau événement » de l'éditeur pour
  CC/PGM/bend (notes seulement depuis 4a).
- Quantisation des bends, `TrackRouter.on_bend_tape`, moteur synthé.
- Application live du bend à un moteur de slot quand aucun synthé n'est
  « courant » (D2 ne touche que la capture).
- Champ `"bend"` du `MidiMessage` du parser (c'est le message Pitch Bend
  lui-même, sans rapport).

### Découpage en commits proposé (à valider avant de coder)

| Étape | Contenu | Fichiers |
|---|---|---|
| **7a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **7b1** | Implémentation — D1 : `MidiEditor.delete_events` (ordre `event_idx` décroissant, corrige le bug A) ; `_delete_event` supprime tout type en sélection, et l'événement sous le curseur s'il n'est pas une note ; messages/undo. | `midi/midi_editor.py`, `ui/mew_delete_clipboard.py` |
| **7c1** | Tests — accord PATCH 67/60 entièrement supprimé (bug A) ; mélange GRID + PATCH + bend au même pas ; Suppr Ctrl+2 sur un bend/CC/PGM seul ; sélection mixte ; curseur sur une note avec bend au même offset (bend conservé) ; undo restaure ; messages. | `test_midi_editor.py`, `test_midi_editor_window.py` |
| **7d1** | Implémentation — D2 : `record_bend` avant `synth_ready()` dans `on_pitch_bend`, statut sans synthé. | `ui/midi_handler_window.py` |
| **7e1** | Tests — enregistrement sans synthé prêt (`ETYPE_BEND` créé, statut brut) ; pas d'enregistrement hors `recording` ; cas synthé prêt inchangé. | `test_midi_handler_window.py` |
| **7f1** | Implémentation — D3 capture/relecture : `record_patch_note` sans `"bend"` + pose d'un `ETYPE_BEND` si l'état de piste diffère ; `_run_thread`/`on_patch_tape` sans bend ; docstring `TapeEvent`. Suite rouge jusqu'à 7g1 — à signaler dans le titre. | `drum_player.py`, `track_router.py`, `pattern.py` |
| **7g1** | Tests — note avec bend tenu → un `ETYPE_BEND` au temps de la note, payload sans `"bend"` ; pas de doublon si l'état est déjà égal ; bend 0 sans état antérieur → aucun `ETYPE_BEND` ; rejeu réel : bend appliqué avant la note au même temps ; adaptation des tests existants. | `test_tape.py`, `test_midi_handler_window.py`, tests `on_patch_tape` |
| **7h1** | Implémentation — D3 éditeur/presse-papier/migration : champ retiré de `MidiEditor` et `TrackEditor`, presse-papier `mw_project` (position gardée, valeur ignorée), migration `from_dict` (`tape_v2` et `patch_tape`). Suite rouge jusqu'à 7i1 — à signaler dans le titre. | `midi/midi_editor.py`, `track_editor.py`, `ui/mw_project.py`, `pattern.py` |
| **7i1** | Tests — migration : notes pliées → `ETYPE_BEND` équivalents, retour à 0 sur la note suivante non pliée, payloads nettoyés, fichier sans bend inchangé ; presse-papier ancien format ; éditeur sans champ `"bend"` ; adaptation des tests existants. | `test_tape.py`, `test_pattern_*.py`, `test_midi_editor.py`, `test_track_editor.py` |
| **7j1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` : Suppr, Pitch Bend), `grep -rn '"bend"'` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

Ordre choisi :
- D1 d'abord : indépendant, et il corrige un bug.
- D2 avant D3, parce que la pose d'un bend au note-on (D3) complète la
  capture de la molette (D2) et que ses tests de non-doublon en dépendent.
- Dans D3, la capture/relecture passe avant la migration, comme en 6.
