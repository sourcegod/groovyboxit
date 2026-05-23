#python3
"""
    File: tests/test_midi_manager.py
    Tests unitaires de MidiManager :
    valeurs initiales, list_ports, open/open_by_name/open_first, close,
    _callback (Note On / Note Off / filtrage canal), on_status, sans rtmidi.
    Date: Fri, 23/05/2026
    Author: Coolbrother
"""
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import midi_manager as mm_module
from midi_manager import MidiManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_PORTS = ["Port A", "Port B", "Port C"]


def make_mgr(ports=DEFAULT_PORTS, **kwargs):
    """
    Crée un MidiManager avec rtmidi mocké.
    Retourne (mgr, mock_rt, stop_fn).
    Appeler stop_fn() en fin de test pour restaurer les patches.
    """
    mock_rt = MagicMock()
    mock_rt.MidiIn.return_value.get_ports.return_value = list(ports)
    p_rt    = patch.object(mm_module, "rtmidi",             mock_rt)
    p_avail = patch.object(mm_module, "_RTMIDI_AVAILABLE",  True)
    p_rt.start()
    p_avail.start()
    mgr = MidiManager(**kwargs)
    def stop(): p_rt.stop(); p_avail.stop()
    return mgr, mock_rt, stop


def ok(msg):
    print(f"  {msg} : OK")


# ---------------------------------------------------------------------------
# Valeurs initiales
# ---------------------------------------------------------------------------

def test_init_is_not_open():
    mgr, _, stop = make_mgr()
    assert not mgr.is_open()
    stop()
    ok("is_open() == False à l'init")

def test_init_port_name_empty():
    mgr, _, stop = make_mgr()
    assert mgr.port_name == ""
    stop()
    ok('port_name == "" à l\'init')

def test_init_channel_none():
    mgr, _, stop = make_mgr()
    assert mgr.channel is None
    stop()
    ok("channel == None à l'init")

def test_init_callbacks_stored():
    on_on  = MagicMock()
    on_off = MagicMock()
    on_st  = MagicMock()
    mgr, _, stop = make_mgr(on_note_on=on_on, on_note_off=on_off, on_status=on_st)
    assert mgr._on_note_on  is on_on
    assert mgr._on_note_off is on_off
    assert mgr._on_status   is on_st
    stop()
    ok("callbacks stockés à l'init")


# ---------------------------------------------------------------------------
# list_ports
# ---------------------------------------------------------------------------

def test_list_ports_returns_list():
    mgr, _, stop = make_mgr(ports=["P1", "P2"])
    assert mgr.list_ports() == ["P1", "P2"]
    stop()
    ok("list_ports() retourne la liste des ports")

def test_list_ports_empty():
    mgr, _, stop = make_mgr(ports=[])
    assert mgr.list_ports() == []
    stop()
    ok("list_ports() retourne [] si aucun port")


# ---------------------------------------------------------------------------
# open()
# ---------------------------------------------------------------------------

def test_open_valid_returns_true():
    mgr, _, stop = make_mgr()
    assert mgr.open(0) is True
    stop()
    ok("open(0) retourne True pour un port valide")

def test_open_sets_is_open():
    mgr, _, stop = make_mgr()
    mgr.open(1)
    assert mgr.is_open()
    stop()
    ok("open() met is_open() à True")

def test_open_sets_port_name():
    mgr, _, stop = make_mgr()
    mgr.open(1)
    assert mgr.port_name == "Port B"
    stop()
    ok("open(1) met port_name à 'Port B'")

def test_open_invalid_index_returns_false():
    mgr, _, stop = make_mgr()
    assert mgr.open(99) is False
    stop()
    ok("open(99) retourne False (index hors limites)")

def test_open_invalid_does_not_open():
    mgr, _, stop = make_mgr()
    mgr.open(99)
    assert not mgr.is_open()
    stop()
    ok("open(99) ne met pas is_open() à True")

def test_open_invalid_notifies():
    status = []
    mgr, _, stop = make_mgr(on_status=status.append)
    mgr.open(99)
    assert any("introuvable" in s or "99" in s for s in status)
    stop()
    ok("open(index invalide) appelle on_status")

def test_open_notifies_on_connect():
    status = []
    mgr, _, stop = make_mgr(on_status=status.append)
    mgr.open(0)
    assert any("connect" in s.lower() or "Port A" in s for s in status)
    stop()
    ok("open() appelle on_status à la connexion")

