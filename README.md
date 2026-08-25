# Interview Copilot

A live interview assistant. It listens (to your mic, to the other person on a
call, or both), turns the question into text in real time, and streams back an
answer written as *you* — grounded in your resume and the job description.

Built to be usable by non-technical people: no terminal, no config files, no
API knowledge needed.

## For people who just want to use it

1. Download `InterviewCopilot.exe` (from the project's Releases page) and put
   it in its own folder.
2. Double-click it. Your browser opens with a **3-step setup wizard**:
   - **Keys** — paste two API keys (the wizard shows exactly where to get
     them, with a Test button for each). A 1-hour interview costs roughly
     $0.30–$0.80 in usage fees.
   - **Sound check** — pick what to listen to (*your mic*, *the other
     person's voice from computer audio*, or *both*) and watch the level bar
     move while you speak.
   - **Interview profile** — plain form: who you are, the job, paste/upload
     your resume and the job description. The AI uses this to answer as you.
3. That's it. Press **Ctrl + Space** (works while any app has focus) to
   start/stop a question — or switch on **Hands-free** and the app notices
   when a question ends and answers by itself.

The app lives in your system tray; use the tray icon to reopen or quit it.
Everything (keys, profile, history) stays on your computer, in the folder
next to the exe.

### Everyday tips

- **Hands-free** (top of the window): no keypresses at all — the app hears
  the pause at the end of a question and answers automatically.
- Type or paste a question in the **"Or type a question…"** box when the
  transcript came out wrong.
- The three dots in the header (🎤 🌐 🤖) are mic / transcription / AI
  health. If one turns red, click it — or use **Settings → Fix it**.
- **Settings** also has: model choice (Fastest / Balanced / Smartest),
  interview language, keyboard shortcut, and text size.
- **End interview & save** files the whole conversation as one history entry.

## How it works (for developers)

- `main.py` — entry point: config, engine, global hotkey, tray icon, web UI.
- `app/engine.py` — orchestrates each turn on a worker thread (listen →
  transcribe → answer), emits events to the UI. Starts even with no keys;
  the setup wizard configures it live.
- `app/audio.py` — PyAudioWPatch capture: mic, WASAPI loopback (system
  audio), or both mixed to 16 kHz mono. Level metering for the sound check.
- `app/transcriber.py` — persistent Deepgram **nova-3** live session with
  interim captions, keyterm prompting (names/terms from your profile),
  event-driven finalization, and utterance-end detection for hands-free mode.
- `app/llm.py` — Anthropic streaming tuned for latency (no extended
  thinking, low effort, 1-hour prompt caching, incremental history caching,
  startup cache warm-up). Detects truncation and refusals.
- `app/server.py` — FastAPI + WebSocket bridge, loopback only, with
  Origin/Host validation and a per-run session token (other websites cannot
  reach the local server), plus the setup-wizard endpoints.
- `app/config.py` — config, settings.json, profile.json, and the
  profile → system-prompt assembly.
- `app/static/index.html` — the whole UI: wizard, tour, live transcript,
  streaming answer (sanitized with DOMPurify), history, settings.

TLS uses the OS certificate store via `truststore` (injected in
`app/__init__.py`), so corporate proxy CAs work without a custom CA bundle.

### Dev setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python main.py
```

No `.env` needed — the wizard collects keys on first run and writes `.env`
itself. (Developers can still pre-create `.env` / `prompt.txt`; see
`.env.example` and `prompt.example.txt`.)

### Build the exe

```bash
pyinstaller main.spec
```

Produces a single windowless `dist/InterviewCopilot.exe`. First run next to
an empty folder triggers the setup wizard; `.env`, `prompt.txt`,
`settings.json`, `profile.json`, `history.json`, and `app.log` are created
beside the exe.

### Notes

- `.env`, `prompt.txt`, `profile.json`, `settings.json`, and `history.json`
  are gitignored. Never commit them.
- Deepgram: nova-3, `endpointing=400`, interim results,
  `utterance_end_ms=1200` (hands-free), keyterms from the profile (English).
- Models: Haiku 4.5 (Fastest), Sonnet 5 (Balanced, default), Opus 5
  (Smartest), Sonnet 4.6 (previous). Switching models re-warms the prompt
  cache, so the first answer after a switch is slower.
- Troubleshooting starts with `app.log` next to the exe / repo.
