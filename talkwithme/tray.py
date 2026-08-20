"""System tray icon. Colour carries state: violet idle, coral listening,
amber processing.

pystray runs detached on its own thread; menu handlers only call back into
App, which marshals any UI work onto the Tk main thread.
"""
from __future__ import annotations

import logging

import pystray

from .icon import make_icon

log = logging.getLogger("talkwithme.tray")

TITLES = {
    "idle": "TalkWithMe — houd Ctrl+Win vast om te praten",
    "listening": "TalkWithMe — luistert",
    "processing": "TalkWithMe — verwerkt",
    "meeting": "TalkWithMe — vergadering wordt opgenomen",
}


class TrayApp:
    def __init__(self, on_quit, on_settings, on_history, on_toggle_cleanup,
                 is_cleanup_enabled, on_toggle_autostart, is_autostart_enabled,
                 on_report, on_toggle_tone, is_tone_enabled,
                 on_check_updates=None, on_toggle_meeting=None,
                 is_meeting=None):
        self._icons = {state: make_icon(state) for state in TITLES}
        self._on_quit = on_quit

        menu = pystray.Menu(
            # default=True: a plain click on the tray icon opens history,
            # instead of it hiding behind a right-click menu.
            pystray.MenuItem("Geschiedenis", lambda icon, item: on_history(),
                              default=True),
            pystray.MenuItem("Weekrapport", lambda icon, item: on_report()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Vergadering opnemen",
                              lambda icon, item: on_toggle_meeting and on_toggle_meeting(),
                              checked=lambda item: bool(is_meeting and is_meeting())),
            pystray.MenuItem("Instellingen", lambda icon, item: on_settings()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Mijn spraak opschonen",
                              lambda icon, item: on_toggle_cleanup(),
                              checked=lambda item: is_cleanup_enabled()),
            pystray.MenuItem("Toon aanpassen aan de app",
                              lambda icon, item: on_toggle_tone(),
                              checked=lambda item: is_tone_enabled()),
            pystray.MenuItem("Starten bij inloggen",
                              lambda icon, item: on_toggle_autostart(),
                              checked=lambda item: is_autostart_enabled()),
            pystray.MenuItem("Controleer op updates",
                              lambda icon, item: on_check_updates and on_check_updates()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afsluiten", self._quit),
        )
        self.icon = pystray.Icon("talkwithme", self._icons["idle"],
                                  TITLES["idle"], menu)

    def _quit(self, icon, item):
        try:
            self._on_quit()
        finally:
            icon.stop()

    def set_state(self, name: str) -> None:
        try:
            self.icon.icon = self._icons.get(name, self._icons["idle"])
            self.icon.title = TITLES.get(name, TITLES["idle"])
        except Exception as e:
            log.debug("kon tray-status niet zetten: %s", e)

    def notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception as e:
            log.debug("tray-notificatie mislukt: %s", e)

    def run_detached(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
