#python3
"""
    File: src/record_modes.py
    Options de l'enregistrement (Phase 8 étape 16b1, docs/DESIGN.md § Phase 8
    étape 16a, O1-O11) : table des modes d'enregistrement et options du
    projet (clé record_options du .gvp).
    Modes extensibles (O5, O6) : un mode = un identifiant texte gardé dans le
    projet, décrit par une ligne de MODES ; la liste du dialogue en est
    construite. Punch In/Out, Automation, Live Looper viendront plus tard
    (une ligne et leur comportement). Un identifiant inconnu (projet d'une
    version plus récente) → Overdub.
    Sans wx : utilisé par le dialogue, la fenêtre principale et les tests.
    Date: Tue, 17/11/2026
    Author: Coolbrother
"""

OVERDUB = "overdub"
REPLACE = "replace"
MPC     = "mpc"              # Remplacer puis Overdub (Mode MPC, 16d1)


class RecordMode:
    """Ligne de la table : identifiant, libellé du dialogue, nom court pour
    les annonces, et si le premier passage remplace (replace) puis si les
    suivants ajoutent (then_overdub)."""
    __slots__ = ("id", "label", "short", "replace", "then_overdub")

    def __init__(self, id, label, short, replace=False, then_overdub=False):
        self.id, self.label, self.short = id, label, short
        self.replace, self.then_overdub = replace, then_overdub


MODES = (
    RecordMode(OVERDUB, "Overdub", "Rec"),
    RecordMode(REPLACE, "Remplacer", "Replace Rec", replace=True),
    RecordMode(MPC, "Remplacer puis Overdub (MPC)", "Rec (MPC)", replace=True,
               then_overdub=True),
)

COUNT_IN_CHOICES = (0, 1, 2, 4, 8)          # mesures de décompte (Ctrl+R)

DEFAULTS = {                                # le comportement d'avant 16b1
    "mode": OVERDUB,
    "click_play": False,
    "count_in_play": 0,                     # décompte avant Play (16b1, essai)
    "click_record": True,
    "count_in": 1,
}


def mode_of(mode_id):
    """RecordMode de l'identifiant ; inconnu → Overdub."""
    for mode in MODES:
        if mode.id == mode_id:
            return mode
    return MODES[0]


def mode_index(mode_id):
    return MODES.index(mode_of(mode_id))


def normalize(data):
    """Options valides depuis la clé du .gvp (absente, incomplète ou d'une
    autre version) : chaque champ invalide prend son défaut."""
    out = dict(DEFAULTS)
    if not isinstance(data, dict):
        return out
    out["mode"] = mode_of(data.get("mode")).id
    for key in ("click_play", "click_record"):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    for key in ("count_in", "count_in_play"):
        count = data.get(key)
        if isinstance(count, int) and not isinstance(count, bool) and count in COUNT_IN_CHOICES:
            out[key] = count
    return out


def count_label(n):
    """« aucun », « 1 mesure », « 2 mesures »…"""
    return "aucun" if n == 0 else f"{n} mesure{'s' if n > 1 else ''}"


def describe(options):
    """Annonce des options : « Mode : Overdub ; clic : enregistrement ;
    décompte de lecture : aucun ; décompte d'enregistrement : 1 mesure »."""
    opts = normalize(options)
    clicks = [name for key, name in (("click_play", "lecture"),
                                     ("click_record", "enregistrement")) if opts[key]]
    return (f"Mode : {mode_of(opts['mode']).label} ; clic : "
            f"{', '.join(clicks) if clicks else 'aucun'} ; décompte de lecture : "
            f"{count_label(opts['count_in_play'])} ; décompte d'enregistrement : "
            f"{count_label(opts['count_in'])}")
