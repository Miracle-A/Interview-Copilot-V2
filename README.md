# Interview Copilot V2

A live interview assistant. Streams microphone audio to Deepgram for transcription, sends each turn to Claude, and prints the response in real time. Press the backtick key (`` ` ``) to start/stop a turn; press `Esc` to exit.

## How it works

- `main.py` — entry point, sets up the keyboard listener.
- `transcriber.py` — Deepgram live transcription session, captures mic input via PyAudio.
- `gpt_processor.py` — sends transcripts to the Anthropic API and streams the reply.
- `configure.py` — loads API keys from `.env` and the system prompt from `prompt.txt`.

## Setup

1. Clone the repo and create a virtual environment:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

   On Windows, `pyaudio` may need a prebuilt wheel — if `pip install` fails, try `pipwin install pyaudio` or grab a wheel from a trusted source.

3. Create your `.env` from the template and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

   You need:
   - `DEEPGRAM_API_KEY` — https://console.deepgram.com/
   - `ANTHROPIC_API_KEY` — https://console.anthropic.com/
   - `OPENAI_API_KEY` — optional, kept for future use

4. Create your `prompt.txt` from the template and fill in your interview context (resume, role context, prepared answers, etc.):
   ```bash
   cp prompt.example.txt prompt.txt
   ```

5. Pick the right input device. Run:
   ```bash
   python check_index.py
   ```
   Note the index of the microphone you want, then update `device_index` in `transcriber.py` if it isn't `1`. You can also use `probe_audio.py` to test which (device, channels, rate) combinations actually open.

## Run

```bash
python main.py
```

- Press `` ` `` (backtick) to start listening.
- Press `` ` `` again to finish the turn — the transcript is sent to Claude and streamed back.
- Press `Esc` to exit.

## Notes

- `.env` and `prompt.txt` are gitignored. Never commit either.
- The default model is `claude-sonnet-4-6`. Change it in `gpt_processor.py` if you want a different one.
- Deepgram uses `nova-2` for transcription with `endpointing=400ms`.