def test_open_calls_set_callback():
    mgr, mock_rt, stop = make_mgr()
    mgr.open(0)
    mgr._midi_in.set_callback.assert_called_once_with(mgr._callback)
    stop()
    ok("open() appelle set_callback")

def test_open_calls_ignore_types():
    mgr, mock_rt, stop = make_mgr()
    mgr.open(0)
    mgr._midi_in.ignore_types.assert_called_once()
    stop()
    ok("open() appelle ignore_types")

def test_open_twice_closes_first():
    status = []
    mgr, _, stop = make_mgr(on_status=status.append)
    mgr.open(0)
    mgr.open(1)
    assert "déconnect" in " ".join(status).lower()
    assert mgr.port_name == "Port B"
    stop()
    ok("open() deux fois ferme le port précédent")


# ---------------------------------------------------------------------------
# open_by_name()
# ---------------------------------------------------------------------------

def test_open_by_name_found():
    mgr, _, stop = make_mgr()
    assert mgr.open_by_name("Port B") is True
    assert mgr.port_name == "Port B"
    stop()
    ok('open_by_name("Port B") ouvre le bon port')

def test_open_by_name_case_insensitive():
    mgr, _, stop = make_mgr()
    assert mgr.open_by_name("port b") is True
    stop()
    ok("open_by_name() est insensible à la casse")

def test_open_by_name_partial_match():
    mgr, _, stop = make_mgr()
    assert mgr.open_by_name("B") is True
    stop()
    ok("open_by_name() accepte un sous-nom")

def test_open_by_name_not_found():
    mgr, _, stop = make_mgr()
    assert mgr.open_by_name("Inexistant") is False
    stop()
    ok("open_by_name() retourne False si introuvable")


# ---------------------------------------------------------------------------
# open_first()
# ---------------------------------------------------------------------------

def test_open_first_opens_port_0():
    mgr, _, stop = make_mgr()
    assert mgr.open_first() is True
    assert mgr.port_name == "Port A"
    stop()
    ok("open_first() ouvre le port 0")

def test_open_first_no_ports():
    mgr, _, stop = make_mgr(ports=[])
    assert mgr.open_first() is False
    stop()
    ok("open_first() retourne False si aucun port")


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

def test_close_sets_is_open_false():
    mgr, _, stop = make_mgr()
    mgr.open(0)
    mgr.close()
    assert not mgr.is_open()
    stop()
    ok("close() met is_open() à False")

def test_close_clears_port_name():
    mgr, _, stop = make_mgr()
    mgr.open(0)
    mgr.close()
    assert mgr.port_name == ""
    stop()
    ok('close() remet port_name à ""')

def test_close_notifies():
    status = []
    mgr, _, stop = make_mgr(on_status=status.append)
    mgr.open(0)
    status.clear()
    mgr.close()
    assert any("déconnect" in s.lower() for s in status)
    stop()
    ok("close() appelle on_status")

def test_close_when_not_open_no_crash():
    mgr, _, stop = make_mgr()
    mgr.close()   # pas encore ouvert → pas de crash
    stop()
    ok("close() sans port ouvert ne plante pas")


# ---------------------------------------------------------------------------
# _callback — Note On / Note Off
# ---------------------------------------------------------------------------

def _fire(mgr, message):
    """Simule la réception d'un message MIDI via le callback rtmidi."""
    mgr._callback((message, 0.0), None)


def test_callback_note_on():
    hits = []
    mgr, _, stop = make_mgr(on_note_on=lambda n, v, c: hits.append((n, v, c)))
    _fire(mgr, [0x90, 60, 100])
    assert hits == [(60, 100, 0)]
    stop()
    ok("_callback Note On → on_note_on(note, vel, chan)")

def test_callback_note_off_explicit():
    offs = []
    mgr, _, stop = make_mgr(on_note_off=lambda n, c: offs.append((n, c)))
    _fire(mgr, [0x80, 62, 0])
    assert offs == [(62, 0)]
    stop()
    ok("_callback 0x80 → on_note_off(note, chan)")

def test_callback_note_on_vel0_is_note_off():
    offs = []
    mgr, _, stop = make_mgr(on_note_off=lambda n, c: offs.append((n, c)))
    _fire(mgr, [0x90, 64, 0])
    assert offs == [(64, 0)]
    stop()
    ok("_callback Note On vel=0 → on_note_off")

