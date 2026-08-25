import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5"

# Friendly model picker: the UI shows label + blurb; the id stays in "Advanced".
MODEL_CHOICES = [
    {
        "id": "claude-haiku-4-5",
        "label": "⚡ Fastest",
        "blurb": "Snappiest replies. Great for rapid-fire Q&A. Roughly $0.10–$0.30 per interview hour.",
    },
    {
        "id": "claude-sonnet-5",
        "label": "⚖️ Balanced — recommended",
        "blurb": "Fast and smart. The best default for interviews. Roughly $0.30–$0.80 per interview hour.",
    },
    {
        "id": "claude-opus-5",
        "label": "🧠 Smartest",
        "blurb": "Deepest answers for hard technical interviews. Roughly $0.80–$2 per interview hour.",
    },
    {
        "id": "claude-sonnet-4-6",
        "label": "⚖️ Balanced (previous generation)",
        "blurb": "The older balanced model. Use if you preferred its style.",
    },
]

# Global hotkey presets. Backtick is the simple default (one key, no chord);
# the chords are there for anyone who types ` a lot and wants to avoid stray
# triggers.
HOTKEY_PRESETS = [
    {"id": "`", "label": "` (backtick)"},
    {"id": "<ctrl>+<space>", "label": "Ctrl + Space"},
    {"id": "<ctrl>+<alt>+<space>", "label": "Ctrl + Alt + Space"},
    {"id": "<f8>", "label": "F8"},
    {"id": "<f9>", "label": "F9"},
]
DEFAULT_HOTKEY = "`"

LANGUAGE_CHOICES = [
    {"id": "en", "label": "English"},
    {"id": "multi", "label": "Multilingual (auto-detect)"},
    {"id": "es", "label": "Spanish"},
    {"id": "fr", "label": "French"},
    {"id": "de", "label": "German"},
    {"id": "pt", "label": "Portuguese"},
    {"id": "hi", "label": "Hindi"},
    {"id": "ja", "label": "Japanese"},
]
DEFAULT_LANGUAGE = "en"

AUDIO_SOURCES = ["mic", "system", "both"]

# Bump when a stored default needs to be reset for existing users. v2 moves
# anyone still on the old Ctrl+Space default back to the simpler backtick.
SETTINGS_VERSION = 2

DEFAULT_PROMPT = (
    "You are a live interview copilot. You receive transcripts of questions "
    "asked to the user in an interview or meeting, and you answer as the user "
    "would, in first person, conversationally.\n\n"
    "Rules:\n"
    "- Keep answers short by default (2-4 sentences). Expand only for clearly "
    "technical or multi-part questions.\n"
    "- Speak plainly and confidently. Never mention being an AI.\n"
    "- If the question is ambiguous, answer the most likely meaning.\n"
)


class ConfigError(Exception):
    """Raised when required configuration is missing or unreadable."""


def app_root() -> Path:
    # When frozen by PyInstaller, .env / prompt.txt live beside the exe.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    root: Path
    deepgram_api_key: str = ""
    anthropic_api_key: str = ""
    prompt: str = DEFAULT_PROMPT
    model: str = DEFAULT_MODEL
    models: list = field(default_factory=lambda: [dict(m) for m in MODEL_CHOICES])
    hotkey: str = DEFAULT_HOTKEY
    hotkeys: list = field(default_factory=lambda: [dict(h) for h in HOTKEY_PRESETS])
    language: str = DEFAULT_LANGUAGE
    languages: list = field(default_factory=lambda: [dict(l) for l in LANGUAGE_CHOICES])
    source: str = "mic"
    auto_mode: bool = False
    mic_device: int | None = None
    system_device: int | None = None
    profile: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.deepgram_api_key and self.anthropic_api_key)

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def prompt_path(self) -> Path:
        return self.root / "prompt.txt"

    @property
    def history_path(self) -> Path:
        return self.root / "history.json"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def profile_path(self) -> Path:
        return self.root / "profile.json"

    @property
    def log_path(self) -> Path:
        return self.root / "app.log"

    # -- persistence ---------------------------------------------------------

    def save_keys(self, deepgram_key: str, anthropic_key: str):
        """Write .env for the user — they should never edit dotfiles by hand."""
        self.deepgram_api_key = deepgram_key.strip()
        self.anthropic_api_key = anthropic_key.strip()
        self.env_path.write_text(
            "# Written by Interview Copilot setup. Keep this file private.\n"
            f"DEEPGRAM_API_KEY={self.deepgram_api_key}\n"
            f"ANTHROPIC_API_KEY={self.anthropic_api_key}\n",
            encoding="utf-8",
        )

    def save_settings(self):
        data = {
            "settings_version": SETTINGS_VERSION,
            "model": self.model,
            "hotkey": self.hotkey,
            "language": self.language,
            "source": self.source,
            "auto_mode": self.auto_mode,
            "mic_device": self.mic_device,
            "system_device": self.system_device,
        }
        tmp = self.settings_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.settings_path)

    def save_profile(self, profile: dict):
        self.profile = profile
        tmp = self.profile_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(profile, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.profile_path)

    def save_prompt(self, text: str):
        self.prompt = text
        self.prompt_path.write_text(text, encoding="utf-8")

    def keyterms(self) -> list[str]:
        """Names & terms the transcriber should recognize (from the profile)."""
        raw = str(self.profile.get("keyterms", ""))
        terms = [t.strip() for t in raw.replace("\n", ",").split(",")]
        return [t for t in terms if t][:90]


