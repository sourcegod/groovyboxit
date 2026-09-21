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
