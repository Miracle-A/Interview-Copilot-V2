import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill in your keys."
        )
    return value


DEEPGRAM_API_KEY = _require("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")


def _load_prompt() -> str:
    prompt_path = ROOT / "prompt.txt"
    if not prompt_path.exists():
        raise RuntimeError(
            "prompt.txt not found. Copy prompt.example.txt to prompt.txt "
            "and fill in your interview context."
        )
    return prompt_path.read_text(encoding="utf-8")


PROMPT = _load_prompt()
