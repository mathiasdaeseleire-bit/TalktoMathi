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

import numpy as np
import win32gui

from . import __version__
from . import config as config_mod
from . import history as history_mod
from . import notify
from . import paste
from . import meetings as meetings_mod
from . import permissions
from . import postprocess
from . import realtime as realtime_mod
from . import secrets_store
from . import single_instance
from . import tones as tones_mod
from .hook import KeyboardHook, START, STOP, CANCEL, MEETING
from .indicator import Indicator
from .polish import PolishClient
from .recorder import Recorder
from .stt import SttClient, SttError
from .tray import TrayApp
from .ui import (TAB_HISTORY, TAB_MEETINGS, TAB_REPORT, TAB_SETTINGS,
                  MainWindow)

log = logging.getLogger("talkwithme.app")

MONITOR_INTERVAL_S = 0.2
PREWARM_IDLE_S = 60.0
MIN_RECORDING_S = 0.3
SILENT_PEAK = 40        # int16; below this the mic gave us nothing
SILENT_STREAK_ALARM = 2  # silent recordings in a row before we blame the device

MIC_DEAD_MESSAGE = (
    "Er komt geen geluid uit je microfoon.\n"
    "\n"
    "Twee dictaten op rij kwamen leeg terug. Loop dit na, in deze volgorde:\n"
    "\n"
    "  1. Staat je microfoon gedempt? Veel laptops hebben daar een toets\n"
    "     voor, vaak F4 of F8, soms met een lampje erin. Dit is veruit de\n"
    "     meest voorkomende oorzaak.\n"
    "\n"
    "  2. Windows-instellingen > Systeem > Geluid > Invoer: beweegt de\n"
    "     balk als je praat?\n"
    "\n"
    "  3. Zo niet, dan hangt de audiodienst. Rechtsklik Start, kies\n"
    "     'Terminal (beheerder)' en voer uit:\n"
    "     Restart-Service -Name Audiosrv -Force\n"
    "\n"
    "Je opnames en instellingen blijven in alle gevallen staan."
)


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
        self.meeting_recorder = meetings_mod.MeetingRecorder()
        self.meeting_busy = False
        # Notes typed while the meeting runs; the write-up expands these
        # instead of summarising from scratch (see meetings.build_prompt).
        self.meeting_notes_draft = ""
        self.stream_session = None
        # Consecutive dictations that came back as pure silence. Two in a
        # row is a broken microphone, not a quiet user, and it is worth
        # saying so with the fix attached.
        self._silent_streak = 0
        self._build_clients()

        self.root = tk.Tk()
        self.root.title("TalkWithMe")
        self.root.withdraw()  # no main window; tray + popups only
        self._apply_window_icon()
        self.indicator = Indicator(
            self.root,
            lambda: (self.recorder.levels if not self.meeting_recorder.recording
                      else [self.meeting_recorder.level] * 20),
            get_meeting_elapsed=lambda: self.meeting_recorder.elapsed_s())

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
            on_toggle_meeting=self.toggle_meeting,
            is_meeting=self.is_meeting,
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
                if req in ("settings", "history", "report", "meetings"):
                    MainWindow.open(self.root, self.config, self._save_settings,
                                     {"history": TAB_HISTORY,
                                      "report": TAB_REPORT,
                                      "meetings": TAB_MEETINGS,
                                      "settings": TAB_SETTINGS}[req],
                                     controller=self)
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
                elif event == MEETING:
                    self.toggle_meeting()
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
        self._start_streaming()
        self._set_state("recording")
        log.info("opname gestart (exe=%s, toon=%s, streaming=%s)",
                  self.ctx_exe, self.ctx_tone, self.stream_session is not None)

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
            session, self.stream_session = self.stream_session, None
            self.recorder.on_audio = None
            if session is not None:
                session.close()
            log.info("te korte opname (%.2fs), genegeerd", elapsed)
            self._set_state("idle")
            return
        self._set_state("processing")
        try:
            self._process(audio, t0)
        finally:
            # Whatever path _process took, the socket must not be left open.
            session, self.stream_session = self.stream_session, None
            self.recorder.on_audio = None
            if session is not None:
                session.close()
            self._set_state("idle")


    # ---- streaming transcription -----------------------------------

    def _start_streaming(self) -> None:
        """Transcribe while the user is still speaking.

        Connecting costs a moment, but it happens at key-down, hidden
        behind the speech itself. If anything goes wrong the recording is
        untouched and the batch endpoint still runs at the end, so this
        can only make things faster, never lossy.
        """
        self.stream_session = None
        if not self.config.realtime_enabled:
            return
        key = secrets_store.get_elevenlabs_api_key()
        if not key:
            return
        try:
            session = realtime_mod.StreamingTranscriber(
                key, language=self.config.language, commit_strategy="vad")
            session.start()
        except Exception as e:
            log.info("streaming niet beschikbaar, batch wordt gebruikt: %s", e)
            return
        self.stream_session = session
        self.recorder.on_audio = session.feed

    def _finish_streaming(self) -> tuple[str, int]:
        """Returns (text, ms). Empty text means: fall back to batch."""
        session, self.stream_session = self.stream_session, None
        self.recorder.on_audio = None
        if session is None:
            return "", 0
        started = time.monotonic()
        try:
            text = session.finish()
        except Exception as e:
            log.warning("streaming afronden mislukt: %s", e)
            session.close()
            return "", 0
        elapsed = int((time.monotonic() - started) * 1000)
        if session.failed:
            log.warning("streaming eindigde met een fout: %s", session.failed)
            return "", elapsed
        return text.strip(), elapsed

    # ---- pipeline --------------------------------------------------

    def _process(self, audio, t0: float) -> None:
        log.info("audio: %.2fs @ %dHz", len(audio) / self.recorder.rate, self.recorder.rate)

        if not self.stt:
            notify.notify("TalkWithMe", "Geen ElevenLabs-key. Open Instellingen.")
            self._ui_queue.put("settings")
            return

        # A recording that is pure silence means the microphone never
        # delivered anything, not that the user spoke too quietly. Saying
        # so beats sending silence off to be transcribed and then blaming
        # it on "geen spraak herkend", which points at the wrong thing.
        peak = int(np.max(np.abs(audio))) if len(audio) else 0
        if peak < SILENT_PEAK:
            self._silent_streak += 1
            log.warning("opname is stil (piek=%d, terugvalapparaat=%s, op rij=%d)",
                         peak, self.recorder.using_fallback_device, self._silent_streak)
            if self._silent_streak >= SILENT_STREAK_ALARM:
                # Windows sometimes wedges an audio device: it opens without
                # complaint and then delivers nothing at all. Only a restart
                # of the audio service or the machine clears it, so say that
                # instead of letting the user keep dictating into a void.
                self._ui_queue.put(("update_msg", MIC_DEAD_MESSAGE))
                self._silent_streak = 0
            elif self.recorder.using_fallback_device:
                notify.notify("TalkWithMe",
                               "Je microfoon was even bezet, er is niets opgenomen. "
                               "Probeer het zo opnieuw.")
            else:
                notify.notify("TalkWithMe",
                               "Er kwam geen geluid binnen. Staat je microfoon "
                               "gedempt? Kijk naar de mute-toets op je toetsenbord.")
            return

        self._silent_streak = 0

        # The streamed transcript is already waiting; the batch endpoint is
        # only paid for when streaming produced nothing.
        raw_text, stt_ms = self._finish_streaming()
        used_streaming = bool(raw_text)
        if not used_streaming:
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
        cleanup_error = None
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
                cleanup_error = type(e).__name__
                final_text = raw_text

        # Runs whether or not the model was involved: the layout rules are
        # about what the target app does with the text, and a raw
        # transcript pasted into WhatsApp must be single-line too.
        final_text = postprocess.finish(final_text, tone or "default")

        total_ms = int((time.monotonic() - t0) * 1000)
        log.info("klaar: stt_ms=%d cleanup_ms=%d total_ms=%d cleaned=%s toon=%s stream=%s",
                  stt_ms, cleanup_ms, total_ms, cleaned_applied, tone or "—",
                  used_streaming)
        log.info("tekst: %r", final_text)

        delivery = self._deliver(final_text)
        history_mod.add(raw_text, final_text, self.ctx_exe or self.ctx_title,
                         cleaned_applied, tone if cleaned_applied else None,
                         record_s=len(audio) / self.recorder.rate,
                         process_ms=total_ms, stt_ms=stt_ms,
                         cleanup_ms=cleanup_ms, delivery=delivery,
                         cleanup_error=cleanup_error)

    def _deliver(self, text: str) -> str:
        """Never lose the user's words: cursor, else clipboard + notice.
        Returns what actually happened, so the report can show how often
        pasting really lands."""
        try:
            current = win32gui.GetForegroundWindow()
            if current != self.ctx_hwnd:
                log.warning("venster gewisseld, niet geplakt")
                paste.set_clipboard_text(text)
                notify.notify("TalkWithMe", "Venster gewisseld — tekst staat op je klembord.")
                return "clipboard"
            if paste.insert_text(text, self.ctx_exe, self.config.paste_keys,
                                  notify_cb=notify.notify):
                log.info("geplakt in %r", self.ctx_title)
                return "pasted"
            log.warning("plakken mislukt")
            notify.notify("TalkWithMe", "Plakken mislukt — tekst staat op je klembord.")
            return "clipboard"
        except Exception:
            log.exception("fout bij afleveren van tekst")
            try:
                if paste.set_clipboard_text(text):
                    notify.notify("TalkWithMe", "Tekst staat op je klembord.")
                    return "clipboard"
                notify.notify("TalkWithMe", text[:200])
            except Exception:
                notify.notify("TalkWithMe", text[:200])
            return "failed"

    # ---- meetings --------------------------------------------------

    def toggle_meeting(self) -> None:
        """Start or finish a meeting recording. Deliberately independent of
        the dictation state machine: a meeting runs for an hour and must
        not be disturbed by, or disturb, a quick dictation."""
        if self.meeting_recorder.recording:
            self._finish_meeting()
            return
        # Live transcription: the meeting is transcribed while it runs, so
        # the notes are ready when it ends instead of after an upload of an
        # hour of audio. The WAV is still written, so a dropped connection
        # falls back to the batch endpoint.
        key = secrets_store.get_elevenlabs_api_key()
        self.meeting_recorder.transcriber = None
        if key and self.config.realtime_enabled:
            try:
                streamer = realtime_mod.StreamingTranscriber(
                    key, language=self.config.language, commit_strategy="vad")
                streamer.start()
                self.meeting_recorder.transcriber = streamer
            except Exception as e:
                log.info("live transcriptie niet beschikbaar: %s", e)

        try:
            self.meeting_recorder.start()
        except Exception as e:
            log.exception("kon vergaderopname niet starten")
            notify.notify("TalkWithMe", f"Opname starten mislukt: {e}")
            return
        self.indicator.show_meeting()
        self.tray.set_state("meeting")
        both = self.meeting_recorder.system_audio
        notify.notify("TalkWithMe",
                       "Vergadering wordt opgenomen"
                       + (" (jij en de anderen)." if both else
                          " (alleen je microfoon; systeemgeluid is niet beschikbaar).")
                       + " Ctrl+Win+M stopt.")

    def is_meeting(self) -> bool:
        return self.meeting_recorder.recording

    def _finish_meeting(self) -> None:
        meeting = self.meeting_recorder.stop()
        self.indicator.hide()
        self.tray.set_state("idle")
        if meeting is None:
            return
        if meeting.duration_s < 10:
            streamer = self.meeting_recorder.transcriber
            self.meeting_recorder.transcriber = None
            if streamer is not None:
                streamer.close()
            notify.notify("TalkWithMe", "Opname te kort, niets uitgewerkt.")
            return

        self.meeting_busy = True
        self.tray.set_state("processing")
        self.indicator.show_processing()
        notify.notify("TalkWithMe",
                       f"Vergadering van {int(meeting.duration_s // 60)} minuten "
                       f"wordt uitgewerkt...")

        draft = self.meeting_notes_draft
        self.meeting_notes_draft = ""

        def work():
            from . import meetings
            try:
                key = secrets_store.get_elevenlabs_api_key()
                if not key:
                    raise RuntimeError("geen ElevenLabs-key ingesteld")
                transcript = ""
                streamer = self.meeting_recorder.transcriber
                self.meeting_recorder.transcriber = None
                if streamer is not None:
                    try:
                        transcript = streamer.finish(timeout_s=8.0).strip()
                    except Exception as e:
                        log.warning("live transcript afronden mislukt: %s", e)
                        streamer.close()

                if transcript:
                    log.info("live transcript gebruikt (%d tekens)", len(transcript))
                else:
                    # Nothing streamed back: fall back to uploading the file,
                    # which also gets us speaker labels.
                    transcript, _ = meetings.transcribe(
                        meeting, key, self.config.stt_model, self.config.language)
                if not transcript.strip():
                    raise RuntimeError("geen spraak herkend in de opname")

                instruction, payload = meetings.build_prompt(transcript, draft)
                notes = transcript
                if self.cleanup_client:
                    try:
                        notes, _ = self.cleanup_client.cleanup(
                            payload, instruction, timeout_s=180.0)
                    except Exception as e:
                        # The transcript alone is still worth keeping.
                        log.warning("uitwerken mislukt, alleen transcript: %s", e)
                        notes = "_Uitwerken mislukt; hieronder staat het ruwe transcript._"

                meetings.write_notes(meeting, transcript, notes)
                self.tray.notify("TalkWithMe", "Notities klaar.")
                self._ui_queue.put("meetings")
            except Exception as e:
                log.exception("vergadering uitwerken mislukt")
                self._ui_queue.put(("update_msg",
                    "Uitwerken mislukt:\n" + str(e) +
                    "\n\nDe opname is bewaard:\n" + meeting.audio_path))
            finally:
                self.meeting_busy = False
                self.indicator.hide()
                self.tray.set_state("idle")

        threading.Thread(target=work, name="meeting-notes", daemon=True).start()

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
