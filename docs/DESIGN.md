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

### Découpage en commits

| Étape | Contenu | Fichiers/tests touchés |
|---|---|---|
| **1c** | `Pattern` : dataclass `TapeEvent` + `_tape` → liste plate par piste + index `{(track,time): [...]}` pour perf grille. API publique de `Pattern` inchangée en signature (aucun appelant externe cassé à ce stade). | `pattern.py`, `test_pattern.py`, `test_pattern_grid_api.py`, `test_pattern_properties_bug.py`, `test_tape.py` |
| **1d** | `to_dict`/`from_dict` : écriture `tape_v2`, lecture rétrocompat ancien format + test explicite de rétrocompat (charger un vieux dict/fichier). | `pattern.py` + fixture de test dédiée |
| **1e** | Migration des 5 consommateurs directs (`ev.note`/`ev.vel`/`ev.bend` → `ev.payload[...]`, nouveau `ev.channel`), un fichier à la fois, tests après chacun. | `drum_player.py`, `track_editor.py`, `midi_editor.py`, `quantize_manager.py`, `ui/mw_project.py` + `test_midi_editor.py`, `test_quantize.py`, `test_track_editor.py`, `test_transport.py` |
| **1f** | Brancher `channel` côté UI là où c'est pertinent (à évaluer une fois 1c-1e faits). | à déterminer |
| **1g** | Durée GRID par événement (override Numpad1/3) — le vrai déclencheur initial de ce chantier (étape 7d, 2026-07-24). | `midi_editor.py` + `mew_numpad.py` |
