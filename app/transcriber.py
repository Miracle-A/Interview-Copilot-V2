import json
import logging
import threading

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveTranscriptionEvents,
)

from app import events
from app.audio import CAPTURE_CHANNELS, CAPTURE_RATE

FINALIZE_TIMEOUT_S = 1.0
# In auto (hands-free) mode: how long a pause ends the question.
UTTERANCE_END_MS = 1200

log = logging.getLogger("app.transcriber")


def _quiet_deepgram_loggers():
    # The SDK force-sets its module loggers to verbose levels; clamp them.
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("deepgram"):
            logging.getLogger(name).setLevel(logging.WARNING)


class DeepgramTranscriber:
    """Persistent Deepgram live session (nova-3). Collects one turn's
    transcript at a time and reports live interim captions through the emit
    callback. In auto mode, fires on_utterance_end when the speaker pauses."""

    def __init__(self, api_key: str, emit,
                 language: str = "en",
                 keyterms: list[str] | None = None,
                 on_utterance_end=None,
                 on_status=None):
        self.emit = emit
        self.language = language
        self.keyterms = list(keyterms or [])
        self.on_utterance_end = on_utterance_end or (lambda: None)
        self.on_status = on_status or (lambda connected: None)
        options = DeepgramClientOptions(
            api_key=api_key,
            verbose=logging.WARNING,
            options={"keepalive": "true"},  # SDK pings itself; no app thread needed
        )
        self.deepgram = DeepgramClient(api_key, options)
        _quiet_deepgram_loggers()
        self.dg_connection = None

        self._parts: list[str] = []
        self._collecting = False
        self._awaiting_finalize = False
        self._finalized = threading.Event()
        self._connected = False
        self.turn_id = 0

    def _build_live_options(self) -> LiveOptions:
        opts = LiveOptions(
            model="nova-3",
            language=self.language,
            encoding="linear16",
            channels=CAPTURE_CHANNELS,
            sample_rate=CAPTURE_RATE,
            punctuate=True,
            smart_format=True,
            numerals=True,
            endpointing="400",
            interim_results=True,
            utterance_end_ms=str(UTTERANCE_END_MS),
            vad_events=True,
        )
        # Nova-3 keyterm prompting: company/tech names from the profile so the
        # words that matter most don't get mangled. English-only feature.
        if self.keyterms and self.language.startswith("en"):
            opts.keyterm = self.keyterms
        return opts

    # -- connection ---------------------------------------------------------

    def start_session(self):
        # A websocket client can't be restarted after a drop; build a fresh
        # one each session and let the old one get garbage-collected.
        self._close_connection()
        conn = self.deepgram.listen.websocket.v("1")
        conn.on(LiveTranscriptionEvents.Transcript, self._on_message)
        conn.on(LiveTranscriptionEvents.UtteranceEnd, self._on_utterance_end)
        conn.on(LiveTranscriptionEvents.Error, self._on_error)
        conn.on(LiveTranscriptionEvents.Close, self._on_close)
        if conn.start(self._build_live_options()) is False:
            raise ConnectionError("Deepgram websocket refused to start")
        self.dg_connection = conn
        self._connected = True
        self.on_status(True)

    def ensure_connected(self):
        if not self._connected or self.dg_connection is None:
            self.start_session()

    @property
    def connected(self) -> bool:
        return self._connected

    def set_language(self, language: str):
        self.language = language

    def set_keyterms(self, keyterms: list[str]):
        self.keyterms = list(keyterms)

    def send_audio(self, data: bytes):
        if self.dg_connection is None:
            return
        try:
            self.dg_connection.send(data)
        except Exception:
            self._connected = False
            self.on_status(False)
            raise

    def _close_connection(self):
        conn, self.dg_connection = self.dg_connection, None
        self._connected = False
        if conn is not None:
            try:
                conn.finish()
            except Exception:
                pass

    # -- turn lifecycle (called from the engine worker thread) ---------------

    def begin_turn(self, turn_id: int):
        self.turn_id = turn_id
        self._parts.clear()
        self._awaiting_finalize = False
        self._finalized.clear()
        self._collecting = True

    def has_speech(self) -> bool:
        return bool(self._parts)

    def finalize_turn(self) -> str:
        """Flush Deepgram's buffer and return the full transcript."""
        self._awaiting_finalize = True
        self._finalized.clear()
        try:
            self.dg_connection.send(json.dumps({"type": "Finalize"}))
        except Exception as e:
            self._connected = False
            self.on_status(False)
            self.emit(events.make_event(
                events.ERROR, scope="deepgram",
                message=f"Finalize failed: {e}", recoverable=True,
            ))
        if not self._finalized.wait(timeout=FINALIZE_TIMEOUT_S):
            # One retry before giving up, so a slow flush doesn't clip the
            # tail of the question.
            try:
                self.dg_connection.send(json.dumps({"type": "Finalize"}))
                self._finalized.wait(timeout=FINALIZE_TIMEOUT_S)
            except Exception:
                pass
        self._collecting = False
        self._awaiting_finalize = False
        transcript = "".join(self._parts).strip()
        self._parts.clear()
        return transcript

    def abort_turn(self):
        self._collecting = False
        self._awaiting_finalize = False
        self._parts.clear()

    # -- SDK callbacks (Deepgram listener thread) ----------------------------

    def _on_message(self, *args, **kwargs):
        if not self._collecting:
            return
        result = kwargs.get("result")
        if not result or not result.channel.alternatives:
            return
        snippet = result.channel.alternatives[0].transcript
        is_final = bool(getattr(result, "is_final", False))

        if snippet:
            if is_final:
                self._parts.append(snippet + " ")
            live_text = "".join(self._parts) + ("" if is_final else snippet)
            self.emit(events.make_event(
                events.INTERIM, turn_id=self.turn_id, text=live_text.strip(),
            ))

        # Any final result while we're draining unblocks finalize_turn().
        if self._awaiting_finalize and (
            is_final or bool(getattr(result, "from_finalize", False))
        ):
            self._finalized.set()

    def _on_utterance_end(self, *args, **kwargs):
        # Auto mode: the speaker paused long enough that the question is
        # probably over. Only meaningful while collecting with real speech.
        if self._collecting and not self._awaiting_finalize and self._parts:
            try:
                self.on_utterance_end()
            except Exception:
                pass

    def _on_error(self, *args, **kwargs):
        error = kwargs.get("error")
        was_connected = self._connected
        self._connected = False
        self._finalized.set()  # never leave finalize_turn() hanging
        self.on_status(False)
        # Only surface the first error of a disconnect; the SDK can fire this
        # repeatedly for one dead socket, and one toast per drop is enough.
        if was_connected:
            log.warning("Deepgram error: %s", error)
            self.emit(events.make_event(
                events.ERROR, scope="deepgram",
                message=str(error) if error else "Deepgram connection error",
                recoverable=True,
            ))

    def _on_close(self, *args, **kwargs):
        self._connected = False
        self._finalized.set()
        self.on_status(False)

    def shutdown(self):
        self._collecting = False
        self._finalized.set()
        self._close_connection()
