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

### Avancement et écarts constatés

- **7b1/7c1** (`87239f9`, `0f4d25b`) — conformes au plan. La contre-épreuve
  des tests de fenêtre sur le code d'avant 7b1 n'est pas possible (le
  fichier de tests ne s'importe pas sans `_deleted_name`) : le bug A reste
  démontré par la reproduction de 7a1 et par les tests de
  `MidiEditor.delete_events`.
- **7d1/7e1** (`e7bb8b3`, `4c99d05`) — conformes. Contre-épreuve : 3 tests
  rouges sur l'ancien code (capture sans synthé, statut brut, bout en bout
  avec un vrai `DrumPlayer`).
- **7f1/7g1** (`d8769a9`, `e5f4a76`) — conformes. La règle d'état est dans
  `Pattern._bend_state_at`/`_chase_bend`, partagée avec la migration.
  Point noté, non traité : à temps égal, `_bend_state_at` retient le
  dernier `ETYPE_BEND` dans l'ordre de `_tape`, alors que la relecture
  (`events.sort()` sur les tuples) les rejoue triés par valeur — deux bends
  différents exactement au même temps sur une piste peuvent donc laisser un
  état final différent de celui calculé. Cas non produit par la capture
  (temps flottants) ; à reprendre si l'import MIDI en crée.
- **7h1/7i1** (`e94603b`, `3efbb59`) — conformes. Les tests qui
  construisaient encore des notes PATCH avec `"bend"` (fixtures de
  `test_midi_editor.py`, `test_pattern_grid_api.py`,
  `test_pattern_properties_bug.py`, `test_transport.py`) sont passés au
  nouveau format ; l'ancien n'existe plus que via `_P_old` dans les tests
  de migration.

### Clôture (7j1)

**7a1-7i1 FAITS** (commits `7a289b9`..`3efbb59`, 1746 tests passed) —
**chantier Phase 7 étape 7 complet**. Les trois points laissés par le
chantier 6 sont résolus :

- **D1** — Suppr de l'éditeur MIDI supprime tout type d'événement
  (sélection ; curseur sur CC/PGM/bend → cet événement seul ; curseur sur
  une note → l'accord, bends du même pas conservés). Bug A corrigé :
  `MidiEditor.delete_events` supprime par `event_idx` décroissant, un
  accord KIT/PATCH n'est plus supprimé à moitié.
- **D2** — `on_pitch_bend` capture même sans synthé prêt.
- **D3** — le bend est un état de canal : plus de champ `"bend"` par note
  PATCH (capture, relecture, éditeur, presse-papier, collage), bend tenu au
  note-on reporté en `ETYPE_BEND`, anciens fichiers convertis à l'ouverture.
  Le bend n'a plus qu'une source de vérité, préalable à l'export MIDI.

`grep -rn '"bend"'` final sur tout le dépôt : dans `src/`, plus que la
migration (`Pattern.from_dict`/`_migrate_patch_note_bends`), la colonne
gardée du presse-papier (`mw_project`, écrite à 0) et des usages sans
rapport (message Pitch Bend du parser MIDI, type d'événement `"bend"` de
l'éditeur et du filtre) ; dans `tests/`, les tests de migration
(`_P_old`) et d'ancien presse-papier. `docs/SPECS.md` mis à jour (Pitch
Bend, Suppr, et description de `TapeEvent`/`_tape`/format `tape_v2`, qui
décrivait encore la structure d'avant la Phase 7).

Restent hors périmètre : copier/coller « niveau événement » de l'éditeur
pour CC/PGM/bend, quantisation des bends, le cas des bends à temps égal
ci-dessus.

---

## Phase 7 étape 8a1 — Découpage de `drum_player.py` en mixins

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 et 7 : `8a1`, `8b1`, `8c1`… ; un
commit imprévu inséré après `8b1` s'appelle `8b2`, `8b3`, etc.

### Origine du besoin

- `src/drum_player.py` fait 1148 lignes. C'est de loin le plus gros fichier
  de `src/` : le suivant, `pattern.py`, fait 635 lignes.
- Décision de l'utilisateur (2026-10-17) : découper ce fichier **avant** le
  chantier Import/Export MIDI, pour partir d'un code découpé.
- Précédents : Phase 5 étapes 11a–12a (gros fichiers éclatés en mixins ou
  par composition) et Phase 6 étape 12a (`midi_editor_window.py`, 2401 →
  101 lignes, 10 mixins `ui/mew_*.py`).

### État des lieux constaté en code (2026-10-18, 1746 tests verts)

**Une seule classe, `DrumPlayer`, plus un helper de module.**
- `_bend_log` (l. 13-22) : log pitch bend activé par `GROOVY_BEND_LOG=1`.
  Il est utilisé seulement par `record_patch_note`/`record_patch_note_off`.
  Trois autres copies identiques existent dans `track_router.py`,
  `synth_engine.py` et `ui/midi_handler_window.py`.
- Sept constantes de classe `*_EVENT` (l. 25-33). Elles ne servent qu'à
  `_run_thread`. Un test lit `DrumPlayer.GRID_EVENT`.
- `__init__` (l. 35-109) : environ 75 attributs d'état, partagés par toutes
  les responsabilités ci-dessous.
- Deux objets sont déjà extraits par composition : `QuantizeManager`
  (`self._qm`, qui reçoit le player comme `owner`) et `LoopManager`
  (`self._lm`). `Metronome` (`self._metro`) et `VoiceManager` aussi.

**Responsabilités repérées (lignes actuelles) :**

| Bloc | Méthodes | Lignes | Taille |
|---|---|---|---|
| Propriétés | `_loop_remaining`, `float_offsets`, `clicking`, `click_in_recording` | 112-145 | ~35 |
| Thread et transport | `start_thread`, `stop_thread`, `play_pattern`, `stop_pattern`, `play_song`, `pause_pattern`, `play_click`, `stop_click`, `stop_all`, `set_bpm` | 148-227, 389-419, 1129-1134 | ~120 |
| Position et navigation | `goto_start`, `goto_end`, `_go_to_offset`, `_current_offset`, `position_str`, `time_str`, `move_by_ticks/beats/seconds/bars`, `navigate_bar` | 229-387 | ~160 |
| Boucle de lecture | `_run_thread` (une seule méthode) | 422-669 | ~250 |
| Délégations quantisation | `apply_quant_row`, `double_pattern`, `halve_pattern`, `apply_quant_to_pattern`, `_compute_offsets`, `load_pattern` | 672-701 | ~30 |
| Jeu live et Note Repeat | `play_sound`, `start_note_repeat`, `stop_note_repeat`, `update_nr_rate`, `set_volume`, `set_pan`, `_mix_pan` | 705-744, 1137-1146 | ~55 |
| Enregistrement | `record_pattern`, `record_pattern_with_count_in`, `stop_record`, `start_replace_recording`, `_record_nr_hit`, `_compute_record_offset`, `_compute_float_offset`, `record_hit`, `record_patch_note`, `record_patch_note_off`, `record_bend`, `record_kit_note`, `record_cc`, `record_program_change` | 747-792, 897-915, 935-1127 | ~265 |
| Effacement (Erase) | `toggle_erase`, `_erase_tape_event`, `erase_hit`, `erase_patch_tape_note`, `_clear_offset` | 794-895, 917-933 | ~120 |

**Couplage avec le reste du code.**
- Deux importeurs dans `src/` (`ui/main_window.py`,
  `ui/midi_handler_window.py`) et huit fichiers de tests font
  `from drum_player import DrumPlayer`.
- L'interface accède à environ 70 attributs et méthodes différents de
  `_player` (`_pattern` et `_cur_track` 51 fois chacun, `voice_manager` 39
  fois, `_compute_offsets` 22 fois…). Les tests en touchent environ 150,
  dont beaucoup d'attributs privés (`_measure_start`, `_pending_patch`,
  `_count_in`…).
- Un seul patch de module dans les tests :
  `mock.patch("drum_player.time.perf_counter")`
  (`test_tape.py::test_compute_float_offset_shared_by_cc_and_bend`). Il
  vise `_compute_float_offset`, donc il cassera si cette méthode change de
  module.
- Toutes les méthodes lisent et écrivent l'état commun : `playing`,
  `recording`, `_measure_start`, `step_duration`, `_pattern`, `_wakeup`…

**`_run_thread` (250 lignes) mélange trois choses dans une seule boucle :**
1. construire la liste des événements de la mesure (tape, métronome, Note
   Repeat), l. 448-497 ;
2. attendre puis distribuer chaque événement selon son marqueur, l. 499-578 ;
3. gérer la fin de mesure : count-in, compteur de boucle, enchaînement
   des patterns d'un song, pause en fin de pattern, l. 579-669.

La variable locale `measure_start` est modifiée par les points 2 et 3, et
le `for … else` lie la fin de mesure au fait que la boucle d'événements
n'a pas été interrompue par `_wakeup`.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — des mixins, pas de la composition.**
- Chaque bloc du tableau devient une classe mixin sans `__init__`, dans
  son propre fichier. `DrumPlayer` hérite de tous les mixins et garde
  `__init__`, les propriétés et les délégations de quantisation.
- L'état reste dans `DrumPlayer.__init__`, comme aujourd'hui. Les mixins
  lisent et écrivent `self.<attribut>` sans changement de code.
- L'interface publique et privée ne change pas. Aucun des ~70 accès de
  l'interface ni des ~150 accès des tests n'est à réécrire.
- C'est le modèle de `midi_editor_window.py` (Phase 6 étape 12a,
  `ui/mew_*.py`).

Alternative écartée — **composition** (un `Recorder`, un `Transport`…
qui reçoivent le player comme `owner`, comme `QuantizeManager`) :
- il faudrait des délégations pour chaque méthode publique, soit une
  trentaine de méthodes d'une ligne dans `DrumPlayer`, ou bien réécrire les
  appelants (`_player.recorder.record_hit(...)`) ;
- l'état étant entièrement partagé, chaque objet passerait son temps à
  lire `self._p.<attribut>` : la séparation ne serait que de façade.

**D2 — package `src/player/`, qui accueille aussi `drum_player.py` en fin
de chantier.**
- Les mixins vont dans un nouveau package `src/player/`, comme `src/midi/`
  (Phase 7 étape 3a) :

  | Fichier | Classe | Contenu |
  |---|---|---|
  | `player/dp_transport.py` | `TransportMixin` | thread, play/stop/pause, song, click, `stop_all`, `set_bpm` |
  | `player/dp_position.py` | `PositionMixin` | position, chaînes de statut, déplacements, `navigate_bar` |
  | `player/dp_playback.py` | `PlaybackLoopMixin` | `_run_thread` et les constantes `*_EVENT` |
  | `player/dp_live.py` | `LivePlayMixin` | `play_sound`, Note Repeat, volume, pan |
  | `player/dp_recording.py` | `RecordingMixin` | armement de l'enregistrement, calcul des positions, tous les `record_*`, `_record_nr_hit`, `_bend_log` |
  | `player/dp_erase.py` | `EraseMixin` | `toggle_erase`, effacement au passage et ciblé, `_clear_offset` |

- Pendant les déplacements des mixins, `src/drum_player.py` reste à sa
  place : les commits 8b1-8e1 ne touchent pas aux importeurs.
- **Dernier commit de code (8g1) : `drum_player.py` est déplacé dans
  `src/player/drum_player.py`** (`git mv`), pour le rangement. Il ne
  contient plus alors que la classe `DrumPlayer` (~200 lignes : imports,
  `__init__`, propriétés, délégations `_qm`). Les deux importeurs de
  `src/` et les huit fichiers de tests passent à
  `from player.drum_player import DrumPlayer`.
- Préfixe `dp_` : même logique que `mew_` (MidiEditorWindow) et `mw_`
  (MainWindow), il dit à quelle classe le mixin appartient.
- Noms de classe sans préfixe, comme les `mew_*` : `PositionMixin` plutôt
  que `NavigationMixin`, pour ne pas faire doublon avec
  `ui/mew_navigation.py::NavigationMixin`.
- Imports : absolus, comme le reste de `src/` (`from pattern import …`,
  `from player.dp_recording import RecordingMixin`).
- Les constantes `*_EVENT` passent dans `PlaybackLoopMixin` :
  `DrumPlayer.GRID_EVENT` reste accessible par héritage.

**D3 — déplacer d'abord, restructurer `_run_thread` ensuite, dans des
commits séparés.**
- Les commits de déplacement (8b1-8d1) copient le code **à l'identique** :
  pas de renommage, pas de reformatage, `git diff --color-moved` doit
  montrer des blocs déplacés et rien d'autre.
- Ensuite seulement (8e1), `_run_thread` est découpé en trois méthodes du
  même mixin, une par point de l'état des lieux :
  - `_build_measure_events(lp_start, lp_end, total_steps, loop_bars, elapsed)`
    → la liste triée ;
  - `_dispatch_event(track_or_type, evt_data, velocity, t_sec)` → le
    grand `if/elif` sur le marqueur ;
  - `_on_measure_end(measure_start, measure_secs, lp_start)` → retourne
    le nouveau `measure_start`, pour garder la variable locale
    explicite.
  - L'attente active (`while … sleep`) et le `for … else` restent dans
    `_run_thread`, qui retombe à ~50 lignes.
- Raison : un déplacement pur se relit en un coup d'œil ; un découpage de
  méthode demande une vraie relecture. Les mélanger cacherait un
  éventuel changement de comportement dans un gros diff.
- C'est aussi la zone que l'export MIDI devra comprendre (ordre de rejeu,
  temps des événements).

**D4 — les patchs de test suivent le code.**
- `mock.patch("drum_player.time.perf_counter")` devient
  `mock.patch("player.dp_recording.time.perf_counter")` dans le même
  commit que le déplacement de `_compute_float_offset` (8c1), pour garder
  la suite verte à chaque commit.
- Le déplacement de `drum_player.py` (8g1) met à jour les imports des
  tests dans le même commit. Vérifier le contenu indexé avant de
  committer : un `git add -A` après un `git mv` suivi d'éditions peut
  rater des lignes.

### Portée explicitement exclue de ce chantier

- Tout changement de comportement. La suite de tests existante (1746)
  doit passer à chaque commit sans autre modification que les patchs et
  imports de D4.
- **Rassembler les quatre copies de `_bend_log`** (`drum_player.py`,
  `track_router.py`, `synth_engine.py`, `ui/midi_handler_window.py`) dans
  un module commun : **reporté à une prochaine étape**, après ce
  chantier. Ici, la copie de `drum_player.py` suit simplement
  `RecordingMixin` dans `player/dp_recording.py`.
- Déplacer de l'état hors de `DrumPlayer.__init__` (par exemple l'état
  du song vers un objet `SongState`) : ce serait un changement de
  structure de données, pas un découpage de fichier.
- `QuantizeManager`, `LoopManager`, `Metronome` : déjà séparés, non
  touchés.
- L'Import/Export MIDI lui-même. Il ne s'ajoutera probablement pas à
  `DrumPlayer` : la lecture/écriture d'un `.mid` travaille sur un
  `Pattern`, elle ira plutôt dans `src/midi/`. Ce sera décidé dans son
  propre plan.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **8a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **8b1** | Refactor — package `src/player/` (`__init__.py`), `TransportMixin` et `PositionMixin` déplacés à l'identique, `DrumPlayer` en hérite. | `drum_player.py`, `player/__init__.py`, `player/dp_transport.py`, `player/dp_position.py` |
| **8c1** | Refactor — `RecordingMixin` (avec `_bend_log`) et `EraseMixin` déplacés à l'identique ; patch de test de D4. | `drum_player.py`, `player/dp_recording.py`, `player/dp_erase.py`, `tests/test_tape.py` |
| **8d1** | Refactor — `LivePlayMixin` et `PlaybackLoopMixin` (avec les constantes `*_EVENT`) déplacés à l'identique. `drum_player.py` ne garde que `__init__`, les propriétés et les délégations. | `drum_player.py`, `player/dp_live.py`, `player/dp_playback.py` |
| **8e1** | Refactor — `_run_thread` découpé en `_build_measure_events`, `_dispatch_event`, `_on_measure_end` (D3). Comportement inchangé. | `player/dp_playback.py` |
| **8f1** | Tests — tests unitaires des trois nouvelles méthodes : liste d'événements (fenêtre de boucle, filtre `elapsed`, ordre bend avant note au même temps, Note Repeat) ; distribution vers les bons callbacks ; fin de mesure (count-in, compteur de boucle, enchaînement et bouclage de song, pause en fin de pattern). | `tests/test_playback_loop.py` (nouveau) |
| **8g1** | Refactor — `git mv src/drum_player.py src/player/drum_player.py` ; imports mis à jour (`from player.drum_player import DrumPlayer`). | `player/drum_player.py`, `ui/main_window.py`, `ui/midi_handler_window.py`, 8 fichiers de `tests/` |
| **8h1** | Doc — clôture (DESIGN.md, structure de `CLAUDE.md`/`docs/SPECS.md` si elle liste les fichiers), `grep -rn "drum_player"` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, autres docs si besoin |

Ordre choisi :
- Deux mixins par commit, par paires de blocs voisins, pour garder des
  diffs lisibles.
- Transport/position d'abord : ce sont les blocs les moins couplés au
  reste (ils n'appellent que `start_thread`/`stop_thread` et
  `_current_offset`).
- `_run_thread` en dernier parmi les mixins : c'est lui qui appelle
  presque tous les autres blocs (`_clear_offset`, `_erase_tape_event`,
  `_record_nr_hit`, `_mix_pan`, `_compute_offsets`).
- Déplacement de `drum_player.py` après tout le reste : le fichier est
  alors petit, et le commit ne contient que le `git mv` et des lignes
  d'import.
- Chaque commit de 8b1 à 8g1 laisse la suite verte : pas de paire
  implémentation/tests rouge dans ce chantier (8e1 est couvert par les
  tests existants, 8f1 ajoute des tests).

### Avancement et écarts constatés

- **8b1** (`e7a444c`) — conforme. `import math`, devenu inutile dans
  `drum_player.py`, est retiré.
- **8c1** — un seul écart au déplacement à l'identique : `_BEND_LOG_PATH`
  est calculé depuis `dirname(__file__)`. Dans `src/player/dp_recording.py`,
  il faut un `".."` de plus pour que `bend_log.txt` reste à la racine du
  dépôt. `os` et `TapeEvent`, devenus inutiles dans `drum_player.py`, sont
  retirés.
- **8d1** — conforme. `drum_player.py` tombe à 165 lignes : imports,
  `__init__`, propriétés et délégations `_qm`. `DrumPlayer` reçoit une
  docstring qui renvoie aux mixins. `time` et les `ETYPE_*`, devenus
  inutiles, sont retirés. L'import `LoopWindow`, déjà inutilisé avant le
  chantier, est laissé tel quel.
- **8e1** — un écart à D3 : l'attente de **fin de mesure** part dans
  `_on_measure_end` au lieu de rester dans `_run_thread`.
  - Le bloc `else` du `for` enchaîne trois choses : le pré-armement du
    dernier count-in, qui doit se faire *avant* l'attente ; l'attente
    elle-même ; puis la décision (count-in, compteur de boucle, song,
    pause), qui se fait *après*.
  - Garder l'attente dans `_run_thread` aurait coupé la logique du count-in
    en deux et demandé une quatrième méthode.
  - L'attente de chaque **événement** et le `for … else` restent bien dans
    `_run_thread`, qui fait maintenant 56 lignes.
  - Les corps des trois méthodes sont repris à l'identique, à l'indentation
    près : la comparaison du diff avec `-w` ne montre que les appels, les
    signatures, les docstrings et les `return`.
- **8f1** — conforme. 31 tests dans `tests/test_playback_loop.py`, qui
  appellent les trois méthodes directement, sans lancer le thread
  (1777 tests au total).
  - Contre-épreuve par mutations volontaires de `dp_playback.py` : 9
    mutations sur 10 font échouer au moins un test (tolérance de 2 ms,
    vélocité, override de durée, filtre Note Repeat, avance du song, pause
    en fin de pattern, garde `_wakeup` du count-in, attente de fin de
    mesure…).
  - La seule non détectée retire la borne basse de la fenêtre de boucle
    (`lp_start <= float_off`). Elle est sans effet : un événement avant
    `lp_start` a un `t_sec` négatif, déjà exclu par le filtre
    `t_sec > elapsed - 0.002` puisque `elapsed >= 0`. Ce n'est donc pas un
    trou de couverture. Le code n'est pas modifié, ce chantier ne change
    pas le comportement.
- **8g1** — conforme. `git mv` à 100 % de similarité (contenu inchangé).
  12 imports dans 11 fichiers, au lieu des 10 prévus : 2 dans `src/ui/` et
  9 fichiers de tests, en comptant le nouveau `test_playback_loop.py` de
  8f1. `test_tape.py` a deux imports. Index vérifié avant le commit.
  Aucun test ne lit `drum_player.py` par son chemin.

### Clôture (8h1)

**8a1-8g1 FAITS** (commits `a0fe487`..`79e83b5`, 1777 tests passed) —
**chantier Phase 7 étape 8 complet**. Aucun changement de comportement :
les 1746 tests d'avant le chantier passent sans autre modification que
les imports et le patch `perf_counter`, et 31 tests ont été ajoutés.

Résultat, `src/drum_player.py` (1148 lignes) devient le package
`src/player/` :

| Fichier | Lignes | Contenu |
|---|---|---|
| `drum_player.py` | 165 | `DrumPlayer` : état (`__init__`), propriétés, délégations `_qm` |
| `dp_transport.py` | 126 | `TransportMixin` |
| `dp_position.py` | 164 | `PositionMixin` |
| `dp_playback.py` | 290 | `PlaybackLoopMixin` : `_run_thread` (56 lignes) et ses trois étapes |
| `dp_live.py` | 55 | `LivePlayMixin` |
| `dp_recording.py` | 278 | `RecordingMixin` et `_bend_log` |
| `dp_erase.py` | 126 | `EraseMixin` |

Écarts au plan, détaillés plus haut :
- 8c1 : chemin `_BEND_LOG_PATH` ;
- 8e1 : attente de fin de mesure dans `_on_measure_end` ;
- 8g1 : 12 imports au lieu de 10.

`grep -rn "drum_player"` final : hors cette section et les sections
historiques de ce fichier, il ne reste que les imports
`from player.drum_player import DrumPlayer` (2 dans `src/ui/`, 10 dans
`tests/`), le nom d'un test (`test_drum_player_has_no_mod_tape_remnants`)
et l'arborescence de `docs/SPECS.md`, qui liste maintenant `player/`.

Restent hors périmètre :
- rassembler les quatre copies de `_bend_log` (reporté à une prochaine
  étape) ;
- l'import inutilisé `LoopWindow` de `drum_player.py` ;
- la borne basse redondante de la fenêtre de boucle dans
  `_build_measure_events` (voir 8f1) ;
- le reste de l'arborescence de `docs/SPECS.md`, en retard sur la Phase 7
  étape 3 : `midi_editor.py` et `midi_manager.py` y sont encore listés
  dans `src/` au lieu de `src/midi/`, et `ui/midi_handler.py` sous son
  ancien nom ;
- l'arborescence de `CLAUDE.md`, qui décrit la structure prévue au départ
  du projet et non les fichiers actuels.

Suite : l'Import/Export MIDI, en commençant par l'export.

---

## Phase 7 étape 9a1 — Un seul `_bend_log` pour tout le projet

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 8 : `9a1`, `9b1`, `9c1`… ; un
commit imprévu inséré après `9b1` s'appelle `9b2`, `9b3`, etc.

### Origine du besoin

La Phase 7 étape 8a1 a relevé quatre copies de `_bend_log` et a reporté
leur regroupement à une étape suivante. C'est cette étape, demandée par
l'utilisateur le 2026-10-18.

### État des lieux constaté en code (2026-10-18, 1777 tests verts)

**Quatre copies du même helper.** Chacune a un drapeau, un chemin et une
fonction :

```python
_BEND_LOG = os.environ.get("GROOVY_BEND_LOG") == "1"
_BEND_LOG_PATH = os.path.join(os.path.dirname(__file__), <..>, "bend_log.txt")

def _bend_log(msg):
    if not _BEND_LOG:
        return
    ts = time.strftime("%H:%M:%S")
    with open(_BEND_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
```

| Fichier | Chemin vers la racine | Alias de `time` | Appels | Messages |
|---|---|---|---|---|
| `player/dp_recording.py` | `"..", ".."` | `time` | 2 | `REC note_on`, `REC note_off` |
| `track_router.py` | `".."` | `_time` | 2 | `PLAY`, `BEND_AUTO` |
| `synth_engine.py` | `".."` | `_time` | 2 | `ENGINE_PLAY` (deux variantes) |
| `ui/midi_handler_window.py` | `"..", ".."` | `_time` | 2 | `BEND_SET`, `REC_READ` |

- Les quatre copies écrivent dans le même fichier, `bend_log.txt` à la
  racine du dépôt. Seule la profondeur du fichier change le nombre de
  `".."`. C'est cette différence qui a demandé une correction en Phase 7
  étape 8c1, quand `dp_recording.py` a changé de dossier.
- Le drapeau est lu une fois, à l'import de chaque module.
- Imports qui ne servent qu'au log :
  - `track_router.py` : `os` et `_time` (`import os, time as _time`) ;
  - `ui/midi_handler_window.py` : `os` et `_time` ;
  - `synth_engine.py` : `_time` seulement, `os` sert ailleurs ;
  - `dp_recording.py` : `os` seulement, `time` sert ailleurs
    (`perf_counter`).
- Aucun test ne couvre le log, et aucun ne patche `_bend_log` ou
  `_BEND_LOG`.
- `bend_log.txt` n'est pas dans `.gitignore`. Il n'existe pas en ce moment
  dans le dépôt.
- Le projet n'utilise pas le module `logging` de Python.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — un module `src/bend_log.py`, avec une fonction publique
`bend_log(msg)`.**
- Le module contient le drapeau `_ENABLED`, le chemin `_LOG_PATH` et
  `bend_log(msg)`, avec exactement le comportement actuel : même variable
  d'environnement, même fichier, même format `[HH:MM:SS] message`.
- Placé à la racine de `src/`, à côté de `app_config.py` : il n'appartient
  à aucun sous-package. Le chemin vers la racine du dépôt n'est donc
  écrit qu'une fois, `".."`.
- Les quatre fichiers font `from bend_log import bend_log`, et leurs 8
  appels passent de `_bend_log(...)` à `bend_log(...)`. Leurs copies et
  les imports qui ne servaient qu'au log sont retirés.
- Les messages ne changent pas.

Alternatives écartées :
- **Module `logging` de Python** (un logger `"groovy.bend"` avec un
  `FileHandler`). Ce serait plus standard, mais il faudrait configurer les
  handlers au démarrage, et le format changerait. Le besoin, un fichier de
  traces activé à la demande pour déboguer le pitch bend, ne le justifie
  pas.
- **Un log générique** `debug_log(channel, msg)`, prévu pour d'autres
  traces. Aucun autre besoin n'existe aujourd'hui. Il sera facile de
  généraliser `bend_log.py` le jour où il y en aura un.
- **Garder le nom `_bend_log` aux appels** (`from bend_log import
  bend_log as _bend_log`), pour un diff plus court. Un alias qui cache une
  fonction publique sous un nom privé rend le code moins clair, pour un
  gain de 8 lignes.

**D2 — lecture du drapeau inchangée, à l'import du module.**
- Comme aujourd'hui, `GROOVY_BEND_LOG=1` doit être posée avant de lancer
  l'application.
- Les tests changent `bend_log._ENABLED` et `bend_log._LOG_PATH` par
  `monkeypatch`, sans toucher à l'environnement.

**D3 — `bend_log.txt` ajouté à `.gitignore`.**
- C'est un fichier de traces local. Il ne doit pas être committé par
  erreur après une session de débogage.

### Portée explicitement exclue de ce chantier

- Le contenu et le nombre des messages de log.
- Les autres traces de débogage du projet (`print` éventuels) et toute
  adoption du module `logging`.
- Le reste de l'arborescence de `docs/SPECS.md`, en retard sur la Phase 7
  étape 3 (voir la clôture de la Phase 7 étape 8). Seule la ligne de
  `bend_log.py` y est ajoutée.

### Découpage en commits

| Étape | Contenu | Fichiers |
|---|---|---|
| **9a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **9b1** | Implémentation — `src/bend_log.py` (D1, D2) ; les quatre copies sont remplacées par l'import, 8 appels renommés, imports devenus inutiles retirés ; `bend_log.txt` dans `.gitignore` (D3). | `bend_log.py`, `player/dp_recording.py`, `track_router.py`, `synth_engine.py`, `ui/midi_handler_window.py`, `.gitignore` |
| **9c1** | Tests — drapeau éteint : aucun fichier créé ; drapeau allumé : une ligne `[HH:MM:SS] message` ajoutée par appel, à la suite des précédentes ; chemin par défaut à la racine du dépôt ; les quatre modules appellent la même fonction et n'ont plus de copie (`_BEND_LOG` absent). | `tests/test_bend_log.py` (nouveau) |
| **9d1** | Doc — clôture (DESIGN.md, ligne `bend_log.py` dans l'arborescence de `docs/SPECS.md`), `grep -rn "_bend_log\|_BEND_LOG"` sur tout le dépôt, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 9b1 laisse la suite verte, puisqu'aucun test ne touche le log : pas de
  paire implémentation/tests rouge dans ce chantier.
- Avant de committer 9b1, une vérification à la main : lancer un
  enregistrement avec `GROOVY_BEND_LOG=1` est impossible ici, faute de
  clavier MIDI. Elle est remplacée par un appel direct de chaque module
  avec le drapeau allumé, qui doit écrire dans le même fichier.

### Avancement et écarts constatés

- **9b1** — conforme. Avec `GROOVY_BEND_LOG=1`, les quatre modules
  pointent sur la même fonction et écrivent une ligne chacun dans
  `bend_log.txt` à la racine du dépôt. `git check-ignore` confirme que
  ce fichier est ignoré.
- **9c1** — conforme, avec un test de plus que prévu (texte non ASCII,
  les messages `ENGINE_PLAY` contiennent « → »). 9 tests dans
  `tests/test_bend_log.py`, 1786 au total.
  - Le fichier de log des tests va dans `tmp_path`, grâce au `monkeypatch`
    de `_ENABLED` et `_LOG_PATH` : les tests n'écrivent jamais à la racine
    du dépôt.
  - Contre-épreuve sur le code d'avant 9b1 : les tests ne s'importent pas,
    `bend_log.py` n'existant pas encore. C'est peu parlant, d'où une
    contre-épreuve par mutations volontaires de `bend_log.py`. Les 5 sont
    détectées : écriture en mode `"w"`, drapeau ignoré, horodatage retiré,
    chemin hors de la racine, encodage ASCII.

### Clôture (9d1)

**9a1-9c1 FAITS** (commits `943f351`..`abe04a9`, 1786 tests passed) —
**chantier Phase 7 étape 9 complet**.

- **D1** — `src/bend_log.py` remplace les quatre copies de `_bend_log` :
  un seul drapeau, un seul chemin, une seule fonction `bend_log(msg)`,
  utilisée par `player/dp_recording.py`, `track_router.py`,
  `synth_engine.py` et `ui/midi_handler_window.py`. Le comportement, le
  fichier et le format sont inchangés. Le code compte 10 lignes de moins.
- **D2** — le drapeau est toujours lu à l'import. Les tests le changent par
  `monkeypatch`.
- **D3** — `bend_log.txt` est dans `.gitignore`.

Le chemin vers la racine n'est plus écrit qu'une fois. Déplacer un
fichier qui utilise le log ne demande donc plus de le corriger, comme
il avait fallu le faire en Phase 7 étape 8c1.

`grep -rn "_bend_log\|_BEND_LOG"` final : hors des sections historiques
de ce fichier, ces noms n'apparaissent plus que dans les docstrings de
`bend_log.py` et de `test_bend_log.py`, et dans le test qui vérifie leur
absence (`test_no_local_copy_left`). `docs/SPECS.md` liste
`bend_log.py` dans son arborescence.

Rien n'est laissé hors périmètre en plus de ce que le plan excluait.

Suite : l'Import/Export MIDI, en commençant par l'export.

---

## Phase 7 étape 10a1 — Export MIDI (.mid) du pattern courant

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 9 : `10a1`, `10b1`, `10c1`… ; un
commit imprévu inséré après `10b1` s'appelle `10b2`, `10b3`, etc.

### Origine du besoin

C'est le but final annoncé dès la Phase 7 étape 1b (§ « Conformité avec le
but final ») : l'import et l'export de fichiers MIDI standard (SMF). Les
préalables sont faits :
- toutes les données d'un pattern vivent dans `_tape`, avec `time` flottant
  et `channel` (Phase 7 étapes 1, 4, 5, 6) ;
- le bend est un état de canal, porté par les seuls `ETYPE_BEND`, comme en
  MIDI (Phase 7 étape 7).

L'utilisateur a demandé le 2026-10-18 d'attaquer l'export en premier.
L'import fera l'objet d'une partie séparée. En validant le plan, il a
ajouté :
- un `requirements.txt` ;
- un canal réglable par piste ;
- des patterns à 16 pistes par défaut.

### État des lieux constaté en code (2026-10-18, 1786 tests verts)

**Les données.** `Pattern._tape[t]` est une liste plate de `TapeEvent` par
piste (`pattern.py:17`) :

| etype | payload | `dur` | Rejeu (`dp_playback.py`, `track_router.py`) |
|---|---|---|---|
| `GRID` | `pad`, `vel` (0..127, 100 par défaut) | ms, 0 = durée de la voix du pad | slot SYNTH : note `_kb_notes_play[pad]` ; sinon `drum_sounds[pad]` |
| `KIT` | `note`, `vel` | toujours 0 (one-shot, `record_kit_note`) | `snd.play_note(note)`, quel que soit le slot |
| `PATCH` | `note`, `vel` | ms, 0 = 500 ms | muet si le slot de la piste n'est pas SYNTH |
| `CC` | `cc_num`, `value` | 0 | 64/120/121/123 globaux ; 1, 7, 10 sur la piste |
| `PGM` | `program` | 0 | pont provisoire `assign_slot(track, program % 16)` |
| `BEND` | `value` (-8192..+8191) | 0 | moteur du slot SYNTH, plage ±2 demi-tons (`synth_engine.py:108`, défaut GM) |

- `channel` est le canal d'origine, capturé en live (`dp_recording.py`).
  Il vaut 0 pour tout ce qui vient de la grille ou du Numpad.
- La note jouée pour un `GRID` dépend de l'état hors `_tape` :
  - sur une piste SYNTH, `scale_midi_notes(pattern._kb_scale,
    pattern._kb_root_midi, 16)[pad]` (`track_router.py:91`, figé par
    pattern via `set_playback_kb`) ;
  - sur une piste kit, `drum_sounds[pad]`, c'est-à-dire la note
    `snd.kit_base + snd.kit_offset + pad` (`sound_manager.py:164`), et
    `kit_base` vient du kit chargé (36 par défaut).
- La durée par défaut d'un `GRID` vient du `VoiceManager` du player
  (`voice_manager.get_duration_ms(pad)`). Le nom d'une piste (F2) est
  stocké au même endroit, `voice_manager.get_name(track)`
  (`mw_tracks.py:78`).
- L'état de mixage de chaque piste vit dans `TrackRouter` :
  `_track_slots`, `_track_mutes`, `_track_solos`, `_track_volumes`,
  `_track_pans`. `Pattern` n'en garde une copie qu'au rangement dans le
  store (`mw_patterns.py`), et c'est cette copie qui est sérialisée.

**Nombre de pistes : 8, en dur à plusieurs endroits.**
- `Pattern._num_tracks = 8` (`pattern.py:130`), alors que
  `Pattern.MAX_TRACKS = 16`.
- `TrackRouter.NUM_TRACKS = 8` (`track_router.py:36`) dimensionne ses
  listes de pistes.
- La liste des pistes de la fenêtre principale : `range(8)`
  (`main_window.py:282`).
- `docs/SPECS.md` annonce « 8 pistes par pattern ».
- `from_dict` relit `num_tracks` (8 pour tout `.gvp` existant), et les
  listes `track_*` telles quelles.
- La plupart des autres lectures passent déjà par `pattern._num_tracks`.

**Ordre de rejeu à temps égal.** `_build_measure_events` trie des tuples
`(t_sec, marqueur, données, vélocité)`. Les marqueurs donnent l'ordre
`PGM (-8)`, `CC (-7)`, `GRID (-6)`, `BEND (-4)`, `PATCH (-3)`, `KIT (-2)` :
le bend passe avant les notes PATCH. Point resté ouvert en Phase 7
étape 7 : deux `BEND` au même temps sur une piste.
- Le tri compare ensuite `données = (t_idx, value)` : c'est la valeur la
  plus haute qui est appliquée en dernier.
- `Pattern._bend_state_at`, lui, retient le dernier dans l'ordre de `_tape`.
- Les deux peuvent donc différer.

**Le temps : une incohérence du lecteur.** Le pas réel est toujours une
double croche, quel que soit `_num_steps` :
- `step_duration = 60.0 / bpm / 4` est écrit à quatre endroits :
  `drum_player.py:40`, `dp_transport.py:125` (`set_bpm`), et
  `dp_playback.py:260` et `:275` (enchaînement du song) ;
- tout le reste place un temps tous les `_num_steps // _num_beats` pas :
  le métronome (`metronome.py:51`), la quantisation, les dialogues
  temporels, `dp_position.py` et l'éditeur MIDI.

Conséquence : un pattern de 32 pas en 4/4 dure deux fois plus longtemps
que ne l'annonce son BPM, et le métronome y bat à BPM/2 (BPM/4 pour 64 pas,
BPM/8 pour 128 pas).
- Le Note Repeat compense sans le savoir : `interval = 16.0 / denom` pas
  (`dp_playback.py:122`) suppose 16 pas par mesure.
- `_num_beats` vaut toujours 4. Il n'est ni sérialisé, ni copié par
  `copy_from`, ni modifiable dans l'UI.
- `_denumerator` n'est lu nulle part.
- `step_duration` n'est recalculé que par `set_bpm`. L'enchaînement du song
  ne le recalcule que si le BPM change (`if next_pat._bpm != self.bpm`).
- Les patterns de 16 pas, le cas par défaut, ne sont pas touchés : pour eux,
  la formule actuelle est juste.

**Les outils.** `mido` 1.3.3 est installé avec `python-rtmidi` 1.5.8, mais
le projet ne l'importe nulle part (`midi_manager.py` utilise `rtmidi`
directement).
- Il n'existe ni `requirements.txt` ni module d'écriture SMF.
- Dépendances tierces réellement importées par `src/` et `tools/` :
  `wx`, `pygame`, `sounddevice`, `numpy`, `soundfile`, `pyrubberband`,
  `rtmidi`.
- La table des dépendances est dans `docs/SPECS.md`.

**Raccourci.** Ctrl+Shift+E est pris (« Choisir la ligne + quant et générer
le motif », `key_handler_ctrl.py:143`). Alt+Shift+E est libre dans la
fenêtre principale, l'éditeur MIDI et la fenêtre Songs.

### Décisions validées (utilisateur, 2026-10-18)

**D1 — corriger d'abord le lecteur : un pas dure
`60 · num_beats / (bpm · num_steps)` secondes.**
- Un temps (une noire, `_denumerator` restant ignoré) dure exactement
  `60 / bpm`, quelle que soit la résolution. Le lecteur est alors d'accord
  avec le métronome, la quantisation et l'affichage.
- Pour 16 pas et 4 temps, la formule redonne `60 / bpm / 4` : les patterns
  par défaut ne changent pas.
- Une seule méthode `DrumPlayer._update_step_duration()` calcule la valeur
  à partir de `self.bpm` et du pattern live. Elle remplace les quatre
  copies de la formule, et elle est appelée :
  - par `set_bpm` ;
  - à chaque enchaînement de pattern du song, que le BPM change ou non ;
  - après un redimensionnement du pattern live
    (`mw_patterns._resize_live_pattern`).
- Le Note Repeat passe de `16.0 / denom` à `num_steps / denom` pas : une
  division `1/denom` reste une fraction de la mesure.
- Effet accepté : les patterns existants de 32, 64 ou 128 pas jouent 2, 4
  ou 8 fois plus vite qu'avant, désormais au tempo affiché. Les durées
  `dur`, en ms, ne bougent pas.

Alternatives écartées :
- **Garder le lecteur et exporter « son et mesures fidèles »** (tempo
  `4·bpm·num_beats/num_steps`). Le .mid sonnerait comme l'appli, mais le
  tempo écrit différerait du BPM affiché, et l'incohérence resterait.
- **Exporter tempo = BPM sans corriger le lecteur.** Le .mid sonnerait plus
  vite que l'appli dès 32 pas.

**D2 — 16 pistes par pattern par défaut.**
- On passe aux 16 canaux MIDI : `Pattern._num_tracks = 16`,
  `TrackRouter.NUM_TRACKS = 16`, et la liste des pistes de la fenêtre
  principale suit `_num_tracks`, sans `range(8)` en dur.
- **Migration** : `from_dict` porte tout pattern de moins de 16 pistes à 16.
  - `_tape` est complété par des pistes vides ;
  - chaque liste `track_*` est complétée par sa valeur par défaut (slot 0,
    pas de mute ni de solo, volume 100, pan 0, canal par défaut, D5).
  - Un `.gvp` existant s'ouvre donc avec 16 pistes, les 8 premières
    inchangées.
- Les autres lectures passent déjà par `pattern._num_tracks` : elles
  suivent sans changement.

Alternative écartée : garder 8 pistes pour les anciens patterns et 16 pour
les nouveaux. Le nombre de pistes varierait d'un pattern à l'autre, alors
que `TrackRouter` a des listes de taille fixe.

**D3 — portée : le pattern courant.**
- On exporte le pattern live (`player._pattern`), avec l'état courant de
  `TrackRouter` et du `VoiceManager`, même s'il n'est pas encore rangé dans
  le store.
- Toute la longueur est exportée, de la mesure 1 à `_num_bars`, sans tenir
  compte des loop points, de `_loop_count` ni de `_start_bar`.
- Le song viendra dans une étape ultérieure, avec le même moteur : on
  enchaînera les patterns et on posera un meta tempo à chaque changement de
  BPM.

Alternatives écartées : pattern et song dès le départ, ou projet entier.
Le song et le projet posent d'autres questions (tempo variable,
organisation des pistes), qu'il vaut mieux traiter une fois le moteur
éprouvé.

**D4 — SMF de type 1, PPQ = 480.**
- **Piste 0 (conductor)** à tick 0 :
  - `track_name` = nom du pattern, ou `Pattern_NN` s'il n'en a pas ;
  - `set_tempo` = `bpm2tempo(bpm)`, exact grâce à D1 ;
  - `time_signature` = `num_beats/4`.
- **Une piste SMF par piste Groovebox non vide**, dans l'ordre, avec
  `track_name` = nom de la piste (F2), ou `Track NN` (numéro d'origine,
  1-based). Les pistes vides sont omises.
- Chaque piste se termine par `end_of_track` au plus tard de deux instants :
  la fin du pattern (`num_bars · num_steps` pas) ou le dernier note-off.
  Ainsi la longueur du pattern est conservée même si sa dernière mesure
  est vide.
- Avec 480 ticks par noire, l'écart reste sous 0,3 ms à 120 BPM pour les
  `time` flottants de la capture live.

Alternatives écartées :
- **Type 0** : une seule piste, et l'import ne retrouverait pas le découpage
  en pistes.
- **PPQ 96 ou 960** : 96 est trop grossier pour le timing libre, 960
  n'apporte rien d'audible.

**D5 — canal MIDI de chaque piste : un canal stocké par piste, piste N →
canal N par défaut, réglable dans les propriétés de la piste.** Cette
décision a été simplifiée par l'utilisateur le 2026-10-20 (Phase 7 étape
10a2). La version de 10a1 est rappelée dans les alternatives écartées.

Chaque piste porte un canal, une valeur stockée et non recalculée, et
l'export y écrit tous ses événements, quel que soit leur etype.

- **Défaut** : la piste N reçoit le canal N, pour N de 1 à 16. La piste 10
  est donc sur le canal 10, celui de la batterie GM. Toute piste au-delà de
  la 16e reçoit le canal 16. Ce cas n'existe pas encore, puisque
  `MAX_TRACKS = 16`, mais la règle est posée pour l'avenir.
- **Assigner un slot kit à une piste** la met sur le canal 10. C'est le cas
  par le choix du slot de la fenêtre principale (`_assign_track_slot`) et
  par `TrackPropertiesDialog`.
- **Assigner un slot qui n'est pas un kit** (synthé, vide ou autre) à une
  piste dont le canal est 10 la ramène à son canal par défaut. La piste 10
  reste donc sur le canal 10. Un autre canal choisi à la main n'est pas
  touché.
  - Limite assumée : aucun drapeau ne retient si le canal 10 a été choisi
    à la main ou posé par un kit. Un 10 choisi à la main sur une piste
    autre que la 10 revient donc lui aussi au défaut dès qu'on lui assigne
    un synthé.
- **Ce qui ne change pas le canal** :
  - le pont provisoire Program Change → `assign_slot` (live et rejeu) ;
  - la restauration des slots au chargement d'un projet ;
  - le chargement d'un kit dans un slot.
  
  Pour cela, la règle est appliquée dans les deux actions utilisateur
  ci-dessus, et non dans `TrackRouter.assign_slot`.
- **Choix manuel** : `TrackPropertiesDialog` gagne une `ListBox` « Canal »
  de 16 entrées, `Canal 1` à `Canal 16`.
  - Elle se place après Slots dans l'ordre Tab.
  - Elle a le même aperçu en temps réel et le même Annuler que les autres
    champs.
  - L'action entre dans l'Undo comme les autres propriétés de piste.
  - Changer de slot dans le dialogue applique la règle du kit et met à jour
    la sélection de la liste Canal. L'utilisateur peut ensuite la changer.
  - Aucune vérification de collision : deux pistes sur un même canal le
    partagent, c'est le choix de l'utilisateur.
- **Données** : `_track_channels`, une liste d'entiers 0..15, avec
  `min(t, 15)` pour la piste `t` (0-based) par défaut.
  - Comme les autres réglages de piste, elle vit dans `TrackRouter`, est
    copiée dans `Pattern` au rangement, et est sérialisée dans le `.gvp`
    sous `track_channels`.
  - Clé absente, cas d'un ancien `.gvp`, ou liste trop courte (migration
    D2) : on complète avec le défaut par index.
  - La règle du kit n'est pas rejouée sur les slots existants : un ancien
    projet s'ouvre comme un nouveau pattern, canal N pour la piste N.
  - Un nouveau pattern a aussi le canal N sur la piste N, bien que ses 16
    pistes pointent par défaut sur le slot 1, qui est un kit (TR-707,
    `main_window.py:112`). Seule une assignation explicite déclenche la
    règle.
- **Portée** : le canal de piste ne sert qu'à l'export pour l'instant. Le
  rejeu et la capture ne changent pas, et `ev.channel` reste le canal
  d'origine capturé. Ce réglage prépare l'adressage par canal du mode Rack
  GM.
- `ev.channel` n'est pas écrit dans le fichier : c'est une perte assumée.
- Un événement `KIT` est écrit sur le canal de sa piste comme tout le
  reste, même si la piste n'est pas sur le canal 10. Il n'y a pas
  d'exception par etype.

Exemple : piste 1 sur un kit (assigné), pistes 2 et 4 sur un même synthé,
piste 3 sur un autre synthé. On obtient piste 1 → 10, piste 2 → 2,
piste 3 → 3, piste 4 → 4. Pour que les pistes 2 et 4 partagent un canal,
on règle la piste 4 sur le canal 2 dans ses propriétés.

Alternatives écartées :
- **Canal automatique calculé à l'export (version 10a1)**. Un canal par slot
  SYNTH distinct, partagé par les pistes du même synthé, kit sur 10, avec
  une surcharge manuelle `None`/0..15. Écartée le 2026-10-20 par
  l'utilisateur, au profit d'une règle plus simple et visible : le canal
  est une valeur de la piste, que l'utilisateur voit et règle, au lieu d'un
  résultat recalculé selon les autres pistes.
- **Le canal d'origine `ev.channel`**, fidèle et utile à l'aller-retour.
  Mais tout ce qui vient de la grille est sur le canal 1.
- **Canal = numéro de slot du Rack** : il s'appuie sur le pont
  `assign_slot`, qui est provisoire.

**D6 — notes, vélocités, durées.**
- **Note d'un `GRID`** : sur une piste SYNTH,
  `scale_midi_notes(pattern._kb_scale, pattern._kb_root_midi, 16)[pad]` ;
  sur une piste kit, `kit_note_base + pad`, avec
  `kit_note_base = snd.kit_base + snd.kit_offset`, l'état courant, comme
  au rejeu.
- **`KIT` et `PATCH`** : la note du payload.
- **Vélocité** : celle du payload, bornée à 1..127, une vélocité 0 valant
  note-off en MIDI.
- **Durées** :
  - `GRID` : `dur` s'il est positif, sinon la durée de la voix du pad
    (`voice_manager`) ;
  - `PATCH` : `dur` s'il est positif, sinon 500 ms, comme au rejeu ;
  - `KIT` : un pas (one-shot), puisque `dur` y vaut toujours 0. Un lecteur
    GM ignore de toute façon le note-off sur le canal 10.
- **Conversions** :
  - temps : `tick = round(time · PPQ · num_beats / num_steps)` ;
  - durée : `ticks = round(dur_ms / 1000 · bpm / 60 · PPQ)`, au minimum
    1 tick ;
  - c'est cohérent avec D1 : un temps dure `60 / bpm` secondes.
- **Notes qui se chevauchent** : une même note sur un même canal, rejouée
  avant son note-off, recevrait ce note-off au milieu de la note suivante.
  Le note-off de la première est donc avancé juste avant le note-on
  suivant, comme le ferait un clavier. Cette règle vaut à l'intérieur d'une
  piste SMF. Entre pistes qui partagent un canal (D5), le cas est laissé au
  lecteur.

**D7 — ordre d'écriture à tick égal.**
- L'ordre est : note-off, `PGM`, `CC`, `BEND`, note-on. C'est celui du
  rejeu (PGM, CC, bend, notes), avec les note-off d'abord, pour qu'une note
  qui finit libère la place avant celle qui commence.
- À catégorie égale, le tri est stable sur l'ordre de `_tape`. Deux `BEND`
  au même temps : le dernier dans `_tape` gagne, comme dans
  `_bend_state_at` (donc l'éditeur et le chase du bend). L'écart avec le
  tri du rejeu (valeur la plus haute en dernier) est noté hors périmètre.

**D8 — `mido` pour écrire le fichier, et un `requirements.txt`.**
- `mido` est déjà installé et servira aussi à l'import. Le code à écrire et
  à tester se limite à la traduction `_tape` → messages, sans codec SMF
  maison.
- **`requirements.txt`** à la racine du dépôt, avec les dépendances
  tierces réellement importées. On y met un plancher de version, celui
  installé le 2026-10-18 :
  ```
  wxPython>=4.2.3
  pygame>=2.6.1
  sounddevice>=0.5.5
  numpy>=2.4.3
  soundfile>=0.13.1
  pyrubberband>=0.4.0
  python-rtmidi>=1.5.8
  mido>=1.3.3
  ```
  - `pytest` sert seulement aux tests. Il est indiqué en commentaire dans
    le fichier, avec la commande d'installation Debian
    (`pip3 install ... --break-system-packages`), plutôt que d'être exigé.
  - `pedalboard`, marqué « futur » dans `docs/SPECS.md`, n'y est pas.
- `mido` est ajouté à la table des dépendances de `docs/SPECS.md`.

Alternative écartée : écrire le SMF à la main (MThd/MTrk, delta-times en
VLQ). Aucune dépendance, mais il y aurait plus de code et de tests, et un
parseur à écrire aussi pour l'import.

**D9 — un module `src/midi/midi_export.py`, sans wx ni player.**
- `build_pattern_midi(pattern, track_channels, track_is_synth,
  track_names, kit_note_base, voice_durations) -> mido.MidiFile` contient
  toute la logique de D4, D6 et D7.
  - `track_channels` est la liste stockée de `TrackRouter` (D5).
  - Les états hors `Pattern` lui sont passés en paramètres : type de slot
    de chaque piste, noms des pistes, `kit_base + kit_offset`, durées des
    voix.
- `export_pattern(path, ...)` appelle `build_pattern_midi`, puis
  `MidiFile.save(path)`.
- Lecture de `_tape` sous `pattern._lock`, sur une copie, comme
  `_build_measure_events`.
- La fonction se teste sans wx, en relisant le fichier avec `mido`.

**D10 — UI : Alt+Shift+E.**
- Dans la fenêtre principale et dans l'éditeur MIDI (même pattern live),
  Alt+Shift+E ouvre un `wx.FileDialog` d'enregistrement :
  - filtre `*.mid` ;
  - nom proposé : le libellé du pattern, nettoyé, plus `.mid` ;
  - dossier proposé : `AppConfig.exports_dir`, nouvelle clé `exports_dir`,
    qui vaut par défaut le dossier `EXPORTS` voisin de `projects_dir` et
    est créé au besoin ;
  - `wx.FD_OVERWRITE_PROMPT`.
- Le résultat s'affiche dans la barre de statut : `Pattern NN exporté :
  <fichier>`, ou le message d'erreur. Orca l'annonce.
- La fenêtre Songs n'a pas d'export dans ce chantier : il viendra avec le
  song (D3).
- `docs/shortcuts.md` est mis à jour.

### Portée explicitement exclue de ce chantier

- L'export d'un song ou du projet entier, et le tempo variable (D3).
- L'import MIDI.
- L'effet du canal de piste sur le rejeu ou la capture live (D5). Il ne
  sert qu'à l'export en attendant le mode Rack GM.
- Le volume et le pan des pistes (CC7/CC10 initiaux) : plusieurs pistes
  peuvent partager un canal (D5), et leurs réglages entreraient en
  conflit. Mute et solo sont ignorés : toutes les pistes non vides sont
  exportées.
- Le canal d'origine `ev.channel`, perdu à l'export (D5). L'aller-retour
  export/import sans perte sera à revoir avec l'import.
- La plage de bend (RPN 0) : elle vaut ±2 demi-tons, le défaut GM, donc
  rien à écrire tant qu'elle n'est pas réglable.
- `_denumerator` et un `_num_beats` réglable (D1 garde la noire comme
  temps).
- L'écart du rejeu sur deux `BEND` au même temps (D7) : c'est un correctif
  séparé de `_build_measure_events`, s'il est voulu.
- L'export depuis la fenêtre Songs (D10).
- Le passage de 16 à 128 pads (chantier futur séparé).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **10a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **10a2** | Doc — D5 simplifiée : piste N → canal N, kit assigné → canal 10, réglage manuel. | `docs/DESIGN.md` |
| **10b1** | Implémentation — `_update_step_duration()` (D1) remplace les quatre formules ; appels dans `set_bpm`, l'enchaînement du song (sans condition) et `_resize_live_pattern` ; Note Repeat en `num_steps / denom`. | `player/drum_player.py`, `player/dp_transport.py`, `player/dp_playback.py`, `ui/mw_patterns.py` |
| **10c1** | Tests — durée du pas pour 16/32/64/128 pas ; 16 pas inchangé ; recalcul à l'enchaînement du song à BPM égal mais à `num_steps` différent ; recalcul au redimensionnement ; métronome à un clic par `60/bpm` ; intervalle du Note Repeat. Mise à jour des tests existants qui supposaient `60/bpm/4` avec un `num_steps` autre que 16, s'il y en a. | `tests/test_transport.py`, `tests/test_playback_loop.py`, … |
| **10d1** | Implémentation — 16 pistes par défaut (D2) : `Pattern`, `TrackRouter.NUM_TRACKS`, liste des pistes de la fenêtre principale, migration dans `from_dict`. | `pattern.py`, `track_router.py`, `ui/main_window.py`, `docs/SPECS.md` |
| **10e1** | Tests — nouveau pattern à 16 pistes ; ancien `.gvp` à 8 pistes porté à 16, avec ses 8 premières pistes et ses `track_*` inchangés ; navigation et sélection jusqu'à la piste 16 ; mise à jour des tests qui supposaient 8 pistes. | `tests/test_pattern.py`, `tests/test_pattern_serialization.py`, `tests/test_track_router.py`, … |
| **10f1** | Implémentation — canal de piste (D5) : `_track_channels` dans `TrackRouter` et `Pattern` (défaut par index, rangement, chargement, sérialisation `track_channels`, complétion des listes courtes) ; règle du kit (canal 10, retour au défaut) dans `_assign_track_slot` et le dialogue ; `ListBox` Canal dans `TrackPropertiesDialog`, aperçu, Annuler et Undo. | `track_router.py`, `pattern.py`, `ui/dialogs_properties.py`, `ui/mw_tracks.py`, `ui/mw_patterns.py` |
| **10g1** | Tests — défaut piste N → canal N ; assigner un kit → 10 ; puis un synthé → retour au défaut (piste 10 reste sur 10, canal manuel autre que 10 conservé) ; Program Change et chargement de projet sans effet sur le canal ; sérialisation (clé absente ou liste courte = défaut) ; dialogue : choix, règle du kit au changement de slot, Annuler, Undo. | `tests/test_track_channels.py` (nouveau), `tests/test_track_properties_dialog.py`, `tests/test_pattern_serialization.py` |
| **10h1** | Implémentation — `src/midi/midi_export.py` (D4, D6, D7, D9) ; `requirements.txt` (D8). | `midi/midi_export.py` (nouveau), `requirements.txt` (nouveau), `docs/SPECS.md` (dépendance `mido`) |
| **10i1** | Tests — relecture par `mido` : en-tête type 1 et PPQ ; conductor (nom, tempo, signature) ; une piste par piste non vide, avec son nom ; chaque événement sur le canal de sa piste (D5), `KIT` compris ; notes GRID synth/kit, KIT, PATCH ; vélocités bornées ; durées par défaut ; conversions de temps à 16 et 32 pas ; chevauchement ; ordre à tick égal et deux BEND au même temps ; CC/PGM/BEND ; `end_of_track` à la fin du pattern ; pattern vide. | `tests/test_midi_export.py` (nouveau) |
| **10j1** | Implémentation — Alt+Shift+E dans la fenêtre principale et l'éditeur MIDI ; `FileDialog` ; `AppConfig.exports_dir` ; statut (D10). | `ui/key_handler_alt.py`, `ui/mew_keymap.py`, `ui/mw_project.py`, `app_config.py`, `docs/shortcuts.md` |
| **10k1** | Tests — `exports_dir` (défaut, valeur relative, valeur absolue) ; le handler appelle l'export avec les bons paramètres (FileDialog simulé) ; Annuler n'écrit rien ; erreur d'écriture affichée. | `tests/test_app_config.py`, `tests/test_midi_export_ui.py` (nouveau) |
| **10l1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` : arborescence, 16 pistes, canal de piste, export MIDI), `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 10b1 et 10d1 peuvent casser des tests existants, qui figent `60/bpm/4`
  sur plus de 16 pas, ou 8 pistes. Si `pytest` est rouge à l'un de ces
  commits, le titre le dira, et le commit de tests suivant le réparera.
- Avant de committer 10b1 : une écoute à la main d'un pattern de 32 pas,
  dont le métronome doit battre au BPM affiché.
- Avant de committer 10d1 : ouvrir un `.gvp` existant et vérifier que les
  8 premières pistes jouent comme avant.
- Avant de committer 10h1 : un fichier exporté est ouvert dans un lecteur
  externe (`timidity` ou un DAW, s'il y en a un), pour vérifier qu'il se
  lit, le tempo, et la batterie sur le canal 10.

### Avancement et écarts constatés

- **10b1** — conforme à D1, avec deux appels de plus que prévu.
  `_num_steps` du pattern live change aussi à deux autres endroits :
  - l'action « Nouveau » du dialogue de propriétés du pattern
    (`mw_patterns.py`, `live.new_pattern(num_bars, num_steps)`) ;
  - `DrumPlayer.load_pattern` (matrice dense).

  Les deux appellent désormais `_update_step_duration()`.
  - L'annulation passe par `_apply_pattern_from_store` → `set_bpm`, et
    l'ouverture d'un projet aussi : elles sont déjà couvertes.
  - `step_duration` reste un attribut, et non une propriété calculée :
    plusieurs tests l'affectent directement.

  À 120 BPM, une mesure de 4 temps dure 2,0 s pour 16, 32, 64 et 128 pas.
  `pytest tests/` est resté vert (1786) : aucun test existant ne figeait
  `60/bpm/4` sur un pattern de plus de 16 pas.
- **10c1** — conforme. `tests/test_step_duration.py` contient 24 tests, ce
  qui porte le total à 1810. Ils couvrent :
  - la formule à 16, 32, 64 et 128 pas, et 16 pas inchangé à plusieurs BPM ;
  - `set_bpm` et `load_pattern` ;
  - l'enchaînement du song et son retour au début, à BPM égal mais avec une
    résolution différente ;
  - Redimensionner (`_resize_live_pattern`), et les actions « Courant » et
    « Nouveau » du dialogue de propriétés, simulé ;
  - le métronome à un clic toutes les `60/bpm` secondes ;
  - le Note Repeat en 1/16, qui donne 16 doubles croches par mesure quelle
    que soit la résolution.

  Pendant l'écoute de 10b1, le Note Repeat a semblé ne pas réagir aux
  touches 1 à 9. La cause était le focus resté sur la liste des patterns
  (exclusion volontaire, `key_handler_chars.py:261`), et non le code de
  10b1. Ce comportement reste hors de ce chantier.
  - Aucun test existant n'avait à changer.
  - Contre-épreuve par 7 mutations volontaires, toutes détectées :
    - l'ancienne formule `60/bpm/4` ;
    - le recalcul conditionné au BPM, aux deux points du song ;
    - le Note Repeat en `16/denom` ;
    - un appel `_update_step_duration()` retiré, tour à tour dans
      Redimensionner, Nouveau et `load_pattern`.
- **10d1** — conforme. `Pattern._extend_tracks(n)` est appelé en fin de
  `from_dict`. Il reconstruit les listes au lieu de les étendre en place, car
  elles peuvent venir du dict de l'appelant (cache d'undo).
  - Vérifié sur les trois `project_0N.gvp`, encore à l'ancien format
    `curpattern`, 8 pistes. Après chargement, ils ont 16 pistes, les 8
    premières inchangées, et le dict d'origine n'est pas modifié.
  - L'utilisateur a validé à la main : 16 pistes, rejeu inchangé.
  - Suite rouge, comme prévu : 15 tests figent 8 pistes, à réparer en 10e1.
- **10d2** — commit imprévu, validé à la main par l'utilisateur (les quatre scénarios : prise vide, prise jouée, Remplacement à vide, Erase) : une prise live marque le projet modifié et
  s'annule d'un bloc.
  - **Constat de l'utilisateur pendant la vérification de 10d1** : après un
    enregistrement live, la fermeture ne proposait pas d'enregistrer. Le
    bug existait avant ce chantier. Seul `_add_undo` appelle
    `_mark_modified`, et rien sur le chemin de l'enregistrement live (R,
    Shift+R, Ctrl+R, Erase, notes du pavé numérique ou du clavier MIDI)
    n'appelle `_add_undo`. Une prise n'était donc ni signalée à la
    fermeture, ni annulable par Ctrl+Z.
  - **Décision de l'utilisateur, 2026-10-20** : un Undo avant la prise, retiré
    à la fin si rien n'a été enregistré. Enregistrer « du vide » pour
    effacer une partie de piste doit compter comme une modification.
  - **Mise en œuvre** (`ui/mw_project.py`) :
    - `_take_begin(title)` appelle `_add_undo` (titres « Enregistrement
      piste N », « Remplacement piste N », « Erase piste N ») et retient la
      signature de `_tape` du pattern live, l'état « modifié » d'avant, et
      l'entrée d'Undo créée.
    - `_take_end_if_idle()` ferme la prise dès que le player n'enregistre
      plus, n'efface plus et n'est plus en décompte. Si `_tape` est
      identique et que l'entrée de la prise est toujours la dernière de
      l'historique, elle est retirée, et l'état « modifié » est rétabli :
      `was_modified and modifié actuel`, pour qu'une sauvegarde faite
      pendant la prise reste prise en compte.
    - Une prise déjà ouverte n'en ouvre pas une seconde : un Erase pendant
      un Rec fait partie de la même prise.
  - **Effacer sans jouer est couvert par construction** : en Remplacement
    ou en Erase, les notes effacées au passage changent `_tape`, donc la
    prise est gardée.
  - **Ouvertures** : R, Shift+R, Ctrl+R (`key_handler_chars.py`,
    `key_handler_ctrl.py`) et l'activation d'Erase.
  - **Fermetures** : après chaque touche traitée par la fenêtre principale
    (`MainWindow._on_char_hook`), ce qui couvre tous les arrêts au clavier
    (R, Shift+R, E, V, Ctrl+F12…). Aussi au début de `_on_close`, de
    `_new_project` et de `_open_project`.
    - `_take` est remis à `None` au chargement et à la création d'un
      projet.
    - Un arrêt fait depuis l'éditeur MIDI ou la fenêtre Songs
      (`handle_transport`) ne ferme la prise qu'à la touche suivante dans
      la fenêtre principale, ou à la fermeture. Dans ce cas, une prise vide
      peut garder le projet marqué modifié : c'est un faux positif sans
      perte de données, accepté.
  - **`UndoManager.last_entry()`** est une nouvelle méthode de lecture, qui
    ne retire rien.
  - Les tests de `test_key_manager.py` qui appuient sur R, Shift+R, Ctrl+R
    ou E échouent à ce commit, car leur `FakeWindow` n'a pas `_take_begin`.
    Ils sont réparés en 10d3, avec les tests de la prise.
- **10d3** — tests de la prise. 21 nouveaux tests, 1830 au total, dont 15
  encore rouges, ceux de 10d1, à réparer en 10e1.
  - `tests/test_live_take.py`, 16 tests sur une fenêtre factice qui utilise
    les vrais `_add_undo`, `_take_begin` et `_take_end_if_idle` :
    - prise vide retirée, que le projet ait été modifié avant ou non ;
    - prise jouée gardée ;
    - Remplacement et Erase qui effacent sans rien jouer : prise gardée ;
    - payload modifié : prise gardée ;
    - pas de fermeture pendant Rec, Erase ou décompte ;
    - deuxième ouverture pendant une prise : un seul Undo ;
    - sauvegarde pendant une prise vide ;
    - autre action annulable pendant la prise ;
    - entrée de la prise déjà annulée par Ctrl+Z ;
    - changement de pattern pendant la prise ;
    - branchement dans `MainWindow._on_char_hook` et `_on_close`.
  - `test_key_manager.py` : la `FakeWindow` gagne `_take_begin`, qui note
    l'état du player au moment de l'appel. On vérifie ainsi que R,
    Shift+R, Ctrl+R et E ouvrent la prise avant de lancer le Rec ou
    l'Erase. Les arrêts n'ouvrent pas de prise. Un nouveau test couvre E
    quand Erase est déjà actif.
  - `test_undo_manager.py` : 3 tests de `last_entry`.
  - Contre-épreuve par 14 mutations volontaires de 10d2, toutes détectées :
    - signature ignorée, entrée jamais retirée, pas d'attente du repos ;
    - sauvegarde ignorée, entrée non vérifiée, deuxième prise ouverte ;
    - payload hors signature ;
    - prise ouverte après le Rec, prise ouverte aussi à la désactivation
      d'Erase ;
    - Ctrl+R sans prise, Shift+R sans prise ;
    - `_on_char_hook` sans fermeture, `_on_close` sans fermeture ;
    - `last_entry` qui renvoie la première entrée.
  - Écart corrigé avant le commit : le test de `_on_char_hook` dépendait de
    l'ordre des tests, car `wx.Window.FindFocus` exige un `wx.App`. Il est
    maintenant remplacé par `monkeypatch`.
- **10e1** — tests des 16 pistes. La suite redevient verte : 1841 tests.
  - **15 tests existants mis à jour.** Ils figeaient 8 pistes et lisent
    maintenant `Pattern.DEFAULT_NUM_TRACKS` ou `TrackRouter.NUM_TRACKS` au
    lieu d'un `8` en dur.
    - `test_track_router.py` : 6 tests.
    - `test_pattern_serialization.py` : 7 tests, et son `NUM_TRACKS` suit
      la constante.
    - `test_pattern.py` : 2 tests.

    Aucune assertion n'a changé de sens.
  - **Nouveau fichier `tests/test_sixteen_tracks.py`**, 11 tests :
    - valeurs par défaut à 16 pistes, router aligné ;
    - migration d'un preset `tape_v2` à 8 pistes : 8 premières pistes
      inchangées, pistes 9 à 16 vides avec les réglages par défaut ;
    - migration de l'ancien format `curpattern` à 8 pistes ;
    - preset sans clés `track_*` ;
    - dict de l'appelant intact, listes non partagées ;
    - preset à 16 pistes relu tel quel ;
    - preset migré réécrit à 16 pistes ;
    - grille et tape de la piste 16 conservées ;
    - solo sur la piste 16 ;
    - sélection Shift+↓ jusqu'à la piste 16, puis Ctrl+A.
  - **Contre-épreuve par 6 mutations volontaires de 10d1** :
    - détectées : `DEFAULT_NUM_TRACKS = 8`, migration non appelée, listes
      étendues en place, `_tape` non complété, `TrackRouter.NUM_TRACKS = 8` ;
    - non détectée : « `_tracks` non complété ».
  - **Écart avec 10d1, corrigé** : la mutation non détectée a montré que la
    ligne de `_extend_tracks` qui complétait `_tracks` était du code mort.
    - `Pattern.__init__` crée déjà 16 objets `Track`, `from_dict` ne réduit
      jamais cette liste, et rien d'autre ne la lit.
    - La ligne est retirée de `pattern.py` dans ce commit.
  - Non couvert par un test automatique : la liste des pistes de la
    fenêtre principale, dimensionnée par `_num_tracks`, parce qu'il faudrait
    construire la vraie `MainWindow`. Elle a été vérifiée à la main par
    l'utilisateur en 10d1.
- **10f1** — canal de piste, validé à la main par l'utilisateur (ordre Tab, règle du kit dans le dialogue, Ok/Ctrl+Z, Annuler sans étoile, aller-retour .gvp), conforme à D5 (version 10a2), avec trois
  précisions.
  - **Données** :
    - `Pattern.KIT_CHANNEL = 9` et `Pattern.default_channel(t) = min(t, 15)`,
      le canal par défaut selon l'index ;
    - `Pattern._track_channels` est sérialisé sous `track_channels` ;
    - `_extend_tracks` complète cette liste avec le canal par défaut de
      chaque index ;
    - `TrackRouter._track_channels` est synchronisé comme les autres
      réglages de piste : `_flush_pattern_to_store`,
      `_apply_pattern_from_store`, et l'enchaînement du song dans
      `mw_songs.py`.
  - **Règle du kit** :
    - `TrackRouter.channel_after_slot(track, slot, channel)` est la fonction
      pure : kit → 9 ; autre slot sur 9 → défaut ; sinon inchangé ;
    - `assign_slot_by_user` combine `assign_slot` et la règle ;
    - `_assign_track_slot` l'utilise, et son message de statut annonce le
      nouveau canal. Le pont Program Change et le chargement de projet
      gardent `assign_slot`, sans effet sur le canal.
  - **Dialogue** : `TrackPropertiesDialog` gagne les paramètres `channel` et
    `channel_after_slot`, avec une `ListBox` « Canal 1 » à « Canal 16 »
    placée après Slots dans l'ordre Tab.
    - Changer de slot applique la règle et met à jour la sélection du
      canal.
    - `on_change` reçoit le canal en sixième argument.
    - Nouvelle méthode `get_channel()`.
  - **Précision 1, l'Undo** : contrairement à ce que disait D5 (« comme les
    autres propriétés de piste »), le dialogue de propriétés de piste
    n'avait aucun Undo, et un changement de slot, de volume ou de pan ne
    marquait pas le projet modifié.
    - Il pose maintenant un Undo avant de s'ouvrir, sur le schéma de F2.
    - Cet Undo est retiré si l'on annule ou si rien n'a changé, et l'état
      « modifié » d'avant est alors rétabli.
    - Cela vaut pour toutes les propriétés, pas seulement le canal.
  - **Précision 2** : le choix du slot dans la fenêtre principale
    (`_assign_track_slot`) n'a toujours pas d'Undo. Ce comportement
    préexistant est laissé tel quel, hors chantier.
  - **Précision 3** : le test `test_on_change_receives_initial_values` de
    `test_track_properties_dialog.py` attend 5 arguments. Il est rouge à ce
    commit et sera mis à jour en 10g1.
- **10g1** — tests du canal de piste. La suite redevient verte : 1866
  tests.
  - **`tests/test_track_channels.py`**, 18 tests :
    - défaut piste N → canal N, plafonné à 16 ;
    - aller-retour `to_dict`/`from_dict` ;
    - clé absente ;
    - liste courte complétée selon l'index, dict de l'appelant intact ;
    - `set_track_channel` borné ;
    - règles de `channel_after_slot` : kit → 10, retour au défaut, piste 10
      sur 10, canal manuel gardé, slot vide ;
    - `assign_slot_by_user` ;
    - `assign_slot` seul et le pont Program Change ne touchent pas au
      canal ;
    - synchronisation par `_flush_pattern_to_store`,
      `_apply_pattern_from_store` et l'enchaînement du song ;
    - Ctrl+T : le statut annonce le canal ;
    - dialogue de propriétés simulé : canal et règle transmis, Ok avec
      changement, Ok sans changement et Annuler.
  - **`test_track_properties_dialog.py`**, 7 tests ajoutés, et le test
    `on_change` passe à 6 valeurs :
    - liste de 16 canaux ;
    - ordre Tab Slots → Canal → Volume ;
    - `on_change` reçoit le canal ;
    - règle appliquée au changement de slot, aller et retour ;
    - sans règle, le canal ne change pas ;
    - le choix manuel n'appelle pas la règle.
  - **Écart avec 10f1, corrigé dans ce commit** (`pattern.py`). Le test de la
    clé absente a montré un vrai bug :
    - `from_dict` gardait les canaux déjà présents dans l'objet quand
      `track_channels` manquait ;
    - or Ctrl+O recharge un projet dans les `Pattern` existants
      (`mw_project.py`, `self._pattern_list[i].from_dict(p)`) ;
    - ouvrir un `.gvp` d'avant 10f1, c'est-à-dire tous les projets
      existants, gardait donc les canaux du projet précédent.

    Désormais, une clé absente remet les canaux par défaut. Les autres
    clés `track_*` ont le même comportement depuis toujours. Il n'est pas
    corrigé ici, car tous les `.gvp` existants contiennent ces clés.
  - **Contre-épreuve par 21 mutations volontaires** de 10f1 et du
    correctif, toutes détectées. Une première version de la mutation
    « Canal créé après Pan » était mal construite. Elle a été refaite, et
    elle est détectée.
- **10h1** — `src/midi/midi_export.py` et `requirements.txt`, avec quatre
  écarts au plan.
  - **Écart 1, signature** : le pattern live ne porte ni la gamme, ni le
    nom, ni le BPM, car `copy_from` ne recopie que les dimensions et
    `_tape`. D6 calculait la note d'une case de grille synthé à partir de
    `pattern._kb_scale`, ce qui aurait donné la gamme par défaut.
    - `build_pattern_midi(pattern, *, name, bpm, track_channels,
      track_is_synth, track_names, kit_note_base, synth_grid_notes,
      voice_durations)` reçoit donc ces valeurs en arguments nommés.
    - `synth_grid_notes` est la liste de lecture du router
      (`_kb_notes_play`), exactement ce que joue le rejeu.
  - **Écart 2, canaux** : un événement `KIT` est écrit sur le canal de sa
    piste, comme le veut D5 révisée en 10a2. Le texte de D6 et D9, écrit
    avant 10a2, ne le précisait pas.
  - **Écart 3, doublons** : D6 ne traitait pas le cas d'une même note
    jouée deux fois au même tick. Elle est écrite une seule fois, faute de
    quoi un note-off serait placé avant son propre note-on.
  - **Écart 4, `requirements.txt` sans pygame**, sur remarque de
    l'utilisateur.
    - Vérifié : avec `pygame` bloqué à l'import, `main`,
      `ui.main_window`, le player et le MIDI se chargent.
    - Seuls `src/pygame_driver.py` (ancien driver, plus importé par
      l'application), `tests/test_pygame_driver.py`,
      `tests/test_sound_manager.py` et `tools/bench_latency.py` l'utilisent.
    - pygame est cité en commentaire avec pytest, comme dépendance
      facultative.
    - La table des dépendances de `docs/SPECS.md` est corrigée : elle
      donnait encore pygame pour l'audio des kits. La ligne `mido` y est
      ajoutée.
  - **Vérification avant commit** : les patterns 1 et 2 de
    `project_01.gvp` ont été exportés par un script, puisque l'interface
    n'arrive qu'en 10j1. Les pistes sur un slot kit ont été mises sur le
    canal 10, comme après une assignation.
    - Relecture par mido : type 1, 480 ticks par noire, une piste
      conductor puis une piste par piste non vide, canaux 1, 3, 4 et 10,
      note-on et note-off appariés.
    - Rendu sans erreur par FluidSynth (FluidR3_GM).
    - Écoute par l'utilisateur : les deux fichiers se lisent, les notes des instruments et la batterie sont reconnaissables. Mais sans Program Change, toutes les pistes mélodiques jouent le son de piano par défaut. Ce manque est traité en 10h2 et suivantes.
  - **Constat à trancher, hors de ce commit** : le nom de piste exporté
    vient de `voice_manager.get_name(t)`. C'est le même stockage que le
    nom F2 et que l'affichage de la liste des pistes. Or ce stockage est
    indexé par pad, et il contient les libellés du kit (« Kick 2 »,
    « Kick 1 »…). Les pistes SMF portent donc ces noms tant qu'aucune
    piste n'a été renommée.

### Phase 7 étape 10h2 — Plan complémentaire : Program Change par slot (instrument GM ou kit GM2), noms de pistes

**Origine.** Écoute de 10h1 par l'utilisateur, le 2026-10-20. Sans Program
Change, un lecteur GM joue toutes les pistes mélodiques avec son programme
par défaut, le piano. Il faut écrire en tête de chaque piste l'instrument
voulu. L'écoute a aussi montré des pistes SMF nommées d'après des pads
(« Kick 2 »…).

**État des lieux.**
- Les patches (`PATCHS/*.json`) ne portent aucun numéro de programme GM :
  seulement `name`, `loop` et `sounds` ou `samples`.
- `InstrumentSlot.config` est un dict libre, sérialisé tel quel dans le
  `.gvp` (`rack.to_dict`).
- `midi_constants.GM_PATCH_NAMES` donne les 128 noms GM, l'index étant le
  numéro de programme.
- `midi_constants.GM2_DRUMKIT_NAMES` donne les 9 kits GM2 nommés, aux
  programmes 0, 8, 16, 24, 25, 32, 40, 48 et 56. Les autres index ne sont
  pas des noms.
- Aucune boîte ne règle un slot : la liste des slots sert seulement à
  choisir et assigner.
- Le nom F2 d'une piste est stocké dans `voice_manager`, au même endroit
  que les noms de pads. On ne peut donc pas savoir si une piste a été
  renommée.

**Décisions validées (utilisateur, 2026-10-20).**

**D11 — un programme par slot : instrument GM pour un synthé, kit GM2
pour un kit.** Pour les kits, c'est une suggestion de l'utilisateur après
la première version de ce plan.
- **Stockage** : `InstrumentSlot.config["gm_program"]`, de 0 à 127. Il
  est sérialisé avec le Rack, sans changement de format.
- **Clé absente**, cas de tous les slots existants : le programme est
  déduit du nom du slot par `guess_gm_program(name, drums=False)`, une
  fonction pure placée dans `midi_constants.py`. Avec `drums=True`, la
  comparaison se fait avec les 9 kits GM2 au lieu des 128 instruments. La
  déduction fonctionne ainsi :
  - les mots du nom sont normalisés (minuscules, `_` et camelCase
    séparés, chiffres ignorés) ;
  - on retient le nom GM qui partage le plus de mots avec eux ;
  - à égalité, le plus petit numéro l'emporte ;
  - sans aucun mot commun, le programme 0 (Acoustic Grand Piano, ou
    Standard Kit pour un kit).

  Les chiffres sont ignorés : sinon « Piano 1 » donnerait « Electric
  Piano 1 ». En contrepartie, « My 808 » donne Standard Kit.

  Sur les patches existants, cela donne :
  - « Piano 1 », « Yamaha Grand Piano » → 0, Acoustic Grand Piano ;
  - « Acoustic Guitar 1 » → 24, Acoustic Guitar (nylon) ;
  - « DrawbarOrgan » et « organ_b3_basic_fast » → 16 ;
  - « Percussive Organ » → 17, « Rock Organ » → 18, « Church Organ » → 19,
    « Reed Organ » → 20 ;
  - kits : « TR-707 » → 25, TR-808 Kit, grâce au mot « tr » ;
    « GM (FluidR3) » → 0, Standard Kit.
- **Kits** : le programme choisit le kit GM2 ou GS. Un lecteur GM1 strict
  peut l'ignorer et garder son kit standard, sans dommage.
- **Export** : nouveau paramètre `track_programs`, avec par piste un
  programme ou `None`.
  - Un `program_change` est écrit au tick 0 sur le canal de la piste,
    avant tout événement de `_tape`. Un `ETYPE_PGM` capturé au tick 0
    passe donc après, et l'emporte.
  - L'appelant donne le programme du slot de la piste si ce slot est un
    synthé ou un kit. Pour un slot vide ou d'un autre type, il donne
    `None`.
- **Rejeu** : il ne change pas, puisque le son vient des échantillons. Le
  programme ne sert qu'à l'export et au futur mode Rack GM.

**D12 — nom de piste exporté = nom du slot.**
- La piste SMF prend `InstrumentSlot.name`, par exemple « Acoustic
  Guitar 1 » ou « TR-707 », et « Track NN » si le slot est vide.
- Le nom F2 n'est pas utilisé tant qu'il est mêlé aux noms de pads.
  Séparer les deux dans les données est un chantier distinct, hors
  chantier 10.
- Le module ne change pas, puisque `track_names` est déjà un paramètre :
  c'est l'appelant (10j1) qui lui passe les noms de slots.

**D13 — interface dans les propriétés de la piste.**
- `TrackPropertiesDialog` gagne une `ListBox` « Programme GM du slot » de
  128 entrées, « 1 - Acoustic Grand Piano » à « 128 - Gunshot », placée
  après Canal dans l'ordre Tab.
  - Elle montre le programme du slot sélectionné dans le dialogue.
  - **Son contenu suit le type du slot.** Pour un synthé : les 128
    instruments GM. Pour un kit : les 9 kits GM2, par exemple « 1 -
    Standard Kit » ou « 26 - TR-808 Kit ». Le numéro affiché est le
    programme + 1.
  - Elle est désactivée pour un slot vide ou d'un autre type.
  - Changer de slot dans le dialogue recharge la liste (instruments ou
    kits) et y sélectionne le programme du nouveau slot.
- Modifier le programme modifie le slot, donc toutes les pistes qui le
  jouent, avec aperçu immédiat comme les autres champs.
  - Annuler rétablit le programme d'origine de chaque slot touché.
  - L'Undo du dialogue (10f1) couvre ce changement, car
    `_capture_state` sérialise le Rack.
  - Valider sans rien changer, programme compris, retire l'Undo comme
    avant.

**Alternatives écartées** :
- un programme par piste, car deux pistes du même synthé pourraient
  alors avoir deux instruments ;
- une clé dans le fichier patch, qui obligerait à éditer les `.json` des
  patches ;
- une nouvelle boîte de propriétés du slot, qui ajouterait une boîte et
  un raccourci ;
- « Track NN » comme nom de piste par défaut, moins parlant que le nom de
  l'instrument.

**Hors périmètre** :
- la séparation entre noms de pistes et noms de pads ;
- la banque (CC0/CC32) ;
- l'écriture de `gm_program` par l'outil d'extraction SF2 ;
- les kits GS au-delà des 9 kits GM2 nommés.

**Découpage inséré** (avant 10i1, inchangé) :

| Étape | Contenu | Fichiers |
|---|---|---|
| **10h2** | Doc — ce plan complémentaire. | `docs/DESIGN.md` |
| **10h3** | Implémentation — `guess_gm_program(name, drums)` ; `slot_gm_program(slot)` (config ou déduction, instruments ou kits selon le type) ; paramètre `track_programs` de l'export ; `ListBox` Programme dans `TrackPropertiesDialog` (instruments ou kits selon le slot), avec aperçu, Annuler et Undo, branchée dans `mw_tracks.py`. | `midi/midi_constants.py`, `rack.py`, `midi/midi_export.py`, `ui/dialogs_properties.py`, `ui/mw_tracks.py` |
| **10h4** | Tests — déduction sur les noms GM, les kits GM2, les patches et kits existants ; `program_change` au tick 0 avant un `ETYPE_PGM`, kit compris ; `None` → rien d'écrit ; dialogue (128 instruments ou 9 kits selon le slot, ordre Tab, désactivé pour un slot vide, rechargé au changement de slot) ; Ok, Annuler et inchangé dans `mw_tracks`. | `tests/test_gm_program.py` (nouveau), `tests/test_track_properties_dialog.py`, `tests/test_track_channels.py` |

Avant de committer 10h3, il faudra réécouter un export des patterns 1 et 2
de `project_01.gvp`, cette fois avec leurs programmes, le kit TR-808
compris.
- **10h3** — conforme au plan 10h2, avec un point de vigilance et une
  limite.
  - **Ce qui est livré** :
    - `midi_constants.py` : `GM2_DRUMKITS`, c'est-à-dire les 9 kits nommés
      sous forme de couples (programme, nom), et
      `guess_gm_program(name, drums)` ;
    - `InstrumentSlot.gm_program()` lit la config si elle est valide,
      sinon déduit le programme ; il renvoie `None` hors synthé et kit ;
    - `InstrumentSlot.set_gm_program()` ;
    - le paramètre `track_programs` de l'export : un `program_change` au
      tick 0, de rang -1, donc avant un `ETYPE_PGM` capturé au même tick ;
    - la `ListBox` « Programme GM du slot » de `TrackPropertiesDialog`.
      Elle prend un nouveau paramètre `slot_program(slot)` qui renvoie
      (genre, programme) et une méthode `get_program()`. `on_change`
      reçoit 7 valeurs.
  - **Point de vigilance, l'Undo** : `InstrumentSlot.to_dict` renvoie le
    dict `config` lui-même, si bien que les instantanés d'Undo
    (`_capture_state` → `rack.to_dict()`) le partagent. Modifier `config`
    sur place aurait aussi modifié l'état mémorisé pour Ctrl+Z.
    - `set_gm_program` remplace donc `config` par un nouveau dict.
    - Pour Annuler, `mw_tracks` garde le dict d'origine de chaque slot
      touché et le remet en place.
  - **Limite** : changer le programme d'un slot A dans le dialogue, puis
    choisir un slot B et valider, garde le nouveau programme de A. C'est
    cohérent avec « modifier le programme modifie le slot ».
  - **Vérification d'export** : patterns 1 et 2 de `project_01.gvp`,
    relus par mido.
    - Pistes nommées « Acoustic Guitar 1 » (canal 1, programme 25),
      « TR-707 » (canal 10, TR-808 Kit, 26), « DrawbarOrgan » (canal 3,
      17), « Piano 1 » (canal 4, 1). Tous les programmes sont au tick 0.
    - Numéros affichés de 1 à 128.
  - **Écoute par l'utilisateur** : instruments et kit reconnus. L'orgue
    semblait absent du pattern 1. Vérification faite, le Program Change
    était bien appliqué : les rendus avec les programmes 1 et 17
    diffèrent. L'orgue sortait au même niveau que le piano, mais couvert
    par la guitare et la batterie. L'utilisateur l'a confirmé à l'oreille
    sur la piste seule.
  - **Constats de l'écoute**, pour la suite :
    - les volumes de piste ne sont pas exportés : ce sera l'étape 10h5,
      volume et pan, à la demande de l'utilisateur ;
    - un ancien projet garde sa piste kit sur le canal N, par exemple 2.
      Le Program Change du kit y choisit alors un instrument mélodique :
      sur le canal 2, la TR-707 joue en Acoustic Guitar (steel). La
      réponse viendra plus tard : soit migrer en passant les kits sur 10,
      soit réassigner le kit à la main.
  - **Suite rouge à ce commit**, 6 tests de l'ancienne interface du
    dialogue, à mettre à jour en 10h4 :
    - le `FakeDlg` de `test_track_channels.py` n'a pas `get_program` ;
    - `on_change` passe à 7 valeurs ;
    - l'ordre Tab est désormais Canal → Programme → Volume.
- **10h4** — tests du Program Change par slot. La suite redevient verte :
  1893 tests.
  - **Les 6 tests rouges de 10h3 sont réparés.**
    - Le `FakeDlg` de `test_track_channels.py` a maintenant
      `get_program`, et des valeurs à 7 éléments.
    - `on_change` passe à 7 valeurs.
    - L'ordre Tab est vérifié dans l'ordre de création. La liste
      Programme, désactivée sans `slot_program`, n'accepte pas le focus.
  - **`test_track_properties_dialog.py`**, 8 tests ajoutés :
    - 128 instruments pour un synthé, avec les libellés « 1 - … » à
      « 128 - Gunshot » ;
    - 9 kits pour un kit ;
    - liste vide et désactivée pour un slot vide ou sans `slot_program` ;
    - programme inconnu : aucune sélection ;
    - ordre Tab Canal → Programme → Volume ;
    - liste rechargée au changement de slot, synthé ↔ kit ↔ vide ;
    - `on_change` reçoit le numéro de kit et non l'index.
  - **Nouveau fichier `tests/test_gm_program.py`**, 19 tests :
    - déduction sur les 128 noms GM, les patches et les kits existants,
      les chiffres ignorés, les noms vides ou inconnus ;
    - `gm_program` : config, valeur invalide, types sans programme ;
    - `set_gm_program` remplace `config` et borne la valeur. Un
      instantané `rack.to_dict()` reste intact ;
    - export : `program_change` en premier au tick 0 sur le canal de la
      piste, rien si `None`, avant un `ETYPE_PGM` au tick 0, valeur
      bornée ;
    - `mw_tracks`, avec un dialogue factice qui joue l'aperçu : Ok avec
      un autre programme, Annuler (les dicts `config` d'origine sont
      remis, même pour un slot visité puis quitté), Ok sans changement,
      programme changé puis rétabli, kit GM2 choisi sur un slot kit.
  - **Écart avec 10h3, corrigé dans ce commit** (`midi_constants.py`). Le
    test sur les 128 noms GM a révélé un défaut :
    - « Electric Piano 1 » donnait Electric Grand Piano (2), qui partage
      les mêmes 2 mots, au lieu d'Electric Piano 1 (4) ;
    - une correspondance exacte des mots passe désormais avant le compte
      des mots communs ;
    - « Piano 1 » donne toujours 0, aucun nom GM ne se réduisant au seul
      mot « piano » ;
    - les exemples de D11 sont inchangés.
  - **Contre-épreuve par 22 mutations volontaires**, toutes détectées :
    - déduction : chiffres gardés, camelCase non coupé, correspondance
      exacte ignorée, égalité inversée, table GM utilisée pour les kits ;
    - `gm_program` et `set_gm_program` : config ignorée, bornes, kit
      traité comme un synthé, tout type accepté, modification sur place ;
    - export : Program Change mal placé ou sur le mauvais canal ;
    - dialogue : liste, libellés, désactivation, rechargement, index ;
    - `mw_tracks` : programme non écrit, Annuler sans restauration, kit
      vu comme un synthé.
- **10h5** — implémentation : volume et pan de piste exportés, demandés
  par l'utilisateur après l'écoute de 10h3, et notes PATCH muettes omises.
  Cela lève l'exclusion « volume et pan des pistes » de D10.
  - **Découpage** : les tests sont dans un commit séparé, 10h6, à la
    demande de l'utilisateur (« quelle qu'en soit la taille »). La
    migration des kits annoncée en 10h6/10h7 devient donc **10h7/10h8**.
  - **Décisions** :
    - nouveaux paramètres `track_volumes` (0..100) et `track_pans`
      (-100..+100) de `build_pattern_midi`. L'appelant (10j1) passera les
      listes de `TrackRouter` ;
    - au tick 0 de chaque piste, l'ordre est : Program Change, puis CC7,
      puis CC10. Ils sont écrits pour toute piste non vide, kit compris, et
      même sans programme ;
    - un CC7 ou un CC10 capturé dans `_tape` au tick 0 vient après, et
      l'emporte ;
    - les conversions sont l'inverse de `TrackRouter.on_cc_tape` :
      `volume_to_cc7(v) = round(v·127/100)`, avec un aller-retour exact
      sur 0..100 ; `pan_to_cc10(p) = 64 + round(p·63/100)`, borné à
      1..127, avec −100, 0 et +100 donnant 1, 64 et 127 ;
    - pour le pan, l'aller-retour se fait à ±1 près, car le CC10 n'a que
      127 valeurs pour 201 positions. 74 positions sont touchées, 50 par
      exemple revenant à 51 ;
    - le volume 100 donne CC7 = 127, et non le 100 par défaut d'un lecteur
      GM : une piste à fond dans l'appli est à fond dans le fichier ;
    - canal partagé entre plusieurs pistes : chaque piste écrit ses
      valeurs, et le lecteur garde la dernière reçue. C'était la raison de
      l'exclusion initiale, acceptée désormais ;
    - toujours exclus : mute et solo, ainsi que le volume et le pan des
      pads (`voice_manager`), qui sont par pad et non par piste.
  - **Notes PATCH d'une piste sans slot synthé, non exportées.** Ce point
    a été demandé par l'utilisateur pendant l'écoute de 10h5.
    - Au rejeu, elles sont muettes (`TrackRouter.on_patch_tape`). Un
      lecteur GM les jouait pourtant, sur le canal du kit : la piste
      TR-707 du pattern 1 de `project_01.gvp` avait ainsi 15 notes PATCH,
      de 50 à 60, jouées en ride, chinese cymbal et toms aigus.
    - Ce comportement remplace la phrase de D6 « les données sont
      conservées », au nom du principe « le fichier sonne comme l'appli ».
    - Les notes GRID et KIT d'une piste kit restent exportées. Une piste
      qui n'aurait que des PATCH sur un kit garde sa piste SMF, sans note.
  - **Écoute par l'utilisateur** : la guitare, réglée à 45, est plus
    discrète, et l'orgue s'entend seul.
  - **Constats de l'écoute, hors du code de ce chantier** :
    - **Octave de l'orgue.** L'orgue sonnait une octave plus bas dans
      le fichier que dans l'appli. Le patch
      `PATCHS/DrawbarOrgan.json` déclarait la racine « C4 », alors que
      l'échantillon est mesuré à 523,5 Hz, soit C5 (note 72). L'appli
      jouait donc tout l'orgue une octave trop haut, et le fichier les
      notes réellement jouées.
      - Avec l'accord de l'utilisateur, la racine est corrigée en « C5 ».
      - Les parties d'orgue sont transposées de +12 : 31 notes dans
        `project_01.gvp` et 124 dans `project_03.gvp`, à l'ancien format,
        tous deux en pattern 1, piste 3.
      - Des sauvegardes ont été prises avant ces modifications.
      - Ces fichiers sont des données utilisateur, hors du dépôt.
    - **Kit non GM.** Le kit TR-707 n'est pas rangé selon la table GM.
      Sa note 49 est « Cowbell », mais en GM c'est une crash : ce sont les
      37 « cymbales très fortes » entendues. Une table de correspondance
      pad → note GM, déduite du libellé du pad, est proposée comme
      chantier séparé.
- **10h6** — tests de 10h5. Nouveau fichier `tests/test_midi_export_mix.py`,
  12 tests, 1905 au total.
  - **Conversions** :
    - bornes, et l'exemple 45 → 57 ;
    - aller-retour du volume exact sur 0..100 ;
    - aller-retour du pan à ±1 près, exact pour −100, 0 et +100. Pour 50,
      on obtient le CC 96, qui revient à 51.
  - **Export** :
    - Program Change, CC7 et CC10 au tick 0, dans cet ordre, sur le
      canal de la piste ;
    - CC7 et CC10 écrits même sans programme ;
    - `None` : rien d'écrit ;
    - un CC7 capturé au tick 0 est écrit après, et l'emporte ;
    - canal partagé : chaque piste écrit sa valeur.
  - **Notes PATCH** :
    - omises sur une piste kit, alors que GRID et KIT sont gardés ;
    - gardées sur une piste synthé ;
    - une piste kit qui n'a que des PATCH donne une piste SMF sans note.
  - **Contre-épreuve par 10 mutations volontaires de 10h5**, toutes
    détectées :
    - volume sur 100, volume tronqué ;
    - pan sans décalage, pan borné à partir de 0 ;
    - CC7 après les CC de `_tape`, CC10 avant CC7, CC7 avant le
      programme ;
    - canal 0 pour le volume, pan non écrit ;
    - PATCH toujours exportées.
- **10h7** — implémentation : à l'ouverture d'un projet sans canaux, les
  pistes kit passent sur le canal 10. C'est une décision de l'utilisateur
  du 2026-10-20, qui révise D5 : jusque-là, la règle du kit ne jouait qu'à
  une assignation explicite.
  - **Constat qui l'a motivée** : un ancien projet gardait sa piste kit sur
    le canal N. Le Program Change du kit y choisissait alors un instrument
    mélodique, par exemple Acoustic Guitar (steel) sur le canal 2.
  - **Mise en œuvre** :
    - `Pattern.from_dict` pose `_needs_kit_channels` quand la clé
      `track_channels` est absente. L'attribut est recalculé à chaque
      lecture, donc remis à `False` sur un `Pattern` réutilisé ;
    - `Pattern.apply_kit_channels(is_kit_slot)` met sur le canal 10 les
      pistes dont le slot est un kit, une seule fois, puis efface le
      drapeau ;
    - `mw_project._load_project` l'appelle juste après chaque
      `from_dict`. Le Rack est déjà lu à ce moment, et `Pattern` ne le
      connaît pas.
  - **Portée** :
    - seul `_load_project`, c'est-à-dire Ctrl+O et le démarrage, lit des
      fichiers ;
    - `_restore_state` (Undo) a toujours `track_channels`, il n'est donc
      pas concerné ;
    - un projet déjà enregistré avec ses canaux est laissé tel quel :
      `project_01.gvp` garde ses réglages.
  - **Effet à connaître** : les pistes vides passent aussi sur 10. Dans les
    anciens projets, elles pointent par défaut sur le slot 1, qui est un
    kit. Leur assigner un synthé les ramène à leur canal par défaut (règle
    de 10f1).
  - **Vérifié dans l'appli par l'utilisateur, et par script sur `project_02.gvp`** : dans les patterns 1 et 2, la piste 2
    (kit) passe sur 10 ; dans les patterns 3 à 5, la piste 1 (kit) passe
    sur 10. La piste synthé reste sur son canal.
- **10h8** — tests de 10h7. Nouveau fichier
  `tests/test_kit_channel_migration.py`, 7 tests, 1912 au total.
  - **Drapeau** : `_needs_kit_channels` n'est vrai que si la clé est
    absente, et il est remis à faux sur un `Pattern` réutilisé.
  - **Règle** : pistes kit sur 10, piste synthé gardée, pistes vides sur le
    slot kit.
  - **Une seule application** : `apply_kit_channels` n'agit qu'une fois.
  - **Canaux enregistrés** : intacts, y compris un kit laissé sur le canal
    2. Un projet migré puis réenregistré garde ses canaux.
  - **`_load_project` sur un vrai `.gvp` temporaire**, avec le vrai
    `ProjectMixin` et une fenêtre factice :
    - ancien projet migré, et le router reçoit le pattern migré ;
    - projet avec canaux laissé tel quel.
  - **Contre-épreuve par 7 mutations volontaires**, toutes détectées :
    - drapeau toujours faux, jamais remis, non effacé, ou non testé ;
    - kit ignoré, toutes les pistes passées sur 10 ;
    - chargement sans migration.
- **10h9** — correctif d'un bug antérieur à ce chantier, repéré en écrivant
  10h7 : après Ctrl+O, l'Undo pouvait réinjecter des patterns de l'ancien
  projet.
  - **Cause** :
    - `_capture_state` ne re-sérialise que les patterns marqués dans
      `_pattern_cache_dirty`, et le pattern courant ;
    - `_new_project` remet tout le cache à neuf, mais `_load_project` ne
      le faisait pas ;
    - après l'ouverture d'un projet B, le cache gardait donc les dicts du
      projet A pour tous les patterns sauf le courant ;
    - la première action annulable prenait alors un instantané mélangé, et
      un Ctrl+Z jusqu'à ce point remettait dans B des patterns de A.
  - **Reproduit par un script avant le correctif** : l'instantané pris
    après l'ouverture de B donnait les noms `['B', 'A', 'A']`, et
    `['B', 'B', 'B']` après.
  - **Correctif** : `_load_project` marque tous les patterns comme périmés
    (`_pattern_cache_dirty = set(range(...))`) juste après leur lecture.
  - **Hors périmètre** : l'historique d'Undo n'est pas vidé à l'ouverture
    d'un projet. Ctrl+Z juste après Ctrl+O revient à un état de l'ancien
    projet, comme avant ce chantier. C'est un comportement à discuter à
    part.
- **10h10** — tests de 10h9. Nouveau fichier
  `tests/test_load_project_cache.py`, 3 tests, 1915 au total. Ils
  utilisent les vrais `_capture_state`, `_add_undo` et `_load_project`
  sur un `.gvp` temporaire :
  - l'instantané pris après Ctrl+O ne contient que les patterns du projet
    ouvert ;
  - tous les patterns sont marqués à re-sérialiser ;
  - une entrée d'Undo prise après l'ouverture ne contient aucun pattern de
    l'ancien projet.

  **Contre-épreuve** : avec le code d'avant 10h9, les 3 tests échouent.
- **10i1** — tests du module d'export, conformes au plan. Nouveau fichier
  `tests/test_midi_export.py`, 18 tests, 1933 au total. Le fichier est
  relu par mido, en temps absolus. Le Program Change, le volume et le pan
  ont déjà leurs tests en 10h4 et 10h6.
  - **Fichier** :
    - écrit puis relu, type 1, 480 ticks par noire ;
    - conductor : nom, tempo, 4/4, fin à la fin du pattern ;
    - pattern vide : conductor seule ;
    - une piste SMF par piste non vide, avec son nom ou « Track NN » ;
    - fin de piste à la fin du pattern, ou au dernier note-off s'il
      déborde.
  - **Canaux et notes** :
    - tout est écrit sur le canal de la piste, `ev.channel` étant ignoré ;
    - GRID : gamme du router pour un synthé, `kit_note_base + pad` pour
      un kit ;
    - KIT et PATCH : note du payload ;
    - vélocités bornées à 1..127.
  - **Durées** :
    - GRID : sa `dur`, sinon la durée de la voix ;
    - PATCH sans `dur` : 500 ms ;
    - KIT : un pas ;
    - durée calculée selon le BPM, au minimum 1 tick.
  - **Temps** : à 16 et 32 pas, avec un temps flottant arrondi.
  - **Chevauchements** : la première note est coupée, et un doublon au
    même tick n'est écrit qu'une fois.
  - **Ordre à tick égal** : note-off, PGM, CC, bend, note-on. Deux bends
    au même tick restent dans l'ordre de `_tape`, le dernier l'emportant
    comme dans `_bend_state_at`.
  - **CC, PGM, bend** : valeurs, temps et bornes, y compris un numéro de CC
    négatif.
  - **Contre-épreuve par 24 mutations volontaires du module**, toutes
    détectées, dont :
    - type 0, PPQ 96, tempo et signature ;
    - pistes vides écrites, nom, canal ;
    - temps et durées, voix, KIT, PATCH ;
    - vélocité, chevauchement, doublon, ordre ;
    - bornes, fin de piste.

    La mutation « CC sans borne basse » n'était d'abord pas détectée. Un
    numéro de CC négatif a été ajouté au test, et elle l'est désormais.
- **10j1** — interface de l'export, conforme à D10. Validée au clavier par l'utilisateur : fenêtre principale, éditeur MIDI, Annuler, annonces Orca.
  - **`AppConfig.exports_dir`** : clé `exports_dir`, absolue ou relative
    à `base_dir`. Par défaut, c'est le dossier `EXPORTS` voisin de
    `projects_dir`, soit `/home/com/groovybox/EXPORTS`.
    `MainWindow._exports_dir` est lu au démarrage.
  - **`mw_project`** :
    - `_midi_export_params()` réunit les arguments de
      `build_pattern_midi` ; ils sont détaillés ci-dessous ;
    - `_midi_export_filename()` propose `Pat_NN.mid`, ou
      `Pat_NN_<nom>.mid` avec un nom nettoyé ;
    - `_export_midi(parent, status)` crée le dossier au besoin, ouvre un
      `wx.FileDialog` (`*.mid`, `FD_OVERWRITE_PROMPT`), ajoute `.mid` s'il
      manque, exporte le pattern live, puis annonce « Pattern NN
      exporté : <fichier> », « Export MIDI annulé » ou l'erreur.
  - **Arguments réunis par `_midi_export_params()`** :
    - nom du pattern, ou `Pat_NN` ;
    - BPM du player ;
    - canaux, volumes et pans de `TrackRouter` ;
    - type, nom et programme du slot de chaque piste ;
    - `snd.kit_base + kit_offset` ;
    - `router._kb_notes_play` ;
    - durées du `VoiceManager`.
  - **Raccourci Alt+Shift+E**, dans la fenêtre principale
    (`key_handler_alt.py`) et dans l'éditeur MIDI (`mew_keymap.py`). Dans
    l'éditeur, le dialogue et le statut sont ceux de sa fenêtre.
    `docs/shortcuts.md` est mis à jour.
  - **Écart au plan sur le nom** : la piste conductor et le fichier
    utilisent `Pat_NN`, la convention de la liste des patterns
    (`_pattern_label`), et non `Pattern_NN` comme l'écrivait D4.
  - **Essai réel, sans clavier** : une vraie `MainWindow` chargée sur
    `project_01.gvp`, avec un `FileDialog` simulé.
    - Nom proposé `Pat_01.mid`, dans `/home/com/groovybox/EXPORTS`.
    - Canaux 1, 10, 3, 4 ; programmes 24, 25, 16, 0 ; noms des slots ;
      kit 36 ; 100 BPM.
    - Fichier relu par mido : 5 pistes, 9,95 s.
    - Le dossier `EXPORTS` a été créé par cet essai.
- **10k1** — tests de l'interface d'export. Nouveau fichier
  `tests/test_midi_export_ui.py`, 12 tests, 1945 au total.
  - **`AppConfig.exports_dir`** :
    - par défaut, `EXPORTS` à côté du dossier des projets, qu'il soit
      absolu avec un `/` final ou relatif ;
    - valeur absolue, relative à `base_dir`, ou vide.
  - **`_midi_export_params`** : testé sur une fenêtre factice qui utilise
    le vrai `ProjectMixin`, avec de vrais `TrackRouter`, `Rack` et
    `VoiceManager`. Il prend :
    - les canaux, volumes et pans du router ;
    - le type, le nom et le programme des slots, y compris un programme
      réglé ;
    - `kit_base + kit_offset` ;
    - les notes de la gamme et les durées des voix ;
    - le BPM du player ;
    - le nom du pattern, ou `Pat_NN` ;
    - et ce sont des copies des listes.
  - **`_midi_export_filename`** : `Pat_NN.mid`, et un nom de pattern
    nettoyé.
  - **`_export_midi`**, avec un `FileDialog` simulé :
    - Ok : dossier créé, paramètres du dialogue (dossier, nom, filtre,
      `FD_SAVE | FD_OVERWRITE_PROMPT`, parent, `Destroy`), fichier relu
      avec les canaux et la note de kit tenant compte de l'offset, statut ;
    - extension `.mid` ajoutée si elle manque ;
    - Annuler : rien d'écrit ;
    - erreur d'écriture : annoncée, sans exception ;
    - parent et statut fournis par l'éditeur MIDI.
  - **Raccourcis** :
    - fenêtre principale : Alt+Shift+E exporte, Alt+E seul ne fait rien ;
    - éditeur MIDI : Alt+Shift+E exporte, avec le dialogue et le statut de
      l'éditeur.
  - **Contre-épreuve par 20 mutations volontaires de 10j1**, toutes
    détectées :
    - `exports_dir` : défaut, `normpath`, valeur relative ;
    - nom, BPM, canaux, offset du kit, noms, programmes, volumes, listes
      partagées ;
    - nettoyage du nom de fichier ;
    - `makedirs`, confirmation d'écrasement, parent, extension, erreur,
      statut ;
    - les deux raccourcis.

### Clôture (10l1)

**10a1-10k1 FAITS** (commits `7807389`..`7fd29c8`, 23 commits, 1945 tests
passed) — **chantier Phase 7 étape 10 complet**. Le pattern courant
s'exporte en fichier MIDI standard par Alt+Shift+E.

**Ce que le chantier a livré**, dans l'ordre des étapes :
- **Lecteur** (10b1-10c1) : un temps dure 60/BPM quel que soit le nombre
  de pas par mesure. `_update_step_duration` remplace les quatre formules
  `60/bpm/4`.
- **16 pistes par pattern** (10d1, 10e1). Les presets à 8 pistes sont
  complétés au chargement.
- **Prise live et Undo** (10d2-10d3), un bug préexistant : une prise
  marque le projet modifié et s'annule d'un bloc. Un Undo vide est retiré.
  Effacer à vide compte comme une modification.
- **Canal MIDI par piste** (10a2, 10f1-10g1) :
  - piste N → canal N par défaut ;
  - un kit assigné met la piste sur 10, un autre slot la ramène au
    défaut ;
  - liste Canal dans les propriétés de la piste ;
  - Program Change et chargement de projet sans effet ;
  - un `.gvp` sans canaux reçoit les canaux par défaut (correctif 10g1).
- **Module d'export** `src/midi/midi_export.py` (10h1, 10i1) :
  - SMF de type 1, PPQ 480, conductor ;
  - une piste SMF par piste non vide, sur le canal de la piste ;
  - notes, durées, chevauchements, ordre à tick égal, CC, PGM et bend ;
  - `requirements.txt`, sans pygame.
- **Program Change par slot** (10h2-10h4) :
  - instrument GM pour un synthé, kit GM2 pour un kit ;
  - déduit du nom, avec un nom GM exact prioritaire (correctif 10h4),
    réglable dans les propriétés de la piste ;
  - pistes SMF nommées d'après leur slot.
- **Volume et pan** en CC7 et CC10 (10h5-10h6). Les notes PATCH d'une
  piste sans synthé, muettes au rejeu, ne sont plus exportées.
- **Anciens projets** (10h7-10h8) : à l'ouverture d'un projet sans
  canaux, les pistes kit passent sur le canal 10.
- **Cache d'Undo à l'ouverture** (10h9-10h10), un bug préexistant : Ctrl+O
  ne mélange plus les patterns de l'ancien projet dans les instantanés.
- **Interface** (10j1-10k1) : Alt+Shift+E dans la fenêtre principale et
  l'éditeur MIDI, `AppConfig.exports_dir` (dossier `EXPORTS`), nom
  `Pat_NN[_nom].mid`, statut.

**Écarts au plan initial**, tous documentés dans les entrées
d'avancement ci-dessus :
- D5 simplifiée en 10a2, puis révisée en 10h7 ;
- Program Change, noms de slots, volume et pan ajoutés après les écoutes ;
- PATCH muettes omises ;
- `Pat_NN` au lieu de `Pattern_NN` ;
- le pattern live ne porte ni gamme, ni nom, ni BPM : l'export les reçoit
  en paramètres (10h1).

**Données utilisateur corrigées pendant le chantier**, hors dépôt, avec
l'accord de l'utilisateur :
- racine de `PATCHS/DrawbarOrgan.json` passée de C4 à C5 ;
- parties d'orgue transposées de +12 dans `project_01.gvp` et
  `project_03.gvp`.

Cause probable de l'erreur d'octave, à vérifier à part :
`tools/extract_organ_sf2.py` écrit la racine d'après l'`orig_pitch` du SF2
(60, C4), sans tenir compte d'un accordage de zone, alors que l'échantillon
sonne à 523 Hz (C5).

**`docs/SPECS.md` mis à jour** :
- ligne Phase 7 de l'état d'avancement ;
- arborescence : `requirements.txt` ; `src/midi/` avec ses cinq modules,
  corrigeant le retard de la Phase 7 étape 3 relevé en 8h1 ;
  `midi_handler_window.py` ;
- clé `exports_dir` ;
- `gm_program` des slots ;
- `_track_channels` du router et du pattern ;
- prise et Undo ;
- canal par piste ;
- nouvelle section « Export MIDI (Alt+Shift+E) ».

**Laissé hors périmètre, pour la suite** :
- **Conversion des notes des kits non GM** : une table pad → note GM
  d'après le libellé, par exemple Cowbell 49 de la TR-707 vers 56, au lieu
  de la crash 49 en GM. Décidée avec l'utilisateur comme prochaine étape
  séparée.
- Export d'un song ou du projet, tempo variable ; import MIDI.
- Séparation des noms de pistes (F2) et des noms de pads dans
  `voice_manager`.
- Historique d'Undo non vidé par Ctrl+O (10h9).
- Touches 1-9 du Note Repeat ignorées quand le focus est sur la liste des
  patterns (10c1).
- Écart du rejeu sur deux bends au même temps : le rejeu applique la
  valeur la plus haute, l'export et `_bend_state_at` le dernier dans
  `_tape`.
- Banque (CC0/CC32), kits GS non GM2, Undo du choix de slot par Ctrl+T.
- Vérification de `tools/extract_organ_sf2.py`.

---

## Phase 7 étape 11a1 — Conversion des notes des kits non GM à l'export MIDI

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 10 : `11a1`, `11b1`, `11c1`… ; un
commit imprévu inséré après `11b1` s'appelle `11b2`, `11b3`, etc.

### Origine du besoin

Relevé à l'écoute de l'export MIDI (Phase 7 étape 10, § Clôture 10l1). Le
kit TR-707 (`KITS/tr_707.json`) n'est pas rangé selon la table de batterie
GM :
- sa note 49 est « Cowbell », mais en GM c'est Crash Cymbal 1. Dans
  TiMidity, 37 coups de cowbell devenaient une crash très forte ;
- autres écarts : 44 HH Open (GM : Pedal Hi-Hat), 46 Crash (GM : Open
  Hi-Hat), 47 Ride (GM : Low-Mid Tom), 48 Tambourine (GM : Hi-Mid Tom).

L'utilisateur a décidé le 2026-10-21 d'en faire une étape séparée, et a
validé les décisions ci-dessous le 2026-10-23.

### État des lieux constaté en code (2026-10-23, 1945 tests verts)

**Le kit.** Un kit est un JSON de `KITS/` : `name`, `base_note` facultatif,
et `pads[]`, dont chaque entrée porte `pad` (1-16, facultatif), `note`
(facultatif), `filename`, `label` et `mute_group`.
- `gm.json` (GM FluidR3) est déjà rangé selon GM : `base_note` 36, pad N
  → note 35 + N, et 30 entrées sans `pad` pour les notes 35 et 52 à 81.
- `tr_707.json` n'a pas de `base_note`, et retombe donc sur 36. Ses pads
  1 à 15 portent les notes 35 à 49. Le pad 16 (`---`) n'a ni note ni son.

**Le chargement** (`SoundManager.load_kit`, `sound_manager.py:54`) :
- `drum_sounds[i]` est le son de l'entrée `"pad": i + 1` ;
- `note_map` et `note_labels` indexent tous les sons par leur `note` ;
- `kit_base = base_note` (36 par défaut) et `kit_offset = 0`.
- `shift_kit` reconstruit au contraire `drum_sounds[i]` à partir de
  `note_map[kit_base + kit_offset + i]` (`_rebuild_drum_sounds`).
- Il n'y a qu'un `SoundManager`, et donc un seul kit chargé à la fois :
  celui du slot courant (`mw_pads._load_kit_slot`).

**Ce que joue le rejeu.**
- `GRID` sur une piste kit : `play_sound(pad)`, c'est-à-dire
  `drum_sounds[pad]`.
- `KIT` : `play_note(note)`, c'est-à-dire `note_map[note]`. La note est
  celle reçue en MIDI à la capture (`record_kit_note`).

**Ce qu'écrit l'export** (`midi_export.build_pattern_midi`) :
- `GRID` sur une piste kit : `kit_note_base + pad`, avec
  `kit_note_base = kit_base + kit_offset` (`mw_project.py:90`) ;
- `KIT` : la note du payload, telle quelle.

**Bug constaté : la note GRID d'une piste kit ne suit pas le son joué.**
Juste après le chargement, le pad joue le son de son entrée `"pad"`, mais
l'export écrit `kit_base + pad`. Les deux ne coïncident que si les pads
sont rangés en notes consécutives à partir de `base_note`. C'est le cas de
`gm.json`, pas celui de la TR-707 :
- le pad 1, « Kick 2 » (note 35), est écrit 36 ;
- le pad 15, « Cowbell » (note 49), est écrit 50 (High Tom en GM).

Après un `shift_kit`, les deux concordent de nouveau.

**Les noms de batterie GM** (notes 35 à 81) ne sont pas dans
`midi_constants.py`. Le fichier contient `GM_PATCH_NAMES`,
`GM2_DRUMKIT_NAMES` et `guess_gm_program`, dont l'outil `_name_words`
(mots en minuscules, camelCase coupé, chiffres ignorés) peut servir ici.

### Décisions validées (utilisateur, 2026-10-23)

**D1 — la note exportée d'un `GRID` de piste kit est la note du son joué.**
C'est un correctif préalable, sans lequel la conversion partirait d'une
mauvaise note.
- `SoundManager` gagne `pad_notes`, une liste de 16 notes de kit, une par
  pad :
  - à `load_kit`, la `note` de l'entrée du pad, ou `kit_base + i` si
    l'entrée n'en a pas (pad 16 de la TR-707, ancien comportement) ;
  - à `_rebuild_drum_sounds` (`shift_kit`), `kit_base + kit_offset + i` ;
  - à `load_sounds` (pas de kit), `kit_base + i`.
- L'export reçoit `kit_pad_notes` à la place de `kit_note_base`.
- Le rejeu, l'affichage des pads et la correspondance d'une note MIDI
  entrante vers un pad (`midi_handler_window.py:415`) ne changent pas.

**D2 — la note GM d'un son se déduit de son libellé, avec deux
surcharges dans le JSON du kit.** Par ordre de priorité :
1. une clé `"gm_note"` (35-81) dans l'entrée du son ;
2. une clé `"gm": true` au niveau du kit : chaque note est déjà GM et
   reste telle quelle. On l'ajoute à `gm.json` ;
3. sinon, une devinette d'après le `label` (D3) ;
4. sinon, aucune correspondance (D4).

`SoundManager.load_kit` construit `gm_note_map`, un dict
`{note du kit: note GM}`, pour chaque entrée qui porte une `note`. Un pad
sans `note` reçoit son entrée sous la clé `pad_notes[i]`, si elle n'y est
pas déjà.

**D3 — devinette d'après le libellé : `guess_gm_drum_note(label,
kit_note)` dans `midi_constants.py`.**
- Une table `GM_DRUM_NAMES`, de 35 (Acoustic Bass Drum) à 81 (Open
  Triangle), avec les noms de la norme GM 1.
- Les mots du libellé et des noms GM sont normalisés avant comparaison :
  - `hi-hat`, `hi hat`, `hihat` et `hh` deviennent un seul mot `hihat`.
    Sinon, le « hi » de « Hi-Hat » se confondrait avec le « Hi » de
    « Hi Mid Tom » ;
  - puis quelques synonymes : `hi` → `high`, `kick` et `bd` → `bass drum`,
    `rimshot` et `rim` → `side stick`, `clap` → `hand clap`, `tamb` →
    `tambourine`, `med` → `mid`, `sd` → `snare`, `cym` → `cymbal`,
    `cb` → `cowbell`.
  - Les chiffres sont ignorés, comme dans `_name_words`.
- Chaque note GM reçoit un score, comparé dans cet ordre :
  1. le nombre de mots communs avec le libellé ;
  2. un bonus si c'est la note actuelle du son (`kit_note`). Un kit
     partiellement GM garde ainsi ses notes justes, et deux sons proches
     ne se replient pas sur une même note ;
  3. le moins de mots en trop dans le nom GM.
  
  À égalité, la plus petite note l'emporte. Aucun mot commun : `None`.
- Résultat attendu pour la TR-707 (il servira de test) :

  | Note | Libellé | GM | Nom GM |
  |---|---|---|---|
  | 35 | Kick 2 | 35 | Acoustic Bass Drum |
  | 36 | Kick 1 | 36 | Bass Drum 1 |
  | 37 | Rimshot | 37 | Side Stick |
  | 38 | Snare 1 | 38 | Acoustic Snare |
  | 39 | Hand Clap | 39 | Hand Clap |
  | 40 | Snare 2 | 40 | Electric Snare |
  | 41 | Tom Low | 41 | Low Floor Tom |
  | 42 | HH Closed | 42 | Closed Hi-Hat |
  | 43 | Tom Mid | 47 | Low-Mid Tom |
  | 44 | HH Open | 46 | Open Hi-Hat |
  | 45 | Tom Hi | 50 | High Tom |
  | 46 | Crash | 49 | Crash Cymbal 1 |
  | 47 | Ride | 51 | Ride Cymbal 1 |
  | 48 | Tambourine | 54 | Tambourine |
  | 49 | Cowbell | 56 | Cowbell |

  Les toms passent de 41/43/45 à 41/47/50. On garde ainsi l'ordre grave →
  aigu et des notes distinctes.

Alternatives écartées :
- **`gm_note` seule** : pas de devinette, mais un kit sans clé reste non
  converti, et il faudrait annoter chaque kit à la main.
- **Libellé seul** : un libellé ambigu ne pourrait pas être corrigé.

**D4 — un son sans équivalent GM garde sa note, et il est signalé.**
- L'export écrit la note du kit telle quelle.
- `build_pattern_midi` reçoit un paramètre facultatif `unmapped`, un
  `set` qu'il remplit avec les notes de kit écrites sans conversion.
  `export_pattern` le transmet.
- La barre de statut l'annonce après l'export, avec les libellés de
  `note_labels` :
  `Pattern 01 exporté : Pat_01.mid — non converti en GM : Zap (52)`.
  Orca l'annonce comme le reste du statut.

Alternatives écartées : omettre la note (le son disparaît du fichier) ;
une note de repli fixe (un son faux, sans le signaler).

**D5 — conversion à l'export seulement.**
- Sont convertis : les `GRID` d'une piste kit (via `pad_notes`, D1) et
  les `KIT`, sur toute piste, puisque leur note est toujours une note du
  kit.
- Les `PATCH` et les `GRID` d'une piste SYNTH ne sont pas touchés.
- `_tape`, le rejeu, la capture et le `.gvp` ne changent pas : aucune
  migration.
- Le paramètre `kit_gm_map` de `build_pattern_midi` reçoit
  `snd.gm_note_map`. S'il vaut `None`, les notes de kit sont écrites
  telles quelles : c'est utile aux tests existants.

Alternative écartée : stocker les `KIT` en GM dans `_tape`. Le rejeu
changerait et il faudrait migrer les `.gvp`, pour un besoin qui ne
concerne que le fichier exporté.

**D6 — pas d'interface.** On corrige une correspondance en ajoutant
`"gm_note"` dans le JSON du kit. Le format est documenté dans
`docs/SPECS.md`. Un dialogue d'édition pourra faire l'objet d'un chantier
séparé.

### Portée explicitement exclue de ce chantier

- **Plusieurs kits dans un même export** : il n'y a qu'un kit chargé à la
  fois. Toutes les pistes kit sont converties avec la table du kit du slot
  courant, comme `kit_note_base` aujourd'hui. Il faudra y revenir quand
  chaque slot gardera son kit chargé (mode Rack GM).
- La conversion pour un futur MIDI out, ou au rejeu.
- Un dialogue d'édition de la correspondance (D6).
- La correspondance d'une note MIDI entrante vers un pad
  (`kit_base + kit_offset`), qui ignore elle aussi les entrées `"pad"` :
  à vérifier à part.
- Le programme GM2 du kit (`guess_gm_program`), qui ne change pas.
- Le passage de 16 à 128 pads (chantier futur séparé).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **11a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **11b1** | Implémentation — `GM_DRUM_NAMES`, normalisation et `guess_gm_drum_note` (D3). | `midi/midi_constants.py` |
| **11c1** | Tests — table GM 35-81 ; normalisation (hi-hat, hh, synonymes) ; tableau TR-707 de D3 ; bonus de la note actuelle ; égalités ; libellé inconnu → `None`. | `tests/test_midi_constants.py` |
| **11d1** | Implémentation — `pad_notes` (D1) et `gm_note_map` (D2) dans `SoundManager` ; `"gm": true` ajouté à `KITS/gm.json`, hors dépôt, avec l'accord de l'utilisateur. | `sound_manager.py` |
| **11e1** | Tests — `pad_notes` après `load_kit` (entrée `pad` avec ou sans `note`), après `shift_kit` et après `load_sounds` ; `gm_note_map` : `gm_note` prioritaire, `"gm": true` = identité, devinette, absence. JSON de test dans `tmp_path`. | `tests/test_sound_manager.py` |
| **11f1** | Implémentation — export : `kit_pad_notes` remplace `kit_note_base`, `kit_gm_map`, `unmapped` (D1, D4, D5) ; paramètres et statut dans `mw_project`. | `midi/midi_export.py`, `ui/mw_project.py` |
| **11g1** | Tests — GRID kit avec pads non consécutifs (bug de D1) ; KIT et GRID convertis ; PATCH et GRID synth intacts ; `kit_gm_map=None` ; `unmapped` rempli ; message de statut. Mise à jour des tests qui passent `kit_note_base`. | `tests/test_midi_export.py`, `tests/test_midi_export_ui.py`, `tests/test_midi_export_mix.py` |
| **11h1** | Doc — clôture (DESIGN.md ; `docs/SPECS.md` : clés `gm` et `gm_note` du JSON de kit, conversion à l'export), `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- 11f1 change la signature de `build_pattern_midi` : si `pytest` est rouge
  à ce commit, le titre le dira, et 11g1 réparera les tests.
- Avant de committer 11f1 : on exporte un pattern TR-707 et on l'écoute
  dans TiMidity. Le cowbell doit sonner cowbell, et le HH Open doit être
  une charleston ouverte.

### Avancement et écarts constatés

- **11b1** — conforme à D3. `GM_DRUM_NAMES` (47 noms, notes 35 à 81),
  `GM_DRUM_FIRST` et `GM_DRUM_LAST`, `_drum_words` (fusion hi-hat → `hihat`,
  puis synonymes) et `guess_gm_drum_note(label, kit_note=None)` dans
  `midi_constants.py`. Contrôle à la main : le tableau TR-707 de D3 est
  retrouvé note pour note. `---` et un libellé inconnu donnent `None`.
- **11c1** — tests dans `tests/test_midi_constants.py` (49 nouveaux,
  1994 tests verts) :
  - la table GM 35-81 ;
  - la normalisation (variantes de hi-hat, « Hi » → high, synonymes,
    chiffres, camelCase) ;
  - le tableau TR-707 de D3, avec des notes toutes distinctes ;
  - les 47 noms GM, qui retombent chacun sur leur propre note ;
  - le bonus de la note actuelle, les égalités, les mots en trop ;
  - les libellés inconnus, qui donnent `None`.
- **11d1** — conforme à D1 et D2. `SoundManager.pad_notes` (16 notes) et
  `gm_note_map`, construits par `load_kit` et réinitialisés par
  `load_sounds`. `_rebuild_drum_sounds` (`shift_kit`) met `pad_notes` à
  jour. La règle de D2 est dans `_entry_gm_note` : un `gm_note` hors 35-81
  ou non entier est ignoré, et la règle suivante s'applique.
  - Contrôle sur les vrais kits :
    - TR-707 : `pad_notes` = 35…49, puis 51 pour le pad 16 sans note
      (`kit_base + 15`, sans correspondance). La table GM est celle de D3.
    - `gm.json` : identité sur les 47 notes, et ce **même sans**
      `"gm": true`, puisque ses libellés reprennent les noms GM.
  - **Écart sur l'emplacement de `"gm": true`**, choisi par l'utilisateur.
    La clé est ajoutée à `data/kits/gm.json`, la copie déjà versionnée,
    synchronisée en Phase 5 étape 4d (`dbda7d5`). Le fichier est ensuite
    recopié dans `/home/com/groovybox/KITS/gm.json`, hors dépôt, le kit
    réellement chargé.
- **11e1** — 19 tests dans `tests/test_sound_manager.py` (2013 tests
  verts), sur des kits JSON écrits dans `tmp_path` :
  - `pad_notes` avant tout kit, d'après les entrées `pad` (TR-707), pour
    un pad sans note ou sans entrée, après `shift_kit` et après
    `load_sounds` ;
  - `gm_note_map` :
    - devinée d'après les libellés (tableau D3) ;
    - libellé inconnu absent ;
    - `gm_note` prioritaire, y compris sur `"gm": true` ;
    - `gm_note` invalide ignoré ;
    - `"gm": true` donne l'identité, mais `"yes"` ou `1` ne valent pas
      `true` ;
    - note sans fichier son ;
    - pad sans note ;
    - remise à zéro entre deux kits ;
  - `data/kits/gm.json` donne l'identité sur 35-81.
  
  **Constaté en passant, déjà présent et hors périmètre** : `load_kit`
  remplace `media_lst` par les chemins du kit, `''` compris pour un pad
  sans fichier. Un `load_sounds` appelé ensuite lève donc
  `LibsndfileError`. L'appli n'appelle `load_sounds` qu'en repli, quand le
  kit n'a pas pu être chargé : le cas ne se produit donc pas. Le test
  remet `media_lst` avant d'appeler `load_sounds`.
- **11f1** — conforme à D1, D4 et D5.
  - Dans `build_pattern_midi`, `kit_pad_notes` remplace `kit_note_base`.
    S'y ajoutent `kit_gm_map=None` et `unmapped=None`, et une fonction
    locale `kit_note` qui convertit les `GRID` des pistes kit et les `KIT`.
  - `mw_project` passe `snd.pad_notes` et `snd.gm_note_map`, puis ajoute
    au statut `— non converti en GM : <libellé> (<note>)`. Le libellé vient
    de `note_labels`, ou vaut `Note N` à défaut.
  - **`pytest` rouge à ce commit** : 34 tests passent encore
    `kit_note_base` (`test_midi_export*.py`, `test_gm_program.py`) ; ils
    sont réparés en 11g1.
  - **Écoute** (utilisateur, TiMidity et mpv) : la TR-707 exportée depuis
    l'appli est bien convertie.
    - Les 37 coups « crash » relevés en 10l1 n'étaient pas des cowbells,
      mais le pad 14, Tambourine. L'ancien export les écrivait
      `36 + 13 = 49` : c'était le bug D1. Ils sortent maintenant en 54.
    - Le sentiment que « tous les instruments sont des pianos » ne venait
      pas du fichier. `timidity -idvvv` confirme les Program Change 24
      (Nylon String Guitar) et 16 (DrawbarOrgan). L'écart venait des
      volumes relatifs et de la reverb et du chorus de TiMidity : un rendu
      sans effets (`-EFreverb=d -EFchorus=d`) a été jugé plus fidèle à
      l'appli.
  - **Pour un chantier séparé**, décidé avec l'utilisateur :
    - trouver une proportion acceptable entre les volumes de l'appli et
      ceux d'un lecteur GM, puisque l'équilibre entre instruments diffère
      nettement ;
    - jouer sec à l'export, par CC91 et CC93 à 0 au tick 0, ou par un
      réglage de TiMidity.
- **11g1** — `pytest` de nouveau vert, 2025 tests.
  - Adaptation : `kit_note_base=36` devient
    `kit_pad_notes=list(range(36, 52))`, de même sens, dans
    `test_midi_export.py`, `test_midi_export_mix.py` et
    `test_gm_program.py`. `_build` gagne `pad_notes`, `gm_map` et
    `unmapped`.
  - 10 nouveaux tests d'export :
    - le bug D1 : le pad 14 est écrit 48, et non plus 49 ;
    - GRID kit et KIT convertis, le KIT aussi sur une piste synthé ;
    - PATCH et GRID synthé intacts ;
    - `kit_gm_map=None` ;
    - `unmapped` rempli sans doublon, ou `None` ;
    - PATCH omis sur une piste kit, et non signalé ;
    - le chevauchement s'applique après la conversion ;
    - `export_pattern` transmet `unmapped`.
  - Interface : les paramètres `kit_pad_notes` et `kit_gm_map` sont des
    copies. La note du kit est convertie dans le fichier. Le statut liste
    les sons non convertis, y compris dans le statut de l'éditeur MIDI.
  - Constaté : un son sans libellé s'affiche `Note 90 (90)`, avec la note
    en double. Le test fige le comportement de 11f1. Un correctif pour
    afficher `Note 90` reste possible, avec l'accord de l'utilisateur.

### Clôture (11h1)

**11a1-11g1 FAITS** (commits `d3c8db5`..`8290b76`, 7 commits, plus ce
commit de clôture ; 2025 tests verts) : **chantier Phase 7 étape 11
complet**. À l'export MIDI, les notes d'un kit non GM sont écrites avec
leur équivalent GM.

**Ce que le chantier a livré** :
- **Correctif préalable** (D1, 11d1, 11f1) : la note GRID d'une piste kit
  est la note du son réellement joué par le pad (`SoundManager.pad_notes`),
  et non plus `kit_base + pad`. Sur la TR-707, tout était décalé d'une
  note : les 37 coups « crash » de 10l1 étaient des coups de Tambourine
  (pad 14).
- **Noms GM et devinette** (11b1, 11c1) : `GM_DRUM_NAMES` (35-81) et
  `guess_gm_drum_note` dans `midi_constants.py`. Les mots sont normalisés
  (hi-hat, synonymes), puis comparés par un score : mots communs, note
  actuelle, mots en trop. La TR-707 est convertie note pour note selon le
  tableau D3, et les 47 noms GM sont des points fixes.
- **Correspondance du kit** (11d1, 11e1) : `SoundManager.gm_note_map`.
  Ordre de priorité : `gm_note`, puis `"gm": true`, puis la devinette.
  `"gm": true` est ajouté à `data/kits/gm.json` et recopié dans
  `KITS/gm.json`, hors dépôt.
- **Export** (11f1, 11g1) : `kit_pad_notes`, `kit_gm_map` et `unmapped`
  dans `build_pattern_midi`. Les GRID kit et les KIT sont convertis, les
  PATCH et les GRID synthé ne le sont pas. Un son sans correspondance garde
  sa note et est listé au statut.

**Écarts au plan** :
- `"gm": true` est mis dans la copie versionnée `data/kits/gm.json`, à la
  demande de l'utilisateur, puis recopié dans `KITS/` ;
- les 34 tests de 11f1 ont été adaptés en 11g1, comme prévu par le plan.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, clés `base_note`, `gm` et
`gm_note` du JSON de kit, sens de `note` (note du kit, pas forcément GM),
`pad_notes` et `gm_note_map` de `SoundManager`, section Export MIDI.

**Laissé hors périmètre, pour la suite** :
- **Volumes et effets à l'export** (écoute 11f1) : trouver un équilibre
  des volumes entre l'appli et un lecteur GM, et jouer sec (CC91 et CC93
  à 0, ou réglage de TiMidity). C'est un chantier séparé.
- Statut `Note 90 (90)` pour un son sans libellé, avec la note en double
  (11g1). Un affichage `Note 90` serait plus court pour Orca.
- Plusieurs kits dans un même export : un seul kit est chargé à la fois.
- La correspondance d'une note MIDI entrante vers un pad
  (`kit_base + kit_offset`), qui ignore elle aussi les entrées `"pad"`.
- `load_sounds` après `load_kit` plante si un pad n'a pas de fichier
  (11e1). Le cas ne se produit pas dans l'appli.
- Un dialogue d'édition de la correspondance GM (D6).
- La conversion pour un futur MIDI out.

---

## Phase 7 étape 12a1 — Courbe de volume GM dans l'appli, vélocité des cases de grille et effets à l'export

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 11 : `12a1`, `12b1`, `12c1`… ; un
commit imprévu inséré après `12b1` s'appelle `12b2`, `12b3`, etc.

### Origine du besoin

Relevé à l'écoute de la Phase 7 étape 11f1. L'utilisateur a exporté
`Pat_01` (guitare, TR-707, orgue, piano) et l'a écouté dans TiMidity
(banque FluidR3 GM) avec mpv :
- l'équilibre entre les instruments diffère nettement de celui de l'appli,
  l'orgue joué en live surtout ;
- un rendu sans reverb ni chorus est plus fidèle à l'appli, qui n'a pas
  d'effets.

Il a demandé un chantier séparé pour « trouver une proportion
acceptable ». Les décisions ci-dessous ont été validées le 2026-10-23.

### État des lieux constaté (2026-10-23, 2025 tests verts)

**Mesure de TiMidity** (rendu sec, note 60, RMS sur 0,4 s ; script jetable
du scratchpad, non versionné) :

| Valeur | 127 | 100 | 77 | 64 | 48 | 32 |
|---|---|---|---|---|---|---|
| Appli, linéaire : `20·log10(v/127)` | 0 dB | −2,1 | −4,3 | −6,0 | −8,5 | −12,0 |
| TiMidity, vélocité (orgue 16) | 0 dB | −4,1 | −8,4 | −11,4 | −15,5 | −21,4 |
| TiMidity, vélocité (piano 0, guitare 24) | 0 dB | −3,4 | −7,2 | −9,9 | −14,0 | −19,9 |
| TiMidity, CC7 (orgue) | 0 dB | −3,4 | — | −9,9 | — | −19,9 |

TiMidity suit la courbe GM habituelle, en carré, soit `40·log10(v/127)` :
deux fois plus de dB que l'appli, qui est linéaire. L'orgue de `Pat_01`,
joué en live avec des vélocités de 29 à 77, perd de 8 à 23 dB dans
TiMidity, contre 4 à 13 dB dans l'appli. C'est pourquoi l'utilisateur
voulait baisser tous les instruments sauf l'orgue.

**Calcul du gain dans l'appli** : un facteur linéaire dans [0, 1], produit
de facteurs bornés :
- **case de grille** (rejeu `dp_playback._dispatch_event`, jeu live
  `dp_live.play_sound`, pads MIDI `midi_handler_window.py:365` et `:403`) :
  `min(1, volume du pad/100 · vel/100)`, puis `× volume de piste/100`
  (`TrackRouter.on_play`).
  - L'échelle est **/100** : la vélocité 100 par défaut du Numpad et de la
    grille joue au maximum, et une vélocité au-delà de 100 est écrêtée.
- **KIT et PATCH** (`TrackRouter.on_kit_tape`, `on_patch_tape`) :
  `min(1, volume de piste/100 · vel/127)`.
- **jeu live d'un synthé** (`midi_handler_window.py:310`, `:335`) et
  pré-écoute de l'éditeur MIDI (`mew_playback.py:80`) : `vel/127`.
- **Note Repeat et Numpad en mode Keyboard** : volume du pad / 100.
- Ce facteur arrive au driver par trois points d'entrée seulement :
  `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play`.
- Le métronome et la pré-écoute d'un son (`preview_sound`) appellent le
  driver sans facteur. Le volume général (`set_master_volume`) s'applique
  au mixage, à part.

**Ce qu'écrit l'export** :
- la vélocité du payload, pour tous les etypes ;
- CC7 = `volume de piste · 127/100` ;
- le volume des pads n'est pas exporté.

Une case de grille par défaut (vel 100, pad à 100) joue donc au maximum
dans l'appli, mais sort à −4 dB dans TiMidity.

**Effets dans TiMidity** (écart RMS avec le rendu sec de `Pat_01`) :
- rendu par défaut : −6,7 dB ;
- CC91 = 0 et CC93 = 0 écrits au tick 0 de chaque piste : −7,0 dB, donc
  **aucun effet**. La reverb et le chorus viennent des réglages
  d'instrument de la banque FluidR3 ;
- seules les options `-EFreverb=d -EFchorus=d` rendent sec, et un fichier
  `~/.timidity.cfg` contenant `opt EFreverb=d` et `opt EFchorus=d` donne
  le même résultat (écart nul), **sans sudo**.

### Décisions validées (utilisateur, 2026-10-23)

**D1 — l'appli passe à la courbe GM : gain = facteur².**
- Le facteur linéaire calculé partout aujourd'hui (vélocité × volume du
  pad × volume de piste, borné à [0, 1]) est élevé au carré en un seul
  endroit, juste avant le driver, aux trois points d'entrée :
  `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play`.
- Comme `(a·b·c)² = a²·b²·c²`, c'est exactement la courbe GM appliquée à
  chaque facteur : la vélocité comme `40·log10(v/127)`, et le volume de
  piste comme un CC7.
- Une fonction `gm_gain(factor)` dans `midi_constants.py` borne le facteur
  à [0, 1] et le met au carré. On n'a pas à toucher la dizaine d'endroits
  qui calculent le facteur.
- Ne changent pas :
  - le métronome et `preview_sound`, qui n'ont pas de facteur ;
  - le volume général, qui reste linéaire : c'est un réglage d'écoute, non
    exporté ;
  - l'échelle /100 des cases de grille (vel 100 = maximum) ;
  - le pan.
- **Effet accepté** : les projets existants sonnent autrement. Une note
  douce ou une piste baissée l'est deux fois plus en dB qu'avant. Par
  exemple, vel 64 passe de −6 à −12 dB, et une piste à 45 de −7 à −14 dB.
  Les notes à 127 et les cases de grille par défaut ne bougent pas.

Alternatives écartées :
- **Compenser à l'export** (vélocité = 127·√gain) : l'appli resterait
  non standard, et l'import devrait appliquer l'inverse.
- **Ne rien changer.**

**D2 — la vélocité exportée d'une case de grille reflète le gain joué.**
- `vel_out = round(127 · min(1, vel/100 · volume du pad/100))`, borné à
  1..127.
  - C'est le facteur du rejeu (`dp_playback`), ramené à l'échelle MIDI.
  - Avec D1, un lecteur GM rend alors `(vel_out/127)²`, le gain de
    l'appli, au volume de piste près, déjà porté par CC7.
  - Une case par défaut (vel 100, pad à 100) sort à 127. Une case à vel
    100 sur un pad à 50 sort à 64.
- `build_pattern_midi` reçoit `pad_volumes`, les 16 volumes du
  `VoiceManager`. S'il vaut `None`, le volume du pad compte pour 100.
  `mw_project` le passe.
- KIT et PATCH : la vélocité du payload est inchangée. Elle est déjà sur
  l'échelle /127, et D1 rend le gain de l'appli identique à celui d'un
  lecteur GM.
- CC7 est inchangé : `volume · 127/100`, que D1 rend fidèle.

Alternatives écartées : prendre la vélocité seule sans le volume du pad,
ou garder la vélocité brute.

**D3 — les effets.**
- **À l'export** : CC91 (reverb) et CC93 (chorus) à 0 au tick 0 de chaque
  piste, après le volume et le pan. Ce sont les rangs négatifs du tick 0,
  comme CC7 et CC10 : un CC91 ou un CC93 capturé dans `_tape` au tick 0
  passe après et l'emporte.
  - Sans effet mesurable dans TiMidity, mais c'est la valeur juste pour
    un lecteur GM ou un DAW qui respecte ces CC (GM2 suppose 40 par
    défaut pour CC91).
- **Pour l'écoute dans TiMidity** : un fichier `/home/sam/.timidity.cfg`,
  hors dépôt, avec `opt EFreverb=d` et `opt EFchorus=d`.
  - Il remplace l'option `/etc/timidity/timidity.cfg` proposée lors des
    questions, qui demandait sudo.
  - Il est écrit avec l'accord de l'utilisateur, à l'étape de clôture.
  - Il agit sur toute écoute TiMidity de l'utilisateur, mpv compris s'il
    passe par TiMidity.

### Portée explicitement exclue de ce chantier

- **Écarts de niveau propres à chaque instrument**, entre un échantillon
  de l'appli et un preset FluidR3 : un réglage de gain GM par slot ne sera
  envisagé qu'après l'écoute de ce chantier, si l'équilibre reste
  insatisfaisant.
- Le volume général : il reste linéaire et n'est pas exporté.
- Le volume des pads pour les KIT et les PATCH : il ne s'applique pas au
  rejeu, donc rien à exporter.
- Le pan, ainsi que le volume (CC7) et le pan (CC10) capturés dans
  `_tape`, qui gardent leur conversion.
- Un réglage de la courbe (linéaire ou GM) dans l'interface.
- Le statut `Note 90 (90)` et les autres restes de la Phase 7 étape 11.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **12b1** | Implémentation — `gm_gain` ; courbe GM aux trois points d'entrée (D1). | `midi/midi_constants.py`, `sound_manager.py`, `synth_engine.py` |
| **12c1** | Tests — `gm_gain` (bornes, carré) ; `play_sound`, `play_note` et `SynthEngine.play` transmettent le facteur au carré au driver (driver factice) ; métronome et `preview_sound` inchangés. Mise à jour des tests qui vérifient le facteur transmis au driver, s'il y en a. | `tests/test_midi_constants.py`, `tests/test_sound_manager.py`, `tests/test_synth_engine*.py` |
| **12d1** | Implémentation — export : vélocité des cases de grille avec le volume du pad (D2, `pad_volumes`), CC91 et CC93 à 0 au tick 0 (D3) ; `mw_project` passe les volumes des pads. | `midi/midi_export.py`, `ui/mw_project.py` |
| **12e1** | Tests — vélocité de grille (défaut 127, pad à 50, écrêtage, `pad_volumes=None`, synthé et kit) ; KIT et PATCH inchangés ; CC91 et CC93 à 0 dans l'ordre du tick 0, battus par un CC capturé au tick 0 ; paramètres de l'interface. Mise à jour des tests qui figent les messages du tick 0 ou une vélocité de grille. | `tests/test_midi_export.py`, `tests/test_midi_export_mix.py`, `tests/test_midi_export_ui.py` |
| **12f1** | Doc — clôture (DESIGN.md ; `docs/SPECS.md` : courbe de volume, export), `~/.timidity.cfg` avec l'accord de l'utilisateur, `pytest tests/` complet vert, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 12b1 : l'utilisateur écoute un projet dans l'appli.
  Les notes douces et les pistes baissées doivent sonner plus bas, et les
  notes fortes ne pas changer.
- Avant de committer 12d1 : on exporte `Pat_01`, et l'utilisateur compare
  l'appli et TiMidity sec. Si l'équilibre reste insatisfaisant, on
  mesurera les écarts propres à chaque instrument (portée exclue).
- 12d1 change les messages du tick 0 et les vélocités de grille : si
  `pytest` est rouge à ce commit, le titre le dira, et 12e1 réparera les
  tests.

### Avancement et écarts constatés

- **12b1** — conforme à D1. `gm_gain(factor)` (borné à [0, 1], au carré)
  dans `midi_constants.py`. Il est appliqué au facteur transmis au driver
  dans `SoundManager.play_sound`, `SoundManager.play_note` et
  `SynthEngine.play` ; `midi_constants` y est importé en tête.
  - 2025 tests verts : aucun test existant ne vérifiait le facteur transmis
    au driver.
  - Écoute validée par l'utilisateur dans l'appli.
- **12c1** — 22 tests, 2047 verts :
  - `gm_gain` (`test_midi_constants.py`) : carré, bornes, double des dB
    (vel 64 ≈ −12 dB), entier accepté ;
  - `SoundManager` (`test_sound_manager.py`, driver qui enregistre les
    appels) : `play_sound` et `play_note` transmettent le facteur au carré
    avec le pan inchangé ; 1.0 par défaut ; un facteur au-delà de 1 est
    borné ; le métronome est appelé sans facteur ;
  - `SynthEngine.play` (`test_synth_engine.py`, moteur factice) : facteur
    au carré, pan, `phase_incr` et `lfo_depth` inchangés ; défaut et borne ;
    pas d'appel au driver sans son.
  
  **Constaté en passant, déjà présent et hors périmètre** :
  `SoundManager.preview_sound` n'a aucun appelant dans `src/`, et il est
  cassé. Il indexe la liste `drum_sounds` par un objet son, un reste de
  l'époque où c'était un dict, et lève donc `TypeError`. Il n'est pas testé
  ici. C'est du code mort, à supprimer ou à réparer à part.
- **12d1** — conforme à D2 et D3.
  - `grid_velocity(vel, pad_volume)` dans `midi_export.py`, et paramètre
    `pad_volumes` (les volumes de `VoiceManager`, passés par
    `mw_project`).
  - CC91 et CC93 à 0 au tick 0, de rangs −2 et −1. Le volume et le pan
    passent aux rangs −4 et −3.
  - **`pytest` rouge à ce commit** : 6 tests figent les messages du tick 0
    (`test_midi_export.py`, `test_midi_export_mix.py`) ; ils sont adaptés
    en 12e1.
  - **Écoute** (utilisateur, 2026-10-23, `Pat_01`, volumes de toutes les
    pistes baissés sauf l'orgue) :
    - **l'orgue sonne une octave plus bas dans TiMidity.** Ce n'est pas
      l'export : le fichier porte les notes 67 à 81. C'est le preset
      FluidR3 « Drawbar Organ ». Spectre de la note 72, identique dans
      FluidSynth et dans TiMidity : 262 Hz à 0 dB, 130 Hz à −2 dB et
      524 Hz à −7 dB. L'échantillon de l'appli, lui, sonne à 524 Hz.
    - **Les échantillons de l'appli sont normalisés** : écart RMS (appli
      moins TiMidity, vélocité 127, sans effets) de +5,7 dB pour la
      guitare (programme 24), **+17,0 dB pour le piano** (programme 0) et
      +3,1 dB pour l'orgue (programme 16). Aucune courbe globale ne peut
      corriger un écart propre à chaque instrument : voir l'avenant 12a2.
    - **Bug trouvé, déjà présent et hors export** : les changements de
      volume et de pan faits par Alt+flèches, Alt+0, les CC7 et CC10 du
      contrôleur et les SpinCtrl des pads n'entrent pas dans l'Undo et ne
      marquent pas le projet modifié. À la fermeture, rien n'est proposé à
      la sauvegarde (`project_03.gvp` a encore tous ses volumes à 100).
      L'utilisateur a décidé d'en faire un chantier séparé, après
      celui-ci.

### Phase 7 étape 12a2 — Avenant : transposition et gain GM par slot

**Origine.** L'écoute de 12d1 a montré deux écarts propres à chaque
instrument, qu'aucune courbe globale ne corrige :
- le preset FluidR3 « Drawbar Organ » sonne une octave sous la note
  écrite (spectre en 12d1) ;
- les échantillons de l'appli sont normalisés, « fortement » pour l'orgue
  selon l'utilisateur. L'écart RMS entre l'appli et TiMidity va de
  +3,1 dB (orgue) à +17,0 dB (piano).

Le 2026-10-24, l'utilisateur a choisi des réglages GM par slot, qui ne
touchent que l'export, comme le programme GM (Phase 7 étape 10h3).

**D4 — transposition GM d'un slot synthé.**
- `slot.config["gm_transpose"]`, un entier de −24 à +24 demi-tons,
  0 par défaut. Accesseurs `Slot.gm_transpose()` et
  `set_gm_transpose(n)`, sur le modèle de `gm_program()` et
  `set_gm_program()`. `config` est remplacé, jamais modifié en place, à
  cause des instantanés d'Undo.
- Appliquée à l'export aux notes `PATCH` et aux `GRID` d'une piste dont le
  slot est un synthé, après le calcul de la note et avant la borne
  0..127.
- Sans effet sur un slot kit, dont les notes passent par la table GM de la
  Phase 7 étape 11, ni sur les `KIT`.
- Exemple : l'orgue à +12. Ses notes 67 à 81 sont écrites 79 à 93, et le
  preset sonne alors à la hauteur de l'appli.

**D5 — gain GM d'un slot, en dB, appliqué au CC7 du fichier.**
- `slot.config["gm_gain_db"]`, un entier de −40 à 0 dB, 0 par défaut.
  Accesseurs `Slot.gm_gain_db()` et `set_gm_gain_db(db)`.
- Il vaut pour tout slot non vide, kit compris.
- À l'export, tout CC7 de la piste est multiplié par `10^(dB/40)`, puis
  arrondi et borné à 0..127. Cela vaut pour le CC7 du tick 0 (volume de
  piste) comme pour un CC7 capturé dans `_tape`. Avec la courbe GM d'un
  lecteur (`40·log10`), c'est exactement le gain voulu en dB.
- Le gain est négatif ou nul, car CC7 plafonne à 127 : pour équilibrer, on
  baisse les instruments trop forts plutôt que de monter les autres.
- Ordre de grandeur, d'après les mesures de 12d1 : pour retrouver dans
  TiMidity l'équilibre de l'appli, il faudrait l'orgue vers −14 dB et la
  guitare vers −11 dB, le piano restant à 0. Ce n'est qu'un point de
  départ : l'utilisateur règle à l'oreille.

**D6 — réglage dans `TrackPropertiesDialog`.**
- Deux `SpinCtrl` après « Programme GM du slot » : « Transposition GM du
  slot (demi-tons) » et « Gain GM du slot (dB) ». Un `SpinCtrl` est
  annoncé en temps réel par Orca.
  - Ordre Tab : Mute → Solo → Slots → Canal → Programme → Transposition →
    Gain → Volume → Pan.
  - La transposition est grisée si le slot n'est pas un synthé, le gain si
    le slot est vide. Changer de slot dans le dialogue recharge les deux
    valeurs, comme le programme.
- Même aperçu, même Annuler et même Undo que le programme :
  `saved_configs` garde la `config` d'origine de chaque slot touché.
- Le réglage appartient au slot : toutes les pistes qui jouent ce slot le
  partagent, comme le programme GM.

**Paramètres d'export.** `build_pattern_midi` reçoit `track_transposes` et
`track_gain_db`, une valeur par piste, lue sur le slot de la piste.
`None` signifie 0. `mw_project._midi_export_params` les remplit depuis le
Rack.

**Exclu de l'avenant** :
- une mesure automatique des écarts : elle dépend de la banque du lecteur ;
- une transposition des kits ;
- un gain positif.

**Découpage révisé** (12a1 à 12d1 inchangés) :

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12e1** | Tests — comme prévu en 12a1 (vélocité de grille, CC91 et CC93, adaptation des 6 tests). | `tests/test_midi_export*.py` |
| **12f1** | Implémentation — `gm_transpose` et `gm_gain_db` du slot (D4, D5) ; export : `track_transposes`, `track_gain_db` ; `mw_project`. | `rack.py`, `midi/midi_export.py`, `ui/mw_project.py` |
| **12g1** | Tests — accesseurs, bornes, `config` remplacé ; transposition des PATCH et des GRID synthé, kit et KIT intacts, borne 0..127 ; gain sur le CC7 du tick 0 et sur un CC7 capturé, arrondi, borne, `None` ; paramètres de l'interface. | `tests/test_rack*.py`, `tests/test_midi_export_mix.py`, `tests/test_midi_export_ui.py` |
| **12h1** | Implémentation — deux `SpinCtrl` dans `TrackPropertiesDialog` (D6), aperçu, Annuler, Undo. | `ui/dialogs_properties.py`, `ui/mw_tracks.py` |
| **12i1** | Tests — valeurs initiales, grisage selon le slot, rechargement au changement de slot, aperçu, Annuler qui rend la `config`, Undo, ordre Tab. | `tests/test_track_properties_dialog.py` |
| **12j1** | Doc — clôture (ex-12f1) : DESIGN.md, `docs/SPECS.md`, `~/.timidity.cfg` avec l'accord de l'utilisateur, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 12h1 : l'utilisateur règle l'orgue à +12 et les
  gains à l'oreille, exporte `Pat_01`, puis compare l'appli et TiMidity
  sec.
- **Chantier suivant**, décidé avec l'utilisateur : l'Undo et le marquage
  « projet modifié » des changements de volume et de pan (Alt+flèches,
  Alt+0, CC7 et CC10 du contrôleur, SpinCtrl des pads), vus en 12d1.
- **12e1** — `pytest` de nouveau vert, 2065 tests (3 passages de suite).
  - **Adaptation des 6 tests** : CC91 et CC93 attendus après CC7 et CC10
    dans les messages du tick 0. « `None` = rien d'écrit » ne vaut plus que
    pour CC7 et CC10. Le test CC/PGM/bend écarte les CC91 et CC93 du
    tick 0.
  - **Nouveaux tests** :
    - `grid_velocity` sur 9 cas, dont défaut 127, pad à 50 → 64, écrêtage
      au-delà de 100 et jamais 0 ;
    - cases de grille synthé et kit avec le volume du pad ;
    - `pad_volumes=None` ;
    - KIT et PATCH inchangés ;
    - CC91 et CC93 à 0 sur chaque piste et son canal, après le volume et
      le pan, seulement au tick 0 ;
    - un CC91 capturé au tick 0 passe après et l'emporte ;
    - les paramètres et le fichier de l'interface (pad à 50 → 64).
  - **Échec intermittent**, vu une seule fois sur 11 passages complets, et
    non reproduit : le test n'a pas pu être identifié (sortie non
    capturée). À surveiller ; voir la fragilité connue des tests
    `wx.CallAfter` sur la suite complète.
- **12f1** — conforme à D4 et D5, avec des bornes plus strictes que
  prévu.
  - `InstrumentSlot.gm_transpose()` et `set_gm_transpose()`,
    `gm_gain_db()` et `set_gm_gain_db()`, ainsi que les constantes
    `GM_TRANSPOSE_MIN/MAX` (±24) et `GM_GAIN_DB_MIN/MAX` (−40..0).
  - Un helper `_config_int` lit la valeur de `config`. Une valeur hors
    bornes y est **ramenée dans les bornes**, alors qu'une valeur non
    entière ou booléenne compte pour 0.
  - Les setters bornent la valeur et remplacent `config`.
  - Export :
    - `apply_gain_db(cc7, db)` vaut `CC7 · 10^(dB/40)`, borné ;
    - `track_transposes` s'ajoute à la note PATCH et à la note GRID d'une
      piste synthé ;
    - `track_gain_db` atténue le CC7 du tick 0 et tout CC7 de `_tape` ;
    - `mw_project` les remplit depuis le Rack.
  - 2065 tests verts : avec des réglages à 0, l'export est inchangé.
  - Essai : un orgue à +12 et −14 dB écrit la note 67 en 79 ; le CC7 passe
    de 127 à 57 au tick 0, et un CC7 capturé de 100 à 45.

### Phase 7 étape 12a3 — Avenant : l'export suit le mute et le solo du rejeu

**Origine.** Le 2026-10-24, l'utilisateur a exporté en ne gardant que la
TR-707 et l'orgue, les autres pistes étant mutées. Les pistes mutées ont
quand même été exportées. Le plan 10a1 les ignorait volontairement (§
Portée exclue : « Mute et solo sont ignorés »). L'utilisateur revient sur
ce choix : ce qui ne s'entend pas au rejeu ne doit pas être exporté.

Lors du même essai, l'orgue ne semblait pas transposé. C'est attendu : la
transposition GM n'a pas encore d'interface, qui arrive en 12h1. Aucun
projet ne porte `gm_transpose`, qui vaut donc 0.

**D7 — mêmes règles qu'au rejeu (validé par l'utilisateur).**
- **Pistes** : la règle est celle de `TrackRouter._track_is_audible`. Une
  piste mutée est omise. S'il y a au moins un solo, seules les pistes en
  solo sont gardées, et le mute l'emporte sur le solo.
  - Une piste omise n'a **aucune piste SMF**, comme une piste vide : ni
    notes, ni CC, ni Program Change. Au rejeu, `TrackRouter` coupe aussi
    ses CC et son bend.
- **Pads** : la règle est celle de `VoiceManager.is_audible`. Les cases de
  grille d'un pad muet, ou hors du solo des pads, sont omises sur toutes
  les pistes, comme dans `DrumPlayer._dispatch_event`.
  - Les `KIT` et les `PATCH` ne dépendent pas des pads, comme au rejeu.
  - Une piste dont il ne reste que des cases de pads muets garde sa piste
    SMF, sans note, comme une piste kit qui n'a que des `PATCH` (10h5).
- **Paramètres** : `build_pattern_midi` reçoit `track_audible` et
  `pad_audible`, des listes de booléens. `None` signifie que tout est
  audible. `mw_project` les remplit depuis le router et le
  `VoiceManager`.

**Découpage** : deux commits sont insérés après 12f1, et la suite (12g1 à
12j1) ne change pas.

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a3** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12f2** | Implémentation — `track_audible` et `pad_audible` (D7), paramètres de `mw_project`. | `midi/midi_export.py`, `ui/mw_project.py` |
| **12f3** | Tests — piste mutée omise, solo, mute qui l'emporte sur le solo ; pad muet ou hors solo omis sur une piste synthé et une piste kit ; KIT et PATCH intacts ; `None` ; paramètres de l'interface. | `tests/test_midi_export.py`, `tests/test_midi_export_ui.py` |
- **12f2** — conforme à D7.
  - `track_audible` saute la piste entière avant de construire sa piste
    SMF. `pad_audible` saute les cases de grille du pad.
  - `mw_project` passe `r._track_is_audible(t)` et `vm.is_audible(i)`.
  - 2065 tests verts : aucun test ne mutait de piste ou de pad à l'export.
  - Essai : une piste mutée disparaît ; un solo ne garde que sa piste ; un
    pad muet perd sa case de grille, mais la note KIT de même hauteur
    reste.

**Chantier 12 en pause après 12f2** (2026-10-24) : l'utilisateur fait
passer d'abord la Phase 7 étape 13, l'Undo des réglages de mixage. Le
chantier 12 reprendra à 12f3.

---

## Phase 7 étape 13a1 — Undo et projet modifié pour le mute, le solo et le volume des pistes et des pads

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 12 : `13a1`, `13b1`, `13c1`… ; un
commit imprévu inséré après `13b1` s'appelle `13b2`, `13b3`, etc.

### Origine du besoin

Relevé à l'écoute de la Phase 7 étape 12d1 : les volumes changés dans
l'appli n'entrent pas dans l'Undo et ne marquent pas le projet modifié.
À la fermeture, rien n'est donc proposé à la sauvegarde. Par exemple,
`project_03.gvp` avait encore tous ses volumes à 100 après une séance de
réglage.

Le 2026-10-24, l'utilisateur a demandé de le traiter avant les tests du
chantier 12, en se limitant pour l'instant au **mute, au solo et au volume
des pistes et des pads**. Le pan et le reste viendront dans un chantier
suivant.

### État des lieux constaté en code (2026-10-24, 2065 tests verts)

**L'instantané d'Undo contient déjà ces réglages.** `_capture_state`
range l'état du router dans le pattern courant (`_flush_pattern_to_store` :
`_track_volumes`, `_track_mutes`, `_track_solos`…) et les voix des pads
(`voice_manager.to_list()` : volume, pan, mute, solo, durée).
`_restore_state` les rétablit par `_apply_pattern_from_store`, puis
rafraîchit la grille, les pads et la liste des pistes. Il manque
seulement l'appel à `_add_undo`, qui marque aussi le projet modifié.

**Chemins sans Undo ni marquage**, dans le périmètre :

| Réglage | Chemin | Code |
|---|---|---|
| Mute / solo de piste | X, S, Shift+X, Shift+S sur la liste des pistes | `key_handler_chars.py:123-165` |
| Mute / solo de piste | X, S dans l'éditeur MIDI, sur les pistes sélectionnées | `mew_playback._toggle_track_mute/_solo` |
| Mute / solo de pad | X, S, Shift+X, Shift+S hors liste des pistes | `key_handler_chars.py` |
| Mute / solo de pad | Boutons Mute et Solo | `mw_pads._on_mute_btn`, `_on_solo_btn` |
| Volume de piste | Alt+↑/↓ sur la liste des pistes | `key_handler_alt.py:16-40` |
| Volume de piste | CC7 du contrôleur, liste des pistes focalisée | `midi_handler_window.on_cc` |
| Volume de pad | Alt+↑/↓ hors liste des pistes | `key_handler_alt.py` |
| Volume de pad | SpinCtrl Volume du pad | `mw_pads._on_vol_spin` |
| Volume de pad | CC7 du contrôleur, ailleurs que la liste des pistes | `midi_handler_window.on_cc` |
| Tout le pad | Dialogue de propriétés du pad : il a un Annuler, mais pas d'Undo | `mw_pads._pad_properties_dialog` |

Seul `TrackPropertiesDialog` fait déjà les choses correctement : un Undo
avant le dialogue, retiré si Annuler ou si rien n'a changé, et l'état
« modifié » rétabli (Phase 7 étape 10f1).

**Avec une prise ouverte** (`_take_begin`), `_take_end_if_idle` ne retire
l'Undo de la prise que s'il est toujours le dernier. Un réglage fait
pendant la prise, avec sa propre entrée, est donc conservé : il n'y a pas
de cas particulier à traiter.

### Décisions validées (utilisateur, 2026-10-24)

**D1 — un Undo avant chaque changement de mute, de solo ou de volume.**
- Il est pris **avant** le changement : l'instantané garde l'état
  d'avant, comme pour les autres actions.
- `_add_undo` marque le projet modifié : c'est ce qui fera proposer la
  sauvegarde à la fermeture.
- **Rien n'est fait si la valeur ne change pas**, par exemple Alt+↑ sur
  un volume à 100, ou Shift+X quand rien n'est muet. On ne crée alors
  aucune entrée vide, et le projet n'est pas marqué.
- Titres : `Mute piste 3`, `Solo pad 5`, `Démuter toutes les pistes`,
  `Désolo tous les pads`, `Volume piste 3`, `Volume pad 5`,
  `Mute pistes 2, 4` dans l'éditeur, `Propriétés pad 5`.

**D2 — regroupement des changements de volume successifs.**
- Une méthode `_add_mix_undo(title, key)` dans `mw_project.py` : `key`
  identifie le réglage, par exemple `("track_volume", 2)` ou
  `("pad_volume", 4)`.
- Un nouveau changement **n'ajoute pas d'entrée** si :
  - il porte la même `key` que le précédent ;
  - l'entrée créée par ce précédent est toujours la dernière de
    l'historique, donc sans autre action entre les deux ;
  - et il arrive **moins de 1 seconde** après le précédent. La fenêtre
    glisse : chaque changement la relance.

  Le projet est quand même marqué modifié.
- Un tour de bouton rotatif (des dizaines de CC7) ou une rafale d'Alt+↑
  ne donne ainsi qu'une entrée, et un seul Ctrl+Z revient au volume de
  départ.
- Les bascules (X, S, Shift+X, Shift+S, boutons Mute et Solo) passent
  `key=None` : **une entrée par bascule**. Une bascule de plusieurs
  pistes dans l'éditeur ne fait qu'une entrée.
- L'horloge est `time.monotonic()`, injectable pour les tests.

**D3 — dialogue de propriétés du pad** : on reprend le schéma de
`TrackPropertiesDialog`. Un Undo `Propriétés pad N` est pris avant le
dialogue. Il est retiré si on annule ou si rien n'a changé, et l'état
« modifié » d'avant est alors rétabli. Le pan et la durée y passent avec
le reste, puisque le dialogue les règle ensemble.

### Portée explicitement exclue de ce chantier

- **Le pan**, des pistes comme des pads : Alt+←/→, Alt+0, CC10 et
  SpinCtrl Pan. C'est le chantier suivant, à la demande de l'utilisateur,
  avec le reste des réglages sans Undo qu'on trouvera.
- Les CC7 et CC10 enregistrés dans `_tape` pendant une prise : ils sont
  déjà couverts par l'Undo de la prise.
- Le chargement des réglages d'un pattern lors de l'enchaînement du song
  (`mw_songs`) : ce n'est pas une action de l'utilisateur.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **13a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **13b1** | Implémentation — `_add_mix_undo` (D2) ; Undo avant chaque changement du tableau (D1) ; dialogue de propriétés du pad (D3). | `ui/mw_project.py`, `ui/key_handler_chars.py`, `ui/key_handler_alt.py`, `ui/midi_handler_window.py`, `ui/mw_pads.py`, `ui/mew_playback.py` |
| **13c1** | Tests — `_add_mix_undo` : regroupement par clé, fenêtre de 1 s glissante (horloge injectée), autre action entre deux, `key=None`. Chaque chemin du tableau : entrée créée, projet modifié, Ctrl+Z rend la valeur ; valeur inchangée sans entrée ni marquage ; dialogue du pad : Ok, Annuler, inchangé. | `tests/test_mix_undo.py` (nouveau) |
| **13d1** | Doc — clôture (DESIGN.md, `docs/SPECS.md` § Undo), `pytest` complet, mémoire ; reprise du chantier 12 à 12f3. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 13b1 : l'utilisateur essaie dans l'appli. Muter une
  piste, tourner un bouton, puis Ctrl+Z, qui doit rétablir chaque
  réglage, le bouton d'un seul coup. Fermer l'appli doit proposer la
  sauvegarde.

**Reprise du chantier 12** (2026-10-24) : l'utilisateur revient sur la
pause. Le chantier 12 continue dès 12f3. Le chantier 13, dont le plan 13a1
est committé, viendra après la clôture du 12.

- **12f3** (chantier 12) — 9 tests, 2074 verts (deux passages) :
  - `test_midi_export.py` :
    - une piste inaudible n'a pas de piste SMF, ni aucun message sur son
      canal (notes, CC, PGM) ;
    - une seule piste audible, comme un solo ;
    - aucune piste audible : il ne reste que la conductor ;
    - `None` ;
    - un pad muet perd ses cases de grille, sur une piste synthé comme sur
      une piste kit ;
    - KIT et PATCH sont gardés ;
    - une piste aux seuls pads muets garde sa piste SMF, sans note.
  - `test_midi_export_ui.py` :
    - les paramètres suivent le router et le `VoiceManager`, le mute
      l'emportant sur le solo ;
    - la piste mutée est absente du fichier.
- **12g1** — 48 tests, 2122 verts (deux passages).
  - **Écart au plan** : les tests sont dans un nouveau fichier,
    `tests/test_gm_slot_export.py`, faute de fichier `test_rack*.py`. Le
    test des paramètres est dans `test_midi_export_ui.py`.
  - **Accesseurs** :
    - défauts à 0 ;
    - lecture dans `config` ;
    - bornes ±24 et −40..0 ;
    - une valeur non entière ou booléenne compte pour 0 ;
    - la transposition n'existe que pour un synthé ; le gain vaut pour
      tout slot non vide ;
    - les setters bornent et remplacent `config` ;
    - les réglages survivent à `to_dict` et `from_dict` du Rack.
  - **`apply_gain_db`** : 7 cas, et −N dB à ±0,3 près sur la courbe GM
    `40·log10`.
  - **Export** :
    - PATCH et GRID d'un synthé transposés, y compris négativement ;
    - piste kit et notes KIT jamais transposées ;
    - note bornée à 0..127 ;
    - réglage propre à chaque piste ;
    - gain sur le CC7 du tick 0 et sur un CC7 capturé, les autres CC
      intacts ;
    - `None` ou 0.
  - **Interface** : les réglages sont lus sur le slot, la transposition
    d'un kit est ignorée, et le fichier porte l'orgue en 79 avec un CC7 à
    57.
- **12h1** — conforme à D6.
  - `TrackPropertiesDialog` gagne `slot_gm_tuning(slot) -> (transposition,
    gain_db)`, où `None` grise le réglage, et deux `SpinCtrl` créés après
    la liste des programmes (ordre Tab). S'y ajoutent `_load_gm_tuning`,
    rappelée au changement de slot, ainsi que `get_transpose()` et
    `get_gain_db()`, qui renvoient `None` si le réglage est grisé.
  - `on_change` passe 9 valeurs au lieu de 7.
  - `mw_tracks` gagne `_slot_gm_tuning` : la transposition pour un synthé
    seulement, le gain pour tout slot non vide. `orig` compte 9 valeurs, et
    `apply` applique les deux réglages via `saved_configs`, comme le
    programme.
  - **`pytest` rouge à ce commit** : 12 tests figent l'ancien contrat
    (`test_gm_program.py`, `test_track_channels.py`,
    `test_track_properties_dialog.py`) ; ils sont adaptés en 12i1.
  - **Écoute validée** (utilisateur, 2026-10-24) : il faut transposer
    l'orgue de **+24**, et non de +12, et baisser les autres instruments.
    - +24 correspond à la mesure de 12d1. Le preset FluidR3 contient
      130 Hz à −2 dB sur la note 72, deux octaves sous la note écrite, et
      l'oreille suit cette composante grave. L'exemple « +12 » de D4
      sous-estimait l'écart, faute d'avoir tenu compte de la composante la
      plus grave.
    - Deux hypothèses de l'utilisateur ont été vérifiées et écartées. La
      racine `C5` de `DrawbarOrgan.json` vaut 72 (convention C4 = 60), et
      l'échantillon mesure 524 Hz, soit la note 72. Le mode Keyboard
      sauvegarde `kb_root_midi` dans le pattern, et une note PATCH garde
      la hauteur jouée. L'appli joue donc l'orgue à la hauteur écrite.
- **12i1** — `pytest` de nouveau vert, 2135 tests (deux passages).
  - **Adaptation des 12 tests** : les faux dialogues de
    `test_gm_program.py` et `test_track_channels.py` lisent
    `slot_gm_tuning` et rendent 9 valeurs, avec `get_transpose()` et
    `get_gain_db()`. Les appels scriptés transmettent les deux réglages.
    Le tuple initial d'`on_change` compte 9 valeurs. L'ordre Tab attendu
    est Canal → Programme → Transposition → Gain → Volume.
  - **7 tests du dialogue** (`test_track_properties_dialog.py`) :
    - synthé : actif, valeurs et bornes ;
    - kit : gain seul ;
    - slot vide, ou sans callback : tout grisé ;
    - un changement de slot recharge et transmet les réglages ;
    - `on_change` transmet les valeurs choisies ;
    - les vrais `EVT_SPINCTRL` donnent l'aperçu.
  - **6 tests de `mw_tracks`** (dans `test_gm_program.py` et non dans le
    fichier du dialogue, pour réutiliser le faux dialogue scripté) :
    - `_slot_gm_tuning` selon le genre du slot, et sa transmission ;
    - Ok enregistre `config` et garde l'Undo ;
    - Annuler rend la `config` d'origine de chaque slot touché ;
    - changé puis rétabli, l'action compte comme inchangée ;
    - un kit ne reçoit que le gain ;
    - le réglage est partagé par les pistes du même slot.

### Phase 7 étape 12a4 — Avenant : fin du fichier pile à la fin du pattern

**Origine.** Le 2026-10-24, l'utilisateur a remarqué que TiMidity reboucle
`Pat_01` environ une mesure et demie après sa fin. Diagnostic (4 mesures
à 100 BPM, soit 9,60 s) :
- le fichier dure 9,95 s. La règle D4 de 10a1 fait finir chaque piste au
  plus tard de deux instants, la fin du pattern ou le dernier note-off, et
  trois pistes ont une note qui déborde de 0,15 mesure ;
- TiMidity rend 12,45 s : il ajoute environ 2,5 s pour laisser s'éteindre
  le relâchement des instruments, puis du silence. Le son passe sous
  −60 dBFS à 10,55 s. Cette part ne dépend pas du fichier.

L'utilisateur a choisi de supprimer la part qui vient de l'export dès
maintenant, sans attendre l'export du song.

**D8 — chaque piste finit exactement à la fin du pattern**, soit
`num_bars · num_steps` pas. Cela remplace la règle « au plus tard des deux
instants » de 10a1 D4.
- Un note-off qui dépasse la fin est ramené à la fin du pattern : la note
  est coupée à la limite de la boucle. Au tick de fin, l'ordre de D7 met
  les note-off d'abord, puis `end_of_track`.
- Les autres messages ne peuvent pas dépasser la fin, puisque leur `time`
  est dans le pattern.
- **Perte acceptée** : la résonance des dernières notes, qui dans l'appli
  sonne par-dessus le retour de boucle, est coupée dans le fichier. On y
  reviendra avec l'export du song, où les patterns s'enchaînent.
- Le délai propre à TiMidity reste : un DAW, ou une boucle calée sur les
  mesures, n'en a pas.

| Étape | Contenu | Fichiers |
|---|---|---|
| **12a4** | Doc — cet avenant. | `docs/DESIGN.md` |
| **12i2** | Implémentation — `end_of_track` à la fin du pattern, note-off ramenés à la fin (D8). | `midi/midi_export.py` |
| **12i3** | Tests — note qui déborde coupée à la fin ; `end_of_track` de chaque piste à la fin du pattern ; durée `mido` égale à la durée des mesures ; note qui finit avant la fin intacte ; adaptation du test de 10i1 sur le dernier note-off. | `tests/test_midi_export.py` |
- **12i2** — conforme à D8, avec une règle élargie.
  - Le note-off d'une note qui déborde est ramené à `end_tick`.
    `end_of_track` tombe donc à la fin du pattern sur chaque piste.
  - **Écart à l'avenant** : D8 supposait que seuls les note-off pouvaient
    dépasser la fin. En fait, un événement de `_tape` peut se trouver
    au-delà de la longueur du pattern, par exemple dans une mesure 2 d'un
    pattern d'une seule mesure. Le rejeu (`_build_measure_events`) ne joue
    que les événements compris entre `lp_start` et `lp_end`.
  - L'export omet donc **tout événement**, quel que soit son etype, dont le
    tick tombe à la fin du pattern ou au-delà. Cela couvre aussi la note
    qui commencerait sur la fin par arrondi du tick : elle aurait une
    durée nulle et un note-on sans note-off.
  - **`pytest` rouge à ce commit** : 2 tests de `test_midi_export.py`.
    `test_track_end_at_pattern_end_or_last_note_off` suit l'ancienne règle
    du dernier note-off, et `test_time_conversion_16_and_32_steps` place
    une note en mesure 2 d'un pattern d'une mesure. Ils sont adaptés en
    12i3.
  - Essai : 4 mesures à 100 BPM donnent une durée `mido` de 9,600 s. Une
    note de 3 s au pas 62 est coupée au tick 7680.
- **12i3** — `pytest` de nouveau vert, 2147 tests (deux passages).
  - **Adaptation** :
    - `test_track_end_at_pattern_end_or_last_note_off` devient
      `test_track_end_at_pattern_end_even_if_note_overflows` : toutes les
      pistes finissent au tick de fin, et la note qui déborde y est
      coupée ;
    - le test de conversion des temps passe à 2 mesures, pour que sa note
      de la mesure 2 reste dans le pattern.
  - **12 nouveaux tests** :
    - durée `mido` égale à la durée des mesures, sur 3 cas (1 × 16 à
      120 BPM, 4 × 16 à 100, 2 × 32 à 90) ;
    - une note qui finit avant la fin reste intacte ;
    - une note coupée a son note-off au tick de fin, avant `end_of_track` ;
    - un événement pile à la fin ou au-delà est omis, pour les 6 etypes ;
    - une note arrondie sur le tick de fin est omise.
  - **Écoute** (utilisateur, 2026-10-24) : le rendu WAV de `Pat_01`,
    ramené à 9,600 s avec la résonance repliée sur le début, « boucle très
    précisément ».

### Clôture (12j1)

**12a1-12i3 FAITS** (commits `1625c17`..`bce9722`, 16 commits du chantier
12 et ce commit de clôture, 2147 tests verts) : **chantier Phase 7 étape 12
complet**. Un pattern exporté sonne dans un lecteur GM avec l'équilibre et
la hauteur de l'appli. Il suit le mute et le solo, et boucle pile sur ses
mesures.

**Ce que le chantier a livré** :
- **Courbe de volume GM dans l'appli** (12b1-12c1) : le gain d'une note
  est le carré de son facteur (`gm_gain`), comme dans un lecteur GM, où la
  vélocité et le CC7 suivent `40·log10`. Les projets existants sonnent
  plus bas sur les notes douces et les pistes baissées. L'utilisateur l'a
  validé à l'écoute.
- **Vélocité des cases de grille** (12d1, 12e1) : c'est le gain joué,
  volume du pad compris (`grid_velocity`). Une case par défaut sort à 127.
- **CC91 et CC93 à 0** au tick 0 de chaque piste (12d1). TiMidity les
  ignore, mais c'est la valeur juste pour un lecteur GM ou un DAW.
- **Réglages GM par slot** (12a2, 12f1, 12g1, 12h1, 12i1) :
  - transposition, de −24 à +24, pour un synthé ;
  - gain, de −40 à 0 dB, appliqué aux CC7 de la piste ;
  - deux SpinCtrl dans les propriétés de piste, avec aperçu, Annuler et
    Undo.

  L'orgue demande +24 avec FluidR3 : son preset a une composante deux
  octaves sous la note écrite.
- **Mute et solo à l'export** (12a3, 12f2, 12f3) : les pistes et les pads
  muets ou hors solo sont omis, comme au rejeu. C'est une demande de
  l'utilisateur, qui revient sur 10a1.
- **Fin du fichier pile à la fin du pattern** (12a4, 12i2, 12i3) : les
  notes qui débordent sont coupées, et les événements hors du pattern sont
  omis. Un rendu WAV de 9,600 s, résonance repliée sur le début,
  « boucle très précisément ».

**Écarts au plan** :
- trois avenants, 12a2 à 12a4, tous issus des écoutes ;
- la transposition de l'orgue est de +24, et non de +12 comme dans
  l'exemple de D4 ;
- les tests sont dans `test_gm_slot_export.py` (nouveau) et dans
  `test_gm_program.py`, faute de fichier `test_rack*.py` ;
- l'export omet tout événement hors du pattern, au-delà des seuls note-off
  prévus par D8 ;
- **pas de `~/.timidity.cfg`** : l'utilisateur le juge inutile maintenant
  que l'écart avec l'appli est expliqué, et préfère des options de
  lancement si besoin (`-EFreverb=d -EFchorus=d`).

**`docs/SPECS.md` mis à jour** :
- ligne Phase 7 ;
- slot : `gm_transpose` et `gm_gain_db` ;
- section « Courbe de volume » ;
- section Export MIDI : pistes audibles, CC91 et CC93, vélocité de grille,
  transposition, fin pile, éléments non exportés ;
- `TrackPropertiesDialog` ;
- Undo : le mute, le solo et le volume n'y passent pas encore. La liste
  annonçait le mute et le solo à tort, ce qui est corrigé.

**Laissé hors périmètre, pour la suite** :
- **Phase 7 étape 13**, l'Undo et le marquage modifié du mute, du solo et
  du volume des pistes et des pads : plan 13a1 committé (`22b3699`),
  prochain chantier. Le pan viendra ensuite.
- **Export audio en WAV**, chantier futur demandé par l'utilisateur. Il
  s'agit d'un rendu de la longueur exacte du pattern, avec la résonance
  repliée sur le début, comme la boucle validée en 12i3.
- La résonance des dernières notes, coupée à la fin du fichier, est à
  revoir avec l'export du song, où les patterns s'enchaînent.
- Le délai de bouclage propre à TiMidity (environ 2,5 s de relâchement
  et de silence).
- `SoundManager.preview_sound`, code mort et cassé (12c1).
- Un échec intermittent non identifié, vu une fois en 12e1.
- Les restes des Phase 7 étapes 10 et 11 listés dans leurs clôtures.

---

### Phase 7 étape 13 — Avancement et écarts constatés

- **13b1** (`f88f17b`) — conforme à D1, D2 et D3, avec ces précisions :
  - **Méthodes communes au volume** : `_set_track_volume_undo`
    (`mw_tracks.py`, absent de la liste de fichiers du plan) et
    `_set_pad_volume_undo` (`mw_pads.py`). Elles bornent la valeur, ne
    font rien si elle ne change pas, et servent à Alt+↑/↓, au CC7 et au
    SpinCtrl du pad.
  - **Shift+X, Shift+S** : l'Undo n'est pris que s'il y a quelque chose à
    rétablir (`any(_track_mutes)`, `voice_manager.any_mute()`, et de même
    pour le solo).
  - **Éditeur MIDI** : `_tracks_title` donne `Mute piste 3` ou
    `Mute pistes 2, 4`, une seule entrée pour toute la sélection.
  - **Avenant demandé par l'utilisateur à l'essai** (2026-10-25) : le
    titre d'un Undo de volume porte la **valeur atteinte**,
    `Volume piste 2: 80` ou `Volume pad 5: 80`. Dans un regroupement, le
    titre de l'entrée suit la dernière valeur (`UndoEntry.title` réécrit
    par `_add_mix_undo`). Cela remplace les titres `Volume piste 3` et
    `Volume pad 5` de D1.
  - **Essai dans l'appli** (utilisateur, 2026-10-25) : le mute et le
    volume de piste marchent. Le volume global, le champ « Vol: » après
    le BPM, n'a ni Undo ni marquage : il est hors périmètre, et surtout
    **il n'est pas sauvegardé** dans le `.gvp`, pas plus que le pan
    global (voir la clôture).
  - **`pytest` rouge à ce commit** : 13 échecs. 12 fausses fenêtres de
    `test_key_manager.py` et `test_midi_editor_window.py` n'ont pas les
    nouvelles méthodes ; `test_left_arrow_moves_grid` échoue en cascade
    et passe seul.
- **13c1** (`a2e7a58`) — 40 tests, 2187 verts (deux passages).
  - **Écart au plan** : pas de vraie `MainWindow`, qui chargerait le
    projet par défaut de l'utilisateur, ses sons et son cache. Les vraies
    méthodes (`ProjectMixin`, `TrackMixin`, `PadMixin`, `KeyManager`,
    `MidiHandler`, `PlaybackMixin`) tournent sur une fenêtre factice, avec
    un vrai `VoiceManager`, un `TrackRouter` sans son `__init__`, et un
    `_capture_state` réduit au mixage. Ctrl+Z passe par le vrai
    `_undo_action`.
  - **`_add_mix_undo`** :
    - même clé dans la fenêtre : une entrée, titre de la dernière valeur ;
    - la fenêtre glisse, et 1 s pile ouvre une nouvelle entrée ;
    - une autre clé, une autre action ou une bascule entre deux coupe le
      regroupement ;
    - après Ctrl+Z, un changement ne rejoint pas l'entrée annulée ;
    - un changement regroupé marque quand même le projet modifié.
  - **Chemins** : X, S, Shift+X, Shift+S (pistes et pads), Alt+↑/↓
    (rafale, bornes 0 et 100), CC7 (tour de bouton, pad avec son
    SpinCtrl, valeur inchangée), SpinCtrl et boutons M/S, éditeur MIDI
    sur plusieurs pistes. Chaque fois : entrée créée, projet modifié,
    Ctrl+Z rend la valeur ; une valeur inchangée ne crée rien.
  - **Dialogue du pad** : Ok avec changement (entrée gardée, Ctrl+Z
    restaure tout), Ok inchangé et Annuler (entrée retirée, état
    « modifié » d'avant rétabli, valeurs d'origine après un aperçu), et
    les entrées précédentes restent.
  - **Contrôle** : sur le code d'avant 13b1, 29 des 40 tests échouent ;
    les 11 autres sont les cas « rien ne change, aucune entrée ».
  - **Fakes adaptés** : `_add_mix_undo` enregistré, vraies
    `_set_*_volume_undo`, et les titres d'Undo vérifiés dans
    `test_key_manager.py` et `test_midi_editor_window.py`.

### Clôture (13d1)

**13a1-13c1 FAITS** (commits `22b3699`, `f88f17b`, `a2e7a58`, et ce
commit de clôture, 2187 tests verts) : **chantier Phase 7 étape 13
complet**. Le mute, le solo et le volume des pistes et des pads entrent
dans l'Undo et marquent le projet modifié : la fermeture propose la
sauvegarde après une séance de mixage.

**Ce que le chantier a livré** :
- **Un Undo avant chaque changement** de mute, de solo ou de volume, par
  tous les chemins : clavier (liste des pistes, pads, éditeur MIDI),
  boutons Mute et Solo, Alt+↑/↓, CC7, SpinCtrl Volume du pad. Rien n'est
  fait si la valeur ne change pas.
- **Regroupement des volumes** (`_add_mix_undo`) : un tour de bouton ou
  une rafale d'Alt+↑ ne donne qu'une entrée, `Volume piste 2: 80`, qu'un
  seul Ctrl+Z annule.
- **Dialogue de propriétés du pad** avec Undo, sur le schéma de celui
  des pistes.

**Écarts au plan** :
- le titre du volume porte la valeur atteinte (avenant de l'utilisateur) ;
- `mw_tracks.py` est touché en plus des fichiers prévus ;
- les tests n'utilisent pas de vraie `MainWindow`.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, section Undo (chemins
couverts, `_add_mix_undo`, ce qui n'y passe pas encore), arborescence et
table des tests.

**Laissé hors périmètre, pour la suite** :
- **Le pan** des pistes et des pads (Alt+←/→, Alt+0, CC10, SpinCtrl Pan),
  chantier suivant voulu par l'utilisateur, avec les autres réglages sans
  Undo qu'on trouvera.
- **Le volume et le pan globaux** (`_player.volume`, 80 par défaut, et
  `_player.pan`) : **ni sauvegardés dans le `.gvp`, ni dans l'instantané
  d'Undo**. L'appli repart à 80 à chaque lancement. Il faut d'abord les
  ajouter au projet, avec une valeur par défaut pour les anciens
  fichiers, puis leur donner l'Undo et le marquage.
- **Export audio en WAV**, et les autres points listés à la clôture 12j1.

---

## Phase 7 étape 14a1 — Liste des tests de `docs/SPECS.md` à jour, et script de vérification

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 13 : `14a1`, `14b1`, `14c1`… ; un
commit imprévu inséré après `14b1` s'appelle `14b2`, `14b3`, etc.

### Origine du besoin

Relevé à la clôture 13d1 (2026-10-25) : `docs/SPECS.md` liste les fichiers
de tests deux fois, dans l'arborescence du projet et dans la table
« Tests unitaires ». **21 fichiers sur 60 n'y figurent pas.** Aucun
fichier listé n'a disparu.

Cause : rien ne demande de tenir ces listes à jour. Les clôtures de
chantier mettent à jour le fonctionnel (sections, raccourcis, dialogues),
pas la liste des tests. La table n'a été modifiée que 5 fois en 5 mois
(Phase 3, Phase 6 étapes 5b et 8a, Phase 7 étapes 4q et 13d1), à chaque
fois pour le seul fichier du chantier en cours. Les premiers fichiers
manquants datent du 2026-07-16 (Phase 6 étape 6b).

### Fichiers manquants (2026-10-25, 2187 tests verts)

`test_bend_log.py`, `test_gm_program.py`, `test_gm_slot_export.py`,
`test_kit_channel_migration.py`, `test_live_take.py`,
`test_load_project_cache.py`, `test_midi_constants.py`,
`test_midi_editor_window.py`, `test_midi_export.py`,
`test_midi_export_mix.py`, `test_midi_export_ui.py`,
`test_midi_handler_window.py`, `test_midi_parser.py`,
`test_midi_virtual_keyboard.py`, `test_pattern_grid_api.py`,
`test_pattern_properties_bug.py`, `test_playback_loop.py`,
`test_save_confirm_dialog.py`, `test_sixteen_tracks.py`,
`test_step_duration.py`, `test_track_channels.py`.

### Décisions (demande de l'utilisateur, 2026-10-25)

**D1 — rattraper les 21 fichiers** dans l'arborescence et dans la table,
à leur place alphabétique. La description de la table est tirée du
docstring d'en-tête de chaque fichier, résumée sur une ligne.

**D2 — un petit script de vérification**, `tools/check_specs_tests.py` :
- il compare les `tests/test_*.py` présents sur le disque avec les
  fichiers cités dans l'arborescence et dans la table de
  `docs/SPECS.md` ;
- il signale les fichiers absents de l'arborescence, ceux absents de la
  table, et ceux cités mais qui n'existent plus ;
- pour un fichier absent de la table, il propose une ligne prête à
  coller, avec la première phrase de son docstring ;
- code de sortie 0 si tout est à jour, 1 sinon ; `--root` pour viser un
  autre dossier (les tests du script s'en servent).
- Il est à lancer avant de committer un nouveau fichier de tests, et à
  chaque clôture de chantier.

### Portée explicitement exclue de ce chantier

- **Brancher le script dans `pytest`** (un test qui échoue si la doc
  décroche) ou dans `tests/test_all.sh` : proposé, mais l'utilisateur a
  demandé un script. On pourra le brancher plus tard.
- **Une seule liste** au lieu de deux, et **retrait des nombres de tests**
  (« (21 tests) ») qui vieillissent : proposé, non retenu pour l'instant.
- La mise à jour des descriptions des fichiers déjà listés.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **14a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **14b1** | Doc — les 21 fichiers dans l'arborescence et la table (D1). | `docs/SPECS.md` |
| **14c1** | Implémentation — le script (D2), décrit dans la section « Outils ». | `tools/check_specs_tests.py`, `docs/SPECS.md` |
| **14d1** | Tests — le script sur un faux dossier (`--root`) : tout à jour, absent de l'arborescence, absent de la table, cité mais disparu, ligne proposée, code de sortie ; et sur le vrai dépôt. Le nouveau fichier de tests est ajouté à `SPECS.md` dans ce commit. | `tests/test_check_specs_tests.py`, `docs/SPECS.md` |
| **14e1** | Doc — clôture, `pytest` complet, mémoire. | `docs/DESIGN.md` |

### Phase 7 étape 14 — Avancement et écarts constatés

- **14b1** (`a8332f5`) — les 21 fichiers dans les deux listes, à leur
  place alphabétique, avec une description tirée de leur docstring.
  - **Écart au plan** : 3 fichiers déjà dans la table manquaient à
    l'arborescence (`test_cc_event_edit_dialog.py`,
    `test_event_filter_dialog.py`, `test_midi_editor_filter.py`). Le
    relevé de 14a1 fusionnait les deux listes et ne les voyait pas ; ils
    sont ajoutés. C'est pourquoi le script vérifie chaque liste à part.
- **14c1** (`2fbf823`) — conforme à D2. Le script est décrit dans la
  section « Outils » et l'arborescence de `tools/`, et une consigne en
  tête de la table des tests rappelle de le lancer.
- **14c2** (`b1bff8c`), commit imprévu relevé en écrivant 14d1 : une ligne
  d'arborescence suivie d'un commentaire (`├── test_x.py   # …`) n'était
  pas reconnue, et le fichier aurait été signalé à tort comme absent.
- **14d1** (`ea365c6`) — 15 tests sur un faux dépôt (`--root`), 2202 verts
  (deux passages).
  - **Écart au plan** : pas de test sur le vrai dépôt. Il ferait échouer
    `pytest` dès qu'un fichier de tests manque à la doc, ce qui revient à
    brancher le script dans `pytest`, exclu par 14a1.
  - Le script a signalé `test_check_specs_tests.py` lui-même avant son
    ajout à `SPECS.md`, dans ce même commit.

### Clôture (14e1)

**14a1-14d1 FAITS** (commits `bb14990`, `a8332f5`, `2fbf823`, `b1bff8c`,
`ea365c6`, et ce commit de clôture, 2202 tests verts) : **chantier Phase 7
étape 14 complet**. `docs/SPECS.md` liste les 61 fichiers `tests/test_*.py`
dans l'arborescence et dans la table, et `python3 tools/check_specs_tests.py`
le vérifie.

**Usage retenu** : lancer le script avant de committer un nouveau fichier
de tests, et à chaque clôture de chantier.

**Laissé hors périmètre, pour la suite** :
- brancher le script dans `pytest` ou dans `tests/test_all.sh` ;
- une seule liste au lieu de deux, et le retrait des nombres de tests
  (« (21 tests) ») qui vieillissent ;
- la mise à jour des descriptions des fichiers déjà listés : celle de
  `test_midi_editor_window.py`, par exemple, ne dit pas que les bascules
  vérifient aussi l'Undo depuis 13c1 ;
- **Phase 7 étape 15**, le chantier suivant : le pan des pistes et des
  pads, puis le volume et le pan globaux, à sauvegarder d'abord dans le
  `.gvp`.

---

## Phase 7 étape 15a1 — Undo du pan, volume et pan globaux sauvegardés, points de boucle et boucle du song

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 14 : `15a1`, `15b1`, `15c1`… ; un
commit imprévu inséré après `15b1` s'appelle `15b2`, `15b3`, etc.

### Origine du besoin

- La clôture 13d1 a laissé pour la suite le **pan** des pistes et des pads,
  et les autres réglages sans Undo qu'on trouverait.
- En essayant 13b1 (2026-10-25), l'utilisateur a constaté que le **volume
  global** n'entrait pas dans l'Undo. En fait, ni le volume ni le pan
  globaux ne sont sauvegardés dans le projet.

### État des lieux constaté en code (2026-10-26, 2202 tests verts)

**Pan des pistes et des pads.** Il est sauvegardé dans le pattern
(`_track_pans`, `_voices`), et l'instantané d'Undo le contient déjà. Il
manque seulement l'appel, comme au chantier 13. Les dialogues de
propriétés de piste et de pad ont déjà l'Undo.

| Réglage | Chemin | Code |
|---|---|---|
| Pan de piste | Alt+←/→, Alt+0 sur la liste des pistes | `key_handler_alt.py` |
| Pan de piste | CC10, liste des pistes focalisée | `midi_handler_window.on_cc` |
| Pan de pad | Alt+←/→, Alt+0 hors liste des pistes | `key_handler_alt.py` |
| Pan de pad | CC10 ailleurs que la liste des pistes | `midi_handler_window.on_cc` |
| Pan de pad | SpinCtrl Pan du pad | `mw_pads._on_pan_spin` |

**Volume et pan globaux** (`DrumPlayer.volume`, 80 au lancement, et
`DrumPlayer.pan`, 0).
- Le volume global est le **volume maître** du pilote audio
  (`SoundDeviceDriver.set_master_volume`) : il s'applique à tout le
  mixage.
- Le pan global est un décalage ajouté au pan de chaque pad joué
  (`_mix_pan`).
- **Ni l'un ni l'autre n'est dans le `.gvp`, ni dans l'instantané d'Undo.**
  Nouveau projet et Ouvrir n'y touchent pas : la valeur de la séance
  continue d'un projet à l'autre, et l'appli repart à 80 et 0 à chaque
  lancement.
- L'export MIDI ne les utilise pas.

| Réglage | Chemin | Code |
|---|---|---|
| Volume global | Ctrl+↑/↓ | `key_handler_ctrl.py` |
| Volume global | `+`, `-` (et `6`) | `key_handler_chars.py` |
| Volume global | SpinCtrl « Vol: » (↑/↓ natifs) | `main_window._on_volume_spin` |
| Pan global | Ctrl+←/→, Ctrl+0 | `key_handler_ctrl.py` |
| Pan global | ←/→/↑/↓ dans le SpinCtrl « Pan: » | `key_handler_navigation.py` |
| Pan global | SpinCtrl « Pan: » | `main_window._on_pan_spin` |

**Points de boucle du pattern.** Ils sont sauvegardés dans le pattern
(`loop_start`, `loop_end`, `loop_count`, `looping`), et l'instantané les
contient et les rétablit. Aucun chemin n'a d'Undo :

| Réglage | Chemin | Code |
|---|---|---|
| Début de boucle | Ctrl+L | `key_handler_ctrl.py` |
| Fin de boucle | Shift+L | `key_handler_chars.py` |
| Réinitialisation | Alt+L | `key_handler_alt.py` |
| Tout | Dialogue Ctrl+Shift+L (`LoopSelectDialog`) | `mw_patterns._loop_select_dialog` |

**Case « Boucle » d'un song** (`song._looping`, sauvegardé avec le song).
Elle n'a pas d'Undo (`song_window._on_loop_toggle`), et elle est recopiée
dans `_player._song_looping` pendant la lecture.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — pan des pistes et des pads : même schéma qu'au chantier 13.**
- `_add_mix_undo` avec les clés `("track_pan", t)` et `("pad_pan", p)`.
  Les changements successifs se regroupent s'ils arrivent à moins de 1 s
  d'écart.
- Le titre porte la valeur atteinte : `Pan piste 2: -20`, `Pan pad 5: 30`.
- Rien n'est fait si la valeur ne change pas (Alt+0 sur un pan centré,
  Alt+→ à +100).
- Deux méthodes communes, `_set_track_pan_undo` et `_set_pad_pan_undo`,
  sur le modèle de celles du volume.

**D2 — volume et pan globaux sauvegardés dans le projet** (option a) : une
seule valeur pour tout le fichier, comme un volume maître, et non une par
pattern.
- Le `.gvp` gagne une clé de premier niveau
  `"master": {"volume": 80, "pan": 0}`. `ProjectManager.VERSION` ne change
  pas : la clé est simplement absente des anciens fichiers.
- Ils entrent dans l'instantané d'Undo (`_capture_state`,
  `_restore_state`, qui remet aussi les deux SpinCtrl à jour).

**D3 — valeurs par défaut dans `data/config.json`** (lecture A) : deux clés,
`"master_volume"` et `"master_pan"`, lues par `AppConfig`. Si elles
manquent ou sont invalides, on prend 80 et 0, bornés à 0..100 et
−100..100.
- **Création** (Ctrl+N, ou lancement sans projet) : les valeurs de la
  config.
- **Ouverture d'un projet** sans clé `master` (ancien fichier) : les
  valeurs de la config. Avec la clé : celles du projet.
- **Sauvegarde** : le projet enregistre ses propres valeurs.
- **Fermeture** (Ctrl+N ou Ctrl+O vers un autre projet) : rien ne passe
  de l'ancien projet au suivant.
- L'appli **n'écrit jamais** `config.json` : l'utilisateur change les
  défauts à la main.

**D4 — Undo du volume et du pan globaux**, sur le schéma de D1 : clés
`("master_volume",)` et `("master_pan",)`, titres `Volume global: 75` et
`Pan global: -3`, rien si la valeur ne change pas. Deux méthodes communes,
`_set_master_volume_undo` et `_set_master_pan_undo`, servent à tous les
chemins du tableau.

**D5 — points de boucle et boucle du song.**
- Un Undo avant chaque changement, avec `key=None` : une entrée par action,
  sans regroupement. Titres : `Début de boucle`, `Fin de boucle`,
  `Réinitialiser la boucle`, `Boucle du pattern` (dialogue),
  `Song 03: boucle On`.
- Rien si la valeur ne change pas.
- Le dialogue Ctrl+Shift+L suit le schéma de `TrackPropertiesDialog` :
  Undo avant, retiré si Annuler ou inchangé, état « modifié » rétabli.
- Après un Ctrl+Z, `_player._song_looping` suit le song rétabli s'il est
  en lecture.

### Portée explicitement exclue de ce chantier

- **Un dialogue pour régler les paramètres de `config.json`** : demandé
  par l'utilisateur pour plus tard. Ici, la config se modifie à la main.
- L'export MIDI du volume et du pan globaux.
- Les autres réglages qui ne sont pas sauvegardés dans le projet (BPM du
  métronome, Note Repeat, mode et gamme du clavier en cours…).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **15a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **15b1** | Implémentation — pan des pistes et des pads (D1). | `ui/mw_tracks.py`, `ui/mw_pads.py`, `ui/key_handler_alt.py`, `ui/midi_handler_window.py` |
| **15c1** | Tests — D1. | `tests/test_mix_undo.py`, fakes au besoin |
| **15d1** | Implémentation — volume et pan globaux : `config.json` (D3), `.gvp` (D2), Undo (D4). | `app_config.py`, `ui/main_window.py`, `ui/mw_project.py`, `ui/key_handler_ctrl.py`, `ui/key_handler_chars.py`, `ui/key_handler_navigation.py` |
| **15e1** | Tests — D2, D3, D4. | `tests/test_master_mix.py` (nouveau), fakes au besoin |
| **15f1** | Implémentation — points de boucle et boucle du song (D5). | `ui/key_handler_ctrl.py`, `ui/key_handler_chars.py`, `ui/key_handler_alt.py`, `ui/mw_patterns.py`, `ui/song_window.py`, `ui/mw_project.py` |
| **15g1** | Tests — D5. | `tests/test_loop_undo.py` (nouveau), fakes au besoin |
| **15h1** | Doc — clôture (DESIGN.md, `SPECS.md` § Undo, § Configuration, format `.gvp`), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer chaque implémentation, l'utilisateur l'essaie dans
  l'appli.

### Phase 7 étape 15a2 — Avenant : volume global par défaut à 100

Constaté en préparant 15d1 (2026-10-26) : le champ « Vol: » affiche 80
(`DrumPlayer.volume = 80`), mais **ce 80 n'est jamais transmis au pilote
audio**. `SoundDeviceDriver` démarre avec son volume maître à 1.0, soit
100 %. Le volume réel n'est appliqué qu'au premier réglage (Ctrl+↑/↓,
`+`/`-` ou le champ), et tout le mixage baisse alors d'environ 20 % d'un
coup.

Avec 15d1, la valeur du projet ou de la config est réellement appliquée à
l'ouverture. Avec un défaut à 80, tous les projets sonneraient environ
20 % plus bas qu'aujourd'hui.

**Décision (utilisateur, 2026-10-26)** : D3 est révisée. **Le volume global
par défaut est 100**, et non 80 : les projets sonnent comme aujourd'hui à
l'ouverture, et le champ affiche enfin la vraie valeur. On peut toujours
écrire `"master_volume": 80` dans `data/config.json`.
- `DrumPlayer.volume` démarre à 100.
- La valeur est appliquée au pilote dès le lancement.
- Avant de committer 15d1, l'utilisateur vérifie à l'écoute, en temps
  réel, qu'un projet sonne comme avant à l'ouverture.

### Phase 7 étape 15 — Avancement et écarts constatés

- **15b1** (`e7ebc12`) — conforme à D1 : `_set_track_pan_undo`
  (`mw_tracks.py`) et `_set_pad_pan_undo` (`mw_pads.py`), branchées sur
  Alt+←/→, Alt+0, le CC10 et le SpinCtrl Pan. Essayé par l'utilisateur.
  `pytest` rouge : 3 fausses fenêtres à adapter.
- **15c1** (`cd6a7db`) — 14 tests dans `test_mix_undo.py`, 2216 verts.
  L'instantané réduit de la fausse fenêtre ne gardait pas `_track_pans` :
  4 tests échouaient pour cette raison seule, corrigée.
- **15a2** (`d27849b`) — avenant : le volume global affiché (80) n'était
  jamais transmis au pilote, resté à 100 %. Défaut révisé à **100**.
- **15d1** (`1aabe35`) — conforme à D2, D3, D4 et à l'avenant 15a2.
  - `AppConfig.master_volume` et `master_pan` (repli 100 et 0, bornés,
    valeur invalide → défaut) ; les deux clés sont ajoutées à
    `data/config.json`, suivi par git.
  - `MainWindow._master_defaults`, appliqué au pilote dès le lancement ;
    `DrumPlayer.volume` démarre à 100.
  - `mw_project` : `_master_dict`, `_master_from_dict` (champ par champ),
    `_apply_master`, `_set_master_volume_undo`, `_set_master_pan_undo` ;
    clé `master` à la sauvegarde, à l'ouverture, dans l'instantané, et
    défauts de la config à Ctrl+N. Un instantané sans la clé laisse les
    valeurs en place.
  - **Écart au plan** : les méthodes communes sont dans `mw_project.py`
    et non dans `main_window.py`, puisque le réglage appartient au projet.
  - Essayé à l'écoute par l'utilisateur. `pytest` rouge : 6 fausses
    fenêtres à adapter.
- **15e1** (`2c84ed9`) — `tests/test_master_mix.py`, 43 tests, 2259 verts.
  Un vrai `DrumPlayer` avec un `SoundManager` simulé vérifie ce qui
  atteint le pilote. 42 des 43 tests échouent sur le code d'avant 15d1.
- **15f1** (`7e50310`) — D5.
  - **Écart au plan** : le dialogue Ctrl+Shift+L n'applique rien avant
    Ok. L'Undo est donc pris à l'Ok, seulement si une valeur change, et
    il n'y a rien à retirer si on annule.
  - `_restore_state` rétablit aussi le compteur de répétitions
    (`_loop_remaining`), synchronise `_song_looping` pendant la lecture
    d'un song, et réveille le thread de lecture.
  - Essayé par l'utilisateur ; `pytest` resté vert.
- **15f2** (`d1c930f`), commit imprévu relevé en écrivant 15g1 : le titre
  d'un point de boucle reprenait `position_str()` entier
  (`2:2:1 / 1:4:4`) ; il ne garde plus que la position.
- **15g1** (`1bec5e8`) — `tests/test_loop_undo.py`, 16 tests, 2275 verts.

### Clôture (15h1)

**15a1-15g1 FAITS** (commits `e1c4295`..`1bec5e8`, 10 commits du chantier
et ce commit de clôture, 2275 tests verts) : **chantier Phase 7 étape 15
complet**. Tous les réglages de mixage sauvegardés dans le projet, et les
boucles, entrent dans l'Undo et marquent le projet modifié.

**Ce que le chantier a livré** :
- **Undo du pan** des pistes et des pads, regroupé comme le volume
  (`Pan piste 2: -20`).
- **Volume et pan globaux** :
  - sauvegardés dans le projet (clé `master` du `.gvp`) ;
  - valeurs par défaut dans `data/config.json` (`master_volume`,
    `master_pan`), jamais écrit par l'appli ;
  - appliqués au pilote dès le lancement : le champ « Vol: » affiche
    enfin le volume réel ;
  - Undo regroupé (`Volume global: 75`).
- **Undo des points de boucle** (Ctrl+L, Shift+L, Alt+L, dialogue) et de
  la **case « Boucler » du song**.

**Écarts au plan** : l'avenant 15a2 (défaut 100), les méthodes du volume
global dans `mw_project.py`, l'Undo du dialogue de boucle pris à l'Ok, et
le correctif 15f2.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, Configuration
(`master_volume`, `master_pan`), Volume et Pan global, format `.gvp`
(clé `master`, deux exemples), ProjectManager, Undo (tous les chemins
couverts).

**Laissé hors périmètre, pour la suite** :
- **Phase 7 étape 16** : le « point propre » de l'Undo. Revenir par
  Ctrl+Z à l'état sauvegardé doit effacer le marquage modifié, grâce à un
  numéro d'état et non à un booléen par entrée.
- **Un dialogue de réglage de `data/config.json`**, demandé par
  l'utilisateur.
- L'export MIDI du volume et du pan globaux.
- Les réglages qui ne sont pas sauvegardés dans le projet (métronome,
  Note Repeat, mode et gamme du clavier en cours…).

---

## Phase 7 étape 16a1 — « Point propre » de l'Undo : revenir à l'état sauvegardé efface le marquage modifié

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 15 : `16a1`, `16b1`, `16c1`… ; un
commit imprévu inséré après `16b1` s'appelle `16b2`, `16b3`, etc.

### Origine du besoin

Idée de l'utilisateur (2026-10-26, pendant le chantier 15) : on modifie un
projet, puis Ctrl+Z ramène exactement l'état du fichier sur disque. La
fermeture ne devrait alors pas proposer de sauvegarder, puisque le projet
n'a finalement pas changé. Aujourd'hui, `_project_modified` est un
booléen qui passe à vrai à la première modification et ne revient à faux
qu'à la sauvegarde, à l'ouverture ou à la création d'un projet.

### Pourquoi pas un booléen dans chaque entrée d'Undo

Mémoriser l'état « modifié » d'avant l'action dans l'entrée, puis le
rétablir par Ctrl+Z, se trompe après une sauvegarde : on ouvre, on change
un volume (l'entrée retient « non modifié »), on sauvegarde, puis Ctrl+Z.
L'entrée rétablit « non modifié » alors que l'appli a l'ancien volume et
le fichier le nouveau : la fermeture ne propose rien, et le retour arrière
est perdu.

### État des lieux constaté en code (2026-10-26, 2275 tests verts)

- `_mark_modified` (`mw_project.py`) passe le booléen à vrai. Il est
  appelé par `_add_undo`, par `_add_mix_undo` quand un réglage rejoint
  l'entrée précédente, et par `_restore_state` (donc par Ctrl+Z et
  Shift+Z).
- Le booléen passe à faux à la sauvegarde, à l'ouverture et à la création
  d'un projet.
- `UndoManager` (`undo_manager.py`) : `add`, `pop_last`, `undo`, `redo`,
  `push_future`, `push_history`. Shift+Z crée une **nouvelle**
  `UndoEntry` : l'identité d'une entrée ne suffit donc pas à repérer un
  état, d'où le numéro.
- **Annulations qui laissent le projet marqué** : une vingtaine de
  chemins prennent un Undo avant un dialogue ou une action, puis le
  retirent par `_pop_last_undo` si on annule ou si rien ne change. Ils ne
  rétablissent pas l'état « modifié » : F2 (piste, pattern, song),
  propriétés de pattern, éditeur MIDI (`mew_editing`, `mew_numpad`,
  `mew_delete_clipboard`), fenêtre Songs, `key_handler_ctrl`. Par
  exemple, F2 puis Annuler sur un projet intact affiche l'astérisque.
  Seuls `TrackPropertiesDialog`, le dialogue du pad (13b1) et la prise
  live (`_take_end_if_idle`) remettent l'état d'avant, à la main
  (`was_modified`).
- **L'historique passe d'un projet à l'autre** :
  - Ctrl+O ne vide pas l'historique. Après l'ouverture de B, Ctrl+Z
    rétablit des états de A (patterns, songs, rack) alors que le fichier
    courant reste B : un Ctrl+S écraserait B avec le contenu de A.
  - Ctrl+N ajoute une entrée « Nouveau projet ». Ctrl+Z ramène le contenu
    de l'ancien projet, mais le nom de fichier reste `noname_00x.gvp`.
- Ordre d'init de `MainWindow` : `_project_modified = False` est posé
  avant la création de `self._undo`.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — un numéro d'état, tenu par `UndoManager`.**
- `UndoManager` garde `current_id` (l'état courant) et `saved_id` (l'état
  du fichier), et chaque `UndoEntry` gagne un champ `state_id` : le
  numéro de l'état qu'elle contient.
- `new_state()` : un nouveau numéro, à chaque modification (y compris un
  réglage regroupé par `_add_mix_undo`). `mark_saved()` :
  `saved_id = current_id`. `is_clean()` : `current_id == saved_id`.
- `add` range le numéro courant dans l'entrée. `undo` et `redo` rendent
  l'entrée ; `push_future` et `push_history` rangent le numéro courant
  avec l'état courant ; l'appelant rétablit `current_id` depuis l'entrée
  restaurée.
- `_project_modified` devient une **propriété** de `ProjectMixin` :
  `not self._undo.is_clean()`. Son setter garde les écritures
  existantes : `False` appelle `mark_saved()`, `True` appelle
  `new_state()`. `_mark_modified` appelle `new_state()`.
- `_restore_state` ne marque plus rien : `_undo_action` et `_redo_action`
  rétablissent le numéro de l'entrée et mettent le titre à jour.
- Revenir par Ctrl+Z à l'état sauvegardé retire l'astérisque, et la
  fermeture ne propose rien. Revenir par Ctrl+Z **avant** une sauvegarde
  laisse le projet modifié.

**D2 — correctif des annulations** : `pop_last()` rétablit le numéro de
l'entrée retirée, puisque l'état n'a pas changé. Les vingt chemins sont
corrigés d'un coup, et les rétablissements `was_modified` à la main
disparaissent (propriétés de piste et de pad, prise live).
- Cas d'une sauvegarde faite pendant une action encore ouverte (Ctrl+S
  pendant une prise live) : si `current_id == saved_id` au moment du
  retrait, `saved_id` suit aussi le numéro rétabli, car le contenu est
  le même.

**D3 — l'historique appartient à un projet** (option a) : Ctrl+O et
Ctrl+N vident l'historique (Undo et Redo). L'entrée « Nouveau projet »
disparaît. Si l'ancien projet est modifié, Ctrl+N et Ctrl+O proposent
déjà de le sauvegarder (`SaveConfirmDialog`).

### Portée explicitement exclue de ce chantier

- Comparer le contenu réel avec le fichier (un hash de l'état) : le
  numéro suffit pour tout ce qui passe par l'Undo.
- Les modifications qui ne passent ni par `_add_undo` ni par
  `_mark_modified` restent comme aujourd'hui.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **16a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **16b1** | Implémentation — numéros d'état dans `UndoManager` (D1, D2). | `undo_manager.py` |
| **16c1** | Tests — `UndoManager` : numéros, propre/sale, undo, redo, pop_last, sauvegarde pendant une action ouverte, limite d'historique. | `tests/test_undo_manager.py` |
| **16d1** | Implémentation — `ProjectMixin` (propriété, `_mark_modified`, Ctrl+Z/Shift+Z, sauvegarde, ouverture, création), retrait des `was_modified`, historique vidé à Ctrl+O et Ctrl+N (D3), ordre d'init. | `ui/mw_project.py`, `ui/main_window.py`, `ui/mw_tracks.py`, `ui/mw_pads.py` |
| **16e1** | Tests — Ctrl+Z jusqu'à l'état sauvegardé, avant et après une sauvegarde, réglage regroupé, F2 annulé, dialogues, prise live, Ctrl+O et Ctrl+N. | `tests/test_undo_clean_point.py` (nouveau), fakes au besoin |
| **16f1** | Doc — clôture, `SPECS.md` § Undo, `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

- Avant de committer 16d1, l'utilisateur l'essaie dans l'appli.

### Phase 7 étape 16 — Avancement et écarts constatés

- **16b1** (`fbf0279`) — conforme à D1 et D2 : `UndoEntry.state_id`,
  `UndoManager.current_id` / `saved_id`, `new_state()`, `mark_saved()`,
  `is_clean()` ; `pop_last()` rétablit le numéro de l'entrée retirée.
  L'appli ne s'en sert pas encore ; `pytest` vert.
- **16c1** (`1e5a0bd`) — 16 tests dans `test_undo_manager.py`, qui
  échouent tous sans 16b1 ; 2291 verts.
- **16d1** (`a575fd6`) — conforme à D1, D2 et D3.
  - `_project_modified` est une propriété de `ProjectMixin`.
    `_undo_action` et `_redo_action` rétablissent le numéro de l'entrée
    et le titre ; `_restore_state` ne marque plus rien.
  - `_pop_last_undo` met aussi le titre à jour. Les `was_modified` des
    propriétés de piste et de pad et de la prise live sont supprimés ;
    `_take` ne garde plus que la signature et l'entrée.
  - `_load_project` et `_new_project` vident l'historique ; l'entrée
    « Nouveau projet » disparaît.
  - `MainWindow` crée `_undo` avant tout accès à `_project_modified`.
  - Essayé par l'utilisateur. `pytest` rouge : 13 échecs et 41 erreurs,
    tous des fausses fenêtres au contrat d'avant.
- **16e1** (`e51fce3`) — `tests/test_undo_clean_point.py`, 22 tests ;
  quatre fausses fenêtres adaptées ; 2313 verts.
  - **Contrôle non concluant** : sur le code d'avant 16d1, la fenêtre
    factice n'a pas de `_project_modified` et les 22 tests plantent à la
    préparation. Les tests de 16c1, eux, échouaient bien sans 16b1.

### Clôture (16f1)

**16a1-16e1 FAITS** (commits `4eb1bd3`, `fbf0279`, `1e5a0bd`, `a575fd6`,
`e51fce3`, et ce commit de clôture, 2313 tests verts) : **chantier Phase 7
étape 16 complet**. Revenir par Ctrl+Z à l'état du fichier efface le
marquage modifié, et la fermeture ne propose plus de sauvegarde inutile.

**Ce que le chantier a livré** :
- **Point propre** : un numéro par état, tenu par `UndoManager`, et
  « modifié » ⇔ l'état courant n'est pas celui du fichier. Ctrl+Z
  au-delà d'une sauvegarde reste correctement « modifié », ce qu'un
  booléen par entrée n'aurait pas permis.
- **Correctif des annulations** : une vingtaine de chemins (F2,
  dialogues, éditeur MIDI, fenêtre Songs…) laissaient l'astérisque après
  une annulation ; le retrait de l'entrée rétablit maintenant l'état
  d'avant.
- **Historique par projet** : Ctrl+O et Ctrl+N le vident. Avant, Ctrl+Z
  après Ctrl+O pouvait rétablir le projet précédent dans le fichier
  ouvert, et un Ctrl+S l'aurait écrasé.

**Écarts au plan** : aucun sur le fond ; le contrôle de 16e1 sur
l'ancien code n'est pas concluant (voir plus haut).

**`docs/SPECS.md` mis à jour** : ligne Phase 7, section Undo
(`pop_last_undo`, point propre, historique par projet), Ctrl+N et Ctrl+O.

**Laissé hors périmètre, pour la suite** :
- Comparer le contenu réel avec le fichier (hash de l'état) : le numéro
  suffit pour ce qui passe par l'Undo.
- Les modifications qui ne passent ni par `_add_undo` ni par
  `_mark_modified`.
- Rappel des chantiers en attente : dialogue de réglage de
  `data/config.json`, export audio WAV, 128 pads, mode Rack Synth/GM.

## Phase 7 étape 17a1 — Slot « Banque » : FluidSynth (SF2/SF3) dans le Rack, 4 emplacements de banque

### Numérotation des commits de ce chantier

Même convention qu'en Phase 7 étapes 6 à 16 : `17a1`, `17b1`, `17c1`… ; un
commit imprévu inséré après `17b1` s'appelle `17b2`, `17b3`, etc.

### Origine du besoin

- Le but suivant est l'**Import MIDI** (Phase 7 étape 18). Pour écouter un
  `.mid` importé tel qu'il a été écrit, l'utilisateur veut d'abord un vrai
  synthé General MIDI dans l'appli, et non nos seuls patches WAV.
- L'export MIDI (étapes 10 à 12) écrit déjà canal, programme, CC7, CC10 et
  vélocités GM. Un slot qui joue une soundfont doit sonner comme ce que
  l'export écrit.
- Contrainte transverse : le moteur audio Python est un **prototype**, la
  cible est C/C++. L'interface du moteur de banque doit rester étroite et
  portable, le rendu temps réel séparé de l'UI.

### Essais préalables (ctypes, 2026-10-26)

- FluidSynth 2.4.4 est installé (`libfluidsynth.so.3`), **sans** liaison
  Python (pas de pyfluidsynth) ni en-têtes de développement. libinstpatch
  est présent (le DLS est lu).
- Soundfonts dans `/usr/share/sounds/sf2/` : `FluidR3_GM.sf2` (148 Mo),
  `GeneralUser_GS.sf2`, `TimGM6mb.sf2` (6 Mo, pour les tests).
- **Plusieurs soundfonts dans une seule instance** : six chargées sans
  problème (`sfont_id` 1 à 6), puis
  `fluid_synth_program_select(synth, chan, sfont_id, bank, preset)`.
  `synth.midi-channels` vaut 16 par défaut (plage 16 à 256).
- `fluid_synth_write_float(synth, n, L, 0, 1, R, 0, 1)` rend du son, et
  peut écrire entrelacé (`lincr = rincr = 2`) directement dans un tampon
  `(frames, 2)`.
- **FluidSynth ne lit pas le SFZ** : un `.sfz` valide est refusé (essai
  SF2 puis DLS). Le SFZ viendra plus tard, par sfizz (lib C, non
  installée) ou par notre AudioSampler et un analyseur SFZ.

### État des lieux constaté en code (2026-10-26, 2313 tests verts)

**Rack** (`src/rack.py`). 16 `InstrumentSlot` (type, nom, `config`) ; types
`kit`, `synth`, `loop`, `audio`, `midi_file`, `midi_port`
(`InstrumentType`). Sauvegardé dans le `.gvp` sous `"rack"`
(`mw_project.py:192`, relu `:281`) et dans l'instantané d'Undo (`:369`,
`:513`). Programme GM, transposition et gain GM du slot servent à l'export
(`gm_program`, `gm_transpose`, `gm_gain_db`).

**Chargement des slots.** Pas de dialogue de slot : l'Explorateur (Alt+X,
`ExplorerDialog.ITEMS = ["Projects", "Preset", "Kit", "Patch", "Sound"]`,
`dialogs_simple.py:303`) charge un kit ou un patch dans `_cur_slot`
(`mw_pads._open_explorer`, `_explorer_kit`, `_explorer_patch`), **sans
Undo**.

**Routage** (`src/track_router.py`). `TrackRouter` répartit par type de
slot :

| Événement | Méthode | Aujourd'hui |
|---|---|---|
| Note de grille | `on_play` | SYNTH : note de la gamme du clavier (`_kb_notes_play[pad]`) ; sinon WAV du pad |
| Note KIT de `_tape` | `on_kit_tape` | `SoundManager.play_note` |
| Note PATCH de `_tape` | `on_patch_tape` | moteur du slot SYNTH |
| Pitch Bend, Mod Wheel | `on_bend_tape`, `on_mod_tape` | moteur du slot SYNTH |
| CC générique | `on_cc_tape` | 64/120/121/123 globaux ; 7 et 10 → volume et pan de la piste |
| Program Change | `on_program_change_tape` | **pont provisoire** `assign_slot(program % 16)` |

- Le jeu direct (pads, clavier, MIDI entrant) passe par `router.synth`, le
  moteur du slot courant chargé en aperçu (`load_slot_preview`).
- Les notes sont coupées par `threading.Timer`.
- Mute et solo : `_track_is_audible` en tête de chaque méthode.
- Canal de piste : `_track_channels` (sauvegardé dans le pattern,
  `pattern.py:160`, `:605`) ; `channel_after_slot` met une piste sur le
  canal 10 quand on lui assigne un kit, et la ramène à son canal par défaut
  quand elle quitte un kit (`track_router.py:298`).

**Pilote audio** (`src/sound_device_driver.py`). Un seul
`SoundDeviceDriver` (`main_window.py:190`). `_callback` (`:182`) mixe les
voix dans `mix`, puis `np.clip(mix * self._master_vol, …)` : le volume
global s'applique à tout ce qui passe par `mix`.

**Propriétés de piste** (`TrackPropertiesDialog`,
`dialogs_properties.py:6`). Mute, solo, slot, canal, liste de programmes
GM (`slot_program`, instruments GM ou kits GM2), transposition et gain GM
(`slot_gm_tuning`), volume, pan ; Undo avant ouverture, retiré si Annuler
ou inchangé.

**Export** (`src/midi/midi_export.py`). `build_pattern_midi` écrit au tick
0 le Program Change (`track_programs`), puis CC7, CC10, réverbération et
chorus à 0 ; les Program Change et CC de `_tape` suivent.

**Tests.** 51 tests utilisent `InstrumentType.SYNTH` ou `KIT`, dans 12
fichiers : le nouveau type ne doit pas changer le comportement des types
existants.

### Décisions validées (utilisateur, 2026-10-26)

**D1 — un moteur de banque commun FluidSynth / SFZ.** Une interface
« moteur de banque » : charger une banque, lister ses programmes, choisir
l'instrument d'un canal, note on/off, CC, Pitch Bend, Program Change,
rendu mixé dans notre callback. FluidSynth maintenant, le SFZ plus tard
derrière la même interface.

**D2 — liaison par ctypes**, pas pyfluidsynth (absent, et une dépendance
de moins). Les signatures des fonctions utilisées sont déclarées
(`argtypes`, `restype`) dans un seul module.

**D3 — un seul type de slot « Banque »** (`InstrumentType.BANK = "bank"`).
Le moteur est choisi par l'extension du fichier : `.sf2` et `.sf3`
maintenant, `.sfz` plus tard.

**D4 — 4 emplacements de banque fixes.** Un emplacement = un fichier
chargé une seule fois dans le moteur, que plusieurs slots du Rack peuvent
partager (FluidR3 n'est chargé qu'une fois, même pour huit slots). Pour le
SFZ, un emplacement sera un instrument.

**D5 — dialogue du slot Banque** : fichier de banque, numéro d'emplacement
(1 à 4), banque et programme. Il est ouvert par un nouvel élément
**« Banque »** de l'Explorateur (Alt+X), pour le slot courant.

**D6 — liste des programmes lue dans la soundfont** : les presets réels
(banque, numéro, nom), et non la liste GM fixe.

**D7 — FluidR3 par défaut.** Nouvelles clés de `data/config.json`, lues par
`AppConfig` : `"soundfonts_dir"` (défaut `/usr/share/sounds/sf2`) et
`"gm_soundfont"` (défaut `FluidR3_GM.sf2` dans ce dossier). C'est le
fichier proposé par le dialogue du slot Banque.

**D8 — le canal 10 est joué par FluidSynth** (batterie) quand la piste est
sur un slot Banque, pour regrouper le son au même endroit. Les KIT WAV
existants restent des KIT.

**D9 — pas de canal dans le slot.** Le canal reste celui de la **piste**
(étape 10f1). `channel_after_slot` est étendue : un slot Banque réglé sur
une batterie (banque 128) met la piste au canal 10 ; un slot Banque
mélodique la ramène à son canal par défaut si elle était au 10. Un
routage « canal MIDI entrant → slot » (clavier multi-timbral) sera une
table du Rack, en mode Rack 16 canaux : **hors périmètre**.

**D10 — deux pistes au même canal sur des slots Banque différents** :
avertissement dans la barre d'état ; le dernier programme envoyé
l'emporte, comme sur un vrai synthé.

**D11 — FluidSynth joue ce que l'export écrit** : volume de piste → CC7
(`volume_to_cc7`), pan → CC10 (`pan_to_cc10`), vélocité de l'export
(`grid_velocity`, étape 12e1) ; mute et solo suppriment les notes (comme
aujourd'hui, par `_track_is_audible`).

**D12 — notes de grille** : slot mélodique → gamme du clavier, comme un
slot SYNTH (`_kb_notes_play[pad]`) ; batterie (canal 10) → pad i = note GM
36 + i.

**D13 — pan global** ajouté au CC10 de chaque canal de banque (borné). Le
volume global, lui, s'applique déjà à tout `mix` dans le callback.

**D14 — code.** Nouveau paquet `src/engines/` : l'interface
(`bank_engine.py`) et `fluidsynth_engine.py`. Le pilote gagne une méthode
pour brancher une source de rendu dans son callback.

**D15 — propriétés de piste (Alt+Entrée) sur un slot Banque, en temps réel** :
changement de **canal** (dont le passage au 10 = batterie), de
**programme** (liste de la soundfont, D6), de **banque MSB (CC0) / LSB
(CC32)**, appliqués **aussitôt au moteur**. Annuler rétablit canal,
banque et programme dans le moteur ; l'Undo reste celui d'aujourd'hui.
Pour un SFZ, banque et programme seront grisés.

**D16 — note d'aperçu à chaque changement** de programme, de banque ou de
canal (do central ; grosse caisse, note 36, au canal 10), comme Alt+↑ sur
la liste des pads.

**D17 — Bank Select.** `synth.midi-bank-select` en **mode GS par défaut** :
seul le MSB choisit la banque (FluidR3 et GeneralUser numérotent leurs
banques comme le MSB : 0, 8, 16…, 128 pour la batterie). Clé
`"midi_bank_select"` de `config.json` (`"gs"` ou `"mma"`) pour passer en
**MMA** (banque = MSB × 128 + LSB). Le LSB est toujours enregistré et
exporté ; le dialogue indique qu'il est sans effet en mode GS.

**D18 — rejeu et export.** Les Program Change et CC0/CC32 de `_tape` sont
envoyés au moteur sur le canal de la piste : pour une piste sur slot
Banque, ils **remplacent le pont `program % 16`** (qui reste pour les
autres slots). L'export écrit CC0 et CC32 avant le Program Change, au
tick 0.

**D19 — découpage** : trois paires impl → tests, chacune **essayée à
l'écoute** par l'utilisateur avant le commit d'implémentation : (a)
moteur et branchement au pilote ; (b) type Banque, 4 emplacements,
`.gvp`, routage de tous les événements ; (c) dialogues (slot, propriétés
de piste) et Undo ; puis la clôture. Les tests du moteur utilisent
TimGM6mb et sont **sautés si libfluidsynth est absente**.

### Choix de conception proposés pour l'implémentation

Ces points découlent des décisions ; ils seront confirmés ou corrigés dans
« Avancement et écarts » au fil des commits.

**Interface `BankEngine`** (`src/engines/bank_engine.py`), volontairement
proche de l'API C, sans objet Python dans les appels temps réel :

| Méthode | Rôle |
|---|---|
| `load(slot, path)` → bool | charge le fichier dans l'emplacement 0..3 (remplace l'ancien) |
| `unload(slot)` | libère l'emplacement |
| `presets(slot)` → `[(bank, program, name)]` | liste lue dans la banque (D6) |
| `select(channel, slot, bank, program)` | instrument d'un canal |
| `note_on(ch, note, vel)`, `note_off(ch, note)` | notes |
| `cc(ch, num, value)`, `pitch_bend(ch, value)`, `program_change(ch, program)` | contrôles |
| `all_notes_off()`, `all_sounds_off()`, `reset_controllers()` | CC 123, 120, 121 |
| `render(out)` | ajoute `frames` échantillons stéréo float32 dans `out` `(frames, 2)` |

- `FluidSynthEngine` : une seule instance `fluid_synth`, 16 canaux, à la
  fréquence du pilote. Le `sfont_id` de chaque emplacement est gardé.
  L'API de FluidSynth est protégée par son propre verrou
  (`synth.threadsafe-api`, actif par défaut) : les appels de l'UI, des
  `threading.Timer` et du séquenceur ne demandent pas de verrou à nous.
- Le chargement d'un gros fichier (FluidR3, 148 Mo) se fait dans un fil,
  comme `_ensure_slot_synth` ; le slot reste muet jusqu'à la fin, message
  dans la barre d'état. Fichier introuvable ou refusé : message, slot muet.
- libfluidsynth absente : `FluidSynthEngine` n'est pas créé, le type
  Banque reste choisissable mais muet, avec un message.

**Pilote.** `SoundDeviceDriver.add_render_source(fn)` /
`remove_render_source(fn)` : `_callback` appelle `fn(mix)` après les voix
et avant `* self._master_vol`. Le volume global s'applique donc aussi à
FluidSynth (D13).

**Slot Banque dans le `.gvp`.**
- `config` du slot : `{"bank_slot": 0..3, "bank_msb": 0..127,
  "bank_lsb": 0..127, "program": 0..127}`. Le nom du slot est celui du
  preset (« Acoustic Grand Piano »).
- Les 4 emplacements sont sauvegardés avec le Rack :
  `"rack": {"slots": […], "bank_files": [chemin ou null] × 4}`. Ils
  entrent donc dans l'instantané d'Undo, et `_restore_state` recharge un
  emplacement seulement si son fichier a changé, puis resélectionne les
  instruments des canaux. `ProjectManager.VERSION` ne change pas : la clé
  est absente des anciens fichiers.
- Programme et banque appartiennent au **slot** (comme `gm_program`
  aujourd'hui) : deux pistes sur le même slot ont le même instrument, sur
  leurs canaux respectifs.

**Envoi aux canaux.** Le routeur tient l'état envoyé à chaque canal
(emplacement, banque, programme) et ne renvoie `select` que s'il change.
Au démarrage de la lecture, à l'ouverture d'un projet et après un Undo,
chaque piste sur slot Banque resélectionne son instrument et envoie CC7
et CC10 (D11, D13). Le jeu direct (pads, clavier, MIDI entrant) sur un
slot Banque va au canal de la piste courante.

**Export.** Une piste sur slot Banque exporte le programme et la banque du
slot (D18) ; ses notes de grille suivent D12 ; la transposition et le gain
GM (12h1) ne s'appliquent pas (SpinCtrl grisés), puisque le programme est
réel.

### Portée explicitement exclue de ce chantier

- Le **SFZ** (sfizz ou AudioSampler + analyseur) : l'interface est prévue
  pour lui, l'implémentation viendra plus tard.
- Le routage « canal MIDI entrant → slot » et le mode Rack 16 canaux
  (chantier futur « mode Rack Synth/GM »).
- Réglages de réverbération et chorus de FluidSynth (laissés à 0, comme
  l'export), polyphonie, interpolation.
- L'export audio WAV, le dialogue de réglage de `config.json`.
- L'Import MIDI lui-même (Phase 7 étape 18).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **17b1** | Implémentation — (a) `BankEngine`, `FluidSynthEngine` par ctypes (D1, D2, D14, D17), `add_render_source` du pilote, clés `soundfonts_dir`, `gm_soundfont`, `midi_bank_select` (D7). | `src/engines/` (nouveau), `sound_device_driver.py`, `app_config.py`, `ui/main_window.py` |
| **17c1** | Tests — moteur sur TimGM6mb (chargement, presets, select, rendu non nul, note off, 4 emplacements, mode GS/MMA), source de rendu du pilote, config. Sautés sans libfluidsynth. | `tests/test_fluidsynth_engine.py` (nouveau), `tests/test_sound_device_driver.py` ou nouveau, `tests/test_app_config.py` |
| **17d1** | Implémentation — (b) `InstrumentType.BANK` (D3), 4 emplacements dans le Rack et le `.gvp` (D4), routage de tous les événements (D8, D11, D12, D13, D18), `channel_after_slot` (D9), avertissement de canal partagé (D10), export (D18). | `rack.py`, `track_router.py`, `ui/mw_project.py`, `midi/midi_export.py`, `ui/midi_handler_window.py` |
| **17e1** | Tests — Rack et `.gvp`, routage (moteur factice), canal 10, avertissement, export CC0/CC32. | `tests/test_bank_slot.py` (nouveau), tests d'export, fakes au besoin |
| **17f1** | Implémentation — (c) dialogue du slot Banque et élément « Banque » de l'Explorateur (D5, D6), propriétés de piste en temps réel (D15, D16), Undo. | `ui/dialogs_bank.py` (nouveau) ou `ui/dialogs_properties.py`, `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — dialogues, application immédiate, Annuler, Undo, note d'aperçu. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17h1** | Doc — clôture (DESIGN.md, `SPECS.md` : Rack, configuration, format `.gvp`, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

- Avant de committer 17b1, 17d1 et 17f1, l'utilisateur les essaie à
  l'écoute dans l'appli.

### Phase 7 étape 17 — Avancement et écarts constatés

- **17b1** — conforme à D1, D2, D7, D14 et D17 : `src/engines/`
  (`BankEngine`, `FluidSynthEngine` par ctypes, essai à l'écoute par
  `python3 -m engines.fluidsynth_engine` depuis `src/`),
  `SoundDeviceDriver.add_render_source` / `remove_render_source` et
  propriété `samplerate`, clés `soundfonts_dir`, `gm_soundfont`,
  `midi_bank_select` ; moteur créé par `MainWindow._init_bank_engine`
  (None sans libfluidsynth), fermé en quittant.
  - **Écart : gain.** À l'écoute, le gain par défaut de FluidSynth (0.2)
    était bien trop faible à côté de nos pads WAV normalisés (crête 1.0 ;
    FluidSynth montait à 0.05-0.09 à vélocité 100). Défaut porté à
    **1.0**, validé par l'utilisateur, et nouvelle clé
    **`"fluidsynth_gain"`** de `config.json` (0.0..10.0).
  - Essayé à l'écoute par l'utilisateur. `pytest` rouge : 1 échec, la
    fausse fenêtre de `test_live_take.py` n'a pas `_bank_engine`
    (adaptée en 17c1).
- **17c1** (`6c82f3a`) — `tests/test_fluidsynth_engine.py` (38 tests),
  sur **FluidR3_GM** à la demande de l'utilisateur (TimGM6mb en repli),
  sautés sans libfluidsynth ; seuil de son audible 1e-4, presets sans
  dépendre des noms ; source de rendu du pilote (6 tests), clés de
  config (29 tests) ; 2386 verts. FluidR3 se charge en 0,08 s.
- **17d1** (`1845318`) — conforme au plan d'origine (D3, D4, D8-D13,
  D18) : `InstrumentType.BANK`, instrument dans la config du slot, 4
  emplacements dans le Rack, le `.gvp` et l'Undo, routage de tous les
  événements, `BankPreview` pour le jeu direct, export CC0/CC32.
  - **Écart : chargement sans fil.** FluidSynth lit la soundfont à la
    demande (FluidR3 en 0,1 s) : pas de fil de chargement.
  - Essayé à l'écoute (lecture, volume, pan, pan global, mute, solo,
    export). `pytest` rouge : 27 faux objets.
- **17d2** (`4726b58`) — correctif trouvé par les tests de 17e1 :
  `assign_slot_by_user` synchronisait la banque **avant** de poser le
  canal ; une batterie était sélectionnée sur l'ancien canal de la piste.
- **17e1** (`6c0e5b3`) — `tests/test_bank_slot.py` (58 tests), 27 faux
  objets adaptés ; 2444 verts.
  - **Piège : crash de pytest à la sortie.** Un vrai `SynthEngine` sans
    pilote (créé par `assign_slot` sur un slot SYNTH) ouvre un
    `SoundDeviceDriver`, flux audio jamais fermé, qui faisait planter
    l'interpréteur après les tests (8 fois sur 10). Les tests remplacent
    désormais `track_router.SynthEngine`.
- **17e2** (`e8a2682`) puis **17e3** (`e04f96e`) — deux révisions du plan,
  ci-dessous : à l'essai de 17d1 puis de 17f1, l'utilisateur veut
  plusieurs instruments sur un même slot, puis le modèle « orchestre ».

## Phase 7 étape 17e2 — Révision du plan : programme et banque par piste

### Origine

- À l'ouverture de 17f1 (dialogues), l'utilisateur demande comment jouer
  plusieurs instruments, plus une batterie, à partir du même slot Banque.
- Dans le modèle de 17a1 à 17e1, **un slot du Rack = un instrument**
  (`config` : emplacement, MSB, LSB, programme, batterie). Plusieurs
  instruments demandent plusieurs slots qui désignent le même emplacement
  (fichier chargé une fois, D4). Chaque instrument consomme l'un des 16
  slots, partagés avec les kits et les synthés WAV : ce n'est pas un module
  GM « 16 canaux sur un slot ».
- L'Import MIDI (Phase 7 étape 18) va dans l'autre sens : un `.mid` de 16
  canaux doit devenir 16 pistes, chacune avec son canal, sa banque et son
  programme, sans consommer 16 slots.
- Décision de l'utilisateur (2026-10-27) : étudier le passage du programme
  à la **piste**, plan d'abord.

### État des lieux constaté en code (après 17e1, 2444 tests verts)

**Réglages par piste.** Ils appartiennent au **pattern** : `Pattern` porte
`_track_slots`, `_track_mutes`, `_track_solos`, `_track_volumes`,
`_track_pans`, `_track_channels` (`pattern.py:152-160`), sauvegardés par
`to_dict` (`:507-512`), relus par `from_dict` (`:598-606`), complétés par
`_extend_tracks` (`:646-652`). Ils sont copiés vers le routeur par
`_apply_pattern_from_store` (`mw_patterns.py:82-87`) et l'avance du song
(`mw_songs.py:143-148`), et retour par `_flush_pattern_to_store`
(`mw_patterns.py:67-72`). Ils entrent donc déjà dans l'Undo (dict du
pattern) et dans le `.gvp`.

**Instrument d'une banque (17d1).** Lu dans le slot : `InstrumentSlot`
`bank_msb`, `bank_lsb`, `bank_program`, `bank_drums` (`rack.py`) ;
`TrackRouter._bank_key(slot)` (`track_router.py:345`) ;
`channel_after_slot` met au canal 10 un slot dont `drums` est vrai
(`:534`) ; `gm_program` d'un slot Banque = son programme ; l'export lit
`track_banks` et `track_programs` sur le slot (`mw_project.py:112, :121`).

**Programme GM des synthés et kits** (`gm_program`, 10h3) : réglage du
**slot**, pour l'export seulement ; Alt+Entrée le modifie
(`mw_tracks.py:79-81`).

**Libellé de piste** (`mw_tracks.py:142`) : `Track_03 - Slot_06 - <nom du
slot>`.

### Décisions validées (utilisateur, 2026-10-27)

**R1 — le slot Banque ne désigne que l'emplacement.** `config =
{"bank_slot": 0..3}`. Son nom par défaut est celui du fichier
(« FluidR3_GM »). Les clés `bank_msb`, `bank_lsb`, `program`, `drums` du
slot disparaissent avec leurs accesseurs ; elles sont ignorées si un
`.gvp` les contient (seul le projet d'essai de 17d1 en a : pas de
migration).

**R2 — banque et programme appartiennent à la piste, donc au pattern**,
comme son slot et son canal. Trois nouvelles listes de `Pattern`,
sauvegardées, relues, complétées et copiées comme les autres :
`_track_programs` (0..127, défaut 0), `_track_bank_msb` et
`_track_bank_lsb` (0..127, défaut 0). Clés absentes des anciens fichiers :
valeurs par défaut. Elles ne servent qu'aux pistes sur slot Banque. Le
routeur les reçoit comme `_track_channels`.

**R3 — la batterie, c'est le canal 10.** Plus de drapeau : une piste sur
slot Banque au canal 10 joue la banque 128 de la soundfont (convention GM,
et ce que fait FluidSynth en mode GS), avec son programme (0 Standard,
8 Room, 16 Power…) ; MSB et LSB y sont sans effet. `channel_after_slot` :
un slot Banque **garde** le canal de la piste, 10 compris (seul un kit
force le 10 ; quitter un kit ramène au canal par défaut, comme
aujourd'hui).

**R4 — routeur.** `_bank_key(track)` = (emplacement du slot, 128 si canal
10 sinon `bank_number(MSB, LSB)` de la piste, programme de la piste). Le
cache par canal, l'avertissement de canal partagé (D10 : deux pistes au
même canal avec des instruments différents), le mixage CC7/CC10 et le
reste du routage de 17d1 ne changent pas. Nouveau
`set_track_program(track, program, msb, lsb)` : enregistre et resélectionne
aussitôt (Alt+Entrée temps réel, D15).

**R5 — Program Change et CC0/CC32 reçus ou rejoués** : comme en 17d1, au
moteur sur le canal de la piste, **sans** modifier les réglages
enregistrés de la piste. Un Program Change venu du contrôleur ne change
que le son ; si l'on relance la lecture, le début de lecture resélectionne
l'instrument enregistré de la piste (`on_play_start`), puis les Program
Change capturés dans `_tape` le changent en cours de route, comme sur un
vrai module (Q2).

**R6 — export.** `track_programs` et `track_banks` viennent de la piste
pour un slot Banque : CC0/CC32 (piste hors canal 10) puis Program Change au
tick 0. Le nom de la piste SMF est celui du **preset** (« Violin »), lu
dans la soundfont, à défaut celui du slot. Synthés et kits : inchangés
(`gm_program` du slot).

**R7 — libellé de piste** sur slot Banque : nom du preset de la piste
(`Track_03 - Slot_06 - Violin`, « Standard » au canal 10) ;
« (preset absent) » si la banque ne le contient pas ; nom du slot si
l'emplacement est vide.

**R8 — Alt+Entrée sur une piste Banque (D15, D16), en temps réel.**
- **Programme** : ListBox des 128 programmes de la banque de la piste,
  noms lus dans la soundfont (D6), « (vide) » pour un numéro absent ; au
  canal 10, les kits de la banque 128.
- **Banque MSB** et **LSB** : deux SpinCtrl 0..127 ; changer le MSB (ou le
  LSB en mode MMA) recharge la liste. Grisés au canal 10. Le libellé du
  LSB indique « sans effet en mode GS » en mode GS (D17).
- Chaque changement de canal, banque ou programme est appliqué aussitôt au
  moteur, avec une note d'aperçu (do central ; 36 au canal 10). Annuler
  rétablit le tout ; Undo inchangé (posé avant, retiré si Annuler ou rien
  changé).
- Transposition et gain GM grisés sur un slot Banque (programme réel).

**R9 — dialogue du slot Banque (D5 simplifié)** : élément « Banque »
ajouté en fin de liste de l'Explorateur (Alt+X) ; il règle le **slot
courant** : fichier (champ + « Parcourir… », défaut `gm_soundfont`) et
emplacement (ListBox « Emplacement 1 » à « Emplacement 4 », avec le
fichier qu'il contient déjà). Plus de liste d'instruments ici : on choisit
l'instrument par piste (R8). Appliqué à Ok ; Undo posé avant, retiré si
Annuler ou rien changé. Remplacer le fichier d'un emplacement change le son
de tous les slots qui le désignent : le dialogue l'annonce.

**R10 — synthés et kits inchangés.** Leur programme GM d'export reste un
réglage du slot. Le passer aussi à la piste serait cohérent, mais c'est un
autre chantier (non demandé).

### Questions tranchées (utilisateur, 2026-10-27)

- **Q1 — programme par pattern** (R2), comme le slot et le canal : changer
  de pattern peut changer d'instrument. Un fichier `.mid` est un pattern
  (Import MIDI, étape 18).
- **Q2 — un Program Change du contrôleur ne change que le son**, pas le
  programme enregistré de la piste (R5) : la piste se règle par Alt+Entrée,
  avec Undo, et la relance de la lecture rejoue le programme enregistré.

### Ce qui est repris de 17d1 et 17e1

- `rack.py` : accesseurs `bank_msb/lsb/program/drums` retirés ;
  `gm_program` d'un slot Banque → None ; `channel_after_slot` sans la
  clause batterie du slot.
- `track_router.py` : `_bank_key` par piste, listes de piste, R4.
- `pattern.py`, `mw_patterns.py`, `mw_songs.py` : trois listes (R2).
- `mw_project.py` : paramètres d'export (R6).
- `tests/test_bank_slot.py` : une vingtaine de tests à réécrire (config du
  slot, batterie, `channel_after_slot`, sélection, export) ; le reste
  (emplacements, rejeu, jeu direct, contrôles globaux) ne change pas.

### Portée exclue

Inchangée par rapport à 17a1 (SFZ, routage canal entrant → slot, mode Rack
16 canaux, réglages de réverbération et chorus, export WAV, Import MIDI).

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17e2** | Doc — cette révision. | `docs/DESIGN.md` |
| **17f1** | Implémentation — R1 à R7 : slot = emplacement, banque et programme par piste dans le pattern, batterie = canal 10, routeur, export, libellé de piste. Essayé à l'écoute. | `rack.py`, `pattern.py`, `track_router.py`, `ui/mw_patterns.py`, `ui/mw_songs.py`, `ui/mw_project.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — R1 à R7, `tests/test_bank_slot.py` adapté. | `tests/test_bank_slot.py`, tests de Pattern au besoin |
| **17h1** | Implémentation — R8 et R9 : Alt+Entrée en temps réel sur une banque, dialogue du slot Banque dans l'Explorateur, Undo. Essayé à l'écoute. | `ui/dialogs_properties.py`, `ui/dialogs_bank.py` (nouveau), `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py` |
| **17i1** | Tests — dialogues, temps réel, Annuler, Undo, note d'aperçu. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17j1** | Doc — clôture (avancement 17c1 à 17i1, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

## Phase 7 étape 17e3 — Révision du plan : le canal est l'instrument (modèle « orchestre »)

### Origine

- Essai à l'écoute de 17f1 (non committé), programme par piste (17e2) :
  quatre pistes sur un seul slot Banque s'entendent bien. Mais changer le
  canal d'une piste dans Alt+Entrée ne fait pas toujours entendre l'instrument
  du nouveau canal : quand deux pistes partagent un canal, la piste de plus
  grand numéro l'emporte (D10). La basse (piste 4) mise au canal 1 garde
  son son, et c'est le piano qui devient basse.
- L'utilisateur précise son modèle (2026-10-27) : **le canal est un
  instrument de l'orchestre, les pistes sont les musiciens.** Un musicien
  joue l'instrument qu'il veut, et peut en changer, donc changer de canal,
  en cours de morceau.
- Il demande que canal, programme et banque soient des **événements de la
  piste**, écrits à la validation de Alt+Entrée, visibles dans la liste des
  événements et modifiables à la main ou par automation.
- Pas de nouveau type d'événement « canal » : le Program Change porte déjà
  un numéro de canal. Pour changer de canal, on écrit un nouveau Program
  Change.

**Principe directeur** (utilisateur, 2026-10-27) : les normes MIDI et les
banques GM n'entrent dans l'appli que pour retrouver les habitudes des
séquenceurs comme **Sonar**, efficaces pour enregistrer et composer. En
cas de doute, on reproduit leur comportement.

### État des lieux constaté en code

- `TapeEvent.channel` existe pour tous les événements. À la capture, il
  reçoit le canal **du contrôleur** (`record_program_change(program,
  channel)`, `dp_recording.py:256`). À l'export, il est ignoré : tout
  s'écrit sur le canal de la piste
  (`test_every_event_on_track_channel_not_ev_channel`,
  `test_midi_export.py:152`).
- Rejeu : `PGM_TAPE_EVENT` transmet `(piste, programme)` sans le canal
  (`dp_playback.py:180-183`) ; `TrackRouter.program_change` l'envoie sur
  le canal de la piste.
- Aucune « poursuite » : démarrer au milieu du pattern ne renvoie pas les
  Program Change déjà passés.
- Export : à tick égal, le Program Change s'écrit **avant** les CC
  (`_ORDER_PGM = 1 < _ORDER_CC = 2`, `midi_export.py:34-35`). Des CC0 /
  CC32 de `_tape` au même tick qu'un Program Change arriveraient après lui
  et ne choisiraient pas la banque.

### Décisions validées (utilisateur, 2026-10-27)

Gardées de 17e2 : **R1** (slot Banque = emplacement seul), **R3** (canal
10 = batterie, banque 128 ; un slot Banque garde le canal de la piste),
**R7** (libellé de piste = nom du preset), **R9** (dialogue du slot Banque :
fichier et emplacement), **R10** (synthés et kits inchangés), **Q1**
(tout appartient au pattern ; un `.mid` est un pattern) et **Q2** (un
Program Change du contrôleur, hors enregistrement, ne change que le son).
**Abandonnée : R2** (listes `_track_programs`, `_track_bank_msb`,
`_track_bank_lsb` du pattern, écrites en 17f1 et non committées) : la
source devient les événements (O2).

**O1 — le canal est l'instrument.** Chacun des 16 canaux a un instrument
(programme, MSB, LSB), entendu par toutes les pistes de ce canal. Le
routeur tient l'instrument courant de chaque canal ; sans Program Change,
programme 0 banque 0 (au canal 10 : kit 0 de la banque 128).

**O2 — les événements de la piste sont la seule source.** Program Change
(`ETYPE_PGM`), CC0 et CC32 (`ETYPE_CC`) de `_tape`. L'**entête** d'une
piste = ses CC0, CC32 et Program Change à 1.1.1. Ils sont visibles dans la
liste des événements (Ctrl+2), modifiables, et l'Import MIDI les
produira directement.

**O3 — le Program Change porte le canal.** Le canal courant d'une piste,
à un instant, est celui de son **dernier Program Change** avant cet
instant ; avant le premier, le canal de la piste (`_track_channels`).
Changer de canal en cours de morceau = écrire un Program Change sur un
autre canal. Un Program Change change aussi l'instrument de son canal
(O1), comme sur un vrai module.
- Les notes, CC, Pitch Bend de la piste vont à son canal courant (leur
  propre champ `channel` reste ignoré, comme aujourd'hui).
- Modifier à la main le canal d'un Program Change à 1.1.1 change aussi le
  canal de la piste (`_track_channels`), pour que Alt+Entrée, le libellé et
  l'export restent d'accord.

**O4 — poursuite (chase).** Au début de la lecture, en partant de
n'importe quelle position, au chargement d'un pattern, à l'avance du song
et après un Undo : pour chaque canal, l'appli renvoie au moteur le dernier
CC0, CC32 et Program Change rencontrés avant la position (toutes pistes
confondues, à temps égal dans l'ordre des pistes), et chaque piste reprend
le canal de son dernier Program Change. Remplace la resélection de
`on_play_start` (17d1).

**O5 — Alt+Entrée sur une piste Banque, choix B : le canal impose son
instrument.**
- Programme, MSB et LSB affichés = l'instrument **du canal choisi**.
  Passer la piste sur un autre canal fait entendre et afficher
  l'instrument de ce canal.
- Changer le programme ou la banque change l'instrument du canal, en
  direct, pour toutes ses pistes, avec la note d'aperçu (D16).
- **Ok** écrit l'entête de la piste : CC0, CC32 et Program Change à 1.1.1,
  sur le canal de la piste, en remplaçant les précédents.
- **Les autres pistes du même canal** qui ont un entête le reçoivent mis à
  jour aussi (message dans la barre d'état) : le canal reste cohérent.
- **Annuler** rétablit canal et instrument dans le moteur ; Undo comme
  aujourd'hui (posé avant, retiré si Annuler ou rien changé).
- **Précision 17f2 (essai de 17f1, utilisateur, 2026-10-27) : piste
  temporaire pendant le dialogue.** Si la lecture tourne en boucle pendant
  Alt+Entrée, la poursuite et le rejeu de l'entête d'origine ramenaient la
  piste à son ancien canal et à son ancien son à chaque tour. Donc, dès
  l'ouverture, la piste (et les autres pistes du canal touchées) est
  copiée ; chaque changement de canal, de programme ou de banque réécrit
  aussitôt l'entête **dans la piste**, temporairement, si bien que le
  bouclage rejoue le nouveau réglage. **Ok** garde ces entêtes ;
  **Annuler** remet les pistes d'origine, puis la poursuite rétablit
  canaux et instruments.

**O6 — entête seulement pour les pistes sur slot Banque.** Sur un synthé
WAV ou un kit, un Program Change réassigne le slot (pont `program % 16`) :
Alt+Entrée n'y écrit pas d'entête.

**O7 — capture : le Program Change est remis au canal de la piste
(validé).** Un Program Change enregistré depuis le contrôleur
porte le canal du contrôleur. Avec O3, il ferait changer la piste de canal.
À la capture, Program Change, CC0 et CC32 reçoivent le **canal
courant de la piste** (comme le « rechannelize » d'un séquenceur). Changer
de canal reste un geste explicite : Alt+Entrée, ou édition de l'événement.

**O8 — export.**
- À tick égal, CC0 et CC32 s'écrivent avant le Program Change ; les
  autres CC restent après (ordre D7 sinon inchangé).
- Chaque événement s'écrit sur le canal courant de la piste à son instant
  (O3) : une piste peut changer de canal dans le fichier, ce que le SMF
  permet.
- Pistes Banque : plus de `track_programs` ni de CC0/CC32 de slot au tick
  0, l'entête de `_tape` suffit ; notes de grille au canal 10 = 36 + pad,
  selon le canal courant. Nom de la piste SMF = preset de l'entête.

### Ce qui change dans 17f1 (non committé)

- Retirés : les trois listes de `Pattern` et du routeur (R2),
  `set_track_program`, leur copie dans `mw_patterns.py` / `mw_songs.py`,
  les paramètres d'export qui en dépendent.
- Gardés : `rack.py` (slot = emplacement, `gm_program` None pour une
  banque), `channel_after_slot` (une banque garde le canal), libellé de
  piste et `bank_preset_name` (lu sur l'instrument du canal de la piste),
  cache des noms de presets.

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **17e3** | Doc — cette révision. | `docs/DESIGN.md` |
| **17f1** | Implémentation — R1, R3, R7, O1 à O4, O7, O8 : slot = emplacement, instrument par canal tiré des événements, canal porté par le Program Change au rejeu, poursuite, capture au canal de la piste, export. Essayé à l'écoute. | `rack.py`, `track_router.py`, `player/dp_playback.py`, `player/dp_recording.py`, `midi/midi_export.py`, `ui/mw_project.py`, `ui/mw_patterns.py`, `ui/mw_songs.py`, `ui/mw_tracks.py` |
| **17g1** | Tests — 17f1 ; `tests/test_bank_slot.py` et tests d'export adaptés. | `tests/test_bank_slot.py`, `tests/test_midi_export.py`, tests du player au besoin |
| **17h1** | Implémentation — O5, O6, R9 : Alt+Entrée (canal impose l'instrument, écriture des entêtes), dialogue du slot Banque, édition du canal d'un Program Change à 1.1.1 (O3). Essayé à l'écoute. | `ui/dialogs_properties.py`, `ui/dialogs_bank.py` (nouveau), `ui/dialogs_simple.py`, `ui/mw_pads.py`, `ui/mw_tracks.py`, éditeur d'événements |
| **17i1** | Tests — dialogues, temps réel, entêtes, Annuler, Undo. | `tests/test_bank_dialogs.py` (nouveau), fakes au besoin |
| **17j1** | Doc — clôture (avancement 17c1 à 17i1, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 17 — Avancement après les révisions (17f1 à 17i1)

- **17f1** (`025e221`) — conforme à 17e3 (R1, R3, R7, O1-O4, O7, O8) :
  slot Banque = emplacement ; instrument des 16 canaux dans le routeur
  (`channel_instrument`) ; canal courant par piste (`track_channel_now`),
  celui de son dernier Program Change ; `program_change` /
  `bank_select` au canal de l'événement ; `chase(tape, pos)` au
  démarrage, à chaque saut, au changement de pattern, à l'avance du song
  et après Undo ; capture remise au canal de la piste ; export : Bank
  Select avant le Program Change à tick égal, canal qui suit la piste.
  - **Précision de O3** : CC0 et CC32 vont, comme le Program Change, à
    **leur propre canal** (et non au canal courant de la piste), pour
    qu'un entête qui change de canal choisisse la banque du bon canal.
  - Essayé à l'écoute : bon. `pytest` rouge : 28 tests.
- **17f2** (`aac5b79`) — précision de O5 trouvée à l'essai : pendant les
  propriétés de piste, la boucle rejouait l'entête d'origine ; la piste
  est donc copiée et son entête réécrit en direct.
- **17g1** (`a879d35`) — `tests/test_bank_slot.py` réécrit (77 tests) ;
  2467 verts.
- **17h1** (`c2f7df8`) — conforme à O5, O6, R8, R9 et 17f2 : propriétés de
  piste en direct sur une banque (liste du canal, MSB / LSB, entêtes,
  autres pistes du canal, note d'aperçu, Annuler) ; `BankSlotDialog`
  (élément « Banque » d'Alt+X) ; champ Canal des CC et Program Change
  dans l'éditeur MIDI (un Program Change à 1.1.1 donne son canal à la
  piste).
  - **Écart : raccourci.** Le plan disait « Ctrl+T » pour les propriétés
    de piste ; c'est **Alt+Entrée** (ou Ctrl+Maj+T). Ctrl+T assigne le
    slot à la piste. Corrigé dans le plan et dans `SPECS.md`.
  - **Correctif de l'essai : aller-retour de canal.** La basse, seule à
    définir le canal 4, le quittait ; la poursuite remettait ce canal à
    l'état GM (piano) et le retour de la basse imposait le piano. Le
    dialogue retient l'instrument des 16 canaux à son ouverture.
  - Essayé à l'écoute. `pytest` rouge : 28 tests.
- **17i1** (`77fc811`) — `tests/test_bank_dialogs.py` (32 tests), tests de
  l'édition du canal ; 28 tests adaptés ; 2506 verts.

### Clôture (17j1)

**17a1-17i1 FAITS** (commits `ee09786` à `77fc811`, et ce commit de
clôture, 2506 tests verts) : **chantier Phase 7 étape 17 complet**.
L'appli joue les soundfonts SF2 / SF3 par FluidSynth, comme un module GM
dont les pistes sont les musiciens.

**Ce que le chantier a livré** :
- **Moteur de banque** (`src/engines/`) : `BankEngine`, interface étroite
  et portable (cible C/C++), et `FluidSynthEngine` par ctypes, rendu
  dans le callback du pilote ; clés `soundfonts_dir`, `gm_soundfont`,
  `midi_bank_select`, `fluidsynth_gain`.
- **Slot Banque** : un emplacement parmi 4 (un fichier chargé une fois,
  partagé), sauvegardé dans le `.gvp` et l'Undo ; dialogue « Banque »
  de l'Explorateur.
- **Modèle « orchestre »** : le canal est l'instrument ; programme et
  banque sont des événements de la piste (entête à 1.1.1), visibles et
  modifiables ; le Program Change porte le canal de la piste ;
  poursuite à toute position ; canal 10 = batterie.
- **Propriétés de piste en direct** : le canal impose son instrument,
  programme et banque au son près, entêtes réécrits (boucle comprise),
  Annuler.
- **Export** fidèle : Bank Select avant le Program Change, canal qui
  suit la piste, nom du preset.

**Écarts au plan** : deux révisions de fond (17e2, puis 17e3, qui
remplace 17e2), une précision (17f2), le gain par défaut de FluidSynth
(1.0), le chargement sans fil, le raccourci (Alt+Entrée), deux
correctifs trouvés à l'essai ou par les tests (17d2, aller-retour de
canal) ; voir plus haut.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, arborescence
(`src/engines/`, `dialogs_bank.py`), configuration, Rack (type BANK,
`bank_files`), section « Banques de sons », TrackRouter, Program Change,
export, format `.gvp`, boîtes de dialogue, Explorateur, tests ;
`docs/shortcuts.md` : Alt+X, propriétés de piste, édition d'un CC ou
d'un Program Change.

**Restent à essayer** (pas de matériel ou pas encore fait) :
- le jeu au contrôleur MIDI sur une banque (notes, Program Change, Bank
  Select en direct, enregistrement au canal de la piste) ;
- des pistes de deux banques différentes jouées ensemble.

**Laissé hors périmètre, pour la suite** :
- le **SFZ** (sfizz ou AudioSampler + analyseur), derrière la même
  interface ;
- le routage « canal MIDI entrant → slot » et le mode Rack 16 canaux ;
- la poursuite à la reprise d'une boucle qui ne commence pas à 1.1.1 ;
- les noms des cases d'une banque au canal 10 dans l'éditeur MIDI ;
- réverbération, chorus, polyphonie de FluidSynth ;
- **Phase 7 étape 18 : Import MIDI** (le but initial du chantier).

## Phase 7 étape 18a1 — Import MIDI : un fichier `.mid` devient un pattern

### Numérotation des commits de ce chantier

`18a1` = ce plan (doc seule). Le code commence à `18b1`. Une paire impl →
tests par sous-chantier ; `18a2`, `18b2`… pour un commit imprévu.

### Origine du besoin

- But initial du chantier 17 : l'utilisateur voulait d'abord un vrai
  synthé GM (slot Banque, FluidSynth) pour **écouter fidèlement les `.mid`
  importés**. Le chantier 17 est clos (17j1) ; l'import vient maintenant.
- Acquis à respecter :
  - **un `.mid` = un pattern** (Q1 de 17e2, gardée en 17e3) ;
  - **modèle « orchestre »** (17e3) : le canal est l'instrument ; les
    Program Change, CC0 et CC32 d'une piste sont ses événements, l'entête
    à 1.1.1 ; le Program Change porte le canal. O2 annonçait déjà que
    « l'Import MIDI les produira directement » ;
  - l'**export** existe (`src/midi/midi_export.py`, mido, SMF 1, PPQ 480) :
    l'import en est l'inverse, et un aller-retour export → import doit
    rendre le même pattern ;
  - comportement de référence : **Sonar**.

### État des lieux constaté en code (2026-10-29, 2506 tests verts)

- **mido 1.3.3** installé, déjà utilisé par l'export ; aucun code de
  lecture de `.mid` dans l'appli. `InstrumentType.MIDI_FILE` existe dans
  `rack.py` mais n'est utilisé nulle part : sans rapport avec ce chantier
  (slot de lecture de fichier, jamais commencé).
- **Positions** (`pattern.py`) : `TapeEvent.time` = pas cumulés
  (`mesure × _num_steps + pas`). Les notes (GRID, KIT, PATCH) sont posées
  sur un **pas entier** (`dp_recording.py:148`, `:223` ; commentaire de
  `_clipboard_to_dict`, `mw_project.py:404`) ; CC et Pitch Bend sont en
  **temps flottant** (`record_cc`, `record_bend`, Phase 7 étape 5b).
- **Résolution** : `_num_steps` ∈ `VALID_NUM_STEPS = (16, 32, 64, 128)` pas
  par mesure ; `_num_bars` 1..999.
- **Signature** : `_num_beats = 4` et `_denumerator = 4` existent, mais
  **ne sont ni sauvés ni relus** (`to_dict` / `from_dict`) et aucune UI ne
  les change : une mesure fait toujours 4 noires. L'export écrit
  `time_signature 4/4` et convertit `tick = steps × PPQ × 4 / num_steps`.
- **Tempo** : `_bpm` entier par pattern (SpinCtrl 1..600,
  `main_window.py:233`) ; un temps = 60 / BPM (Phase 7 étape 10b1).
- **Durée d'une note PATCH en millisecondes** (`ev.dur`, mesurée au
  note-off ; l'export la convertit au BPM : `ms_ticks`). Une note
  importée doit donc recevoir sa durée en ms au BPM du pattern.
- **16 pistes** par pattern ; `_track_channels` (canal 0..15 par piste),
  `_track_slots`, `_track_volumes` (0..100), `_track_pans` (-100..+100).
  Au rejeu, un CC7 / CC10 de `_tape` règle le volume / pan de la piste
  (`TrackRouter.on_cc_tape`, `track_router.py:835`) ; l'export écrit leur
  inverse exact (`volume_to_cc7`, `pan_to_cc10`).
- **Entête** : `bank_header` / `with_bank_header` (`pattern.py:66-89`) ;
  canal courant d'une piste = celui de son dernier Program Change
  (`TrackRouter.chase`, `track_router.py:505`).
- **Notes sur une banque** : un PATCH est joué tel quel au canal courant
  de la piste, canal 10 compris (`on_patch_tape`, `track_router.py:768`) ;
  l'export garde la note telle quelle. Une note de batterie importée en
  PATCH sonne donc juste au canal 10, avec sa durée.
- **Noms de pistes** : le nom d'une piste (F2, `_rename_track`,
  `mw_tracks.py:206`) est le nom du **pad** du même numéro
  (`voice_manager.get_name`, sauvé dans `Pattern._voices`). Le libellé
  d'une piste Banque affiche le preset de son canal (`bank_preset_name`).
- **Rack** : 16 slots, 4 emplacements de banque (`Rack.bank_files`,
  `set_bank_file`) ; `AppConfig.gm_soundfont` (FluidR3 par défaut).
- **Raccourcis** : Alt+Shift+E = export (fenêtre principale,
  `key_handler_alt.py:83`, et éditeur MIDI, `mew_keymap.py:333`).
  **Alt+Shift+I est libre** dans la fenêtre principale. Dans l'éditeur
  MIDI, le test de Shift+I (limiteur gauche, `mew_keymap.py:267`) ne
  regarde pas Alt : Alt+Shift+I doit être testé **avant** lui.

### Décisions validées (utilisateur, 2026-10-29)

**I1 — Commande.** **Alt+Shift+I** (fenêtre principale et éditeur MIDI,
comme l'export) ouvre un dialogue de fichier `*.mid` / `*.midi`, dans le
dossier EXPORTS (`exports_dir`) par défaut.

**I2 — Destination : le pattern courant** (choix a). S'il n'est pas vide,
une confirmation Oui / Non le dit avant de le remplacer. Un Undo
« Import MIDI : nom.mid » est posé avant ; Non ou une erreur de lecture
le retirent (`_pop_last_undo`). Le pattern est entièrement remplacé :
boucle, mute, solo, voix des pads remis aux valeurs d'un pattern neuf,
puis rempli par l'import. Son nom = nom de la piste conductor, sinon nom
du fichier sans extension.

**I3 — Slot : le premier slot Banque du Rack** (choix a). Toutes les
pistes importées y sont assignées. S'il n'y en a pas, l'import en crée un
dans le **premier slot vide**, avec la soundfont `gm_soundfont` : à
l'emplacement de banque qui la contient déjà, sinon au premier emplacement
libre, sinon à l'emplacement 1 tel qu'il est. Rack plein et sans slot
Banque : import refusé, message dans la barre d'état. Le Rack est dans
l'état de l'Undo : I2 le couvre.

**I4 — Notes arrondies au pas** (choix de l'utilisateur). L'import prend
le plus petit nombre de pas par mesure (16, 32, 64, 128) qui place
**toutes** les notes exactement ; sinon 128 (1/32 de noire), chaque note
arrondie au pas le plus proche, et le compte rendu dit combien de notes
ont bougé. CC, Pitch Bend et Program Change hors entête gardent leur
position exacte (temps flottant). **Chantier suivant prévu : les notes en
temps flottant**, pour une précision complète (voir « Portée exclue »).

**I5 — Noms des pistes : écrits comme noms de pistes F2** (choix b). Le
nom SMF (`track_name`) est nécessaire pour savoir quel instrument doit
jouer la piste. Il va dans le nom du pad du même numéro
(`Pattern._voices[t]["name"]`), avec le mélange pistes / pads connu
(séparation hors périmètre). Un nom vide laisse le nom vide.

**I6 — Pistes.** Une piste Groovebox par couple (piste SMF, canal) qui
porte au moins un événement de canal, dans l'ordre du fichier. Un SMF de
type 0 (une piste, plusieurs canaux) donne donc une piste par canal. Une
piste ne joue que sur un canal à la fois (O3) : c'est pourquoi une piste
SMF à plusieurs canaux est découpée. Plus de 16 pistes : les pistes d'un
même canal sont fusionnées (16 canaux au plus, donc 16 pistes au plus),
nom de la première ; le compte rendu le dit. SMF de type 2 : refusé.
`_track_channels[t]` = canal de la piste.

**I7 — Entête.** Les Program Change, CC0 et CC32 d'une piste **placés
avant sa première note** vont à 1.1.1 (beaucoup de fichiers les posent
quelques ticks après 0), dans l'ordre CC0, CC32, Program Change ; s'il y en
a plusieurs du même type, le dernier l'emporte (comme un module qui les
reçoit dans l'ordre). Chacun garde son propre canal (O3). Après la
première note, ils restent des événements à leur position. Sans Program
Change, pas d'entête : le canal garde l'instrument GM 0 (O1), kit 0 au
canal 10.

**I8 — Volume et pan.** Les CC7 et CC10 placés avant la première note
règlent `_track_volumes` / `_track_pans` (même conversion que
`on_cc_tape` : `round(v × 100 / 127)`, `round((v − 64) × 100 / 63)`), le
dernier l'emportant ; ils ne vont pas dans `_tape`. Ceux d'après restent
des événements CC. Un export suivi d'un import rend ainsi le même volume
et le même pan.

**I9 — Événements.**
- note on / note off (note on de vélocité 0 = note off) → **ETYPE_PATCH**
  (note, vélocité), position arrondie (I4), durée en ms au BPM du pattern
  (au moins 1 ms) ; appariement premier entré, premier sorti pour une même
  note ; note jamais fermée = fermée à la fin de sa piste ;
- control change → **ETYPE_CC**, CC91 / CC93 compris (tels quels) ;
- pitchwheel → **ETYPE_BEND** ;
- program change → **ETYPE_PGM** ;
- le champ `channel` de chaque événement = son canal MIDI ;
- ignorés et comptés dans le compte rendu : aftertouch de canal et
  polyphonique (pas d'etype), SysEx (dont les reset GM / GS), métas autres
  que nom de piste, tempo, signature et fin de piste.

**I10 — Tempo, signature, longueur.**
- BPM = premier `set_tempo` (arrondi, borné 1..600), 120 sans tempo (défaut
  MIDI). Les changements de tempo suivants sont ignorés et comptés : les
  positions en noires ne dépendent pas du tempo ; seul le rythme change.
- Signature : la mesure reste de 4 noires (`_num_beats` n'est pas
  sauvé) ; une autre signature est annoncée dans le compte rendu, les
  événements gardent leur position en noires.
- Conversion : `steps = tick × num_steps / (PPQ du fichier × 4)`.
- Longueur : `_num_bars` = fin la plus tardive (dernier note-off ou
  `end_of_track` de la piste la plus longue), arrondie à la mesure
  supérieure, bornée 1..999 ; au-delà de 999 mesures, les événements sont
  perdus, et comptés.

**I11 — Après l'import.** Pattern rechargé comme un changement de pattern
(poursuite O4 comprise), listes et grille rafraîchies, projet marqué
modifié (par l'Undo). Compte rendu dans la barre d'état, par exemple :
« Import MIDI : song.mid → Pattern 03, 8 pistes, 32 mesures, 96 BPM,
128 pas ; 12 notes déplacées ; ignorés : 40 aftertouch, 2 SysEx ».

**I12 — Code.** `src/midi/midi_import.py`, sans wx ni player (comme
l'export) : `build_pattern_from_midi(mid, *, name)` rend un `Pattern`
neuf (avec `_track_channels`, volumes, pans, noms dans `_voices`) et un
compte rendu ; le choix du slot (I3), le remplacement du pattern, l'Undo
et l'UI vont dans `ui/mw_project.py` (`_import_midi`, à côté de
`_export_midi`).

### Alternatives écartées

- Destination : premier pattern vide, ou dialogue de choix (I2) ;
- slot : slot courant seulement, ou dialogue de choix (I3) ;
- noms SMF ignorés, ou séparation préalable des noms pistes / pads (I5) ;
- notes en temps flottant dès ce chantier (I4) : chantier à part ;
- notes de batterie en ETYPE_KIT : one-shot d'un pas, la durée se
  perdrait ; ou en cases de grille (pads) : il faudrait un kit et une
  table note → pad. PATCH joue juste sur une banque, au canal 10 compris ;
- une piste Groovebox par piste SMF sans découpage par canal :
  incompatible avec O3 (une piste joue sur un canal à la fois).

### Portée explicitement exclue de ce chantier

- **Notes en temps flottant** (grille, piano roll, liste des événements,
  quantisation, presse-papier, enregistrement) : **chantier suivant**,
  demandé par l'utilisateur ;
- import d'un song ou de plusieurs patterns, carte de tempo, signatures
  autres que 4/4 (il faudrait d'abord sauver `_num_beats`) ;
- import sur un slot synthé WAV ou kit, conversion des notes de batterie
  en pads ;
- séparation des noms de pistes et des noms de pads ;
- aftertouch, SysEx, réverbération / chorus de FluidSynth ;
- routage « canal → slot », mode Rack 16 canaux.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **18a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **18b1** | Implémentation — `midi_import.py` : I4, I6 à I10 (lecture, pistes, entêtes, volume / pan, événements, tempo, longueur, compte rendu). | `src/midi/midi_import.py` (nouveau) |
| **18c1** | Tests — fichiers construits avec mido ; aller-retour export → import ; type 0 ; plus de 16 pistes ; arrondi ; entête décalé ; notes non fermées. | `tests/test_midi_import.py` (nouveau), `docs/SPECS.md` (liste des tests) |
| **18d1** | Implémentation — I1 à I3, I5, I11 : Alt+Shift+I (deux fenêtres), dialogue, confirmation, slot Banque, remplacement du pattern, Undo, compte rendu. Essayé à l'écoute sur de vrais `.mid`. | `ui/mw_project.py`, `ui/key_handler_alt.py`, `ui/mew_keymap.py` |
| **18e1** | Tests — commande, slot trouvé / créé / Rack plein, Undo, Non, erreur de lecture. | `tests/test_midi_import_ui.py` (nouveau), fakes au besoin |
| **18f1** | Doc — clôture (avancement, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 18 — Avancement et écarts constatés

- **18b1** — `src/midi/midi_import.py` : `build_pattern_from_midi(mid,
  *, name)` → `(Pattern, ImportReport)`, `import_pattern(path)` ;
  `ImportReport.details()` donne les remarques du compte rendu (I11).
  Conforme à I4, I6 à I10. Essayé sur un aller-retour export → import et
  sur dix vrais `.mid` (types 0 et 1, batterie seule, 3/4, fichier abîmé).
  Précisions trouvées à l'essai :
  - **SMF de type 0** : le nom de son unique piste est le nom du morceau ;
    il devient le nom du **pattern**, et les pistes (une par canal)
    restent sans nom (sinon elles porteraient toutes le même).
  - **Lecture tolérante** (`clip=True`) : un fichier abîmé (octet de
    données hors 0..127) que mido refusait se lit, l'octet ramené à 127.
  - **Noms** sans les espaces de début et de fin (`"Bass  "`).
  - L'export écrit CC91 et CC93 à 0 au tick 0 (12a1 D3) : réimportés, ils
    restent des événements CC (I9), sans effet sur le rendu ; un nouvel
    export les écrit deux fois au tick 0.
  - Le pan revient à ±1 près (`pan_to_cc10`, 127 valeurs pour 201
    positions) ; le volume revient exact.
- **18c1** — `tests/test_midi_import.py` (62 tests), fichiers construits
  avec mido ; `SPECS.md` (arborescence, liste des tests). 2568 verts.
- **18d1** — `_import_midi` et `_import_bank_slot` (`ui/mw_project.py`),
  Alt+Shift+I dans les deux fenêtres (dans l'éditeur MIDI, testé avant
  Shift+I). Conforme à I1-I3, I5, I11.
  - **Écart : le fichier est lu avant toute question.** Une erreur de
    lecture ne pose ni confirmation ni Undo (le plan disait : Undo posé,
    puis retiré). Même résultat, plus simple.
  - Lecture arrêtée avant le remplacement (`stop_all`), comme Ctrl+N.
  - Essayé à l'écoute (utilisateur, 2026-10-29) sur `bach_01.mid` et
    `recado.mid` : toutes les notes et tous les instruments y sont.
    **Problème de pédale trouvé**, qui ne vient pas de l'import mais du
    rejeu du CC64 sur une banque (chantier 17) : voir l'avenant 18d2.
  - Undo d'un import qui avait créé le slot Banque : FluidSynth écrit
    « No preset found » pour les 16 canaux dans le terminal
    (`fluid_synth_sfunload` avec remise des presets, dernière soundfont
    déchargée). Sans effet sur le son ; vrai de tout Undo qui retire la
    dernière banque.

## Phase 7 étape 18d2 — Avenant : pédale, Pitch Bend et modulation des banques, à l'arrêt et à la poursuite

### Origine

Essai à l'écoute de 18d1 (utilisateur, 2026-10-29) :
- `bach_01.mid` (une piste de piano, CC64 enfoncé puis relâché à chaque
  mesure) « saute » ou démarre mal sur la première mesure ;
- `recado.mid`, importé ensuite **sans relancer l'appli**, est joué
  avec un « gros problème de pédale sustain », alors qu'il n'enfonce
  jamais la pédale (trois CC64 à 0, à la toute fin).

L'utilisateur et Claude concluent au même diagnostic : une pédale de Bach
restée enfoncée, qui brouille le début de Bach à la relance et tout
Recado. Ce n'est pas l'import : c'est le rejeu du CC64 sur une banque
(chantier 17), que les vrais `.mid` révèlent.

### État des lieux constaté en code (après 18d1, 2568 tests verts)

- **CC64 rejoué = pédale globale.** `TrackRouter.on_cc_tape` traite le
  CC64 avant tout autre test (`track_router.py:853`) par
  `set_sustain(value >= 64)` (`:715`), qui l'envoie aux **16 canaux** de
  FluidSynth et à tous les synthés WAV. La pédale du piano tient aussi
  les autres instruments : contraire au modèle « orchestre » (17e3 O1),
  où chaque canal est un instrument.
- **Rien ne relâche la pédale à l'arrêt.** `stop_pattern`,
  `pause_pattern` et `stop_all` (`player/dp_transport.py`) n'appellent pas
  le routeur ; il n'existe pas de rappel « fin de lecture ». Les notes
  d'une banque s'arrêtent d'elles-mêmes (durée), et la pédale reste
  enfoncée dans FluidSynth.
- **La poursuite ignore la pédale.** `TrackRouter.chase`
  (`track_router.py:505`) rejoue PGM, CC0 et CC32 jusqu'à la position,
  rien d'autre. Une pédale enfoncée le reste d'une lecture à l'autre, et
  d'un pattern à l'autre.
- Pitch Bend et modulation d'une banque vont déjà au canal courant de la
  piste (`on_bend_tape`, `on_mod_tape`, `:800`, `:819`), mais ne sont, eux
  non plus, ni remis à zéro à l'arrêt ni poursuivis.
- Jeu en direct : `midi_handler_window.py:235` appelle aussi
  `set_sustain` (pédale du contrôleur sur tous les canaux).

### Comportement de Sonar (vérifié le 2026-10-29)

Vérifié sur les forums de Cakewalk (discuss.cakewalk.com : fils 38483,
38778, 90109, 44964, 9246) ; aucune page officielle à jour trouvée :
- **Zero Controllers When Play Stops** (Préférences > Projet > MIDI) : à
  l'arrêt, pitch wheel, pédale sustain et molette de modulation à zéro
  sur les 16 canaux. Sans cette option, arrêter avant le retour du CC64 à
  0 laisse des notes tenues (fil 38778) : notre cas.
- **MIDI Event Chase on Play** (même page ; « Patch/Controller
  Searchback » jusqu'à Sonar 4) : au démarrage, renvoie par canal les
  derniers programme, pitch wheel, pédale et contrôleurs avant la
  position.

### Décisions validées (utilisateur, 2026-10-29)

**P1 — Le CC64 d'une piste Banque va au canal courant de la piste
seulement**, comme les autres CC. Il est envoyé même si la piste est
muette ou hors solo, pour qu'un relâchement ne se perde jamais (comme
aujourd'hui, où le CC64 passe avant le test de mute). Les pistes sur
synthé WAV gardent la pédale globale (`set_sustain`).

**P2 — Arrêt = Zero Controllers.** À l'arrêt et à la pause de la
lecture (Espace, Pause, `stop_pattern`, `pause_pattern`, `stop_all`), le
routeur met à zéro, sur les 16 canaux du moteur de banque : pédale
(CC64 = 0), Pitch Bend (centre) et modulation (CC1 = 0). Le player
reçoit pour cela un rappel `_on_play_stop_cb`, symétrique de
`_on_play_start_cb` (17f1), appelé seulement si une lecture tournait.

**P3 — Poursuite étendue (Event Chase).** `chase(tape, pos)` reprend
aussi, pour chaque canal, la **dernière pédale (CC64), le dernier Pitch
Bend et la dernière modulation (CC1)** des pistes Banque avant la
position, sinon zéro. Le canal d'un tel événement est le canal courant
de sa piste à son instant (celui de son dernier Program Change, O3),
calculé dans la même passe. Comme la poursuite a lieu au démarrage, à
chaque saut, au changement de pattern, à l'avance du song et après
Undo, une pédale restée enfoncée ne survit plus à une relance.

### Portée exclue

- Pédale du **contrôleur en direct** (`midi_handler_window.py:235`) :
  reste globale ; à revoir avec le routage par canal du jeu en direct.
- Poursuite des autres contrôleurs (CC7 / CC10 sont déjà le mixage de la
  piste ; CC91, CC93 et autres) et des notes (« Include Note Events »).
- Synthés WAV : ni remise à zéro à l'arrêt ni poursuite nouvelles.

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **18d2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **18d3** | Implémentation — P1 à P3. Essayé à l'écoute : Bach arrêté pédale enfoncée, puis Recado, sans relancer l'appli. | `track_router.py`, `player/dp_transport.py`, `player/drum_player.py`, `ui/main_window.py` |
| **18e1** | Tests — interface de l'import (18d1) et P1 à P3. | `tests/test_midi_import_ui.py` (nouveau), `tests/test_bank_slot.py`, fakes au besoin |
| **18f1** | Doc — clôture. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 18 — Avancement après l'avenant (18d3)

- **18d3** — P1 à P3 conformes à 18d2 : CC64 d'une piste Banque au canal
  courant de la piste (`on_cc_tape`) ; `TrackRouter.on_play_stop`, appelé
  par le nouveau rappel `_on_play_stop_cb` du player à l'arrêt, à la
  pause, et quand la lecture s'arrête d'elle-même (fin d'un pattern sans
  boucle, du song, des répétitions) ; `chase` étendu à la pédale, au Pitch
  Bend et à la modulation. Essayé à l'écoute (utilisateur, 2026-10-29) :
  Recado n'est plus noyé dans la pédale. Trois corrections de plus,
  trouvées à l'essai :
  - **Ordre des événements simultanés** (`dp_playback.py`, défaut du
    rejeu depuis le chantier 4) : `events.sort()` triait aussi sur les
    données, donc les CC d'un même instant par numéro. À 1.1.1 de
    `bach_01.mid`, les deux CC121 (Reset All Controllers) passaient après
    le CC64 = 127 et relâchaient la pédale : première mesure piquée, notes
    coupées. Tri stable sur (temps, marqueur) : l'ordre de `_tape` est
    gardé.
  - **Saut de lecture avec Haut / Bas sur la liste des pistes** :
    `Pattern.grid_row` cherchait chaque case en parcourant toute la piste
    (16 × 128 cases × 2715 notes sur la guitare de `survive1.mid`) :
    321 ms de thread UI par changement de piste, callback audio en retard,
    9 sous-alimentations en 3 s. Un seul passage par ligne : 2,8 ms,
    aucune sous-alimentation.
  - **Dossier de l'import retenu** pour la session (`_import_dir`), sinon
    EXPORTS ; pas d'une session à l'autre, `config.json` étant en lecture
    seule.

### Phase 7 étape 18d4 — Avenant : gain de FluidSynth, mesure vide initiale

Essai de `survive1.mid` (dix pistes, karaoké ; utilisateur, 2026-10-29) :

- **Saturation.** L'appli joue nettement plus fort que TiMidity et
  sature par moments. Rendu hors appli de deux minutes du morceau, avec
  les CC7 du fichier : au gain 1.0 (défaut de 17b1, validé sur quatre
  pistes à côté des pads WAV), crête 2,95 et 43,5 % des blocs écrêtés ;
  à 0.5, crête 1,47 (0,8 %) ; à 0.4, crête 1,18 (0,1 %). Le pilote
  écrête net (`np.clip`, `sound_device_driver.py:212`).
  **Décision (utilisateur) : défaut de `fluidsynth_gain` à 0.4** « pour
  l'instant ». Alternative écartée pour ce chantier : un limiteur doux
  sur la sortie générale (plus de code dans le pilote, à refaire dans le
  moteur natif) ; à reprendre s'il manque de niveau.
- **Mesure vide au début.** TiMidity commence tout de suite ; l'appli
  joue d'abord une mesure vide. Elle est dans le fichier (première note
  à la mesure 2, un seul tempo) ; TiMidity supprime le silence initial
  par défaut (son aide : « Default: drop initial silence »,
  `--preserve-silence`). **L'import reste fidèle**, comme Sonar, qui
  ouvre le fichier tel quel ; Ctrl+G permet de partir de la mesure 2.
- **Ralenti final de `bach_01.mid`** (60 changements de tempo) : carte de
  tempo, hors périmètre (18a1), chantier futur.
- **18d4** (`02ee85d`) — gain de FluidSynth par défaut à 0.4 ; `pytest`
  rouge : 6 tests de l'ancien défaut.
- **18e1** — `tests/test_midi_import_ui.py` (25 tests : slot Banque,
  dialogue et dossier retenu, annulation, erreur de lecture, Rack plein,
  confirmation, remplacement, noms, Undo, compte rendu, Alt+Shift+I dans
  les deux fenêtres) ; P1 à P3 et rappel de fin de lecture dans
  `tests/test_bank_slot.py` (17 tests) ; ordre de `_tape` à temps égal et
  rappel aux arrêts automatiques dans `tests/test_playback_loop.py` ;
  `grid_row` dans `tests/test_pattern_grid_api.py` ; 6 tests du gain
  adaptés. Chaque correction de 18d3 défaite à l'essai fait échouer au
  moins un test. 2620 verts.
- **18d5** — Ajout demandé avant la clôture (utilisateur, 2026-10-29) :
  **l'import place le lecteur au début** (`goto_start` après l'arrêt,
  avant le chargement du pattern, donc poursuite depuis 1.1.1). Arrêté,
  le player garde sa position (`_resume_offset`) : `bach_01.mid` importé
  après `survive1.mid` reprenait au milieu, à la position où ce dernier
  avait été arrêté.
- **18e2** — 2 tests de 18d5 dans `tests/test_midi_import_ui.py` (lecteur
  remis au début et poursuite depuis 1.1.1 ; position gardée si Non). 2622
  verts.

### Clôture (18f1)

**18a1-18e2 FAITS** (commits `f78408f` à `c8fbe05`, et ce commit de
clôture, 2622 tests verts) : **chantier Phase 7 étape 18 complet**. Un
fichier `.mid` s'ouvre dans le pattern courant et se joue par FluidSynth,
avec ses instruments, sa pédale et ses noms de pistes.

**Ce que le chantier a livré** :
- **`src/midi/midi_import.py`**, sans wx ni player, inverse de l'export :
  pistes par (piste SMF, canal), fusion au-delà de 16, entête à 1.1.1,
  volume et pan de piste, notes PATCH arrondies au pas, CC / Pitch Bend /
  Program Change en temps flottant, tempo, longueur, compte rendu ;
  lecture tolérante d'un fichier abîmé.
- **Alt+Shift+I** (fenêtre principale et éditeur MIDI) : dialogue
  (dernier dossier retenu), confirmation, slot Banque trouvé ou créé,
  pattern courant remplacé, noms de pistes, lecteur à 1.1.1, Undo,
  compte rendu au statut.
- **Rejeu des banques, comme Sonar** (avenant 18d2) : pédale au canal de
  la piste, Zero Controllers à l'arrêt, poursuite de la pédale, du Pitch
  Bend et de la modulation.
- **Trois défauts plus anciens, révélés par les vrais fichiers** :
  événements simultanés rejoués dans le désordre (chantier 4), grille
  recalculée case par case qui faisait sauter la lecture, gain de
  FluidSynth qui écrêtait un orchestre (1.0 → 0.4).

**Écarts au plan** : fichier lu avant toute question (18d1) ; nom d'un
SMF de type 0 donné au pattern, lecture tolérante, noms nettoyés (18b1) ;
l'avenant 18d2 et les corrections 18d3, le gain (18d4), le lecteur remis
au début (18d5) ; voir plus haut.

**Règle de travail confirmée** : pour reproduire Sonar, dire d'où vient
l'information (de mémoire ou vérifiée) et la vérifier avant d'en faire
une décision (§ 18d2, « Comportement de Sonar »).

**`docs/SPECS.md` mis à jour** : ligne Phase 7, outils, arborescence,
configuration (gain, dossier d'import), section « Banques de sons »
(pédale, arrêt, poursuite, ordre), nouvelle section « Import MIDI
(Alt+Shift+I) », tests ; `docs/shortcuts.md` : Alt+Shift+I dans les deux
fenêtres.

**Laissé hors périmètre, pour la suite** :
- **notes en temps flottant** (demandé par l'utilisateur, puis **reporté,
  non urgent** : l'import au pas marche bien ; corrigé en 19a1) : l'arrondi
  au pas déplace des milliers de notes jouées à la main ;
- **carte de tempo** : changements de tempo (ralenti final de
  `bach_01.mid`), signatures autres que 4/4 (`_num_beats` à sauver
  d'abord) ;
- limiteur doux sur la sortie générale, si le gain 0.4 manque de niveau ;
- dossier d'import gardé d'une session à l'autre (avec le dialogue de
  configuration, `config.json` étant en lecture seule) ;
- pédale du contrôleur en direct, qui reste globale ;
- réverbération et chorus de FluidSynth (CC91 / CC93 des fichiers) ;
- aftertouch, SysEx ; import d'un song ou de plusieurs patterns ;
  séparation des noms de pistes et des noms de pads ;
- message « No preset found » de FluidSynth quand un Undo retire la
  dernière banque (sans effet sur le son).

## Phase 7 étape 19a1 — Carte de tempo : plusieurs tempos par pattern

### Numérotation des commits de ce chantier

`19a1` = ce plan (doc seule). Le code commence à `19b1`. Une paire impl →
tests par sous-chantier ; `19a2`, `19b2`… pour un commit imprévu.

### Origine du besoin

- Essai de l'Import MIDI (Phase 7 étape 18) : TiMidity joue le ralenti
  final de `bach_01.mid` (60 changements de tempo, de 92 à 94 BPM puis
  plus lent), que l'appli ignore : un seul BPM par pattern, le premier.
- L'utilisateur demande la carte de tempo comme chantier suivant
  (2026-10-29) ; les notes en temps flottant sont reportées.

### Comportement de Sonar (vérifié le 2026-10-29)

Forums de Cakewalk (discuss.cakewalk.com, fils 19746, 38042, 89704,
29073, 2341) ; aucune page officielle à jour trouvée :
- **Insert Tempo** (menu Project) : un dialogue propose soit de
  **modifier le tempo en vigueur** à la position, soit d'**insérer un
  nouveau tempo** ; la position est celle du curseur, modifiable.
- Un changement de tempo en cours de morceau **décale toutes les barres de
  mesure qui suivent** (dans le temps réel).
- Un tempo égal au précédent est supprimé (redondant).
- Sonar connaît les **rampes** (le tempo glisse jusqu'au suivant).
- **Non trouvé** : ce que fait le champ de tempo de la barre de transport
  quand une carte existe ; aucune décision ne s'appuie dessus.

### État des lieux constaté en code (2026-10-29, 2622 tests verts)

- **Temps linéaire partout.** `DrumPlayer.step_duration = 60 ·
  _num_beats / (bpm · _num_steps)` (`player/drum_player.py:163`) ; toute
  conversion pas ↔ secondes est `pas × step_duration` ou `secondes /
  step_duration`, une soixantaine d'endroits :
  - lecture : `_run_thread`, `_build_measure_events` (`t_sec`), durée de
    la boucle, Note Repeat, décompte (`player/dp_playback.py`) ;
  - position : `_current_offset`, `position_str`, `navigate_bar`, saut en
    secondes (`player/dp_position.py`) ; pause (`dp_transport.py:93`) ;
  - enregistrement (`dp_recording.py:86`, `:111`), effacement
    (`dp_erase.py`) ;
  - métronome (`metronome.py:42`, reçoit `step_duration`) ;
  - dialogues : Aller à, sélection de boucle et de pistes, en secondes
    (`ui/dialogs_temporal.py`, `mw_patterns.py:231`, `song_window.py:252`,
    `mew_quantize.py:79`) ;
  - millisecondes par pas : quantisation des durées
    (`quantize_manager.py:138`), insertion au pavé numérique
    (`ui/mew_numpad.py:22`), dialogue d'insertion (`midi_editor_dialogs.py:131`).
- **Le BPM** : `Pattern._bpm` (entier), `DrumPlayer.bpm`, `set_bpm`
  (`dp_transport.py:144`, réveille le thread) ; champ BPM (SpinCtrl
  1..600, `main_window.py:234`, sans Undo), Tap Tempo (avec Undo) et ±5
  (`key_handler_chars.py:191`, `:351`) ; en mode song, le BPM du pattern
  suivant est repris à l'avance (`dp_playback.py:268`, `:282`).
- **Positions** : `TapeEvent.time` en pas cumulés ; toutes les mesures ont
  le même nombre de pas, la mesure fait 4 noires (`_num_beats` n'est ni
  sauvé ni modifiable).
- **Durées des notes en millisecondes** (PATCH, cases de grille sans durée
  propre : durée du pad) : indépendantes du tempo au rejeu.
- **Opérations qui déplacent le temps du pattern** : `resize` (change de
  `_num_steps`), `double_bars`, `halve_bars`, `copy_from` (ne copie pas
  le BPM : le player le reçoit à part), `to_dict` / `from_dict`.
- **Export** : un seul `set_tempo` au tick 0 ; durées ms → ticks au BPM
  unique (`ms_ticks`, `midi_export.py:138`).
- **Import** : premier tempo seul, changements suivants comptés et
  ignorés ; durées ticks → ms au BPM unique (`midi_import.py`).
- **Liste des événements** (Ctrl+2, `MidiEditor.get_all_events`,
  `midi/midi_editor.py:163`) : lignes (dictionnaires) tirées de `_tape`
  des pistes sélectionnées ; rien hors des pistes.
- **Alt+Shift+T** est libre dans la fenêtre principale et dans l'éditeur
  MIDI (Ctrl+Shift+T = propriétés de piste, Ctrl+T = assigner le slot).

### Décisions validées (utilisateur, 2026-10-29)

**T1 — Périmètre : le tempo seulement** (choix a). La mesure reste de 4
noires ; une signature par pattern, puis ses changements, feront un
autre chantier (ils touchent au codage des positions).

**T2 — Carte de tempo par pattern.** `Pattern._bpm` reste le **tempo de
départ** ; `Pattern._tempo_changes` = liste triée de `(position en pas,
BPM)`, position > 0, flottante (exacte depuis un import, comme un CC).
BPM **entier** 1..600, comme le champ BPM. Un changement égal au tempo
qui le précède est retiré (Sonar). Sauvé dans le `.gvp` (clé
`"tempo_changes"`, absente = aucun changement) et donc dans l'Undo ;
copié par `copy_from`, recalé par `resize`, `double_bars` et
`halve_bars`, comme les événements.

**T3 — Changements instantanés.** Comme dans un fichier MIDI ; un ralenti
est une suite de changements. Les rampes de Sonar sont exclues.

**T4 — `TempoMap`** (`src/tempo_map.py`, sans wx ni player, portable
C/C++) : construite depuis le tempo de départ, les changements et le
nombre de pas par noire ; `secs(pas)` (secondes depuis 0, linéaire par
morceaux), `steps(secs)` (inverse), `bpm_at(pas)`. Le player garde la
carte du pattern joué et l'utilise à la place de `step_duration` partout
(durée de la boucle = `secs(fin) − secs(début)`). **À tempo unique, mêmes
résultats qu'aujourd'hui** : les 2622 tests restent verts sans
adaptation de fond.

**T5 — Durées des notes : toujours en millisecondes.** L'import les
calcule au tempo en vigueur au début de chaque note, l'export les
reconvertit de même ; les millisecondes par pas (quantisation, pavé
numérique, dialogue d'insertion) prennent le tempo de la position.

**T6 — Import et export.** L'import garde tous les changements de tempo
(ils ne sont plus « ignorés » au compte rendu, qui dit combien il en a
lus) ; l'export écrit chaque changement dans la piste conductor. Un
aller-retour rend la même carte.

**T7 — Champ BPM, Tap Tempo, ±5 : le tempo en vigueur à la position
courante** (choix a ; le « modifier le tempo en vigueur » de Sonar).
Arrêté à 1.1.1, c'est le tempo de départ. Après un déplacement de la
position à l'arrêt (Aller à, mesure suivante ou précédente, début, fin),
le champ affiche le tempo de la position ; **pas pendant la lecture**
(pas de bavardage du lecteur d'écran). Tap Tempo garde son Undo ; le
champ et ±5 restent sans Undo, comme aujourd'hui.

**T8 — Dialogue « Tempo » (Alt+Shift+T, deux fenêtres)** (choix c, avec
T9). Liste des tempos du pattern : « 1.1.1 — 92 BPM » (départ), puis un
élément par changement, position en mesure.temps.pas. Boutons : **Insérer**
(à la position courante, position et BPM modifiables avant validation),
**Modifier** (BPM et position de l'élément ; le départ : BPM seul),
**Supprimer** (pas le départ), **Fermer**. Clavier : Entrée = Modifier,
Suppr = Supprimer, Échap = Fermer. Un Undo par changement (« Tempo :
insérer 80 BPM à 33.1.1 »). En lecture, un changement est entendu aussitôt
(réveil du thread, position gardée).

**T9 — Liste des événements (Ctrl+2).** Les tempos y apparaissent en tête
de chaque position, comme une piste « Tempo » (conductor), quelles que
soient les pistes sélectionnées : « Tempo 80 BPM ». Entrée les modifie (BPM,
position), Suppr les supprime (pas le départ), avec Undo ; le filtre
d'événements (Ctrl+Shift+F) gagne le type « Tempo ». Pas de copie /
duplication / insertion de tempo depuis la liste : le dialogue s'en charge.

**T10 — Mode song.** Chaque pattern joue avec sa propre carte ; à
l'avance du song, la carte du pattern suivant remplace la courante.

### Portée explicitement exclue de ce chantier

- **Signatures** (une par pattern, puis leurs changements) : chantier à
  part (T1) ;
- **rampes** de tempo (T3) ; BPM décimaux ;
- tempo dans le piano roll (Ctrl+1) ;
- Undo du champ BPM et de ±5 (inchangés) ;
- notes en temps flottant (reportées, non urgentes).

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **19a1** | Doc — ce plan ; correction de la clôture 18f1 (notes en temps flottant reportées). | `docs/DESIGN.md` |
| **19b1** | Implémentation — T2, T4, T6 : `TempoMap`, `_tempo_changes` (`.gvp`, `copy_from`, `resize`, doubler / diviser), import et export avec la carte, durées au tempo local (T5). | `src/tempo_map.py` (nouveau), `pattern.py`, `midi/midi_import.py`, `midi/midi_export.py` |
| **19c1** | Tests — 19b1 ; aller-retour export → import de la carte. | `tests/test_tempo_map.py` (nouveau), `tests/test_midi_import.py`, `tests/test_midi_export.py`, `docs/SPECS.md` |
| **19d1** | Implémentation — T4 dans le player (lecture, boucle, position, pause, enregistrement, effacement, métronome, décompte, Note Repeat), T5 (ms par pas), T7, T10, dialogues en secondes. Essayé à l'écoute (ralenti de Bach). | `player/*.py`, `metronome.py`, `quantize_manager.py`, `ui/main_window.py`, `ui/key_handler_chars.py`, `ui/dialogs_temporal.py`, `ui/mew_numpad.py`, `ui/midi_editor_dialogs.py`, `ui/mw_patterns.py`, `ui/mw_songs.py` |
| **19e1** | Tests — 19d1 (à tempo unique, rien ne change ; avec changements, positions, boucle, enregistrement, song). | `tests/test_tempo_playback.py` (nouveau), tests existants au besoin |
| **19f1** | Implémentation — T8, T9 : dialogue Tempo (Alt+Shift+T, deux fenêtres), tempos dans la liste des événements (affichage, Entrée, Suppr, filtre), Undo. Essayé au lecteur d'écran. | `ui/dialogs_tempo.py` (nouveau), `ui/key_handler_alt.py`, `ui/mew_keymap.py`, `midi/midi_editor.py`, `ui/mew_*.py`, `ui/midi_editor_dialogs.py` |
| **19g1** | Tests — 19f1. | `tests/test_tempo_dialog.py` (nouveau), `tests/test_midi_editor*.py` |
| **19h1** | Doc — clôture (avancement, SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 19 — Avancement et écarts constatés

- **19b1** — `src/tempo_map.py` (`TempoMap`, `normalize_changes`,
  `clamp_bpm`) ; `Pattern._tempo_changes` (`.gvp` : `"tempo_changes"`),
  `tempo_map()`, `set_tempo_changes()`, `steps_per_beat()` ; recalés par
  `copy_from`, `resize`, `double_bars` (la seconde moitié repart du tempo
  de départ), `halve_bars` ; vidés par `new_pattern` (Nouveau pattern),
  **gardés par `reset_pattern`** (Shift+Suppr n'efface que les notes).
  Import : tempo de départ = dernier tempo au tick 0, sinon 120 jusqu'au
  premier ; chaque tempo suivant devient un changement ; durées au tempo
  local ; le compte rendu dit « N changements de tempo » (plus
  « ignorés »). Export : un `set_tempo` par changement dans la piste
  conductor, fin de note au tempo local (`end_tick`). À tempo unique,
  tous les tests de l'export passent sans changement.
  - Essai sur `bach_01.mid` : 60 changements, de 92 à 40 BPM ; durée
    jusqu'au dernier événement 98,30 s, comme mido ; notes identiques
    après export puis import.
  - **Limite de résolution** : un changement placé à une position que PPQ
    480 ne représente pas (fichier à PPQ 256, un tick avant la mesure)
    revient décalé de 1/600 de pas après export puis import, comme un CC.
  - `pytest` rouge : 2 tests de l'import attendaient « changements de
    tempo ignorés ».
- **19c1** — `tests/test_tempo_map.py` (42 tests : `clamp_bpm`,
  `normalize_changes`, `TempoMap` — à tempo unique, l'ancien calcul
  linéaire —, changements du pattern, import, export, aller-retour exact
  d'une carte faite dans l'appli) ; 2 tests de l'import adaptés (« N
  changements de tempo » ; un tempo pile à la fin du pattern est écarté).
  Quatre défauts de 19b1 réintroduits à l'essai : chacun fait échouer au
  moins un test. 2664 verts.
- **19d1** — le player suit la carte (T4) : `DrumPlayer.tempo_map()` (en
  cache), `_position_at` (position dans la fenêtre en cours, utilisée par
  la position, la pause, l'enregistrement et l'effacement),
  `_t_to_offset`, `_measure_clock` (durée de la fenêtre et minutage des
  événements, du métronome et du Note Repeat ; pendant le décompte, tempo
  de la position de reprise) ; dialogue Aller à en secondes par la carte ;
  ms par pas au tempo de la position (quantisation des durées, grille de
  l'éditeur MIDI, dialogue d'édition de note) ; mode song (carte du pattern
  suivant). T7 tel que planifié : champ BPM, Tap Tempo et ±5 modifient le
  tempo en vigueur (`set_tempo_at`), affiché après un déplacement à
  l'arrêt (`_on_stopped_move_cb`) et à l'arrêt de la lecture.
  - **Ajout : un changement de tempo en lecture garde la position
    musicale** (`_keep_position`, le thread se recale) ; avant, changer le
    BPM en lecture faisait sauter la position.
  - **Défauts plus anciens corrigés au passage** :
    - le pattern du player gardait `_bpm = 100` (jamais mis à jour) : le
      dialogue d'édition de note et la grille de l'éditeur MIDI
      convertissaient les durées à 100 BPM ; `set_bpm` et l'avance du song
      le tiennent maintenant à jour ;
    - avec une boucle qui ne commence pas à 1.1.1, l'enregistrement,
      l'effacement et le Note Repeat calculaient la position comme si la
      boucle commençait au début du pattern (d'après le code) ; ils
      passent par `_position_at` / `_t_to_offset` ;
    - une reprise à l'intérieur d'une telle boucle repartait décalée ;
      elle repart exactement à sa position.
  - Essai sans le son : de la mesure 34 à la fin de `bach_01.mid`, 15,31 s
    joués pour 15,30 s prévus (7,83 s à 92 BPM constant), notes à moins
    d'1 ms. **Essayé à l'écoute (utilisateur, 2026-10-29) : le ralenti de
    Bach s'entend bien.** Mais T7 ne permet pas de ralentir tout le
    morceau pour l'étudier : voir l'avenant 19d2.
  - `pytest` rouge : 1 test (`test_bpm_increase_via_key5`, fausse fenêtre
    sans `tempo_at` / `set_tempo_at`), plus un second qui n'échoue qu'à sa
    suite (application wx laissée ouverte).

## Phase 7 étape 19d2 — Avenant : ralentir tout le morceau, tempos décimaux

### Origine

Essai à l'écoute de 19d1 (utilisateur, 2026-10-29) : le ralenti de
`bach_01.mid` s'entend bien, mais avec T7 (le champ BPM ne change que le
tempo en vigueur à la position), un morceau à plusieurs tempos ne peut pas
être ralenti d'un seul geste. Or **ralentir un morceau pour l'étudier et
en relever les notes est l'intérêt premier de la carte de tempo**.

### Décisions validées (utilisateur, 2026-10-29)

**R1 — Tempos décimaux, à 0,01 près** (choix a). Tempo de départ et
changements gardent deux décimales : une mise à l'échelle est exacte et
un aller-retour (plus lent puis plus vite) revient au même point, sans
dérive d'arrondi. L'import garde les tempos exacts du fichier (93,75 au
lieu de 94), l'export les écrit tels quels. Le champ BPM reste un
SpinCtrl entier (seul widget annoncé en temps réel par le lecteur
d'écran) : il affiche le tempo arrondi à l'unité. Ailleurs (dialogue
Tempo, liste des événements, compte rendu de l'import), un tempo
s'affiche avec ses décimales seulement s'il en a, à la française :
« 46,5 BPM ». Remplace « BPM entier » de T2.

**R2 — Champ BPM, Tap Tempo, ±5 : tous les tempos changent dans la même
proportion** (remplace T7). Le champ **affiche le tempo en vigueur à la
position** (choix b, « pour pouvoir lire le changement de tempo en direct
avec un lecteur d'écran ») ; le modifier, taper un tempo (H) ou faire ±5
applique le rapport *nouveau / tempo affiché exact* au tempo de départ et
à tous les changements. Un tempo qui sortirait de 1..600 est borné.
- Affichage mis à jour après un déplacement à l'arrêt, à l'arrêt de la
  lecture, et **pendant la lecture, à chaque changement de tempo
  franchi** (le player signale le tempo atteint ; le champ suit, pour
  qu'un lecteur d'écran le lise). *Interprétation de « en direct », à
  confirmer à l'essai.*
- Undo inchangés : Tap Tempo en pose un ; le champ et ±5 non.

**R3 — Dialogue Tempo (T8), « Modifier » : deux choix.** « **Changer le
tempo récent** » (seul l'élément sélectionné, ou le tempo en vigueur à la
position, change ; le « modifier le tempo en vigueur » de Sonar) et
« **Tous les tempos** » (même proportion que R2). « Insérer » et
« Supprimer » inchangés.

### Ce qui reste de 19d1

Le player et la carte (T4), la position gardée quand le tempo change en
lecture, les ms par pas au tempo de la position, le mode song. `set_tempo_at`
(changer le tempo en vigueur) reste : il sert au choix « Changer le tempo
récent » du dialogue (19f1).

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **19d2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **19d3** | Implémentation — R1 (tempos à 0,01, import, export, affichage), R2 (mise à l'échelle de tous les tempos, champ qui suit le tempo en lecture). Essayé à l'écoute et au lecteur d'écran. | `tempo_map.py`, `pattern.py`, `player/*.py`, `midi/midi_import.py`, `ui/main_window.py`, `ui/key_handler_chars.py`, `ui/mw_project.py`, `ui/mw_patterns.py`, `ui/mw_songs.py` |
| **19e1** | Tests — 19d1 et 19d3. | `tests/test_tempo_playback.py` (nouveau), `tests/test_tempo_map.py`, fakes au besoin |
| **19f1** | Implémentation — T8 avec R3, T9. | inchangé |
| **19g1** | Tests — 19f1. | inchangé |
| **19h1** | Doc — clôture. | inchangé |

### Phase 7 étape 19 — Avancement après l'avenant (19d3)

- **19d3** — conforme à 19d2 :
  - R1 : `clamp_bpm` arrondit à 0,01 (entier s'il n'a pas de décimales),
    `format_bpm` (« 46,5 ») ; import exact à 0,01 (constantes `BPM_MIN` /
    `BPM_MAX` de l'import retirées) ; compte rendu de l'import formaté ;
    champ BPM arrondi à l'unité.
  - R2 : `DrumPlayer.scale_tempos(ratio)` et `set_tempo_scaled(bpm)`
    (rapport nouveau / tempo exact à la position, position musicale
    gardée) pour le champ BPM, Tap Tempo et ±5 (±5 depuis le tempo
    affiché, arrondi) ; marqueur `TEMPO_EVENT` dans la mesure (début de la
    fenêtre et chaque changement, seulement s'il y a des changements) →
    `_on_tempo_cb` → champ BPM mis à jour en lecture.
  - Essai sans le son : Bach à 46 → départ 46, fin 20, durée doublée
    (202,6 s) ; 46, +5 ×7, −5 ×7, puis 92 : carte identique ; en lecture
    depuis la mesure 34, tempos signalés 85, 83, 80, 77, 70, 60, 50, 40.
    **Essayé à l'écoute et au lecteur d'écran (utilisateur, 2026-10-29) :
    « ça marche bien »** ; affichage en direct confirmé.
  - `pytest` rouge : 6 tests (4 BPM entiers dans `test_tempo_map.py` et
    `test_midi_import.py`, la fausse fenêtre de `test_key_manager.py` et
    un échec qui n'en est que la suite).
- **19e1** — `tests/test_tempo_playback.py` (44 tests : carte du player
  en cache, tempo en vigueur, `set_tempo_at`, `scale_tempos` /
  `set_tempo_scaled` et aller-retour exact, `_position_at` dans une
  fenêtre, `_t_to_offset`, `_measure_clock` et décompte, événements /
  métronome / Note Repeat minutés par la carte, `TEMPO_EVENT`, pause,
  déplacement à l'arrêt, position gardée par `set_bpm` et la mise à
  l'échelle, avance du song, `ms_per_step_at`, Aller à en secondes, champ
  BPM de la fenêtre principale, lecture réelle chronométrée) ;
  `format_bpm` et tempos à 0,01 dans `tests/test_tempo_map.py` ; 6 tests
  adaptés (BPM décimaux, `FakePlayer.tempo_at` / `set_tempo_scaled`).
  Huit défauts réintroduits à l'essai : chacun fait échouer au moins un
  test (deux trous trouvés ainsi et bouchés : `set_bpm` qui garde la
  position, Note Repeat dans une boucle). 2716 verts.
- **19f1** — T8 et T9, avec R3 précisé à l'essai :
  - `DrumPlayer.tempo_items`, `insert_tempo`, `modify_tempo(idx, pos, bpm,
    scope)`, `delete_tempo` (position gardée en lecture) ; `TempoMixin`
    (`ui/mw_tempo.py`) : Undo par changement (« Tempo : insérer 70 BPM à
    21:2:1 »…), champ BPM, statut, éditeur MIDI rafraîchi ;
    `ui/dialogs_tempo.py` : `TempoDialog` (Alt+Shift+T, deux fenêtres) et
    `TempoEditDialog` (Mesure, Temps, Pas, BPM en texte « 46,5 », Portée),
    partagé avec Entrée sur une ligne Tempo de Ctrl+2.
  - Liste des événements : `MidiEditor.get_tempo_events` (piste −1, en
    tête de sa position, départ compris), libellé « 1:1:1, Tempo, 92 BPM,
    départ », annonces, Entrée, Suppr (pas le départ ; sélection
    multiple comprise), filtre « Tempo » (`EventFilterDialog`, types « à
    venir » décalés de un).
  - **Écart : trois portées au lieu de deux.** À l'essai, « Tous les
    tempos » pouvait vouloir dire « tous à cette valeur » ; le dialogue
    propose donc « Changer le tempo le plus récent », « Changer tous les
    tempos à cette valeur » (le pattern n'a plus qu'un tempo) et
    « Changer tous les tempos proportionnellement » (boutons radio : les
    choix s'excluent) ; `DrumPlayer.SCOPE_*`.
  - **Écart : positions « 21:2:1 »** (deux-points, comme le reste de
    l'appli) au lieu de « 21.2.1 ».
  - **Ligne du tempo de départ toujours présente dans Ctrl+2**, pour
    pouvoir la modifier par Entrée : une liste n'est plus jamais vide.
  - **Correctifs trouvés à l'essai** : (1) le dialogue d'édition ne
    s'ouvrait pas — `Pattern.steps_per_beat()` rend un float que
    `wx.SpinCtrl` refuse (TypeError dans le terminal, rien à l'écran ; mes
    essais passaient un entier) ; (2) `EVT_CHAR_HOOK` du dialogue Tempo
    (pour Suppr) bloquait Entrée et Espace sur les boutons
    (cf. `SaveConfirmDialog`) : le dialogue les traite lui-même.
  - Essayé au lecteur d'écran (utilisateur, 2026-10-29) : ça marche.
  - `pytest` rouge : 8 tests (ligne de départ en tête de Ctrl+2 :
    indices décalés, liste jamais vide ; type « Tempo » du filtre).
- **19g1** — `tests/test_tempo_dialog.py` (49 tests : opérations du
  player et trois portées, `TempoMixin` et titres d'Undo, dialogue Tempo et
  dialogue d'édition ouverts par le chemin de l'appli — vrai Pattern dont
  `steps_per_beat()` est un float —, Insérer / Modifier / Supprimer,
  Entrée / Espace / Suppr, lignes Tempo de Ctrl+2, filtre, Entrée sur une
  ligne Tempo, Alt+Shift+T dans les deux fenêtres) ; 8 tests adaptés à la
  ligne de départ en tête de Ctrl+2 et au type « Tempo » du filtre.
  Les deux défauts de 19f1 et « à cette valeur » qui garderait les
  changements, réintroduits à l'essai, font échouer des tests.
  - **Écart : focus simulé** (`wx.Window.FindFocus` remplacé) dans les
    tests du clavier : afficher le dialogue pour lui donner un vrai focus
    faisait planter Python (erreur de segmentation) à la sortie de la
    suite complète. 2765 verts.

### Clôture (19h1)

**19a1-19g1 FAITS** (commits `73ae931` à `f11647f`, et ce commit de
clôture, 2765 tests verts) : **chantier Phase 7 étape 19 complet**. Un
pattern a une carte de tempo : le ralenti final de `bach_01.mid` s'entend
comme sous TiMidity, et tout un morceau se ralentit d'un geste pour être
étudié.

**Ce que le chantier a livré** :
- **`TempoMap`** (`src/tempo_map.py`, sans wx ni player, portable) :
  tempo de départ et changements instantanés, pas ↔ secondes par
  morceaux ; tempos à 0,01 près, `format_bpm` (« 46,5 »).
- **Carte du pattern** (`_tempo_changes`) : `.gvp`, Undo, copie,
  redimensionnement, doubler, diviser ; import (tous les tempos du
  fichier) et export (un `set_tempo` par changement), durées au tempo
  local.
- **Player** : tout le minutage suit la carte ; position gardée quand le
  tempo change en lecture ; mode song.
- **Champ BPM, Tap Tempo, ±5** : tous les tempos dans la même proportion ;
  le champ affiche le tempo de la position, en direct pendant la lecture.
- **Dialogue Tempo (Alt+Shift+T)** et **lignes Tempo de Ctrl+2** :
  insérer, modifier (le plus récent, tous à cette valeur, tous
  proportionnellement), supprimer, Undo, filtre.

**Écarts au plan** : avenant 19d2 (tous les tempos en proportion au lieu
du seul tempo en vigueur, tempos décimaux, affichage en direct) ; trois
portées au lieu de deux et positions « 21:2:1 » (19f1) ; ligne du tempo de
départ toujours dans Ctrl+2 ; focus simulé dans les tests du clavier
(19g1) ; défauts plus anciens corrigés en chemin (pattern du player figé à
100 BPM, positions dans une boucle qui ne commence pas à 1.1.1) ; voir
plus haut.

**Leçons notées** : tester un dialogue par le chemin réel de l'appli
(`steps_per_beat()` est un float que `wx.SpinCtrl` refuse : deux allers-
retours avec l'utilisateur) ; ne pas afficher de dialogue dans un test
(Python plante à la sortie de la suite) ; vérifier le code de sortie de
`pytest`.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, arborescence
(`tempo_map.py`, `dialogs_tempo.py`, `mw_tempo.py`), structure Pattern et
format `.gvp`, section « BPM, Tap Tempo et carte de tempo », export,
import, liste des événements (lignes Tempo, Entrée, Suppr), boîtes de
dialogue (`TempoDialog`, `TempoEditDialog` ; `PatternPropertiesDialog`
corrigé : il n'a pas de champ BPM) ; `docs/shortcuts.md` : Alt+Shift+T
(deux fenêtres), champ BPM / H / ( / ) proportionnels, Entrée et Suppr
sur une ligne Tempo.

**Laissé hors périmètre, pour la suite** :
- **signatures** (une par pattern, puis leurs changements : il faudrait
  d'abord sauver `_num_beats`, puis revoir le codage des positions) ;
- rampes de tempo ; tempo dans le piano roll (Ctrl+1) ;
- Undo du champ BPM et de ±5 ;
- notes en temps flottant (reportées, non urgentes).

### Phase 7 étape 19i1 — Ajout après la clôture : Tap Tempo et Click dans le dialogue Tempo

Demandé par l'utilisateur (2026-10-30), avant d'attaquer les signatures :
- **Bouton « Tap Tempo »** : Entrée ou Espace = une frappe, mécanique de
  H (`Metronome.tap` : 4 frappes au moins, pause de plus de 2 s = nouvelle
  série, un Undo par série « Tap Tempo (BPM: 92) ») ; **le tempo
  sélectionné prend la valeur tapée et tous les autres suivent dans la
  même proportion** (choix 1a, comme H). `TempoMixin._tempo_tap`,
  `TempoDialog.tap` ; le bouton garde le focus et son libellé dit le tempo
  obtenu (« Tap Tempo : 120 BPM »), la ligne de la liste et le champ BPM
  suivent.
- **Case « Click (métronome) »** (demandée à l'essai du Tap Tempo) :
  active ou coupe le click comme la touche C ; cochée à l'ouverture si le
  click tourne ; garde son état à la fermeture. Espace sur la case est
  traité par le dialogue (même piège `EVT_CHAR_HOOK` que les boutons).
- Essayé au lecteur d'écran (utilisateur) : ça marche. `pytest` rouge :
  1 test (`test_enter_and_space_activate_focused_button` attend 4 boutons).
- **19j1** — tests de 19i1 dans `tests/test_tempo_dialog.py` (9 tests :
  4 frappes au moins, tempo sélectionné et tous les autres en proportion,
  un Undo par série, libellé du bouton, frappe par Entrée / Espace, case
  Click : état à l'ouverture, bascule comme C, Espace traité par le
  dialogue, état gardé à la fermeture ; horloge du Tap Tempo factice) ;
  test des boutons adapté (cinq boutons) ; `SPECS.md` (dialogue Tempo,
  tableau des dialogues), `shortcuts.md` (Alt+Shift+T). Trois défauts
  réintroduits à l'essai font échouer des tests. 2774 verts.

## Phase 7 étape 20a1 — Signatures rythmiques : une signature par pattern

### Numérotation des commits de ce chantier

`20a1` = ce plan (doc seule). Le code commence à `20b1`. Une paire impl →
tests par sous-chantier ; `20a2`, `20b2`… pour un commit imprévu.

### Origine du besoin

- Import MIDI (Phase 7 étape 18) : `01Minuetto2.mid` (3/4) est lu en 4/4,
  « signature 3/4 lue en 4/4 » au compte rendu ; l'export écrit toujours
  4/4.
- Carte de tempo (étape 19) : les signatures, laissées hors périmètre (T1),
  sont demandées comme chantier suivant (utilisateur, 2026-10-30).

### Comportement de Cakewalk / Sonar (vérifié le 2026-10-30)

- **Documentation officielle** (legacy.cakewalk.com, « Setting the Meter
  and Key signatures ») : la signature donne le nombre de temps par mesure
  et la valeur du temps (le dénominateur) ; « 6/8 : six temps par mesure,
  chaque croche reçoit un temps » ; elle place les accents du métronome et
  règle l'affichage de la position (Measure:Beat:Tick).
- Un message de forum (discuss.cakewalk.com, fil 11135, 2020) dit qu'un
  temps est toujours une noire : contredit par la documentation, écarté.
- Forums : changer la signature décale les barres de mesure dans le
  temps ; le BPM reste compté en noires (comme dans un fichier MIDI).

### État des lieux constaté en code (2026-10-30, 2774 tests verts)

- `Pattern._num_beats = 4` et `_denumerator = 4` (`pattern.py:174`,
  `:181`) : **ni sauvés ni modifiables**. Une mesure fait toujours 4
  noires.
- **Positions** : `TapeEvent.time = mesure × _num_steps + pas` ; toutes les
  mesures ont `_num_steps` pas. `VALID_NUM_STEPS = (16, 32, 64, 128)` pas
  par mesure (`pattern.py:109`), choisis dans le dialogue des propriétés du
  pattern (champ « Pas », `dialogs_properties.py:308`, `mw_patterns.py:411`).
- **Position affichée (mesure:temps:pas)** : partout
  `steps_per_beat = _num_steps // _num_beats` (`dp_position.py:68`,
  `mew_display.py:91`, `midi_editor_dialogs.py:123`, `:333`,
  `track_editor.py:136`, `key_handler_chars.py:374`…, `mew_keymap.py:359`,
  `mew_delete_clipboard.py:117`, dialogues temporels) : juste pour toute
  signature si `_num_beats` est le numérateur et `_num_steps` les pas de
  la mesure (le temps = le dénominateur).
- **Tempo** : `Pattern.steps_per_beat()` (`pattern.py:523`) sert de **pas
  par noire** à la carte de tempo (`tempo_map()`, `ms_per_step_at`), à
  `step_duration` (`drum_player.py:175`), au décompte (`dp_playback.py:170`),
  à la quantisation des durées (`quantize_manager.py:138`) et aux
  dialogues de tempo (`dialogs_tempo.py`, `mw_tempo.py:29`, qui s'en
  servent aussi pour la position affichée). En 6/8, pas par temps (la
  croche) et pas par noire diffèrent : il faut les séparer.
- **Valeurs de note supposant mesure = ronde** : grille (`grid_step_size`,
  `pattern.py:142` : « 1/16 » = `_num_steps / 16`), quantisation
  (`quantize_manager.py:46`, `:79`), quantisation à l'enregistrement
  (`dp_recording.py:89`), Note Repeat (`dp_playback.py:147`). En 3/4 à 12
  pas, « 1/16 » vaudrait 0,75 pas au lieu d'un.
- **Métronome** (`metronome.py:42`) : `num_beats` clicks par mesure,
  `num_steps // num_beats` pas entre deux : juste pour toute signature
  (un click par temps du dénominateur, accent sur le 1).
- **Grille** : 16 colonnes (`MainWindow.COLS`), les 16 premiers pas de la
  mesure 1 (`mw_patterns.py:19`).
- **Import** : `BEATS_PER_BAR = 4`, `bar_ticks = PPQ × 4`
  (`midi_import.py:25`), signature lue mais remplacée par 4/4 ; **export** :
  `time_signature` = `_num_beats`/4, `tick = pas × PPQ × _num_beats /
  _num_steps` (`midi_export.py:135`).
- `copy_from` ne copie pas la signature ; `resize(num_bars, num_steps)`
  (changement de « Pas ») garde mesure:pas de chaque événement (un
  événement au pas 4 sur 16 reste au pas 4 sur 32 : il change de place
  dans le temps).

### Décisions validées (utilisateur, 2026-10-30)

**S1 — Une signature par pattern** (choix a). Numérateur et dénominateur
propres à chaque pattern ; chaque pattern d'un song garde la sienne. Les
changements de signature à l'intérieur d'un pattern : chantier suivant
(tout le codage des positions suppose des mesures égales).

**S2 — « Pas » devient « Résolution »** (choix a) : 1/16, 1/32, 1/64,
1/128, quelle que soit la signature ; les pas de la mesure s'en déduisent :
`pas par mesure = résolution × numérateur / dénominateur` (3/4 en 1/16 :
12 ; 6/8 : 12 ; 5/4 : 20 ; 7/8 : 14 ; 4/4 : 16, comme aujourd'hui).

**S3 — Changer la signature d'un pattern : les notes gardent leur place
dans le temps** (choix a). À résolution égale, un pas dure toujours la
même fraction de noire : les positions en pas ne bougent pas, seuls
`_num_steps` (pas par mesure) et donc les barres de mesure changent ; le
nombre de mesures est recalculé pour garder la longueur (arrondi à la
mesure supérieure). Changements de tempo et boucle (positions en pas)
inchangés. Un Undo.

**S4 — Le temps est le dénominateur** (choix a, documentation de
Cakewalk) : en 6/8, 6 temps de croche par mesure, positions 1:1:1 à
1:6:x, un click par croche avec accent sur le 1. Le BPM reste compté en
noires.

### Choix de conception proposés

**S5 — Deux unités séparées dans `Pattern`** : `steps_per_beat()` = pas
par temps (le dénominateur : position affichée, métronome) ;
`steps_per_quarter()` = pas par noire (tempo : carte, `step_duration`,
décompte, ms par pas) = `résolution / 4`. `quarters_per_bar()` =
`4 × numérateur / dénominateur`. Les usages « tempo » de
`steps_per_beat()` passent à `steps_per_quarter()`.

**S6 — Valeurs de note = valeurs de note.** « 1/16 » de la grille, de la
quantisation, de l'enregistrement et du Note Repeat est une double croche
quelle que soit la signature : `pas = résolution / valeur` (au lieu de
`_num_steps / valeur`). Identique en 4/4. « 1 mes. » (et 2, 3, 4 mesures)
de la grille reste une mesure.

**S7 — Réglage** dans le dialogue des propriétés du pattern (Alt+Entrée) :
« Signature » = numérateur (SpinCtrl 1..16) et dénominateur (liste 2, 4,
8, 16), puis « Résolution » (liste 1/16 … 1/128). Signature et résolution
changées ensemble : signature d'abord (S3), puis résolution (comportement
actuel de `resize`, inchangé).

**S8 — Sauvegarde** : `.gvp` (`"num_beats"`, `"denominator"`, absents =
4/4) et donc Undo ; `copy_from` copie la signature (mode song : chaque
pattern la sienne).

**S9 — Import et export.** Import : première signature du fichier
(`bar_ticks = PPQ × 4 × num / den`, résolution choisie comme aujourd'hui
mais parmi 1/16 … 1/128) ; les changements de signature suivants sont
comptés au compte rendu (« N changements de signature ignorés ») ; le
compte rendu ne dit plus « lue en 4/4 ». Export : `time_signature` du
pattern, ticks par `quarters_per_bar()`.

**S10 — Grille de la fenêtre principale** : seules les colonnes de la
mesure sont actives (12 en 3/4 à 1/16) ; au-delà de 16 pas, les 16
premiers comme aujourd'hui.

### Portée explicitement exclue de ce chantier

- **Changements de signature à l'intérieur d'un pattern** (carte des
  signatures) : chantier suivant ;
- signatures irrégulières groupées (7/8 = 2+2+3) et métronome groupé
  (6/8 en 2 noires pointées) ;
- changement de résolution qui garde les notes en place dans le temps
  (`resize` garde mesure:pas, comportement actuel inchangé) ;
- tonalité (« Key ») ; signature dans le piano roll au-delà de la
  position affichée.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **20a1** | Doc — ce plan. | `docs/DESIGN.md` |
| **20b1** | Implémentation — S5, S6, S8, S3 (modèle) : signature du pattern (`.gvp`, `copy_from`, `set_signature`), unités séparées, valeurs de note, tempo par noire ; import et export (S9). | `pattern.py`, `tempo_map.py` (au besoin), `player/*.py`, `quantize_manager.py`, `midi/midi_import.py`, `midi/midi_export.py`, appels de `steps_per_beat()` côté tempo |
| **20c1** | Tests — 20b1 (3/4, 6/8, 5/4, 7/8 : positions, tempo, métronome, quantisation, import / export, aller-retour). | `tests/test_signature.py` (nouveau), tests existants au besoin, `docs/SPECS.md` |
| **20d1** | Implémentation — S7, S10 : dialogue des propriétés (signature, résolution), grille, affichages. Essayé à l'écoute (menuet en 3/4, un 6/8) et au lecteur d'écran. | `ui/dialogs_properties.py`, `ui/mw_patterns.py`, `ui/main_window.py` |
| **20e1** | Tests — 20d1. | `tests/test_pattern_properties_dialog.py`, tests de la grille |
| **20f1** | Doc — clôture (SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 20 — Avancement et écarts constatés

- **20b1** — modèle conforme à S2-S6, S8, S9 :
  - `Pattern` : `quarters_per_bar()`, `steps_per_quarter()` (tempo :
    carte, `ms_per_step_at`, `step_duration`), `steps_per_beat()` (temps
    du dénominateur), `resolution()`, `note_steps(valeur)`,
    `steps_for(résolution, num, den)`, `set_signature(num, den)` (S3 :
    positions en pas gardées, mesures recalculées ; refuse un dénominateur
    hors de 2, 4, 8, 16 ou un numérateur hors de 1..16) ;
    `VALID_RESOLUTIONS`, `VALID_DENOMINATORS` ; `.gvp` `"num_beats"` /
    `"denominator"` (absents = 4/4) ; `copy_from` copie la signature.
  - Valeurs de note (S6) : `grid_step_size(…, resolution)` (« 1 mes. »
    reste une mesure), Note Repeat, quantisation à l'enregistrement,
    quantisation. **Écart : grille de quantisation continue** depuis le
    début du pattern (et non recommencée à chaque mesure) : identique en
    4/4, juste quand une valeur ne divise pas la mesure (blanche en 3/4).
  - Import : première signature (ticks par mesure en fraction exacte :
    7/8, PPQ impair), résolution 1/16 … 1/128, changements de signature
    comptés, signature refusée lue en 4/4 ; compte rendu « signature
    3/4 » (au lieu de « lue en 4/4 ») et, au statut, « résolution 1/16 »
    (au lieu de « 16 pas »). Export : `time_signature` du pattern, ticks
    par `quarters_per_bar()`.
  - Essais : `01Minuetto2.mid` en 3/4 (12 pas par mesure, 49 mesures au
    lieu de 37 en 4/4, notes sur 1:1, 1:2, 1:3…), export 3/4, aller-retour
    identique ; 4/4 → 6/8 : notes au même instant, 6 clicks de croche par
    mesure.
  - `pytest` rouge : 4 tests (textes du compte rendu de l'import, fausse
    classe `_FakeGridPattern` sans `resolution`).
- **20c1** — `tests/test_signature.py` (56 tests : unités et pas par
  mesure en 3/4, 6/8, 5/4, 7/8, 2/2 ; `set_signature` qui garde notes,
  tempos et boucle en place, recalcul des mesures, refus ; `.gvp`,
  `copy_from` ; grille, Note Repeat, quantisation à l'enregistrement,
  rangée et quantisation continue en valeurs de note, 4/4 inchangé ;
  durée de la mesure, métronome, position affichée, décompte en 6/8,
  avance du song ; import 6/8, 7/8 à PPQ impair, signature refusée,
  changements comptés, résolution choisie ; export, aller-retour) ; 4
  tests adaptés. Cinq défauts réintroduits à l'essai font échouer des
  tests. 2830 verts.
- **20d1** — S7 et S10 :
  - `PatternPropertiesDialog` : « Signature, temps par mesure » (SpinCtrl
    1..16), « Signature, valeur du temps » (2 blanche, 4 noire, 8 croche,
    16 double croche), « Résolution » (1/16 double croche … 1/128) au lieu
    de « Pas » ; la longueur se recalcule en direct quand la signature
    change (durée gardée exacte en pas : un passage par 6/4 avant 6/8
    ajoutait une mesure, trouvé à l'essai) ; `get_num_beats`,
    `get_denominator`, `get_resolution`, `get_num_steps` (déduit). Action
    « Courant » : `set_signature` d'abord (notes en place), puis
    longueur et résolution (`resize` inchangé) ; « Nouveau » : pattern
    neuf dans la signature choisie ; Doubler / Diviser n'y touchent pas.
    Statut « mis à jour — 6/8, résolution 1/16 ».
  - Grille : colonnes au-delà des pas de la mesure vides et grisées
    (`_active_cols`), curseur et flèches bornés à la mesure, case hors
    mesure refusée — sans quoi `_refresh_grid` plantait sur un pattern en
    3/4 (ligne de 12 pas, 16 colonnes lues).
  - Essayé à l'écoute et au lecteur d'écran (utilisateur, 2026-10-30) :
    menuet en 3/4 importé, click qui suit la signature (accent et nombre
    de temps), dialogue : ça marche. `bach_01.mid` est bien en 4/4 (6/4
    seulement à la dernière mesure, ignoré).
  - Fichiers d'essai copiés hors du dépôt (copyright de la transcription
    de Bach) : `/home/com/groovybox/media/midis/Minueto_02.mid` (3/4) et
    `Prelude_01.mid`.
  - `pytest` rouge : 2 tests (`test_step_duration.py`, faux dialogue sans
    les nouveaux accesseurs).
- **20e1** — `tests/test_signature_ui.py` (20 tests : dialogue des
  propriétés — valeurs initiales, libellés, pas par mesure, longueur
  recalculée, exacte à travers une signature intermédiaire, après une
  longueur choisie à la main ; application — signature transmise, notes
  en place, durée du pas et métronome, résolution après signature,
  Nouveau, Doubler sans signature ; grille — colonnes actives, cases
  grisées, curseur ramené, 4/4 inchangé, case et flèches bornées) ; faux
  dialogue de `test_step_duration.py` adapté. Quatre défauts réintroduits
  à l'essai, dont celui de la longueur trouvé en 20d1, font échouer des
  tests. 2850 verts.

## Phase 7 étape 20e2 — Avenant : champ Tempo dans les propriétés du pattern

### Origine

Demande de l'utilisateur (2026-10-30), après 20e1 : ajouter un champ
Tempo (SpinCtrl) dans le dialogue des propriétés du pattern, juste avant
la signature, « car généralement ça va ensemble ».

### État des lieux

- `PatternPropertiesDialog` (`ui/dialogs_properties.py`) n'a pas de champ
  de tempo (la ligne « nom, BPM, mesures, pas » de `SPECS.md` était
  fausse, corrigée en 19h1).
- Le tempo se règle aujourd'hui par le champ BPM de la fenêtre principale
  (`set_tempo_scaled` : tous les tempos dans la même proportion, § 19d2
  R2), Tap Tempo, ±5 et le dialogue Tempo (Alt+Shift+T).
- Le tempo de départ peut être décimal (`Pattern._bpm`, à 0,01 près,
  19d3) ; un SpinCtrl est entier.

### Décisions validées (utilisateur, 2026-10-30)

**P1 — Le champ se comporte comme le champ BPM de la fenêtre principale**
(choix a) : « Tempo (BPM) », SpinCtrl 1..600, placé juste avant
« Signature, temps par mesure » ; il affiche le **tempo de départ**
arrondi à l'unité ; le modifier change **tous les tempos dans la même
proportion** (`scale_tempos`, rapport *nouveau / tempo de départ exact*),
ralenti compris. La référence est le départ (1:1:1), et non la position
courante : on règle le pattern entier.

**P2 — Appliqué à Ok**, comme les autres champs, sous l'Undo du dialogue ;
**rien si le champ n'a pas changé** (un départ à 93,75, affiché 94, n'est
pas arrondi).

**P3 — « Nouveau »** : le pattern neuf a ce tempo, unique (la carte est
vidée par `new_pattern`). « Doubler » et « Diviser » appliquent aussi le
tempo s'il a changé (le doublement garde déjà la carte, 19b1).

**P4 — Ordre Tab** : Nom → Début → Longueur → **Tempo** → Signature,
temps par mesure → Signature, valeur du temps → Résolution → Boucler →
Action.

### Découpage en commits révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **20e2** | Doc — cet avenant. | `docs/DESIGN.md` |
| **20e3** | Implémentation — P1 à P4. Essayé au lecteur d'écran. | `ui/dialogs_properties.py`, `ui/mw_patterns.py` |
| **20e4** | Tests — 20e3. | `tests/test_signature_ui.py`, `tests/test_pattern_properties_dialog.py` au besoin |
| **20f1** | Doc — clôture (signatures et champ Tempo). | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 7 étape 20 — Avancement après l'avenant (20e3)

- **20e3** — P1, P3, P4 conformes : champ « Tempo (BPM) » (SpinCtrl
  1..600) avant la signature, tempo de départ arrondi, tous les tempos en
  proportion (`scale_tempos`, rapport au départ exact), « Nouveau » = tempo
  unique, `get_tempo()` = None si inchangé (départ décimal non arrondi) ;
  `PatternMixin._apply_properties_tempo` met aussi à jour le pattern du
  store et le champ BPM de la fenêtre principale.
  - **Écart à P2, demandé à l'essai : tempo en direct.** Le champ
    s'entend aussitôt (click et lecture) : `on_tempo_change` →
    `_preview_properties_tempo` (tempos d'origine × nouveau / départ) ;
    Annuler rétablit les tempos d'origine ; à Ok, l'origine est rétablie
    **avant** l'Undo de l'action, puis le tempo final appliqué : l'Undo
    ramène l'état d'avant l'ouverture.
  - **Écart demandé à l'essai : signature en direct aussi.**
    `on_signature_change` → `_preview_properties_signature`
    (`set_signature` depuis l'origine, notes en place, grille et click
    suivent) ; Annuler (et Ok, avant l'Undo) remet tels quels signature,
    pas par mesure et mesures d'origine (un aller-retour par
    `set_signature` pourrait ajouter une mesure). La résolution reste
    appliquée à Ok (elle déplace les notes). En tapant 6 temps avant la
    croche, on entend brièvement l'étape 6/4.
  - Essayé au lecteur d'écran et à l'écoute (utilisateur, 2026-10-30) :
    ça marche. `pytest` rouge : 8 tests (faux dialogues sans `get_tempo`).
- **20e4** — 12 tests de plus dans `tests/test_signature_ui.py` (champ
  Tempo : affichage arrondi, départ décimal gardé, ordre Tab ; rappels
  en direct ; Ok : tous les tempos en proportion et store à jour ;
  inchangé : carte intacte ; Nouveau : tempo unique ; direct puis
  Annuler : tempos et signature d'origine, sans Undo ; direct puis Ok :
  Undo pris sur l'état d'avant le dialogue ; click qui suit la signature
  en direct ; aucun rafraîchissement sans changement) ; faux dialogues
  adaptés (`get_tempo`). Quatre défauts réintroduits à l'essai font
  échouer des tests. 2862 verts.

### Clôture (20f1)

**20a1-20e4 FAITS** (commits `0ef15b5` à `75907b9`, et ce commit de
clôture, 2862 tests verts) : **chantier Phase 7 étape 20 complet**. Un
pattern a sa signature : le menuet se lit en 3/4, un 6/8 se bat en six
croches, et tempo et signature se règlent ensemble, en direct, dans les
propriétés du pattern.

**Ce que le chantier a livré** :
- **Modèle** : signature par pattern (`.gvp`, copie, song), temps du
  dénominateur et tempo en noires (`steps_per_beat` / `steps_per_quarter`),
  résolution 1/16 … 1/128, `set_signature` qui garde les notes en place,
  vraies valeurs de note (grille, quantisation, enregistrement, Note
  Repeat).
- **Import et export** de la signature (première du fichier, changements
  comptés, ticks par mesure exacts).
- **Propriétés du pattern** : Tempo (tous les tempos en proportion),
  signature et résolution ; tempo et signature en direct, Annuler,
  Undo de l'état d'avant le dialogue.
- **Grille** limitée aux colonnes de la mesure.

**Écarts au plan** : grille de quantisation continue (20b1) ; longueur
gardée exacte à travers une signature intermédiaire (trouvé à l'essai de
20d1) ; avenant 20e2 (champ Tempo), puis tempo et signature en direct
(demandés à l'essai de 20e3) ; voir plus haut.

**`docs/SPECS.md` mis à jour** : ligne Phase 7, structure Pattern et
format `.gvp`, nouvelle section « Signatures rythmiques », import
(résolution, signature), export (signature du pattern), compte rendu,
boîtes de dialogue, tests ; `docs/shortcuts.md` : Alt+Entrée sur un
pattern.

**Fichiers d'essai, hors du dépôt** (copyright de la transcription de
Bach) : `/home/com/groovybox/media/midis/Minueto_02.mid` (3/4),
`Prelude_01.mid`.

**Laissé hors périmètre, pour la suite** :
- **changements de signature à l'intérieur d'un pattern** (carte des
  signatures : le codage des positions suppose des mesures égales) ;
- mesures irrégulières groupées (7/8 = 2+2+3), métronome groupé (6/8 en
  deux noires pointées) ;
- changement de résolution qui garde les notes en place dans le temps ;
- tonalité.

---

## Phase 8 étape 1a — Export audio WAV du pattern courant

### Numérotation des commits de ce chantier

`1a` = ce plan (doc seule). Le code commence à `1b1`. Une paire impl →
tests par sous-chantier ; `1a2`, `1b2`… pour un commit imprévu.

### Origine du besoin

- Demandé le 2026-10-24, à la clôture de la Phase 7 étape 12 : « il faut
  noter l'export Audio en Wav comme un autre chantier ».
- Pour vérifier la boucle de `Pat_01.mid`, un rendu TiMidity
  (`-Ow -EFreverb=d -EFchorus=d`) a été coupé à 9,600 s (4 mesures à
  100 BPM). La résonance au-delà a été additionnée au début, puis le tout
  normalisé. Jugé « excellent, ça boucle très précisément ».
- Choisi comme premier chantier de la Phase 8 le 2026-10-30.
- Demande de l'utilisateur (2026-10-31) : une option pour replier ou non
  la résonance. Le fichier contient soit exactement les mesures du
  pattern, soit le pattern suivi de la fin de la résonance des instruments.

### État des lieux constaté en code (2026-10-31, 2862 tests verts)

- **Mixage** : `SoundDeviceDriver._callback` (`sound_device_driver.py:187`)
  mélange les voix one-shot (`_Voice`), les voix bouclantes
  (`_LoopVoice`, release de 80 ms) et les sources externes
  (`add_render_source` : FluidSynth). Il applique ensuite le volume global
  et écrête (`np.clip`, `:212`). Le mixage et le flux PortAudio sont dans
  la même classe : rien ne permet aujourd'hui de mixer sans carte son.
- **Sons** : `SdSound` (données float32, fréquence, points de boucle) est
  une donnée pure, indépendante du flux. `SoundManager` et `SynthEngine`
  gardent une référence `_driver` et appellent `driver.play` / `stop_*` ;
  `SynthEngine` lit aussi `driver.LFO_DEPTH_MAX`.
- **FluidSynth** : `FluidSynthEngine.render(out)`
  (`engines/fluidsynth_engine.py:210`) ajoute un bloc à `out`. Réglages :
  gain 0,4, sans réverbération ni chorus. La soundfont est lue à la
  demande (FluidR3 : 0,1 s).
- **Fins de note** : `TrackRouter` coupe les notes par
  `threading.Timer` sur l'horloge murale (`track_router.py:430` banque,
  `:795` grille sur synthé, `:833` patch). Le rejeu dépend aussi de l'état
  du routeur : slots, mute et solo, volume et pan de piste, canal courant,
  pan global, gamme de lecture, état des canaux de banque (`chase`).
- **Événements** : `DrumPlayer._build_measure_events`
  (`player/dp_playback.py:90`) lit `_tape` et convertit les positions en
  secondes par la carte de tempo (`_measure_clock` → `TempoMap.secs`,
  signature comprise). Ces événements sont mêlés au métronome et au Note
  Repeat. `_dispatch_event` (`:181`) mêle le jeu (volume, pan et durée du
  pad via `voice_manager`, `_mix_pan`) à l'effacement et à
  l'enregistrement. La lecture attend chaque événement par
  `time.sleep` : la précision est d'environ 5 ms, elle n'est pas à
  l'échantillon près.
- **Boucle en lecture** : à la reprise de la boucle, rien n'est
  réinitialisé (pas de `chase`). Une note tenue au-delà de la fin continue
  dans le passage suivant ; une charleston fermée au début coupe
  l'ouverte de la fin (groupes de mute, `SoundManager._apply_mute_group`).
- **Export MIDI** (Alt+Shift+E, `mw_project.py:143`) : dialogue de
  fichier dans `EXPORTS`, nom `Pat_NN[_nom]`, compte rendu au statut.
- **Écriture** : `soundfile` est déjà une dépendance (`requirements.txt`).
- **Raccourci** : Alt+Shift+W est libre (fenêtre principale et éditeur
  MIDI).

### Décisions validées (utilisateur, 2026-10-31)

**W1 — Deux fins au choix** dans le dialogue d'export :
- **« Boucle exacte »** : le fichier dure exactement les mesures du
  pattern (`TempoMap.secs(mesures × pas par mesure)`), et la résonance qui
  dépasse est repliée sur le début ;
- **« Pattern + résonance »** : le pattern, puis la fin de la résonance
  des instruments, jusqu'au silence.

**W2 — Repli en régime établi** (choix 1a). Le pattern est rendu
plusieurs fois de suite, et seul le dernier passage est gardé. Son début
contient la fin du passage précédent, comme en lecture en boucle :
charleston coupée par son groupe, notes tenues, pédale, polyphonie.
- Nombre de passages : `K = 1 + max(1, ceil(T / L))`, où `L` est la
  longueur du pattern et `T` la durée de la résonance mesurée par un
  premier rendu « Pattern + résonance ». Dans le cas courant (`T ≤ L`), on
  a deux passages.
- Chaque passage commence à un multiple entier de `L` échantillons : les
  passages sont identiques à l'échantillon près.
- Écartée : l'addition simple de la résonance sur le début (la méthode
  TiMidity). Elle est plus rapide, mais à la jonction elle ne joue pas les
  coupures de groupe de mute.

**W3 — Écrêtage : atténuer si besoin, case « Normaliser »** (choix 2c).
Par défaut, le niveau est celui de l'écoute. Si la crête dépasse
−0,3 dBFS, tout le fichier est baissé pour l'y ramener. Case
« Normaliser » (décochée par défaut) : la crête est toujours amenée à
−0,3 dBFS. Le compte rendu donne le gain appliqué (« atténué de 2,4 dB »,
« normalisé : +3,1 dB »). Le mixage se fait en flottant, sans `np.clip` :
rien n'est écrêté avant ce gain.

**W4 — Format : liste « 16 bits » (défaut), « 24 bits », « 32 bits
flottant »**. Stéréo, 44 100 Hz, la fréquence du moteur. Proposé : un
dither TPDF de ±1 LSB en 16 bits seulement. C'est l'usage pour réduire à
16 bits, et c'est inaudible.

**W5 — Portée : le pattern entier** (choix 3a), comme l'export MIDI.

### Choix de conception proposés

**W6 — Ce qui est rendu : ce qu'on entend en lecture**, sans le
métronome ni le Note Repeat. Le rendu suit :
- la carte de tempo et la signature ;
- les slots (kit, synthé, banque FluidSynth) ;
- le mute et le solo des pistes et des pads ;
- le volume et le pan des pads et des pistes ;
- le volume et le pan globaux ;
- la courbe GM (`gm_gain`) et l'état des canaux de banque, poursuivi
  depuis le début (`chase(tape, 0)`).

**W7 — Rendu hors temps réel, à l'échantillon près, avec les moteurs de
l'appli.** Pas de capture de la sortie pendant une lecture : elle
prendrait le temps réel, et ses instants dépendent de `time.sleep`.
- **Mixeur** : le mélange des voix de `SoundDeviceDriver` est extrait dans
  une classe `Mixer` (`play`, `stop_*`, `mix(out)` sans écrêtage, volume
  global). `SoundDeviceDriver(Mixer)` ajoute le flux PortAudio, et son
  callback devient `mix` suivi de `np.clip`. L'API du driver ne change pas.
- **Moteurs du rendu** : ce sont des copies, branchées sur un `Mixer` hors
  ligne, qui ne touchent pas aux moteurs de l'écoute. Les pads restent
  jouables pendant l'export.
  - `TrackRouter.render_copy(mixer, bank_engine, schedule)` recopie
    l'état du routeur.
  - `SoundManager` est copié superficiellement avec `_driver = mixer` :
    les sons sont partagés, pas rechargés.
  - Chaque `SynthEngine` des slots est copié avec `_driver = mixer` et un
    état neuf (voix, bend, pédale) ; les caches sont partagés.
  - Un second `FluidSynthEngine` (même gain, même mode de banque) charge
    les fichiers du Rack.
- **Fins de note** : `TrackRouter` reçoit un ordonnanceur
  `schedule(delay_ms, fn, *args)`. Par défaut, c'est `threading.Timer`,
  comme aujourd'hui. Pour le rendu, il pose l'appel dans la file des
  événements, à l'échantillon voulu.
- **Événements** : la partie « tape » de `_build_measure_events` devient
  une fonction pure (pattern, fenêtre, horloge → événements triés), avec
  le même tri qu'aujourd'hui (§ 18d2). Le jeu de `_dispatch_event`, sans
  l'effacement ni l'enregistrement, devient une fonction partagée. La
  lecture et le rendu ont ainsi les mêmes règles.
- **Boucle de rendu** (`src/audio_export.py`, sans wx) : file d'événements
  à l'échantillon `round(secs × sr)`. On mixe jusqu'à l'événement suivant
  par blocs de 512 échantillons au plus (le bloc de l'écoute : le LFO
  reste le même), puis on joue l'événement. Le mixeur et FluidSynth sont
  rendus dans le même tampon.
- **Fin de la résonance** : la résonance s'arrête quand le mixeur n'a
  plus de voix et que FluidSynth n'a plus de voix active
  (`fluid_synth_get_active_voice_count`, à déclarer). Plafond de 30 s
  (`TAIL_MAX_S`) : au-delà, la résonance est coupée et le compte rendu le
  dit.
- **Prototype, cible C/C++** (moteur audio) : interfaces étroites, sans
  wx ni objets propres à Python, transposables telles quelles :
  `mix(out)` sur un tampon float32 (frames, 2) ; événements à un indice
  d'échantillon ; moteurs appelés par canal, note, vélocité.

**W8 — Interface.** Alt+Shift+W (fenêtre principale et éditeur MIDI, comme
Alt+Shift+E) :
1. La lecture est arrêtée, si elle tourne.
2. Le dialogue « Export audio » s'ouvre :
   - liste « Fin » (« Boucle exacte (résonance repliée) », « Pattern +
     résonance ») ;
   - liste « Format » (16 bits par défaut) ;
   - case « Normaliser » ;
   - Ok et Annuler.

   Ce sont des ListBox, navigables au lecteur d'écran comme dans les
   propriétés du pattern. Les choix sont gardés pour la session.
3. Le dialogue de fichier s'ouvre dans `EXPORTS`, avec le nom
   `Pat_NN[_nom].wav`.
4. Le rendu tourne dans un fil, et le statut l'annonce (« Export audio :
   40 % », via `wx.CallAfter`).
5. Le compte rendu donne le fichier, la durée, la fin choisie et le gain
   appliqué.

Si un synthé est encore en chargement, le rendu l'attend
(`wait_loaded`). Sans libfluidsynth, les pistes Banque sont muettes,
comme à l'écoute.

### Portée explicitement exclue de ce chantier

- l'export de la fenêtre de boucle (points In/Out), d'un song ou du
  projet ;
- l'export piste par piste (stems) ;
- les autres fréquences (48 kHz…), le mono, et les formats compressés
  (FLAC, OGG, MP3) ;
- la réverbération et le chorus de FluidSynth (laissés à 0, comme à
  l'écoute) ;
- le métronome et le Note Repeat dans le fichier.

### Découpage en commits proposé

| Étape | Contenu | Fichiers |
|---|---|---|
| **1a** | Doc — ce plan ; tableau d'avancement de SPECS (Phase 7 ✓, ligne Phase 8). | `docs/DESIGN.md`, `docs/SPECS.md` |
| **1b1** | Implémentation — `Mixer` extrait de `SoundDeviceDriver` (W7), sans changement de comportement. | `sound_device_driver.py` |
| **1c1** | Tests — 1b1 (mix hors flux, sans écrêtage, volume global, callback inchangé). | `tests/test_mixer.py` (nouveau), `docs/SPECS.md` |
| **1d1** | Implémentation — ordonnanceur injecté dans `TrackRouter`, `render_copy`, fonctions pures des événements et du jeu, partagées avec la lecture (W6, W7). | `track_router.py`, `player/dp_playback.py`, `sound_manager.py`, `synth_engine.py`, `engines/fluidsynth_engine.py` |
| **1e1** | Tests — 1d1 (lecture inchangée, copie indépendante des moteurs de l'écoute). | tests existants, `tests/test_render_copy.py` (nouveau) |
| **1f1** | Implémentation — `audio_export.py` : boucle de rendu, deux fins, régime établi, fin de résonance, gain, dither, écriture (W1-W4, W7). | `src/audio_export.py` (nouveau) |
| **1g1** | Tests — 1f1 (positions à l'échantillon, carte de tempo, longueur exacte, passages identiques, repli, charleston coupée à la jonction, plafond, gain, formats). | `tests/test_audio_export.py` (nouveau), `docs/SPECS.md` |
| **1h1** | Implémentation — Alt+Shift+W, dialogue, fil de rendu, statut (W8). Essayé à l'écoute et au lecteur d'écran. | `ui/mw_project.py`, `ui/key_handler_alt.py`, `ui/mew_keymap.py`, `ui/dialogs_simple.py` |
| **1i1** | Tests — 1h1. | `tests/test_audio_export_ui.py` (nouveau) |
| **1j1** | Doc — clôture (SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 1 — Avancement et écarts constatés

**Rappel de l'utilisateur (2026-10-31)** : tout le moteur audio est un
prototype Python, destiné à être réécrit en C/C++ pour la performance,
l'optimisation et la fluidité. Ce moteur comprend :
- les sons (`SdSound`) et les voix ;
- le `Mixer` ;
- le driver audio et son callback PortAudio ;
- les moteurs (sampler, synthé, FluidSynth) ;
- le rendu de l'export.

Ce chantier en tient compte de trois façons :
- les interfaces restent étroites (`mix(out)` sur un tampon float32,
  événements à un indice d'échantillon, moteurs appelés par canal, note
  et vélocité) ;
- rien de wx ni de propre à Python dans le chemin audio ;
- les tests fixent le comportement observable (contenu des tampons,
  découpage en blocs), qui servira de référence à la version native.

- **1b1** — conforme à W7. `Mixer` reprend le mélange, les voix, le
  chargement des sons, le volume global et les sources externes.
  `mix(out)` remplit le tampon, volume global appliqué, sans écrêtage.
  `SoundDeviceDriver(Mixer)` ajoute le flux et `close()` ; son callback
  fait `mix`, puis `np.clip`. Comportement inchangé, 2862 verts.
- **1c1** — 21 tests dans `tests/test_mixer.py` :
  - aucun flux ouvert, constantes ;
  - mélange non écrêté, en positif et en négatif ;
  - volume global, pan, sources externes avant le volume global ;
  - voix consommées d'un appel à l'autre ;
  - découpage en blocs quelconques identique à un seul bloc, pour les voix
    one-shot (avec `phase_incr`) et bouclantes. C'est ce qui permettra de
    rendre jusqu'à chaque événement ;
  - release, jeu depuis un autre fil ;
  - callback du driver = `mix`, puis écrêtage.

  L'écrêtage remis dans `mix` à l'essai fait échouer trois tests. Limite
  constatée : le LFO d'une voix one-shot est constant sur un bloc ; avec
  vibrato, le découpage en blocs change donc un peu le son. Le rendu
  gardera des blocs de 512 au plus, comme à l'écoute (W7).

## Phase 8 étape 1d2 — Avenant : passage à blanc avant le rendu

### Origine

À la fin de 1d1, une limite est apparue. Un Program Change sur une piste
qui n'est pas en Banque peut assigner un slot synthé pas encore chargé
(`assign_slot` → `_ensure_slot_synth`). Le patch se charge alors en tâche
de fond. À l'écoute, on ne l'entend qu'au passage suivant de la boucle ;
dans l'export, il manquerait. L'utilisateur (2026-10-31) : « c'est
gênant, car le rendu ne serait pas fidèle à l'écoute » ; il faut
parcourir le pattern deux fois de suite, pour inclure les sons chargés à
la volée, comme Sonar et, sans doute, Reaper.

### Comportement de Reaper et de Sonar (vérifié le 2026-10-31)

- **Reaper, « 2nd pass render »** (ajouté en 6.20) : Reaper joue la zone à
  rendre une première fois, puis la rend au second passage. La résonance
  de la fin se retrouve ainsi au début, pour des boucles sans couture.
  C'est notre W2 (régime établi).
- **Reaper, « Dry run »** : un rendu sans fichier écrit.
- **Sonar** : rien trouvé sur un rendu en deux passes. Son export propose
  le « Fast Bounce » (hors temps réel) ou le rendu en temps réel. Les
  forums conseillent le temps réel pour les instruments qui rendent mal
  en Fast Bounce.

### Décision

**W9 — Passage à blanc, puis attente des chargements, puis rendu.**
- Avant le rendu, et dans les deux fins (W1), tous les événements du
  pattern sont joués une fois sur la copie du routeur. C'est un
  « passage à blanc » : le mixeur n'est pas rendu, rien n'est écrit. Tout
  ce qui se charge à la volée est ainsi demandé : patchs des slots
  assignés par Program Change, sons transposés calculés à la demande.
- Le rendu attend ensuite la fin des chargements (`wait_loaded` de la
  copie). Les voix du passage à blanc sont coupées.
- Le rendu repart d'une copie neuve du routeur de l'écoute (état du
  début du pattern), qui reprend les moteurs chargés pendant le passage à
  blanc, puis `chase(tape, 0)`.
- Écartée : enchaîner simplement deux passages rendus. Le rendu va plus
  vite que le temps réel, et un patch lancé au premier passage peut ne
  pas être prêt au second. Attendre explicitement rend l'export
  déterministe.
- Le rendu correspond alors à ce qu'on entend une fois la boucle
  installée, quand tout est chargé.
- W2 est inchangé : les passages du régime établi viennent après le
  passage à blanc.

### Découpage

W9 entre dans **1f1** (boucle de rendu) et ses tests dans **1g1**. Les
étapes suivantes gardent leurs numéros.

### Phase 8 étape 1 — Avancement après l'avenant (1e1)

- **1d1** — conforme à W6 et W7 :
  - `TrackRouter(schedule=)` remplace les trois `threading.Timer` (banque,
    grille sur synthé, patch) ; par défaut `_timer_schedule`, l'horloge
    murale ;
  - `render_copy(driver, bank_engine, schedule, status_cb)` sur
    `TrackRouter`, `SoundManager` et `SynthEngine`. Un moteur partagé par
    deux slots n'est copié qu'une fois. Les messages de la copie sont
    ignorés par défaut ;
  - `BankEngine.render_copy()` : pour FluidSynth, un moteur neuf aux mêmes
    fréquence, gain et Bank Select, sans banque chargée ;
  - `src/player/tape_events.py` : `tape_events`, `sort_events`, `grid_hit`,
    `play_event` et les marqueurs. `dp_playback.py` s'en sert.

  **Écart** : les tables de `SoundManager` et les caches de `SynthEngine`
  sont copiés, et non partagés comme le prévoyait W7. Sans cela,
  `stop_all_voices` (qui vide `_loop_cache`) ou un kit chargé pendant
  l'export auraient touché l'écoute. Les sons eux-mêmes restent partagés.
  Limite trouvée : les synthés chargés à la volée ; elle a mené à l'avenant
  1d2 (W9).
- **1e1** — 30 tests dans `tests/test_render_copy.py` :
  - ordonnanceur : minuterie murale par défaut, ordonnanceur injecté pour
    les trois coupures, note tenue non ordonnancée ;
  - copie du routeur : état recopié et indépendant, mute et solo,
    moteurs sur le mixeur du rendu, rien joué sur l'écoute, banque chargée
    au `chase` sans toucher au moteur de l'écoute ;
  - copies de `SoundManager` (sons partagés, tables indépendantes, groupe
    de mute), de `SynthEngine` (même patch, état neuf, caches
    indépendants) et de FluidSynth (mêmes réglages) ;
  - `tape_events` (fenêtre, conversion, `min_sec`), tri stable,
    `grid_hit`, `play_event`. Le player et `play_event` donnent les mêmes
    volume, pan et durée pour une même case.

  Trois défauts réintroduits à l'essai font échouer des tests : minuterie
  remise dans `on_patch_tape`, cache partagé, volumes partagés.
- **1f1** — `src/audio_export.py`, conforme à W1-W7 et W9 :
  - `render_pattern(...)` rend dans un `RenderResult` non écrêté ;
    `apply_gain`, `dither_tpdf` et `write_wav` écrivent le fichier ;
  - `_Session` réunit la copie du routeur, son `Mixer`, la banque copiée
    et une file triée à l'échantillon. À échantillon égal, les fins de
    note passent avant les notes, comme dans l'export MIDI (D7) ; sans
    cela, une note rejouée sur la même touche serait coupée ;
  - `BankEngine.active_voices()` (FluidSynth :
    `fluid_synth_get_active_voice_count`).

  **Écarts** :
  - `render_pattern` attend aussi les chargements de l'écoute
    (`router.wait_loaded()`) avant de copier ;
  - `status_cb` fait remonter les messages du passage à blanc. Trouvé à
    l'essai : une erreur de patch passait sous silence et l'export aurait
    été muet sans prévenir ;
  - pas de rendu à blanc du mixeur : le passage à blanc joue seulement
    les événements.

  **Essais** :
  - kit seul : le régime établi est identique au repli additif (écart
    0,0) ;
  - avec FluidSynth : écart de 0,167, voulu (la note rejouée sur la même
    touche est relâchée) ;
  - W9 vérifié avec `PATCHS/piano_01.json`.
- **1f2** — trouvé en 1g1 : la résonance finissait à la fin du bloc (511
  échantillons de silence au plus), ce qui pouvait ajouter un passage au
  régime établi. Elle finit maintenant au dernier échantillon non nul.
- **1g1** — 38 tests dans `tests/test_audio_export.py` :
  - positions à l'échantillon près ; carte de tempo ; signature et
    mesures ; longueur exacte ; pattern vide ; fenêtre de la lecture ;
  - régime établi : identique au repli additif sans interactions, plus de
    passages quand la résonance dépasse le pattern, passages identiques,
    charleston coupée à la jonction ;
  - fin de la résonance au dernier échantillon, plafond, note tenue
    attendue, release de la banque ;
  - fin de note avant la note rejouée au même échantillon ; aucune
    minuterie murale ;
  - passage à blanc : synthé chargé à la volée rendu dès le premier
    passage, écoute intacte, erreur annoncée, chargement de l'écoute
    attendu ;
  - banques copiées fermées, mixage (mute, volume de piste, volume et pan
    globaux, pan du pad) ; FluidSynth réel si présent ;
  - progression croissante jusqu'à 1, annulation qui ferme les moteurs ;
  - gain (atténuer, normaliser, silence), dither (±1 LSB, centré,
    reproductible), trois formats relus, 16 bits par défaut, format
    inconnu.

  Six défauts réintroduits à l'essai font échouer des tests : ordre des
  fins de note, passage à blanc retiré, premier passage gardé, toujours
  deux passages, coupe au dernier échantillon retirée, blocs non coupés
  aux événements.

## Phase 8 étape 1h3 — Avenant : limiteur au lieu de l'atténuation globale

### Origine

Essai de 1h1 par l'utilisateur (2026-10-31) : « même en choisissant le
param "Normaliser", le fichier final est moins fort qu'à l'écoute ».

Mesures sur `EXPORTS/Pat_01.wav` (4 mesures, « Normaliser » cochée) :
- crête à −0,3 dBFS, donc la normalisation a fonctionné ;
- RMS à −18,8 dBFS. La boucle TiMidity validée le 2026-10-24
  (`Pat_01_boucle.wav`), à crête égale, est à −13,7 dBFS : 5 dB plus
  forte ;
- 3 échantillons sur 9,6 s dépassent −0,9 dBFS, et 30 dépassent
  −1,9 dBFS.

Cause probable : le mixage brut dépasse 0 dBFS sur quelques
transitoires.
- À l'écoute, le callback les écrête (`np.clip`). C'est inaudible sur si
  peu d'échantillons, et le reste garde tout son niveau.
- Dans l'export, W3 ramène cette crête à −0,3 dBFS en baissant tout le
  fichier de plusieurs dB.

### Comportement de Reaper (vérifié le 2026-10-31)

Le dialogue de rendu de Reaper a une section « Normalize/Limit ». On y
normalise à une crête (crête d'échantillon ou true peak) ou à une
loudness (RMS, LUFS), et on peut ajouter un limiteur brickwall. Les forums
conseillent −0,3 dB TP pour un fichier final.

### Décision (utilisateur, 2026-10-31)

**W10 — Un limiteur brickwall à anticipation remplace l'atténuation
globale de W3.**
- **Seuil** : −0,3 dBFS (`PEAK_DB`), en crête d'échantillon. Le gain est
  le même sur les deux canaux (stéréo liée) : l'image ne bouge pas.
- **Gain demandé** par échantillon : `min(1, seuil / crête des deux
  canaux)`.
- **Anticipation** de 5 ms (`A` échantillons). Un minimum glissant sur
  `[n, n + A]`, puis une moyenne glissante sur `A` échantillons, donnent
  une enveloppe qui descend en douceur avant la crête. Elle ne dépasse
  jamais le gain demandé sur la crête : aucun échantillon ne passe le
  seuil.
- **Retour** exponentiel vers 1, en 50 ms environ, après le minimum
  glissant et avant la moyenne.
- **Ailleurs, le gain reste à 1** : le fichier a le niveau de l'écoute,
  sans la distorsion de l'écrêtage.
- **Boucle exacte** : le limiteur traite le fichier comme une boucle. On
  lui donne la fin du fichier avant le début, et le début après la fin,
  sur la longueur de l'anticipation et du retour ; seule la partie
  centrale est gardée. La jonction reste sans couture : un limiteur
  appliqué au fichier seul verrait un début sans passé.
- **« Normaliser »** ne sert plus qu'à monter un mixage dont la crête
  est sous le seuil, jusqu'à −0,3 dBFS. Au-dessus du seuil, c'est le
  limiteur qui agit, case cochée ou non.
- **Compte rendu** : « limiteur : −3,2 dB au plus » (la plus forte
  réduction) à la place de « atténué de … dB » ; « normalisé :
  +3,1 dB » ne change pas.
- **Ordre à l'écriture** : limiteur ou normalisation, puis dither en
  16 bits, puis écrêtage final de sécurité à ±1 pour les formats
  entiers. Le dither ajoute ±1 LSB, bien en dessous de la marge de
  0,3 dB.
- **Prototype, cible C/C++** : le retour exponentiel est une récurrence
  par échantillon. En Python, elle ne tourne que sur les zones où le gain
  demandé est sous 1, prolongées du retour. Le reste est vectorisé.
- **Écartés** :
  - écrêter comme à l'écoute : identique à ce qu'on entend, mais avec la
    distorsion des crêtes ;
  - garder l'atténuation globale : c'est l'écart constaté ;
  - normaliser en loudness (LUFS) : hors du besoin.

### Portée exclue

- true peak (crêtes entre échantillons, par suréchantillonnage) ;
- réglages du limiteur dans le dialogue (seuil, anticipation, retour) ;
- limiteur à l'écoute : le callback garde son `np.clip`.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **1h3** | Doc — cet avenant. | `docs/DESIGN.md` |
| **1h4** | Implémentation — limiteur (`limit_peaks`, boucle circulaire), `write_wav` (limiteur, normalisation, dither) et compte rendu. | `src/audio_export.py`, `src/ui/mw_project.py` |
| **1h5** | Tests — limiteur (aucun échantillon au-dessus du seuil, gain à 1 hors des crêtes, anticipation, retour, stéréo liée, jonction de boucle continue, normalisation des mixages faibles, compte rendu) ; tests de gain de 1g1 adaptés. | `tests/test_audio_export.py` |

Les étapes 1i1 (tests de l'interface) et 1j1 (clôture) gardent leurs
numéros.

### Phase 8 étape 1 — Avancement après l'avenant 1h3 (1h5)

- **1h1** — dialogue « Export audio », Alt+Shift+W dans les deux
  fenêtres, rendu dans un fil, avancement et compte rendu au statut.
- **1h2** — retours de l'utilisateur à l'essai : le dialogue du fichier
  passe avant celui des paramètres (ordre standard) ; le dernier dossier
  choisi est retenu pour la session, comme celui de l'import MIDI. D'un
  lancement à l'autre, il faudra écrire `config.json` (chantier
  « Dialogue de config.json »).
- **1h4** — limiteur conforme à W10 :
  - `limit_peaks(data, seuil, sr, loop)` ;
  - `apply_gain` rend (données, gain de normalisation, réduction du
    limiteur) ; `write_wav` rend (gain, réduction) ;
  - `RenderResult.looped` choisit le limiteur circulaire ;
  - compte rendu « limiteur : −X dB au plus ».

  **Écart** : W10 prévoyait une récurrence par échantillon limitée aux
  zones réduites. Tout est vectorisé :
  - minimum glissant par blocs (van Herk / Gil-Werman) ;
  - retour exponentiel par un maximum cumulé en logarithmes
    (`z[n] = max_k d[k]·c^(n-k)`) ;
  - moyenne glissante par somme cumulée.

  10 s de son sont limitées en 0,06 s. Une borne finale `min(moyenne, g)`,
  qui aurait supprimé la rampe d'anticipation, a été retirée avant
  l'essai.
- **1h5** — 55 tests dans `tests/test_audio_export.py` : 17 de plus, et
  les 7 tests de gain de 1g1 adaptés.
  - **Limiteur** : aucun échantillon au-dessus du seuil ; crête pile au
    seuil ; gain à 1 avant l'anticipation et après le retour ; rampe de A
    échantillons sans saut ; retour exponentiel ; stéréo liée ; signal
    sous le seuil intact ; boucle circulaire (fin réduite, jonction
    continue, identique au passage du milieu de trois copies) ; une
    minute en moins de 10 s.
  - **Gain** : mixage chaud au limiteur, « Normaliser » coché ou non ;
    normalisation des mixages faibles ; niveau gardé hors des crêtes dans
    les trois formats ; `looped` du rendu en boucle exacte.
  - **Compte rendu** : limiteur, normalisation, fin, format, résonance
    coupée, messages.

  Six défauts réintroduits à l'essai font échouer des tests : sans
  anticipation, sans retour, boucle non circulaire, sans moyenne,
  atténuation globale, `write_wav` sans boucle.

**Point ouvert — niveau (utilisateur, 2026-10-31)** : après le limiteur,
l'export de `Pat_01` est à −0,3 dBFS de crête et −13,4 dBFS RMS, au
niveau de la boucle TiMidity (−13,7 dBFS). L'utilisateur l'entend
pourtant moins fort qu'à l'écoute dans GroovyboxIt : il doit monter le
volume de mpv pour retrouver le niveau de l'appli.
- Déjà vérifié : pas de volume mpv mémorisé ni réglé ; volumes par
  application de PipeWire à 1,0.
- À vérifier plus tard : le volume global de l'appli au moment de
  l'export ; une mesure de la sortie son (moniteur PipeWire), appli puis
  mpv.

Au passage, la boucle TiMidity de référence, écrasée par un export du même
nom, a été refaite sous `EXPORTS/Pat_01_boucle_timidity.wav`, avec des
mesures identiques à l'originale.

## Phase 8 étape 1h6 — Avenant : normalisation à un niveau visé (crête, RMS, LUFS-I)

### Origine

Le point ouvert de 1h5 : l'export sonne moins fort qu'à l'écoute.
L'utilisateur (2026-10-31) se souvient que Reaper propose une case de
normalisation, et un champ à partir de −24 dB pour choisir jusqu'à quel
niveau monter le rendu : « un très bon compromis, qui permet de résoudre
le problème du niveau final ».

### Comportement de Reaper (vérifié le 2026-10-31)

Dans la section « Normalize/Limit » du dialogue de rendu :
- une case « Normalize » ;
- un niveau visé en dB ;
- un type de mesure : Peak, True Peak, RMS-I, LUFS-I, LUFS-M max,
  LUFS-S max ;
- à part, une case « Brickwall limit », avec son plafond.

Réglage courant pour un fichier final : −14 LUFS-I avec un limiteur à
−1 dB. Normaliser à une crête ne peut pas monter le volume au-delà de ce
que permet la plus haute crête. Normaliser à un niveau moyen (RMS ou
LUFS) le peut : le limiteur rattrape ensuite les crêtes qui dépassent.

### Décisions validées (utilisateur, 2026-10-31)

**W11 — Normalisation à un niveau visé**, qui remplace la normalisation à
−0,3 dBFS de W3 et W10.
- **Dialogue « Export audio »** :
  - la case « Normaliser », décochée par défaut ;
  - la liste « Mesure : Crête », « Mesure : RMS », « Mesure : LUFS-I »
    (choix 1c), LUFS-I par défaut ;
  - le champ « Niveau visé (dB) » : SpinCtrl de −24 à −6, au pas de 1 dB
    (choix 2a), −14 par défaut (choix 3a). C'est le widget qu'Orca
    annonce en temps réel.

  La liste et le champ ne sont actifs que si la case est cochée. Les
  cinq choix sont gardés pour la session.
- **Gain** = niveau visé − niveau mesuré sur le mixage rendu, vers le
  haut comme vers le bas. Le **limiteur** de W10 (−0,3 dBFS, circulaire
  en boucle exacte) agit **ensuite, toujours** : un niveau visé élevé
  monte le morceau, et le limiteur tient les crêtes. Comme dans Reaper,
  la loudness finale peut être un peu sous la cible quand le limiteur a
  beaucoup travaillé. Le compte rendu le montre.
- **Mesures** (sur les deux canaux) :
  - **Crête** : `20·log10(max |x|)`, en dBFS ;
  - **RMS** : `10·log10(moyenne de x²)` sur tous les échantillons des
    deux canaux, en dBFS (un sinus à pleine échelle mesure −3 dBFS) ;
  - **LUFS-I** : loudness intégrée selon l'UIT-R BS.1770-4 :
    - pondération K, c'est-à-dire un filtre en plateau suivi d'un
      passe-haut RLB, avec des coefficients calculés pour la fréquence du
      rendu ;
    - blocs de 400 ms, recouvrement de 75 % ;
    - `−0,691 + 10·log10(Σ canaux)` ;
    - porte absolue à −70 LUFS, puis porte relative à −10 LU.

    Sans scipy, la pondération K est appliquée par FFT (réponse en
    fréquence des deux biquads, par blocs avec recouvrement-addition).
- **Mixage silencieux** (crête nulle, ou aucun bloc au-dessus de la porte
  absolue) : pas de gain.
- **Sans « Normaliser »** : comme aujourd'hui, le limiteur seul.
- **Compte rendu** : par exemple « normalisé à −14 LUFS-I : +3,2 dB —
  limiteur : −4,1 dB au plus ».
- **Prototype, cible C/C++** : la pondération K deviendra deux biquads en
  temps réel ; la FFT n'est qu'un moyen d'éviter une boucle Python par
  échantillon.

### Conséquence de la plage (choix 2a)

« Crête » va au plus à −6 dBFS : la normalisation de crête à −0,3 dBFS
(W3) n'est plus proposée. Sans « Normaliser », le limiteur garde le
niveau de l'écoute, et les crêtes au-dessus de −0,3 dBFS restent tenues.

### Portée exclue

- True Peak, LUFS-M max, LUFS-S max ;
- plafond du limiteur réglable ;
- normalisation « seulement si trop fort » (une option de Reaper).

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **1h6** | Doc — cet avenant. | `docs/DESIGN.md` |
| **1h7** | Implémentation — mesures (crête, RMS, LUFS-I), normalisation au niveau visé, puis limiteur ; dialogue (case, liste, champ) ; options de session ; compte rendu. | `src/audio_export.py`, `src/ui/dialogs_simple.py`, `src/ui/mw_project.py` |
| **1h8** | Tests — étalonnage LUFS-I (sinus de 997 Hz à pleine échelle sur un canal : −3,01 LUFS ; portes absolue et relative), RMS et crête, gain vers le haut et vers le bas, limiteur après la normalisation, silence, dialogue, compte rendu ; tests de 1h5 adaptés. | `tests/test_audio_export.py` |

Les étapes 1i1 (tests de l'interface) et 1j1 (clôture) gardent leurs
numéros.

## Phase 8 étape 1h8 — Avenant : niveau visé jusqu'à 0 dB

### Origine

À l'essai de 1h7 (utilisateur, 2026-10-31), « ça marche avec une
normalisation de −6 dB, on atteint le même niveau que l'écoute ».
L'utilisateur propose d'étendre la plage jusqu'à +6 dB, pour les audios
très faibles.

Le niveau visé n'est pas un gain : c'est le niveau final. Un audio à
−40 LUFS normalisé à −6 est déjà monté de +34 dB. Au-dessus de −6, le
limiteur prend chaque dB de plus : transitoires aplatis, son qui pompe
et sature. Avec la mesure « Crête », une valeur au-dessus de −0,3 dBFS ne
peut pas être atteinte.

### Décision (utilisateur, 2026-10-31)

**W12 — Plage du niveau visé : de −24 à 0 dB** (au pas de 1 dB, −14 par
défaut). Reaper accepte de même toute valeur. L'utilisateur accepte que le
rendu sature au-delà d'environ −6. Ce choix remplace le choix 2a de W11
(−24 à −6).

### Piste pour le point ouvert sur le niveau

L'écoute sonne comme un fichier à −6 LUFS-I, alors que l'export limité de
`Pat_01` mesure −10,2 LUFS-I. Si le mixage brut dépasse 0 dBFS bien plus
souvent que sur ses quelques crêtes, le callback de lecture écrête
(`np.clip`) : le niveau perçu monte, au prix d'une distorsion.

À vérifier plus tard : compter les échantillons écrêtés en lecture, puis
revoir au besoin le gain de FluidSynth (0,4, § 18d4) ou le volume global.

### Découpage révisé

| Étape | Contenu | Fichiers |
|---|---|---|
| **1h8** | Doc — cet avenant. | `docs/DESIGN.md` |
| **1h9** | Implémentation — `LEVEL_MAX_DB = 0`. | `src/audio_export.py` |
| **1h10** | Tests — ceux prévus en 1h8 par l'avenant 1h6, plus la plage de −24 à 0. | `tests/test_audio_export.py` |

1i1 et 1j1 gardent leurs numéros.

### Phase 8 étape 1 — Avancement après les avenants 1h6 et 1h8 (1h10)

- **1h7** — conforme à W11 :
  - `k_weighting(sr)` et `_k_filter` (FFT, recouvrement-addition par
    blocs de 2^18) ;
  - `loudness_lufs`, `measure_level(data, mesure, sr)` ;
  - `apply_gain(data, normalize, measure, level_db, ...)` : normalisation,
    puis limiteur toujours ; `write_wav(..., normalize, measure,
    level_db)` ;
  - dialogue : liste Mesure et champ Niveau visé, actifs si Normaliser ;
  - options de session à cinq valeurs ; compte rendu « normalisé à −14
    LUFS-I : +3,20 dB ».

  **Mesures** :
  - 997 Hz à 0 dBFS sur un canal → −3,010 LUFS, à 48 kHz comme à
    44,1 kHz ; 3 min de son mesurées en 2 s ;
  - les exports de `Pat_01` (−10,2 LUFS-I) et la boucle TiMidity (−10,5)
    sont déjà plus forts que −14.

  À l'essai, −6 LUFS-I donne le niveau de l'écoute.
- **1h9** — `LEVEL_MAX_DB = 0` (W12).
- **1h10** — 76 tests dans `tests/test_audio_export.py` : 21 de plus, et
  4 tests de 1h5 adaptés.
  - **LUFS-I** : référence de la norme à 48 et 44,1 kHz ; stéréo et
    linéarité en dB ; réponse de la pondération K (≈ 0 dB à 1 kHz, ≈ +4 dB
    à 10 kHz, coupure à 20 Hz) ; aigu favorisé ; porte absolue (silence
    sans effet) ; porte relative (partie à −45 ignorée) ; silence et son
    sous −70 → None ; fichier court ; deux minutes en moins de 10 s.
  - **Crête et RMS**, mesure inconnue refusée.
  - **Normalisation** : vers le haut, vers le bas, cible élevée puis
    limiteur (loudness finale sous la cible), silence sans gain, boucle
    circulaire ; écriture au niveau visé pour les trois mesures, LUFS-I à
    −14 par défaut ; plage de −24 à 0.
  - **Dialogue** : champs inactifs sans Normaliser, plage du SpinCtrl,
    options restaurées, niveau borné.
  - **Compte rendu** de la normalisation et du limiteur.

  Six défauts réintroduits à l'essai font échouer des tests : sans porte
  relative, sans porte absolue, sans pondération K, gain inversé, pas de
  limiteur après la normalisation, RMS sur le canal le plus fort.

  **Constat** : chaque mesure LUFS fait une FFT de 2^19 points, même pour
  un fichier court ; `test_audio_export.py` passe de 2,7 s à 8,5 s. À
  optimiser au besoin : FFT à la taille du fichier, plus la queue de la
  réponse impulsionnelle.

## Phase 8 étape 1h11 — Avenant : export audio de la sélection ou du presse-papier

### Origine

Demande de l'utilisateur (2026-10-31) : exporter en audio la sélection
courante, ou le contenu du presse-papier, plutôt que le pattern entier.
- Un dialogue « Exporter la sélection ou le presse-papier » propose la
  liste « Sélection », « Presse-papier ».
- Pour « Sélection », deux champs donnent les limiteurs Gauche et Droit.
- Ok mène ensuite au même parcours que l'export audio : fichier, puis
  paramètres.
- Raccourci : Alt+Shift+S.

### Comportement de Sonar (vérifié le 2026-10-31)

L'export audio de Sonar part de la sélection : les pistes choisies, sur la
plage de temps sélectionnée (le fichier dure exactement la sélection) ;
sans sélection, tout le projet. Le module « Export » de la barre de
contrôle propose « Selection » comme source.

### État des lieux constaté en code (2026-10-31, 2989 tests verts)

- **Sélection** (`TrackEditor`, partagé par la fenêtre principale et
  l'éditeur MIDI) :
  - pistes : `_sel_tracks`, ou la piste courante si vide
    (`get_effective_tracks`) ;
  - limiteurs `_lim_left` et `_lim_right`, en pas, posés par i et o.
    Ils sont inclusifs : l'effacement par plage prend
    `lim_l ≤ t < lim_r + 1` (§ 6g2).
- **Deux presse-papiers** :
  - **pistes** (`_ClipboardData`, Ctrl+C de la fenêtre principale) :
    `tape` = {(piste relative, mesure relative, pas): [TapeEvent]} ;
    `num_bars`, `num_steps` de la source. L'événement garde son temps
    absolu, mais ni les pistes d'origine ni la mesure de départ ne sont
    retenues ;
  - **notes** (`_EventClipboard`, Ctrl+C de l'éditeur MIDI) : des notes
    seulement, chacune avec sa piste d'origine (`track`), `offset` en
    pas, `rel_offset` et une durée en ms.
- **Champs mesure:temps:pas** : `BBTHelper` (`dialogs_temporal.py`),
  `fmt` / `parse`, comme dans `LoopSelectDialog`.
- **Alt+Shift+S** est libre dans les deux fenêtres (S, Shift+S, Ctrl+S
  et Ctrl+Shift+S existent, sans Alt).
- **Rendu** : `render_pattern` rend toujours tout le pattern, de 0 à
  `mesures × pas`, et poursuit l'état des banques depuis 0
  (`chase(tape, 0)`).

### Décisions validées (utilisateur, 2026-10-31)

**W13 — Presse-papier de la fenêtre** (choix 1a) : Alt+Shift+S dans la
fenêtre principale rend le presse-papier des pistes, et dans l'éditeur
MIDI celui des notes.

**W14 — Instruments des pistes d'origine** (choix 2a).
`_ClipboardData` retient les pistes copiées (`tracks`) et le pas de début
de la copie (`start_step`). Chaque événement est rendu sur sa piste
d'origine, avec l'état actuel de cette piste (slot, mute, solo, volume,
pan). Le presse-papier des notes a déjà sa piste d'origine.

**W15 — Notes commencées avant le limiteur gauche : ignorées** (choix
3a). Les instruments sont réglés comme à cette position, comme à la
reprise de la lecture : `chase(tape, G)` rejoue Program Change, banque,
pédale, modulation et Pitch Bend des pistes sur slot Banque.

**W16 — Champs Gauche et Droit préremplis, pour l'export seul** (choix
4a). Ils sont en mesure:temps:pas, avec les limiteurs, ou tout le
pattern s'ils ne sont pas posés. Les modifier ne déplace pas les
limiteurs.

### Choix de conception proposés

**W17 — Fenêtre de rendu.** `render_pattern` reçoit une fenêtre
`[début, fin)` en pas, et un ensemble de pistes à rendre (les autres sont
vidées dans la copie du pattern rendue).
- Les événements gardés sont ceux de temps `début ≤ t < fin`.
- Les secondes sont `TempoMap.secs(t) − TempoMap.secs(début)`, et la
  longueur `secs(fin) − secs(début)`.
- La poursuite se fait à `début`.
- Sans fenêtre, rien ne change : tout le pattern, avec la fenêtre de la
  lecture (positions 0 à total − 1).
- Les deux fins (W1) s'appliquent à la fenêtre : « Boucle exacte » boucle
  sur la sélection, « Pattern + résonance » donne la sélection plus la
  résonance.

**W18 — Sélection** : les pistes de `get_effective_tracks`, et la
fenêtre `[G, D + 1)`, D compris en entier, comme l'effacement par plage.
Champs invalides, ou D < G : message, et le dialogue reste ouvert.

**W19 — Presse-papier des pistes.** Il est rendu à partir de 0, au tempo
du pattern courant :
- temps rendu = `ev.time − start_step`, mis à l'échelle
  `pas du pattern courant / pas de la source` si les résolutions
  diffèrent ;
- longueur : `num_bars` mesures du pattern courant ;
- pistes : celles d'origine (W14).

**W20 — Presse-papier des notes.** Il est rendu au tempo du pattern
courant, aligné sur la mesure :
- il commence au début de la mesure de la première note et finit à la fin
  de la mesure de la dernière ; chaque note garde sa place dans la
  mesure ;
- il ne contient que des notes, sans CC ni Pitch Bend : les instruments
  partent de l'état par défaut.

**W21 — Interface.**
1. Alt+Shift+S, dans les deux fenêtres.
2. Le dialogue « Exporter la sélection ou le presse-papier » :
   - la liste « Source : Sélection », « Source : Presse-papier » ;
   - les champs « Limiteur gauche » et « Limiteur droit » (TextCtrl
     mesure:temps:pas, avec étiquette et `SetName`), actifs seulement
     pour « Sélection » ;
   - Ok et Annuler.
3. Ok mène au parcours de l'export audio (W8 et 1h2) : dialogue de
   fichier, puis « Export audio », puis rendu dans un fil. Noms proposés :
   `Pat_NN[_nom]_selection.wav` et `Pat_NN[_nom]_presse-papier.wav`.
4. Presse-papier vide : message « Presse-papier vide », pas d'export.
5. Compte rendu : « Sélection (pistes 1, 3 ; 2:1:1 à 4:4:4) exportée en
   WAV : … », « Presse-papier (3 pistes, 2 mesures) exporté en WAV : … ».
6. La source choisie est gardée pour la session.

### Portée exclue

- notes commencées avant le limiteur gauche (W15) ;
- poursuite des Program Change sur les pistes qui ne sont pas en Banque,
  comme à la reprise de la lecture ;
- sélection d'événements de l'éditeur MIDI (Shift+↑/↓) comme source :
  seule compte la sélection de pistes et de limiteurs ;
- export d'un song.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **1h11** | Doc — cet avenant. | `docs/DESIGN.md` |
| **1h12** | Implémentation — fenêtre et pistes de `render_pattern` (W17) ; patterns de rendu de la sélection (W18) et des deux presse-papiers (W19, W20) ; `_ClipboardData.tracks` et `start_step` (W14). | `src/audio_export.py`, `src/track_editor.py` |
| **1h13** | Tests — 1h12 : positions dans la fenêtre, tempo, poursuite à G, notes d'avant G ignorées, pistes filtrées, presse-papiers (pistes d'origine, résolutions différentes, alignement sur la mesure), boucle sur la fenêtre. | `tests/test_audio_export.py`, `tests/test_track_editor.py` (au besoin) |
| **1h14** | Implémentation — W21 : dialogue, Alt+Shift+S dans les deux fenêtres, parcours, compte rendu. Essai à l'écoute et au lecteur d'écran. | `ui/dialogs_simple.py`, `ui/mw_project.py`, `ui/key_handler_alt.py`, `ui/mew_keymap.py` |

Ensuite viennent **1i1**, les tests de l'interface des deux exports
(`tests/test_audio_export_ui.py`), puis **1j1**, la clôture.

### Phase 8 étape 1 — Avancement après l'avenant 1h11 (1h14)

- **1h12** — conforme à W13-W20 :
  - `render_pattern(..., window=(début, fin), tracks=…)` ; poursuite à
    `début` dans le passage à blanc et dans les passages rendus ;
  - `selection_window(G, D)`, `clipboard_pattern`,
    `event_clipboard_pattern` ;
  - `_ClipboardData.tracks`, sauvegardé dans le `.gvp` et dans l'Undo
    (`"tracks"`, absent → 0..n−1).

  **Écart à W14** : pas de `start_step`. Un presse-papier relu d'un
  `.gvp` ne garde que la fraction de pas de chaque événement (`time =
  frac`, § 5d). On replace donc chaque événement par sa clé (mesure, pas)
  plus cette fraction, exactement comme `TrackEditor.paste`.
- **1h13** — commit imprévu, trouvé par les tests de 1h14 : le pattern de
  rendu des presse-papiers repartait à 100 BPM, car `Pattern.copy_from`
  laisse volontairement le tempo de départ au player. `_render_copy_of`
  recopie `_bpm`. **Renumérotation** : tests en 1h14 (prévus en 1h13),
  interface en 1h15 (prévue en 1h14).
- **1h14** — 95 tests dans `tests/test_audio_export.py` (19 de plus) :
  - **fenêtre** : positions relatives au début, pas D compris en entier,
    au-delà exclu ; carte de tempo dans la fenêtre ; notes d'avant G
    ignorées, même longues ; pistes filtrées ; boucle exacte en régime
    établi sur la fenêtre ; Program Change d'avant G poursuivi pour une
    piste rendue, pas pour une piste exclue ; sans fenêtre, comportement
    inchangé ;
  - **presse-papier des pistes** : pistes d'origine retenues, depuis 0,
    événements copiés ; réglages du pattern (tempo, carte, signature) ;
    autre résolution remise à l'échelle ; presse-papier relu d'un `.gvp`
    (fraction seule) ; rendu avec l'état actuel de la piste d'origine
    (piste muette) ; `tracks` sauvegardé, relu, absent → 0..n−1 ;
  - **presse-papier des notes** : aligné sur la mesure, pistes d'origine ;
    GRID (durée propre), KIT et PATCH ; vide ou sans note → None ; rendu.

  Sept défauts réintroduits à l'essai font échouer des tests : fin de
  fenêtre incluse, poursuite depuis 0, pistes non filtrées, pistes
  relatives, sans mise à l'échelle, notes non alignées, pistes non
  sauvegardées.

### Phase 8 étape 1 — Avancement (1h15, 1i1)

- **1h15** — conforme à W21 :
  - `SelectionExportDialog` (`dialogs_temporal.py`) : liste Source ;
    champs mesure:temps:pas avec étiquette et `SetName` ; `_validate`
    affiche un message et garde le dialogue ouvert ;
  - dans `ProjectMixin` : `_audio_export_ready` (export déjà en cours,
    pause) et `_audio_export_flow` (fichier, puis paramètres), communs aux
    deux exports ; `_export_audio_selection(editor=)` avec
    `_selection_job` et `_clipboard_job` ; `_start_audio_export(job=)` ;
    compte rendu au masculin ou au féminin (« exporté », « exportée ») ;
  - Alt+Shift+S dans `key_handler_alt.py` et `mew_keymap.py` (avant le
    transport).

  Essai sans écoute, sur un vrai affichage : champs préremplis, erreurs
  détectées, sélection et presse-papier rendus aux bonnes positions. Reste
  à faire par l'utilisateur : l'essai à l'écoute et au lecteur d'écran.
  Point de forme ouvert : le compte rendu dit « pattern + résonance »
  aussi pour une sélection.
- **1i1** — 27 tests dans `tests/test_audio_export_ui.py` (nouveau) :
  - **Alt+Shift+W** : fichier avant paramètres ; annulation à chaque
    dialogue ; extension ajoutée ; nom, titre et filtre proposés ; EXPORTS
    créé puis dernier dossier retenu ; cinq options gardées et transmises
    (format, normalisation, mesure, niveau, fin) ; paramètres du rendu
    (copie du pattern, pan et volume globaux, carte de tempo) ; pause de
    la lecture ; export déjà en cours ; statut d'avancement et compte rendu
    (normalisation, limiteur, messages) ; erreur annoncée ; parent et
    statut de l'éditeur ; fenêtre fermée pendant le rendu ;
  - **Alt+Shift+S** : source, puis fichier, puis paramètres ; fenêtre
    [G, D + 1) et pistes sélectionnées (ou la piste courante) ;
    limiteurs non déplacés ; presse-papier des pistes (fenêtre principale)
    et des notes (éditeur MIDI) ; presse-papier vide ; source gardée ;
  - **dialogue de la source** : valeurs préremplies, `SetName`, erreurs,
    champs inactifs pour le presse-papier, dialogue gardé ouvert sur une
    erreur ;
  - **raccourcis** dans les deux fenêtres ;
  - **un rendu réel** de la sélection jusqu'au fichier.

  Huit défauts réintroduits à l'essai font échouer des tests : dossier non
  retenu, options non gardées, pas de pause, pas D exclu, presse-papier
  des notes ignoré, droit avant gauche accepté, Alt+Shift+S absent,
  éditeur sans presse-papier des notes.

  **Piège rencontré** : `make_km()` et `teardown()` (`test_key_manager.py`)
  créent puis détruisent une `wx.App`. Les fichiers qui passent ensuite
  par ordre alphabétique (dialogues de banque, de CC, de filtre,
  explorateur) perdaient l'application : 85 `PyNoAppError` dans la suite
  complète, alors que le fichier passait seul. Le test des raccourcis
  construit donc `KeyManager(FakeWindow())` sur la `wx.App` de la session
  (`conftest.py`).

### Clôture (1j1)

**1a-1i2 FAITS** (commits `de2bdf0` à `66de2ab`, 26 commits, et ce commit
de clôture ; 3035 tests verts) : **chantier Phase 8 étape 1 complet**.
GroovyboxIt exporte en WAV le pattern, la sélection ou le presse-papier,
avec ses propres moteurs. La boucle exacte se rejoue sans couture, et le
niveau se règle comme dans Reaper.

**Ce que le chantier a livré** :
- **Moteur** (prototype, cible C/C++) :
  - `Mixer`, le mélange sans carte son ;
  - copies des moteurs pour le rendu (`render_copy`) et ordonnanceur des
    fins de note injecté dans le routeur ;
  - événements et jeu partagés par la lecture et le rendu
    (`player/tape_events.py`).
- **Rendu** (`audio_export.py`) :
  - hors temps réel, à l'échantillon près ;
  - passage à blanc, qui attend les chargements à la volée ;
  - boucle exacte en régime établi, ou pattern + résonance ;
  - fenêtre et pistes (sélection) ; presse-papiers des pistes (pistes
    d'origine, sauvegardées dans le `.gvp`) et des notes.
- **Gain** :
  - limiteur brickwall à anticipation, circulaire en boucle ;
  - normalisation à un niveau visé, en crête, RMS ou LUFS-I
    (BS.1770-4, étalonné), de −24 à 0 dB ;
  - dither en 16 bits ; formats 16, 24 et 32 bits flottant.
- **Interface** :
  - Alt+Shift+W et Alt+Shift+S, dans la fenêtre principale et dans
    l'éditeur MIDI ;
  - fichier puis paramètres ; dossier et options gardés pour la session ;
  - avancement et compte rendu au statut.

**Décisions prises en cours de route** (avenants, tous à la demande ou
avec l'accord de l'utilisateur) :
- passage à blanc (1d2) ;
- limiteur au lieu de l'atténuation globale (1h3) ;
- niveau visé en crête, RMS ou LUFS-I (1h6), étendu jusqu'à 0 dB (1h8) ;
- export de la sélection et du presse-papier (1h11) ;
- dialogue du fichier avant celui des paramètres, et dernier dossier
  retenu (1h2).

**Défauts trouvés par les tests et corrigés à part** :
- 1f2 : la résonance finissait à la fin du bloc ;
- 1h13 : un presse-papier exporté repartait à 100 BPM.

Piège des tests noté en 1i1 (`make_km` / `teardown`).

**`docs/SPECS.md` mis à jour** :
- ligne Phase 8, arborescence (`audio_export.py`, `tape_events.py`,
  `Mixer`) ;
- backends audio (`Mixer`, prototype C/C++) ;
- nouvelle section « Export audio » ;
- presse-papier des pistes (pistes d'origine) ;
- boîtes de dialogue ;
- tests (`test_mixer.py`, `test_render_copy.py`, `test_audio_export.py`,
  `test_audio_export_ui.py`).

`docs/shortcuts.md` a été mis à jour en 1i2.

**Laissé hors périmètre, pour la suite** :
- **niveau à l'écoute** (point ouvert de 1h5 et 1h8) : l'écoute sonne
  comme −6 LUFS-I, alors que l'export limité de `Pat_01` mesure −10,2. Le
  callback écrête probablement beaucoup (`np.clip`). À mesurer
  (échantillons écrêtés en lecture), puis à revoir au besoin : gain
  FluidSynth 0,4, volume global, voire un limiteur à l'écoute ;
- Alt+Shift+S : l'essai à l'écoute et avec Orca a été **confirmé** par
  l'utilisateur après la clôture (2026-10-31, 1j2). Reste un point de
  forme : le compte rendu dit « pattern + résonance » aussi pour une
  sélection ;
- export d'un song, pistes séparées (stems), autres fréquences, formats
  compressés, true peak, plafond du limiteur réglable ;
- poursuite des Program Change avant G sur les pistes qui ne sont pas en
  Banque (comme à la reprise de la lecture) ;
- mesure LUFS-I : FFT de 2^19 points même pour un fichier court, à
  optimiser au besoin ;
- dossier d'export retenu d'un lancement à l'autre : demande d'écrire
  `config.json` (chantier « Dialogue de config.json »).

**Suite décidée (utilisateur, 2026-10-31, 1j2)** : à la prochaine
session, le plan de l'export d'un song, en MIDI puis en audio, et des
pistes séparées (stems). Ce sera la Phase 8 étape 2a.

---

## Phase 8 étape 2a — Export du song (MIDI puis audio) et pistes séparées (stems)

### Numérotation des commits de ce chantier

`2a` = ce plan (doc seule). Le code commence à `2b1`. Une paire impl →
tests par sous-chantier ; `2a2`, `2b2`… pour un commit imprévu. Les
décisions de ce plan sont notées **E1, E2…** (§ 2a).

### Origine du besoin

- Le song et les stems ont été laissés hors périmètre en Phase 7 étape 10
  (export MIDI) et en Phase 8 étape 1 (export audio).
- Demande de l'utilisateur (2026-10-31, clôture 1j2) : « à la prochaine
  session on pourrait faire le plan de l'export du Song en Midi, puis en
  Audio, ainsi que les pistes séparées ». L'ordre est voulu : MIDI du
  song, puis audio du song, puis stems.
- Ajout de l'utilisateur pendant le plan (2026-10-31) : « Pour
  l'exportation des pistes séparées, ajouter l'option sélection, avec la
  possibilité d'une sélection temporelle avec les limiteurs Gauche/Droit
  de toutes les pistes » (E16).

### État des lieux constaté en code (2026-10-31, 3035 tests verts à 1j1)

- **Song** (`src/song.py`) : `_name`, `_sequence` (indices dans
  `_pattern_list` ; un même pattern peut revenir), `_looping`. Un song
  vide est refusé par `_play_song` (« Song vide — ajoutez des
  patterns… »).
- **Enchaînement en lecture** (`DrumPlayer._on_measure_end`,
  `player/dp_playback.py:221`) : en song, `_looping` du pattern est forcé
  à `False`. Chaque pattern est donc joué **une fois, en entier** ; ses
  points de boucle et son compteur sont ignorés
  (`LoopManager.compute_window`). Au passage, le player fait `copy_from`
  du pattern suivant (tape, mesures, pas, signature, carte de tempo) et
  prend son BPM. Rien n'est coupé : les voix en cours continuent. En fin
  de song, le player se met en pause, ou repart du premier pattern si le
  song boucle.
- **État propre à chaque pattern** (`MainWindow._on_song_advance`,
  `ui/mw_songs.py:133`, appliqué après coup sur le fil de l'UI) :
  - voix des pads (`_voices` : volume, pan, durée, mute, solo) ;
  - slots, mute, solo, volume, pan et canal de chaque piste ;
  - gamme de lecture (`_kb_scale`, `_kb_root_midi`) ;
  - poursuite des banques (`router.chase(new._tape, 0.0)`).

  Le mixage et les instruments **changent donc d'un pattern à l'autre**.
  À l'écoute, le changement arrive quelques millisecondes après la
  frontière ; au rendu, il peut tomber pile dessus.
- **Pattern courant** : il est édité dans le player. `_play_song` le
  range d'abord dans `_pattern_list` (`_flush_pattern_to_store`, plus
  `_voices` lu dans le `voice_manager`). Un export devra faire de même.
- **Export MIDI d'un pattern** (`midi/midi_export.py`,
  `build_pattern_midi`) : une passe sur un seul pattern. Il écrit
  programme, CC7, CC10, CC91 et CC93 au tick 0. Les notes sont coupées à
  la fin du pattern (12a4 D8), et les chevauchements traités par
  (canal, note). Les arguments viennent de `mw_project.py:107` (état du
  routeur et du `voice_manager`).
- **Export audio** (`audio_export.py`, `render_pattern`) : une seule
  carte de tempo et un seul état du routeur, plus une fenêtre et un choix
  de pistes (`tracks`). Le limiteur (`limit_peaks`) est une enveloppe de
  gain, multipliée aux données et identique sur les deux canaux.
- **Export de la sélection** (Alt+Shift+S, `_export_audio_selection`,
  `mw_project.py:263`) : le dialogue `SelectionExportDialog` propose la
  source (sélection ou presse-papier) et les limiteurs G et D, préremplis
  en mesure:temps:pas. La sélection prend les pistes de
  `TrackEditor.get_effective_tracks` (les pistes sélectionnées, sinon la
  piste courante). Il n'existe pas encore de choix « toutes les pistes ».
- **Fenêtre Songs** (`ui/song_window.py`) : Alt+Shift+E et Alt+Shift+W y
  sont libres.

### Comportement de Sonar et de Reaper (de mémoire, à vérifier à l'essai)

- **Song** : les deux exportent la ligne de temps du projet d'un seul
  tenant, et les queues des sons débordent sur la suite. En MIDI, la
  piste de tempo porte les changements de tempo et de signature.
- **Stems** : Reaper propose « Master mix », « Stems (selected tracks) »
  ou « Master mix + stems ». Sa plage peut être tout le projet ou la
  sélection temporelle, et son nom de fichier accepte des motifs
  (`$track`, sous-dossier possible). Ses options de normalisation
  comprennent un gain commun aux stems, calculé sur le mix. Sonar exporte
  « chaque piste séparément », sur la sélection ou sur tout le projet.

### Décisions validées (utilisateur, 2026-10-31)

- **E1 — Résonance continue** : le song est rendu d'un seul tenant. Les
  notes et les queues d'un pattern débordent sur le suivant, comme à
  l'écoute.
- **E2 — Deux fins pour le song audio**, comme pour un pattern : « song +
  résonance » ou « boucle exacte » (queue du dernier pattern repliée sur
  le début du premier, en régime établi). Par défaut : boucle exacte si
  le song est en mode boucle, sinon song + résonance. En MIDI, le song
  est écrit une seule fois.
- **E3 — Stems dans un sous-dossier** du nom du fichier : `Song_01/`
  contient `Song_01_01_Drums.wav`, `Song_01_02_Bass.wav`… (numéro de
  piste sur deux chiffres, puis nom de la piste ou `Track NN`). Avec
  « mix + pistes », le mix `Song_01.wav` est écrit à côté du dossier. La
  règle est la même pour un pattern ou une sélection
  (`Pat_03_selection/Pat_03_selection_01_Drums.wav`).
- **E4 — Gain commun calculé sur le mix** : la normalisation et le
  limiteur sont calculés sur le mix. Le même gain et la même enveloppe du
  limiteur sont appliqués à chaque stem, sans limiteur propre. La somme
  des stems redonne le mix, au dither près (sauf les cas de E12).
- **E16 — Stems de la sélection, sur les pistes choisies ou sur toutes**
  (ajout de l'utilisateur) : le dialogue d'Alt+Shift+S reçoit, pour la
  source « Sélection », un choix **Pistes** :
  - « Pistes sélectionnées » : comportement actuel, les pistes
    sélectionnées ou la piste courante ;
  - « Toutes les pistes » : sélection temporelle seule. Les limiteurs
    Gauche et Droit s'appliquent à toutes les pistes non vides et
    audibles.

  Le choix est retenu pour la session. Il vaut pour le mix comme pour les
  stems (E14) : Alt+Shift+S, « Toutes les pistes », Sortie « Pistes
  séparées » donne un stem par piste, entre G et D. Le compte rendu le
  dit (« toutes les pistes ; 2:1:1 à 4:4:4 »). La fenêtre principale et
  l'éditeur MIDI sont concernés tous les deux.

### Choix de conception proposés

**Le song comme suite de segments**

- **E5 — `SongSegment`** : un pattern du song, figé en données pures et
  sans wx. Il contient :
  - une copie du pattern (tape, mesures, pas, signature, carte de
    tempo) et son BPM ;
  - son état : voix des pads, slots, mute, solo, volume, pan et canal
    des pistes, gamme ;
  - son début, en secondes et en noires depuis le début du song.

  `song_segments(song, pattern_list)` construit la liste, après le
  rangement du pattern courant. Les deux exports partent de cette liste.
  Chaque pattern est pris en entier, une fois (comme en lecture) ; ses
  points de boucle sont ignorés.
- **E6 — Tempo et signature de chaque pattern** : chaque segment garde
  son BPM, sa carte de tempo et sa signature, comme en lecture. La durée
  du song est la somme des durées des segments.

**Export MIDI du song**

- **E7 — Une seule écriture pour le pattern et le song** :
  `build_pattern_midi` est découpé en deux parties, un écrivain de
  segment (tick de départ, état du segment) et un assemblage. Un pattern
  devient un song d'un seul segment. **Le fichier d'un pattern ne change
  pas d'un octet** ; les tests existants de `test_midi_export.py` en
  sont la garde.
- **E8 — Piste conductor** : elle porte le nom du song. À chaque début de
  pattern, elle reçoit un `set_tempo`, un `time_signature` si la
  signature change, et un `marker` au libellé du pattern (Sonar et
  Reaper l'affichent). Viennent ensuite les changements de tempo de
  chaque pattern, décalés.
- **E9 — État des pistes à chaque pattern** : au premier segment, comme
  aujourd'hui (programme, CC7, CC10, CC91, CC93). Ensuite, programme, CC7
  et CC10 ne sont réécrits que s'ils changent par rapport au segment
  précédent sur cette piste, ou si le canal de la piste change. Les
  pistes en Banque gardent leurs CC0, CC32 et Program Change de `_tape`,
  poursuivis par segment (comme `chase`).
- **E10 — Notes au passage** : une note déborde sur le pattern suivant
  (E1) et n'est coupée qu'à la fin du song. Les chevauchements par
  (canal, note) sont traités sur tout le song. Une piste n'est omise que
  si elle est vide, ou muette ou hors solo, dans **tous** les segments.
  Dans un segment où elle est muette, ses événements sont omis.

**Export audio du song**

- **E11 — `render_song(segments, router, …)`** : un rendu continu.
  - Les événements de chaque segment sont placés à l'échantillon par sa
    carte de tempo, puis décalés de son début.
  - À chaque frontière, à l'échantillon près, l'état du segment est
    appliqué à la copie du routeur et au `voice_manager` du rendu :
    slots, mix, canaux, gamme, voix, `chase` des banques. Les voix en
    cours continuent.
  - Le passage à blanc parcourt tous les segments, pour charger tous les
    patchs du song.
  - Les deux fins (E2) reprennent le régime établi de `render_pattern`,
    sur la durée du song.

  `render_pattern` devient un `render_song` d'un seul segment ; ses tests
  sont la garde.

**Pistes séparées (stems)**

- **E12 — Un rendu par piste** : un rendu par piste non vide et audible
  (`tracks={t}`), en plus du mix. C'est simple et sûr. La durée est
  multipliée par le nombre de pistes (prototype, voir la note « moteur
  audio = prototype Python, cible C/C++ ») ; un mixeur à bus par piste
  pourra venir avec le moteur C/C++. La somme des stems égale le mix,
  sauf dans deux cas, notés dans la doc :
  - un groupe de mute partagé entre pistes (une charleston coupée par une
    autre piste) ;
  - deux pistes sur un même canal de banque (le CC7 de l'une agit sur
    l'autre).
- **E13 — Gain commun (E4)** : `apply_gain` rend aussi son gain de
  normalisation et l'enveloppe du limiteur (`limit_peaks`). Les deux sont
  calculés sur le mix, qui est rendu même s'il n'est pas écrit, puis
  appliqués à chaque stem. Le dither est tiré indépendamment pour chaque
  fichier.
- **E14 — Sortie, dans le dialogue des paramètres**
  (`AudioExportDialog`) : « Mix », « Pistes séparées » ou « Mix +
  pistes ». Disponible pour le pattern, la sélection (E16), le
  presse-papier et le song, et retenue pour la session comme les autres
  options. Le compte rendu donne le nombre de fichiers et le dossier.

**Interface**

- **E15 — Fenêtre Songs** : Alt+Shift+E exporte en MIDI le song
  sélectionné, et Alt+Shift+W l'exporte en audio. Le parcours est celui
  d'un pattern : fichier dans `EXPORTS`, puis les paramètres pour
  l'audio. Le nom proposé est `Song_NN[_nom]`. La lecture est mise en
  pause pendant le rendu. Un song vide est refusé, avec le message de la
  lecture. La fenêtre principale garde Alt+Shift+E et Alt+Shift+W pour
  le pattern.

### Portée exclue

- l'export du song depuis la fenêtre principale ou l'éditeur MIDI ;
- une sélection temporelle dans un song (les limiteurs restent ceux du
  pattern) ;
- les stems en MIDI (le SMF de type 1 sépare déjà les pistes) ;
- un mixeur à bus par piste (E12), les autres fréquences, les formats
  compressés, le true peak ;
- le métronome et le Note Repeat dans les fichiers ;
- le point ouvert du niveau à l'écoute (1j1), qui reste un chantier à
  part.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **2a** | Doc — ce plan. | `docs/DESIGN.md` |
| **2b1** | Implémentation — `SongSegment`, `song_segments`, rangement du pattern courant avant export (E5, E6). | `src/song.py`, `ui/mw_songs.py` |
| **2c1** | Tests — 2b1 (début des segments en secondes et en noires, tempo et signature par pattern, carte de tempo, pattern répété, état figé indépendant de la liste, pattern courant rangé). | `tests/test_song_segments.py` (nouveau), `docs/SPECS.md` |
| **2d1** | Implémentation — écrivain de segment et `build_song_midi` (E7-E10). | `midi/midi_export.py` |
| **2e1** | Tests — 2d1 (pattern identique à l'octet ; conductor : tempo, signature, marqueurs ; état réécrit au changement seulement ; notes qui débordent ; muet par segment ; banque). | `tests/test_midi_export.py` |
| **2f1** | Implémentation — Alt+Shift+E dans la fenêtre Songs (E15). | `ui/song_window.py`, `ui/mw_songs.py`, `ui/mw_project.py` |
| **2g1** | Tests — 2f1. | `tests/test_song_export_ui.py` (nouveau), `docs/SPECS.md` |
| **2h1** | Implémentation — `render_song`, état appliqué aux frontières, passage à blanc sur tout le song, deux fins (E11). | `src/audio_export.py` |
| **2i1** | Tests — 2h1 (pattern inchangé, frontières à l'échantillon, tempo par segment, queue qui déborde, changement de slot et de mix à la frontière, boucle exacte du song). | `tests/test_audio_export.py` |
| **2j1** | Implémentation — Alt+Shift+W dans la fenêtre Songs (E15). Essayé à l'écoute et avec Orca. | `ui/song_window.py`, `ui/mw_project.py` |
| **2k1** | Tests — 2j1. | `tests/test_song_export_ui.py` |
| **2l1** | Implémentation — stems : rendu par piste, gain et enveloppe communs, sous-dossier, option Sortie, compte rendu (E3, E4, E12-E14). | `src/audio_export.py`, `ui/dialogs_simple.py`, `ui/mw_project.py` |
| **2m1** | Tests — 2l1 (somme des stems = mix, nommage et dossier, pistes muettes omises, gain commun, option retenue). | `tests/test_audio_export.py`, `tests/test_audio_export_ui.py` |
| **2n1** | Implémentation — choix Pistes (« Pistes sélectionnées » / « Toutes les pistes ») dans le dialogue d'Alt+Shift+S, fenêtre principale et éditeur MIDI ; compte rendu (E16). Essayé avec Orca. | `ui/dialogs_temporal.py`, `ui/mw_project.py` |
| **2o1** | Tests — 2n1 (toutes les pistes entre G et D, mix et stems ; choix retenu ; pistes vides ou muettes omises ; ordre de tabulation du dialogue). | `tests/test_audio_export_ui.py` |
| **2p1** | Doc — clôture (SPECS : Export MIDI, Export audio, fenêtre Songs, dialogues ; raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 2 — Avancement (2b1, 2c1)

- **2b1** (`d0f6135`) : `src/song.py` reçoit `frozen_pattern`,
  `SongSegment`, `song_segments` et `song_secs` (E5, E6). `ui/mw_songs.py`
  reçoit `_store_current_pattern`, désormais commun à `_play_song` et à
  `_song_load_pattern`, et `_song_segments(song_idx)` pour les exports.
- **2c1** : `tests/test_song_segments.py`, 18 tests ; 3053 tests verts.
- **Précisions par rapport au plan** :
  - un indice de la séquence hors du store est ignoré, sans laisser de
    trou dans le temps ;
  - la copie figée met la boucle du pattern à « non » et efface ses
    points de boucle : chaque pattern est joué une fois en entier, comme
    en song. Le store n'est pas touché.
  - les événements de la tape sont partagés avec le store, comme dans
    `copy_from` et le `_snapshot` de l'export audio ; seules les listes
    sont copiées.

### Phase 8 étape 2 — Avancement (2d1, 2e1)

- **2d1** (`921c553`) : dans `midi/midi_export.py`, `build_song_midi`,
  `SongPart`, `export_song` et l'écrivain de segment `_segment_track`
  (E7-E10). `build_pattern_midi` est devenu un song d'un seul segment,
  sans marqueur. Les 115 fichiers MIDI construits par la suite de tests
  ont été comparés avant et après, par empreinte : identiques à l'octet.
- **2e1** : 22 tests du song dans `tests/test_midi_export.py`.
- **Précisions par rapport au plan** :
  - **E9, état comparé par canal** : programme, CC7, CC10, CC91 et CC93
    sont comparés à l'état laissé **sur ce canal** par les patterns
    précédents, événements de `_tape` compris. Un CC7 enregistré qui a
    changé le volume fait donc réécrire le volume rangé du pattern
    suivant, comme à la lecture. Sur un canal où la piste n'a pas encore
    joué, l'état est écrit en entier.
  - **E10** : une note qui déborde garde sa durée en secondes ; sa fin est
    placée au tempo du pattern où elle tombe. Un événement placé à la fin
    d'un pattern, ou au-delà, reste omis : il n'est pas reporté sur le
    pattern suivant.
  - **Piste en Banque** : au début de chaque pattern, elle repart du
    canal de la piste dans ce pattern, comme à la lecture (canaux du
    pattern suivant, puis `chase`).
  - **Nom de piste** : celui du premier pattern où elle joue.
  - **Conductor** : le marqueur précède le tempo et la signature au même
    tick.

### Phase 8 étape 2 — Avancement (2f1, 2g1)

- **2f1** (`13fa3fa`) : Alt+Shift+E dans la fenêtre Songs exporte en MIDI
  le song courant (`_export_song_midi`). Les réglages de chaque pattern
  sont calculés d'après son état figé (`_song_midi_params`), par le même
  cœur que ceux du pattern courant (`_midi_params`). La règle mute / solo
  d'une piste est devenue `TrackRouter.track_audible`. Le fichier MIDI
  d'un pattern reste identique à l'octet : les 115 fichiers de référence
  ont été comparés de nouveau.
- **2g1** : `tests/test_song_export_ui.py`, 19 tests.
- **Précisions par rapport au plan** :
  - **Piste en Banque dans un song** : elle prend le nom de son slot. Le
    preset joué dépend de la position dans le song et n'est pas connu
    avant le rendu. L'export d'un pattern garde le nom du preset.
  - **Annulation** : le pattern courant n'est rangé qu'après le dialogue
    du fichier. Annuler ne touche donc pas au store.
  - **Compte rendu** : il s'affiche dans la ligne d'état de la fenêtre
    Songs, avec le nombre de patterns (« 1 pattern », « 2 patterns »).
- **À essayer dans l'appli** : Alt+Shift+E dans la fenêtre Songs, à
  l'écoute du fichier et avec Orca.

### Phase 8 étape 2 — Avancement (2h1, 2i1)

- **2h1** (`df845d3`) : `render_song` dans `audio_export.py` (E11).
  - L'état d'un pattern (`_PatternState`) entre dans la file des
    événements à sa frontière, entre les fins de note et les notes.
  - Les voix des pads de chaque segment partent de celles de l'écoute,
    réglées d'après le pattern (`_segment_voices`).
  - `render_pattern` et `render_song` partagent `_render` et une ligne de
    temps. Les 43 rendus de pattern de la suite ont été comparés avant et
    après, par empreinte : identiques.
- **2i1** : 17 tests du song dans `tests/test_audio_export.py`.
- **Précisions par rapport au plan** :
  - **Passage à blanc** : seul lui demande le chargement des slots de
    synthé du song. Les sessions de rendu reprennent les moteurs chargés,
    sans relancer de chargement en cours de rendu.
  - **Démarrage** : aucune poursuite avec l'état de l'écoute ; l'état du
    premier pattern est appliqué à l'échantillon 0.
  - **Groupes de mute** : ils viennent du kit (`SoundManager`), communs à
    tout le song. Une charleston fermée au début d'un pattern coupe
    l'ouverte du pattern précédent.
  - **Slot vide** : une piste sur un slot sans instrument joue les sons du
    kit, au rendu comme à la lecture (`TrackRouter.on_play`). Ce n'est pas
    un silence.
  - **Fin par défaut** : `render_song` prend END_TAIL ; l'interface (2j1)
    choisira END_LOOP si le song est en mode boucle (E2).

### Phase 8 étape 2 — Avancement (2j1, 2k1)

- **2j1** (`5573e2a`) : Alt+Shift+W dans la fenêtre Songs exporte en WAV
  le song courant (`_export_song_audio`). Le parcours est celui d'un
  pattern (`_audio_export_flow`, `_start_audio_export`), avec un travail
  « song » rendu par `render_song`.
- **2k1** : 19 tests dans `tests/test_song_export_ui.py`, dont un rendu
  réel jusqu'au fichier.
- **Précisions par rapport au plan** :
  - **Fin proposée (E2)** : boucle exacte si le song boucle, sinon « Song
    + résonance ». La fin choisie pour un song n'est pas gardée pour les
    patterns ; le format et la normalisation, eux, sont gardés pour tous
    les exports.
  - **Dialogue** : `AudioExportDialog(unit="Song")` affiche « Fin : Song +
    résonance ». Rien ne change pour un pattern.
  - **Segments** : ils sont pris après les deux dialogues. Une annulation
    ne range donc pas le pattern courant.
  - **Compte rendu** : « Song 01 exporté en WAV : Song_01.wav (2
    patterns) — 6,00 s, song + résonance (aucune), 32 bits flottant ».
- **À essayer dans l'appli** : Alt+Shift+E et Alt+Shift+W dans la
  fenêtre Songs, à l'écoute et avec Orca.

### Phase 8 étape 2 — Avancement (2l1, 2m1)

- **2l1** (`6c9aca2`) : pistes séparées (E3, E4, E12-E14).
  - Dans `audio_export.py` : `Gain`, `compute_gain`, `mix_gain`,
    `limit_envelope`, `nonempty_tracks`, `is_silent`, `fit_length`,
    `stem_folder`, `stem_path`, et le paramètre `tracks` de
    `render_song`.
  - Dans l'interface : l'option Sortie de `AudioExportDialog`, et le
    rendu des stems dans le fil de `_start_audio_export`.
- **2m1** : 15 tests du moteur dans `test_audio_export.py`, 10 tests
  d'interface dans `test_audio_export_ui.py`, 1 test des stems d'un song
  dans `test_song_export_ui.py` (non prévu au plan). Les faux
  `write_wav` des tests acceptent désormais `gain`. 3156 tests verts.
- **Précisions par rapport au plan** :
  - **Sortie rangée à part** : `_audio_export_output`, hors du tuple
    `_audio_export_opts`, que dix tests vérifient à cinq valeurs.
  - **Pistes rendues** : celles qui ne sont pas vides dans le pattern, la
    sélection, le presse-papier ou au moins un pattern du song. Une piste
    muette ou hors solo donne un rendu silencieux, qui n'est pas écrit ;
    il n'y a pas de filtre d'audibilité à part.
  - **Longueur** : chaque stem est ramené à la longueur du mix (complété
    de silence ou coupé) avant de recevoir son gain. En boucle exacte,
    chaque stem atteint son propre régime établi ; la somme reste celle du
    mix.
  - **Banques dans un song** : la poursuite des banques à chaque frontière
    se fait sur la tape complète du pattern, même pour un stem.
  - **Mesuré** : la somme des stems relus égale le mix relu (flottant,
    normalisé et limité), à 1e-6 près.
  - **Avancement** : un seul pourcentage, sur le mix puis chaque piste.
- **À essayer dans l'appli** : la Sortie dans Alt+Shift+W, Alt+Shift+S et
  la fenêtre Songs, avec Orca.

### Phase 8 étape 2 — Avancement (2n1, 2o1)

- **2n1** (`a7060fd`) : choix Pistes dans `SelectionExportDialog`
  (`TRACKS_LABELS`, `get_tracks_idx`), gardé pour la session
  (`_audio_sel_tracks`) ; `_selection_job(window, all_tracks)` (E16).
- **2o1** : 10 tests dans `test_audio_export_ui.py`.
- **Précisions par rapport au plan** :
  - **Place de la liste** : juste après la Source, avant les limiteurs.
    L'ordre de tabulation est donc Source, Pistes, limiteur gauche,
    limiteur droit, puis les boutons. Entrée sur la liste Pistes valide,
    comme sur la liste Source.
  - **Activation** : la liste n'est active que pour la source Sélection.
    Avec le presse-papier, le choix n'est pas modifié.
  - **Toutes les pistes** : aucune restriction de pistes au rendu
    (`tracks=None`). Les pistes muettes ou hors solo restent silencieuses,
    comme à l'écoute ; en stems, leur rendu silencieux n'est pas écrit.

### Phase 8 étape 2 — Avancement (2o2, 2o3, imprévus)

- **Origine** : le point de forme laissé ouvert à la clôture 1j1 (le
  compte rendu d'Alt+Shift+S disait « pattern + résonance » pour une
  sélection). Corrigé dans ce chantier à la demande de l'utilisateur
  (2026-10-31).
- **2o2** (`5da4f7a`) : les travaux de la sélection et du presse-papier
  portent leur mot (`unit`). Il passe au compte rendu (« sélection +
  résonance », « presse-papier + résonance ») et au dialogue des
  paramètres (« Fin : Sélection + résonance », « Fin : Presse-papier +
  résonance »). Rien ne change pour un pattern.
- **2o3** : 5 tests dans `test_audio_export_ui.py`.

### Clôture (2p1)

**2a-2o3 FAITS** (commits `137b202` à `44e9480`, 17 commits, et ce commit
de clôture ; 3171 tests verts) : **chantier Phase 8 étape 2 complet**.
GroovyboxIt exporte un song en MIDI et en WAV, et n'importe quel export
audio en pistes séparées.

**Ce que le chantier a livré** :
- **Song figé** (`song.py`) : `frozen_pattern`, `SongSegment`,
  `song_segments` ; le pattern en cours d'édition est rangé avant chaque
  export (`_store_current_pattern`).
- **Export MIDI du song** (`midi_export.py`) : `build_song_midi` ;
  marqueurs, tempo et signature au changement, état des pistes par canal,
  notes qui débordent au tempo suivant. Le fichier d'un pattern est
  identique à l'octet (115 fichiers comparés par empreinte).
- **Rendu audio du song** (`audio_export.py`) : `render_song`, état de
  chaque pattern appliqué à sa frontière à l'échantillon près, deux fins.
  Les rendus de pattern sont identiques (43 rendus comparés).
- **Pistes séparées** : un rendu par piste, gain et enveloppe du limiteur
  du mix appliqués à chaque piste (`Gain`), sous-dossier ; la somme des
  stems redonne le mix.
- **Interface** :
  - fenêtre Songs : Alt+Shift+E et Alt+Shift+W ;
  - dialogue des paramètres : Sortie (mix, pistes séparées, les deux) ;
  - Alt+Shift+S : liste Pistes (sélectionnées ou toutes), ajout de
    l'utilisateur (E16) ;
  - mot juste au compte rendu et au dialogue : « Sélection »,
    « Presse-papier », « Song + résonance » (2o2, point de forme de 1j1).

**Décisions prises en cours de route** (voir les avancements) :
- E9 : état des pistes comparé par canal, événements de `_tape` compris ;
- piste en Banque d'un song nommée d'après son slot ;
- Sortie gardée à part du tuple des options ;
- stems silencieux omis plutôt qu'un filtre d'audibilité ;
- slot vide = sons du kit, au rendu comme à la lecture (constaté en 2i1).

**Défauts et pièges rencontrés** :
- `test_midi_export_ui.py` détruit la `wx.App` de session : un fichier
  qui passe après lui la recrée, gardée dans une variable du module (2k1).
  Le correctif de fond (`make_km` / `teardown`) n'est pas fait.

**`docs/SPECS.md` mis à jour** : ligne Phase 8, arborescence
(`audio_export.py`, `midi_export.py`, `song.py`), Export MIDI (song),
Export audio (Sortie, choix Pistes, song, stems, non exportés), Mode Song
(raccourcis, lecture), boîtes de dialogue, tests (`test_song_segments.py`,
`test_song_export_ui.py`, compléments de `test_midi_export.py`,
`test_audio_export.py`, `test_audio_export_ui.py`).

`docs/shortcuts.md` : Alt+Shift+W (sortie), Alt+Shift+S (liste Pistes),
fenêtre Songs (Alt+Shift+E, Alt+Shift+W). L'aide F1 le lit directement.

**À essayer dans l'appli par l'utilisateur** : Alt+Shift+E et Alt+Shift+W
dans la fenêtre Songs, la Sortie et la liste Pistes, à l'écoute et avec
Orca. Le comportement de Reaper et de Sonar cité au plan (gain commun des
stems) a été écrit de mémoire et reste à confirmer.

**Laissé hors périmètre, pour la suite** :
- niveau à l'écoute (point ouvert de 1j1) ;
- export du song depuis la fenêtre principale ou l'éditeur MIDI ;
  sélection temporelle dans un song ;
- mixeur à bus par piste (stems en un seul rendu), avec le moteur C/C++ ;
- autres fréquences, formats compressés, true peak ;
- Program Change avant G sur les pistes hors Banque ; dossier d'export
  retenu d'un lancement à l'autre (`config.json`).

### Phase 8 étape 2 — Après la clôture : pistes kit au canal 10 (2p2, 2p3)

- **Origine** : essai de l'utilisateur (2026-11-01). Alt+Shift+E et
  Alt+Shift+W de la fenêtre Songs sont concluants, mais dans le `.mid` du
  song, les patterns qui n'ont qu'un kit jouent la batterie sur un
  instrument de FluidSynth.
- **Cause** (constatée dans `Song_01.mid` et `essai_banque_17f1.gvp`) : un
  pattern créé sans réglage a toutes ses pistes sur le slot 0, ici le kit
  TR-707, mais aux canaux par défaut 1, 2, 3… La règle « kit → canal 10 »
  n'est posée que par `assign_slot_by_user`, quand l'utilisateur assigne
  un kit, et par la migration des anciens presets. La piste kit sortait
  donc sur un canal mélodique, avec le Program Change 25 du kit, qui n'y
  désigne pas un kit (guitare acoustique). L'export d'un tel pattern seul
  avait le même défaut. À l'écoute, rien ne s'entend : le sampler ignore
  le canal.
- **Décision (utilisateur, 2026-11-01)** : les deux remèdes.
  1. **Tout de suite** (2p2) : à l'export MIDI, pattern et song, une piste
     sur un slot Kit est toujours écrite au canal 10 (`_midi_params`).
     L'état du routeur et du pattern n'est pas touché.
  2. **Plus tard, chantier à part** : corriger les données, c'est-à-dire
     appliquer la règle « kit → 10 » dans les patterns eux-mêmes (création,
     chargement du projet, changement de pattern), avec le canal affiché
     par Alt+Entrée. Plan à écrire.
- **2p2** (`247f611`) : implémentation. Une assertion de
  `test_song_export_ui.py`, qui attendait les canaux tels quels, a été
  adaptée.
- **2p3** : 2 tests, l'export d'un pattern et celui d'un song.

### Phase 8 étape 2p4 — Essais de l'utilisateur (2026-11-01)

Essais concluants dans l'appli, à l'écoute et avec Orca :
- Alt+Shift+E et Alt+Shift+W dans la fenêtre Songs ;
- après 2p2, la batterie des patterns qui n'ont qu'un kit, dans le `.mid`
  du song ;
- l'orgue à la bonne hauteur dans le `.mid`, après réglage de la
  transposition GM du slot à +24 (réglage prévu en Phase 7 étape 12 pour
  le preset Drawbar Organ de FluidR3), enregistré dans le projet ;
- la Sortie du dialogue des paramètres audio (Mix, Pistes séparées, Mix +
  pistes) ;
- la liste Pistes d'Alt+Shift+S (Sélectionnées ou Toutes).

Tout ce que le chantier Phase 8 étape 2 avait laissé « à essayer » est
donc confirmé. Reste seulement, pour mémoire, le comportement de Reaper et
de Sonar sur le gain commun des stems, cité de mémoire au plan.

---

## Phase 8 étape 3a — Pistes kit au canal 10 dans les données des patterns

### Numérotation des commits de ce chantier

`3a` = ce plan (doc seule). Le code commence à `3b1`. Une paire impl →
tests ; `3a2`, `3b2`… pour un commit imprévu. Les décisions sont notées
**K1, K2…** (§ 3a).

### Origine du besoin

- Défaut trouvé à l'essai de l'export MIDI du song (2026-11-01, § 2p2) :
  un pattern créé sans réglage a ses pistes sur le kit du slot 0, mais aux
  canaux 1, 2, 3… Son `.mid` jouait la batterie sur un instrument
  mélodique.
- Décision de l'utilisateur (2026-11-01) : les deux remèdes. Le forçage à
  l'export est fait (2p2). Ce chantier corrige les données elles-mêmes, pour
  que le canal affiché par Alt+Entrée soit juste.

### État des lieux constaté en code (2026-11-01, 3173 tests verts)

- **Naissance des patterns** : les 99 patterns sont créés par `Pattern()`
  au démarrage (`main_window.py:148`), à Ctrl+N (`mw_project.py:80`) et
  réutilisés au chargement. Pistes sur le slot 0, canaux par défaut
  `Pattern.default_channel(t)` (piste N au canal N). `Pattern` ne connaît
  pas le Rack.
- **Où la règle « kit → 10 » est posée aujourd'hui** :
  - `TrackRouter.assign_slot_by_user` (`channel_after_slot`), quand
    l'utilisateur assigne un slot à une piste ;
  - `Pattern.apply_kit_channels`, migration des projets sans canaux
    (Phase 7 étape 10h7) : une seule fois, et seulement si la clé
    `track_channels` manque (`_needs_kit_channels`) ; appelée par
    `_load_project` (`mw_project.py:888`) ;
  - `ProjectMixin._midi_params`, à l'export MIDI (Phase 8 étape 2p2).
- **Démarrage** : `_load_project` sort aussitôt si le fichier du projet
  n'existe pas. Les patterns neufs ne passent alors par aucune règle.
- **Ctrl+N** (`_new_project`) : 99 patterns neufs, rien n'est appliqué.
- **Décision passée** : en Phase 7 étape 10h8, un canal enregistré est
  intact, même un kit « laissé sur le canal 2 »
  (`test_saved_channels_untouched`). Ce test met la piste 2 au canal 2,
  son canal par défaut.

### Décisions validées (utilisateur, 2026-11-01)

- **K1 — Défaut corrigé, choix respecté** : une piste sur un slot Kit
  **restée sur son canal par défaut** passe au canal 10. Un autre canal
  est tenu pour un choix de l'utilisateur et respecté. Limite acceptée :
  un canal choisi qui tombe sur le canal par défaut de la piste est
  corrigé lui aussi.
- **K2 — Moments** : au démarrage, à Ctrl+N et à Ctrl+O, pour les 99
  patterns, d'après le Rack du projet.
- **K3 — Forçage de l'export gardé** (2p2). Conséquence acceptée : une
  piste kit mise exprès sur un autre canal garde ce canal dans le projet
  et dans Alt+Entrée, mais sort toujours au canal 10 dans un `.mid`.

### Choix de conception proposés

- **K4 — Une règle dans `Pattern`** : `apply_kit_channels(is_kit_slot)`
  applique désormais K1 à chaque appel. Une piste sur un kit, au canal
  `default_channel(t)`, passe au canal 10. La méthode retourne les pistes
  changées. Le drapeau `_needs_kit_channels` devient inutile : un projet
  sans canaux a tous ses canaux par défaut, et la nouvelle règle donne le
  même résultat que l'ancienne migration. Il est retiré, avec la lecture
  qui le posait.
- **K5 — Un seul point d'appel** : `ProjectMixin._apply_kit_rule()`
  applique K4 aux 99 patterns d'après le Rack courant. Elle est appelée au
  démarrage (projet absent compris), à Ctrl+N et à Ctrl+O, avant que le
  pattern courant soit passé au routeur (`_apply_pattern_from_store`). Le
  routeur reçoit donc des canaux justes.
- **K6 — Ni Undo ni « modifié »** : c'est une mise en règle au chargement,
  comme la migration de 10h7. L'historique vient d'être vidé, et le projet
  n'est pas marqué modifié. Le fichier garde ses anciens canaux jusqu'au
  prochain enregistrement, mais la règle est réappliquée à chaque
  ouverture.
- **K7 — Compte rendu discret** : le message de Ctrl+O ajoute le nombre de
  pistes mises au canal 10, s'il y en a (« Projet chargé : x.gvp — 12
  pistes kit mises au canal 10 »). Rien au démarrage ni à Ctrl+N : les
  patterns neufs sont toujours concernés, et le message n'apprendrait
  rien.

### Portée exclue

Les autres moments proposés n'ont pas été retenus par l'utilisateur :
- un slot qui change de type (Alt+X charge un kit dans un slot utilisé,
  ou le remplace par un synthé) ;
- le changement de slot dans les propriétés de piste (Alt+Entrée), qui
  appelle `assign_slot` sans la règle du canal.

Un pattern dont le slot devient un kit en cours de session ne sera donc
corrigé qu'à la prochaine ouverture du projet. L'export MIDI, lui, le
force déjà (K3).

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **3a** | Doc — ce plan. | `docs/DESIGN.md` |
| **3b1** | Implémentation — `Pattern.apply_kit_channels` selon K1 (drapeau retiré), `_apply_kit_rule` au démarrage, à Ctrl+N et à Ctrl+O, compte rendu de Ctrl+O (K4-K7). | `src/pattern.py`, `ui/mw_project.py`, `ui/main_window.py` |
| **3c1** | Tests — 3b1 : règle (défaut corrigé, choix respecté, synthé et banque intacts, projet sans canaux), démarrage avec et sans fichier, Ctrl+N, Ctrl+O, routeur, ni Undo ni « modifié », compte rendu ; tests de 10h8 revus (le kit au canal 2 de la piste 2 passe au canal 10). | `tests/test_kit_channel_migration.py`, `docs/SPECS.md` |
| **3d1** | Doc — clôture (SPECS), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md` |

### Phase 8 étape 3 — Avancement (3b1, 3c1)

- **3b1** (`f71a6bb`) : `Pattern.apply_kit_channels` selon K1 (drapeau
  `_needs_kit_channels` retiré), `_apply_kit_rule` au démarrage, à Ctrl+N
  et à Ctrl+O, `_project_loaded_msg` (Ctrl+O et ouverture par
  l'explorateur). Quatre tests de 10h8 étaient rouges à ce commit, comme
  annoncé.
- **3c1** : `tests/test_kit_channel_migration.py` réécrit, 16 tests ;
  3182 tests verts.
  - Tests de 10h8 revus : le drapeau n'existe plus ; le kit de la piste 2
    « laissé sur le canal 2 » passe au canal 10 (limite de K1) ; un canal
    choisi, différent du canal par défaut, est gardé.
- **Précisions par rapport au plan** :
  - **Cache de l'Undo** : `_apply_kit_rule` ne marque pas le cache de
    `_capture_state` ; les trois appelants le marquent déjà en entier. Une
    première version le marquait avant sa recréation au chargement, ce qui
    a fait échouer deux tests (corrigé avant le commit 3b1).
  - **Démarrage sans projet** : le routeur reçoit les canaux corrigés du
    pattern courant par `set_track_channel`, piste par piste.
  - **Piste 10** : déjà au canal 10, elle n'est pas comptée.

### Clôture (3d1)

**3a-3c1 FAITS** (commits `9b4af05`, `f71a6bb`, `d072ec4`, et ce commit
de clôture ; 3182 tests verts) : **chantier Phase 8 étape 3 complet**.
Les patterns du projet ont leurs pistes kit au canal 10, et le canal
affiché par Alt+Entrée est juste.

**Ce que le chantier a livré** :
- **Règle** (`Pattern.apply_kit_channels`) : une piste sur un slot Kit
  restée sur son canal par défaut passe au canal 10 ; un canal choisi est
  gardé (K1). Elle remplace la migration des projets sans canaux de la
  Phase 7 étape 10h7 ; le drapeau `_needs_kit_channels` est retiré.
- **Moments** (`_apply_kit_rule`) : démarrage, projet absent compris, avec
  le routeur aligné ; Ctrl+N ; Ctrl+O, avant que le pattern courant passe
  au routeur (K2, K5). Ni Undo ni « modifié » (K6).
- **Compte rendu** de Ctrl+O et de l'ouverture par l'explorateur :
  « — N pistes kit mises au canal 10 » (K7).
- **Forçage du canal 10 à l'export MIDI gardé** (2p2, K3).

**Essai de l'utilisateur** (2026-11-01) : concluant.

**Laissé hors périmètre** (non retenu par l'utilisateur) :
- un slot qui change de type par Alt+X ;
- le changement de slot dans Alt+Entrée, qui appelle `assign_slot` sans
  la règle du canal.

Un pattern dont le slot devient un kit en cours de session n'est donc
corrigé qu'à la prochaine ouverture du projet ; l'export MIDI, lui, le
force déjà.

`docs/SPECS.md` a été mis à jour en 3c1 (règle dans la section Export
MIDI, table des tests) et en 3d1 (ligne Phase 8). Aucun raccourci n'a
changé.

### Phase 8 étape 1j3 — Point ouvert du niveau à l'écoute : clos (2026-11-01)

Le point ouvert de la clôture 1j1 (l'écoute sonnait plus fort que
l'export, autour de −6 LUFS-I contre −10,2 pour `Pat_01`) est clos par
l'utilisateur : avec la normalisation à un niveau visé (avenants 1h6 et
1h8), la différence entre le niveau d'écoute et celui de l'export est
très faible, et elle s'ajuste facilement. La mesure de l'écrêtage du
callback et un limiteur à l'écoute ne sont donc pas à faire.

---

## Phase 8 étape 4a — Export du song depuis la fenêtre principale et l'éditeur MIDI

### Numérotation des commits de ce chantier

`4a` = ce plan (doc seule). Le code commence à `4b1`. Une paire impl →
tests ; `4a2`, `4b2`… pour un commit imprévu. Décisions notées **X1,
X2…** (§ 4a).

### Origine du besoin

- Laissé hors périmètre en Phase 8 étape 2 : le song ne s'exporte que
  depuis la fenêtre Songs (Alt+5).
- Demande de l'utilisateur (2026-11-01) : pouvoir l'exporter aussi depuis
  la fenêtre principale, **sans nouveau raccourci** : Alt+Shift+E et
  Alt+Shift+W proposent un choix entre le pattern courant et le song
  courant.

### État des lieux constaté en code (2026-11-01, 3182 tests verts)

- **Raccourcis** : Alt+Shift+E et Alt+Shift+W appellent `_export_midi()` et
  `_export_audio()`, dans la fenêtre principale (`key_handler_alt.py:83`,
  `:86`) et dans l'éditeur MIDI (`mew_keymap.py:350`, `:356`, avec la
  fenêtre et le statut de l'éditeur).
- **Exports du song** : `_export_song_midi(song_idx, parent, status)` et
  `_export_song_audio(song_idx, parent, status)` (`mw_project.py`) ; ce
  dernier vérifie lui-même « export déjà en cours » et met la lecture en
  pause (`_audio_export_ready`). Un song vide est refusé.
- **Song courant** : `MainWindow._cur_song_idx`, connu même fenêtre Songs
  fermée.
- **Tests** : `_export_midi` et `_export_audio` sont appelés directement 39
  fois (`test_midi_export_ui.py`, `test_audio_export_ui.py`).

### Décisions validées (utilisateur, 2026-11-01)

- **X1 — Un choix, pas de nouveau raccourci** : Alt+Shift+E et
  Alt+Shift+W ouvrent d'abord un choix « Pattern courant » ou « Song
  courant ».
- **X2 — Fenêtre principale et éditeur MIDI** ; la fenêtre Songs garde ses
  raccourcis directs, sans ce choix.
- **X3 — Dernier choix de la session** sélectionné à l'ouverture ;
  « Pattern courant » au premier export.

### Choix de conception proposés

- **X4 — `ExportTargetDialog`** (`dialogs_simple.py`) : une liste de deux
  lignes, au libellé complet pour le lecteur d'écran : « Exporter : Pattern
  courant (Pat_02 Intro) » et « Exporter : Song courant (Song_01 Mon song,
  3 patterns) ». Entrée sur la liste valide (GTK : EVT_LISTBOX_DCLICK),
  Ok, Annuler. Titre « Exporter en MIDI » ou « Exporter en WAV ».
- **X5 — Nouveaux points d'entrée** : `_export_midi_choose(parent, status)`
  et `_export_audio_choose(parent, status)`, appelés par les raccourcis.
  Ils ouvrent le choix, puis appellent l'export du pattern
  (`_export_midi`, `_export_audio`, inchangés) ou du song
  (`_export_song_midi`, `_export_song_audio`). Les 39 appels des tests
  restent valables.
- **X6 — Un seul choix gardé pour MIDI et WAV** (`_export_target`) :
  exporter le song en MIDI puis en WAV ne demande qu'une fois de descendre
  sur « Song courant ».
- **X7 — Ordre** : pour le WAV, « export déjà en cours » est vérifié avant
  le choix ; on ne pose pas une question pour refuser ensuite. Annuler le
  choix annonce « Export MIDI annulé » ou « Export audio annulé », sans
  changer le choix gardé.
- **X8 — Song vide** : la ligne « Song courant » reste proposée (« Song
  courant (Song_02, vide) ») ; la choisir donne le refus habituel « Song
  vide — ajoutez des patterns dans la fenêtre Songs ».

### Portée exclue

- Alt+Shift+S (sélection, presse-papier) : il a déjà son propre choix de
  source et ne concerne pas le song.
- Choisir un autre song que le song courant.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **4a** | Doc — ce plan. | `docs/DESIGN.md` |
| **4b1** | Implémentation — `ExportTargetDialog`, `_export_midi_choose`, `_export_audio_choose`, choix gardé, raccourcis de la fenêtre principale et de l'éditeur MIDI (X1-X8). Essayé avec Orca. | `ui/dialogs_simple.py`, `ui/dialogs.py`, `ui/mw_project.py`, `ui/key_handler_alt.py`, `ui/mew_keymap.py` |
| **4c1** | Tests — 4b1 (dialogue, choix pattern ou song, MIDI et WAV, choix gardé et partagé, annulation, déjà en cours, song vide, raccourcis des deux fenêtres, fenêtre Songs inchangée). | `tests/test_song_export_ui.py`, tests des raccourcis, `docs/SPECS.md` |
| **4d1** | Doc — clôture (SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 4 — Avancement (4b1, 4c1)

- **4b1** (`f385806`) : `ExportTargetDialog`, `_export_midi_choose`,
  `_export_audio_choose`, `_export_target_labels`, choix gardé
  `_export_target` ; raccourcis de la fenêtre principale et de l'éditeur
  MIDI. Quatre tests des raccourcis étaient rouges à ce commit, comme
  annoncé.
- **4c1** : les quatre tests des raccourcis visent les nouveaux points
  d'entrée ; 12 tests du choix dans `test_song_export_ui.py` ; 3194 tests
  verts.
- **Précisions par rapport au plan** :
  - **Libellés** : « Pat_02 Intro » pour le pattern ; « Song_01 Mon song,
    3 patterns », « 1 pattern » ou « vide » pour le song.
  - **Pour le WAV**, l'export en cours est refusé avant la question ; la
    pause de la lecture vient ensuite, dans l'export choisi.
  - **Essai de l'utilisateur avec Orca** : concluant (2026-11-01).

### Clôture (4d1)

**4a-4c1 FAITS** (commits `6ed4cae`, `f385806`, `49fa001`, et ce commit
de clôture ; 3194 tests verts) : **chantier Phase 8 étape 4 complet**. Le
song courant s'exporte en MIDI et en WAV depuis la fenêtre principale et
l'éditeur MIDI, sans nouveau raccourci.

**Ce que le chantier a livré** :
- `ExportTargetDialog` : « Pattern courant » ou « Song courant », libellés
  complets, Entrée valide ;
- `_export_midi_choose`, `_export_audio_choose` : les raccourcis
  Alt+Shift+E et Alt+Shift+W des deux fenêtres y passent, puis appellent
  l'export existant du pattern ou du song ;
- dernier choix gardé pour la session, commun au MIDI et au WAV ; export
  audio en cours refusé avant la question ; song vide proposé puis refusé.

**Essai de l'utilisateur avec Orca** : concluant (2026-11-01).

**`docs/SPECS.md`** : ligne Phase 8, Export MIDI (choix « Pattern courant
/ Song courant »), Export d'un song, Export audio (introduction, parcours),
boîtes de dialogue (`ExportTargetDialog`), tests (4c1).
**`docs/shortcuts.md`** : Alt+Shift+E et Alt+Shift+W dans la fenêtre
principale et l'éditeur MIDI ; « sans choix » dans la fenêtre Songs.

**Laissé hors périmètre** : Alt+Shift+S (son propre choix de source), et
l'export d'un autre song que le song courant.

## Phase 8 étape 5a — Mode Rack 16 canaux : le canal N joue le slot N

### Numérotation des commits de ce chantier

`5a` = ce plan (doc seule). Le code commence à `5b1`. Une paire impl →
tests par sous-chantier ; `5a2`, `5b2`… pour un commit imprévu. Décisions
notées **M1, M2…** (§ 5a).

### Origine du besoin

- But formulé le 2026-09-21 : un **mode Synth/GM du Rack** pour jouer des
  fichiers MIDI sur **16 canaux**, chaque canal avec le patch qui lui est
  associé (**16 slots du Rack ↔ 16 canaux**). C'est pour lui que le format
  garde le canal de chaque événement et qu'un Program Change peut tomber à
  tout moment.
- Choisi le 2026-11-01, de préférence aux 128 pads : il apporte un vrai
  atout sonore (un `.mid` joué par **vos propres sons** WAV, kits et
  banques, pas seulement par la soundfont GM), et il avance le code des 128
  pads (notes de kit par numéro, kits par slot).
- Il remplace, dans ce mode, le **pont provisoire** du Program Change
  (`assign_slot(program % 16)`), explicitement temporaire depuis la Phase 7
  étape 4a.
- Comportement de référence : **Sonar**.

### État des lieux constaté en code (2026-11-01, 3194 tests verts)

- **Une piste joue son propre slot** (`TrackRouter._track_slots`, copié du
  pattern). Le routeur le lit à 5 endroits : `_bank_slot_of`
  (`track_router.py:389`), `on_play` (`:827`), `on_patch_tape` (`:868`),
  `on_bend_tape` (`:890`), `on_mod_tape` (`:909`) ; plus `slot_for_track` et
  `slot_name` (`:259-263`).
- **Le canal ne compte que sur un slot Banque** (modèle « orchestre »,
  Phase 7 étape 17e3) : instrument des 16 canaux (`_chan_prog`, `_chan_msb`,
  `_chan_lsb`) ; canal courant d'une piste = celui de son dernier Program
  Change (`_track_cur_channels`, `track_channel_now`, `:402`) ; poursuite
  (`chase`, `:554`) limitée aux pistes Banque. Ailleurs, le canal ne sert
  qu'à l'export.
- **Program Change hors banque** : `program_change` (`:625`) réassigne le
  slot de la piste à `program % 16` (pont provisoire), en direct
  (`midi_handler_window.py:269`) comme au rejeu
  (`on_program_change_tape`, `:966`).
- **Notes** : une case de grille joue selon le type du slot (kit : pad ;
  synthé : gamme ; banque : 36 + pad au canal 10, sinon gamme) ; une note
  PATCH ne sonne que sur un synthé ou une banque (`on_patch_tape`, `:874`),
  **elle est muette sur un kit** ; une note KIT passe par
  `SoundManager.note_map` (`on_kit_tape`, `:850`).
- **Un seul kit sonne à la fois** : un seul `SoundManager`, chargé par
  `_load_kit_slot` (`mw_pads.py:120`) quand l'utilisateur choisit un slot kit.
  Ce chargement **renomme les pads**, donc les pistes (noms mêlés, I5 de
  Phase 7 étape 18).
- **Entrée MIDI** : tout va à la piste courante et au slot courant
  (`win._cur_slot`), quel que soit le canal du contrôleur ;
  l'enregistrement remet Program Change, CC0 et CC32 au canal courant de la
  piste (O7). `_cur_slot` suit le slot de la piste au changement de piste
  (`mw_tracks.py:295`).
- **Import MIDI** (`_import_midi`, `mw_project.py:735`) : toutes les pistes
  sur le premier slot Banque (créé au besoin, `_import_bank_slot`, `:714`).
  Les notes de batterie arrivent en PATCH au canal 10.
- **Propriétés du pattern** (Alt+Entrée sur la liste des patterns,
  `PatternPropertiesDialog`, `dialogs_properties.py:274`) : nom, début,
  longueur, tempo, signature, résolution, boucle ; Undo posé à Ok.
- **Ctrl+T** assigne le slot courant à la piste (`assign_slot_by_user`,
  `:747` : un kit met la piste au canal 10).
- **Export MIDI** : programme de tête, transposition et gain GM pris au slot
  de chaque piste (`track_programs`, `track_transposes`, `track_gain_db`) ;
  `track_is_bank` fait suivre aux événements le canal du Program Change.

### Décisions validées (utilisateur, 2026-11-01)

**M1 — Le canal N joue le slot N.** Dans un pattern en mode Rack, toute
piste joue le slot dont le numéro est son **canal courant** (canal 1 → slot
1 … canal 16 → slot 16), quel que soit son propre slot : synthé WAV, kit ou
banque. Vrai à la lecture, à l'export audio et au jeu direct (M4).

**M2 — Un réglage par pattern.** Case « Mode Rack 16 canaux (canal N →
slot N) » dans les propriétés du pattern. Sauvée dans le `.gvp` avec le
pattern ; absente = mode normal. Un song peut mêler des patterns des deux
modes ; le routeur change de mode avec le pattern (chargement, avance du
song).

**M3 — Program Change sur un slot synthé WAV ou kit : ignoré pour le
son.** Le slot N reste le son du canal N. Le Program Change reste un
événement de la piste, visible, modifiable, exporté ; il porte toujours le
canal (O3) : il fait changer la piste de canal, donc de slot. Sur un slot
Banque, il choisit l'instrument GM du canal, comme aujourd'hui. **Le pont
`program % 16` n'existe pas en mode Rack** ; il reste en mode normal.

**M4 — Entrée MIDI comme Sonar : la piste courante.** Le contrôleur joue
la piste courante avec le son de son canal courant N, donc le slot N ;
l'enregistrement va sur cette piste, à son canal (O7 inchangé). Changer de
piste change le son du clavier. Le canal émis par le contrôleur ne choisit
pas le son.

**M5 — Slot vide : repli sur la banque GM.** Un canal dont le slot est
vide joue le **premier slot Banque du Rack**, avec l'instrument GM du canal
(Program Change, CC0, CC32). Sans slot Banque, le canal est muet, et un
message le dit au chargement du pattern. Un `.mid` importé sonne donc en
entier même avec quelques slots seulement remplis, et à l'identique du mode
normal avec un Rack vide.

**M6 — Un seul kit à la fois, avec avertissement.** Au chargement d'un
pattern en mode Rack, le kit joué est celui du slot 10 si c'est un kit,
sinon celui du premier canal joué dont le slot est un kit. Un autre slot kit
joué par un autre canal est signalé dans la barre d'état ; il entend le kit
chargé. Plusieurs kits ensemble : chantier 128 pads / AudioSampler.

**M7 — Ctrl+T met la piste au canal S.** En mode Rack, canal et slot ne
font qu'un : assigner le slot S à la piste, c'est la passer au canal S,
comme le ferait Alt+Entrée (entête réécrit s'il existe, O3). Undo comme
aujourd'hui.

**M8 — Import : un choix.** Alt+Shift+I demande « Banque GM » (comme
aujourd'hui) ou « Rack 16 canaux » (le pattern importé passe en mode
Rack).

### Choix de conception proposés

- **M9 — Slot effectif.** Le routeur lit le slot d'une piste par une seule
  méthode, `_slot_idx_of(t)` : en mode normal `_track_slots[t]` ; en mode
  Rack le slot du canal courant, ou le slot de repli (M5). Les 5 lectures
  de `_track_slots` y passent ; `slot_for_track` et `slot_name` aussi.
  `_track_slots` du pattern n'est pas modifié par le mode : décocher la
  case rend à chaque piste son propre slot.
- **M10 — Canal courant pour toutes les pistes en mode Rack.**
  `_track_cur_channels` et la poursuite (`chase`) couvrent toutes les pistes
  du pattern, pas seulement celles d'une banque : le canal d'une piste est
  celui de son dernier Program Change, quel que soit le slot. L'instrument
  GM d'un canal n'est envoyé au moteur que si son slot effectif est une
  banque.
- **M11 — Note PATCH sur un kit** (nouveau, utile aux `.mid` importés : la
  batterie arrive en PATCH) : jouée par `note_map` du kit chargé, après
  conversion GM → note du kit (inverse de `gm_note_map`, Phase 7 étape 11),
  sinon telle quelle ; durée ignorée (one-shot). Vrai aussi en mode normal
  (une note PATCH muette sur un kit n'avait pas de raison d'être).
- **M12 — Kit chargé sans renommer les pads.** En mode Rack, le kit de M6
  est chargé pour ses sons seulement : les noms de pads tiennent les noms de
  pistes importés (I5). À vérifier à l'essai.
- **M13 — `Pattern._rack_mode`** (bool, `"rack_mode"` dans `to_dict`,
  absent = False) ; le routeur le reçoit au chargement du pattern
  (`TrackRouter.rack_mode`), comme les canaux ; `render_copy` le copie
  (export WAV).
- **M14 — Libellé de piste** : en mode Rack, « Canal 3 → Slot_03 Piano »
  (banque : nom du preset du canal, comme aujourd'hui ; repli : « Canal 3 →
  banque GM, Acoustic Grand Piano »).
- **M15 — Propriétés de piste (Alt+Entrée) en mode Rack** : la liste des
  canaux dit le slot de chaque canal (« Canal 3 — Slot_03 Piano ») ;
  programme et banque ne sont actifs que si le canal choisi joue une banque
  (repli compris). La note d'aperçu joue le slot du canal choisi.
- **M16 — Jeu direct** : au changement de piste et quand un Program Change
  la fait changer de canal, `_cur_slot` et la préécoute (`load_slot_preview`)
  suivent le slot effectif ; la liste des slots le montre.
- **M17 — Import en mode Rack** : mêmes pistes et même slot Banque
  qu'aujourd'hui (I3 : `_track_slots` = la banque, si bien que décocher le
  mode rend le son GM), plus `_rack_mode = True`. Dialogue à deux lignes
  comme `ExportTargetDialog` (Entrée valide), dernier choix gardé pour la
  session.
- **M18 — Export MIDI en mode Rack** : chaque piste est traitée comme une
  piste Banque (canal qui suit le Program Change, événements de `_tape`) ;
  les réglages GM (programme de tête s'il n'y a pas d'entête, transposition,
  gain, conversion des notes de kit) sont pris au **slot effectif** de la
  piste. Export WAV : le rendu suit M1 par `render_copy`.

### Alternatives écartées

- Entrée MIDI multitimbrale (canal du contrôleur → slot) : contraire à M4,
  qui suit Sonar ;
- mode global au projet, ou par piste (pseudo-slot « selon le canal ») ;
- Program Change qui choisit un autre patch WAV ou un autre kit ;
- slot vide muet ; plusieurs kits ensemble dès ce chantier ;
- Ctrl+T refusé en mode Rack.

### Portée exclue

- plusieurs kits joués ensemble, 128 pads ;
- suppression du pont `program % 16` en mode normal ;
- filtre de canal d'entrée par piste ;
- notes en temps flottant, SFZ, réverbération et chorus.

### Points à vérifier à l'essai

- rechargement du kit à l'avance d'un song entre deux patterns Rack aux
  kits différents (latence en pleine lecture) ;
- noms de pads d'un pattern Rack quand son kit est chargé (M12) ;
- un `.mid` importé en mode Rack avec quelques slots WAV et le reste en
  repli GM.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **5a** | Doc — ce plan. | `docs/DESIGN.md` |
| **5b1** | Implémentation — moteur : `Pattern._rack_mode` (M13), slot effectif et repli (M1, M5, M9), canal courant et poursuite de toutes les pistes (M10), Program Change sans pont (M3), PATCH sur un kit (M11), kit du pattern et avertissement (M6, M12), `render_copy`. | `src/pattern.py`, `src/track_router.py`, `src/player/dp_playback.py`, `ui/mw_patterns.py`, `ui/mw_songs.py`, `ui/mw_pads.py` |
| **5c1** | Tests — 5b1 (lecture par canal, repli, Program Change, poursuite, PATCH sur kit, kit unique, `.gvp`, mode normal inchangé). | `tests/test_rack_mode.py` (nouveau), `docs/SPECS.md` |
| **5d1** | Implémentation — UI : case des propriétés du pattern et Undo (M2), libellé (M14), Ctrl+T (M7), jeu direct (M4, M16), propriétés de piste (M15). Essayé à l'écoute avec Orca. | `ui/dialogs_properties.py`, `ui/mw_patterns.py`, `ui/mw_tracks.py`, `ui/midi_handler_window.py` |
| **5e1** | Tests — 5d1. | `tests/test_rack_mode_ui.py` (nouveau), tests des raccourcis, `docs/SPECS.md` |
| **5f1** | Implémentation — import (M8, M17) et export MIDI / WAV (M18). Essayé sur de vrais `.mid`. | `ui/mw_project.py`, `ui/dialogs_simple.py`, `src/midi/midi_export.py` |
| **5g1** | Tests — 5f1 (choix à l'import, aller-retour, export par slot effectif, rendu WAV). | `tests/test_midi_import_ui.py`, `tests/test_midi_export.py`, `tests/test_audio_export_ui.py` |
| **5h1** | Doc — clôture (SPECS, raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 5 — Avancement (5b1)

- **5b1** — moteur, conforme à M1, M3, M5, M6, M9-M13 :
  - `Pattern._rack_mode` (`"rack_mode"` du `.gvp`, absent = False ;
    copié par `copy_from`, donc par l'Undo et le song figé) ;
    `TrackRouter.rack_mode`, posé avec les canaux au changement de
    pattern, à l'avance du song et dans l'export WAV ; `render_copy` le
    copie.
  - Slot effectif `_slot_idx_of` / `_eff_slot` (M9), lu par
    `_bank_slot_of`, `on_play`, `on_kit_tape`, `on_patch_tape`,
    `on_bend_tape`, `on_mod_tape`, `slot_for_track`, `slot_name` ;
    `rack_slot_idx(canal)` et `fallback_bank_idx()` (M5).
  - Mode Rack : `track_channel_now` et `chase` couvrent toutes les
    pistes (M10) ; `_rack_program_change` sans pont (M3) ; moteurs des
    slots synthé des canaux joués chargés à la poursuite et au changement
    de canal (`ensure_rack_synths`, `rack_channels_of` : canal des pistes
    non vides et de leurs Program Change) ; une note KIT sur un slot synthé
    y est jouée comme une note PATCH ; un slot vide sans repli est muet.
  - Note PATCH sur un kit (M11, les deux modes) :
    `SoundManager.kit_note_of_gm`, inverse de `gm_note_map`.
  - Kit du pattern (M6, M12) : `rack_report(tape)` (kit à charger, autres
    kits, canaux muets) et `_apply_rack_kit` (`mw_pads.py`), qui charge le
    kit sans renommer les pads (`SoundManager.kit_path` évite de recharger
    le même) et avertit dans la barre d'état. `_load_project` ne charge
    plus les kits des slots des pistes d'un pattern Rack, et recharge les
    moteurs des canaux après `clear_slot_synths`.
  - **Précision** : `_load_project` met `_cur_slot` au slot effectif de la
    piste courante (`slot_for_track`), comme le changement de piste.
  - **Reste pour 5d1** : en mode Rack, le message d'un Program Change reçu
    du contrôleur dit encore « → Slot N » (pont) ; le canal émis par le
    contrôleur est déjà ignoré (M4).
  - `pytest` : 3194 verts (mode normal inchangé) ; essai du routeur par
    un script (fakes de `test_bank_slot.py`), avant les tests de 5c1.
- **5b2** — correctif trouvé par les tests de 5c1 : le message des canaux
  muets de `_apply_rack_kit` disait « canalaux » au pluriel ; « canal » /
  « canaux ».
- **5c1** — `tests/test_rack_mode.py` (62 tests) : `_rack_mode` du
  pattern (`.gvp`, clé absente ou non booléenne, `copy_from`, song figé),
  slot effectif et repli, lecture par canal, PATCH sur un kit (deux
  modes), Program Change sans pont et pont gardé en mode normal,
  poursuite, moteurs des canaux, `render_copy`, `rack_report`,
  `kit_note_of_gm` / `kit_path`, `_apply_rack_kit`, mode posé au
  changement de pattern, à l'avance du song et à l'export WAV ;
  `SPECS.md` (arborescence, table). 3256 verts.
- **5d1** — interface, conforme à M2, M4, M7, M12, M14-M16 :
  - **Propriétés du pattern** : case « Mode Rack 16 canaux (canal N →
    slot N) », après Boucler (`get_rack_mode`) ; `_set_rack_mode`
    (`mw_patterns.py`) l'applique après l'Undo de l'action : store et
    pattern joué, routeur, poursuite, kit du pattern, slot courant,
    libellés. Si seul le mode change, l'Undo s'appelle « Mode Rack pattern
    03 : activé / désactivé ».
  - **Libellé** (M14) : « Track_01 (Basse) - Canal 4 → Slot_04 Piano
    WAV », « … → Slot_04 vide → banque GM (Slot_06 FluidR3) - Fingered
    Bass » ou « … → Slot_04 vide, muet » (`_rack_channel_desc`).
  - **Ctrl+T** (M7) : `_assign_rack_channel` passe la piste au canal du
    slot choisi, réécrit son entête sur ce canal (programme et banque
    gardés), poursuit. **Précision** : un Undo « Piste 2 → canal 3 » est
    posé, car l'entête change ; Ctrl+T n'en pose pas en mode normal.
  - **Jeu direct** (M4, M16) : `_follow_track_slot` (slot courant,
    préécoute ou kit, libellés) au changement de pattern, aux propriétés
    de piste, à Ctrl+T et quand un Program Change reçu change le canal ;
    message du Program Change reçu en mode Rack : « Piste 1: Program
    Change 33 — canal 2, Slot_02 Piano WAV (programme sans effet sur ce
    slot) », ou le nom du preset sur une banque.
  - **Kit sans renommer les pads** (M12) : `_load_kit_slot(rename=None)`,
    sans renommage en mode Rack, partout où un kit se charge (changement
    de piste, liste des slots).
  - **Propriétés de piste** (M15) : `TrackPropertiesDialog(rack_slot_of,
    channel_labels)` ; le slot choisi est le canal (choisir l'un choisit
    l'autre) ; programmes, banque et réglages GM sont ceux du slot que
    joue le canal ; `_track_slots` n'est pas touché ; libellés « Canal 3 —
    Slot_03 Piano WAV ».
  - **Changement de pattern** : « Pattern 03 — mode Rack 16 canaux »,
    puis les avertissements du kit.
  - `pytest` : **20 tests rouges jusqu'à 5e1**, tous dus aux fakes
    (routeurs sans `rack_mode` dans `test_midi_handler_window.py`,
    `FakeDlg` sans `get_rack_mode` dans `test_signature_ui.py` et
    `test_step_duration.py`). Dialogues vérifiés par un script.
- **5e1** — `tests/test_rack_mode_ui.py` (36 tests) sur une fenêtre
  factice (pistes, patterns, pads) et un vrai `TrackRouter` : case des
  propriétés du pattern et Undo, `_set_rack_mode`, libellés, Ctrl+T, slot
  courant qui suit la piste, kit sans renommer les pads, Program Change
  reçu, propriétés de piste (vrai dialogue et fenêtre), changement de
  pattern ; fakes des 20 tests rouges de 5d1 adaptés (`rack_mode` du
  routeur factice, `get_rack_mode` des `FakeDlg`) ; `SPECS.md`. 3292 verts.
  Essai de 5d1 avec Orca : pas encore fait.
- **5f1** — import et export, conforme à M8, M17, M18 :
  - **Import** : `ImportModeDialog` (`dialogs_simple.py`), « Importer :
    Banque GM (toutes les pistes sur le slot Banque) » ou « Importer : Rack
    16 canaux (le canal N joue le slot N) », titre « Importer song.mid »,
    Entrée valide ; posé après la lecture du fichier, avant la
    confirmation ; Annuler = « Import MIDI annulé » ; dernier choix gardé
    pour la session (`_import_mode`). En mode Rack : pistes sur le slot
    Banque comme aujourd'hui, `_rack_mode = True`, slot courant = slot
    effectif, compte rendu « ; mode Rack 16 canaux » suivi des
    avertissements du kit (`_rack_kit_messages`, extrait de
    `_apply_rack_kit`).
  - **Précision : Rack plein sans slot Banque.** Toujours refusé en Banque
    GM ; accepté en mode Rack (chaque canal a son slot), sans slot Banque :
    les pistes gardent leur slot.
  - **Export MIDI** : `build_pattern_midi(rack_mode, track_is_kit)` ; en
    mode Rack, le canal de chaque piste suit ses Program Change quel que
    soit son slot, Program Change / CC0 / CC32 sur leur propre canal ;
    `_midi_params` décrit chaque piste par le slot que joue son canal à
    1.1.1 (`_rack_slot_at_start` : canal de l'entête, sinon de la piste) et
    garde son canal, kit compris (pas de « kit → 10 » en mode Rack).
    Pattern courant et song.
  - **Précision : notes PATCH sur un kit exportées** dans les deux modes,
    telles quelles (notes GM), puisqu'elles sonnent depuis M11.
  - **Limite** : une piste qui change de slot en cours de morceau (Program
    Change vers un canal d'un autre type) garde les réglages GM de son slot
    de départ (programme de tête, transposition, gain, conversion du kit).
  - **Export WAV** : rien à ajouter ; le rendu suit le routeur
    (`render_copy`, `_PatternState.apply`, 5b1).
  - `pytest` : **15 tests rouges jusqu'à 5g1** dans
    `test_midi_import_ui.py` (le vrai `ImportModeDialog` refuse leur
    fenêtre factice comme parent). Dialogue et export vérifiés par un
    script.
- **5f2** — correctif trouvé par les tests de 5g1 : l'import demandait
  les avertissements du kit (`_rack_kit_messages`) même en Banque GM ; ils
  ne sont demandés qu'en mode Rack.
- **5g1** — tests de 5f1 : 15 tests de `test_midi_import_ui.py`
  adaptés (faux `ImportModeDialog` dans `_run`) ; 11 tests de l'import
  et des réglages d'export (vrai `ImportModeDialog`, choix proposé avec le
  nom du fichier et le dernier choix, Annuler, mode Rack ou Banque GM,
  slot courant du canal, Rack plein accepté en mode Rack, avertissements
  du kit au compte rendu, `_midi_params` d'un pattern ou d'un song Rack) ;
  6 tests de `test_midi_export.py` (canal qui suit les Program Change,
  case de grille d'un kit, notes PATCH d'un kit, fichier identique sans le
  mode) ; 3 tests du rendu WAV dans `test_audio_export.py` (slot du canal,
  synthé chargé au passage à blanc, écoute intacte, song) ; `SPECS.md`.
  3312 verts. Essais avec Orca (5d1) et sur de vrais `.mid` (5f1) : pas
  encore faits.
- **Essai de l'utilisateur (2026-11-02)** — trois remarques :
  1. propriétés de piste : changer de slot passe la piste au canal 10,
     mais le curseur de la liste des canaux reste sur le canal 1 (Haut ne
     remonte pas depuis le canal 10) → 5d2 ;
  2. confusion de noms entre le slot 5, kit « GM (FluidR3) », et le slot
     6, banque « FluidR3_GM » créée par l'import : le kit doit s'appeler
     « Kit GM » (données de l'utilisateur, pas du code) ;
  3. Program Change du contrôleur : pas facile à envoyer depuis le
     contrôleur, à tester par le code → 5e2.
- **5d2** — correctif de l'essai : `ui/gtk_listbox.py`,
  `select_with_cursor(listbox, idx)`. Sous wxGTK 3.2, `SetSelection`
  sélectionne sans placer le curseur du GtkTreeView ;
  `gtk_tree_view_set_cursor` (ctypes, `GetGtkWidget()` → enfant
  GtkTreeView du GtkScrolledWindow) le place, sans prendre le focus ni
  émettre d'événement wx. Toutes les sélections faites par le code dans
  `TrackPropertiesDialog` (slots, canaux, programmes) y passent, dans les
  deux modes. Hors GTK : `SetSelection` seul. Vérifié par un script
  (curseur au canal 10, focus resté sur la liste des slots, un seul
  aperçu).
- **5e2** — tests de 5d2 et remarque 3 de l'essai, dans
  `tests/test_rack_mode_ui.py` (47 tests) :
  - curseur clavier : défaut de `SetSelection` sous GTK constaté,
    `select_with_cursor` sans événement wx, hors limites et hors GTK ;
    propriétés de piste : curseur au canal 10 après un slot kit (le cas de
    l'essai), mode Rack dans les deux sens, programme du canal ;
  - **Program Change du contrôleur de bout en bout** : octets MIDI bruts
    → `MidiManager._callback` → `MidiHandler` (sans `CallAfter`) →
    routeur et moteur de banque : instrument du canal de la piste (le
    canal émis par le contrôleur est ignoré, M4), Bank Select puis
    programme, synthé sans pont, enregistrement au canal de la piste par
    le vrai `record_program_change`, pont et banque en mode normal.
  - **Précision des tests** : pas de `wx.Yield()` dans un test de liste ;
    en pleine suite, il traitait des événements laissés par d'autres
    fichiers et faisait planter Python à la sortie (assertion
    `PyTuple_Check`). Le signal GTK est de toute façon synchrone.
  - 3323 verts.
- **Remarque 2 de l'essai, faite dans les données de l'utilisateur
  (2026-11-03, pas de code)** : le kit « GM (FluidR3) » est renommé
  « Kit GM » dans `KITS/gm.json` (champ `"name"`) et comme nom du slot 5
  des cinq projets de `PROJECTS/` (project_01 à 03, essai_banque_17d1,
  essai_banque_17f1), chaque fichier copié d'abord en `.bak`. L'appli n'a
  pas de commande pour renommer un slot (hors périmètre).
- **Essai de l'utilisateur (2026-11-03), remarque 4** : après l'ouverture
  d'un projet, le simple passage du curseur sur le Slot_05 (un kit) dans
  la liste des slots chargeait ce kit à la place du TR-707, donc changeait
  la batterie du pattern. Il faut pouvoir parcourir les slots sans les
  charger → 5d3.
- **5d3** — correctif : `_cur_slot` garde un seul rôle, le **slot joué**
  (celui de la piste courante, lu par l'entrée MIDI, les pads, le clavier
  virtuel et l'éditeur MIDI) ; le **slot listé** (`_listed_slot()`, la
  sélection de la liste) est la cible de Ctrl+T, d'Entrée et de
  l'Explorateur (Alt+X).
  - Parcourir la liste (`_on_slot_choice`) n'affiche que le nom du slot :
    plus de chargement de kit ni de préécoute.
  - Ctrl+T / Entrée : assignation, puis `_follow_track_slot` (le slot
    assigné devient le slot joué, chargé à ce moment).
  - Explorateur : kit, patch ou banque chargé dans le slot listé ; la
    liste reste sur lui (`_update_slot_list(listed)`) ; ses sons ne sont
    chargés (kit, préécoute) que si c'est le slot joué ; un patch recharge
    toujours les pistes de ce slot, le clavier garde son son.
  - Sélections de la liste des slots faites par le code (changement de
    piste, slot suivi) : curseur clavier placé aussi (`select_with_cursor`,
    tolérant aux listes factices des tests).
  - `pytest` : **12 tests rouges jusqu'à 5e4**, dus aux fenêtres
    factices (`_PadWindow`, `FakeWindow` sans `_listed_slot` ;
    `_FakeTrackWindow` sans `_load_kit_slot`).
- **5d4** — robustesse trouvée en écrivant les tests de 5d3 :
  `select_with_cursor` ne parle à GTK que pour une vraie `wx.ListBox`. Un
  objet factice (`MagicMock`) répond à `GetGtkWidget()`, et `int()` lui
  donne 1 : GTK aurait reçu l'adresse 1 (segfault). Le plantage
  effectivement constaté venait d'ailleurs : un vrai `SynthEngine` créé par
  la préécoute de Ctrl+T dans le routeur de `test_track_channels.py`
  (adapté en 5e4).
- **5e4** — tests de 5d3 et 5d4, dans `tests/test_rack_mode_ui.py` (58
  tests), sur une vraie liste des slots : parcourir un kit, un synthé ou
  un slot vide ne charge rien (batterie, noms des pads et préécoute
  inchangés) ; Ctrl+T assigne et charge le slot listé (kit renommant les
  pads en mode normal, préécoute d'un synthé) ; Explorateur : kit dans un
  slot listé non joué (rien chargé) ou joué (chargé), patch (pistes du
  slot rechargées, clavier inchangé), banque (préécoute inchangée) ; liste
  et curseur gardés sur le slot listé ; curseur au changement de piste.
  Fakes adaptés : `_listed_slot` des fenêtres de `test_explorer_actions.py`
  et `test_bank_dialogs.py`, `_load_kit_slot` et préécoute neutralisée du
  routeur de `test_track_channels.py` (un vrai `SynthEngine` y faisait
  planter Python à la sortie). 3334 verts.
- **Essai de l'utilisateur (2026-11-03), remarque 5** : Ctrl+T
  (assigner une piste à un slot) ne pose pas d'Undo en mode normal ; on ne
  peut pas revenir en arrière → 5d5.
- **5d5** — correctif : Ctrl+T / Entrée en mode normal posent un Undo
  « Piste 4 → Slot_10 » avant l'assignation ; slot et canal de la piste
  sont déjà dans l'état capturé (pattern courant recopié du routeur).
  Même slot et même canal : rien n'est fait, « Piste 4: déjà sur Slot_10
  (808), canal 10 », sans Undo. `_restore_state` (Undo / Redo) rétablit
  le slot joué s'il a changé (`_follow_track_slot` : préécoute ou kit
  rechargés), et seulement dans ce cas, pour ne pas recharger un kit (et
  renommer ses pads) à chaque Undo.
  - `pytest` : **24 tests rouges jusqu'à 5e5** : 23 dans
    `test_loop_undo.py`, `test_master_mix.py`, `test_undo_clean_point.py`
    (fenêtres factices sans `_cur_slot`), et
    `test_ctrl_t_normal_mode_assigns_slot` (`test_rack_mode_ui.py`), qui
    vérifiait l'absence d'Undo.
- **5e5** — tests de 5d5 : Undo de Ctrl+T de bout en bout dans
  `tests/test_rack_mode_ui.py` (61 tests ; vrai `UndoManager`, vraie
  capture et restauration de l'état) : Undo puis Redo rétablissent slot,
  canal (10 ↔ 1) et son du slot joué (préécoute de la banque, kit
  rechargé) ; même slot et même canal sans Undo ; Undo d'une autre action
  sans recharger le kit. Fakes des 24 tests rouges adaptés : `_cur_slot`,
  `slot_for_track` et `_follow_track_slot` de la fenêtre de
  `test_master_mix.py` (dont héritent celles de `test_loop_undo.py` et
  `test_undo_clean_point.py`) ; Undo attendu dans
  `test_ctrl_t_normal_mode_assigns_slot`. 3337 verts.

### Clôture (5h1)

**5a-5e5 FAITS** (commits `22af5bc` à `23979c5`, et ce commit de
clôture ; 3337 tests verts) : **chantier Phase 8 étape 5 complet**. Un
pattern en mode Rack 16 canaux joue chaque canal avec le slot de même
numéro : un `.mid` importé sonne avec les sons du Rack (synthés WAV, kit,
banques), les canaux vides avec la banque GM.

**Ce que le chantier a livré** :
- **Moteur** : `Pattern._rack_mode` (`.gvp`) ; slot effectif du routeur
  (canal N → slot N, repli sur le premier slot Banque, slot vide muet) ;
  canal courant et poursuite de toutes les pistes ; Program Change sans
  pont ; moteurs des slots synthé des canaux joués ; note PATCH sur un
  kit par sa note GM (deux modes) ; un kit par pattern, chargé sans
  renommer les pads, avec avertissements.
- **Interface** : case des propriétés du pattern et Undo ; libellé
  « Canal N → slot » ; Ctrl+T = canal du slot ; entrée MIDI sur la piste
  courante comme Sonar ; propriétés de piste où le slot est le canal.
- **Import et export** : choix « Banque GM / Rack 16 canaux » à l'import ;
  export MIDI où le canal suit les Program Change et où chaque piste est
  décrite par le slot de son canal ; rendu WAV par le même routeur.
- **Correctifs de l'essai de l'utilisateur** (2026-11-02 et 03), utiles
  aux deux modes : curseur clavier des listes liées sous GTK
  (`ui/gtk_listbox.py`, 5d2, 5d4) ; parcourir la liste des slots ne charge
  plus rien, slot joué et slot listé séparés (5d3) ; Undo de Ctrl+T et
  slot joué rétabli par l'Undo (5d5) ; kit « GM (FluidR3) » renommé
  « Kit GM » dans les données de l'utilisateur (5e3) ; Program Change du
  contrôleur testé de bout en bout par le code (5e2).

**Écarts au plan** : Rack plein sans slot Banque accepté à l'import en
mode Rack ; notes PATCH d'un kit exportées dans les deux modes ; Ctrl+T
pose un Undo dans les deux modes ; `dp_playback.py` inchangé ;
correctifs imprévus 5b2, 5f2 (trouvés par les tests) et 5d2-5d5 (trouvés
à l'essai), avec leurs tests 5e2-5e5.

**`docs/SPECS.md`** : ligne Phase 8, arborescence (`gtk_listbox.py`,
`test_rack_mode.py`, `test_rack_mode_ui.py`), section « Mode Rack 16
canaux », Program Change, TrackRouter, Export MIDI, Import MIDI, format
`.gvp` (`rack_mode`), liste des slots, boîtes de dialogue
(`ImportModeDialog`, propriétés du pattern et de la piste), tests.
**`docs/shortcuts.md`** : Alt+Shift+I (choix), propriétés du pattern
(mode Rack), liste des slots (parcourir, Entrée, Alt+X), Ctrl+T (slot
listé, Undo, mode Rack), propriétés de piste en mode Rack.

**Essais de l'utilisateur** (2026-11-02, 03) : cinq remarques, toutes
traitées (propriétés de piste, noms de slots, Program Change, liste des
slots, Undo de Ctrl+T). Le
Program Change envoyé du contrôleur n'a pas pu être essayé (fonction peu
accessible sur le contrôleur) : couvert par les tests de bout en bout.

**Laissé hors périmètre** :
- plusieurs kits joués ensemble (chantier 128 pads / AudioSampler) ;
- le pont `program % 16` en mode normal ;
- les réglages GM d'une piste qui change de type de slot en cours de
  morceau (export) ;
- une commande pour renommer un slot ;
- filtre de canal d'entrée par piste, notes en temps flottant, SFZ.

## Phase 8 étape 6a — Notes coupées avant un changement de son, Mute/Solo exclusifs (F3, F4)

### Numérotation des commits de ce chantier

`6a` = ce plan (doc seule). Le code commence à `6b1`. Une paire impl →
tests par sous-chantier ; `6a2`, `6b2`… pour un commit imprévu. Décisions
notées **N1, N2…** (§ 6a).

### Origine du besoin (utilisateur, 2026-11-03)

- Des notes MIDI restent bloquées et jouent sans fin. Avant un changement
  de slot, de canal ou de Program Change, il faut un « Panic » ; de même
  avant un Mute ou un Solo de piste.
- Deux nouveaux modes, **Mute exclusif** et **Solo exclusif** : seule la
  piste courante est en Mute (ou en Solo), sans tenir compte des autres ;
  naviguer dans la liste des pistes (Haut / Bas) y met la nouvelle piste ;
  **F3** bascule le Mute exclusif, **F4** le Solo exclusif. L'utilisateur
  doutait de l'utilité du Mute exclusif (doublon du Mute ?) : gardé (N6).
- Shift+X / Shift+S doivent toujours désactiver tous les Mute / Solo,
  modes exclusifs compris (N15).

### État des lieux constaté en code (2026-11-03, 3337 tests verts)

- **Cause des notes sans fin** : une note jouée au contrôleur est tenue
  jusqu'au relâchement (`bank_note(..., duration 0)`, `synth.play(..., 0)`).
  Au relâchement, l'arrêt part vers le canal **actuel** de la piste
  (`BankPreview.stop`, `track_router.py:44`) ou vers le moteur de
  préécoute **actuel** (`router.synth.stop`, `on_note_off` de
  `midi_handler_window.py`). Un changement de slot, de canal ou de
  programme entre l'appui et le relâchement envoie l'arrêt ailleurs : la
  note reste tenue. À la lecture, pas ce défaut : chaque fin de note est
  programmée avec le canal et le moteur de son début (`bank_note`,
  `_play_synth_note`).
- **Coupures existantes** : `stop_all_synth_voices` (banques
  `all_notes_off`, moteurs synthé ; All Notes Off, CC123), `stop_all_sounds`
  (plus kit et banque `all_sounds_off` ; CC120), `panic` (Ctrl+F12 : plus
  Reset All Controllers). `BankEngine.all_notes_off` / `all_sounds_off`
  valent pour les 16 canaux, sans canal (`bank_engine.py:81`, `:84`) ; un
  All Notes Off laisse sonner les notes tenues par la pédale.
- **Mute / Solo de piste** : `toggle_track_mute`, `toggle_track_solo`,
  `unmute_all_tracks`, `unsolo_all_tracks` (`track_router.py`), appelés par
  X, Shift+X, S, Shift+S de la fenêtre principale
  (`key_handler_chars.py:124-185`) et de l'éditeur MIDI
  (`mew_playback.py:23-52`), et par les cases Mute / Solo des propriétés
  de piste ; Undo `_add_mix_undo` (`mw_project.py:1359`), regroupé en
  moins d'une seconde pour une même clé. Règle d'écoute `track_audible` :
  une piste muette se tait ; s'il y a un solo, seules les pistes en solo
  jouent. Mute et Solo sont sauvés dans le `.gvp` et suivis par l'export.
- **Changement de piste** : `_on_track_select` → `_go_to_track`
  (`mw_tracks.py`), interdit pendant l'enregistrement.
- **Touches** : F1 (aide) et F2 (renommer) dans `key_manager.py:58-66` ;
  **F3 et F4 libres**.

### Décisions validées (utilisateur, 2026-11-03)

**N1 — Mute / Solo : toutes les notes coupées.** Avant tout changement de
Mute ou de Solo de piste (X, Shift+X, S, Shift+S dans la fenêtre
principale et l'éditeur MIDI, cases des propriétés de piste, modes
exclusifs et leur navigation), en lecture comme à l'arrêt : toutes les
notes de tous les moteurs sont coupées.

**N2 — Slot, canal, programme : les notes de la piste seule.** Avant un
changement de slot, de canal ou de programme fait par l'utilisateur
(propriétés de piste, Ctrl+T, Entrée ou double-clic sur un slot, Program
Change reçu du contrôleur) : seules les notes de cette piste sont coupées.

**N3 — Un Program Change rejoué par le pattern ne coupe rien** : la note
précédente finit à sa durée, comme aujourd'hui.

**N4 — Les modes exclusifs écrivent vraiment Mute et Solo.** Les drapeaux
Mute / Solo des pistes sont modifiés (sauvés dans le `.gvp`, Undo, suivis
par l'export) ; en quittant le mode, l'état reste celui de la dernière
piste.

**N5 — F3 bascule le Mute exclusif, F4 le Solo exclusif** ; Haut / Bas
dans la liste des pistes y met la nouvelle piste courante.

**N6 — Les deux modes sont gardés** (avis donné : le Mute exclusif fait
entendre « tout sauf la piste courante » en naviguant, ce que le Mute
normal, fixe, ne fait pas).

**N15 — Shift+X et Shift+S désactivent toujours tout** : Shift+X démute
toutes les pistes et quitte le Mute exclusif ; Shift+S retire tous les
solos et quitte le Solo exclusif ; dans n'importe quel mode, avec Undo et
coupure des notes (N1). Annonce : « Toutes les Pistes: Démutées — Mute
exclusif : Off ».

### Choix de conception proposés

- **N7 — Coupure des notes = notes seules.** All Sounds Off (coupure nette,
  y compris les notes tenues par la pédale) et pédale relâchée (CC64 à 0) ;
  Pitch Bend et modulation **gardés**, pour ne pas casser l'automation en
  lecture. Ce n'est pas le Panic de Ctrl+F12, qui remet aussi les
  contrôleurs à zéro.
- **N8 — `TrackRouter.cut_all_notes()`** (N1) : moteurs synthé et
  préécoute (`stop_all_voices`), sons du kit (`stop_all`), banque
  (`all_sounds_off`, CC64 à 0 sur les 16 canaux).
- **N9 — `TrackRouter.cut_track_notes(t)`** (N2), appelé **avant** le
  changement : banque → All Sounds Off et CC64 à 0 sur le canal courant de
  la piste (nouveau `BankEngine.channel_sounds_off(channel)`, CC120 du
  canal ; FluidSynth `fluid_synth_all_sounds_off(synth, chan)`) ; synthé →
  `stop_all_voices` du moteur de son slot ; et toujours le moteur de
  préécoute (les notes tenues au clavier). Un kit n'a que des one-shots :
  rien à couper. Les pistes qui partagent ce canal ou ce moteur perdent
  aussi leurs notes en cours : accepté (un moteur ne sait pas à quelle
  piste appartient une voix).
- **N10 — État du mode** : `MainWindow._exclusive` ∈ {None, "mute",
  "solo"}, de session (non sauvé). F3 et F4 s'excluent : F4 en Mute
  exclusif passe en Solo exclusif. F3 / F4 agissent dans la fenêtre
  principale, quel que soit le focus ; F3 en Mute exclusif (F4 en Solo
  exclusif) quitte le mode.
- **N11 — Application** sur la piste courante t : Solo exclusif → solo de
  t seul (les autres solos retirés), mute de t retiré ; Mute exclusif →
  mute de t seul (les autres mutes retirés), tous les solos retirés. À
  l'activation, puis à chaque changement de piste courante (Haut / Bas
  dans la liste des pistes, et tout passage par `_go_to_track`).
- **N12 — Undo** : un par activation (« Solo exclusif : piste 3 ») ; la
  navigation passe par `_add_mix_undo` avec la clé `("exclusive", mode)` :
  une navigation rapide ne donne qu'une entrée, titrée de la dernière
  piste. Quitter le mode par F3 / F4 ne change rien, donc pas d'Undo.
- **N13 — Annonces** : « Solo exclusif : On — piste 3 », « Solo exclusif :
  Off », et à la navigation le libellé de piste, qui porte déjà [S] / [M].
- **N14 — X / S pendant un mode exclusif** : ils restent des bascules
  normales, et quittent le mode (le mode ne survivrait pas à un état
  qu'il n'a pas posé) ; annonce « … — Solo exclusif : Off ».

### Portée exclue

- Mute / Solo exclusifs dans l'éditeur MIDI (Alt+4) : F3 / F4 de la
  fenêtre principale seulement ;
- Mute / Solo des pads ;
- une coupure au Program Change rejoué par le pattern (N3) ;
- un suivi des notes par piste dans les moteurs (N9).

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **6a** | Doc — ce plan. | `docs/DESIGN.md` |
| **6b1** | Implémentation — N1-N3, N7-N9 : `cut_all_notes`, `cut_track_notes`, `channel_sounds_off` ; appels avant Mute / Solo (fenêtre principale, éditeur MIDI, propriétés de piste) et avant slot / canal / programme (propriétés de piste, Ctrl+T, Program Change du contrôleur). Essayé au contrôleur. | `src/engines/bank_engine.py`, `src/engines/fluidsynth_engine.py`, `src/track_router.py`, `ui/key_handler_chars.py`, `ui/mew_playback.py`, `ui/mw_tracks.py`, `ui/midi_handler_window.py` |
| **6c1** | Tests — 6b1 (coupures, ce qui est gardé, quels gestes coupent, Program Change rejoué sans coupure, note tenue au contrôleur coupée). | `tests/test_note_cuts.py` (nouveau), `docs/SPECS.md` |
| **6d1** | Implémentation — N4-N6, N10-N15 : F3 / F4, application, navigation, Undo, annonces, Shift+X / Shift+S. Essayé avec Orca. | `ui/key_manager.py`, `ui/mw_tracks.py`, `ui/key_handler_chars.py` |
| **6e1** | Tests — 6d1. | `tests/test_exclusive_mute_solo.py` (nouveau), `docs/SPECS.md` |
| **6f1** | Doc — clôture (SPECS, raccourcis, aide F1), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 6 — Avancement (6b1)

- **6b1** — coupures des notes, conforme à N1-N3, N7-N9 :
  - `BankEngine.channel_sounds_off(canal)` (par défaut CC120 du canal ;
    `FluidSynthEngine` : `fluid_synth_all_sounds_off(synth, canal)`) ;
  - `TrackRouter.cut_all_notes()` : moteurs synthé, préécoute et Kit
    pitché (voix coupées, pédale relâchée), sons du kit, banque (All
    Sounds Off, CC64 à 0 sur les 16 canaux) ;
  - `TrackRouter.cut_track_notes(t)` : canal courant de la piste sur une
    banque, moteur de son slot sur un synthé, et la préécoute (son canal
    ou son moteur) ; une fois par canal et par moteur ;
  - appels : X, Shift+X, S, Shift+S sur la liste des pistes, X et S de
    l'éditeur MIDI → `cut_all_notes` ; propriétés de piste → Mute / Solo
    changés : `cut_all_notes`, son changé (slot, canal, programme, MSB,
    LSB, Annuler compris) : `cut_track_notes` ; Ctrl+T et Entrée (deux
    modes), Program Change reçu du contrôleur → `cut_track_notes`. Rien au
    rejeu du pattern (N3).
  - Vérifié par un script : note tenue sur une banque coupée sur son canal
    avant le Program Change ; Pitch Bend et modulation non touchés.
  - `pytest` : **21 tests rouges jusqu'à 6c1**, dus aux fakes (routeurs
    factices sans `cut_all_notes` / `cut_track_notes`, `TrackRouter` sans
    `__init__` dans `test_mix_undo.py`, synthé factice sans
    `stop_all_voices`).
- **6c1** — `tests/test_note_cuts.py` (27 tests) : CC120 d'un canal
  (défaut et FluidSynth) ; `cut_all_notes` (tous les moteurs une fois,
  kit, banque et pédale sur 16 canaux, Pitch Bend et modulation gardés,
  sans banque) ; `cut_track_notes` (canal courant d'une banque, préécoute
  une fois, note tenue au contrôleur coupée avant le changement de canal,
  synthé et préécoute, autres moteurs intacts, kit, mode Rack) ; Program
  Change rejoué sans coupure ; gestes : X, S, Shift+X, Shift+S (coupure
  avant la bascule), pads sans coupure, propriétés de piste (canal, slot,
  volume sans coupure, Mute, Annuler), Ctrl+T (deux modes, même slot sans
  coupure), Program Change du contrôleur ; 2 tests de l'éditeur MIDI
  (`test_midi_editor_window.py`). Fakes des 21 tests rouges adaptés
  (`cut_all_notes` / `cut_track_notes` des routeurs factices, moteurs du
  `TrackRouter` sans `__init__` de `test_mix_undo.py`, `stop_all_voices`
  du synthé factice de `test_bank_slot.py`) ; `SPECS.md`. 3366 verts.
- **Essai de l'utilisateur (2026-11-03)** : concluant pour le Mute / Solo
  pendant la navigation des pistes et pour les changements de slot, canal
  et Program Change des propriétés de piste. **Défaut** : une note tenue
  au contrôleur pendant la navigation des pistes reste bloquée sur le
  canal de la piste précédente ; elles s'accumulent, seul Ctrl+F12 les
  arrête → 6b2.
- **6b2** — correctif : le relâchement va **là où la note a été jouée**.
  La cause est celle de l'état des lieux (arrêt vers le canal ou le moteur
  de préécoute actuels), déclenchée par le changement de piste, que N2 ne
  couvre pas. Plutôt qu'une coupure à chaque changement de piste (qui
  couperait la musique en lecture) :
  - `BankPreview` retient le canal de chaque note tenue (`_held`) et
    l'arrête sur ce canal ;
  - `MidiHandler._live_play` retient, pour chaque touche du contrôleur, le
    moteur de préécoute et la note jouée (`_live_held`) ; `on_note_off` les
    reprend (enregistrement de la fin de note et Erase compris), quels que
    soient la piste, le slot ou le canal courants. Les quatre jeux directs
    tenus (clavier et pads, avec ou sans Note Repeat) y passent.
  - Reproduit par un script avant la correction (note jouée canal 4,
    arrêt envoyé canal 6), puis corrigé (arrêt canal 4). 3366 verts ; tests
    en 6c2.
- **6c2** — tests de 6b2 dans `tests/test_note_cuts.py` (33 tests) :
  `BankPreview` arrête une note tenue sur son canal après un changement de
  piste, une note à durée n'est pas retenue ; note tenue au contrôleur
  pendant la navigation arrêtée sur le canal de la piste précédente (le
  cas de l'essai) ou sur son synthé ; fin de note enregistrée avec la note
  jouée malgré une transposition changée ; pad de batterie au canal 10.
  Les six échouent sur le code d'avant 6b2. 3372 verts.
- **Essai de 6b2 (utilisateur, 2026-11-03)** : concluant. Fichier MIDI
  importé en Banque GM, plusieurs notes tenues pendant la navigation des
  pistes : toutes s'arrêtent au relâchement. **Conséquence non recherchée,
  utile** : on peut jouer un accord dont chaque note appartient à un canal
  différent (une note, puis changer de piste, puis une autre…), sans note
  bloquée, puisque chaque relâchement va au canal où sa note a été jouée.
- **6d1** — Mute / Solo exclusifs, conforme à N4-N6, N10-N15 :
  - `MainWindow._exclusive` (None, "mute", "solo"), remis à None par
    Ctrl+N et Ctrl+O ; F3 / F4 sans modificateur (`key_manager.py`,
    après F2) → `_toggle_exclusive` (`mw_tracks.py`) : active (Undo « Solo
    exclusif : piste 3 », application, annonce « Solo exclusif : On —
    piste 3 ») ou quitte (« Solo exclusif : Off », état gardé) ; refusé
    pendant l'enregistrement ;
  - `_apply_exclusive(t)` : toutes les notes coupées, puis Solo exclusif
    → solo de t seul et t démutée ; Mute exclusif → mute de t seul, aucun
    solo ;
  - `_go_to_track` : en mode exclusif et si la piste change, Undo groupé
    (`_add_mix_undo`, clé `("exclusive", mode)`) puis application ;
    annonce « Piste 3 — Piano — Solo exclusif » ;
  - X / S (fenêtre principale et éditeur MIDI) quittent le mode,
    Shift+X le Mute exclusif, Shift+S le Solo exclusif
    (`_quit_exclusive`) : « … — Solo exclusif : Off » ;
  - `docs/shortcuts.md` (aide F1) : F3, F4, X / S / Shift+X / Shift+S,
    pour l'essai.
  - Vérifié par un script : activation, navigation (deux pas rapprochés,
    une entrée d'Undo), passage de F4 à F3, sortie. 3372 verts ; tests en
    6e1.
- **Essai de 6d1 (utilisateur, 2026-11-03)** : F3 / F4 marchent, mais ne
  font pas une bascule : en quittant le mode, l'état restait (N4), donc à
  l'oreille rien ne changeait. Demandes : une vraie bascule (choix :
  revenir à l'état d'avant le mode), et **F5** pour tout réinitialiser
  (Shift+X et Shift+S à la fois). Renommer aussi « GM (FluidR3) » en
  « Kit GM » dans le code (slot 5 créé au démarrage) → 5h2.
- **6d2** — révision de N4 : à l'activation depuis aucun mode,
  `_exclusive_saved` garde les Mute / Solo de toutes les pistes ; un
  second F3 / F4 (même après un passage de F4 à F3) pose un Undo
  « Solo exclusif : Off », coupe les notes et les rétablit ; annonce
  « Solo exclusif : Off — Mute et Solo d'avant rétablis ». X / S / Shift+X /
  Shift+S quittent sans rétablir (leur effet s'applique). **F5**
  (`_reset_mute_solo`) : Undo « Réinitialiser Mute / Solo » s'il y a
  quelque chose à défaire, notes coupées, tous les Mute et Solo retirés,
  mode quitté (« … — Solo exclusif : Off »). Aide F1 à jour. Vérifié par
  un script.
- **5h2** (Phase 8 étape 5, après sa clôture) — remarque 2 de l'essai de
  la Phase 8 étape 5, côté code : le slot 5 créé au démarrage sans projet
  (`main_window.py`) s'appelle « Kit GM » au lieu de « GM (FluidR3) ».
  Même programme GM deviné (0, kit standard).
- **Essai de 6d2 (utilisateur, 2026-11-03)** : concluant pour F3, F4
  (bascule, état d'avant rétabli) et F5 (réinitialisation).
- **6e1** — `tests/test_exclusive_mute_solo.py` (27 tests, vrai Undo,
  vraie liste des pistes) : activation par F4 / F3 (piste courante seule,
  notes coupées avant, Undo, annonce, passage d'un mode à l'autre, refus
  pendant l'enregistrement) ; navigation (le mode suit, Undo groupé en
  moins d'une seconde, notes coupées, rien sans mode ou sur la même
  piste) ; second F3 / F4 (état d'avant rétabli, même après un changement
  de mode ; Undo de la sortie et de l'activation) ; drapeaux réels suivis
  par l'écoute ; X / S / Shift+X / Shift+S pendant un mode ; X de
  l'éditeur MIDI ; F5 (tout retiré, mode quitté, Undo seulement s'il y a
  lieu) ; touches F3 / F4 / F5 par le vrai `KeyManager`, F4 avec
  modificateur sans effet. `SPECS.md`. 3399 verts. Non testé : la remise
  à zéro du mode par Ctrl+N / Ctrl+O (deux affectations).

### Clôture (6f1)

**6a-6e1 FAITS** (commits `053ec96` à `c0403f4`, et ce commit de
clôture ; 3399 tests verts) : **chantier Phase 8 étape 6 complet**. Plus
de note qui joue sans fin : les changements de son et les Mute / Solo
coupent les notes, et une note tenue au contrôleur s'arrête toujours là
où elle a été jouée. Mute et Solo exclusifs (F3, F4) et F5.

**Ce que le chantier a livré** :
- **Coupures** : `TrackRouter.cut_all_notes` (avant tout Mute / Solo),
  `cut_track_notes` (avant un changement de slot, canal, programme ou
  banque fait par l'utilisateur), `BankEngine.channel_sounds_off` ; notes
  seules, pédale relâchée, Pitch Bend et modulation gardés ; rien au
  Program Change rejoué.
- **Notes tenues au contrôleur** (6b2, trouvé à l'essai) : le
  relâchement va là où la note a été jouée (`MidiHandler._live_held`,
  `BankPreview._held`) ; effet utile, un accord sur plusieurs canaux.
- **Mute / Solo exclusifs** : F3, F4 ; la navigation des pistes suit ;
  drapeaux réels ; Undo à l'activation, groupé pendant la navigation ;
  second F3 / F4 = retour à l'état d'avant (6d2, à l'essai) ; X, S,
  Shift+X, Shift+S quittent le mode ; **F5** réinitialise tout (6d2).
- **5h2** : slot kit de démarrage « Kit GM » dans le code.

**Écarts au plan** : correctif 6b2 (relâchement des notes tenues) ;
révision de N4 en 6d2 (la sortie du mode rétablit l'état d'avant) ; F5
ajouté ; aide F1 mise à jour dès 6d1 pour les essais.

**Essais de l'utilisateur** (2026-11-03) : coupures (Mute / Solo pendant
la navigation, propriétés de piste) concluantes ; notes tenues pendant
la navigation, après 6b2, concluant (Banque GM, plusieurs notes) ; F3, F4
et F5, après 6d2, concluants.

**`docs/SPECS.md`** : ligne Phase 8, section « Notes coupées et notes
tenues », Program Change, Mute / Solo par piste (modes exclusifs, F5),
tests (`test_note_cuts.py`, `test_exclusive_mute_solo.py`).
**`docs/shortcuts.md`** (aide F1) : Panic (rarement utile désormais),
Mute / Solo des pistes (F3, F4, F5, coupure), « Pistes » (X, S, Shift+X,
Shift+S, F3, F4, F5 en détail ; Ctrl+T et propriétés de piste qui coupent
les notes), éditeur MIDI (X, S), contrôleur (notes tenues, Program
Change), aide (F3 / F4, F5).

**Laissé hors périmètre** :
- Mute / Solo exclusifs dans l'éditeur MIDI (F3 / F4 de la fenêtre
  principale seulement) ;
- Mute / Solo des pads ;
- un suivi des notes par piste dans les moteurs (une coupure de canal ou
  de moteur touche les autres pistes qui le partagent) ;
- le test de la sortie du mode par Ctrl+N / Ctrl+O.

## Phase 8 étape 7a1 — Instruments SFZ : choix de sfizz, compilation de libsfizz, essai par ctypes

### Numérotation des commits de ce chantier

`7a1` = ce commit (doc et outil d'essai) : choix du moteur, compilation
de libsfizz, essai par ctypes. `7a2` = le plan de conception (état des
lieux, décisions, découpage), après les questions restantes. Le code
commence à `7b1`. Une paire impl → tests par sous-chantier ; `7b2`,
`7c2`… pour un commit imprévu. Décisions notées **Z1, Z2…**.

### Origine du besoin (utilisateur, 2026-11-03)

- Gérer le format **SFZ** et un slot de Rack **« Synth SFZ »**.
- Déjà noté en Phase 7 étape 17a1 : FluidSynth **ne lit pas** le SFZ ;
  deux voies évoquées, sfizz (bibliothèque C/C++) ou notre AudioSampler
  avec un analyseur SFZ ; l'interface étroite `BankEngine` (D1) était
  prévue pour accueillir le SFZ.
- Contrainte transverse : le moteur audio Python est un **prototype**, la
  cible est C/C++.

### Décisions validées (utilisateur, 2026-11-04)

**Z1 — sfizz par ctypes, pas de moteur SFZ maison.** Comparaison faite
avec l'utilisateur :
- un moteur maison (analyseur, voix lues à vitesse variable, enveloppes,
  boucles, groupes, round robin, keyswitches…) serait un chantier de la
  taille de la Phase 7 étape 17, limité (sous-ensemble d'opcodes, pas de
  filtres ni de LFO, tout en mémoire, polyphonie bornée par Python,
  interpolation linéaire), et **jeté** à la réécriture C/C++, qui liera
  sfizz ;
- sfizz couvre les opcodes, lit les samples depuis le disque, interpole
  finement ; la liaison ctypes sert de modèle à la future liaison C/C++ ;
- le travail durable est l'intégration (slot, routage, Rack, `.gvp`,
  export, coupures de notes), identique dans les deux voies.
- Prix accepté : libsfizz n'est pas dans Debian 13, il faut la compiler
  (une fois, puis à chaque mise à jour voulue).

**Z2 — nouveau type de slot « Synth SFZ »** : le slot porte son propre
fichier `.sfz`, un slot = un instrument (jusqu'à 16), joué sur le canal
de la piste. Il n'utilise pas les 4 emplacements du slot Banque (D3/D4
de la Phase 7 étape 17a1 ne valent donc pas pour le SFZ).

**Z3 — instruments d'essai téléchargés par Claude**, hors du dépôt
(licences, taille), pour les essais à l'écoute.

**Z4 — l'appli doit marcher sans FluidSynth ni sfizz.** Les deux moteurs
dépendent de bibliothèques compilées ; l'appli doit se lancer et rester
entièrement fonctionnelle sans eux. Options **`--no-fluidsynth`** et
**`--no-sfizz`** dans le fichier de configuration (`config.json`).
Moteur désactivé ou bibliothèque absente : slots Banque ou Synth SFZ
muets avec un message ; kits, synthés WAV, séquenceur, MIDI et exports
inchangés ; tests dépendants sautés. Aujourd'hui, seule l'absence de
libfluidsynth est gérée (`MainWindow._init_bank_engine` →
`_bank_engine = None`) ; aucune option ne coupe un moteur installé, et
`main.py` ne lit pas la ligne de commande. **À préciser en 7a2** : forme
des clés de `config.json` (par exemple `"fluidsynth": false`), ligne de
commande en plus ou non, message affiché, comportement d'un projet qui
contient de tels slots (gardés tels quels dans le `.gvp`, jamais perdus).

### Compilation et essai (2026-11-04)

Procédure complète, de A à Z, dans **`docs/sfizz_build.md`** :
- clone récursif de `sfztools/sfizz` (commit `f5c6e29`, 2025-03-17,
  bibliothèque 1.2.3) dans `/home/com/build/sfizz` ;
- CMake Release, bibliothèque partagée, sans JACK, avec `sfizz_render`
  et les tests ; compilation en 1 min 58 s sur 8 cœurs ;
- tests de sfizz : 477 cas, 52 206 assertions, tous verts ;
- installation dans `~/.local` (sans `sudo`) ;
- procédure **rejouée à blanc** dans un dossier neuf : même résultat.

Essai par ctypes : **`tools/sfizz_probe.py`** (17 vérifications, toutes
vertes, sur les deux compilations) : chargement et refus, opcodes
inconnus, hauteur et transposition, Pitch Bend, vélocité, note off,
délai exact dans le bloc, All Sound Off, CC64, `group` / `off_by`, deux
instances, 32 voix = 2,5 % du temps réel.

### Faits qui pèsent sur le plan 7a2

- **Une instance sfizz = un instrument, sans canal MIDI** : un slot
  Synth SFZ = une instance (Z2 s'y prête bien).
- **Événements datés à l'échantillon** dans le prochain bloc : file
  d'événements vidée dans le callback, transposable en C/C++.
- **Rendu en deux canaux séparés**, à ajouter au mixage (source de rendu
  du pilote, comme FluidSynth).
- **Chargement bloquant** : dans un fil, sur une instance neuve, puis
  échange.
- **CC 7, 10, 11, 64 répondus par défaut** : volume et pan de piste par
  CC7 / CC10, comme pour une banque.
- **Niveau bas** (cosinus 0,5 → RMS 0,058 à vélocité 100) : un gain
  `sfizz_gain` à régler à l'écoute, comme `fluidsynth_gain`.
- Le chemin `~/.local/lib` n'est pas dans `ldconfig` : chargement par
  chemin complet, puis le système (Z4 pour l'absence).

## Phase 8 étape 7a2 — Plan : slot « Synth SFZ » joué par sfizz, appli sans FluidSynth ni sfizz

Suite de § 7a1 (Z1-Z4). Décisions de 7a2 notées **Z5, Z6…**

### État des lieux constaté en code (2026-11-04, 3399 tests verts)

- **Le slot Banque fait déjà presque tout ce qu'il faut.**
  `BankEngine` (`src/engines/bank_engine.py`) est une interface à canaux :
  `select`, notes, `cc`, `pitch_bend`, `channel_sounds_off`,
  `all_sounds_off`, `render(out)`, `render_copy()`, `active_voices()`.
  `TrackRouter` s'en sert pour :
  - le canal courant de la piste (`_track_cur_channels`) ;
  - le volume et le pan de piste en CC7 / CC10 (`_send_bank_mix`) ;
  - la poursuite (`chase`, `sync_banks`, cache `_chan_sel`) ;
  - les CC, le Bend et la pédale par canal (`on_cc_tape`, `on_bend_tape`,
    `on_mod_tape`) ;
  - les coupures (`cut_track_notes`, `cut_all_notes`, Phase 8 étape 6) ;
  - la préécoute `BankPreview`, qui retient le canal des notes tenues
    (6b2) ;
  - les notes de grille (`_bank_grid_note` : canal 10 → 36 + pad,
    sinon gamme du clavier) ;
  - le mode Rack (`_slot_idx_of`, `fallback_bank_idx`).
- **Un seul moteur, un seul type.** `InstrumentType.BANK` est testé
  13 fois dans `track_router.py` (via `_bank_slot_of`, `:478`, et
  directement à `:288`, `:360`, `:427`, `:488`, `:551`, `:758`, `:865`,
  `:989`, `:1014`, `:1065`, `:1095`, `:1113`). Les appels vont toujours à
  `self.bank_engine`. Hors du routeur :
  - `rack.py:44`, `:111` (`plays_notes`, programme GM) ;
  - `ui/mw_project.py:169` (export : `is_bank`), `:760`, `:837` (import) ;
  - `ui/mw_tracks.py:132`, `:142`, `:174`, `:228` (propriétés de piste,
    Ctrl+T) ;
  - `ui/mw_pads.py:278-305` (Explorateur, élément « Banque ») ;
  - 11 fichiers de tests.
- **Moteurs au démarrage** : `MainWindow._init_bank_engine`
  (`ui/main_window.py:216`) crée `FluidSynthEngine` et le branche au
  pilote (`add_render_source`) ; libfluidsynth absente →
  `_bank_engine = None`, les slots Banque sont muets. **Aucune option**
  ne coupe un moteur installé.
- **Démarrage** : `main.py` ne lit pas la ligne de commande.
- **Configuration** : `AppConfig` (`src/app_config.py`) lit
  `data/config.json` et ne l'écrit jamais. Clés de la banque :
  `soundfonts_dir`, `gm_soundfont`, `midi_bank_select`,
  `fluidsynth_gain`.
- **Export WAV** : `audio_export.py:110` copie le moteur de banque
  (`render_copy`) et le passe à `router.render_copy`.
- **Export MIDI** : `build_pattern_midi(track_is_bank=…)`
  (`midi/midi_export.py:84`). Une piste Banque prend ses entêtes PGM /
  CC0 / CC32 dans `_tape`. Les autres pistes prennent le `gm_program` de
  leur slot.
- **Explorateur** : `ExplorerDialog.ITEMS` (`ui/dialogs_simple.py:472`) =
  Projects, Preset, Kit, Patch, Sound, Banque.

### Décisions validées (utilisateur, 2026-11-04)

**Z5 — une instance sfizz par canal** (le canal est l'instrument, comme
pour la banque). Chaque piste garde son volume et son pan par CC7 / CC10
de son canal. Deux pistes sur le même slot SFZ et sur deux canaux
différents chargent l'instrument deux fois (temps et mémoire), ce qui est
accepté. En mode Rack (canal N → slot N), cela fait un chargement par
slot.

**Z6 — choix de l'instrument : une liste des instruments trouvés dans
`sfz_dir`.** Nouvel élément **« SFZ »** de l'Explorateur (Alt+X), pour le
slot courant. Une ListBox navigable au clavier liste les `.sfz`,
parcourus récursivement, avec un bouton **« Parcourir… »** en plus. Les
fragments sont écartés : un fichier inclus (`#include`) par un autre
`.sfz` de l'arborescence, ou dont un `#include` est introuvable (cas de
`big-rusty-drums/Programs/default/`).

**Z7 — options de Z4 : `config.json` et ligne de commande.**
- Clés `"fluidsynth": true|false` et `"sfizz": true|false` (défaut
  `true`).
- Arguments `--no-fluidsynth` et `--no-sfizz` de `main.py`. Ils priment
  sur `config.json` le temps d'un lancement.
- Moteur coupé ou bibliothèque absente : les slots Banque et Synth SFZ
  sont gardés **intacts** dans le Rack, le `.gvp` et l'Undo, mais
  restent muets. La barre d'état l'explique au démarrage, puis à chaque
  choix d'un tel slot. Tout le reste marche (kits, synthés WAV,
  séquenceur, MIDI, exports).

### Choix de conception proposés

Ils seront confirmés ou corrigés dans « Avancement » au fil des commits.

**Z8 — `SfzEngine` implémente `BankEngine`** (`src/engines/sfizz_engine.py`,
liaison ctypes comme `fluidsynth_engine.py`, signatures déclarées dans un
seul module, celles de `tools/sfizz_probe.py`).
- « Emplacement » = **indice du slot du Rack** (0..15) :
  - `load(slot, path)` retient le fichier du slot ;
  - `select(channel, slot, bank, program)` lie le canal à ce fichier
    (banque et programme ignorés) et charge l'instance du canal si le
    fichier a changé ;
  - `presets(slot)` = `[(0, 0, nom du fichier)]` ;
  - `program_change` est sans effet.
- `NUM_BANK_SLOTS` vaut 16 pour ce moteur.
- `channel_sounds_off(ch)` = `sfizz_all_sound_off` de l'instance du
  canal ; `reset_controllers` = Bend au centre, CC1 et CC64 à 0, CC11 à
  127 (sfizz n'a pas de CC121 propre, à vérifier en 7b1).
- `active_voices()` = somme des instances.

**Z9 — sfizz n'est appelé que depuis le callback audio.**
- **File d'événements** : l'interface, les `threading.Timer` et le
  séquenceur déposent `(type, canal, a, b)` dans une `collections.deque`
  (ajout atomique). `render(out)` la vide avant de rendre, avec un
  `delay` de 0 : la précision reste celle d'aujourd'hui, celle des
  minuteries. Une datation à l'échantillon pourra venir plus tard sans
  changer l'interface.
- **Chargement dans un fil**, sur une instance neuve (fréquence du
  pilote, taille de bloc maximale) ; un événement « échange » la met en
  place dans le callback. L'ancienne instance est libérée hors du
  callback.
- **Tampons préalloués** L et R, à la taille de bloc maximale.
  `render(out)` ajoute `gain × (L, R)` dans `out (frames, 2)`.
- Pendant le chargement, le canal est muet et la barre d'état dit
  « Chargement de <instrument>… », puis « prêt ».
- Prototype, cible C/C++ : file d'événements et échange d'instance se
  transposent tels quels (file sans verrou en C/C++).

**Z10 — `InstrumentType.SFZ = "sfz"`**, libellé « Synth SFZ ».
- `config` = `{"sfz_file": chemin}` : relatif à `sfz_dir` s'il s'y
  trouve (projet portable), absolu sinon.
- Nom du slot = nom du fichier, sans extension.
- `plays_notes` est vrai.
- Le Rack est déjà dans le `.gvp` et l'instantané d'Undo :
  `_restore_state` recharge un canal seulement si son fichier a changé.
- `ProjectManager.VERSION` est inchangé (nouveau type, rien à migrer).

**Z11 — routeur : « slot à canaux »** = BANK ou SFZ.
- `_bank_slot_of` devient `_chan_slot_of` (BANK ou SFZ), et
  `_engine_of(slot)` rend `bank_engine` ou `sfz_engine` (None si coupé).
- Les branches Banque valent pour les deux types : notes, grille, CC,
  Bend, pédale, mix, chase, coupures, préécoute (`BankPreview` prend le
  moteur de son slot).
- **Différences du SFZ** :
  - le Program Change déplace la piste sur son canal (O3), mais ne
    change pas le son ;
  - CC0 / CC32 sont gardés dans `_tape` mais sans effet ;
  - mode Rack : un canal sur un slot vide se replie toujours sur le
    premier slot **Banque** (M5), pas sur un SFZ.
- `cut_all_notes`, `stop_all_sounds`, `panic` et `on_play_stop` passent
  par les deux moteurs.
- Une banque et un SFZ sur le même canal : avertissement de canal
  partagé, comme D10.

**Z12 — exports.**
- **MIDI** : une piste SFZ exporte ses notes comme une piste Banque
  (grille D12, canal courant), avec le **`gm_program` du slot**, comme un
  synthé WAV. Dans Alt+Entrée, le programme GM du slot reste réglable
  pour l'export ; programme et MSB / LSB du canal sont grisés.
- **WAV** : `audio_export` copie aussi le moteur SFZ
  (`SfzEngine.render_copy()`, chargement bloquant permis hors temps
  réel) et le passe à `router.render_copy`.

**Z13 — configuration.** Nouvelles clés de `config.json`, lues par
`AppConfig` :
- `"sfz_dir"`, défaut `/home/com/groovybox/media/sfz` ;
- `"sfizz_gain"`, à régler à l'écoute en 7b1 (sfizz sort bas : crêtes
  0,03 à 0,23 à vélocité 100 sur les instruments d'essai) ;
- `"fluidsynth"` et `"sfizz"` (Z7).

Chargement de libsfizz : `~/.local/lib/libsfizz.so.1` d'abord, puis le
système (`docs/sfizz_build.md` § 7).

**Z14 — démarrage (Z7).** `main.py` lit `--no-fluidsynth` et
`--no-sfizz` (`argparse`, `parse_known_args` pour ne pas gêner wx) et
les passe à `MainWindow`. `_init_bank_engine` et `_init_sfz_engine`
consultent l'option, puis la bibliothèque. La barre d'état dit par
exemple « FluidSynth désactivé (--no-fluidsynth) : slots Banque muets »
ou « libsfizz introuvable : slots Synth SFZ muets ». Les tests des
moteurs restent sautés sans bibliothèque.

**Z15 — dialogue `SfzSlotDialog`** (`ui/dialogs_sfz.py`, Z6) :
- ListBox des instruments, avec le chemin relatif à `sfz_dir` comme
  libellé (« karoryfer-bigcat.cello/Programs/03- Plucked ») ;
- bouton « Parcourir… » ;
- Ok applique au slot courant, avec Undo « SFZ slot 03 », et Annuler ne
  change rien ;
- Ordre Tab : liste → Parcourir → Ok → Annuler ;
- curseur clavier posé par `ui/gtk_listbox.select_with_cursor` ;
- Alt+↑ joue une note d'aperçu de l'instrument sélectionné, comme dans
  la liste des pads (à confirmer à l'essai : le chargement peut prendre
  une seconde).
- Le parcours de `sfz_dir` se fait sur le texte des fichiers
  (`#include`), sans sfizz : rapide. Un fichier qui se révèle refusé au
  chargement donne un message, et le slot reste muet.

### Portée exclue

- Effets de sfizz, réverbération (VPO la demande, plus tard) et réglages
  de qualité (suréchantillonnage, interpolation) : défauts de sfizz.
- Accordage Scala, keyswitches affichés, étiquettes de touches et de CC
  (`sfizz_get_key_label_*`).
- Datation des événements à l'échantillon près (Z9).
- Une instance partagée par plusieurs canaux (Z5).
- Virtual Playing Orchestra (téléchargement manuel, plus tard).
- Un dialogue de réglage de `config.json` (chantier à
  part).
- Plusieurs kits SFZ en mode Rack au-delà de ce que M6 permet aux banques.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **7a2** | Doc — ce plan. | `docs/DESIGN.md` |
| **7b1** | Implémentation — `SfzEngine` (Z8, Z9), clés `sfz_dir`, `sfizz_gain`, `fluidsynth`, `sfizz` (Z13), options de ligne de commande et moteurs optionnels au démarrage (Z7, Z14), branchement au pilote. Démo `python3 -m engines.sfizz_engine <fichier.sfz>` ; gain réglé à l'écoute. | `src/engines/sfizz_engine.py` (nouveau), `src/app_config.py`, `src/main.py`, `src/ui/main_window.py` |
| **7c1** | Tests — moteur sur des `.sfz` et WAV fabriqués (comme `tools/sfizz_probe.py`) : file d'événements, échange d'instance, canaux, CC7 / CC10, coupures, `render_copy` ; sautés sans libsfizz. Config, options, démarrage sans moteurs. | `tests/test_sfizz_engine.py` (nouveau), `tests/test_app_config.py`, `tests/test_engine_options.py` (nouveau), `docs/SPECS.md` |
| **7d1** | Implémentation — type SFZ (Z10), routeur à deux moteurs (Z11), exports (Z12), `.gvp` / Undo. Essai à l'écoute sur un projet d'essai (batterie, piano, violoncelle). | `src/rack.py`, `src/track_router.py`, `src/audio_export.py`, `src/ui/mw_project.py`, `src/ui/mw_tracks.py`, `src/midi/midi_export.py` |
| **7e1** | Tests — routage avec un moteur SFZ factice (notes, grille, CC, Bend, pédale, chase, coupures, mode Rack, canal partagé), `.gvp`, exports ; types existants inchangés. | `tests/test_sfz_slot.py` (nouveau), fakes au besoin, `docs/SPECS.md` |
| **7f1** | Implémentation — élément « SFZ » de l'Explorateur et `SfzSlotDialog` (Z6, Z15), Alt+Entrée (champs grisés), messages des moteurs coupés, aide F1. Essai avec Orca. | `src/ui/dialogs_sfz.py` (nouveau), `src/ui/dialogs_simple.py`, `src/ui/mw_pads.py`, `src/ui/dialogs_properties.py`, `docs/shortcuts.md` |
| **7g1** | Tests — parcours de `sfz_dir` (fragments, `#include` introuvable), dialogue (Tab, Ok, Annuler, Undo, Parcourir), Alt+Entrée. | `tests/test_sfz_dialogs.py` (nouveau), `docs/SPECS.md` |
| **7h1** | Doc — clôture (DESIGN, SPECS : Rack, configuration, `.gvp`, options ; raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

- Avant de committer 7b1, 7d1 et 7f1, l'utilisateur les essaie (à
  l'écoute, et avec Orca pour 7f1).
- Les commits d'implémentation peuvent laisser `pytest` rouge à cause
  des fakes ; le titre le dira.

### Phase 8 étape 7 — Avancement (7b1)

- **7b1** — moteur et options, conformes à Z7, Z8, Z9, Z13, Z14 :
  - `src/engines/sfizz_engine.py` : `SfzEngine(BankEngine)`, liaison
    ctypes (`load_library`, `SfizzUnavailable`, `sfizz_available`) ;
    emplacement = slot du Rack (`NUM_BANK_SLOTS = 16`) ; une instance par
    canal ; file d'événements (`deque`, types entiers `EV_*`) vidée par
    `render()` ; chargement dans un fil sur une instance neuve,
    `EV_SWAP` avec numéro de génération (un chargement dépassé est
    libéré) ; instances remplacées libérées hors du callback ; un canal
    au repos (sans voix ni événement) n'est pas rendu ; blocs d'au plus
    1024 échantillons ; `render_copy()` hors temps réel
    (`realtime=False` : appels directs, chargement bloquant) ;
    `channel_ready`, `channel_path`, `wait_loaded`, `status_cb`.
  - **Écart à Z8** : sfizz traite lui-même les CC 120, 121 et 123
    (vérifié) : `all_notes_off`, `reset_controllers` et
    `channel_sounds_off` passent par eux ou par `sfizz_all_sound_off`,
    sans code propre. L'état des CC (sauf 120, 121, 123) et du Bend de
    chaque canal est **retenu et rejoué** sur une instance neuve : un CC7
    posé pendant le chargement n'est pas perdu.
  - **Écart au contrat `BankEngine.load`** : `load` ne fait que retenir
    le fichier (False s'il n'existe pas) ; sfizz ne le lit qu'à la
    sélection d'un canal, en arrière-plan ; un fichier refusé (aucune
    région) est signalé par `status_cb` (« SFZ refusé : … »), le canal
    reste muet.
  - `AppConfig` : `sfz_dir` (**écart à Z13** : défaut = `media/sfz` à côté
    du dossier des projets, comme `exports_dir`, soit
    `/home/com/groovybox/media/sfz` ; `config.json` inchangé),
    `sfizz_gain` (défaut 1.0, borné 0..10 : mesuré, sfizz sort alors à
    peu près comme FluidR3 à 0.4), `fluidsynth_enabled`,
    `sfizz_enabled` (clés `"fluidsynth"`, `"sfizz"`, défaut true).
  - `main.py` : `parse_args` (`--no-fluidsynth`, `--no-sfizz`,
    `parse_known_args`) → `MainWindow(no_fluidsynth, no_sfizz)` ;
    `_init_bank_engine` et `_init_sfz_engine` consultent l'option, puis
    la clé, puis la bibliothèque ; messages réunis dans la barre d'état
    au démarrage (« FluidSynth désactivé (--no-fluidsynth) : slots
    Banque muets ; … ») ; `_sfz_engine` fermé à la sortie.
  - Démo `python3 -m engines.sfizz_engine [fichier.sfz] [note]` (gamme
    canal 1, accord canal 2 à volume 60 et pan à gauche).
  - Vérifié par un script (sans carte son) : échange, CC rejoués, pan,
    deux canaux, fichier remplacé pendant le chargement, coupures, Bend
    et Reset, copie hors temps réel, fichier refusé.
  - `pytest` : **3 tests rouges jusqu'à 7c1**, dus aux fakes
    (`SimpleNamespace` sans `_no_fluidsynth` dans
    `test_fluidsynth_engine.py`, `_FakeMain` sans `_sfz_engine` dans
    `test_live_take.py`).
- **Essai de l'utilisateur (2026-11-04)** : concluant ; pas de
  craquements ; pas d'erreur avec les deux moteurs coupés. **Gain un peu
  faible**, mais à juger en comparant à l'écoute avec FluidSynth : à
  faire à l'essai de 7d1, le même morceau joué tour à tour par une
  banque FluidR3 et par un slot Synth SFZ, puis régler `sfizz_gain`.
- **7c1** — tests de 7b1 :
  - `tests/test_sfizz_engine.py` (41 tests, sautés sans libsfizz), sur des
    `.sfz` et WAV fabriqués (cosinus à 440 et 660 Hz), sans dépendre des
    instruments téléchargés : contrat (16 emplacements, bibliothèque
    absente), emplacements (`load` refusé pour un slot ou un fichier
    invalide, `unload`, `presets`), sélection et échange d'instance par
    `render`, banque et programme ignorés, même fichier non rechargé,
    fichier remplacé pendant le chargement, **échange périmé écarté par
    le callback** (course entre le fil de chargement et un nouveau choix),
    file d'événements, événements vers un canal sans instance, fichier
    refusé, hauteur (69, 81, 57), note off, bloc plus long que
    `MAX_BLOCK`, canal au repos qui rejoue, gain, une instance par canal,
    volume propre à chaque canal, CC7 et CC10 posés avant la fin du
    chargement puis rejoués, Bend (borné, rejoué), Reset, messages de mode
    non retenus, Program Change sans effet, coupures (d'un canal, pédale
    comprise, toutes), `render_copy`, fermeture.
  - Vérifié en cassant le code : sans le rejeu des CC, ou sans le
    contrôle de génération du callback, un test échoue (le second a
    demandé le test d'échange périmé : le fil de chargement vérifiait
    déjà la génération, ce qui masquait le défaut).
  - `tests/test_app_config.py` (+24) : `sfz_dir` (défaut à côté de
    `projects_dir`, absolu, relatif, invalide), `sfizz_gain` (défaut,
    bornes, invalide), `fluidsynth` / `sfizz` (défaut, false, valeur non
    booléenne = moteur gardé).
  - `tests/test_engine_options.py` (12 tests) : `parse_args`, création
    des deux moteurs, option, clé, option qui prime, bibliothèques
    absentes, `status_cb` par `wx.CallAfter`, **vraie fenêtre principale
    sans les deux moteurs** (message de démarrage, un pad joue).
  - Fakes des 3 tests rouges de 7b1 adaptés (`test_fluidsynth_engine.py`,
    `test_live_take.py`) ; `SPECS.md` (arborescence, table, `engines/`).
  - 3476 verts ; tests du moteur stables sur 8 passages.
- **7d1** — slot Synth SFZ dans le routeur et les exports, conforme à
  Z10, Z11, Z12 :
  - `rack.py` : `InstrumentType.SFZ = "sfz"`, `sfz_file()` ;
    `plays_notes` et `gm_program()` (programme GM deviné du nom ou réglé)
    valent pour un SFZ ; `gm_transpose` non (notes réelles), `gm_gain_db`
    oui.
  - `track_router.py` : `CHAN_TYPES` (BANK, SFZ), `_chan_slot_of`,
    `_engine_of(slot)`, `_track_engine`, `_chan_engines`, `_engine_place`
    (emplacement de banque, ou indice du slot pour un SFZ), `sfz_path`
    (relatif à `sfz_dir`), `_sync_sfz_files` (appelé par
    `sync_bank_files`). `_chan_sel` retient `(type, emplacement, banque,
    programme)`. Toutes les branches Banque passent au slot à canaux et au
    moteur de son slot : notes, grille, KIT / PATCH, Bend, modulation, CC,
    pédale, volume, pan, pan global, chase, `on_play_stop`, coupures
    (`cut_track_notes` coupe le canal dans le bon moteur), All Notes Off,
    Reset, pédale globale, `assign_slot`, `load_slot_preview`,
    `channel_after_slot` (un SFZ garde le canal, 10 compris),
    `program_change` (le SFZ change de canal, pas de son ; pas de
    resélection forcée). `bank_select` retient CC0 / CC32 mais n'envoie
    qu'à une banque. Restent propres à la banque : noms des presets,
    `program_names`, numéro de banque, repli du mode Rack (M5).
    Avertissement de canal partagé : « sur des sons différents » entre
    une banque et un SFZ.
  - `BankPreview` : moteur du slot de préécoute ; `_held` retient
    `(canal, moteur)`.
  - `bank_note(…, engine=None)` (défaut : la banque) ; `render_copy(…,
    sfz_engine=None)` ; `TrackRouter(…, sfz_engine, sfz_dir)` créé par
    `MainWindow`.
  - `audio_export.py` : copie hors temps réel du moteur sfizz, source de
    rendu du mixeur, voix comptées, fermée à la fin.
  - Export MIDI : `_midi_params` met `track_is_bank` vrai pour un SFZ
    (canal qui suit les Program Change, grille au canal 10 en 36 + pad,
    notes de kit telles quelles) ; son programme reste le `gm_program` du
    slot ; nom de piste = nom du slot. `midi_export.py` inchangé (docstring).
  - Éditeur MIDI : la poursuite après l'édition d'un Program Change vaut
    aussi pour une piste SFZ (`mew_editing.py`).
  - Non fait (7f1) : propriétés de piste (Alt+Entrée) et Ctrl+T adaptés
    au SFZ, élément « SFZ » de l'Explorateur.
  - Projet d'essai `/home/com/groovybox/PROJECTS/essai_sfz_7d1.gvp`
    (script dans le scratchpad de la session) : pattern 1 = orchestre
    FluidR3 de `essai_banque_17f1.gvp` (piano canal 1, batterie canal 10,
    cordes canal 3, basse canal 4) ; pattern 2 = même musique sur des
    slots SFZ (piano et basse Discord GM, batterie SamsSonor, violoncelle
    Karoryfer) ; pattern 3 = piano Headroom. Vérifié par un script avec
    une vraie `MainWindow` : chargement, slots et canaux, rendu WAV hors
    temps réel de chaque piste ; à `sfizz_gain` 1.0, RMS des pistes SFZ
    de 0,5 à 1,5 fois celui de FluidR3 selon l'instrument.
  - `pytest` : **30 tests rouges jusqu'à 7e1** : 25 fakes (`TrackRouter`
    sans `__init__` de `test_mix_undo.py` : ni `_rack` ni `sfz_engine` ;
    `_FakeEditRouter` sans `_chan_slot_of` dans
    `test_cc_event_edit_dialog.py`) et 5 tests du défaut de `sfizz_gain`
    (1.0 → 1.5, voir l'essai).
- **Essai de 7d1 (utilisateur, 2026-11-04)** : concluant.
  - **Gain** : à 1.0, les patterns SFZ sont un tout petit peu moins forts
    que le pattern FluidSynth (il faut tendre l'oreille) ; à 1.5, un peu
    plus forts, mais **beaucoup plus agréables et plus clairs** →
    **défaut de `sfizz_gain` porté à 1.5** (`AppConfig`, `SfzEngine.GAIN`).
  - Pas de craquements ; Mute, Solo, volume et pan des pistes SFZ
    concluants ; jeu direct au clavier et aux pads sur une piste SFZ : la
    préécoute suit ; export WAV du pattern 2 fidèle à l'écoute.
  - **Remarque, hors SFZ → 7d2** : un projet ouvert après la lecture d'un
    autre reprend à l'ancienne position de lecture. Comportement attendu :
    après Ctrl+N, Ctrl+O, l'ouverture ou la fermeture de la fenêtre Song,
    la lecture du pattern ou du song repart du début. Cause : la position
    de reprise du lecteur (`_resume_offset`) n'est remise à zéro ni par
    Ctrl+N (qui arrête la lecture), ni par Ctrl+O (qui ne l'arrête même
    pas), ni à l'ouverture de la fenêtre Song (qui arrête le pattern) ; la
    fermeture la remet déjà au début (`_exit_song_mode`).
- **7d2** — imprévu, remarque de l'essai de 7d1 : la lecture repart du
  début après Ctrl+N, Ctrl+O, l'ouverture ou la fermeture de la fenêtre
  Song.
  - Cause précisée : un **arrêt** (`stop_pattern`) efface déjà la
    position, mais une **pause** (`pause_pattern`) la garde dans
    `_resume_offset`, et rien ne l'effaçait au changement de projet ni à
    l'ouverture de la fenêtre Song. Ctrl+O n'arrêtait même pas une
    lecture en cours.
  - `ProjectMixin._rewind_playback` (`ui/mw_project.py`) : `stop_all`,
    voix des synthés coupées, mode Song quitté (`_song_mode`,
    `_song_looping`, `_song_sequence`, `_song_pos` remis à zéro : la
    séquence appartenait à l'ancien projet), `goto_start`. Appelée par
    `_new_project` (Ctrl+N, à la place de son `stop_all`) et par
    `_load_project` (Ctrl+O, après la lecture réussie du fichier).
  - `_open_song_window` : `_song_pos = 0` et `goto_start` à la création
    de la fenêtre. La fermeture (`_exit_song_mode`) remettait déjà au
    début.
  - Vérifié par un script avec une vraie `MainWindow` : pause au pas 20,
    puis Ctrl+N, Ctrl+O, ouverture et fermeture de la fenêtre Song → pas
    0, `_song_pos` 0. `pytest` : toujours les 30 rouges de 7d1 ; tests de
    7d2 en 7e2.
- **Essai de 7d2 (utilisateur, 2026-11-04)** : concluant.
- **7e1** — tests de 7d1 :
  - `tests/test_sfz_slot.py` (40 tests), avec un moteur sfizz factice
    (`FakeSfzEngine`, 16 emplacements, copies de rendu) et les fakes de
    `test_bank_slot.py` (banque, son du kit, minuteries) :
    - Rack : type listé, `plays_notes`, `sfz_file` (espaces, vide, autre
      type), programme GM deviné et réglé, pas de transposition GM, gain
      GM gardé, aller-retour du Rack ;
    - routeur : `sfz_path` (relatif, absolu, sans dossier), moteur de
      chaque slot, `_chan_slot_of`, fichiers des slots retenus, changés
      ou oubliés, fichier introuvable signalé, sélection du canal et
      mixage envoyés au seul sfizz, sélection une fois par canal, sans
      moteur sfizz rien ne joue ;
    - notes : grille en gamme, canal 10 en 36 + pad, fin de note
      programmée, piste muette, KIT / PATCH tels quels, Bend, modulation,
      CC, pédale, CC0 / CC32 retenus sans envoi, volume, pan et pan
      global ; un SFZ garde le canal 10 à l'assignation ;
    - Program Change : la piste change de canal, pas de son ni de pont
      `program % 16` ; poursuite d'un Program Change et d'une modulation ;
      chase et fin de lecture remettent les deux moteurs à zéro ; canal
      partagé banque / SFZ signalé ;
    - coupures : canal de la piste dans le seul sfizz ; `cut_all_notes`,
      All Notes Off, All Sounds Off, Reset, pédale globale : les deux
      moteurs ;
    - préécoute : jeu sur sfizz, note tenue arrêtée sur son moteur après
      un changement de slot de préécoute, Bend et modulation ;
    - mode Rack : le canal N joue le slot SFZ N ; le repli reste une
      banque (M5) ;
    - exports : copie de rendu du routeur, `_Session` de l'export WAV
      (copie de sfizz, source de rendu, voix, fermeture, moteur de
      l'écoute intact), `_midi_params` (piste à canaux, programme GM du
      slot, nom du slot ; preset pour une banque), `build_pattern_midi`
      d'une batterie SFZ au canal 10 ;
    - de bout en bout avec le vrai sfizz (sauté sans libsfizz) :
      `render_pattern` d'une piste SFZ, la 220 Hz attendue.
  - Vérifié sur le code d'avant 7d1 (arbre de travail au commit de
    7c1) : 39 tests sur 40 échouent ; le seul qui passe porte sur
    `build_pattern_midi`, inchangé par 7d1.
  - Les 30 tests rouges de 7d1 corrigés : `test_mix_undo.py` (le
    `TrackRouter` sans `__init__` reçoit un Rack vide, `_track_slots`,
    `rack_mode`, `sfz_engine`), `test_cc_event_edit_dialog.py`
    (`_FakeEditRouter._chan_slot_of`), `test_app_config.py` (défaut de
    `sfizz_gain` à 1.5) ; `SPECS.md`. 3516 verts.
- **7e2** — tests de 7d2 : `tests/test_playback_rewind.py` (8 tests) :
  `_rewind_playback` sur un lecteur factice (arrêt, voix coupées, mode
  Song quitté, début) ; vraie `MainWindow` sans FluidSynth ni sfizz
  (fixture de module) : la pause est gardée sans remise au début (le
  défaut), Ctrl+N, Ctrl+O (`_load_project` d'un projet enregistré dans
  un dossier temporaire ; lecture en cours arrêtée, mode Song quitté),
  ouverture de la fenêtre Song (position et `_song_pos` à zéro), fenêtre
  déjà ouverte (seulement montrée : position gardée), fermeture.
  - Vérifié sur le code de 7d1 (arbre de travail) : les 5 tests du défaut
    échouent ; les 3 autres passaient déjà (pause gardée, fenêtre déjà
    ouverte, fermeture qui remettait au début).
  - Piège retrouvé : dans la suite complète, la `wx.App` de session est
    détruite par des fichiers passés avant (`test_key_manager`,
    `test_midi_export_ui`) → App recréée au besoin et gardée dans le
    module. `SPECS.md`. 3524 verts.

## Phase 8 étape 7a3 — Révision du plan : le Synth SFZ devient une banque de programmes SFZ

### Origine (utilisateur, 2026-11-05, après 7e2)

Utiliser le Program Change avec sfizz pour changer de preset, comme le
fait Keyzone Classic de Bitsonic : plusieurs pianos SFZ dans Sforzando,
avec une liste déroulante qui change le preset, c'est-à-dire le type de
piano et ses réglages de filtres, d'effets… L'utilisateur pensait aux
« fichiers de presets » de l'appli ; mais l'élément « Preset » de
l'Explorateur charge l'ancien format de projet (`PRESETS/preset_01.json`,
tout l'état de l'appli), pas des presets d'instrument.

### État des lieux (2026-11-05, 3524 tests verts)

- **Le mécanisme de Sforzando est le fichier `.bank.xml`** (`AriaBank`),
  présent dans deux instruments téléchargés
  (`karoryfer-bigcat.cello/Karoryfer x bigcat cello.bank.xml`,
  3 programmes ; `karoryfer.big-rusty-drums/Big Rusty Drums.bank.xml`,
  8 programmes) :
  - `<Define name="$sample_dir" value="../Samples"/>` : définition
    passée aux `.sfz` ;
  - `<AriaProgram name="…" gui="…"><AriaElement path="Programs/….sfz"/>
    </AriaProgram>`, dans l'ordre de la liste ; chemins relatifs au
    `.bank.xml` ;
  - `<Key>` (signature de Sforzando) et `gui` : sans objet ici.
- sfizz reçoit les définitions par `sfizz_add_external_definitions` (avant
  le chargement), effacées par `sfizz_clear_external_definitions`.
- La banque GM Discord range un programme GM par fichier, numéroté :
  `Discord GM/Melodic/001-Acoustic Grand Piano.sfz` … ; le violoncelle et
  Big Rusty Drums numérotent aussi leurs programmes (`01- …`, `01-…`).
- Code de 7b1-7d1 : un slot SFZ = un fichier (`config["sfz_file"]`) ;
  `SfzEngine` : emplacement = slot du Rack, `presets` = un seul,
  `program_change` sans effet ; routeur (Z11) : le Program Change d'une
  piste SFZ change son canal, pas son son ; `_bank_key` d'un SFZ =
  `(slot, 0, 0)`.

### Décisions validées (utilisateur, 2026-11-05)

**Z16 — un slot Synth SFZ est une banque de programmes SFZ** (révise Z8,
Z10, Z11). Le programme N est le N-ième `.sfz` de la liste du slot. Comme
pour une banque FluidSynth, **le canal est l'instrument** : un Program
Change (entête à 1.1.1 compris) choisit le programme du canal, la
poursuite le suit, Alt+Entrée affiche la liste des programmes. Un seul
`.sfz` = une banque d'un programme (le 0).

**Z17 — trois sources de programmes** (réponses 1a, 1b, 1c) :
- **(a) un `.bank.xml` de Sforzando** : les `AriaProgram` dans l'ordre,
  nom = attribut `name`, `.sfz` = premier `AriaElement` (chemin relatif au
  `.bank.xml`), `<Define>` passés à sfizz avant le chargement de chaque
  programme ;
- **(b) un dossier** : ses `.sfz` qui ne sont pas des fragments (règle de
  Z6 : ni inclus par un autre `.sfz`, ni avec un `#include` introuvable) ;
- **(c) une liste à nous** : un fichier JSON « banque SFZ », composé dans
  un dialogue, qui peut mélanger des instruments de plusieurs
  bibliothèques.

**Z18 — numéro de programme d'un dossier : le préfixe numérique du nom**
(réponse 2a), sinon l'ordre alphabétique. Préfixe = chiffres en tête du
nom, suivis d'une séparation (`001-Acoustic Grand Piano`, `01- Bowed`) :
numéroté à partir de 1, il donne le programme préfixe − 1 (`001` → 0) ;
si un fichier du dossier porte le préfixe 0, la numérotation part de 0
(préfixe = programme). Les fichiers sans préfixe prennent ensuite les
numéros libres, par ordre alphabétique. Au plus 128 programmes (0..127) ;
au-delà, ignorés avec un message.

**Z19 — préchargement à la poursuite** (réponse 3b) : à chaque poursuite
(démarrage de la lecture, changement de pattern, saut, Undo), le moteur
prépare, pour chaque canal SFZ, une instance par programme que les
Program Change du pattern demanderont, en plus du programme courant. Un
Program Change en lecture bascule alors sans silence. Les instances
préparées qui ne servent plus sont libérées à la poursuite suivante.

### Choix de conception proposés

**Z20 — slot et sources.** `config["sfz_source"]` = chemin d'un `.sfz`,
d'un `.bank.xml`, d'un dossier ou d'une banque SFZ JSON (relatif à
`sfz_dir`, absolu sinon, comme Z10) ; `config["sfz_file"]` de 7d1 est lu
comme `sfz_source` (projets d'essai). Nouveau module `src/sfz_sources.py`,
sans sfizz ni wx (pur, testable, transposable) : `read_source(path)` →
`[(programme, nom, chemin du .sfz, définitions)]`, triée, avec les
messages (programme sans fichier, plus de 128, `.bank.xml` illisible) ;
parcours des fragments partagé avec le dialogue (Z6).

**Z21 — banque SFZ JSON** (Z17 c) : extension `.sfzbank.json`,
`{"name": …, "programs": [{"program": 0, "name": "…", "path": "…"}]}`,
chemins relatifs au fichier (portable) ; enregistrée par défaut dans
`sfz_dir`. Composée dans un dialogue accessible : liste des programmes
(numéro, nom), ajouter un `.sfz` (liste de `sfz_dir`, Z6, ou
Parcourir…), retirer, monter / descendre, renommer (F2), Enregistrer sous.

**Z22 — moteur** (révise Z8) : `SfzEngine.load(slot, source)` lit la
source (Z20) ; `presets(slot)` = `[(0, programme, nom)]` ;
`select(canal, slot, banque, programme)` → le `.sfz` du programme
(banque ignorée ; programme absent : False, comme un preset introuvable
d'une banque) ; `prefetch(canal, slot, programmes)` (Z19) ; instances
d'un canal gardées par chemin de `.sfz` (la courante, les préparées) ;
**une instance remplacée continue de sonner jusqu'à la fin de ses voix**
(un Program Change ne coupe pas les notes en cours, N3), puis rejoint
les préparées ou est libérée. L'état des CC et du Bend du canal est
envoyé à chaque instance qui devient courante (déjà fait en 7b1).

**Z23 — routeur** (révise Z11) : `_bank_key` d'un SFZ = `(slot, 0,
programme du canal)` ; `program_change` d'une piste SFZ change son
instrument (comme une banque) ; `bank_preset_name` et `program_names`
valent pour un SFZ (noms de la source ; MSB / LSB sans objet, grisés) ;
`chase` appelle `prefetch` avec les Program Change de tout le pattern
pour chaque canal joué par une piste SFZ.

**Z24 — propriétés de piste et entêtes** : Alt+Entrée sur une piste SFZ
montre la liste des programmes de la source (en direct, note d'aperçu,
comme D15 / D16) ; l'entête écrit à 1.1.1 est un Program Change (CC0 /
CC32 à 0, comme une banque) ; Ctrl+T comme pour une banque.

**Z25 — export MIDI** (révise Z12) : une piste SFZ s'exporte comme une
piste Banque : ses Program Change sont écrits tels quels (numéro du
programme dans la source, comme Sonar envoie le numéro au module) ;
sans Program Change dans la piste, le programme GM du slot (`gm_program`)
reste écrit en tête. Avec une source GM numérotée (banque Discord), le
`.mid` joue juste dans un lecteur GM.

**Z26 — dialogue du slot** (révise Z15) : la liste montre des
**sources** : chaque `.bank.xml` (« Banque Sforzando — Karoryfer x bigcat
cello (3 programmes) »), chaque dossier d'au moins deux programmes
(« Dossier — Discord GM/Melodic (128 programmes) »), chaque banque
`.sfzbank.json` et chaque `.sfz` seul ; boutons « Parcourir… » et
« Nouvelle banque SFZ… » (Z21).

### Portée exclue

- Plus de 128 programmes par source (Bank Select MSB / LSB pour un
  SFZ) ; plusieurs `AriaElement` par programme (couches) : le premier
  seulement ; l'interface graphique de Sforzando (`gui`, `<Key>`).
- Le reste de la portée exclue de 7a2.

### Découpage révisé (remplace 7f1-7h1 de 7a2)

| Étape | Contenu | Fichiers |
|---|---|---|
| **7a3** | Doc — ce plan. | `docs/DESIGN.md` |
| **7f1** | Implémentation — sources (Z17, Z18, Z20 : `.sfz`, `.bank.xml`, dossier, JSON), moteur à programmes, préchargement et instances en extinction (Z19, Z22), routeur (Z23), export (Z25). Essai à l'écoute : projet d'essai avec Program Change en cours de pattern (banque Discord en dossier, violoncelle en `.bank.xml`). | `src/sfz_sources.py` (nouveau), `src/engines/sfizz_engine.py`, `src/track_router.py`, `src/rack.py`, `src/ui/mw_project.py` |
| **7g1** | Tests — 7f1. | `tests/test_sfz_sources.py` (nouveau), `tests/test_sfizz_engine.py`, `tests/test_sfz_slot.py`, `docs/SPECS.md` |
| **7h1** | Implémentation — Explorateur « SFZ » et dialogue des sources (Z6, Z26), Alt+Entrée et entêtes (Z24), Ctrl+T, messages des moteurs coupés, aide F1. Essai avec Orca. | `src/ui/dialogs_sfz.py` (nouveau), `src/ui/dialogs_simple.py`, `src/ui/mw_pads.py`, `src/ui/mw_tracks.py`, `src/ui/dialogs_properties.py`, `docs/shortcuts.md` |
| **7i1** | Tests — 7h1. | `tests/test_sfz_dialogs.py` (nouveau), `docs/SPECS.md` |
| **7j1** | Implémentation — composition d'une banque SFZ JSON (Z21). Essai avec Orca. | `src/ui/dialogs_sfz.py`, `src/sfz_sources.py` |
| **7k1** | Tests — 7j1. | `tests/test_sfz_dialogs.py`, `tests/test_sfz_sources.py` |
| **7l1** | Doc — clôture (DESIGN, SPECS : Rack, sources SFZ, configuration, `.gvp`, options ; raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 7 — Avancement (7f1)

- **7f1** — banque de programmes SFZ, conforme à Z16-Z20, Z22, Z23, Z25 :
  - `src/sfz_sources.py` (module pur) : `read_source` → `SfzSource`
    (programmes `SfzProgram(numéro, nom, chemin, définitions)` triés,
    messages) pour un `.sfz`, un `.bank.xml` (lu par expressions
    régulières : le fichier commence par `<Key>` avant `<AriaBank>`, deux
    racines que ElementTree refuse ; `<Define name="$x">` passé à sfizz
    **sans le `$`**, comme le stocke son analyseur), un dossier
    (`fragments`, `number_programs` : préfixe à partir de 1 ou de 0,
    numéros libres pour le reste, au plus 128) ou une banque
    `.sfzbank.json` (`write_sfzbank` aussi, chemins relatifs).
    Vérifié sur les instruments téléchargés : `Discord GM/Melodic` =
    128 programmes, de `001-Acoustic Grand Piano` (0) à `128-Gunshot`
    (127) ; `.bank.xml` du violoncelle (3) et de Big Rusty Drums (8) ;
    dossier `Programs` du violoncelle (3, fragments `vc_*_map` écartés).
  - `SfzEngine` réécrit : par canal, une instance courante, des instances
    préparées (`prefetch`) et des instances en extinction ; registre
    `_owned` (clé = fichier et définitions) tenu hors callback sous
    verrou ; le callback seul joue et rend, et reste seul juge de ce
    qu'il tient : une instance qui ne sert plus lui est confiée par
    `EV_DROP`, il la rend par `_freeq` quand elle se tait, libérée hors
    callback. `select` bascule aussitôt sur une instance prête, sinon la
    charge ; à la bascule, l'instance reçoit CC121 puis l'état du canal ;
    l'ancienne finit ses notes (fin de note, CC, Bend et coupures vont
    aussi aux instances en extinction). `release_channel` : canal qui
    n'a plus de piste SFZ, mémoire rendue. `sfizz_add_external_definitions`
    déclarée. Les numéros de génération de 7b1 sont remplacés par la clé
    du programme voulu.
  - Rack : `sfz_source()` (clé `"sfz_source"`, `"sfz_file"` de 7d1 lue de
    même ; `sfz_file` reste un alias).
  - Routeur : `_bank_key` d'un SFZ = `(slot, 0, programme du canal)` ;
    Program Change : resélection pour les deux types ; `bank_preset_name`,
    `program_names`, `_preset_names_of(slot)` (cache par type et
    emplacement) valent pour un SFZ ; `_prefetch_sfz` après la poursuite
    (programmes de tous les Program Change du pattern, par canal ;
    `release_channel` des canaux sans SFZ).
  - Export MIDI : nom de piste = programme SFZ ; Program Change écrits
    tels quels (`midi_export.py` inchangé).
  - Projet d'essai `/home/com/groovybox/PROJECTS/essai_sfz_7f1.gvp`
    (script dans le scratchpad) : pattern 1 = orchestre sur le dossier
    Discord GM (entêtes 0, 48, 33 → piano, cordes, basse GM) et
    SamsSonor ; pattern 2 = Program Change en cours de pattern (piste 1 :
    0 → 4 au pas 9 → 19 à la mesure 2 → 0 ; piste 3 : violoncelle en
    `.bank.xml`, archet → pizzicato à la mesure 2) ; pattern 3 = FluidR3.
    Vérifié par un script (vraie `MainWindow`, rendu WAV) : noms des
    programmes, 3 instances préparées sur le canal 1 du pattern 2,
    aucune au pattern 3.
  - `pytest` : **10 tests rouges jusqu'à 7g1**, qui décrivent l'ancien
    modèle (programme ignoré, numéros de génération, fichier introuvable,
    Program Change sans changement de son, poursuite sans préchargement).
    Un premier passage a donné 11 échecs et un avertissement de plus
    (exception dans un fil ?), non reproduit en 15 passages : à surveiller
    en 7g1.
- **Essai de 7f1 (utilisateur, 2026-11-05)** :
  - changement de programme en cours de lecture **sans silence ni clic** ;
  - piano, cordes et basse GM du dossier Discord : à peu de chose près
    ceux de FluidR3 ;
  - **saturation à l'écoute** : la banque Discord sort environ 10 dB plus
    fort que FluidR3 (RMS du pattern 1 : 0,41 contre 0,12) ; le pattern 1
    sature un peu, le pattern 2 beaucoup, surtout l'orgue d'église (19).
    Cause : le pilote additionne les moteurs puis écrête à ±1 ; l'export
    WAV passe, lui, par le limiteur (Phase 8 étape 1) et ne sature pas.
    Idée de l'utilisateur : baisser le volume de chaque instrument, puis
    remonter le mix (gain staging) → **7f2** : gain par slot SFZ (dB) ;
    un limiteur du mix à l'écoute, chantier à part, à décider à la
    clôture ;
  - noms des programmes dans la liste des pistes : bons ; le préfixe
    numérique n'y est pas nécessaire → ôté en 7f2 **dans les noms des
    pistes seulement** (la liste des programmes et les propriétés de piste
    gardent « 001-Acoustic Grand Piano ») ;
  - export WAV du pattern 2 sans saturation ; export MIDI : changements
    de programme entendus sous timidity.
- **7f2** — imprévu, suites de l'essai de 7f1 :
  - **gain par slot SFZ** : `config["sfz_gain_db"]` (−24..+12 dB, défaut
    0 ; `InstrumentSlot.sfz_gain_db`, `set_sfz_gain_db`), envoyé au
    moteur par `_sync_sfz_files` (`SfzEngine.set_slot_gain`) ; appliqué
    au rendu de chaque instance (`_inst_gain`, lu par le callback ; plutôt
    que `sfizz_set_volume`, pour ne pas appeler sfizz hors du callback),
    celles qui sonnent comprises ; copié par `render_copy`. La clé d'une
    instance inclut maintenant le slot (`(slot, fichier, définitions)`) :
    un même `.sfz` dans deux slots a deux gains. Réglage dans le dialogue
    du slot en 7h1.
  - **noms des pistes** : `sfz_sources.display_name` ôte le préfixe
    numérique (« 001-Acoustic Grand Piano » → « Acoustic Grand Piano » ;
    « 2nd Violin » et « 128 » intacts), dans `_track_label` seulement :
    liste des programmes et propriétés de piste gardent le nom complet.
  - Projet d'essai régénéré avec −10 dB sur le slot Discord : mix du
    pattern 1 RMS 0,142 (crête 0,89), pattern 2 RMS 0,131 (crête 0,95),
    FluidR3 RMS 0,124.
  - `pytest` : **28 tests rouges jusqu'à 7g1** : les 10 de 7f1, et 18
    tests de `test_sfz_slot.py` dont le moteur factice n'a pas
    `set_slot_gain`.
- **Essai de 7f2 (utilisateur, 2026-11-05)** : concluant (plus de
  saturation, noms des pistes sans préfixe).
- **7f3** — imprévu, trouvé en écrivant les tests de 7g1 : une instance
  **courante** abandonnée (`release_channel` : plus aucune piste SFZ sur
  le canal) n'était jamais libérée, faute d'être remplacée : le callback
  ne rendait une instance qu'à la fin d'une extinction ou d'un échange.
  `render` la retire désormais (`_inst[ch] = None`, `_freeq`) dès qu'elle
  est marquée à abandonner et muette ; elle finit d'abord ses notes.
- **7g1** — tests de 7f1, 7f2, 7f3 :
  - `tests/test_sfz_sources.py` (nouveau, 33 tests, sans sfizz) : sorte de
    source, `.sfz` seul, `.bank.xml` (`<Key>` avant `<AriaBank>`,
    `<Define>` sans `$`, programme commenté ignoré, programme sans fichier
    signalé, sans nom, illisible), fragments (inclus, `#include`
    introuvable, en commentaire, à variable), fichiers d'un dossier,
    numérotation (préfixe à partir de 1 ou de 0, numéros libres par ordre
    alphabétique, doublon, hors plage, « 2nd Violin », séparateur exigé,
    plus de 128), banque JSON (aller-retour aux chemins relatifs, entrées
    invalides, illisible, chemin absolu), `display_name`.
  - `tests/test_sfizz_engine.py` (59 tests, +18) : les 5 tests de
    l'ancien modèle réécrits (banque ignorée et programme 0 seul, même
    programme non rechargé, dernier choix gardé pendant un chargement,
    échange périmé ignoré puis abandonné, fermeture) ; source dossier et
    `.bank.xml` (définition `$sample_dir` reçue par sfizz, message d'un
    programme sans fichier), programme absent ou source vide refusés,
    bascule sans chargement vers un programme préparé, programme non
    préparé chargé, **instance remplacée qui sonne encore** (440 Hz et
    989 Hz ensemble), fin de note, pédale et coupure qui l'atteignent,
    instance gardée si le pattern la demande encore (retour sans
    chargement) ou libérée sinon, état du canal envoyé à la nouvelle,
    abandon des préparées, canal libéré (7f3), gain par slot (instances
    qui sonnent, nouvelles, même fichier dans deux slots), copie de rendu.
  - `tests/test_sfz_slot.py` (55 tests, +15) : les 4 tests de l'ancien
    modèle réécrits (message de source, Program Change qui choisit le
    programme et toujours renvoyé, poursuite, nom de piste = programme à
    l'export) ; `sfz_source` et l'ancienne clé, `sfz_gain_db`, gain envoyé
    au moteur, programme du canal, programme absent signalé, noms des
    programmes (mis à jour quand la source change), préchargement à la
    poursuite (programmes de tout le pattern, programme courant, canaux
    suivis, mode Rack), canaux sans SFZ libérés, Program Change d'une
    banque non préchargé, sans moteur ; nom de piste sans préfixe (la
    liste des programmes garde le nom complet), banque inchangée. Moteur
    factice : 3 programmes par source, `set_slot_gain`, `prefetch`,
    `release_channel`.
  - Vérifié en cassant le code : sans préchargement (4 échecs), sans
    `display_name` (1), sans la libération de 7f3 (1).
  - Échec fugace de 7f1 : non revu (suite complète verte trois fois).
  - Deux tests d'abord faux, corrigés : la numérotation d'un dossier
    donne les numéros libres par ordre alphabétique (« 001-b » avant
    « 2nd Violin ») ; une instance remplacée que le pattern ne demande
    plus est libérée, pas gardée. `SPECS.md`. 3590 verts.
- **7h1** — interface, conforme à Z6, Z24, Z26 (et Z7 pour les messages) :
  - `sfz_sources.list_sources(root)` → `SourceEntry` (chemin, sorte, nom,
    nombre de programmes, libellé « chemin relatif — sorte, N
    programmes ») : chaque `.bank.xml`, banque JSON, dossier d'au moins
    deux programmes et `.sfz` qui est un programme ; 201 sources en
    0,14 s sur les instruments téléchargés.
  - **Écart à Z6 (fragments)** : sfizz résout un `#include`, même écrit
    dans un fichier inclus, depuis le dossier du **fichier racine**
    (`mappings/kick_24_map.sfz` inclut `"mappings/kick_24/k_kick.sfz"`,
    relatif à `Programs/`). `fragments` prend chaque `.sfz` comme racine
    et suit la chaîne de ses `#include` depuis son dossier ; seuls ses
    `#include` directs introuvables en font un fragment. Un dossier n'est
    proposé que si ses programmes sont les mêmes, analysé seul ou dans
    toute l'arborescence (un dossier de morceaux inclus depuis ailleurs
    n'est pas une banque).
  - Nom d'une source dossier : « parent — dossier » (`folder_name` :
    « Discord GM — Melodic », « karoryfer-bigcat.cello — Programs »).
  - `ui/dialogs_sfz.py` : `SfzSlotDialog` (liste des sources avec la
    source actuelle présélectionnée et le curseur clavier placé, Gain du
    slot −24..+12 dB, Fichier…, Dossier…, Ok, Annuler ; Entrée ou
    double-clic = Ok ; une source hors de `sfz_dir` est ajoutée en tête),
    `stored_source` (relatif à `sfz_dir`, absolu sinon).
  - Explorateur : élément **« SFZ »** ; `_explorer_sfz` (slot visé de la
    liste, Undo « SFZ slot NN » retiré si Annuler ou inchangé, autres
    réglages d'un slot déjà SFZ gardés, message « Slot 11: SFZ …, N
    programmes, gain … dB (Ctrl+T pour assigner) ») ;
    `_engine_off_note` : « sfizz (ou FluidSynth) désactivé ou absent :
    slot muet » après l'Explorateur (SFZ, Banque) et Ctrl+T.
  - Alt+Entrée : `_bank_info` vaut pour un SFZ (`"sfz"` vrai :
    programmes de la source, MSB / LSB grisés, « sans objet pour un
    SFZ ») ; programme d'origine = celui du canal ; entête écrit à 1.1.1
    et poursuite comme une banque (`_chan_slot_of` pour les autres pistes
    du canal).
  - Aide F1 (`docs/shortcuts.md`) : Alt+X (SFZ), section « Slot Synth
    SFZ », Alt+Entrée sur un SFZ.
  - **Corrections trouvées à l'essai** (intégrées à 7h1) :
    - la note d'aperçu d'Alt+Entrée partait vers FluidSynth
      (`bank_note` sans moteur) : moteur du slot, et sur un SFZ elle
      attend que le programme soit chargé (`_preview_note_when_ready`,
      sondage toutes les 40 ms, au plus 5 s ; aperçu dépassé abandonné) ;
    - un programme pas encore chargé faisait entendre l'ancien :
      `SfzEngine` **retient les notes** jouées pendant le chargement du
      programme voulu (`_pending`, 64 au plus par canal) et les joue à la
      bascule ; une fin de note avant la bascule les annule ; coupure,
      CC120 / CC123, canal libéré ou chargement refusé (`EV_FLUSH`) les
      abandonnent ;
    - **banque GM Discord incomplète** (« Work in progress ») : 118 des
      128 programmes de `Melodic` et 9 des 10 de `Drums` ne sont qu'une
      sinusoïde (`//dummy` puis `<region> sample=*sine`) ; seuls 1, 2, 3,
      5, 26, 34, 45, 46, 105, 112 (et le kit 1) sont de vrais
      instruments. D'où « seuls quelques programmes changent le son », et
      l'« orgue d'église » saturé de 7f1 (une sinusoïde à pleine
      amplitude). `is_placeholder` (commentaires ôtés, le fichier se
      réduit exactement à `<region> sample=*sine`) ; nom montré
      `shown_name` : « 020-Church Organ (Dummy) » (mot choisi par
      l'utilisateur, celui de la banque), dans la liste des programmes et
      le nom de la piste ;
    - Undo d'un slot rempli par l'Explorateur : le Rack était rétabli,
      mais la liste des slots gardait l'ancien libellé (SFZ, Banque, Kit
      ou Patch) : `_restore_state` appelle `_update_slot_list`.
  - `pytest` : **6 tests rouges jusqu'à 7i1** : éléments de
    l'Explorateur (3), nom d'une source dossier (2), fake de Ctrl+T sans
    `_engine_off_note` (1).
- **Essai de 7h1 (utilisateur, 2026-11-05)** : concluant avec Orca
  (Explorateur, slot vide, liste des sources, gain ; Ctrl+T ; source et
  gain présélectionnés au retour ; Alt+Entrée après les corrections ;
  `--no-sfizz` : patterns SFZ muets). Remarques pour plus tard (hors de ce
  chantier) :
  - **mode Clavier par défaut** au chargement d'une banque ou d'un SFZ :
    rien à recalculer pour FluidSynth et sfizz, alors qu'il faut
    aujourd'hui passer en mode Clavier (Ctrl+2) pour jouer ;
  - **audition dans l'Explorateur** : pour chaque banque ou fichier SFZ,
    un court fichier audio (une note de l'instrument, un rythme du kit),
    pour écouter sans charger l'instrument.
- **7i1** — tests de 7h1 :
  - `tests/test_sfz_dialogs.py` (nouveau, 30 tests) : `SfzSlotDialog`
    (sources listées, source actuelle présélectionnée, gain borné,
    première source sans source actuelle, source hors de `sfz_dir` en
    tête, source ajoutée, retrouvée ou sans programme, liste fournie sans
    parcours, `sfz_dir` vide, ordre Tab, `stored_source`) ; Explorateur sur
    une vraie `MainWindow` sans moteurs (slot rempli et nommé « GM —
    Melodic », libellé de la liste, message avec moteur coupé, Undo
    « SFZ slot 11 », Annuler et inchangé retirent l'Undo, programme GM
    gardé, ancienne clé `sfz_file` remplacée, **Undo qui rétablit le
    libellé de la liste**, élément « SFZ » et son aiguillage) ;
    `_engine_off_note` ; `_bank_info` d'un SFZ ; `TrackPropertiesDialog`
    sur un SFZ (libellé, « (Dummy) », MSB / LSB grisés) et sur une banque
    (inchangé) ; note d'aperçu (attend le chargement, abandonnée si un
    autre programme est choisi, jouée au bout de 5 s, aussitôt sur une
    banque, rien sans moteur).
  - `tests/test_sfz_sources.py` (54, +21) : `#include` imbriqués résolus
    depuis le dossier de la racine (cas de big-rusty-drums), `#include`
    imbriqué introuvable sans effet sur la racine, cycle d'inclusions,
    `folder_name`, `list_sources` sur une bibliothèque fabriquée (sortes,
    libellés, ordre, fragments, dossier de morceaux écarté, dossier d'un
    seul programme non proposé), `source_entry`, `is_placeholder` (8 cas,
    dont un vrai oscillateur réglé), `shown_name` et nom de piste.
  - `tests/test_sfizz_engine.py` (70, +11, vrai sfizz) : note jouée
    pendant un chargement (après la bascule, retenue puis jouée, annulée
    par sa fin, abandonnée par coupure, CC120, CC123, canal libéré ou
    chargement refusé, au plus 64, pas de retenue sans programme voulu),
    « (Dummy) » dans `presets`.
  - Les 6 tests rouges de 7h1 corrigés (`test_explorer_dialog.py`,
    `test_track_channels.py` : `_engine_off_note` du vrai `PadMixin`,
    noms de source dossier dans `test_sfz_sources.py` et
    `test_sfizz_engine.py`).
  - Vérifié en remettant l'ancien comportement : liste des slots non
    rafraîchie (1 échec), `#include` résolus depuis l'incluant (1), aperçu
    sans attente (3), sans notes retenues (7), sans détection des factices
    (5).
  - **Écart constaté** : l'ordre Tab réel du dialogue est Sources → Gain →
    Fichier… → Dossier… → **Annuler → Ok** (GTK place Annuler avant Ok
    dans `StdDialogButtonSizer`, comme pour les autres dialogues) ; le test
    vérifie l'ordre des contrôles propres au dialogue.
  - `SPECS.md`. 3652 verts, deux passages.
- **7j1** — composition d'une banque SFZ JSON, conforme à Z21 :
  - `sfz_sources.SfzBankDraft` (pur) : programmes `[numéro, nom, chemin]`
    triés, numéros distincts ; `add` (numéro libre après le dernier, ou
    le numéro demandé s'il est libre ; `None` si 128 pris), `remove`,
    `rename`, `set_number` (échange avec le titulaire du numéro), `move`
    (échange avec le voisin de liste, sinon le numéro adjacent),
    `from_file`, `save`.
  - `write_sfzbank` : **écart** — chemin relatif seulement si la banque
    et le `.sfz` partagent un dossier autre que la racine (une banque
    enregistrée dans `/tmp` ne pointe plus en « ../../home/… »).
  - `ui/dialogs_sfz.SfzBankDialog` : Nom ; Programmes (« numéro - nom —
    fichier », mise à jour ligne par ligne : `SetString` / `Insert` /
    `Delete`, pour Orca) ; Numéro du programme (`SpinCtrl` 1..128,
    échange) ; Monter, Descendre, Renommer…, Retirer ; Fichiers SFZ
    disponibles (les `.sfz` de `list_sources`, Entrée ou double-clic =
    Ajouter) ; Parcourir… ; Enregistrer (fichier demandé la première fois,
    proposé dans `sfz_dir` sous `<nom>.sfzbank.json` ; banque vide
    refusée). Touches sur la liste des programmes : Suppr, F2,
    Alt+Haut / Alt+Bas.
  - `SfzSlotDialog` : boutons « Nouvelle banque SFZ… » et « Modifier la
    banque… » (actif sur une banque SFZ) ; la banque enregistrée est
    sélectionnée, sa ligne mise à jour (`refresh_source`).
  - Aide F1 : boutons du dialogue du slot, section « Composer une banque
    SFZ ».
  - **Correction trouvée à l'essai** (point 6) : une banque modifiée puis
    rechargée sur le même slot n'était pas relue (même chemin, même
    gain : « inchangé » ; et le routeur ne relisait une source que si son
    chemin changeait) ; il fallait un Undo puis un nouveau choix.
    `sfz_sources.source_stamp` (date et taille d'un fichier ; pour un
    dossier, celles de ses `.sfz`) retenu par `SfzEngine.load`,
    `source_stale(slot)` ; `_sync_sfz_files` relit une source dont
    l'empreinte a changé (à chaque synchronisation : lecture, pattern,
    Undo, choix d'un slot) ; l'Explorateur, sur la même source modifiée :
    « Slot 12: SFZ Essai relu, 2 programmes », sans Undo (le Rack ne
    change pas). Vérifié par un script (vraie `MainWindow`). Les instances
    déjà chargées des programmes inchangés restent valables ; un `.sfz`
    modifié lui-même n'est pas rechargé (hors périmètre).
  - `pytest` : **14 tests rouges jusqu'à 7k1** (moteur factice de
    `test_sfz_slot.py` sans `source_stale` : 13 ; ordre Tab du dialogue
    du slot : 1).
- **Essai de 7j1 (utilisateur, 2026-11-05)** : concluant (composition,
  numéros, Alt+Haut / Alt+Bas, F2, Suppr, enregistrement, banque
  sélectionnée, Ctrl+T, Alt+Entrée), sauf le point 6 (banque modifiée non
  relue), corrigé ci-dessus ; essai de la correction concluant.
- **7k1** — tests de 7j1 :
  - `tests/test_sfz_sources.py` (66, +12) : `SfzBankDraft` (numéro après
    le dernier, numéro demandé libre, pris ou invalide, retour au début
    après 127, banque pleine, retrait, renommage, nom vide ignoré,
    `set_number` qui échange et borne, `move` avec voisin ou numéro
    adjacent, `save` et `from_file`, nom par défaut), `write_sfzbank`
    (relatif sous un dossier commun, absolu avec la seule racine),
    `source_stamp` (fichier, dossier : un `.sfz` ajouté compte, un autre
    fichier non ; absent).
  - `tests/test_sfizz_engine.py` (73, +3, vrai sfizz) : `source_stale`
    après une banque réécrite (relue : plus périmée, 2 programmes),
    après un dossier modifié, sans source, copie de rendu.
  - `tests/test_sfz_slot.py` (57, +2) : source périmée relue à la
    synchronisation (rechargée, canal resélectionné, noms rafraîchis),
    source inchangée non rechargée ; moteur factice : `source_stale`.
  - `tests/test_sfz_dialogs.py` (44, +14) : `SfzBankDialog` (seuls les
    `.sfz` proposés, libellés « numéro - nom — fichier », numéro échangé,
    monter, renommer, retirer, Alt+Haut / F2 / Suppr sur la liste des
    programmes et sans effet ailleurs, banque vide refusée, extension
    ajoutée, nom de fichier proposé et nettoyé, modification d'une banque
    existante) ; boutons du dialogue du slot (« Modifier la banque… »
    actif sur une banque SFZ seulement, nouvelle banque ajoutée et
    sélectionnée, banque modifiée : ligne mise à jour sur place,
    composition annulée sans effet) ; Explorateur : même source modifiée
    relue (« Slot 10: SFZ Sax relu, 3 programmes », sans Undo), sinon
    « inchangé » ; ordre Tab avec les deux nouveaux boutons.
  - Vérifié en remettant l'ancien comportement : routeur sans relecture
    (1 échec), Explorateur « inchangé » (1), numéro sans échange (5),
    chemins toujours relatifs (1).
  - `SPECS.md`. 3683 verts, deux passages.

### Clôture (7l1)

**7a1-7k1 FAITS** (commits `f9d1d12` à `63b8453`, et ce commit de
clôture ; 3683 tests verts) : **chantier Phase 8 étape 7 complet**. Le
Rack a un type **Synth SFZ** : une banque de programmes SFZ jouée par
sfizz, que le Program Change parcourt comme une banque FluidSynth ; et
l'appli marche sans FluidSynth ni sfizz.

**Ce que le chantier a livré** :
- **sfizz** (Z1) : bibliothèque compilée et installée dans `~/.local`,
  procédure de A à Z rejouée à blanc (`docs/sfizz_build.md`), outil
  d'essai `tools/sfizz_probe.py` ; liaison ctypes
  (`src/engines/sfizz_engine.py`, interface `BankEngine`), modèle de la
  future liaison C/C++.
- **Moteurs facultatifs** (Z4, Z7, Z14) : clés `"fluidsynth"`, `"sfizz"`
  de `config.json`, options `--no-fluidsynth` / `--no-sfizz` de `main.py` ;
  slots gardés mais muets, messages au démarrage et au choix d'un slot.
- **Moteur** : file d'événements vidée dans le callback, instances par
  canal et par programme, préparées à la poursuite (bascule sans
  silence), en extinction après un Program Change (elles finissent leurs
  notes), abandonnées par `EV_DROP` et libérées hors callback, canal
  libéré ; état des CC rejoué ; notes retenues pendant un chargement ;
  gain global `sfizz_gain` (1.5) et gain par slot ; copie hors temps réel
  pour l'export WAV.
- **Sources** (`src/sfz_sources.py`, pur) : `.sfz`, `.bank.xml` de
  Sforzando (définitions), dossier numéroté par préfixe, banque
  `.sfzbank.json` composée dans l'appli ; fragments résolus comme sfizz
  (depuis le fichier racine) ; programmes factices « (Dummy) » ; liste
  des sources ; empreinte (source modifiée relue).
- **Routeur** : slots à canaux Banque / SFZ, moteur de chaque slot, dans
  tous les chemins (notes, grille, CC, Bend, pédale, mixage, poursuite,
  préchargement, coupures, préécoute, mode Rack, copie de rendu) ;
  exports WAV et MIDI.
- **Interface** : Explorateur « SFZ » (liste des sources, gain, Fichier…,
  Dossier…, Nouvelle banque / Modifier la banque), composition d'une
  banque, Alt+Entrée (programmes de la source, aperçu au chargement),
  nom de piste sans préfixe, aide F1.

**Écarts au plan et imprévus** :
- **7a3** : révision du plan à la demande de l'utilisateur (comme Keyzone
  Classic dans Sforzando) : le Synth SFZ devient une banque de programmes
  (Program Change), au lieu d'un fichier unique au son fixe (Z11 révisé) ;
  découpage 7f1-7l1 au lieu de 7f1-7h1.
- **7d2** : la lecture repart du début après Ctrl+N, Ctrl+O et la
  fenêtre Song (une pause gardait sa position) — hors SFZ, trouvé à
  l'essai.
- **7f2** : gain par slot et noms de pistes sans préfixe (saturation de
  la banque Discord à l'essai) ; **7f3** : instance courante d'un canal
  libéré enfin libérée (trouvé en écrivant les tests).
- Corrections de l'essai de 7h1 : fragments résolus depuis le fichier
  racine, aperçu vers sfizz quand le programme est chargé, notes
  retenues, programmes factices, liste des slots rafraîchie par l'Undo
  (défaut général : SFZ, Banque, Kit, Patch) ; de l'essai de 7j1 : source
  modifiée relue.
- Note d'aperçu dans la liste des sources (Alt+↑, Z15) : non faite, pas
  demandée à l'essai (voir l'audition, plus bas).

**Essais de l'utilisateur** (2026-11-04 et 2026-11-05) : tous concluants
après correction — moteur et options (7b1), écoute comparée à FluidR3 et
gain (7d1), lecture au début (7d2), Program Change sans silence ni clic,
export WAV et MIDI (7f1), saturation corrigée (7f2), Explorateur, Ctrl+T,
Alt+Entrée et `--no-sfizz` avec Orca (7h1), composition d'une banque
(7j1).

**`docs/SPECS.md`** : ligne Phase 8, stack, arborescence (`sfz_sources.py`,
`dialogs_sfz.py`, `sfizz_engine.py`), configuration (`sfz_dir`,
`sfizz_gain`, moteurs facultatifs), type SFZ et structure de son slot,
section « Instruments SFZ », Program Change, exemple de `.gvp`, tests.
**`docs/shortcuts.md`** (aide F1) : Alt+X (SFZ), slot Synth SFZ, composer
une banque, Alt+Entrée sur un SFZ. **`docs/sfizz_build.md`** : lancer
l'appli sans les moteurs.

**Laissé hors périmètre** :
- effets de sfizz (réverbération : Virtual Playing Orchestra la demande),
  réglages de qualité, accordage Scala, keyswitches affichés ;
- plus de 128 programmes par source, plusieurs `AriaElement` par
  programme ; un `.sfz` modifié lui-même n'est pas rechargé (seule la
  liste des programmes est relue) ;
- datation des événements à l'échantillon ; Virtual Playing Orchestra
  (téléchargement manuel : le site refuse les clients automatiques).

**Suites proposées par l'utilisateur** (futurs chantiers) :
- **limiteur du mix à l'écoute** (comme celui de l'export), pour ne
  jamais écrêter quand plusieurs instruments jouent ensemble ;
- **mode Clavier par défaut** au chargement d'une banque ou d'un SFZ
  (rien à recalculer pour FluidSynth et sfizz) ;
- **audition dans l'Explorateur** : un court extrait audio par banque ou
  fichier SFZ (une note, un rythme de kit), pour écouter sans charger.

## Phase 8 étape 8a — Rangement des fichiers audio dans src/audio/, limiteur du mix à l'écoute, volume global jusqu'à 200

### Numérotation des commits de ce chantier

`8a` = ce plan (doc seule). Rangement : `8b1` à `8b5`. Limiteur et
volume : paire `8c1` (implémentation) → `8d1` (tests). Clôture : `8e1`.
`8c2`… pour un commit imprévu. Décisions notées **R1, R2…** (rangement)
et **L1, L2…** (limiteur).

### Origine du besoin (utilisateur)

- **Limiteur** (essais de la Phase 8 étape 7, suite proposée à la
  clôture 7l1) : plusieurs instruments ensemble saturent à l'écoute
  (banque GM Discord, essai de 7f1), alors que l'export WAV, qui a son
  limiteur, ne sature pas. Idée de l'utilisateur : baisser le volume de
  chaque instrument, puis **remonter le volume du mix total** (gain
  staging).
- **Rangement** (2026-11-07) : « comme c'est un petit chantier », ranger
  les fichiers du son et de l'audio dans leur propre dossier, comme les
  fichiers MIDI dans `src/midi/` (Phase 7 étape 3).

### État des lieux constaté en code (2026-11-07, 3683 tests verts)

**Fichiers audio de `src/`** (nombre de fichiers de `src/`, `tests/`,
`tools/` qui les importent) : `sound_device_driver.py` (19 :
`SoundDeviceDriver`, `Mixer`), `pygame_driver.py` (3), `sound_manager.py`
(9), `synth_engine.py` (22), `audio_sampler.py` (2), `audio_tools.py` (3),
`sound_cache.py` (3), `audio_export.py` (6), `sfz_sources.py` (7),
`engines/` (`bank_engine.py`, `fluidsynth_engine.py`, `sfizz_engine.py` ;
12). Dépendances internes : `audio_sampler` → `audio_tools` ;
`sound_manager`, `synth_engine`, `audio_export`, démos des moteurs →
`sound_device_driver` ; `synth_engine` → `audio_sampler`, `sound_cache` ;
`sfizz_engine` → `sfz_sources`, `bank_engine` ; `fluidsynth_engine` →
`bank_engine`. Les démos `python3 -m engines.fluidsynth_engine` et
`engines.sfizz_engine` calculent la racine du projet depuis leur propre
chemin (`sys.path`, `AppConfig`).

**Fichiers à la frontière** : `track_router.py` (routage piste → slot →
moteur, colle entre le séquenceur et l'audio), `voice_manager.py`
(réglages des pads : données), `metronome.py` (logique du click ; son par
`SoundManager`).

**Écoute** : `SoundDeviceDriver._callback` appelle `Mixer.mix(outdata)`
(voix des kits et synthés WAV, sources de rendu FluidSynth et sfizz, puis
`× _master_vol`), puis **écrête net** : `np.clip(outdata, -1, 1)`.

**Export WAV** : `limit_peaks` / `limit_envelope` (`audio_export.py`,
Phase 8 étape 1, W10) : brickwall à **anticipation de 5 ms**, seuil
`PEAK_DB` −0,3 dBFS en crête d'échantillon, stéréo liée, retour
exponentiel de 50 ms (`RELEASE_S`), sur le fichier entier
(`_sliding_min_forward`, `_release` vectorisé par un maximum cumulé en
logarithmes). Le `Mixer` sert aussi au rendu de l'export : le limiteur
d'écoute ne doit pas y entrer.

**Volume global** (0..100, gain linéaire, 100 = ×1), borné à 100 :
`Mixer.set_master_volume`, `DrumPlayer.set_volume` (`dp_live.py` : ignoré
hors de 0..100), SpinCtrl « Volume » de la fenêtre principale,
`_set_master_volume_undo` et `_master_from_dict` (`mw_project.py`),
`AppConfig.master_volume`. Ctrl+Haut / Ctrl+Bas : ±1. L'export reçoit
`master_volume=player.volume`. **Défaut trouvé** : `set_master_volume`
traite toute valeur ≤ 1 comme un rapport (`vol / 100 if vol > 1.0 else
float(vol)`) : un volume global de **1** donne **×1** au lieu de ×0,01.

### Décisions validées (utilisateur, 2026-11-06 et 2026-11-07)

**R1 — paquet `src/audio/`** (singulier, comme `src/midi/`) : les fichiers
audio y passent ; imports en forme pointée (`from audio.synth_engine
import SynthEngine`), plus d'import plat.

**R2 — `engines/` en sous-paquet `src/audio/engines/`** : les moteurs
restent groupés.

**R3 — fichiers frontière laissés en place** : `track_router.py`,
`voice_manager.py`, `metronome.py`.

**R4 — un commit par groupe de fichiers, avec leurs imports dans le code,
les tests et les outils**, suite verte à chaque commit : rangement pur,
sans changement de comportement (exception assumée à la paire impl →
tests).

**L1 — limiteur sans anticipation** : aucune latence ajoutée (le jeu en
direct au clavier et aux pads compte plus). Le gain baisse à
l'échantillon même de la crête ; une brève distorsion reste possible sur
une attaque très franche, sans commune mesure avec l'écrêtage.

**L2 — seuil −0,3 dBFS**, comme l'export.

**L3 — toujours actif**, à la place de l'écrêtage ; clé
`"live_limiter": false` de `config.json` pour le couper (l'écrêtage
revient alors).

**L4 — volume global jusqu'à 200** (×2, +6 dB) : on baisse les
instruments, on remonte le mix, le limiteur rattrape les crêtes.

### Choix de conception proposés

**R5 — ordre des déplacements** (des fichiers sans dépendance audio vers
ceux qui en ont), chaque commit avec `git mv` (historique gardé) :
- `8b1` : `src/audio/__init__.py` (vide, comme `src/midi/`),
  `audio_tools`, `audio_sampler`, `sound_cache`, `sfz_sources` ;
- `8b2` : `sound_device_driver`, `pygame_driver` ;
- `8b3` : `sound_manager`, `synth_engine` ;
- `8b4` : `engines/` → `audio/engines/` (démos : `python3 -m
  audio.engines.sfizz_engine`, racine du projet recalculée) ;
- `8b5` : `audio_export` ; chemins dans la documentation vivante
  (`SPECS.md` : arborescence, sections ; `docs/sfizz_build.md`, aide F1 si
  besoin). L'historique de `DESIGN.md` garde les anciens chemins.
- Chaînes de chemin dans les tests (`monkeypatch.setattr("…")`, `patch(…)`)
  et alias de module (`import track_router as tr_mod`…) suivis.
- Vérification avant chaque commit (piège de la Phase 7 étape 3k) :
  `git status --short` montre `R` **et** les éditions (`RM`), `git diff
  --cached` les contient ; `pytest` complet vert.

**L5 — `src/audio/live_limiter.py`, `LiveLimiter`** (module pur, numpy,
sans wx ni pilote ; prototype, cible C/C++) : `process(block)` traite en
place un bloc float32 `(frames, 2)` et garde son état d'un bloc à l'autre.
- Gain demandé par échantillon : `min(1, seuil / max(|G|, |D|))` (stéréo
  liée).
- Gain appliqué `g[n] = min(demandé[n], 1 − (1 − g[n−1]) · c)`,
  `c = exp(−1 / (0,05 · fréquence))` : attaque immédiate, retour
  exponentiel de 50 ms. Vectorisé par bloc avec l'astuce de `_release`
  (maximum cumulé en logarithmes), l'état `1 − g` du dernier échantillon
  servant de départ au bloc suivant ; un bloc sans crête et sans réduction
  en cours ne coûte qu'un `max`.
- Garantie : aucun échantillon ne dépasse le seuil (`g ≤ demandé`).
- Mesure : `reduction_db` (plus forte réduction depuis la dernière
  lecture), pour les tests et une annonce éventuelle.

**L6 — pilote** : `SoundDeviceDriver(…, limiter=True)` ; `_callback` =
`mix`, puis `limiter.process`, puis `np.clip` de sécurité (sans effet
après le limiteur) ; `set_limiter(on)` pour la clé L3 ; `Mixer.mix`
inchangé (export).

**L7 — volume global 0..200** : bornes portées à 200 partout (pilote,
`SoundManager`, lecteur, SpinCtrl, Undo, `.gvp`, `config.json`, export) ;
gain = volume / 100. `set_master_volume` : un **entier** est un
pourcentage, un **réel** un rapport (corrige le défaut : 1 % = ×0,01). Le
pilote pygame (optionnel) garde son plafond de ×1.

**L8 — annonce** : au-dessus de 100, « Volume Global: 150 (+3,5 dB) »,
pour savoir qu'on amplifie ; « Volume Global: 80 » sinon. Pas
d'indicateur de réduction en direct.

**L9 — export** : il garde son limiteur à anticipation ; avec un volume
global au-dessus de 100, il rattrape aussi les crêtes, et le WAV reste
fidèle à l'écoute.

### Portée exclue

- Déplacer `track_router.py`, `voice_manager.py`, `metronome.py` (R3) ;
  renommer des fichiers ou des classes.
- Anticipation à l'écoute, réglages du limiteur dans l'interface, true
  peak, compresseur ou maximiseur, indicateur de réduction en direct.
- Volume de piste au-delà de 100.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **8a** | Doc — ce plan. | `docs/DESIGN.md` |
| **8b1** | Rangement — `src/audio/`, `audio_tools`, `audio_sampler`, `sound_cache`, `sfz_sources`. | ces fichiers, leurs importeurs (code, tests, outils) |
| **8b2** | Rangement — `sound_device_driver`, `pygame_driver`. | idem |
| **8b3** | Rangement — `sound_manager`, `synth_engine`. | idem |
| **8b4** | Rangement — `engines/` → `audio/engines/`, démos. | idem |
| **8b5** | Rangement — `audio_export` ; chemins de la documentation vivante. | idem, `docs/SPECS.md`, `docs/sfizz_build.md` |
| **8c1** | Implémentation — `LiveLimiter` (L5), pilote (L6), clé `live_limiter` (L3), volume global 0..200 et défaut du volume 1 (L7), annonce (L8). Essai à l'écoute (banque Discord sans gain de slot, volume global 150). | `src/audio/live_limiter.py` (nouveau), `src/audio/sound_device_driver.py`, `src/app_config.py`, `src/audio/sound_manager.py`, `src/player/dp_live.py`, `src/ui/main_window.py`, `src/ui/mw_project.py`, `src/ui/key_handler_ctrl.py`, `src/ui/key_handler_chars.py` |
| **8d1** | Tests — limiteur (seuil jamais dépassé, attaque immédiate, retour de 50 ms, état entre blocs, blocs de tailles diverses, stéréo liée, silence, coupé), pilote, clé, volume 0..200 (pilote, Undo, `.gvp`, config, export), défaut du volume 1. | `tests/test_live_limiter.py` (nouveau), tests existants du volume, `docs/SPECS.md` |
| **8e1** | Doc — clôture (DESIGN, SPECS : volume global, configuration, pilote, arborescence ; raccourcis), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 8 — Avancement (8b1)

- **8b1** — rangement : `src/audio/__init__.py` (vide) ; `git mv` de
  `audio_tools.py`, `audio_sampler.py`, `sound_cache.py`, `sfz_sources.py`
  vers `src/audio/` ; imports pointés dans `src/` (`synth_engine`,
  `engines/sfizz_engine`, `ui/main_window`, `ui/mw_pads`, `ui/mw_tracks`,
  `ui/dialogs_sfz`), les tests et `tools/diag_loop.py`,
  `tools/find_loop_points.py` (`import sound_cache` →
  `from audio import sound_cache`, même objet module pour les
  `monkeypatch`) ; docstrings « File: ». Un import indirect,
  `__import__("audio_sampler")` (`test_synth_engine.py`), échappait au
  motif : trouvé par la suite. 3683 verts, outils lancés.
- **8b2** — rangement : `git mv` de `sound_device_driver.py` et
  `pygame_driver.py` vers `src/audio/` ; 26 lignes d'import pointées
  (`src/` : `synth_engine`, `sound_manager`, `audio_export`,
  `ui/main_window`, démos des deux moteurs ; tests ; `tools/diag_loop.py`,
  `bench_latency.py`, `test_loop.py`), dont `import sound_device_driver`
  → `from audio import sound_device_driver` (`test_mixer.py`) et les
  imports alignés par des espaces ; aucun import indirect. 3683 verts,
  appli et outils importés.
- **8b3** — rangement : `git mv` de `sound_manager.py` et
  `synth_engine.py` vers `src/audio/` ; 32 lignes d'import pointées
  (`src/` : `track_router`, `midi/midi_parser`, `ui/main_window`,
  `ui/mw_project`, `ui/midi_handler_window`, `ui/key_handler_numpad`,
  `ui/midi_editor_dialogs`, `ui/mew_display` ; tests ;
  `tools/diag_loop.py`, `find_loop_points.py`, `test_loop.py`), dont
  `import synth_engine` → `from audio import synth_engine`
  (`test_bend_log.py`) ; les remplacements de `SynthEngine` par les tests
  passent par l'attribut du module `track_router` (inchangés). 3683
  verts, appli et outils importés.
- **8b4** — rangement : `git mv src/engines src/audio/engines`
  (`bank_engine.py`, `fluidsynth_engine.py`, `sfizz_engine.py`,
  `__init__.py`) ; l'ancien dossier, où ne restait que `__pycache__` non
  suivi, est supprimé (sinon Python pouvait encore y voir un paquet
  `engines`) ; 19 lignes d'import pointées (`from engines.x import` →
  `from audio.engines.x import`, `from engines import x` → `from
  audio.engines import x`, alias compris) dans les deux moteurs,
  `ui/main_window` et les tests ; démos : `python3 -m
  audio.engines.sfizz_engine` / `fluidsynth_engine`, `sys.path` remonte
  d'un niveau de plus (trois `dirname`) jusqu'à `src/`, racine du projet
  et `config.json` retrouvés (vérifié ; démos lancées sur un fichier
  absent, sans son). 3683 verts, `tools/sfizz_probe.py` vert.
- **8b5** — rangement : `git mv` de `audio_export.py` vers `src/audio/` ;
  6 lignes d'import (`import audio_export` → `from audio import
  audio_export`, alias `ax` gardé) dans `ui/mw_project` et les tests.
  Documentation vivante : arborescence de `SPECS.md` (sous-arbre `audio/`
  avec `engines/`, avant `midi/`), chemins cités dans `SPECS.md`
  (Instruments SFZ, export WAV), `docs/sfizz_build.md`, docstrings de
  `tools/sfizz_probe.py` et `tests/test_sfz_sources.py` ; l'historique de
  `DESIGN.md` garde les anciens chemins. Contrôle global : plus aucun
  import plat d'un module déplacé. 3683 verts, `check_specs_tests`,
  appli et `sfizz_probe` verts.
- **Rangement terminé (8b1-8b5)** : `src/` ne garde à sa racine que la
  logique du projet (16 fichiers) ; `src/audio/` réunit 9 modules et
  `engines/`. Aucun changement de comportement.
- **8c1** — limiteur et volume global, conformes à L1-L8 :
  - `src/audio/live_limiter.py`, `LiveLimiter` : seuil −0,3 dBFS
    (`THRESHOLD_DB`, visé à ×(1 − 10⁻⁶) pour que l'arrondi en float32 ne
    le dépasse jamais), retour 50 ms, attaque immédiate, stéréo liée ;
    état `1 − gain` gardé d'un bloc à l'autre ; bloc calme sans réduction
    en cours : un seul `max` ; `reduction_db()`, `gain`, `reset()`.
    Vérifié par un script : écart au calcul échantillon par échantillon
    1e-5 sur des blocs de tailles irrégulières, crête de sortie au seuil,
    retour à 1 − (1 − g)/e au bout de 50 ms ; 66 µs par bloc de 512 qui
    limite, 26 µs au repos (budget 11 600 µs).
  - Pilote : `SoundDeviceDriver(…, limiter=True)`, `_callback` = `mix`,
    limiteur, `np.clip` de sécurité ; `set_limiter(on)`, propriété
    `limiter` ; `Mixer.mix` inchangé (export).
  - `set_master_volume` : entier = pourcentage (0..200), réel = rapport
    (0..2) — **défaut corrigé** : un volume de 1 donnait ×1 ;
    `MASTER_MAX = 2.0`.
  - Volume global 0..200 : `SoundManager.set_volume` (pygame plafonné à
    ×1), `DrumPlayer.set_volume` (`VOLUME_MAX`), SpinCtrl de la fenêtre
    principale, `_set_master_volume_undo` et `_master_from_dict`
    (`MASTER_VOLUME_MAX`), `AppConfig.master_volume`.
  - Clé `"live_limiter"` (`AppConfig.live_limiter_enabled`, défaut true)
    passée au pilote par `MainWindow`.
  - Annonce (`ProjectMixin.master_volume_text`) : « Volume Global: 150
    (+3,5 dB) » au-dessus de 100 (champ Volume, `+` / `-`, Ctrl+Haut /
    Ctrl+Bas).
  - Vérifié par un script (vraie `MainWindow`) : limiteur actif, volume
    80 / 150 / 200, 260 borné à 200, **1 → ×0,01**, SpinCtrl jusqu'à 200.
  - `pytest` : **12 tests rouges jusqu'à 8d1** : bornes à 100 des tests du
    volume global (`test_master_mix.py`, `test_sound_device_driver.py`),
    pilotes construits sans `__init__` (sans `_limiter`) dans
    `test_mixer.py` et `test_sound_device_driver.py`, fenêtre factice de
    `test_key_manager.py` sans `master_volume_text`.
- **Essai de 8c1 (utilisateur, 2026-11-07)** : concluant ; « ça marche
  vraiment bien » : volume global poussé jusqu'à 200 (+6 dB) sans aucune
  saturation. **Suite notée** : la clé `live_limiter` ira plus tard dans
  les préférences de l'utilisateur, catégorie Audio (chantier du dialogue
  de configuration, pas commencé).
- **8d1** — tests de 8c1 :
  - `tests/test_live_limiter.py` (nouveau, 46 tests) : constantes égales
    à celles de l'export ; `LiveLimiter` comparé au calcul échantillon par
    échantillon (blocs de 512, de 1, de 4096, de tailles irrégulières),
    seuil jamais dépassé (bruit fort, blocs aléatoires), attaque immédiate
    (échantillons d'avant intacts, crête au seuil), retour de 50 ms
    (1 − (1 − g)/e à τ, e⁻⁵ à 5τ), état identique d'un seul bloc ou en
    morceaux, signal sous le seuil intact au bit près, stéréo liée,
    silence et bloc vide, float32 en place, `reduction_db` et `reset`,
    seuil et retour réglables ; callback du pilote avec limiteur (au
    seuil, pas écrêté) et sans (écrêté à 1), `set_limiter`, limiteur après
    le volume global, `Mixer.mix` de l'export non limité ;
    `set_master_volume` (13 cas : entier = %, réel = rapport, **1 →
    ×0,01**, plafond ×2, entier numpy) ; volume 0..200 de `SoundManager`
    (pygame plafonné à ×1) et du lecteur ; `master_volume_text` ; clés
    `live_limiter` et `master_volume` ; **vraie fenêtre principale** avec
    un pilote factice : la clé arrive au pilote (vraie et fausse),
    SpinCtrl jusqu'à 200 ; `_Session` de l'export à 200 (×2) et à 1,0.
  - Les 12 tests rouges de 8c1 adaptés : `test_master_mix.py` (bornes à
    200 ; `+` au-delà de 100 amplifie, `+` à 200 ne fait rien),
    `test_sound_device_driver.py` (plafond ×2 ; pilotes sans `__init__`
    sans limiteur), `test_mixer.py` (« mix puis écrêtage » sans limiteur),
    `test_key_manager.py` (fenêtre factice avec `MASTER_VOLUME_MAX` et
    `master_volume_text`).
  - Vérifié en cassant le code : callback sans limiteur (2 échecs),
    ancienne règle du volume (4), état non gardé entre blocs (7), plafond
    de l'Undo à 100 (5), annonce sans dB (3).
  - `SPECS.md`. 3730 verts, deux passages.

### Clôture (8e1)

**8a-8d1 FAITS** (commits `0a3764c` à `3c98d02`, et ce commit de
clôture ; 3730 tests verts) : **chantier Phase 8 étape 8 complet**.

**Ce que le chantier a livré** :
- **Rangement** (8b1-8b5) : paquet `src/audio/` (pilotes, `Mixer`,
  `SoundManager`, `SynthEngine`, `AudioSampler`, outils de boucle, cache
  des sons, sources SFZ, export WAV) et `src/audio/engines/` (FluidSynth,
  sfizz) ; imports pointés partout (code, tests, outils), historique gardé
  (`git mv`), aucun changement de comportement, suite verte à chaque
  commit ; `track_router.py`, `voice_manager.py`, `metronome.py` laissés
  en place (R3) ; démos `cd src && python3 -m audio.engines.sfizz_engine`.
- **Limiteur du mix à l'écoute** (8c1) : `LiveLimiter`, sans
  anticipation, −0,3 dBFS, retour 50 ms, stéréo liée, à la place de
  l'écrêtage, dans le seul callback du pilote ; clé `live_limiter`.
- **Volume global jusqu'à 200** (+6 dB) : pilote, lecteur, champ Volume,
  touches, Undo, `.gvp`, `config.json`, export ; annonce en dB au-dessus
  de 100 ; défaut corrigé (un volume de 1 sortait à ×1).

**Écarts au plan et imprévus** :
- le rangement, demandé après le plan initial du limiteur, a été ajouté
  au chantier avant lui (plan 8a commun) ;
- scripts de rangement exécutés sous bash (zsh ne découpe pas les
  variables de liste), à la demande de l'utilisateur ;
- un import indirect (`__import__("audio_sampler")`) échappait à la
  recherche des imports (8b1) ; l'ancien dossier `src/engines/`, réduit à
  son cache, supprimé (8b4) ;
- seuil visé à ×(1 − 10⁻⁶) pour que l'arrondi en float32 ne le dépasse
  jamais (8c1).

**Essai de l'utilisateur** (2026-11-07) : concluant — « ça marche
vraiment bien », volume global poussé jusqu'à 200 (+6 dB) sans aucune
saturation, pas de latence ajoutée au jeu.

**`docs/SPECS.md`** : ligne Phase 8, arborescence (`audio/`), configuration
(`live_limiter`, `master_volume` 0..200), pilote et limiteur d'écoute,
volume global, tests. **`docs/shortcuts.md`** (aide F1) : volume global
0..200 et annonce en dB. **`docs/sfizz_build.md`** : chemins des moteurs.

**Laissé hors périmètre** : anticipation à l'écoute, réglages du limiteur
dans l'interface, true peak, compresseur, indicateur de réduction en
direct, volume de piste au-delà de 100.

**Suite notée** : la clé `live_limiter` (et les autres réglages audio de
`config.json`) dans les **préférences de l'utilisateur**, catégorie
Audio — chantier du dialogue de configuration, pas commencé. Restent
aussi, de la Phase 8 étape 7 : mode Clavier par défaut sur une banque ou
un SFZ, audition dans l'Explorateur.

## Phase 8 étape 9a — Mode Clavier d'office sur une banque ou un Synth SFZ

### Numérotation des commits de ce chantier

`9a` = ce plan (doc seule). Le code commence à `9b1` (implémentation),
puis `9c1` (tests), `9d1` (clôture) ; `9b2`… pour un commit imprévu.
Décisions notées **K1, K2…** (lettre libre dans cette Phase).

### Origine du besoin (utilisateur, essai de la Phase 8 étape 7h1)

Pour jouer un slot Banque ou Synth SFZ au clavier MIDI, il faut d'abord
passer en mode Clavier (Ctrl+2) depuis la fenêtre principale. Avec
FluidSynth et sfizz, il n'y a aucun échantillon à recalculer : le mode
Clavier pourrait être choisi d'office au chargement de la banque.

### État des lieux constaté en code (2026-11-07, 3730 tests verts)

- **Mode d'entrée** : `MainWindow._input_mode` (« pad » ou
  « keyboard », défaut « pad », de session) ; `_set_input_mode(mode)`
  (`main_window.py`), appelé par Ctrl+1 / Ctrl+2 (`key_handler_ctrl.py`)
  et la liste « Mode » (`_on_mode_choice`) ; jamais d'office. En Clavier :
  gamme d'entrée mise à jour, annonce « Mode: Keyboard — major @ C3 », et
  sur un **synthé WAV** pré-calcul de 61 notes transposées (36..96) dans
  un fil — la raison de ne pas passer en Clavier d'office.
- **Effets du mode** sur un slot qui joue des notes : pavé numérique
  (`key_handler_numpad.py` : touches 1-8 = gamme, octave par `+` / `-`, en
  Clavier ; pads en Pad), contrôleur MIDI (`midi_handler_window.on_note_on`
  : notes chromatiques transposées en Clavier, rangées sur les pads en
  Pad), `_play` (autoplay de la grille).
- **Le slot joué (`_cur_slot`) change** à : `_go_to_track` (navigation des
  pistes, `mw_tracks.py`), `_follow_track_slot` (Ctrl+T, mode Rack,
  changement de pattern en mode Rack, Program Change du contrôleur en mode
  Rack, Undo qui change le slot joué), propriétés de piste (slot changé),
  `_load_project` (Ctrl+O, démarrage), import MIDI (`mw_project.py`) ; et
  son **contenu** change par l'Explorateur (Kit, Patch, Banque, SFZ) quand
  il vise le slot joué, ou par un Undo.

### Décisions validées (utilisateur, 2026-11-07)

**K1 — Banque et Synth SFZ → mode Clavier d'office** (rien à calculer) ;
un synthé WAV garde le mode en cours (son pré-calcul reste au choix de
l'utilisateur, Ctrl+2).

**K2 — Kit → mode Pad d'office** (les pads jouent la batterie).

**K3 — une batterie sur une banque ou un SFZ** (piste au canal 10)
**passe aussi en Clavier**, comme les autres instruments de banque.

**K4 — un choix manuel est gardé jusqu'au prochain changement du slot
joué** : Ctrl+1 sur un piano de banque laisse le mode Pad tant qu'on reste
sur ce slot ; le passage d'office ne se refait qu'en arrivant sur un autre
slot, ou quand le contenu du slot joué change de type.

### Choix de conception proposés

**K5 — une seule méthode, `_apply_auto_input_mode()`** (`main_window.py`),
appelée après chaque changement du slot joué ou de son contenu (liste
de l'état des lieux) :
- clé = `(_cur_slot, type du slot)` ; si elle est la même qu'au dernier
  appel, rien (K4) ; sinon elle est retenue, puis la règle s'applique :
  Banque ou SFZ → « keyboard », Kit → « pad », autre (synthé WAV, slot
  vide) → mode inchangé ;
- rien si le mode voulu est déjà le mode en cours ;
- pas de passage d'office pendant l'enregistrement ou le décompte (le
  changement de piste y est déjà refusé).

**K6 — annonce** : le passage d'office complète l'annonce du changement
de slot au lieu de l'effacer : « Piste 3 — Discord GM — Melodic — Mode
Clavier » ; « … — Mode Pad » pour un kit. `_set_input_mode` reçoit un
argument `announce` (vrai par défaut : Ctrl+1 / Ctrl+2 inchangés) ; en
Clavier, la gamme d'entrée est mise à jour comme aujourd'hui (pas de
pré-calcul : seul un synthé WAV en a besoin, K1).

**K7 — démarrage et ouverture d'un projet** : la règle s'applique au slot
joué une fois le projet chargé (projet dont la piste courante est sur une
banque → Clavier d'office).

**K8 — le mode reste de session** (pas sauvegardé dans le `.gvp`), comme
aujourd'hui.

### Portée exclue

- Mode d'office pour les synthés WAV (K1) ; préférence pour couper la
  règle (préférences, catégorie Audio ou Clavier, plus tard).
- Mode différent par piste mémorisé ; mode de l'éditeur MIDI.

### Découpage

| Étape | Contenu | Fichiers |
|---|---|---|
| **9a** | Doc — ce plan. | `docs/DESIGN.md` |
| **9b1** | Implémentation — `_apply_auto_input_mode` (K5), appels aux changements du slot joué et de son contenu, annonce (K6), démarrage et projet (K7). Essai au clavier MIDI et au pavé numérique avec Orca. | `src/ui/main_window.py`, `src/ui/mw_tracks.py`, `src/ui/mw_project.py`, `src/ui/mw_pads.py` |
| **9c1** | Tests — règle (Banque, SFZ, Kit, synthé, vide), choix manuel gardé (K4), contenu du slot changé, chaque appelant, pas pendant l'enregistrement, annonces. | `tests/test_auto_input_mode.py` (nouveau), `docs/SPECS.md` |
| **9d1** | Doc — clôture (DESIGN, SPECS : Modes de jeu ; aide F1), `check_specs_tests`, `pytest` complet, mémoire. | `docs/DESIGN.md`, `docs/SPECS.md`, `docs/shortcuts.md` |

### Phase 8 étape 9 — Avancement (9b1)

- **9b1** — mode d'office, conforme à K1-K8 :
  - `MainWindow._apply_auto_input_mode()` : `AUTO_MODES` (Banque, SFZ →
    « keyboard » ; Kit → « pad »), clé `(_cur_slot, type)` retenue dans
    `_auto_mode_key` (même clé : rien, choix manuel gardé, K4) ; rien
    pendant l'enregistrement ou le décompte ; `_set_input_mode(mode,
    announce=False)` (gamme d'entrée mise à jour, ni annonce ni
    pré-calcul).
  - Appels : `_go_to_track`, `_follow_track_slot`, propriétés de piste
    (slot changé), `_load_project` (K7), import MIDI, `_restore_state`
    (Undo), Explorateur Kit / Patch / Banque / SFZ (la clé ne change que
    si le slot visé est le slot joué).
  - **Annonce (K6), écart trouvé en vérifiant** : la fin d'annonce
    (`MODE_NOTES` : « — Mode Clavier », « — Mode Pad ») est ajoutée à
    **chaque** message de la même action par `_show_status`, et oubliée
    une fois l'action finie (`wx.CallAfter(_flush_mode_note)`, qui
    l'ajoute aussi à la ligne en cours si aucun message n'a suivi) : sur
    une piste de kit, le chargement du kit écrit son message après celui
    de la piste, et une annonce consommée par le premier se perdait.
  - Vérifié par un script (vraie `MainWindow`, `essai_sfz_7f1.gvp`) :
    Clavier à l'ouverture (piste 1 sur SFZ), Pad sur la piste 5 (kit),
    Clavier en revenant, Ctrl+1 gardé sur une autre piste du même slot,
    Clavier sur un autre slot SFZ, rien pendant l'enregistrement.
  - `pytest` : **114 tests rouges jusqu'à 9c1** : 14 classes de fenêtres
    factices (mixins) sans `_apply_auto_input_mode`.
- **Essai de 9b1 (utilisateur, 2026-11-07)** : concluant (Orca, contrôleur
  MIDI). **Remarque → 9b2** : incohérence de hauteur entre le pavé
  numérique et le contrôleur. Sur un kit en mode Pad, le pavé 1 et la
  touche la plus grave du contrôleur (36) jouent tous deux la grosse caisse
  (note 36) ; en mode Clavier sur un synthé, le pavé 1 joue 48 (racine
  d'entrée `_kb_root_midi`, défaut 48) alors que la même touche du
  contrôleur joue 36 (notes jouées telles quelles, transposées seulement
  de `_kb_root_midi − _kb_play_root`, 0 au départ). Choix de
  l'utilisateur (option a) : **le pavé suit le contrôleur** — pavé 1 = 36
  au départ, contrôleur sans transposition, `+` / `-` déplacent les deux ;
  racine des **nouveaux** patterns à 36 pour que la grille d'un synthé
  soit relue à la hauteur jouée (patterns existants inchangés).
- **9b2 (implémentation, imprévue)** : référence commune du pavé et du
  contrôleur en mode Clavier.
  - `MainWindow.KB_INPUT_BASE = 36` (do 2) : le contrôleur est transposé
    de `_kb_root_midi − 36` (`midi_handler_window`, note on et note off),
    donc pas du tout au départ ; `_kb_root_midi` et `_kb_play_root`
    partent de 36 : NumPad1 = touche la plus grave du contrôleur = 36,
    comme le pad 1 d'un kit ; NumPad + / − déplacent les deux.
  - `Pattern()` : `_kb_root_midi = 36` pour un nouveau pattern ; un
    pattern relu garde le sien (`from_dict` : 48 sans clé).
  - **Écart trouvé en vérifiant** : la racine de lecture du clavier
    (`_kb_play_root`, d'où `kb_notes`, qui donne la case de grille d'une
    note du contrôleur) restait fixe ; sur un ancien pattern (48), une
    note enregistrée au contrôleur aurait été rejouée une octave plus
    haut. Nouvelle méthode `_set_kb_play_root(root)` appelée avec la
    racine du pattern joué (`_apply_pattern_from_store`, avancée du
    song) ; l'octave d'entrée n'est pas touchée.
  - Vérifié par un script (vraie `MainWindow`, projet de l'utilisateur à
    48) : NumPad1 → 36, contrôleur 36 → 36 ; après NumPad + : 48 et 48.
  - `pytest` : **119 tests rouges jusqu'à 9c1** : les 114 de 9b1, 4 tests
    de fenêtres factices sans `_set_kb_play_root` (test_rack_mode,
    test_track_channels) et le montage de test_song_export_ui (racine 48
    figée face aux patterns neufs à 36).
- **Essai de 9b2 (utilisateur, 2026-11-07)** : concluant.
- **9c1 (tests)** : `tests/test_auto_input_mode.py` (32 tests).
  - Vraie `MainWindow` (sans FluidSynth ni sfizz), **une seule pour le
    module** : chaque fenêtre ouvre un client du séquenceur ALSA, et une
    par test épuisait la limite (erreurs `MidiInAlsa::initialize` dans la
    suite complète) ; état remis à zéro avant chaque test, MIDI et pilote
    fermés à la fin comme `_on_close`.
  - Règle K1-K3, choix manuel gardé (K4), contenu qui change de type,
    enregistrement et décompte, annonces (K6), appelants
    (`_go_to_track`, refus pendant l'enregistrement, `_follow_track_slot`,
    `_apply_pattern_from_store` → `_set_kb_play_root`).
  - 9b2 : base 36 et état de départ, `Pattern()` à 36 / relu sans clé à
    48, NumPad + / − (vrai `KeyManager`), racine de lecture sans toucher
    l'octave d'entrée ; contrôleur par le vrai `MidiHandler` (fenêtre du
    mode Rack) : touche 36 jouée 36, suit l'octave d'entrée, non
    transposée par la racine de lecture.
  - Vérifié en remettant l'ancien code : l'ancienne transposition du
    contrôleur et l'oubli du choix manuel font échouer des tests.
  - 11 classes de fenêtres factices complétées, dont héritent les autres
    (`_apply_auto_input_mode`,
    `_set_kb_play_root`, et `KB_INPUT_BASE` pour `_RackWin`) ;
    `test_note_cuts` (racine de départ 36, transposition +12) et le
    montage de `test_midi_export_ui` (gamme d'un pattern neuf à 36)
    adaptés.
  - `SPECS.md` (arborescence et table) ; `check_specs_tests` : 93 fichiers.

### Clôture (9d1)

**9a-9c1 FAITS** (commits `3544234` à `670a711`, et ce commit de
clôture ; 3762 tests verts) : **chantier Phase 8 étape 9 complet**.

**Ce que le chantier a livré** :
- **Mode d'office** (9b1, K1-K8) : `_apply_auto_input_mode()` à chaque
  changement du slot joué ou de son contenu ; Banque et Synth SFZ →
  Clavier (batterie au canal 10 comprise), Kit → Pad, synthé WAV et slot
  vide → inchangé ; choix manuel gardé sur le même slot ; rien pendant
  l'enregistrement ou le décompte ; annonce « — Mode Clavier » / « — Mode
  Pad » ajoutée aux messages de l'action ; démarrage et ouverture d'un
  projet.
- **Pavé et contrôleur sur la même octave** (9b2, imprévu, remarque de
  l'essai de 9b1) : `KB_INPUT_BASE = 36` ; NumPad 1 = touche la plus
  grave du contrôleur = do 2, comme le pad 1 d'un kit ; NumPad + / −
  déplacent les deux ; nouveaux patterns à la racine 36, anciens à 48 ;
  racine de lecture du clavier = celle du pattern joué.
- **Tests** (9c1) : `tests/test_auto_input_mode.py`, 32 tests, vraie
  fenêtre principale et vrai `MidiHandler`.

**Écarts au plan et imprévus** :
- l'annonce, consommée par le premier message, se perdait sur une piste
  de kit (le message du chargement du kit suit) : ajoutée à chaque message
  de l'action, oubliée par un `wx.CallAfter` (9b1) ;
- 9b2 tout entier (hauteur du pavé ≠ contrôleur en mode Clavier), et dans
  9b2 la racine de lecture qui doit suivre le pattern (sinon une note
  enregistrée au contrôleur sur un ancien pattern était rejouée une
  octave plus haut) ;
- tests : une seule vraie fenêtre par module, chaque `MainWindow` ouvrant
  un client du séquenceur ALSA (limite atteinte à une trentaine).

**Essais de l'utilisateur** (2026-11-07) : 9b1 concluant (Orca,
contrôleur MIDI), avec la remarque qui a donné 9b2 ; 9b2 concluant.

**`docs/SPECS.md`** : ligne Phase 8, « Modes de jeu » (mode choisi
d'office, référence commune 36, racine de lecture), tests.
**`docs/shortcuts.md`** (aide F1) : mode d'office, NumPad 1 = do 2,
NumPad + / − suivis par le contrôleur.

**Laissé hors périmètre** : mode d'office pour les synthés WAV,
préférence pour couper la règle (futur dialogue des préférences), mode
mémorisé par piste, mode de l'éditeur MIDI ; la case de grille d'une note
jouée au pavé après NumPad + / − (indice de gamme, pas la hauteur jouée),
comportement d'avant ce chantier.

**Suite notée** (Phase 8 étape 7) : audition dans l'Explorateur (un court
extrait audio par banque / SFZ) ; dialogue des préférences (catégorie
Audio : `live_limiter`, gains, moteurs).

---

## Phase 8 étape 10a — Dialogue des Préférences à onglets

### Numérotation des commits de ce chantier

`10a` = ce plan (doc seule). Le code commence à `10b1` (implémentation),
puis `10c1` (tests), etc. ; `10b2`… pour un commit imprévu. Décisions
notées **P1, P2…**.

### Origine du besoin (utilisateur, 2026-10-26, 2026-11-07, 2026-11-10)

Un dialogue des Préférences à onglets, qui écrit la configuration :
Général, Matériel, Audio, Midi, Projet, Raccourcis, Divers.
- Ctrl+Tab / Ctrl+Shift+Tab passent d'un onglet à l'autre ; **le focus
  sur un onglet, Gauche / Droite passent à l'onglet voisin** (comme les
  lecteurs d'écran l'attendent sous Windows et Linux).
- **Alt+Shift+P** ouvre le dialogue **depuis toutes les fenêtres**.
- Les entrées et sorties MIDI choisies ici **remplacent la liste « MIDI: »
  de la fenêtre principale**.
- Les entrées et sorties audio et MIDI choisies ici apparaîtront dans les
  **propriétés des pistes**.
- **Général** : démarrage sur un projet existant ou sur un nouveau
  projet ; case Autoplay (lecture automatique dans l'Explorateur).
- **Matériel** : pilotes de la carte audio, entrées audio, sorties audio,
  boutons « Détecter les périphériques audio » et « Tester les
  périphériques audio » ; entrées MIDI, sorties MIDI, boutons « Détecter
  les périphériques MIDI » et « Tester les périphériques MIDI ». Si la
  bibliothèque FluidSynth est installée, « Synthé FluidSynth » figure dans
  les sorties MIDI et y est proposé par défaut.
- **Audio**, **Midi** : les réglages correspondants de `config.json`.
- **Projet** : chemins des projets de l'appli, des projets de
  l'utilisateur, des banques de l'appli, des banques de l'utilisateur.
- **Raccourcis**, **Divers** : plus tard.

### État des lieux constaté en code (2026-11-10, 3762 tests verts)

- **Configuration** : `AppConfig` (`src/app_config.py`) **lit seulement**
  `data/config.json` (suivi par git, avec des chemins propres à cette
  machine) ; l'appli ne l'écrit jamais (Phase 7 étape 15a1, D3). Lu dans
  `MainWindow.__init__`, `_init_sound`, et les démos des moteurs. Clés :
  - chemins : `media_dir`, `patches_dir`, `samples_dir`, `kits_dir`,
    `presets_dir`, `projects_dir`, `exports_dir`, `sound_cache_dir`,
    `click1_file`, `click2_file`, `soundfonts_dir`, `gm_soundfont`,
    `sfz_dir` ;
  - audio : `live_limiter`, `fluidsynth`, `sfizz`, `fluidsynth_gain`,
    `sfizz_gain`, `master_volume`, `master_pan` ;
  - MIDI : `midi_bank_select`.
- **Sortie audio** : `SoundDeviceDriver` ouvre un `sd.OutputStream` sur
  le **périphérique par défaut** de PortAudio (pas de `device=`), 44 100
  Hz, bloc de 512. Sur cette machine, PortAudio voit les pilotes (« host
  API ») ALSA et OSS ; côté ALSA : `default`, `pipewire`, `pulse`, la
  carte `HDA Intel PCH` (analogique, HDMI)… **Aucune entrée audio**
  utilisée par l'appli : pas de piste audio.
- **Entrée MIDI** : `MidiManager` (python-rtmidi) ouvre **un seul port**
  à la fois. La liste « MIDI: » de la fenêtre principale
  (`_midi_port_list`) : double-clic / Alt+M connecte ou déconnecte le
  port choisi, Alt+Shift+M recharge la liste. Le port **n'est pas ouvert
  au démarrage** ; `open_by_name` / `open_first` existent, jamais appelés.
- **Sortie MIDI** : **aucune**. Les notes vont aux moteurs internes
  (échantillonneur, FluidSynth par ctypes, sfizz), qui sortent sur la
  carte son. Pas de `rtmidi.MidiOut`. FluidSynth est détecté par
  `ctypes.util.find_library("fluidsynth")` (`fluidsynth_engine.py`).
- **Démarrage** : `_resolve_project_path` ouvre
  `PROJECTS/project_01.gvp` (ou l'ancien `preset_01.json`), pas le
  dernier projet ouvert ; aucun « dernier projet » n'est retenu.
- **Autoplay** : `MainWindow._autoplay` (toujours vrai, sans réglage)
  fait entendre le pad en naviguant dans la grille et dans la liste des
  pads. L'**Explorateur** (Alt+X, `ExplorerDialog`) choisit un type puis
  un fichier, **sans audition** (suite notée en Phase 8 étape 7).
- **Propriétés de piste** (`TrackPropertiesDialog`) : slot, canal,
  programme GM, banque, transposition, gain, volume, pan ; ni entrée ni
  sortie.
- **Alt+Shift+P** : libre partout. Fenêtre principale : Alt traité avant
  P (lecture) et Shift+P (pattern aléatoire). Éditeur MIDI et fenêtre
  Songs : à vérifier à l'implémentation, P / Shift+P y étant aussi pris.

### Découpage en étapes (validé, 2026-11-10)

Le cahier des charges touche des parties qui n'existent pas encore :
pistes audio, sorties MIDI externes, audition dans l'Explorateur.
Proposition : une étape par ensemble, chacune avec ses paires
implémentation → tests et ses essais.

- **Étape 10 — le dialogue, l'écriture des préférences, les onglets sans
  matériel** : Général, Audio, Midi, Projet (Raccourcis et Divers
  présents, vides).
- **Étape 11 — onglet Matériel** : pilote et sortie audio (flux rouvert),
  entrée MIDI ouverte au démarrage, liste « MIDI: » retirée de la fenêtre
  principale, sorties MIDI (Synthé FluidSynth, ports externes), boutons
  Détecter et Tester.
- **Étape 12 — entrées et sorties dans les propriétés des pistes** :
  sortie MIDI par piste ; entrée audio quand les pistes audio existeront.

### Commits de l'étape 10 (validé, 2026-11-10)

- **10b1 / 10c1 — configuration** : `AppConfig` lit `preferences.json`
  par-dessus `data/config.json` et écrit les préférences (P1) ; nouvelles
  clés `startup`, `last_project`, `autoplay`, `explorer_autoplay`,
  `app_projects_dir`, `app_banks_dir`, `user_banks_dir` ; défauts
  `banks/sf2` et `banks/sfz` (P8) ; recherche par nom des fichiers
  déplacés (P9).
- **10d1 / 10e1 — le dialogue** : onglets, Gauche / Droite sur l'onglet,
  Ctrl+Tab / Ctrl+Shift+Tab (P4), Alt+Shift+P depuis les trois fenêtres
  (P3), champs de Général, Audio, Midi, Projet (P5-P8), Ok / Annuler /
  Appliquer.
- **10f1 / 10g1 — les effets** : démarrage sur le dernier projet ou un
  nouveau projet, les deux cases Autoplay, l'Explorateur (utilisateur
  puis appli), effet immédiat ou au prochain lancement (P2).
- **10h1 — clôture**.

### Choix de conception proposés (étape 10)

**P1 — fichier des préférences (validé, 2026-11-10)** : les
changements s'écrivent dans un fichier de l'utilisateur,
**`preferences.json`**, rangé dans `~/.config/groovyboxit/` (emplacement validé).
`data/config.json` garde les **valeurs par défaut** (suivi par git,
jamais écrit). `AppConfig` lit les
deux : la clé du fichier utilisateur l'emporte. Le dialogue n'écrit que
les clés qu'il règle et garde celles qu'il ne connaît pas. Écriture
sûre : fichier temporaire, puis renommage.

**P2 — prise d'effet** : immédiate quand c'est simple (Autoplay, chemins
pour le prochain parcours, gains FluidSynth / sfizz, limiteur, banque
MIDI) ; **au prochain lancement** pour les moteurs FluidSynth / sfizz
activés ou coupés (le dialogue le dit en fermant). Volume et pan globaux
par défaut : pour le prochain nouveau projet, comme aujourd'hui.

**P3 — ouverture : Alt+Shift+P** depuis la fenêtre principale,
l'éditeur MIDI et la fenêtre Songs (un seul dialogue, ouvert par la
fenêtre principale, parent = la fenêtre qui a le focus). Aide F1 mise à
jour.

**P4 — onglets** : `wx.Notebook`.
- Le focus sur l'onglet : **Gauche / Droite** passent à l'onglet voisin
  (comportement natif du `GtkNotebook`, à vérifier avec Orca ; géré par
  le dialogue s'il manque).
- **Ctrl+Tab / Ctrl+Shift+Tab** depuis n'importe quel champ : onglet
  suivant / précédent, en boucle, géré par le dialogue (`EVT_CHAR_HOOK`),
  le focus posé sur l'onglet pour qu'Orca l'annonce.
- Tab parcourt l'onglet puis les champs de la page, puis Ok / Annuler /
  Appliquer, en bas du dialogue.

**P5 — Général** :
- liste « Au démarrage » : « Ouvrir le dernier projet » (défaut) /
  « Nouveau projet ». Nouvelle clé `startup` ; le dernier projet ouvert
  ou enregistré est retenu dans la clé `last_project` (écrite par Ctrl+O,
  Ctrl+S, Ctrl+Shift+S). Fichier absent : repli sur le comportement
  actuel ;
- **deux cases Autoplay (validé, 2026-11-10)** :
  - « Autoplay de la grille et des pads » : clé `autoplay` (défaut
    vrai), règle `MainWindow._autoplay`, effet immédiat ;
  - « Autoplay de l'Explorateur » : clé `explorer_autoplay` (défaut
    vrai), gardée dès l'étape 10 ; elle prendra effet avec l'audition de
    l'Explorateur, à construire (suite de la Phase 8 étape 7).

**P6 — Audio** : case « Limiteur à l'écoute » (`live_limiter`), cases
« Moteur FluidSynth » et « Moteur sfizz », gains FluidSynth et sfizz,
volume et pan globaux par défaut. SpinCtrl pour les nombres (gains en
dixièmes).

**P7 — Midi** : « Sélection de banque » (`midi_bank_select` : GS / MMA).

**P8 — Projet (précisé par l'utilisateur, 2026-11-10)** : quatre
chemins, chacun avec un champ texte et un bouton « Parcourir… » :
- **projets de l'appli** : les **démos de patterns livrées avec
  l'installation** (nouvelle clé `app_projects_dir`, défaut
  `<racine de l'appli>/projects`, à créer) ;
- **projets de l'utilisateur** : `projects_dir` (aujourd'hui
  `/home/com/groovybox/PROJECTS`) ;
- **banques de l'appli** et **banques de l'utilisateur** : « banques »
  veut dire **tout** (banques, kits, patchs, SFZ), réunis sous **un
  répertoire parent**, chacun dans son propre sous-répertoire, comme
  aujourd'hui (`/home/com/groovybox/KITS`, `PATCHS`, …). Nouvelles clés
  `app_banks_dir` (défaut `<racine de l'appli>/banks`, à créer) et
  `user_banks_dir` (défaut `/home/com/groovybox`).
- Les sous-répertoires gardent leurs noms ; les clés actuelles
  (`kits_dir`, `patches_dir`, `samples_dir`, `sfz_dir`…) restent
  possibles dans `data/config.json` pour un dossier placé ailleurs, mais
  **absentes, elles se déduisent du parent de l'utilisateur**.
- **Soundfonts et SFZ (validé, 2026-11-10)** : un nouveau dossier
  **`banks`** sous le parent de l'utilisateur les réunit :
  `/home/com/groovybox/banks/sf2` (défaut de `soundfonts_dir`, au lieu du
  dossier système `/usr/share/sounds/sf2`) et
  `/home/com/groovybox/banks/sfz` (défaut de `sfz_dir`, au lieu de
  `/home/com/groovybox/media/sfz`). Kits, patchs, samples restent dans
  `KITS`, `PATCHS`, `SAMPLES`.

**P9 — fichiers déplacés et anciens projets** : les `.gvp` gardent le
chemin absolu des soundfonts et des SFZ (essais 17d1, 17f1, 7d1, 7f1 :
`/usr/share/sounds/sf2/FluidR3_GM.sf2`…). Au chargement, un fichier
introuvable est **recherché par son nom** dans le nouveau dossier
(`banks/sf2`, `banks/sfz`, en gardant le chemin relatif sous l'ancien
dossier pour un SFZ) ; il est ensuite enregistré avec le nouveau chemin.
Le rangement des fichiers se fait à l'essai, avec l'accord de
l'utilisateur : les SFZ **déplacés** de `media/sfz` (1,5 Go), les SF2
**copiés** depuis `/usr/share/sounds/sf2` (fichiers du système, laissés
en place).
- **Explorateur (validé, 2026-11-10)** : il cherche **d'abord dans le
  dossier de l'utilisateur**, puis dans celui de l'appli.

### Questions à trancher avant le code

- ~~Q1~~ : tranchée, fichier utilisateur `preferences.json` (P1).
- ~~Q2~~ : tranchée, trois étapes (10, 11, 12), voir le découpage.
- ~~Q3~~ : tranchée, deux cases Autoplay (P5).
- ~~Q4~~ : tranchée, démos livrées avec l'appli ; banques = tout, sous
  un parent (P8).
- **Q5** (étape 11) : boutons Tester. Sortie audio : un court bip ;
  sortie MIDI : une note de test ; entrée MIDI : la prochaine note reçue
  annoncée ; entrée audio : un niveau.

### Avancement 10b1 (implémentation — configuration)

- **`AppConfig(base_dir, prefs_path=None)`** (`src/app_config.py`) : lit
  `data/config.json` (valeurs par défaut), puis `preferences.json` par
  dessus. Fichier : `prefs_path`, sinon la variable `GROOVYBOXIT_PREFS`,
  sinon `~/.config/groovyboxit/preferences.json`. Fichier absent ou
  illisible : aucune préférence.
- **`save_preferences(values)`** : relit le fichier, applique les clés
  (`None` = clé retirée, retour au défaut), garde les autres, écrit par
  fichier temporaire puis renommage (dossier créé au besoin) ; un fichier
  illisible est gardé en `preferences.json.bak`. `preferences()`,
  `default(key)` pour le dialogue.
- **Nouvelles clés** : `startup` (« last » / « new »), `last_project`,
  `autoplay`, `explorer_autoplay`, `app_projects_dir`
  (`<racine>/projects`), `app_banks_dir` (`<racine>/banks`),
  `user_banks_dir` (parent du dossier des projets).
- **Défauts** : `kits_dir`, `patches_dir`, `samples_dir` absents →
  `KITS`, `PATCHS`, `SAMPLES` sous `user_banks_dir` ; `soundfonts_dir` →
  `banks/sf2`, `sfz_dir` → `banks/sfz` sous `user_banks_dir`.
- **Écart au plan** : tant que `banks/sf2` ou `banks/sfz` n'existe pas,
  l'ancien dossier sert encore (`/usr/share/sounds/sf2`, `media/sfz`) :
  l'appli marche avant le rangement des fichiers.
- **`relocate(path)`** (P9) : un chemin sous un ancien dossier passe au
  même chemin relatif dans le nouveau dossier **dès que le fichier s'y
  trouve, même si l'ancien existe encore** (écart au plan : les SF2 sont
  copiés, les originaux du système restent) ; sinon tel quel s'il existe ;
  sinon le même nom dans `banks/sf2` ou `banks/sfz`.
- **`MainWindow._cfg`** garde la configuration ; `_load_project` appelle
  `_relocate_rack_files()` (fichiers des emplacements de banque, sources
  SFZ absolues) après la lecture du rack. Le nouveau chemin est écrit au
  prochain enregistrement du projet.
- **Tests** : `conftest.py` pointe `GROOVYBOXIT_PREFS` vers un fichier
  temporaire absent (les tests ne lisent jamais les préférences réelles).
  Suite : 3752 verts, **10 rouges jusqu'à 10c1** : les tests des défauts
  de `soundfonts_dir` et `sfz_dir` (`test_app_config.py`) attendent les
  anciens dossiers, et `/home/com/groovybox/banks` existe maintenant.
- Sous-dossiers en minuscules, comme `/usr/share/sounds/` (demande de
  l'utilisateur) : `banks/sf2`, `banks/sfz`.

**Essai 10b1** : ranger les fichiers (SFZ déplacés de `media/sfz` vers
`banks/sfz`, SF2 copiés vers `banks/sf2`), puis ouvrir les projets
d'essai d'une banque (`essai_banque_17d1.gvp`) et d'un SFZ
(`essai_sfz_7d1.gvp`) : ils doivent sonner comme avant.

**Essai 10b1** (utilisateur, 2026-11-10) : concluant (fichiers rangés :
SFZ déplacés dans `banks/sfz`, SF2 copiés dans `banks/sf2`). Le
violoncelle de `essai_sfz_7d1.gvp` est muet, « (preset absent) » : **pas
lié au rangement** (le fichier se charge et joue depuis `banks/sfz`). La
source est un seul `.sfz` (programme 0), et la piste 3 commence par un
Program Change 48 : depuis la Phase 8 étape 7f1 (Z22), le programme
absent ne sonne pas. **Suite notée** (Phase 8 étape 7, après l'étape
10) : une source à un seul programme ignore le numéro du Program Change
et joue son unique programme, comme en 7d1.

### Avancement 10c1 (tests — configuration)

- **`tests/test_preferences.py`** (nouveau, 62 tests) :
  - lecture par-dessus `data/config.json`, fichier absent ou illisible,
    `default()`, emplacement (`prefs_path`, `GROOVYBOXIT_PREFS`,
    `~/.config`), isolation par le `conftest` ;
  - `save_preferences` : dossier créé, instance mise à jour, clés gardées
    et relues avant l'écriture, `None`, `.bak`, pas de fichier temporaire
    laissé, échec d'écriture sans perte, UTF-8 ;
  - clés du dialogue (`startup`, `last_project`, les deux Autoplay),
    dossiers de l'appli et de l'utilisateur, `KITS` / `PATCHS` /
    `SAMPLES`, `banks/sf2` et `banks/sfz` (en minuscules), anciens
    dossiers tant qu'ils manquent ;
  - `relocate` (ancien dossier, copie préférée, nom, `.sf3`, introuvable,
    valeurs invalides) et `_relocate_rack_files` (emplacements de banque,
    sources SFZ absolues, relatives laissées, dictionnaire et liste
    remplacés, pas modifiés en place).
- **`test_app_config.py`** : les 10 tests rouges de 10b1 placent les
  banques de l'utilisateur dans un dossier temporaire (le vrai
  `/home/com/groovybox/banks` existe).
- Mutations vérifiées (copie non préférée ; instance modifiée avant
  l'écriture) : chacune fait échouer un test.
- **`docs/SPECS.md`** : arborescence et table. Suite : 3824 verts.

### Avancement 10d1 (implémentation — le dialogue)

- **`PreferencesDialog(parent, cfg, on_apply, page=0)`**
  (`src/ui/dialogs_preferences.py`, nouveau) : `wx.Notebook` à sept
  onglets (Général, Matériel, Audio, Midi, Projet, Raccourcis, Divers ;
  Matériel, Raccourcis et Divers portent une phrase « à venir »).
  - **Général** : liste « Au démarrage » (Ouvrir le dernier projet /
    Nouveau projet), cases « Autoplay de la grille et des pads » et
    « Autoplay de l'Explorateur ».
  - **Audio** : cases Limiteur à l'écoute, Moteur FluidSynth et Moteur
    sfizz (« au prochain lancement ») ; SpinCtrl des gains en dixièmes
    (0 à 100), volume (0 à 200) et pan (−100 à 100) d'un nouveau projet.
  - **Midi** : liste « Sélection de banque » (GS / MMA).
  - **Projet** : quatre chemins, chacun avec « Parcourir… »
    (`wx.DirDialog`) ; un champ vidé retire la clé (retour au défaut).
  - `values()`, `changes()` (réglages changés depuis l'ouverture ou le
    dernier Appliquer) ; Ok et Appliquer passent `changes()` à
    `on_apply`, rien s'il n'y a aucun changement.
  - **Clavier** (P4) : `EVT_CHAR_HOOK` du dialogue ; Ctrl+Tab /
    Ctrl+Shift+Tab = onglet suivant / précédent en boucle, focus posé sur
    l'onglet ; Gauche / Droite quand le focus est sur l'onglet (géré par
    le dialogue, pas laissé au `GtkNotebook`) ; autres touches laissées
    passer.
- **`ProjectMixin._open_preferences(parent, status)`** et
  **`_apply_preferences(changes, status)`** (`mw_project.py`) : écrit
  `preferences.json`, annonce « Préférences enregistrées (N réglages) »
  ou l'erreur. Les effets sur l'appli en cours viennent en 10f1 (d'ici
  là, l'appli relancée relit les réglages).
- **Alt+Shift+P** : fenêtre principale (`key_handler_alt.py`), éditeur
  MIDI (`mew_keymap.py`) et fenêtre Songs (`song_window.py`), testé avant
  les autres usages de P ; parent et statut de la fenêtre appelante.
- **Aide F1** : Alt+Shift+P sous « Projet ». Suite : 3824 verts (tests en
  10e1).

**Essai 10d1** : Alt+Shift+P depuis les trois fenêtres ; onglets
annoncés par Orca, Gauche / Droite sur l'onglet, Ctrl+Tab /
Ctrl+Shift+Tab depuis un champ ; Tab dans chaque page ; Appliquer puis
Ok écrivent `~/.config/groovyboxit/preferences.json` ; Annuler n'écrit
rien.

**Essai 10d1** (utilisateur, 2026-11-11) : concluant pour les onglets
(annoncés par Orca, Gauche / Droite, Ctrl+Tab / Ctrl+Shift+Tab) et
Alt+Shift+P dans les trois fenêtres ; réglages bien enregistrés.
- **Corrigé (10d1)** : onglet Audio, Orca ne lisait pas les libellés des
  quatre SpinCtrl. Cause : chaque libellé était créé **après** son champ ;
  Orca nomme un champ d'après le texte qui le précède dans l'ordre de
  création (wxGTK ne pose pas de relation « libellé de »). Tous les
  libellés du dialogue sont maintenant créés juste avant leur champ
  (`_labeled`).
- « Au démarrage : Nouveau projet » sans effet au relancement : normal à
  ce stade, l'effet vient en 10f1.

**Recette d'un dialogue de réglages à onglets** (à réutiliser) :
`wx.Notebook` (les onglets sont des « onglets de page » accessibles de
GTK, nom annoncé par Orca) ; `EVT_CHAR_HOOK` du dialogue pour Ctrl+Tab /
Ctrl+Shift+Tab (onglet voisin en boucle, `SetFocus()` sur le notebook
pour l'annonce) et Gauche / Droite quand `FindFocus()` est le notebook ;
toute autre touche `event.Skip()` ; libellé créé avant son champ ;
SpinCtrl pour les nombres.

### Avancement 10e1 (tests — le dialogue)

- **`tests/test_preferences_dialog.py`** (nouveau, 60 tests) :
  - sept onglets dans l'ordre, titre et boutons, page de départ bornée,
    pages « à venir » ;
  - valeurs par défaut et lues dans `preferences.json`, champs affichés,
    bornes des SpinCtrl, gains arrondis au dixième ;
  - `changes()` : rien à l'ouverture, seulement ce qui a bougé, retour à
    la valeur d'origine = rien, champ vidé = `None` ;
  - Appliquer (reste ouvert, nouveau point de départ, rien sans
    changement), Ok (applique puis ferme ; rien de plus après Appliquer ;
    sans `on_apply`), Annuler ;
  - Parcourir… (Ok remplit le champ, Annuler le garde, dialogue détruit) ;
  - onglets au clavier : boucle dans les deux sens, Ctrl+Tab et
    Ctrl+Shift+Tab depuis un champ (focus sur l'onglet), Gauche / Droite
    seulement sur l'onglet, flèches modifiées et autres touches laissées
    passer ;
  - accessibilité : chaque SpinCtrl, liste et champ texte suit son
    libellé (non-régression de l'essai de 10d1) ;
  - `_apply_preferences` (écriture, annonce, erreur, statut fourni),
    `_open_preferences` (parent et statut, dialogue détruit même sur
    erreur) ;
  - Alt+Shift+P : fenêtre principale (vrai `KeyManager`), éditeur MIDI,
    fenêtre Songs ; Alt+P et Ctrl+Alt+Shift+P n'ouvrent rien ; P joue
    toujours dans la fenêtre Songs.
- **Piège de test noté** : `FindWindowById` est une recherche globale (il
  trouvait le bouton Ok d'un dialogue d'un test précédent) ; chercher un
  enfant par `dlg.FindWindow(id)`. `EndModal` se remplace sur la classe,
  pas sur l'objet wx.
- Mutations vérifiées (libellé créé après son champ ; onglets sans
  boucle) : chacune fait échouer des tests.
- **`docs/SPECS.md`** : arborescence et table. Suite : 3884 verts.

### Avancement 10f1 (implémentation — les effets)

- **Démarrage** (`_resolve_project_path`, P5) : « Nouveau projet » → un
  nom libre `noname_NNN.gvp` (rien à charger, patterns neufs) ;
  « Ouvrir le dernier projet » → `last_project` s'il existe ; sinon,
  comme avant, `project_01.gvp`.
- **Dernier projet** (`_remember_project`) : écrit dans `last_project`
  après Ctrl+O, l'Explorateur (Projects), Ctrl+S et Ctrl+Shift+S ;
  seulement un fichier existant, seulement s'il a changé ; erreur
  d'écriture ignorée.
- **Autoplay de la grille et des pads** : `MainWindow._autoplay` lu au
  démarrage. **Autoplay de l'Explorateur** : gardé, sans effet tant que
  l'audition n'existe pas.
- **Explorateur** (`_explorer_dir`, P8) : dossier de l'utilisateur s'il
  existe, sinon celui de l'appli (`app_projects_dir` pour Projects ;
  `KITS`, `PATCHS`, `SAMPLES`, `sf2`, `sfz` sous `app_banks_dir`), sinon
  le dossier personnel. **Écart au plan** : un seul dossier de départ, pas
  une liste réunissant les deux ; à revoir quand l'appli livrera des
  banques. Banques de l'appli rangées directement sous `app_banks_dir`
  (`<racine>/banks/sf2`, pas `banks/banks/sf2`).
- **Effet immédiat** (`_apply_preferences_now`, P2) : Autoplay ; dossiers
  relus (`_refresh_dirs_from_cfg`, aussi `TrackRouter.sfz_dir`) ;
  limiteur (`SoundDeviceDriver.set_limiter`) ; gain FluidSynth
  (`FluidSynthEngine.set_gain`, nouveau : `fluid_synth_set_gain`) ; gain
  sfizz (`SfzEngine.gain`) ; volume et pan d'un nouveau projet. **Au
  prochain lancement**, annoncé : moteurs FluidSynth et sfizz, sélection
  de banque (réglage de FluidSynth posé à sa création) — « Préférences
  enregistrées (3 réglages) ; au prochain lancement : moteur FluidSynth ».
- Vérifié sur une vraie fenêtre principale : démarrage « new »
  (`noname_001.gvp`), « last » (le projet), « last » introuvable
  (`project_01.gvp`) ; Autoplay lu ; limiteur coupé tout de suite.
- Suite : 3866 verts, **18 rouges jusqu'à 10g1** (fenêtres factices sans
  `_explorer_dir` / `_apply_preferences_now` : `test_explorer_actions.py`,
  `test_preferences_dialog.py`).

**Essai 10f1** : « Au démarrage : Nouveau projet », relancer → nouveau
projet ; revenir à « Ouvrir le dernier projet », ouvrir un projet (Ctrl+O),
relancer → ce projet ; décocher l'Autoplay de la grille → la navigation
dans la grille ne joue plus, tout de suite ; changer le gain FluidSynth →
le volume des banques change tout de suite ; décocher le limiteur ;
Explorateur (Alt+X) : dossiers de l'utilisateur.

**Essai 10f1** (utilisateur, 2026-11-11) : concluant. Demande : pouvoir
**annuler** un réglage appliqué (gain FluidSynth porté à 3,6 par
Appliquer, sans retour possible) → avenant à trancher (10f2).

## Phase 8 étape 10f2 — Avenant : bouton « Valeurs par défaut » de l'onglet

**Origine** (essai de 10f1, 2026-11-11) : un réglage appliqué (gain
FluidSynth à 3,6) ne pouvait pas être défait.

**Décision de l'utilisateur** : pour l'instant, un bouton « Valeurs par
défaut » sur l'onglet courant suffit.

**Noté, pas nécessaire pour le moment** — plan du Ctrl+Z dans le
dialogue : le dialogue garde la liste de ses Appliquer ; Ctrl+Z revient
sur le dernier (réglage rétabli tout de suite) ; Annuler après des
Appliquer remet tout comme à l'ouverture. Hors de l'historique du projet
(qui est vidé par Ctrl+O et marquerait le projet modifié).

**Avancement 10f2** :
- `AppConfig.defaults_only()` : la configuration sans les préférences
  (`data/config.json` et défauts du code).
- `PreferencesDialog` : bouton « Valeurs par défaut », créé en dernier au
  bas des onglets Général, Audio, Midi et Projet (dernier arrêt de Tab
  dans la page ; nom « Valeurs par défaut — onglet Audio »).
  `restore_defaults(onglet)` remet les champs de cet onglet seulement,
  **sans appliquer** : Ok ou Appliquer ensuite, Annuler pour renoncer.
  `values_of(cfg)`, `show_values(vals)`, `TAB_KEYS`.
- À l'application, un réglage égal à sa valeur par défaut est passé à
  `None` : la clé quitte `preferences.json`, qui ne garde que les écarts.
- Suite : 5 rouges dans `test_preferences_dialog.py` jusqu'à 10g1 (les 4
  de 10f1, et l'onglet Projet qui compte un bouton de plus), 14 dans
  `test_explorer_actions.py`.

**Essai 10f2** : onglet Audio, « Valeurs par défaut » puis Appliquer →
gain FluidSynth à 4 (0,4), le volume des banques revient tout de suite ;
les autres onglets gardent leurs réglages.

**Essai 10f2** (utilisateur, 2026-11-11) : concluant.

### Avancement 10g1 (tests — les effets)

- **`tests/test_preferences_effects.py`** (nouveau, 44 tests) :
  - démarrage : « Nouveau projet » (nom libre, rien à charger), dernier
    projet, dernier projet introuvable ou dossier → `project_01.gvp`,
    sans préférence (ancien `preset_01.json`), sans configuration ;
  - dernier projet : chemin absolu, fichier absent, inchangé (pas
    d'écriture), erreur ignorée ; retenu après le chargement par Ctrl+O
    et l'Explorateur, après l'écriture par Ctrl+S, pas après un échec ;
  - Explorateur : dossier de l'utilisateur, banques ou projets de
    l'appli, dossier personnel, sans configuration ;
  - effet immédiat : Autoplay, limiteur, gains (moteurs absents compris),
    réglages non touchés pas réappliqués, volume / pan d'un nouveau
    projet, dossiers (`KITS`, `PATCHS`, `SAMPLES`, `EXPORTS`, `banks/sfz`,
    `TrackRouter.sfz_dir`) ; au prochain lancement : moteurs et sélection
    de banque, annoncés ; rien d'appliqué si l'écriture échoue ;
  - `FluidSynthEngine.set_gain` (vraie bibliothèque, bornes) ;
  - « Valeurs par défaut » : `defaults_only`, bouton sur les quatre
    onglets réglables, onglet seul, rien d'appliqué tout seul, clé retirée
    (`None`), valeurs de `config.json`, chemins, clic du bouton ;
  - vraie fenêtre principale (une seule) : démarrage « Nouveau projet »,
    Autoplay lu, limiteur coupé par `_apply_preferences`.
- **19 tests rouges de 10f1 / 10f2 corrigés** : `_explorer_dir` (vraie
  méthode) et `_remember_project` dans la `FakeWindow` de
  `test_explorer_actions.py` ; `_apply_preferences_now` dans l'hôte de
  `test_preferences_dialog.py` ; bouton « Valeurs par défaut » compté sur
  l'onglet Projet.
- Mutations vérifiées (« Nouveau projet » ignoré ; valeur par défaut
  écrite au lieu d'être retirée) : chacune fait échouer des tests.
- **`docs/SPECS.md`** : arborescence et table. Suite : 3928 verts.

### Clôture de l'étape 10 (10h1)

**Bilan** (Phase 8 étapes 10a à 10g1, 2026-11-10 / 11, 3928 tests verts) :
dialogue des Préférences à onglets ouvert par Alt+Shift+P depuis les
trois fenêtres ; réglages de l'utilisateur dans
`~/.config/groovyboxit/preferences.json`, par-dessus `data/config.json`
(valeurs par défaut, jamais écrit) ; onglets Général (démarrage,
deux Autoplay), Audio, Midi, Projet (projets et banques de l'appli et de
l'utilisateur) ; effet immédiat ou annoncé au prochain lancement ; bouton
« Valeurs par défaut » de l'onglet ; soundfonts et SFZ rangés dans
`/home/com/groovybox/banks/sf2` et `banks/sfz`, anciens projets
retrouvés.

**Commits** : 10a (plan), 10b1 / 10c1 (configuration), 10d1 / 10e1 (le
dialogue), 10f1 (effets), 10f2 (avenant : Valeurs par défaut), 10g1
(tests des effets), 10h1 (clôture).

**Écarts au plan et imprévus** :
- anciens dossiers gardés tant que `banks/sf2` / `banks/sfz` manquent ;
  une copie dans le nouveau dossier l'emporte sur l'original (10b1) ;
- sous-dossiers en minuscules, comme `/usr/share/sounds/` (10b1) ;
- libellés créés avant leur champ, sinon Orca ne les lit pas (10d1) ;
- l'Explorateur part d'un seul dossier (utilisateur, sinon appli), pas
  d'une liste réunie (10f1) ;
- sélection de banque prise au prochain lancement (réglage posé à la
  création de FluidSynth) (10f1) ;
- avenant 10f2 (Valeurs par défaut), demandé à l'essai de 10f1.

**Essais de l'utilisateur** : 10b1 (rangement des fichiers), 10d1
(onglets et Orca ; libellés de l'onglet Audio corrigés), 10f1, 10f2 :
concluants.

**`docs/SPECS.md`** : ligne Phase 8, « Configuration et Préférences »
(deux fichiers, dialogue, tableau des réglages, dossiers des banques,
fichiers déplacés), arborescence, tableau des dialogues, tests.
**`docs/shortcuts.md`** (aide F1) : Alt+Shift+P (10d1).

**Recette réutilisable** : dialogue de réglages à onglets accessible
(§ Essai 10d1).

**Suites notées** :
- **étape 11 — onglet Matériel** (plan 11a, boutons Tester à trancher) ;
- **étape 12 — entrées et sorties dans les propriétés des pistes** ;
- Ctrl+Z dans le dialogue des Préférences (plan noté en 10f2, pas
  nécessaire pour le moment) ;
- audition dans l'Explorateur (case déjà prête) ; liste réunie de
  l'appli et de l'utilisateur quand l'appli livrera des banques ;
- source SFZ à un seul programme qui ignore le numéro du Program Change
  (essai de 10b1, Phase 8 étape 7).

---

## Phase 8 étape 11a — Onglet Matériel des Préférences

### Numérotation des commits de ce chantier

`11a` = ce plan (doc seule). Le code commence à `11b1` ; paires
implémentation → tests, `11b2`… pour un commit imprévu. Décisions notées
**H1, H2…**.

### Origine du besoin (cahier des charges du 2026-11-10)

Onglet **Matériel** : pilotes de la carte audio ; entrées et sorties
audio, puis boutons « Détecter les périphériques audio » et « Tester les
périphériques audio » ; entrées et sorties MIDI, puis boutons « Détecter
les périphériques MIDI » et « Tester les périphériques MIDI » ; si
FluidSynth est installé, « Synthé FluidSynth » parmi les sorties MIDI,
proposé par défaut. Les listes MIDI **remplacent la liste « MIDI: » de la
fenêtre principale**.

### État des lieux constaté en code (2026-11-11, 3928 tests verts)

- **PortAudio** (V19.6.0, par sounddevice) voit deux pilotes (« host
  API ») : **ALSA** (16 périphériques : `default`, `pipewire`, `pulse`,
  la carte `HDA Intel PCH` analogique et HDMI…) et **OSS** (`/dev/dsp`,
  entrée seule). Ni JACK ni PulseAudio comme pilotes PortAudio (pas
  compilés) : PipeWire et Pulse passent par des périphériques ALSA.
  Défaut : `default` (ALSA) en entrée et en sortie.
- **Sortie audio** : `SoundDeviceDriver` ouvre un seul `sd.OutputStream`
  au démarrage, sur le périphérique par défaut (pas de `device=`), 44 100
  Hz, bloc de 512 ; `close()` l'arrête. Aucun moyen de changer de
  périphérique en cours de route. La liste des périphériques de
  PortAudio est **figée à son initialisation** : une carte branchée après
  le lancement n'apparaît qu'après une réinitialisation de PortAudio, qui
  coupe le flux ouvert.
- **Entrée audio** : aucune (pas de piste audio).
- **Entrée MIDI** : `MidiManager` (python-rtmidi) ouvre **un seul port**,
  par indice (`open`) ; `open_by_name` / `open_first` existent, jamais
  appelés ; **pas d'ouverture au démarrage**. La liste des ports
  (`get_ports`) est relue à chaque appel. Fenêtre principale : liste
  « MIDI: » (`_midi_port_list`), double-clic et Alt+M = connecter /
  déconnecter le port choisi, Alt+Shift+M = relire la liste. 26 usages
  dans `src/` et `tests/` (`main_window`, `midi_handler_window`,
  `key_manager`, `key_handler_navigation`, quatre fichiers de tests).
- **Sortie MIDI** : **aucune** ; les notes vont aux moteurs internes.
  rtmidi voit ici une seule sortie, `Midi Through`. FluidSynth est le
  moteur interne des slots Banque (`fluidsynth_available()`).

### Choix de conception proposés

**H1 — clés de `preferences.json`** (par **nom**, les numéros de
PortAudio et de rtmidi changent d'un lancement à l'autre) :
`audio_hostapi` (« ALSA »), `audio_output`, `audio_input` (nom du
périphérique, vide = défaut du pilote), `midi_input` (nom du port, vide
= aucun), `midi_output` (« Synthé FluidSynth » par défaut si la
bibliothèque est là, sinon le premier port, sinon aucun).

**H2 — sortie audio : effet immédiat**, le flux est rouvert sur le
périphérique choisi (`SoundDeviceDriver.set_device`) : arrêt, nouveau
`OutputStream(device=…)`, voix et sources de rendu gardées ; échec
(périphérique occupé, absent) → retour au précédent et annonce. Au
démarrage : le périphérique enregistré, ou le défaut s'il n'est plus là
(annoncé).

**H3 — pilote** : la liste « Pilote » (ALSA, OSS…) filtre les listes des
périphériques ; changer de pilote propose son périphérique par défaut.

**H4 — entrée audio** : choix enregistré seulement (aucune piste audio
ne l'utilise encore ; servira aux pistes audio, étape 12 et au-delà).

**H5 — « Détecter les périphériques audio »** : réinitialise PortAudio
pour voir une carte branchée depuis le lancement ; le flux est arrêté le
temps de la relecture, puis rouvert (un court silence). Les listes sont
relues, le choix gardé s'il existe encore ; annonce du nombre de
périphériques.

**H6 — entrée MIDI** : le port choisi est ouvert **au démarrage** par
son nom, et tout de suite quand on le change ; port absent → annoncé,
rien d'ouvert. Alt+M garde son rôle (connecter / déconnecter ce port).

**H7 — liste « MIDI: » retirée de la fenêtre principale** ; Alt+Shift+M
ouvre les Préférences **sur l'onglet Matériel** (au lieu de relire la
liste) ; le double-clic disparaît avec la liste.

**H8 — sorties MIDI** : « Synthé FluidSynth » (si la bibliothèque est
là), puis les ports de sortie de rtmidi. À l'étape 11, le choix est
enregistré et testable ; **l'envoi réel des pistes vers un port externe
vient à l'étape 12** (sortie par piste, la sortie choisie ici servant de
défaut).

**H9 — « Détecter les périphériques MIDI »** : relit les ports d'entrée
et de sortie (rtmidi les relit sans rien couper), choix gardés s'ils
existent encore ; annonce.

**H10 — « Tester »** (proposition, à trancher, Q2) :
- **audio** : un court bip (440 Hz, 0,3 s) sur la sortie choisie ; puis,
  si une entrée est choisie, une seconde d'écoute et le niveau mesuré
  annoncé (« Entrée : crête −18 dB ») ;
- **MIDI** : une note (do 3, 0,5 s) sur la sortie choisie (FluidSynth :
  le premier slot Banque, ou le programme 1 de la soundfont par défaut ;
  port externe : note on / note off par `rtmidi.MidiOut`) ; puis, pendant
  5 secondes, la prochaine note reçue sur l'entrée choisie est annoncée
  (« Entrée MIDI : note do 3, vélocité 90 ») ;
- **résultat** affiché dans un champ en lecture seule « Résultat du
  test » au bas de l'onglet, qui prend le focus pour qu'Orca le lise.

**H11 — accessibilité** : listes déroulantes (`wx.Choice`) pour les
pilotes et les périphériques, libellé créé avant chaque liste (recette
de 10d1) ; ordre de Tab : Pilote, Sortie audio, Entrée audio, Détecter
audio, Tester audio, Entrée MIDI, Sortie MIDI, Détecter MIDI, Tester
MIDI, Résultat, Valeurs par défaut.

### Découpage proposé

- **11b1 / 11c1 — audio** : `src/audio/audio_devices.py` (pilotes et
  périphériques par nom, défaut, relecture de PortAudio, bip, mesure
  d'entrée), `SoundDeviceDriver.set_device`, clés, sortie ouverte au
  démarrage.
- **11d1 / 11e1 — MIDI** : ports d'entrée et de sortie par nom, entrée
  ouverte au démarrage et au changement, sorties (Synthé FluidSynth,
  ports), note de test, écoute de la prochaine note.
- **11f1 / 11g1 — l'onglet et la fenêtre principale** : onglet Matériel
  (H11), boutons, champ Résultat, effets (H2, H6) ; liste « MIDI: »
  retirée, Alt+M, Alt+Shift+M ; aide F1.
- **11h1 — clôture**.

### Décisions de l'utilisateur (2026-11-11) — révisent H1, H6, H7, H10, H11

**H12 — plusieurs entrées et sorties à la fois, audio comme MIDI**
(réponse à Q1, qui révise H1 et H6) : chaque liste est une **liste à
cases à cocher** ; les périphériques cochés sont ceux que l'appli
**ouvre au démarrage** et met à disposition des pistes. À l'étape 12,
l'entrée ou la sortie d'une piste se choisira dans ses propriétés
**parmi les périphériques cochés**, sans revenir aux Préférences ; au
démarrage, les pistes retrouvent directement leurs entrées et sorties.
Clés (par nom) : `audio_inputs`, `audio_outputs`, `midi_inputs`,
`midi_outputs` (listes).
- **Entrées MIDI** : tous les ports cochés écoutés ensemble (un
  `rtmidi.MidiIn` par port ; les messages vont au même gestionnaire).
- **Sorties audio** : le mix de l'appli va à **la sortie principale**
  (première sortie cochée, réglable : à préciser, Q5) ; les autres sont
  prêtes pour les pistes de l'étape 12.
- **Sorties MIDI** : « Synthé FluidSynth » coché par défaut s'il est
  installé ; les ports externes cochés sont ouverts pour l'étape 12.
- **Entrées audio** : cochées et enregistrées ; aucune piste audio ne
  les utilise encore.

**H13 — ordre des listes** (révise H11) : **Entrées audio, Sorties
audio, Entrées MIDI, Sorties MIDI**, chacune précédée de son libellé et
suivie de ses boutons ; pilote audio en tête.

**H14 — Tester** (révise H10) : agit sur **la ligne sélectionnée** de la
liste (cochée ou non) :
- **sortie audio** : un **La 440 Hz d'une seconde** envoyé à la carte ;
- **sortie MIDI** : un **A4 (note 69) d'une seconde** ;
- entrées : niveau d'une seconde d'écoute (audio), prochaine note reçue
  pendant 5 secondes (MIDI) — proposition gardée, à confirmer (Q6).

**H15 — Shift+F12 = reconnecter tous les périphériques MIDI** (révise
H7), à côté de Ctrl+F12 (Panic) : relit les ports et rouvre toutes les
entrées et sorties MIDI cochées (après un débranchement, par exemple) ;
annonce du résultat. **Remplace Alt+Shift+M**. Disponible dans toutes
les fenêtres (`handle_transport`, comme Ctrl+F12). Alt+M garde son rôle :
connecter / déconnecter les entrées MIDI cochées. La liste « MIDI: » de
la fenêtre principale est retirée.

### Questions tranchées (utilisateur, 2026-11-11)

- **Q5 → H16 — liste « Sortie principale »** à part, sous la liste des
  sorties audio : elle propose les sorties cochées ; le mix de l'appli y
  va (flux rouvert tout de suite, H2). Clé `audio_main_output`. Sortie
  principale décochée → la première sortie cochée la remplace (annoncé) ;
  aucune sortie cochée → le défaut du pilote.
- **Q6 → H17 — résultat dans un champ** « Résultat du test » en lecture
  seule au bas de l'onglet, qui prend le focus pour qu'Orca le lise.
  Tests des entrées gardés comme proposé (H14).
- **Q4 → H8 confirmé** : sortie MIDI externe ouverte et testable à
  l'étape 11 ; envoi réel des pistes à l'étape 12.
- Reste à vérifier à l'essai : `wx.CheckListBox` lu par Orca avec l'état
  de chaque case (Espace pour cocher).

### Découpage (révisé)

- **11b1 / 11c1 — audio** : `src/audio/audio_devices.py` (pilotes et
  périphériques par nom, défaut, relecture de PortAudio, La 440 Hz d'une
  seconde, niveau d'une entrée) ; `SoundDeviceDriver.set_device` ; clés
  `audio_hostapi`, `audio_inputs`, `audio_outputs`,
  `audio_main_output` ; sortie principale ouverte au démarrage.
- **11d1 / 11e1 — MIDI** : plusieurs entrées ouvertes ensemble
  (`MidiManager`), sorties (Synthé FluidSynth, ports par
  `rtmidi.MidiOut`), A4 d'une seconde, écoute de la prochaine note ;
  ouverture au démarrage ; Shift+F12 (reconnecter), Alt+M (toutes les
  entrées cochées).
- **11f1 / 11g1 — l'onglet et la fenêtre principale** : onglet Matériel
  (H13 : pilote, quatre listes à cases, Sortie principale, boutons,
  Résultat, Valeurs par défaut), effets ; liste « MIDI: » retirée,
  Alt+Shift+M retiré ; aide F1.
- **11h1 — clôture**.

### Avancement 11b1 (implémentation — audio)

- **`src/devices/audio_device.py`** (nouveau ; paquet autonome `src/devices/`, voir plus bas) : `hostapis()`,
  `default_hostapi()`, `devices(pilote, "input" | "output")`,
  `default_device`, `find_device(nom, pilote, sens)` (par nom),
  `resolve_output(sortie principale, pilote)` (indice ou défaut, avec
  l'annonce d'une sortie absente), `rescan()` (réinitialise PortAudio),
  `tone()` (La 440 Hz d'une seconde, −10 dBFS, fondus de 10 ms),
  `play_tone(device)`, `input_peak_db(device)` (une seconde d'écoute,
  crête en dBFS), `format_db`, `AudioDeviceError`.
- **`SoundDeviceDriver`** : argument `device` ; `device`,
  `start_stream()`, `stop_stream()` (voix et sources de rendu gardées),
  **`set_device(device)`** : flux rouvert sur le nouveau périphérique ;
  refus de PortAudio → flux rouvert sur le précédent, erreur relevée.
- **`AppConfig`** : `audio_hostapi`, `audio_inputs`, `audio_outputs`
  (listes de noms, sans doublon), `audio_main_output` (la clé si elle est
  cochée, sinon la première sortie cochée, sinon le défaut).
- **Démarrage** (`MainWindow._open_audio_driver`) : sortie principale
  enregistrée si elle est là, sinon le défaut, annoncé (« Sortie audio
  « X » absente : sortie par défaut ») ; refusée par PortAudio → défaut,
  annoncé.
- **Effet immédiat** (`_apply_audio_output`, appelé par
  `_apply_preferences` quand le pilote, les sorties ou la sortie
  principale changent) : flux rouvert, annonce « sortie audio : X », ou
  refus (sortie précédente gardée).
- Vérifié sur le vrai matériel : ALSA et OSS ; flux passé sur
  `pipewire` ; refus d'un périphérique inexistant (précédent gardé) ;
  relecture de PortAudio puis flux rouvert ; crête de l'entrée mesurée.
  **Constat** : la sortie analogique de la carte (`hw:0,0`) n'apparaît
  pas en sortie, PipeWire la tenant ; on y passe par `pipewire`, `pulse`
  ou `default`. Les greffons ALSA (`lavrate`, `speex`, `upmix`…)
  apparaissent comme périphériques : à filtrer peut-être (11f1).
- Suite : 3921 verts, **7 rouges jusqu'à 11c1** (pilote factice sans
  `device` dans `test_live_limiter.py`, hôtes factices sans
  `PREFS_AUDIO_OUT_KEYS` dans `test_preferences_dialog.py` et
  `test_preferences_effects.py`).

**Essai 11b1** : sans réglage, l'appli sonne comme avant ; avec
`"audio_main_output": "pipewire"` dans `preferences.json`, elle sonne
aussi ; avec un nom inexistant, l'annonce de démarrage le dit et le son
passe par le défaut.

**Avenant 11b1 — paquet autonome `src/devices/`** (demande de
l'utilisateur, 2026-11-11 : « ce module de détection des périphériques
audio / MIDI est très important… l'isoler comme un module autonome, il
sera très utile dans d'autres applications audio / MIDI ») :
- `src/devices/audio_device.py` (l'ancien `audio_devices.py`), `__init__.py`
  (présentation, dépendances), et la partie MIDI viendra en
  `src/devices/midi_device.py` (11d1) ;
- **aucun import de l'appli** (seulement sounddevice, numpy ; rtmidi pour
  le MIDI) : le paquet se copie tel quel ;
- **`python3 -m devices`** (depuis `src/`) : liste les pilotes et les
  périphériques ; `--tone SORTIE` joue le La 440 Hz, `--input ENTRÉE`
  mesure la crête — pour l'essai de plusieurs cartes son prévu par
  l'utilisateur à la fin de l'étape 11 ;
- l'appli l'importe par `from devices import audio_device as audio_devices`.

**Avenant 11b1 — boîte de message au démarrage** (demande de
l'utilisateur, 2026-11-11) : un périphérique introuvable ou refusé au
démarrage est annoncé dans une **boîte de message bloquante** avec un
bouton Ok (`MainWindow._show_device_notes`, titre « Périphériques
introuvables »), mieux vue par un lecteur d'écran que la barre d'état ;
le message reste aussi dans la barre d'état. Liste `_device_notes`,
distincte des notes des moteurs ; vaudra aussi pour les ports MIDI
(11d1).
- Essai 3 (utilisateur) : boîte vue ; demandes : **nom du périphérique
  mis en avant** (« Sortie audio introuvable : Carte inexistante. Sortie
  par défaut utilisée. », titre « Périphérique introuvable » ou « N
  périphériques introuvables ») et **bip d'alerte** à l'ouverture de la
  boîte (`_alert_beep` : deux bips descendants 880 puis 660 Hz joués par
  le pilote audio de l'appli, `wx.Bell()` étant souvent muet).

**Essais 11b1** (utilisateur, 2026-11-11) : 1 (sans réglage), 2
(`pipewire`), 3 (sortie inexistante : boîte, nom, bip) concluants. Le
réglage d'essai est retiré de `preferences.json`.

**Avenant 11c1 — noms des fichiers du paquet** (suggestion de
l'utilisateur, 2026-11-11, pour la lisibilité dans une autre appli) :
`src/devices/audio.py` → **`audio_device.py`** ; le MIDI sera
**`midi_device.py`** (11d1).

### Avancement 11c1 (tests — audio)

- **`tests/test_audio_device.py`** (nouveau, 70 tests) :
  - paquet autonome : aucun fichier de `src/devices/` n'importe un
    module de l'appli (analyse des imports) ; noms des fichiers ;
  - `devices.audio_device` sur un **PortAudio factice** : pilotes, pilote
    par défaut et replis, périphériques par sens, défauts, recherche par
    nom (et nom retrouvé après renumérotation), sortie absente,
    relecture, La 440 Hz (440 Hz mesuré par FFT, niveau, fondus), crête
    d'une entrée (canaux, durée, refus) ; `python3 -m devices` (liste,
    `--tone`, `--input`, introuvable, refus, autre pilote) ;
  - `SoundDeviceDriver` sur un flux factice : périphérique donné ou
    défaut, `set_device` (refus → précédent rouvert), voix et sources de
    rendu gardées, `stop_stream` / `start_stream`, `close` ;
  - clés `audio_hostapi`, `audio_inputs`, `audio_outputs` (nettoyées),
    `audio_main_output` (cochée, décochée, sans sortie cochée) ;
  - démarrage : sortie enregistrée, sans réglage, absente, refusée,
    défaut refusé, pilote enregistré, limiteur transmis ; boîte
    « Périphérique introuvable » (un ou plusieurs, Ok, avertissement) et
    bip (deux bips descendants, repli sur `wx.Bell`, sans pilote) ;
  - sortie changée depuis les Préférences : bascule, retour au défaut,
    rien si inchangée, absente, refusée, sans pilote ; annonce dans
    `_apply_preferences`, clés qui déclenchent ou non ;
  - vraie fenêtre principale : sortie absente au démarrage → boîte,
    défaut, barre d'état.
- **7 tests rouges de 11b1 corrigés** (pilote factice avec `device`,
  hôtes avec `PREFS_AUDIO_OUT_KEYS`).
- Mutations vérifiées (précédent non rouvert après un refus ;
  périphériques non filtrés par pilote) : chacune fait échouer des tests.
- **`docs/SPECS.md`** : arborescence (`src/devices/`) et table. Suite :
  3998 verts (un échec isolé non reproduit en trois passages, sans
  doute le test de gain de sfizz déjà noté).

### Avancement 11d1 (implémentation — MIDI)

- **`src/devices/midi_device.py`** (nouveau, autonome : seulement
  python-rtmidi) : `input_ports()`, `output_ports()`, **`MidiInputs`**
  (plusieurs ports ouverts ensemble, `open_names` → (ouverts, absents),
  `close_all`, callback `(message, port)`), `open_output(nom)`,
  `send_test_note` (A4 d'une seconde, Note Off par minuterie),
  `wait_note(port, 5 s)` (ouvre son propre accès au port, possible sous
  ALSA même s'il est déjà ouvert), `note_name(69)` → « A4 ».
  `python3 -m devices` liste aussi les ports MIDI ; `--note PORT`,
  `--listen PORT`.
- **`MidiManager`** : ports par `MidiInputs` ; `open_names(noms)`
  (plusieurs ensemble), `port_names` ; `open(indice)` garde son rôle (un
  port, jusqu'au retrait de la liste en 11f1) ; `close()` ferme tout.
- **`AppConfig`** : `midi_inputs`, `midi_outputs` (clé absente →
  [« Synthé FluidSynth »]), `MIDI_SYNTH_OUTPUT`.
- **`src/ui/mw_devices.py`** (nouveau, `DevicesMixin` de `MainWindow`) :
  - `_open_midi_devices` au démarrage : entrées cochées ouvertes,
    sorties externes cochées ouvertes (`_midi_outs`, pour l'étape 12) ;
    introuvables → boîte « Périphérique introuvable » (« Entrée MIDI
    introuvable : X. ») ;
  - **Alt+M** (`_toggle_midi_inputs`) : déconnecte les entrées ouvertes,
    sinon connecte les entrées cochées (sans entrée cochée : le port de
    la liste « MIDI: », jusqu'à 11f1) ;
  - **Shift+F12** (`_reconnect_midi`, fenêtre principale et
    `handle_transport` pour les autres fenêtres) : tout fermer, relire,
    rouvrir ; annonce « MIDI reconnecté : … — Entrée MIDI introuvable :
    X. » ;
  - `_test_midi_output(nom)` : A4 d'une seconde (port externe : par
    rtmidi ; « Synthé FluidSynth » : FluidSynth **à part**, soundfont par
    défaut, branché au pilote le temps de la note, sans toucher aux slots
    Banque) ; `_listen_midi_input(nom, done)` : écoute dans un fil,
    résultat « Entrée MIDI X : note A4, vélocité 100, canal 1 » ou
    « aucune note reçue en 5 secondes ». Boutons en 11f1.
- Vérifié de bout en bout par **Midi Through** : A4 envoyé sur la
  sortie, reçu par l'entrée (`MidiInputs`, `wait_note`, `MidiManager`) ;
  A4 du Synthé FluidSynth rendu (crête 0,09) puis source retirée ;
  soundfont introuvable annoncée.
- Suite : 3988 verts, **11 rouges jusqu'à 11e1** (`test_midi_manager.py`
  simule rtmidi dans l'ancien module).

**Essai 11d1** : contrôleur branché et coché (`midi_inputs` dans
`preferences.json`) → connecté au démarrage, sans passer par la liste ;
Alt+M déconnecte / reconnecte ; débrancher puis Shift+F12 → introuvable
annoncé ; rebrancher puis Shift+F12 → reconnecté ; port inexistant
coché → boîte au démarrage.
- **Ajout pendant la préparation de l'essai** : sous ALSA, rtmidi termine
  le nom d'un port par son adresse (« MPK mini Plus:MPK mini Plus MIDI 1
  20:0 »), donnée au branchement et qui peut changer. Un nom enregistré
  retrouve son port par le nom exact, sinon par le même nom sans
  l'adresse (`midi_device.base_name`, `find_port`).

**Essai 11d1** (utilisateur, 2026-11-11) : concluant (Akai connecté au
démarrage, déconnexion / reconnexion, débranchement puis
réinitialisation). Demande : **raccourcis MIDI regroupés sur F12**
(révise H15) :
- **Ctrl+F12** : Panic (inchangé) ;
- **Shift+F12** : connecter / déconnecter les entrées MIDI (remplace
  **Alt+M**, retiré) ;
- **Ctrl+Shift+F12** : réinitialiser tous les périphériques MIDI
  (l'ancien Shift+F12 de ce chantier).
Fenêtre principale (`key_manager`) et autres fenêtres
(`handle_transport`). Alt+Shift+M (relire la liste « MIDI: ») reste
jusqu'au retrait de la liste en 11f1.
- Second essai concluant ; demande : un port MIDI introuvable par
  Shift+F12 ou Ctrl+Shift+F12 s'affiche aussi dans la **boîte bloquante
  avec bip**, comme au démarrage (`_show_device_notes(notes)`, parent =
  la fenêtre active pour que le focus y revienne).
- Troisième essai (boîte et bip par Shift+F12, Ctrl+Shift+F12, depuis
  l'éditeur MIDI) : concluant.

### Avancement 11e1 (tests — MIDI)

- **`tests/test_midi_device.py`** (nouveau, 69 tests) :
  - `devices.midi_device` sur un **rtmidi factice** : noms des notes,
    ports, sans rtmidi, `base_name` / `find_port` (adresse ALSA changée,
    nom exact préféré), `MidiInputs` (plusieurs ports ensemble, messages
    avec leur port, message vide, déjà ouvert, refusé, adresse changée,
    fermeture), sorties (adresse changée, introuvable, refusée), A4 d'une
    seconde (Note Off par minuterie, canal), `is_note_on`, `wait_note`
    (note reçue, CC ignoré, délai, port introuvable, accès refermé) ;
    `python3 -m devices` (ports MIDI, `--note`, `--listen`) ;
  - `MidiManager.open_names` (deux ports, même décodage, annonces,
    silencieux, sans rtmidi, `open(indice)` ferme les autres, refus) ;
    clés `midi_inputs` / `midi_outputs` ;
  - `DevicesMixin` : ouverture au démarrage (synthé interne pas un port,
    sorties gardées), fermeture, Shift+F12 (déconnecte / connecte,
    introuvable → boîte, sans entrée cochée → liste), Ctrl+Shift+F12
    (reconnecté, introuvable → boîte, rien de coché), A4 sur un port
    ouvert, temporaire (refermé), introuvable, Synthé FluidSynth (moteur
    factice : source branchée puis retirée, Note On / Off, soundfont
    introuvable, bibliothèque absente), écoute d'une entrée ;
  - boîte devant la fenêtre active ; F12 dans la fenêtre principale,
    l'éditeur MIDI et la fenêtre Songs, Alt+M et Alt+Shift+F12 sans
    effet ; vraie fenêtre principale (entrée introuvable → boîte).
- **11 tests rouges de 11d1 corrigés** (`test_midi_manager.py` : rtmidi
  factice aussi dans `devices.midi_device`, appels de `MidiInputs`).
- **Pièges de test** : la wx.App de la session détruite par un fichier
  précédent (recréée et gardée dans le module) ; les tests à vraie
  fenêtre attendent les fils de chargement (`wait_loaded`) avant
  `Destroy` (sinon un `wx.CallAfter` tardif lève une exception dans un
  test suivant) — ajouté aussi à `test_audio_device.py` et
  `test_preferences_effects.py`.
- Mutations vérifiées (nom sans l'adresse ALSA ignoré ; boîte absente à
  Ctrl+Shift+F12) : chacune fait échouer des tests.
- **`docs/SPECS.md`** : arborescence (`midi_device.py`) et table. Suite :
  4068 verts (aussi avec les exceptions de fil traitées en erreurs).

### Avancement 11f1 (implémentation — l'onglet et la fenêtre principale)

- **`src/ui/prefs_hardware.py`** (nouveau, `HardwarePage`) : Pilote
  audio (liste), **Entrées audio**, **Sorties audio**, **Entrées MIDI**,
  **Sorties MIDI** (listes à cases à cocher `wx.CheckListBox`, Espace
  coche) chacune suivie de son bouton Tester (« Tester l'entrée audio »,
  « Tester la sortie audio »…), **Sortie principale** (« Défaut du
  pilote » puis les sorties cochées, mise à jour en cochant), « Détecter
  les périphériques audio » / « MIDI », **Résultat du test** (lecture
  seule, prend le focus), puis Valeurs par défaut. Un périphérique coché
  mais absent reste listé (« — absent ») et coché. Changer de pilote
  relit les listes audio (cases gardées par nom). Tester agit sur la
  ligne sélectionnée ; les tests d'entrée rendent leur résultat plus tard
  (« écoute d'une seconde… », « jouez une note (5 secondes)… »).
- **`PreferencesDialog(…, hardware=None)`** : onglet Matériel construit
  avec l'objet `hardware` (sinon une phrase) ; clés `audio_hostapi`,
  `audio_inputs`, `audio_outputs`, `audio_main_output`, `midi_inputs`,
  `midi_outputs` dans `values()` / `values_of()` / Valeurs par défaut.
- **`mw_devices.HardwareAccess`** : listes par le paquet devices
  (« Synthé FluidSynth » en tête des sorties MIDI si la bibliothèque est
  là) ; Détecter audio = flux arrêté, PortAudio relu, flux rouvert sur la
  même sortie retrouvée par son nom (`audio_device.device_name`) ; Tester
  la sortie audio = La 440 Hz par le pilote de l'appli si c'est sa sortie,
  sinon directement ; Tester l'entrée audio = crête d'une seconde dans un
  fil ; MIDI par `_test_midi_output` / `_listen_midi_input`.
- **Effet immédiat** : entrées / sorties MIDI cochées changées → ports
  fermés puis rouverts (`_apply_midi_devices`, introuvables en boîte) ;
  sortie principale → flux rouvert (11b1).
- **`devices.midi_device`** : les clients rtmidi eux-mêmes (« RtMidiIn
  Client:RtMidi input 133:0 », un par port ouvert) apparaissaient dans les
  listes → retirés (`is_own_port`) ; nos clients s'appellent « devices ».
- **Fenêtre principale** : liste « MIDI: » retirée, ainsi
  qu'**Alt+Shift+M**, le double-clic, `MidiHandler.connect / toggle /
  refresh_ports`, `on_midi_port_list` ; Shift+F12 sans entrée cochée
  annonce « aucune entrée cochée — Alt+Shift+P, onglet Matériel ».
- **Aide F1** : Alt+Shift+P (onglet Matériel), Shift+F12 ; Alt+Shift+M
  et le double-clic retirés.
- Vérifié sur le vrai matériel : ALSA, 12 entrées et 7 sorties audio,
  Akai coché, « Synthé FluidSynth » coché par défaut ; ordre des
  contrôles conforme à H13.
- Suite : 4058 verts, **10 rouges jusqu'à 11g1** (hôtes et dialogue
  factices, test de la liste « MIDI: » retirée, Shift+F12 sans entrée).

**Essai 11f1** : Alt+Shift+P, onglet Matériel : Orca lit les listes à
cases (état de chaque case) ; cocher une sortie, la choisir comme
principale, Appliquer → son par elle ; Tester la sortie audio (La 440) ;
Tester l'entrée audio (crête) ; Tester la sortie MIDI sur « Synthé
FluidSynth » (A4) ; Tester l'entrée MIDI (jouer une note sur l'Akai) ;
Détecter ; décocher l'Akai, Appliquer → déconnecté.
- **Avant l'essai, demande de l'utilisateur** : greffons ALSA masqués des
  listes à cocher (`audio_device.devices(…, hide_plugins=True)`,
  `is_alsa_plugin`) : restent les cartes (« (hw:… ) »), `default`,
  `pipewire`, `pulse`. `find_device` les trouve toujours (réglage écrit à
  la main).

**Essai 11f1, remarques de l'utilisateur (2026-11-12)** :
- **Résultat du test** : le focus ne va plus sur le champ (il fallait
  revenir où l'on était) ; le champ reste, pour contrôler ce qui s'est
  passé. L'énoncé viendra du futur module **SpeechAccess** (synthèse
  vocale des barres d'état et autres messages).
- **Tester l'entrée audio** affichait toujours 0 dB de crête, sans dire
  si le son entrait. Mesure des quatre entrées : `hw:0,0` bloquée à −1
  (pleine échelle) ; `pipewire`, `pulse`, `default` : souffle, crête de
  −4 à −1 dB pour un niveau moyen de −17 à −24 dB. Désormais :
  **3 secondes** d'écoute (« parlez ou jouez pendant 3 secondes… ») ;
  **diagnostic** `audio_device.analyse_input` / `describe_input` :
  « silence (rien ne rentre) » (niveau moyen sous −70 dB), « signal
  bloqué à pleine échelle : entrée saturée ou inutilisable » (plus de la
  moitié des échantillons à pleine échelle), sinon « signal présent —
  niveau moyen −19 dB, crête −4 dB » ; **réécoute** des 3 secondes
  captées sur la sortie principale quand un signal est présent (pas pour
  un signal bloqué, qui serait un bruit à pleine échelle). Nouvelles
  fonctions `record_input`, `rms_db`, `to_stereo`.
- Second essai : réécoute appréciée. Toutes les entrées rendent la même
  voix : normal, l'ordinateur n'a qu'un micro intégré (`hw:0,0` en accès
  direct, `pipewire` / `pulse` / `default` par PipeWire) ; l'essai de
  plusieurs cartes les distinguera. **Corrigé** : chaque liste
  sélectionnait d'office sa première ligne, si bien que Tester écoutait
  une entrée non choisie ; désormais aucune ligne n'est sélectionnée à
  l'ouverture (« Choisissez d'abord une entrée audio dans la liste. »),
  et une sélection est gardée par nom quand la liste est relue. Tester
  agit toujours sur la ligne sous le curseur, cochée ou non (on peut
  tester avant de cocher).

- Troisième essai : Tester écoutait encore sans entrée choisie (GTK place
  le curseur, donc la sélection, sur la première ligne en entrant dans la
  liste). **Corrigé** : « **(Aucun)** » en tête des quatre listes, coché
  quand rien d'autre ne l'est ; le cocher décoche tout ; Tester sur lui
  répond « Choisissez d'abord… ».
- **OSS** : le test de `/dev/dsp` marche sur cette machine, par
  l'émulation OSS du noyau (`snd_pcm_oss` chargé, `/dev/dsp` présent),
  qui passe par ALSA ; entrée seule, aucune sortie.

**Essai 11f1** (utilisateur, 2026-11-12) : concluant après les
corrections (focus gardé, écoute de 3 s avec diagnostic et réécoute,
« (Aucun) » en tête des listes, Akai recoché). OSS gardé dans la liste
des pilotes (il marche ici par l'émulation du noyau).

## Phase 8 étape 11f2 — Corrections trouvées par les tests de 11g1

- **Liste des sorties audio** : la page captait l'événement de case
  cochée sans le transmettre ; les règles de « (Aucun) » (coché quand
  rien d'autre ne l'est, le cocher décoche tout) ne s'appliquaient pas à
  cette liste. Désormais `_CheckList(…, on_change)` traite la case, puis
  appelle la page (sortie principale relue).
- **Sortie principale** : la liste proposait « Défaut du pilote » même
  avec des sorties cochées, alors qu'`AppConfig.audio_main_output` prend
  alors la première sortie cochée (le dialogue aurait montré un choix et
  l'appli en aurait fait un autre). Désormais, comme H16 : les sorties
  cochées, ou « Défaut du pilote » quand aucune ne l'est ; choix gardé
  s'il reste coché, sinon la première cochée.

**Essai 11f2** : cocher puis décocher des sorties audio, cocher
« (Aucun) » dans les sorties audio ; la liste « Sortie principale » ne
propose que les sorties cochées.
- Essai 11f2 (utilisateur, 2026-11-12) : concluant.

### Avancement 11g1 (tests — l'onglet Matériel)

- **`tests/test_prefs_hardware.py`** (nouveau, 71 tests) :
  - `HardwarePage` sur un matériel factice : sans matériel (phrase),
    ordre des contrôles (H13) et libellés, résultat en lecture seule ;
    « (Aucun) » en tête, curseur dessus, coché quand rien d'autre ne
    l'est, le cocher décoche tout, impossible à décocher seul ;
    périphérique absent gardé et coché ; sélection gardée par nom ;
    valeurs lues, défauts affichés, Synthé FluidSynth seulement s'il est
    proposé, pilote inconnu → défaut, changement de pilote (cases gardées),
    sortie principale (sorties cochées ou défaut, choix gardé, principale
    décochée) ; réglages changés et valeur par défaut retirée ; Valeurs
    par défaut de l'onglet ;
  - Tester : rien de sélectionné (quatre listes), sortie audio, ligne non
    cochée, entrées en différé (message d'attente puis résultat) ; le
    focus ne va jamais sur le résultat ; Détecter relit les listes ;
    résultat après fermeture sans erreur ;
  - `audio_device` : greffons ALSA, `devices(…, hide_plugins)`,
    diagnostic (silence, bloqué, présent malgré un pic de souffle, très
    faible = silence), `rms_db`, `to_stereo`, écoute de 3 s,
    `device_name` ; `midi_device` : clients rtmidi retirés, nos clients
    nommés « devices » ;
  - `HardwareAccess` : listes (greffons masqués, Synthé FluidSynth selon
    la bibliothèque), Détecter audio (flux arrêté, relu, rouvert sur la
    même sortie retrouvée par son nom ; défaut), Détecter MIDI, La 440 par
    le pilote de l'appli (sans ouverture en double) ou directement,
    introuvable, refus ; écoute : présent → réécoute en stéréo, bloqué ou
    silence → pas de réécoute, introuvable, refus ; tests MIDI délégués ;
  - ports MIDI rouverts depuis les Préférences (`_apply_midi_devices`,
    annonce « MIDI rouvert »), matériel passé au dialogue.
- **11 tests rouges de 11f1 corrigés** ; traces de la liste « MIDI: »
  retirées des tests (`test_key_manager`, `test_exclusive_mute_solo`,
  `test_master_mix`, `test_mix_undo`).
- Les tests ont trouvé les deux défauts corrigés en 11f2.
- Mutations vérifiées (« (Aucun) » ne décoche rien ; signal bloqué non
  détecté) : chacune fait échouer des tests.
- **`docs/SPECS.md`** : arborescence (`prefs_hardware.py`,
  `mw_devices.py`) et table. Suite : 4139 verts (aussi avec les
  exceptions de fil traitées en erreurs).

### Clôture de l'étape 11 (11h1)

**Bilan** (Phase 8 étapes 11a à 11g1, 2026-11-11 / 12, 4139 tests
verts) : onglet **Matériel** des Préférences — pilote audio, entrées et
sorties audio et MIDI à cases à cocher (« (Aucun) » en tête), ouvertes
ensemble au démarrage, sortie principale, Tester (La 440 Hz, A4, écoute
de 3 s avec diagnostic et réécoute, prochaine note), Détecter, résultat
sans déplacer le focus ; périphérique introuvable en boîte bloquante avec
bip ; raccourcis MIDI sur F12 ; liste « MIDI: », Alt+M et Alt+Shift+M
retirés ; **paquet autonome `src/devices/`** et `python3 -m devices`.

**Commits** : 11a (plan), 11b1 / 11c1 (audio), 11d1 / 11e1 (MIDI), 11f1
(onglet et fenêtre principale), 11f2 (corrections trouvées par les
tests), 11g1 (tests de l'onglet), 11h1 (clôture).

**Écarts au plan et imprévus** (demandes de l'utilisateur aux essais
pour la plupart) :
- plusieurs entrées **et** sorties, audio comme MIDI (H12) ; ordre
  Entrées audio, Sorties audio, Entrées MIDI, Sorties MIDI ; un bouton
  Tester par liste ;
- paquet autonome `src/devices/` (`audio_device.py`, `midi_device.py`)
  et sa commande d'essai ;
- boîte bloquante avec le nom du périphérique et un bip, au démarrage
  puis pour le MIDI à F12 ;
- raccourcis MIDI regroupés sur F12 (Shift+F12 remplace Alt+M,
  Ctrl+Shift+F12 réinitialise) ;
- adresse ALSA des ports MIDI tolérée ; clients rtmidi et greffons ALSA
  retirés des listes ;
- résultat sans focus (futur SpeechAccess) ; écoute d'entrée de 3 s avec
  diagnostic et réécoute ; « (Aucun) » en tête des listes ;
- 11f2 : deux défauts trouvés par les tests.

**Essais de l'utilisateur** : 11b1 (sortie inexistante, boîte, bip),
11d1 (Akai, F12), 11f1 (onglet, Orca, Tester, Détecter), 11f2 :
concluants. OSS gardé (il marche ici par l'émulation du noyau).

**`docs/SPECS.md`** : ligne Phase 8, « Onglet Matériel et
périphériques », tableau des réglages, arborescence, tests.
**`docs/shortcuts.md`** (aide F1) : Alt+Shift+P (onglet Matériel),
Shift+F12, Ctrl+Shift+F12 ; Alt+M, Alt+Shift+M, double-clic retirés.

**Suites notées** :
- **essai de l'utilisateur avec plusieurs cartes son** (et
  `python3 -m devices`) ;
- **étape 12 — entrées et sorties dans les propriétés des pistes**
  (choix parmi les périphériques cochés, envoi des pistes vers une
  sortie MIDI externe) ;
- **module SpeechAccess** (synthèse vocale des messages) ;
- Ctrl+Z du dialogue des Préférences (noté en 10f2) ; audition dans
  l'Explorateur ; source SFZ à un seul programme (10b1).

---

## Phase 8 étape 12a — Entrées et sorties dans les propriétés des pistes

### Numérotation des commits de ce chantier

`12a` = ce plan (doc seule). Le code commence à `12b1` ; paires
implémentation → tests ; `12b2`… pour un commit imprévu. Décisions notées
**T1, T2…**.

### Origine du besoin

Cahier des charges du 2026-11-10 : « les entrées / sorties audio et MIDI
choisies dans les Préférences doivent apparaître dans les propriétés des
pistes ». Précisé le 2026-11-11 (H12) : l'entrée ou la sortie d'une piste
se choisit **parmi les périphériques cochés** dans l'onglet Matériel,
sans revenir aux Préférences ; au démarrage, les pistes retrouvent leurs
entrées et sorties directement.

### État des lieux constaté en code (2026-11-12, 4139 tests verts)

- **Données d'une piste** : par pattern (`Pattern`) — slot, canal MIDI,
  programme / banque (en-têtes de la piste), mute, solo, volume, pan.
  Aucune entrée ni sortie.
- **Sorties : tout passe par les moteurs internes.** `TrackRouter`
  (`on_play` pour la grille, `on_kit_tape`, `on_patch_tape`,
  `on_cc_tape`, `on_bend_tape`, `on_program_change_tape`…) envoie chaque
  événement au moteur du slot de la piste (échantillonneur, synthé WAV,
  FluidSynth, sfizz) ; tout est mélangé par le `Mixer` et va à la
  **sortie audio principale**. Les ports MIDI de sortie cochés sont
  ouverts (`_midi_outs`, 11d1) mais rien n'y est envoyé.
- **Notes d'une piste en MIDI** : l'export MIDI sait déjà traduire chaque
  piste en messages (grille de kit → notes GM, `pad_notes` ; PATCH / KIT
  ; CC, Pitch Bend, Program Change ; en-têtes banque / programme ;
  volume et pan en CC7 / CC10) — réutilisable pour un envoi en direct.
- **Entrée en direct** : toutes les entrées MIDI cochées arrivent au même
  décodage (`MidiManager`, sans le nom du port), puis à la **piste
  courante** seule (`MidiHandler.on_note_on` : mode Pad ou Clavier,
  enregistrement, effacement).
- **Audio** : un seul flux (la sortie principale) ; les autres sorties
  cochées ne servent pas ; les entrées audio ne servent pas (pas de piste
  audio).
- **Propriétés de piste** (`TrackPropertiesDialog`, Alt+Entrée) :
  Mute, Solo, Slot, Canal, Programme, Banque MSB / LSB, Transposition et
  Gain GM, Volume, Pan.

### Choix de conception proposés

**T1 — Sortie MIDI de la piste** : « Interne (son du slot) » (défaut, le
comportement actuel) ou une des sorties MIDI externes cochées. Sur une
sortie externe, les événements de la piste partent vers le port, sur le
canal de la piste, traduits comme à l'export (notes de grille d'un kit en
notes GM, PATCH / KIT, CC, Pitch Bend, Program Change et en-têtes
banque / programme au départ, volume et pan en CC7 / CC10) ; **le son
interne de la piste se tait**. Note Off programmés comme pour les
moteurs ; Stop, Panic (Ctrl+F12), Mute / Solo → All Notes Off sur le
canal du port.

**T2 — Entrée MIDI de la piste** : « Toutes » (défaut, comme
aujourd'hui) ou une des entrées MIDI cochées. Le nom du port est
transmis avec chaque message (`MidiInputs` le connaît déjà) ; une note
n'arrive à la piste courante que si son entrée est « Toutes » ou ce
port.

**T3 — Sortie audio de la piste** : sortie principale seulement à cette
étape (liste affichée, une seule entrée) ; l'envoi d'une piste vers une
autre sortie audio demande un flux et un mélange par sortie, synchronisés
— chantier à part.

**T4 — Entrée audio de la piste** : quand les pistes audio existeront ;
hors de cette étape.

**T5 — Propriétés de piste** : deux listes, « Entrée MIDI » et « Sortie
MIDI », après Canal (libellé avant chaque liste ; périphériques cochés
seulement ; « — absent » pour un port enregistré mais débranché).

**T6 — Export MIDI** : inchangé (un fichier .mid ne garde pas de port).

### Décisions de l'utilisateur (2026-11-12)

- **Q1 → T7 — MIDI seulement** à cette étape (sortie audio par piste et
  entrée audio plus tard) ; dans les propriétés de piste, **les listes
  des ports viennent avant la liste des canaux** (révise T5) : Mute,
  Solo, Slot, **Entrée MIDI**, **Sortie MIDI**, Canal, Programme…
- **Q2 → T8 — par pattern**, comme le canal (les pistes sont
  indépendantes d'un pattern à l'autre) : `Pattern._track_midi_in` et
  `_track_midi_out` (noms ; "" = « Toutes » / « Interne »), enregistrés
  dans le `.gvp` (clés absentes des anciens projets → ""), copiés avec la
  piste (presse-papier, duplication de pattern) et pris par l'Undo comme
  le canal.
- **Q3 → T9 — piste courante seulement**, pour l'instant (simplicité) :
  le jeu en direct va à la piste courante si son entrée est « Toutes » ou
  le port d'où vient la note ; sinon la note est ignorée.
- **Q4 → T10 — port externe absent : son interne avec avertissement**,
  pour jouer quand même : la piste joue le son de son slot ;
  avertissement au chargement du pattern (ou quand on choisit le port),
  une fois par port absent et par session : boîte « Périphérique
  introuvable » avec bip (« Sortie MIDI introuvable : X. Piste 3 : son
  interne. ») et barre d'état.

### Découpage

- **12b1 / 12c1 — sortie MIDI des pistes** : données par pattern (T8) ;
  envoi des événements d'une piste vers son port (T1 : traduction comme
  l'export, en-têtes au départ, Note Off, Stop / Panic / Mute → All
  Notes Off) ; repli sur le son interne (T10).
- **12d1 / 12e1 — entrée MIDI des pistes et propriétés** : nom du port
  transmis avec chaque message, filtre de la piste courante (T9) ;
  listes « Entrée MIDI » et « Sortie MIDI » avant Canal dans les
  propriétés (T7), effet immédiat ; aide F1.
- **12f1 — clôture**.
