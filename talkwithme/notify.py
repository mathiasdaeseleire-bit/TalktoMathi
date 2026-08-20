"""Windows toast notifications."""
from __future__ import annotations

import logging

log = logging.getLogger("talkwithme.notify")


def notify(title: str, message: str) -> None:
    try:
        from winotify import Notification
        n = Notification(app_id="TalkWithMe", title=title, msg=message, duration="short")
        n.show()
    except Exception as e:
        log.debug("toast-notificatie mislukt: %s", e)
