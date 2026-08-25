# Improvement Checklist

Deep review of the codebase (2026-08-23). Ordered by impact.
**Status update (same day): Part 1 + the critical technical items are implemented** — see checkmarks.

---

# Part 1 — Usability for non-technical users

Goal: someone with zero technical background can go from "downloaded a file" to "getting answers in an interview" in under 10 minutes, without ever seeing a terminal, a dotfile, or an error code.

## U0 — Remove the installation wall

- [x] **Ship a single downloadable `.exe`** — `pyinstaller main.spec` now produces a one-file, windowless `dist/InterviewCopilot.exe` (~32 MB). Upload it to GitHub Releases to share.
- [x] **Never require editing `.env` or `prompt.txt` by hand** — the wizard writes `.env`; the profile form writes `profile.json` + regenerates `prompt.txt`.
- [x] **First-run setup wizard in the browser** — the server always starts; missing keys show a 3-step wizard: paste keys (with "How do I get this?" walkthroughs + live per-key Test buttons and plain-English failures) → sound check → profile.
- [x] **Hide the console window** — `console=False` build, logging to `app.log`, system-tray icon with Open / Quit.
- [ ] **Auto-update check** — needs a public GitHub Releases URL to point at; add once the repo is published.

## U1 — Make setup human

- [x] **Interview Profile form replaces "edit prompt.txt"** — About you / the job / paste-or-upload job description / paste-or-upload resume (PDF & DOCX extraction) / extra notes / names & terms. Prompt assembled behind the scenes; raw editor moved to Settings → Advanced.
- [x] **Mic check with a live level meter** in the wizard and Settings. (A live transcript preview during the check would be a nice follow-up.)
- [x] **Plain "Listen to" choice** — My microphone / Other person (computer audio) / Both — powered by real WASAPI loopback capture (PyAudioWPatch), so it works with any headphones, no Stereo Mix. The old cryptic device-classifier is gone.
- [x] **Interview language dropdown** (English, multilingual auto-detect, Spanish, French, German, Portuguese, Hindi, Japanese).
- [x] **Plain-English model picker** — ⚡ Fastest / ⚖️ Balanced (recommended) / 🧠 Smartest with cost-per-hour blurbs; the real model id is a tooltip.
- [x] **Cost in human terms** — the wizard states ~$0.30–$0.80 per interview hour up front.

## U2 — Make everyday use effortless

- [x] **Hands-free Auto mode** — Deepgram utterance-end detection (1.2 s pause) finishes the question and answers automatically, then goes straight back to listening. Toggle in the header. Errors never auto-loop.
- [x] **Hotkey is now a chord** — default Ctrl+Space, selectable presets (Ctrl+Alt+Space, F8, F9, legacy backtick), switchable live in Settings.
- [x] **3-step first-use tour** after setup (localStorage-dismissed).
- [x] **Plain-language errors with Retry buttons** — every error names the component in words ("Transcription service", "Microphone problem"), says what to do, and offers Retry (wired to the repair command).
- [x] **Jargon removed** — "✓ Ready." instead of "prompt cache warmed in 1.2s", etc.
- [x] **Health dots** — 🎤 🌐 🤖 in the header, green/red, click for the plain-English fix.
- [x] **"Fix it" button** in Settings — reconnects mic + transcription + AI without restarting.
- [x] **Type-a-question box** under the Question card (covers bad transcripts and written exercises).
- [x] **Text-size toggle** — Normal / Large / Extra large.

---

# Part 2 — Technical improvements

## P0 — Security of the local server

- [x] **WebSocket locked down** — Origin-header validation + a random per-run session token required on `/ws` and all `/api/*` calls. Other websites can no longer read the prompt/transcripts or send commands.
- [x] **Host-header validation** (DNS-rebinding protection) on all HTTP routes.
- [x] **Markdown sanitized with DOMPurify** (vendored `app/static/purify.min.js`) before `innerHTML`.

## P1 — Biggest functional wins

- [x] **WASAPI loopback capture** via PyAudioWPatch (`app/audio.py` rewrite).
- [x] **Dual-source capture** — mic + loopback resampled to 16 kHz mono and mixed ("Both" mode). (True 2-channel Deepgram `multichannel` speaker separation is a possible upgrade.)
- [x] **Deepgram nova-2 → nova-3.**
- [x] **Nova-3 keyterm prompting** — the profile's "Names & special terms" field feeds `keyterm` (English only, capped at 90).
- [ ] **Deepgram Flux** — current hands-free uses `utterance_end_ms`; Flux's model-based end-of-turn would be the next quality step.

## P1 — LLM layer

- [x] **`max_tokens` raised to 4096 + truncation detected** (`stop_reason == "max_tokens"` → user is told the answer was cut short).
- [x] **`refusal` stop reason handled** with a plain-English toast.
- [x] `output_config: {effort: low}` still sent via `extra_body` deliberately — wire-identical, works on every SDK version.
- [x] **Model list refreshed** — Sonnet 5 (default), Opus 5, Haiku 4.5, Sonnet 4.6.
- [x] **Time-to-first-token shown** ("0.6s to first word · 4.2s total").
- [x] **History trimmed in blocks of 4 turns** so the cache prefix stays stable at the cap.

## P2 — Reliability

- [x] **Mid-turn Deepgram drops surfaced** — health dot goes red + one clear error toast instead of a silent empty turn.
- [x] **Stray hotkey toggles during thinking/answering dropped** (no more phantom queued turns).
- [x] **Finalize retried once on timeout** before giving up on the tail of a transcript.
- [x] **Real logging** — rotating `app.log` (required now that the exe is windowless).
- [x] **Browser opened from the server's startup hook**, not a sleep.

## P2 — Code quality & tooling

- [ ] Pytest suite in-repo (a full smoke script exists; promote it to `tests/` with pytest).
- [ ] ruff + pyright + pre-commit.
- [ ] Dependency lockfile (uv / pip-tools).
- [x] Stale `deepgram_sdk-3.2.3.dist-info/` folder deleted.
- [x] Migrated off deprecated `@app.on_event` to the `lifespan` API.
- [ ] GitHub Actions CI.
- [ ] Split `index.html` into css/js files if it keeps growing.

## P3 — UX polish (future)

- [ ] "Regenerate" button on the last answer.
- [ ] Export a session to Markdown.
- [ ] Search box over history.
- [ ] Rename sessions inline.
- [x] Turn history is now server-emitted after every answer (client no longer rebuilds turns from DOM state).

## Ideas (only if you want them)

- [ ] Two-stage answers: instant 1-sentence gist from Haiku while the full answer streams below.
- [ ] Per-session prompt profiles (different profile per company/role).
- [ ] Practice mode: the app asks *you* questions from the job description and critiques your answers.
