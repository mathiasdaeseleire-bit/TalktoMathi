"""Meeting notes: record a whole conversation, then write it up.

Different from dictation in every way that matters, so it is a separate
path rather than a longer dictation:

  - It runs for an hour, not eight seconds, so the audio is written to
    disk as it comes in instead of being held in memory.
  - Several people speak, so transcription asks for diarisation and the
    notes are organised by what was decided, not by who said what.
  - Nothing is pasted at the cursor. The result is a document, saved and
    opened, because notes are read later rather than typed into a field.

The recording keeps going even if transcription or the write-up fails —
the audio file stays, so a meeting is never lost to a network error.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import sounddevice as sd

from . import config as config_mod
from .recorder import BLOCKSIZE, RATE, _preferred_input_device

log = logging.getLogger("talkwithme.meetings")

NOTES_DIR = os.path.join(config_mod.APP_DIR, "notities")
MAX_HOURS = 4

NOTES_INSTRUCTION = """You turn a raw meeting transcript into notes someone can act on.

Write the notes in the language the meeting was held in.

Use exactly these headings, in this order, and leave out any section that has no content:

## Samenvatting
Three to five sentences: what this meeting was about and where it landed.

## Besluiten
What was actually decided. One line each, stating the decision, not the discussion.

## Actiepunten
One line per action, formatted as: **wie** - wat - wanneer. Use the name as spoken. Write
"onbekend" where the transcript does not say who or when, rather than guessing.

## Aandachtspunten
Risks, blockers, concerns and dependencies raised in the meeting. One line each. This is
what someone should worry about, not what they should do.

## Besproken
The substance, grouped by subject. Short paragraphs or bullets, not a retelling of the
conversation turn by turn.

## Open vragen
Anything raised and left unresolved.

Rules:
- Use only what is in the transcript. Never invent a decision, an owner, or a date.
- Speaker labels are approximate. If the transcript names someone, prefer that name.
- Drop small talk, filler and repetition.
- No preamble and no closing remark: start at the first heading."""


SYSTEM_SOURCE_HINTS = ("loopback", "stereo mix", "stereo-mix", "stereomix",
                       "wave out mix", "what u hear", "wat u hoort")


def find_system_source() -> int | None:
    """A device that captures what the computer plays.

    Recording only the microphone means a meeting transcript contains one
    side of the conversation: your own. Windows exposes the other side
    through a loopback or "Stereo Mix" input, which is usually present but
    often disabled in the sound settings — hence the probe rather than a
    hard requirement.
    """
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) <= 0:
            continue
        name = (device.get("name") or "").lower()
        if any(hint in name for hint in SYSTEM_SOURCE_HINTS):
            return index
    return None


class _Source:
    """One audio input writing into its own buffer list."""

    def __init__(self, label: str, device: int | None, rate: int):
        self.label = label
        self.device = device
        self.rate = rate
        self.chunks: list[np.ndarray] = []
        self.stream_pos = 0       # how far the live transcriber has consumed
        self.peak = 0
        self.stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _cb(self, indata, frames, time_info, status):
        mono = indata[:, 0] if indata.ndim > 1 else indata
        with self._lock:
            self.chunks.append(mono.copy())
        if len(mono):
            local_peak = int(np.max(np.abs(mono)))
            if local_peak > self.peak:
                self.peak = local_peak

    def start(self) -> None:
        stream = sd.InputStream(samplerate=self.rate, channels=1, dtype="int16",
                                 blocksize=BLOCKSIZE, callback=self._cb,
                                 device=self.device, latency="high")
        stream.start()
        self.stream = stream

    def stop(self) -> np.ndarray:
        try:
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None
        with self._lock:
            if not self.chunks:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self.chunks)


def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(audio) == 0:
        return audio
    duration = len(audio) / source_rate
    target_len = int(duration * target_rate)
    source_index = np.linspace(0, len(audio) - 1, target_len)
    return np.interp(source_index, np.arange(len(audio)),
                      audio.astype(np.float64)).astype(np.int16)


def mix(tracks: list[np.ndarray], rate: int) -> np.ndarray:
    """Sum the sources into one mono track, scaled down only if the sum
    would clip. Transcription cares about intelligibility, not loudness."""
    tracks = [t for t in tracks if len(t)]
    if not tracks:
        return np.zeros(0, dtype=np.int16)
    if len(tracks) == 1:
        return tracks[0]

    longest = max(len(t) for t in tracks)
    total = np.zeros(longest, dtype=np.float64)
    for track in tracks:
        padded = np.zeros(longest, dtype=np.float64)
        padded[:len(track)] = track
        total += padded

    peak = np.max(np.abs(total))
    if peak > 32767:
        total *= 32767 / peak
    return total.astype(np.int16)


ENHANCE_INSTRUCTION = """You expand the notes someone typed during a meeting, using the transcript
of that meeting as the source of detail.

