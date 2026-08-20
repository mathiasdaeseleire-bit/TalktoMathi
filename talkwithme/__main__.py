from __future__ import annotations

import argparse
import sys

from . import secrets_store
from .logging_setup import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(prog="talkwithme")
    parser.add_argument("--debug", action="store_true", help="log naar console + verbose logging")
    parser.add_argument("--set-elevenlabs-key", metavar="KEY", help="ElevenLabs API-key instellen en afsluiten")
    parser.add_argument("--set-gemini-key", metavar="KEY", help="Gemini API-key instellen en afsluiten")
    parser.add_argument("--show-key-status", action="store_true", help="tonen welke keys zijn opgeslagen")
    parser.add_argument("--install", action="store_true",
                        help="kopieer naar %%LOCALAPPDATA%%, maak Start-menu-snelkoppeling, start bij inloggen")
    parser.add_argument("--uninstall", action="store_true",
                        help="snelkoppeling en autostart verwijderen")
    args = parser.parse_args()

    # Before anything reads config or keys: the app was renamed, and
    # an existing install must not come back up looking empty.
    from . import migrate
    migrate.run()

    if args.set_elevenlabs_key or args.set_gemini_key:
        if args.set_elevenlabs_key:
            secrets_store.set_elevenlabs_api_key(args.set_elevenlabs_key.strip())
            print("ElevenLabs-key opgeslagen.")
        if args.set_gemini_key:
            secrets_store.set_gemini_api_key(args.set_gemini_key.strip())
            print("Gemini-key opgeslagen.")
        return 0

    if args.install:
        from . import install as install_mod
        try:
            path = install_mod.install()
        except RuntimeError as e:
            print(e)
            return 1
        print(f"Geinstalleerd: {path}")
        print(f"Start-menu:    {install_mod.SHORTCUT_PATH}")
        print("Start bij inloggen staat aan.")
        print()
        print("Vastmaken aan de taakbalk: druk op Start, typ TalkWithMe,")
        print("rechtsklik het resultaat en kies 'Aan taakbalk vastmaken'.")
        return 0

    if args.uninstall:
        from . import install as install_mod
        install_mod.uninstall()
        print("Snelkoppeling en autostart verwijderd.")
        print(f"De bestanden staan nog in: {install_mod.INSTALL_DIR}")
        return 0

    if args.show_key_status:
        print("ElevenLabs-key aanwezig:", bool(secrets_store.get_elevenlabs_api_key()))
        print("Gemini-key aanwezig:    ", bool(secrets_store.get_gemini_api_key()))
        return 0

    setup_logging(debug=args.debug)

    # Clicking the shortcut while it already runs used to look like
    # nothing happened: the app has no main window. Hand over instead.
    from . import single_instance
    if not single_instance.acquire():
        single_instance.signal_show()
        return 0
    single_instance.clear()

    from .app import App
    App(debug=args.debug).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