def build_prompt(profile: dict) -> str:
    """Assemble the system prompt from the plain-language profile form.

    Mirrors the section layout of prompt.example.txt so the file-upload
    slotting logic ([RESUME], [SOURCE MATERIAL]) keeps working.
    """
    def sec(title: str, body: str) -> str:
        body = (body or "").strip()
        return f"--- [{title}] ---\n{body}\n\n" if body else ""

    parts = [
        "You are a live interview copilot. You receive transcripts of questions "
        "asked in an interview and must respond as the candidate would, in first "
        "person, conversationally.\n\n",
        sec("ABOUT ME", profile.get("about", "")),
        sec("INTERVIEW CONTEXT", profile.get("job", "")),
        sec("SOURCE MATERIAL", profile.get("job_description", "")),
        sec("RESUME", profile.get("resume", "")),
        sec("EXTRA NOTES", profile.get("extra", "")),
        (
            "--- [HARD RULES] ---\n"
            "- Speak in first person as the candidate. Never break character. "
            "Never reference being an AI.\n"
            "- Keep answers short by default (2-4 sentences). Expand only when "
            "the question is clearly technical or multi-part.\n"
            "- Mirror the interviewer's tone.\n"
            "- Be honest about gaps — acknowledge them and show willingness to learn.\n"
            "- Don't fabricate experience or metrics beyond what's above.\n"
        ),
    ]
    return "".join(parts).strip() + "\n"


def load_config() -> Config:
    """Load whatever exists. Missing keys are NOT an error anymore — the app
    starts either way and the in-browser setup wizard collects them."""
    root = app_root()
    load_dotenv(root / ".env")
    cfg = Config(
        root=root,
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", "").strip(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
    )

    if cfg.prompt_path.exists():
        try:
            text = cfg.prompt_path.read_text(encoding="utf-8").strip()
            if text:
                cfg.prompt = text
        except OSError:
            pass

    migrated = False
    try:
        settings = json.loads(cfg.settings_path.read_text(encoding="utf-8"))
        if settings.get("model") in {m["id"] for m in MODEL_CHOICES}:
            cfg.model = settings["model"]
        if settings.get("hotkey") in {h["id"] for h in HOTKEY_PRESETS}:
            cfg.hotkey = settings["hotkey"]
        # One-time migration: users left on the old Ctrl+Space default move
        # to backtick. Only touches the stale default, so anyone who later
        # picks a chord on purpose keeps it (their settings are v2).
        if settings.get("settings_version", 1) < SETTINGS_VERSION and cfg.hotkey == "<ctrl>+<space>":
            cfg.hotkey = DEFAULT_HOTKEY
            migrated = True
        if settings.get("language") in {l["id"] for l in LANGUAGE_CHOICES}:
            cfg.language = settings["language"]
        if settings.get("source") in AUDIO_SOURCES:
            cfg.source = settings["source"]
        cfg.auto_mode = bool(settings.get("auto_mode", False))
        if isinstance(settings.get("mic_device"), int):
            cfg.mic_device = settings["mic_device"]
        if isinstance(settings.get("system_device"), int):
            cfg.system_device = settings["system_device"]
    except (OSError, ValueError):
        pass

    if migrated:
        try:
            cfg.save_settings()  # persist so it survives even if nothing else changes
        except OSError:
            pass

    try:
        profile = json.loads(cfg.profile_path.read_text(encoding="utf-8"))
        if isinstance(profile, dict):
            cfg.profile = profile
    except (OSError, ValueError):
        pass

    return cfg