Their notes are the outline and the priorities: they wrote down what mattered to them.
The transcript fills in what they did not have time to type.

Write in the language of the notes, or of the meeting if the notes are too short to tell.

How to work:
- Keep every point they wrote, in their order. Never drop one because the transcript
  covers it lightly.
- Flesh each point out with the specifics from the transcript: names, numbers, dates,
  what was decided, who objected.
- Where their note is a shorthand or an abbreviation, expand it only if the transcript
  makes the meaning unambiguous. Otherwise leave it as they wrote it.
- Add a point they did not write ONLY when the transcript contains a decision or an
  action item. Mark those additions with a leading "+ " so they can see what they
  did not capture themselves.
- Never invent a decision, an owner or a date. Write "onbekend" where the transcript
  does not say.

Then, below their expanded notes, add these sections, leaving out any that would be empty:

## Besluiten
## Actiepunten
One line per action, formatted as: **wie** - wat - wanneer.
## Aandachtspunten
Risks, blockers and concerns raised. What someone should worry about, not do.
## Open vragen

Start with the heading "## Mijn notities" followed by their expanded notes.
No preamble and no closing remark."""


@dataclass
class Meeting:
    started: datetime
    audio_path: str
    duration_s: float


class MeetingRecorder:
    """Records the meeting from both sides.

    The microphone carries you; a loopback or "Stereo Mix" input carries
    everyone else in the call. Both are captured separately and mixed when
    the recording stops, so a failure on either side still leaves a usable
    file. If no system source is available the meeting is still recorded,
    just one-sided — `system_audio` says which happened, so the interface
    can be honest about it rather than quietly losing half the meeting.
    """

    def __init__(self):
        self.recording = False
        self.started_at: datetime | None = None
        self.system_audio = False
        # Live transcription, fed by a pump thread rather than from the
        # audio callbacks: two sources have to be mixed before they can be
        # sent as one stream, and that is not callback work.
        self.transcriber = None
        self._pump: threading.Thread | None = None
        self._pump_stop = threading.Event()
        self.level = 0.0
        self.rate = RATE
        self._sources: list[_Source] = []
        self._path: str | None = None
        self._start_monotonic = 0.0

    def _device_rate(self, device: int | None, default: int = RATE) -> int:
        if device is None:
            return default
        try:
            return int(sd.query_devices(device)["default_samplerate"])
        except Exception:
            return default

    def start(self) -> str:
        os.makedirs(NOTES_DIR, exist_ok=True)
        self.started_at = datetime.now()
        stamp = self.started_at.strftime("%Y-%m-%d_%H-%M")
        self._path = os.path.join(NOTES_DIR, f"vergadering_{stamp}.wav")

        mic_device = _preferred_input_device()
        mic_rate = self._device_rate(mic_device)
        self.rate = mic_rate

        sources: list[_Source] = []
        mic = _Source("microfoon", mic_device, mic_rate)
        try:
            mic.start()
            sources.append(mic)
        except Exception as e:
            log.warning("microfoon niet beschikbaar voor de vergadering: %s", e)

        system_device = find_system_source()
        self.system_audio = False
        if system_device is not None:
            system = _Source("systeemgeluid", system_device,
                              self._device_rate(system_device, mic_rate))
            try:
                system.start()
                sources.append(system)
                self.system_audio = True
                log.info("systeemgeluid wordt meegenomen (apparaat %d)", system_device)
            except Exception as e:
                log.warning("systeemgeluid niet beschikbaar: %s", e)
        else:
            log.info("geen bron voor systeemgeluid gevonden; alleen de microfoon")

        if not sources:
            raise RuntimeError("geen enkele geluidsbron beschikbaar")

        self._sources = sources
        self._start_monotonic = time.monotonic()
        self.recording = True
        if self.transcriber is not None:
            self._pump_stop.clear()
            self._pump = threading.Thread(target=self._pump_loop,
                                           name="meeting-stream", daemon=True)
            self._pump.start()
        log.info("vergaderopname gestart: %s (%d bron(nen))", self._path, len(sources))
        return self._path

    def elapsed_s(self) -> float:
        if not self.recording:
            return 0.0
        return time.monotonic() - self._start_monotonic

    def _drain(self) -> np.ndarray:
        """Take everything captured since the last pass, mixed into one
        track at the recorder's rate."""
        tracks = []
        for source in self._sources:
            with source._lock:
                pending = source.chunks[source.stream_pos:]
                source.stream_pos = len(source.chunks)
            if not pending:
                continue
            audio = np.concatenate(pending)
            tracks.append(_resample(audio, source.rate, self.rate))
        return mix(tracks, self.rate)

    def _pump_loop(self) -> None:
        while not self._pump_stop.is_set():
            time.sleep(0.25)
            try:
                chunk = self._drain()
                if len(chunk) and self.transcriber is not None:
                    self.transcriber.feed(chunk, self.rate)
            except Exception as e:
                log.debug("live transcriptie overslaan: %s", e)

    def stop(self) -> Meeting | None:
        if not self.recording:
            return None
        self.recording = False
        duration = self.elapsed_s()

        self._pump_stop.set()
        if self._pump is not None:
            self._pump.join(timeout=1.0)
            self._pump = None
        try:
            if self.transcriber is not None:
                leftover = self._drain()
                if len(leftover):
                    self.transcriber.feed(leftover, self.rate)
        except Exception:
            pass

        tracks: list[np.ndarray] = []
        for source in self._sources:
            audio = source.stop()
            if len(audio):
                tracks.append(_resample(audio, source.rate, self.rate))
            log.info("bron %s: piek=%d", source.label, source.peak)
        self._sources = []

        path, self._path = self._path, None
        if path is None:
            return None

        mixed = mix(tracks, self.rate)
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.rate)
                wf.writeframes(mixed.tobytes())
        except Exception as e:
            log.exception("kon de opname niet wegschrijven: %s", e)
            return None

        log.info("vergaderopname gestopt: %.0fs, piek=%d",
                  duration, int(np.max(np.abs(mixed))) if len(mixed) else 0)
        return Meeting(started=self.started_at or datetime.now(),
                        audio_path=path, duration_s=duration)

    @property
    def peak(self) -> int:
        return max((s.peak for s in self._sources), default=0)


