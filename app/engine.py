import logging
import queue
import threading
import time

from app import config as cfg
from app import events, store
from app.audio import AudioCapture, MicError
from app.config import Config
from app.llm import AnswerGenerator, LLMError
from app.transcriber import DeepgramTranscriber

log = logging.getLogger("app.engine")


class InterviewEngine:
    """Owns all audio/transcription/LLM work on a single worker thread.

    Every public command is thread-safe and non-blocking: it enqueues and
    returns immediately, so the hotkey listener and the web server never
    stall behind a turn.

    The engine starts even with no API keys: audio (mic test) works right
    away, and `configure_keys()` brings the transcriber + LLM online once
    the setup wizard has collected working keys.
    """

    def __init__(self, config: Config, emit):
        self.config = config
        self._emit_raw = emit
        self.state = events.IDLE
        self.turn_id = 0
        self.turns: list[dict] = []
        self.sessions: list[dict] = []
        self._commands: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self._running = True
        self._mic_testing = False
        self._dg_drop_flagged = False
        self._health = {"mic": "off", "transcriber": "off", "llm": "off"}
        self.on_hotkey_change = lambda combo: None  # set by main.py

        self.llm: AnswerGenerator | None = None
        self.transcriber: DeepgramTranscriber | None = None
        self.mic = AudioCapture(
            self._send_audio,
            level_cb=lambda v: self.emit(events.make_event(events.LEVEL, value=round(v, 3))),
            mic_device=config.mic_device,
            system_device=config.system_device,
        )
        self.mic.source = config.source

        if config.configured:
            self._init_services()

        # Restore saved history; an unfinished interview keeps its LLM context.
        self.turns, self.sessions = store.load_history(config.history_path)
        if self.turns:
            self.turn_id = max(t.get("turn_id", 0) for t in self.turns)
            if self.llm:
                self.llm.seed_history([(t["question"], t["answer"]) for t in self.turns])

        self._worker = threading.Thread(target=self._run, daemon=True, name="engine")

    def _init_services(self):
        self.llm = AnswerGenerator(
            api_key=self.config.anthropic_api_key,
            prompt=self.config.prompt,
            model=self.config.model,
        )
        self.transcriber = DeepgramTranscriber(
            self.config.deepgram_api_key,
            self.emit,
            language=self.config.language,
            keyterms=self.config.keyterms(),
            on_utterance_end=self._on_utterance_end,
            on_status=self._on_dg_status,
        )

    def _send_audio(self, data: bytes):
        if self.transcriber is not None:
            self.transcriber.send_audio(data)

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        self._worker.start()
        if self.config.configured:
            threading.Thread(target=self._startup, daemon=True, name="engine-startup").start()

    def _startup(self):
        try:
            self.transcriber.start_session()
        except Exception as e:
            log.warning("Deepgram startup failed: %s", e)
            self._set_health("transcriber", "error")
            self._error("deepgram", f"Could not connect to the transcription service: {e}")
        try:
            self.mic.open()
            self._set_health("mic", "ok")
        except MicError as e:
            self._set_health("mic", "error")
            self._error("mic", str(e), recoverable=True)
        try:
            warmup_ms = self.llm.warm_cache()
            self._set_health("llm", "ok")
            self.emit(events.make_event(events.READY, warmup_ms=warmup_ms))
        except LLMError as e:
            self._set_health("llm", "error")
            self._error("anthropic", str(e), recoverable=e.recoverable)

    def configure_keys(self, deepgram_key: str, anthropic_key: str):
        """Called by the setup wizard after both keys validated live."""
        self.config.save_keys(deepgram_key, anthropic_key)
        if self.llm is not None:
            self.llm.seed_history([])  # fresh client below re-seeds from turns
        self._init_services()
        if self.turns:
            self.llm.seed_history([(t["question"], t["answer"]) for t in self.turns])
        self.emit(events.make_event(
            events.SETUP, configured=True, has_profile=bool(self.config.profile),
        ))
        threading.Thread(target=self._startup, daemon=True, name="engine-startup").start()

    def shutdown(self):
        self._running = False
        self._cancel.set()
        self._commands.put({"cmd": "_stop"})
        try:
            self.mic.terminate()
        except Exception:
            pass
        if self.transcriber:
            self.transcriber.shutdown()

    # -- emit helpers --------------------------------------------------------

    def set_emitter(self, emit):
        """Swap the transport once the server owns it (see main.py)."""
        self._emit_raw = emit

    def emit(self, event: dict):
        try:
            self._emit_raw(event)
        except Exception:
            pass

    def _error(self, scope: str, message: str, recoverable: bool = True):
        log.warning("[%s] %s", scope, message)
        self.emit(events.make_event(
            events.ERROR, scope=scope, message=message, recoverable=recoverable,
        ))

    def _set_state(self, state: str):
        self.state = state
        self.emit(events.make_event(events.STATE, state=state, turn_id=self.turn_id))

    def _set_health(self, component: str, status: str):
        if self._health.get(component) != status:
            self._health[component] = status
            self.emit(events.make_event(events.HEALTH, **self._health))

    def _on_dg_status(self, connected: bool):
        self._set_health("transcriber", "ok" if connected else "error")
        if connected:
            self._dg_drop_flagged = False
        elif self.state == events.LISTENING and not self._dg_drop_flagged:
            # A mid-turn drop would otherwise be silent: audio keeps flowing
            # into a dead socket and the turn comes back empty.
            self._dg_drop_flagged = True
            self._error(
                "deepgram",
                "Lost the transcription connection mid-question. "
                "Click Retry, then ask again.",
            )

    def snapshot(self) -> list[dict]:
        """Full current state, replayed to each newly connected UI client."""
        return [
            events.make_event(
                events.SETUP,
                configured=self.config.configured,
                has_profile=bool(self.config.profile),
            ),
            events.make_event(
                events.CONFIG,
                model=self.config.model,
                models=self.config.models,
                hotkey=self.config.hotkey,
                hotkeys=self.config.hotkeys,
                language=self.config.language,
                languages=self.config.languages,
                auto_mode=self.config.auto_mode,
            ),
            self._devices_event(),
            events.make_event(
                events.HISTORY, turns=list(self.turns), sessions=list(self.sessions),
            ),
            events.make_event(events.PROMPT, text=self.config.prompt, saved=False),
            events.make_event(events.PROFILE, profile=dict(self.config.profile), saved=False),
            events.make_event(events.HEALTH, **self._health),
            events.make_event(events.STATE, state=self.state, turn_id=self.turn_id),
        ]

    def _devices_event(self) -> dict:
        try:
            devices = self.mic.list_devices()
        except Exception:
            devices = {"mics": [], "loopbacks": [], "has_loopback": False}
        return events.make_event(
            events.DEVICES,
            selected_mic=self.mic.mic_device,
            selected_system=self.mic.system_device,
            source=self.mic.source,
            **devices,
        )

    # -- commands (any thread) -----------------------------------------------

    def submit(self, command: dict):
        cmd = command.get("cmd")
        if cmd == "cancel":
            # Set inline so it interrupts a stream already in flight; the
            # worker is busy streaming and would not reach a queued command.
            self._cancel.set()
            if self.state == events.LISTENING:
                self._commands.put({"cmd": "_abort"})
            return
        self._commands.put(command)

    def toggle(self):
        # A stray hotkey press mid-answer used to queue a phantom turn that
        # started the moment the answer finished; drop those instead.
        if self.state in (events.THINKING, events.ANSWERING):
            return
        self.submit({"cmd": "toggle"})

    # -- worker --------------------------------------------------------------

    def _run(self):
        while self._running:
            command = self._commands.get()
            if not self._running or command.get("cmd") == "_stop":
                break
            try:
                self._handle(command)
            except Exception as e:
                log.exception("Unhandled engine error")
                self._error("engine", f"Unexpected error: {e}")
                self._reset_to_idle()

    def _handle(self, command: dict):
        cmd = command.get("cmd")
        if cmd == "toggle":
            self._start_listening() if self.state == events.IDLE else self._stop_listening()
        elif cmd == "_abort":
            self.mic.pause()
            if self.transcriber:
                self.transcriber.abort_turn()
            self._reset_to_idle()
        elif cmd == "start":
            if self.state == events.IDLE:
                self._start_listening()
        elif cmd in ("stop", "_auto_stop"):
            if self.state == events.LISTENING:
                self._stop_listening(auto=cmd == "_auto_stop")
        elif cmd == "_auto_start":
            if self.state == events.IDLE and self.config.auto_mode:
                self._start_listening()
        elif cmd == "ask":
            self._ask(str(command.get("text", "")).strip())
        elif cmd == "set_mic_device":
            self._set_audio(lambda: self.mic.set_mic_device(int(command["index"])))
            self.config.mic_device = self.mic.mic_device
            self.config.save_settings()
        elif cmd == "set_system_device":
            self._set_audio(lambda: self.mic.set_system_device(int(command["index"])))
            self.config.system_device = self.mic.system_device
            self.config.save_settings()
        elif cmd == "set_source":
            source = str(command.get("source", "mic"))
            if source in cfg.AUDIO_SOURCES:
                self._set_audio(lambda: self.mic.set_source(source))
                self.config.source = self.mic.source
                self.config.save_settings()
        elif cmd == "set_model":
            self._set_model(str(command.get("model", "")))
        elif cmd == "set_language":
            self._set_language(str(command.get("language", "")))
        elif cmd == "set_hotkey":
            self._set_hotkey(str(command.get("hotkey", "")))
        elif cmd == "set_auto":
            self._set_auto(bool(command.get("on", False)))
        elif cmd == "mic_test":
            self._mic_test(bool(command.get("on", False)))
        elif cmd == "repair":
            self._repair()
        elif cmd == "clear_history":
            if self.llm:
                self.llm.clear_history()
            self.turns.clear()
            self.sessions.clear()
            self._save_history()
            self._emit_history()
        elif cmd == "end_session":
            self._end_session()
        elif cmd == "rename_session":
            self._rename_session(command.get("session_id"), str(command.get("title", "")))
        elif cmd == "set_prompt":
            self._set_prompt(str(command.get("text", "")))
        elif cmd == "set_profile":
            profile = command.get("profile")
            if isinstance(profile, dict):
                self._set_profile(profile)

    # -- turns ---------------------------------------------------------------

    def _require_configured(self) -> bool:
        if not self.config.configured or self.llm is None:
            self._error("engine", "Finish setup first — the app needs your two keys.")
            return False
        return True

    def _start_listening(self):
        if not self._require_configured():
            return
        self.turn_id += 1
        self._cancel.clear()
        self._mic_testing = False
        try:
            self.transcriber.ensure_connected()
            self._set_health("transcriber", "ok")
        except Exception as e:
            self._set_health("transcriber", "error")
            self._error("deepgram", f"Could not connect to the transcription service: {e}")
            return
        self.transcriber.begin_turn(self.turn_id)
        try:
            self.mic.resume()
        except MicError:
            try:
                self.mic.open()
                self.mic.resume()
            except MicError as e:
                self._set_health("mic", "error")
                self._error("mic", str(e))
                self.transcriber.abort_turn()
                return
        self._set_health("mic", "ok")
        self._set_state(events.LISTENING)

    def _stop_listening(self, auto: bool = False):
        if self.state != events.LISTENING:
            return
        self._set_state(events.THINKING)
        self.mic.pause()
        transcript = self.transcriber.finalize_turn()

        if not transcript:
            if not auto:
                self._error("deepgram", "No speech was captured for that turn.")
            self._reset_to_idle(auto_continue=auto)
            return

        self.emit(events.make_event(
            events.TRANSCRIPT, turn_id=self.turn_id, text=transcript,
        ))
        self._answer(transcript)

    def _ask(self, text: str):
        """Typed question — covers bad transcripts and written exercises."""
        if not text or self.state != events.IDLE or not self._require_configured():
            return
        self.turn_id += 1
        self._cancel.clear()
        self._set_state(events.THINKING)
        self.emit(events.make_event(
            events.TRANSCRIPT, turn_id=self.turn_id, text=text,
        ))
        self._answer(text)

    def _answer(self, transcript: str):
        started = time.monotonic()
        parts: list[str] = []
        first_token_ms = 0
        try:
            for chunk in self.llm.generate(transcript, self._cancel):
                if not parts:
                    first_token_ms = int((time.monotonic() - started) * 1000)
                    self._set_state(events.ANSWERING)
                parts.append(chunk)
                self.emit(events.make_event(
                    events.ANSWER_DELTA, turn_id=self.turn_id, text=chunk,
                ))
        except LLMError as e:
            self._set_health("llm", "error")
            self._error("anthropic", str(e), recoverable=e.recoverable)
            self._reset_to_idle()
            return

        self._set_health("llm", "ok")
        cancelled = self._cancel.is_set()
        answer = "".join(parts)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stop_reason = self.llm.last_stop_reason
        truncated = stop_reason == "max_tokens"
        if not cancelled and not answer and stop_reason == "refusal":
            self._error("anthropic", "The AI declined to answer that one — try rephrasing.")
        self.emit(events.make_event(
            events.ANSWER_DONE, turn_id=self.turn_id, text=answer,
            elapsed_ms=elapsed_ms, first_token_ms=first_token_ms,
            cancelled=cancelled, truncated=truncated,
        ))
        if truncated:
            self._error("anthropic", "That answer hit the length limit and was cut short.")
        if answer and not cancelled:
            self.turns.append({
                "turn_id": self.turn_id,
                "question": transcript,
                "answer": answer,
                "elapsed_ms": elapsed_ms,
                "first_token_ms": first_token_ms,
                "ts": time.strftime("%I:%M %p").lstrip("0"),
            })
            self._save_history()
            self._emit_history()
        self._reset_to_idle(auto_continue=True)

    def _reset_to_idle(self, auto_continue: bool = False):
        self._cancel.clear()
        self._set_state(events.IDLE)
        # Hands-free mode: go straight back to listening after a good turn.
        # Never auto-continue after an error (auto_continue=False) so a broken
        # mic or dead connection can't loop forever.
        if auto_continue and self.config.auto_mode and self._running:
            self._commands.put({"cmd": "_auto_start"})

    def _on_utterance_end(self):
        # Deepgram noticed the speaker stopped (fired from its listener
        # thread) — in auto mode that ends the question.
        if self.config.auto_mode and self.state == events.LISTENING:
            self.submit({"cmd": "_auto_stop"})

    # -- settings ------------------------------------------------------------

    def _set_audio(self, action):
        was_listening = self.state == events.LISTENING
        try:
            action()
            self._set_health("mic", "ok")
            if was_listening or self._mic_testing:
                self.mic.resume()
        except MicError as e:
            self._set_health("mic", "error")
            self._error("mic", str(e))
        self.emit(self._devices_event())

    def _mic_test(self, on: bool):
        """Level-meter test for the wizard/settings; no transcription needed."""
        if self.state != events.IDLE:
            return
        self._mic_testing = on
        if on:
            try:
                self.mic.open()
                self.mic.resume()
                self._set_health("mic", "ok")
            except MicError as e:
                self._mic_testing = False
                self._set_health("mic", "error")
                self._error("mic", str(e))
        else:
            self.mic.pause()

    def _set_auto(self, on: bool):
        self.config.auto_mode = on
        self.config.save_settings()
        self._emit_config()
        if on and self.state == events.IDLE and self.config.configured:
            self._commands.put({"cmd": "_auto_start"})

    def _set_hotkey(self, combo: str):
        if combo not in {h["id"] for h in cfg.HOTKEY_PRESETS}:
            return
        self.config.hotkey = combo
        self.config.save_settings()
        try:
            self.on_hotkey_change(combo)
        except Exception as e:
            self._error("engine", f"Could not switch the shortcut: {e}")
        self._emit_config()

    def _set_language(self, language: str):
        if language not in {l["id"] for l in cfg.LANGUAGE_CHOICES}:
            return
        self.config.language = language
        self.config.save_settings()
        if self.transcriber:
            self.transcriber.set_language(language)
            try:
                self.transcriber.start_session()  # applies on a fresh session
            except Exception as e:
                self._error("deepgram", f"Could not restart transcription: {e}")
        self._emit_config()

    def _set_model(self, model: str):
        if model not in {m["id"] for m in cfg.MODEL_CHOICES}:
            return
        self.config.model = model
        self.config.save_settings()
        if self.llm and model != self.llm.model:
            self.llm.set_model(model)
            # Switching models invalidates the prompt cache — re-warm it.
            self._rewarm_cache()
        self._emit_config()

    def _emit_config(self):
        self.emit(events.make_event(
            events.CONFIG,
            model=self.config.model,
            models=self.config.models,
            hotkey=self.config.hotkey,
            hotkeys=self.config.hotkeys,
            language=self.config.language,
            languages=self.config.languages,
            auto_mode=self.config.auto_mode,
        ))

    def _repair(self):
        """The 'Fix it' button: reconnect everything that can be reconnected."""
        if self.state != events.IDLE:
            self._error("engine", "Finish the current question first.")
            return
        fixed = []
        try:
            self.mic.open()
            self._set_health("mic", "ok")
            fixed.append("microphone")
        except MicError as e:
            self._set_health("mic", "error")
            self._error("mic", str(e))
        if self.transcriber:
            try:
                self.transcriber.start_session()
                fixed.append("transcription")
            except Exception as e:
                self._set_health("transcriber", "error")
                self._error("deepgram", f"Could not reconnect transcription: {e}")
        if self.llm:
            try:
                self.llm.warm_cache()
                self._set_health("llm", "ok")
                fixed.append("AI")
            except LLMError as e:
                self._set_health("llm", "error")
                self._error("anthropic", str(e), recoverable=e.recoverable)
        if fixed:
            self.emit(events.make_event(events.READY, warmup_ms=0))

    # -- history / prompt / profile ------------------------------------------

    def _emit_history(self):
        self.emit(events.make_event(
            events.HISTORY, turns=list(self.turns), sessions=list(self.sessions),
        ))

    def _save_history(self):
        try:
            store.save_history(self.config.history_path, self.turns, self.sessions)
        except OSError as e:
            self._error("history", f"Could not save history.json: {e}")

    def _end_session(self):
        """Archive the current conversation as one history entry and reset the
        LLM context so the next interview starts clean."""
        if self.state != events.IDLE:
            self._error("engine", "Finish the current question before ending the interview.")
            return
        if not self.turns:
            return
        number = len(self.sessions) + 1
        self.sessions.append({
            "session_id": number,
            "title": f"Interview {number}",
            "ended": time.strftime("%b %d, %I:%M %p").replace(" 0", " "),
            "turns": list(self.turns),
        })
        self.turns.clear()
        if self.llm:
            self.llm.clear_history()
        self._save_history()
        self._emit_history()

    def _rename_session(self, session_id, title: str):
        title = title.strip()[:80]
        if not title:
            return
        for session in self.sessions:
            if session.get("session_id") == session_id:
                session["title"] = title
                self._save_history()
                self._emit_history()
                return

    def _set_prompt(self, text: str):
        if not text.strip():
            self._error("prompt", "The prompt cannot be empty.")
            return
        if text == self.config.prompt:
            self.emit(events.make_event(events.PROMPT, text=text, saved=True))
            return
        try:
            self.config.save_prompt(text)
        except OSError as e:
            self._error("prompt", f"Could not save prompt.txt: {e}")
            return
        if self.llm:
            self.llm.prompt = text
            # A new system prompt invalidates the cache — re-warm it.
            self._rewarm_cache()
        self.emit(events.make_event(events.PROMPT, text=text, saved=True))

    def _set_profile(self, profile: dict):
        """Save the plain-language profile and regenerate the prompt from it."""
        clean = {k: str(profile.get(k, ""))[:60000] for k in
                 ("about", "job", "job_description", "resume", "extra", "keyterms")}
        try:
            self.config.save_profile(clean)
            prompt = cfg.build_prompt(clean)
            self.config.save_prompt(prompt)
        except OSError as e:
            self._error("prompt", f"Could not save your profile: {e}")
            return
        if self.llm:
            self.llm.prompt = prompt
            self._rewarm_cache()
        if self.transcriber:
            self.transcriber.set_keyterms(self.config.keyterms())
            try:
                self.transcriber.start_session()  # apply keyterms
            except Exception:
                pass
        self.emit(events.make_event(events.PROFILE, profile=clean, saved=True))
        self.emit(events.make_event(events.PROMPT, text=prompt, saved=False))

    def _rewarm_cache(self):
        def rewarm():
            try:
                warmup_ms = self.llm.warm_cache()
                self._set_health("llm", "ok")
                self.emit(events.make_event(events.READY, warmup_ms=warmup_ms))
            except LLMError as e:
                self._set_health("llm", "error")
                self._error("anthropic", str(e), recoverable=e.recoverable)

        threading.Thread(target=rewarm, daemon=True, name="rewarm").start()
