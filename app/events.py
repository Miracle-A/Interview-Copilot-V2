"""Event schema shared by the engine (producer) and server/UI (consumer).

Every event is a plain dict: {"type": <TYPE>, ...payload}. The engine emits
them through a single emit(dict) callback and never imports the server.
"""

STATE = "state"            # {state: idle|listening|thinking|answering, turn_id}
INTERIM = "interim"        # {turn_id, text}
TRANSCRIPT = "transcript"  # {turn_id, text}
ANSWER_DELTA = "answer_delta"  # {turn_id, text}
ANSWER_DONE = "answer_done"    # {turn_id, text, elapsed_ms, first_token_ms, cancelled, truncated}
ERROR = "error"            # {scope, message, recoverable, hint}
DEVICES = "devices"        # {mics, loopbacks, selected_mic, selected_system, source, has_loopback}
CONFIG = "config"          # {model, models, hotkey, hotkeys, language, languages, auto_mode}
HISTORY = "history"        # {turns: [...], sessions: [...]}
READY = "ready"            # {warmup_ms}
PROMPT = "prompt"          # {text, saved}
SETUP = "setup"            # {configured, has_profile}
HEALTH = "health"          # {mic, transcriber, llm}  each: ok|warn|error|off
LEVEL = "level"            # {value: 0..1}
PROFILE = "profile"        # {profile: {...}, saved}

IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
ANSWERING = "answering"


def make_event(event_type: str, **payload) -> dict:
    payload["type"] = event_type
    return payload
