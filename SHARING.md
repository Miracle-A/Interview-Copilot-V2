# Sharing Interview Copilot with someone

Everything your friend needs is **one file**: `dist/InterviewCopilot.exe` (~32 MB).
No Python, no install — they double-click it and a setup wizard does the rest.

---

## 1. The file to send

- **Send:** `dist\InterviewCopilot.exe` (in this project's `dist` folder).
- **Do NOT send:** `.env`, `settings.json`, `profile.json`, `history.json`.
  Those hold *your* API keys and *your* interview answers. The `.exe` contains
  none of them — your friend creates their own on first run.

Optional integrity check (so they know the file arrived intact) —
SHA-256 of the current build:

```
d8aaa5966daca84ef090d31d6cc7d13e56d330116b421445662bc56419c87164
```

They can verify on their PC with:
`certutil -hashfile InterviewCopilot.exe SHA256`

---

## 2. Requirements on their side

- **Windows 10 or 11, 64-bit.** (It won't run on macOS — the "hear the other
  person" feature uses Windows audio.)
- A **Deepgram** account and an **Anthropic** account (both free to create).
  The wizard links straight to them and tests the keys.
- A little usage credit: about **$0.30–$0.80 per interview hour**. Anthropic
  needs a small prepaid balance (~$5 lasts a long time); Deepgram gives new
  accounts free starter credit.

---

## 3. How to actually send a 32 MB file

Email usually won't work (Gmail caps attachments at 25 MB). Use one of these:

### Option A — Google Drive (recommended, you already have it)
1. Go to **drive.google.com**.
2. Click **+ New → File upload**, pick `InterviewCopilot.exe`, wait for it to finish.
3. Right-click the uploaded file → **Share**.
4. Under "General access" choose **Anyone with the link**, set it to **Viewer**.
5. Click **Copy link** and send that link to your friend.
   - Google may warn "This file is executable and may harm your computer" on
     download — that's an automatic notice for all `.exe` files; they click
     **Download anyway**.

### Option B — WeTransfer (no account needed)
1. Go to **wetransfer.com**.
2. Add `InterviewCopilot.exe`, enter your friend's email (or choose
   "Get transfer link").
3. Send. The link stays live for a few days.

### Option C — OneDrive / Dropbox
Same idea: upload the file, create a share link, send it.

### Option D — USB stick / same network
Just copy the `.exe` onto a USB drive, or drop it in a shared folder.

---

## 4. Message to send with it (copy–paste this)

> Here's the interview helper — one file, no install.
>
> 1. Download **InterviewCopilot.exe** and put it in its own folder (e.g. a new
>    folder on your Desktop called "Interview Copilot").
> 2. Double-click it. Windows may say **"Windows protected your PC"** — click
>    **More info → Run anyway**. That's normal for small apps like this.
> 3. Your browser opens with a 3-step setup: paste two keys (it shows you
>    exactly where to get them and tests each one), do a quick mic check, then
>    fill in a little about yourself and the job.
> 4. After that, press the **`** key (backtick, top-left of the keyboard) to
>    start/stop a question — or turn on **Hands-free** and it answers by itself.
>
> Heads-up: it uses two paid services, roughly **$0.30–$0.80 per interview
> hour**. Both are quick to sign up for and the app links you straight to them.

---

## 5. What your friend will see on first run (so you can help)

1. **Windows SmartScreen** — "Windows protected your PC." → **More info → Run
   anyway**. (Happens because the app isn't code-signed. It's safe; that's just
   Windows being cautious about any unknown program.)
2. **Antivirus false positive (sometimes)** — some antivirus tools flag apps
   packaged this way. If it gets quarantined, they may need to allow/restore it
   in their antivirus. This is a known quirk of the packaging tool, not a virus.
3. **A browser tab opens** at `127.0.0.1:...` — that's the app's screen. The app
   itself runs quietly in the **system tray** (bottom-right, near the clock);
   right-click that icon for **Open** or **Quit**.
4. **The 3-step wizard**: keys → sound check → profile. It writes everything to
   files next to the `.exe`, so nothing else to configure.

---

## 6. If it doesn't work for them

- **Nothing happens on double-click / tab doesn't open** — check the tray icon
  is there; if antivirus ate the file, restore it and re-run.
- **"Microphone problem" / red 🎤 dot** — Windows may be blocking mic access:
  Settings → Privacy & security → Microphone → allow desktop apps. Then click
  **Fix it** in the app's Settings.
- **Red 🌐 or 🤖 dot** — internet or a bad key. Re-open the keys via the wizard,
  or click a red dot for the plain-English fix.
- **General weirdness** — there's an `app.log` file next to the `.exe`; it
  records what went wrong.

---

## 7. Sending them a newer version later

When you rebuild (`pyinstaller main.spec`), just send the new
`InterviewCopilot.exe` the same way. They **replace the old file with the new
one** — their keys, profile, and saved interviews stay untouched, because those
live in the separate files next to the exe, not inside it.

---

## 8. Privacy

Everything runs on their own PC. Their keys, profile, and interview history are
saved only in files next to their copy of the exe — nothing is sent to you or to
any server except Deepgram (audio → text) and Anthropic (the answers), which are
the services doing the work.