def transcribe(meeting: Meeting, api_key: str, model: str,
               language: str = "auto") -> tuple[str, dict]:
    """Batch transcription with speaker diarisation. Returns the transcript
    laid out per speaker, plus the raw response."""
    import httpx

    with open(meeting.audio_path, "rb") as f:
        audio = f.read()

    data = {"model_id": model, "diarize": "true", "tag_audio_events": "false"}
    if language and language != "auto":
        data["language_code"] = language

    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=900.0,
                                             write=600.0, pool=10.0)) as client:
        resp = client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": api_key}, data=data,
            files={"file": (os.path.basename(meeting.audio_path), audio, "audio/wav")})

    if resp.status_code != 200:
        raise RuntimeError(f"transcriptie mislukt: HTTP {resp.status_code} "
                            f"{resp.text[:300]}")

    payload = resp.json()
    return format_by_speaker(payload), payload


def format_by_speaker(payload: dict) -> str:
    """Group the word list into turns, so the model sees a conversation
    rather than one undifferentiated block."""
    words = payload.get("words") or []
    if not words:
        return (payload.get("text") or "").strip()

    lines: list[str] = []
    current_speaker = None
    buffer: list[str] = []

    def flush():
        if buffer:
            text = "".join(buffer).strip()
            if text:
                who = current_speaker or "spreker"
                lines.append(f"{who}: {text}")
        buffer.clear()

    for word in words:
        kind = word.get("type")
        if kind == "audio_event":
            continue
        speaker = word.get("speaker_id") or current_speaker
        if speaker != current_speaker:
            flush()
            current_speaker = speaker
        text = word.get("text", "")
        # Some responses carry explicit "spacing" entries, others only
        # words. Insert the space ourselves when the payload did not, or
        # the whole turn comes back as one run-on string.
        if (kind != "spacing" and buffer
                and not text[:1].isspace()
                and not buffer[-1][-1:].isspace()):
            buffer.append(" ")
        buffer.append(text)
    flush()
    return "\n".join(lines)


