import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import wx
from ui.main_window import MainWindow


def parse_args(argv=None):
    """Options de lancement (Phase 8 étape 7b1, docs/DESIGN.md § 7a2 Z7,
    Z14) : --no-fluidsynth et --no-sfizz coupent un moteur de synthèse pour
    ce lancement, en primant sur config.json. Les arguments inconnus sont
    ignorés (parse_known_args)."""
    parser = argparse.ArgumentParser(prog="groovyboxit",
                                     description="GroovyboxIt — groovebox au pavé numérique")
    parser.add_argument("--no-fluidsynth", action="store_true",
                        help="sans le moteur FluidSynth (slots Banque muets)")
    parser.add_argument("--no-sfizz", action="store_true",
                        help="sans le moteur sfizz (slots Synth SFZ muets)")
    args, _unknown = parser.parse_known_args(argv)
    return args


def main():
    args = parse_args()
    app = wx.App(False)
    frame = MainWindow(no_fluidsynth=args.no_fluidsynth, no_sfizz=args.no_sfizz)
    frame.wait_loaded()   # patches + precompute terminés avant d'afficher la fenêtre
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
