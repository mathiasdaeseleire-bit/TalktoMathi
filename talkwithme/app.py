"""Orchestration: hold Ctrl+Win -> record -> Scribe v2 -> Gemini cleanup -> paste.

Threads:
  - hook thread   : low-level keyboard hook, only pushes START/STOP/CANCEL
  - worker thread : all the real work (audio, network, clipboard, paste)
  - monitor thread: max-duration guard
  - tray thread   : pystray, detached
  - main thread   : Tk (indicator, settings, history windows)

Anything touching Tk is marshalled onto the main thread via _ui_queue,
because Tk is not thread-safe.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk

import win32gui

from . import __version__
from . import config as config_mod
from . import history as history_mod
from . import notify
from . import paste
from . import permissions
from . import postprocess
from . import secrets_store
from . import single_instance
from . import tones as tones_mod
from .hook import KeyboardHook, START, STOP, CANCEL
from .indicator import Indicator
from .polish import PolishClient
from .recorder import Recorder
from .stt import SttClient, SttError
from .tray import TrayApp
from .ui import TAB_HISTORY, TAB_REPORT, TAB_SETTINGS, MainWindow

log = logging.getLogger("talkwithme.app")

MONITOR_INTERVAL_S = 0.2
PREWARM_IDLE_S = 60.0
MIN_RECORDING_S = 0.3


class App:
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.config = config_mod.load_config()
        self.event_queue: "queue.Queue[str]" = queue.Queue()
        self._ui_queue: "queue.Queue" = queue.Queue()

        self.state = "idle"  # idle | recording | processing
        self._state_lock = threading.Lock()
        self._last_activity_ts = time.monotonic()

        self.recorder = Recorder()
        self._build_clients()

        self.root = tk.Tk()
        self.root.withdraw()  # no main window; tray + popups only
        self._apply_window_icon()
        self.indicator = Indicator(self.root, lambda: self.recorder.levels)

        self.tray = TrayApp(
            on_quit=self.quit,
            on_settings=lambda: self._ui_queue.put("settings"),
            on_history=lambda: self._ui_queue.put("history"),
            on_report=lambda: self._ui_queue.put("report"),
            on_toggle_cleanup=self._toggle_cleanup,
            is_cleanup_enabled=lambda: self.config.cleanup_enabled,
            on_toggle_tone=self._toggle_tone,
            is_tone_enabled=lambda: self.config.tone_enabled,
            on_toggle_autostart=self._toggle_autostart,
            is_autostart_enabled=self._autostart_enabled,
            on_check_updates=lambda: self.check_updates(manual=True),
        )

        self.hook = KeyboardHook(
            self.event_queue,
            is_active_cb=lambda: self.state == "recording",
        )

        self._stop = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker_loop, name="worker", daemon=True)
        self._monitor_thread = threading.Thread(target=self._monitor_loop, name="monitor", daemon=True)
        self._prewarm_thread = threading.Thread(target=self._prewarm_loop, name="prewarm", daemon=True)

    def _apply_window_icon(self) -> None:
        """Same mark in the title bar and taskbar as in the tray. Tk needs
        it as an .ico on disk, so generate one next to the config."""
        try:
            import os
            from .icon import save_ico
            path = os.path.join(config_mod.APP_DIR, "talkwithme.ico")
            if not os.path.exists(path):
                save_ico(path)
            self.root.iconbitmap(default=path)
        except Exception as e:
            log.debug("kon venster-icoon niet zetten: %s", e)

    def _build_clients(self) -> None:
        el_key = secrets_store.get_elevenlabs_api_key()
        gm_key = secrets_store.get_gemini_api_key()
        self.stt = SttClient(el_key, self.config.stt_model, self.config.language) if el_key else None
        self.cleanup_client = PolishClient(gm_key, self.config.cleanup_model) if gm_key else None
        if not el_key:
            log.warning("Geen ElevenLabs-key — open Instellingen om er een te zetten.")

    # ---- lifecycle -------------------------------------------------

    def run(self) -> None:
        if not permissions.microphone_allowed():
            log.warning("microfoontoegang staat op Deny")
            self._ui_queue.put("mic_denied")

        if self.stt is None:
            self._ui_queue.put("settings")

        self.hook.start()
        self._worker_thread.start()
        self._monitor_thread.start()
        self._prewarm_thread.start()
        self.tray.run_detached()
        log.info("TalkWithMe gestart (hold Ctrl+Win)")

        self.root.after(100, self._pump_ui)
        if self.config.update_check_enabled:
            # Delayed so a slow network can't hold up startup.
            self.root.after(8000, lambda: self.check_updates(manual=False))
        self.root.mainloop()

    def quit(self) -> None:
        log.info("Afsluiten...")
        self._stop.set()
        try:
            self.hook.stop()
        except Exception:
            pass
        try:
            self.recorder.close()
        except Exception:
            pass
        if self.stt:
            self.stt.close()
        try:
            self.root.after(0, self.root.quit)
        except Exception:
            pass

    # ---- Tk main-thread pump ---------------------------------------

    def _pump_ui(self) -> None:
        try:
            while True:
                try:
                    req = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                if req in ("settings", "history", "report"):
                    MainWindow.open(self.root, self.config, self._save_settings,
                                     {"history": TAB_HISTORY,
                                      "report": TAB_REPORT,
                                      "settings": TAB_SETTINGS}[req])
                elif isinstance(req, tuple) and req[0] == "update":
                    self._offer_update(req[1])
                elif isinstance(req, tuple) and req[0] == "update_msg":
                    from tkinter import messagebox
                    messagebox.showinfo("TalkWithMe — updates", req[1])
                elif req == "mic_denied":
                    from tkinter import messagebox
                    messagebox.showwarning("TalkWithMe — microfoon", permissions.MESSAGE)
                    permissions.open_privacy_settings()
        except Exception:
            log.exception("fout in UI-pomp")
        finally:
            self.root.after(100, self._pump_ui)

    def _save_settings(self, cleanup_enabled: bool, instructions: str,
                        tone_enabled: bool, tone_instructions: dict,
                        update_repo: str = None) -> None:
        self.config.cleanup_enabled = cleanup_enabled
        self.config.cleanup_instructions = instructions
        self.config.tone_enabled = tone_enabled
        self.config.tone_instructions = tone_instructions
        if update_repo is not None:
            self.config.update_repo = update_repo.strip()
        self.config.save()
        self._build_clients()  # keys may have changed
        log.info("instellingen opgeslagen (cleanup=%s, toon=%s)",
                  cleanup_enabled, tone_enabled)

    def _toggle_cleanup(self) -> None:
        self.config.cleanup_enabled = not self.config.cleanup_enabled
        self.config.save()
        log.info("opschonen %s", "aan" if self.config.cleanup_enabled else "uit")

    def _toggle_tone(self) -> None:
        self.config.tone_enabled = not self.config.tone_enabled
        self.config.save()
        log.info("toon-aanpassing %s", "aan" if self.config.tone_enabled else "uit")

    def _autostart_enabled(self) -> bool:
        try:
            from . import autostart
            return autostart.is_enabled()
        except Exception:
            return False

    def _toggle_autostart(self) -> None:
        try:
            from . import autostart
            if autostart.is_enabled():
                autostart.disable()
            else:
                autostart.enable()
        except Exception as e:
            log.warning("autostart wijzigen mislukt: %s", e)

    # ---- worker ----------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.event_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._last_activity_ts = time.monotonic()
            try:
                if event == START:
                    self._on_start()
                elif event == STOP:
                    self._on_stop()
                elif event == CANCEL:
                    self._on_cancel()
            except Exception:
                log.exception("onverwachte fout bij event %s", event)
                self._set_state("idle")

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            self.state = state
        self.tray.set_state(state if state != "idle" else "idle")
        if state == "recording":
            self.indicator.show_listening()
        elif state == "processing":
            self.indicator.show_processing()
        else:
            self.indicator.hide()

    def _on_start(self) -> None:
        with self._state_lock:
            if self.state != "idle":
                return
        self.ctx_hwnd = win32gui.GetForegroundWindow()
        self.ctx_title = win32gui.GetWindowText(self.ctx_hwnd) or ""
        self.ctx_exe = ""
        try:
            import psutil
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(self.ctx_hwnd)
            if pid:
                self.ctx_exe = psutil.Process(pid).name().lower()
        except Exception:
            pass
        # Resolve tone from the window that had focus when recording began —
        # not at paste time, when a notification could have stolen focus.
        self.ctx_tone = tones_mod.resolve(
            self.ctx_exe, self.ctx_title,
            self.config.exe_tones, self.config.title_tones,
        )
        try:
            self.recorder.start()
        except Exception as e:
            log.exception("kon opname niet starten")
            notify.notify("TalkWithMe", f"Microfoon niet beschikbaar: {e}")
            self._set_state("idle")
            return
        self._set_state("recording")
        log.info("opname gestart (exe=%s, toon=%s)", self.ctx_exe, self.ctx_tone)

    def _on_cancel(self) -> None:
        with self._state_lock:
            if self.state != "recording":
                return
        self.recorder.stop()
        self._set_state("idle")
        log.info("opname geannuleerd (ESC)")

    def _on_stop(self) -> None:
        with self._state_lock:
            if self.state != "recording":
                return
        t0 = time.monotonic()
        elapsed = self.recorder.recording_elapsed_s()
        audio = self.recorder.stop()
        if elapsed < MIN_RECORDING_S or audio is None or len(audio) == 0:
            log.info("te korte opname (%.2fs), genegeerd", elapsed)
            self._set_state("idle")
            return
        self._set_state("processing")
        try:
            self._process(audio, t0)
        finally:
            self._set_state("idle")

    # ---- pipeline --------------------------------------------------

    def _process(self, audio, t0: float) -> None:
        log.info("audio: %.2fs @ %dHz", len(audio) / self.recorder.rate, self.recorder.rate)

        if not self.stt:
            notify.notify("TalkWithMe", "Geen ElevenLabs-key. Open Instellingen.")
            self._ui_queue.put("settings")
            return

        try:
            raw_text, stt_ms = self.stt.transcribe(audio, self.recorder.rate)
        except SttError as e:
            log.warning("STT mislukt: %s", e)
            notify.notify("TalkWithMe", f"Spraakherkenning mislukt: {e}")
            return

        if not raw_text:
            log.info("geen spraak herkend")
            return

        final_text = raw_text
        cleanup_ms = 0
        cleaned_applied = False
        tone = self.ctx_tone if self.config.tone_enabled else None
        if self.config.cleanup_enabled and self.cleanup_client:
            instructions = tones_mod.build_instructions(
                self.config.cleanup_instructions, tone or "default",
                self.config.tone_instructions if tone else {"default": ""})
            try:
                final_text, cleanup_ms = self.cleanup_client.cleanup(raw_text, instructions)
                cleaned_applied = True
            except Exception as e:
                log.warning("opschonen mislukt, ruwe tekst plakken: %s", e)
                final_text = raw_text

        # Runs whether or not the model was involved: the layout rules are
        # about what the target app does with the text, and a raw
        # transcript pasted into WhatsApp must be single-line too.
        final_text = postprocess.finish(final_text, tone or "default")

        total_ms = int((time.monotonic() - t0) * 1000)
        log.info("klaar: stt_ms=%d cleanup_ms=%d total_ms=%d cleaned=%s toon=%s",
                  stt_ms, cleanup_ms, total_ms, cleaned_applied, tone or "—")
        log.info("tekst: %r", final_text)

        history_mod.add(raw_text, final_text, self.ctx_exe or self.ctx_title,
                         cleaned_applied, tone if cleaned_applied else None,
                         record_s=len(audio) / self.recorder.rate,
                         process_ms=total_ms)
        self._deliver(final_text)

    def _deliver(self, text: str) -> None:
        """Never lose the user's words: cursor, else clipboard + notice."""
        try:
            current = win32gui.GetForegroundWindow()
            if current != self.ctx_hwnd:
                log.warning("venster gewisseld, niet geplakt")
                paste.set_clipboard_text(text)
                notify.notify("TalkWithMe", "Venster gewisseld — tekst staat op je klembord.")
                return
            if paste.insert_text(text, self.ctx_exe, self.config.paste_keys,
                                  notify_cb=notify.notify):
                log.info("geplakt in %r", self.ctx_title)
                return
            log.warning("plakken mislukt")
            notify.notify("TalkWithMe", "Plakken mislukt — tekst staat op je klembord.")
        except Exception:
            log.exception("fout bij afleveren van tekst")
            try:
                if paste.set_clipboard_text(text):
                    notify.notify("TalkWithMe", "Tekst staat op je klembord.")
                else:
                    notify.notify("TalkWithMe", text[:200])
            except Exception:
                notify.notify("TalkWithMe", text[:200])

    # ---- monitor / prewarm -----------------------------------------

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(MONITOR_INTERVAL_S)
            with self._state_lock:
                recording = self.state == "recording"

            # Watchdog: if the hook missed a keyup (Windows can swallow one
            # when the Start menu steals focus), we'd otherwise stay "held"
            # forever and every later Ctrl press would start a recording.
            # Reconciling against real key state un-sticks that.
            self.hook.sync_from_physical()

            if single_instance.consume_show_request():
                self._ui_queue.put("history")

            if recording and self.recorder.recording_elapsed_s() >= self.config.max_duration_s:
                log.info("max_duration bereikt, automatisch afronden")
                self.event_queue.put(STOP)

            if self.hook._thread is not None and not self.hook._thread.is_alive():
                log.warning("keyboard hook gestopt — herstart")
                self.hook.start()
    # ---- updates ---------------------------------------------------

    NO_REPO_MESSAGE = (
        "Er is nog geen GitHub-repository ingesteld."
        "\n\nVul die in bij Instellingen, bijvoorbeeld:\n  jouwnaam/talkwithme"
    )

    def check_updates(self, manual: bool = False) -> None:
        """Ask GitHub for a newer release. Runs off the UI thread; results
        come back through _ui_queue. The silent startup check stays quiet
        unless there is actually something to install."""
        def work():
            from . import updater
            repo = self.config.update_repo
            if not repo:
                if manual:
                    self._ui_queue.put(("update_msg", self.NO_REPO_MESSAGE))
                return
            try:
                release = updater.check(repo)
            except updater.UpdateError as e:
                log.warning("update-controle mislukt: %s", e)
                if manual:
                    self._ui_queue.put(("update_msg", "Controleren mislukt:\n" + str(e)))
                return
            if release is None:
                log.info("geen update beschikbaar (huidige versie %s)", __version__)
                if manual:
                    self._ui_queue.put(("update_msg",
                                        "Je hebt de nieuwste versie (%s)." % __version__))
                return
            log.info("update beschikbaar: %s", release.version)
            self._ui_queue.put(("update", release))

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _offer_update(self, release) -> None:
        from tkinter import messagebox

        notes = release.notes.strip()
        if len(notes) > 600:
            notes = notes[:600].rsplit("\n", 1)[0] + "\n..."

        lines = [
            "Versie %s is beschikbaar (je hebt %s)." % (release.version, __version__),
            "",
            "Download: %.0f MB" % release.size_mb,
        ]
        if notes:
            lines += ["", notes]
        lines += ["", "Nu bijwerken? De app sluit even af en start opnieuw."]

        if not messagebox.askyesno("TalkWithMe - update", "\n".join(lines)):
            return

        def work():
            from . import updater
            try:
                path = updater.download(release)
                self.tray.notify("TalkWithMe", "Update gedownload, herstarten...")
                updater.apply_and_restart(path)
            except updater.UpdateError as e:
                log.warning("update mislukt: %s", e)
                self._ui_queue.put(("update_msg", "Bijwerken mislukt:\n" + str(e)))
                return
            # The batch script waits for this process to exit before it
            # swaps the files, so quitting is what completes the update.
            self.root.after(0, self.quit)

        threading.Thread(target=work, name="update-apply", daemon=True).start()

    def _prewarm_loop(self) -> None:
        while not self._stop.is_set():
            with self._state_lock:
                idle = self.state == "idle"
            if idle and time.monotonic() - self._last_activity_ts >= PREWARM_IDLE_S:
                self._last_activity_ts = time.monotonic()
                if self.stt:
                    self.stt.prewarm()
                if self.cleanup_client:
                    self.cleanup_client.prewarm()
            time.sleep(5.0)
