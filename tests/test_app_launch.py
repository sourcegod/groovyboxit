#python3
"""
    File: tests/test_app_launch.py
    Vérifie que l'application s'importe et instancie sans erreur (sans afficher
    de fenêtre).  Lance wx.App en mode headless puis détruit immédiatement.
    Date: Mon, 18/05/2026
    Author: Coolbrother
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_import_main_window():
    from ui.main_window import MainWindow
    print("  import MainWindow : OK")


def test_instantiate_main_window():
    import wx
    from ui.main_window import MainWindow
    win = MainWindow()
    win.Destroy()
    print("  instanciation MainWindow : OK")


if __name__ == "__main__":
    import wx
    app = wx.App(False)
    print("=== test_app_launch ===")
    test_import_main_window()
    test_instantiate_main_window()
    app.Destroy()
    print("Tous les tests : OK")