def build_prompt(transcript: str, draft: str) -> tuple[str, str]:
    """Which instruction to use, and what to send with it.

    With notes typed during the meeting, those lead and the transcript
    fills them in — that keeps the result shaped like the user's own
    thinking. Without them, there is nothing to enhance and it falls back
    to writing the notes from scratch.
    """
    if draft.strip():
        payload = ("MIJN NOTITIES:\n" + draft.strip()
                    + "\n\nTRANSCRIPT:\n" + transcript.strip())
        return ENHANCE_INSTRUCTION, payload
    return NOTES_INSTRUCTION, transcript


def write_notes(meeting: Meeting, transcript: str, notes: str) -> str:
    """Save as markdown next to the audio, with the transcript kept below
    the notes so a wrong summary can always be checked against the source."""
    os.makedirs(NOTES_DIR, exist_ok=True)
    stamp = meeting.started.strftime("%Y-%m-%d_%H-%M")
    path = os.path.join(NOTES_DIR, f"vergadering_{stamp}.md")

    minutes = int(meeting.duration_s // 60)
    header = (f"# Vergadering {meeting.started.strftime('%d-%m-%Y %H:%M')}\n\n"
              f"Duur: {minutes} minuten  \n"
              f"Opname: `{os.path.basename(meeting.audio_path)}`\n\n---\n\n")
    body = notes.strip() + "\n\n---\n\n## Transcript\n\n" + transcript.strip() + "\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + body)
    log.info("notities opgeslagen: %s", path)
    return path


def open_in_editor(path: str) -> None:
    try:
        os.startfile(path)
    except Exception as e:
        log.warning("kon notities niet openen: %s", e)


# ---- browsing saved meetings ----------------------------------------

@dataclass
class SavedMeeting:
    stamp: str          # 2026-08-20_14-05
    notes_path: str
    audio_path: str | None

    @property
    def when(self) -> datetime | None:
        try:
            return datetime.strptime(self.stamp, "%Y-%m-%d_%H-%M")
        except ValueError:
            return None

    @property
    def label(self) -> str:
        when = self.when
        return when.strftime("%d-%m-%Y  %H:%M") if when else self.stamp


def list_meetings() -> list[SavedMeeting]:
    """Newest first. Driven by the notes files, since audio without notes
    means the write-up failed and there is nothing to show yet."""
    if not os.path.isdir(NOTES_DIR):
        return []
    found: list[SavedMeeting] = []
    for name in os.listdir(NOTES_DIR):
        if not (name.startswith("vergadering_") and name.endswith(".md")):
            continue
        stamp = name[len("vergadering_"):-len(".md")]
        audio = os.path.join(NOTES_DIR, f"vergadering_{stamp}.wav")
        found.append(SavedMeeting(
            stamp=stamp,
            notes_path=os.path.join(NOTES_DIR, name),
            audio_path=audio if os.path.exists(audio) else None))
    return sorted(found, key=lambda m: m.stamp, reverse=True)


def read_meeting(meeting: SavedMeeting) -> tuple[str, str]:
    """Returns (notes, transcript). The file keeps both, split by the
    transcript heading that write_notes puts in."""
    try:
        with open(meeting.notes_path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return f"Kon de notities niet lezen: {e}", ""

    marker = chr(10) + "## Transcript" + chr(10)
    if marker in content:
        notes, transcript = content.split(marker, 1)
        return notes.rstrip().removesuffix("---").rstrip(), transcript.strip()
    return content.strip(), ""


def delete_meeting(meeting: SavedMeeting) -> None:
    for path in (meeting.notes_path, meeting.audio_path):
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            log.warning("kon %s niet verwijderen: %s", path, e)
