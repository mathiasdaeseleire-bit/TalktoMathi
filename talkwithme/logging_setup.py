from __future__ import annotations

import logging
import logging.handlers

from . import config as config_mod


def setup_logging(debug: bool = False) -> None:
    config_mod.ensure_app_dir()
    root = logging.getLogger("talkwithme")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.handlers.clear()

    fh = logging.handlers.RotatingFileHandler(
        config_mod.LOG_PATH, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(fh)

    if debug:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(ch)