def test_callback_note_on_vel0_does_not_call_on_note_on():
    hits = []
    mgr, _, stop = make_mgr(on_note_on=lambda n, v, c: hits.append((n, v, c)))
    _fire(mgr, [0x90, 64, 0])
    assert hits == []
    stop()
    ok("_callback Note On vel=0 ne déclenche pas on_note_on")

def test_callback_channel_extracted():
    hits = []
    mgr, _, stop = make_mgr(on_note_on=lambda n, v, c: hits.append(c))
    _fire(mgr, [0x93, 60, 80])   # canal 3
    assert hits == [3]
    stop()
    ok("_callback extrait correctement le canal (0x93 → canal 3)")

def test_callback_channel_filter_match():
    hits = []
    mgr, _, stop = make_mgr(on_note_on=lambda n, v, c: hits.append(n))
    mgr.channel = 2
    _fire(mgr, [0x92, 60, 100])   # canal 2 → accepté
    assert hits == [60]
    stop()
    ok("filtrage canal : canal correspondant → on_note_on appelé")

def test_callback_channel_filter_no_match():
    hits = []
    mgr, _, stop = make_mgr(on_note_on=lambda n, v, c: hits.append(n))
    mgr.channel = 2
    _fire(mgr, [0x90, 60, 100])   # canal 0 → filtré
    assert hits == []
    stop()
    ok("filtrage canal : canal différent → on_note_on ignoré")

def test_callback_no_callbacks_no_crash():
    mgr, _, stop = make_mgr()   # pas de callbacks
    _fire(mgr, [0x90, 60, 100])
    _fire(mgr, [0x80, 60,   0])
    stop()
    ok("_callback sans callbacks ne plante pas")

def test_callback_empty_message_no_crash():
    mgr, _, stop = make_mgr()
    _fire(mgr, [])
    stop()
    ok("_callback message vide ne plante pas")


# ---------------------------------------------------------------------------
# Sans rtmidi (_RTMIDI_AVAILABLE = False)
# ---------------------------------------------------------------------------

def test_no_rtmidi_list_ports_empty():
    with patch.object(mm_module, "_RTMIDI_AVAILABLE", False):
        mgr = MidiManager()
        assert mgr.list_ports() == []
    ok("sans rtmidi : list_ports() == []")

def test_no_rtmidi_open_returns_false():
    with patch.object(mm_module, "_RTMIDI_AVAILABLE", False):
        mgr = MidiManager()
        assert mgr.open(0) is False
    ok("sans rtmidi : open() retourne False")

def test_no_rtmidi_notifies_at_init():
    status = []
    with patch.object(mm_module, "_RTMIDI_AVAILABLE", False):
        mgr = MidiManager(on_status=status.append)
    assert any("non disponible" in s or "désactivée" in s for s in status)
    ok("sans rtmidi : on_status appelé à l'init")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_init_is_not_open,
        test_init_port_name_empty,
        test_init_channel_none,
        test_init_callbacks_stored,
        test_list_ports_returns_list,
        test_list_ports_empty,
        test_open_valid_returns_true,
        test_open_sets_is_open,
        test_open_sets_port_name,
        test_open_invalid_index_returns_false,
        test_open_invalid_does_not_open,
        test_open_invalid_notifies,
        test_open_notifies_on_connect,
        test_open_calls_set_callback,
        test_open_calls_ignore_types,
        test_open_twice_closes_first,
        test_open_by_name_found,
        test_open_by_name_case_insensitive,
        test_open_by_name_partial_match,
        test_open_by_name_not_found,
        test_open_first_opens_port_0,
        test_open_first_no_ports,
        test_close_sets_is_open_false,
        test_close_clears_port_name,
        test_close_notifies,
        test_close_when_not_open_no_crash,
        test_callback_note_on,
        test_callback_note_off_explicit,
        test_callback_note_on_vel0_is_note_off,
        test_callback_note_on_vel0_does_not_call_on_note_on,
        test_callback_channel_extracted,
        test_callback_channel_filter_match,
        test_callback_channel_filter_no_match,
        test_callback_no_callbacks_no_crash,
        test_callback_empty_message_no_crash,
        test_no_rtmidi_list_ports_empty,
        test_no_rtmidi_open_returns_false,
        test_no_rtmidi_notifies_at_init,
    ]

    print("=== test_midi_manager ===")
    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"  ÉCHEC {t.__name__}: {e}")
            failed.append(t.__name__)

    print("Tous les tests : OK" if not failed else f"{len(failed)} ÉCHEC(S) : {failed}")
