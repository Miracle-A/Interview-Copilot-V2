import threading
import time

import anthropic
from anthropic import Anthropic

MAX_HISTORY_TURNS = 20  # question/answer pairs kept in context
# Trim history in blocks so the cached conversation prefix stays stable
# between trims instead of shifting (and invalidating) every turn at the cap.
TRIM_BLOCK_TURNS = 4
MAX_ANSWER_TOKENS = 4096
SEED_NOTE = "Note: Remember to always be concise, brief, straight-to-the-point..."


class LLMError(Exception):
    def __init__(self, message: str, recoverable: bool = True):
        super().__init__(message)
        self.recoverable = recoverable


def _to_llm_error(e: Exception) -> LLMError:
    if isinstance(e, anthropic.AuthenticationError):
        return LLMError("The Anthropic key was rejected. Re-enter it in setup.", recoverable=False)
    if isinstance(e, anthropic.RateLimitError):
        return LLMError("The AI is briefly rate-limited — wait a few seconds and try again.", recoverable=True)
    if isinstance(e, anthropic.APIConnectionError):
        return LLMError("Could not reach the AI service — check your internet connection.", recoverable=True)
    if isinstance(e, anthropic.APIStatusError):
        return LLMError(f"AI service error ({e.status_code}): {e.message}", recoverable=True)
    return LLMError(f"Unexpected error while generating the answer: {e}", recoverable=True)


class AnswerGenerator:
    """Streams answers from the Anthropic API with aggressive latency tuning:
    low effort + no extended thinking, 1h-cached system prompt, incremental
    history caching, and a startup cache warm-up."""

    def __init__(self, api_key: str, prompt: str, model: str):
        self.client = Anthropic(api_key=api_key, timeout=30.0, max_retries=1)
        self.prompt = prompt
        self.model = model
        self.history: list[dict] = []  # committed turns, block-list content
        self.last_stop_reason: str | None = None
        self._ttl_1h_ok = True
        self._lock = threading.Lock()

    # -- request assembly ----------------------------------------------------

    def _system_blocks(self) -> list[dict]:
        cache: dict = {"type": "ephemeral"}
        if self._ttl_1h_ok:
            cache = {"type": "ephemeral", "ttl": "1h"}
        return [{"type": "text", "text": self.prompt, "cache_control": cache}]

    @staticmethod
    def _user_message(text: str, cached: bool = False) -> dict:
        block: dict = {"type": "text", "text": text}
        if cached:
            block["cache_control"] = {"type": "ephemeral"}
        return {"role": "user", "content": [block]}

    @staticmethod
    def _assistant_message(text: str) -> dict:
        return {"role": "assistant", "content": [{"type": "text", "text": text}]}

    def _build_messages(self, transcript: str) -> list[dict]:
        with self._lock:
            history = list(self.history)
        messages = [self._user_message(SEED_NOTE)]
        messages.extend(history)
        # Cache breakpoint on the newest user turn: next request re-reads the
        # whole conversation prefix from cache instead of re-prefilling it.
        # (No-op until the prefix passes the ~1024-token cacheable minimum.)
        messages.append(self._user_message(transcript, cached=True))
        return messages

    def _latency_kwargs(self) -> dict:
        """Lowest-latency config for short conversational answers.

        `effort` is rejected by Haiku 4.5, so it is only sent to models that
        support it — otherwise the request 400s.
        """
        if self.model.startswith("claude-haiku"):
            return {}
        return {
            "thinking": {"type": "disabled"},
            "extra_body": {"output_config": {"effort": "low"}},
        }

    def _is_ttl_rejection(self, e: Exception) -> bool:
        return (
            self._ttl_1h_ok
            and isinstance(e, anthropic.BadRequestError)
            and "ttl" in str(e).lower()
        )

    # -- public API (called from the engine worker thread) --------------------

    def set_model(self, model: str):
        self.model = model

    def clear_history(self):
        with self._lock:
            self.history.clear()

    def seed_history(self, pairs: list[tuple[str, str]]):
        """Restore committed (question, answer) turns — e.g. reloaded from
        disk after a restart — into the conversation context."""
        with self._lock:
            self.history.clear()
            for question, answer in pairs[-MAX_HISTORY_TURNS:]:
                self.history.append(self._user_message(question))
                self.history.append(self._assistant_message(answer))

    def warm_cache(self) -> int:
        """Pre-write the system-prompt cache so the first real question pays a
        cache read instead of a cold prefill. Returns elapsed ms."""
        started = time.monotonic()
        for attempt in range(2):
            try:
                self.client.messages.create(
                    model=self.model,
                    max_tokens=1,
                    system=self._system_blocks(),
                    messages=[{"role": "user", "content": "warmup"}],
                )
                break
            except Exception as e:
                if self._is_ttl_rejection(e):
                    self._ttl_1h_ok = False  # fall back to 5-minute cache
                    continue
                raise _to_llm_error(e)
        return int((time.monotonic() - started) * 1000)

    def generate(self, transcript: str, cancel_event: threading.Event):
        """Yield answer text chunks. Commits the turn to history only when the
        stream completes uncancelled. After completion, `last_stop_reason`
        holds why the model stopped ("end_turn", "max_tokens", "refusal", ...)."""
        messages = self._build_messages(transcript)
        reply_parts: list[str] = []
        cancelled = False
        self.last_stop_reason = None

        for attempt in range(2):
            reply_parts.clear()
            try:
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=MAX_ANSWER_TOKENS,
                    system=self._system_blocks(),
                    messages=messages,
                    **self._latency_kwargs(),
                ) as stream:
                    for text in stream.text_stream:
                        if cancel_event.is_set():
                            cancelled = True
                            break
                        reply_parts.append(text)
                        yield text
                    if not cancelled:
                        try:
                            final = stream.get_final_message()
                            self.last_stop_reason = final.stop_reason
                        except Exception:
                            pass
                break
            except Exception as e:
                if self._is_ttl_rejection(e):
                    self._ttl_1h_ok = False
                    continue
                raise _to_llm_error(e)

        reply = "".join(reply_parts)
        if not cancelled and reply:
            with self._lock:
                self.history.append(self._user_message(transcript))
                self.history.append(self._assistant_message(reply))
                excess = len(self.history) - MAX_HISTORY_TURNS * 2
                if excess > 0:
                    # Trim a whole block once over the cap (see TRIM_BLOCK_TURNS).
                    del self.history[:excess + (TRIM_BLOCK_TURNS - 1) * 2]
