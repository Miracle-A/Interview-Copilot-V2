import io
import logging
import logging.handlers
import sys
import threading
import webbrowser

from app.config import load_config
from app.engine import InterviewEngine
from app.hotkeys import HotkeyManager
from app.server import create_app, find_free_port

log = logging.getLogger("app")


class _NullStream(io.TextIOBase):
    """Stand-in for a missing console stream. A windowless PyInstaller build
    gives the process no stdout/stderr (they are None), and libraries like
    uvicorn call sys.stderr.isatty() during setup — which crashes on None.
    """
    def write(self, *_a):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


def _ensure_streams():
    """Guarantee stdout/stderr exist so third-party code can't crash on None."""
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()


def _setup_logging(log_path):
    """File log always (the exe runs windowless); console too when one exists."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    ))
    root.addHandler(handler)
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(console)


def _say(message: str):
    if sys.stdout is not None:
        print(message)


def _start_tray(url: str, stop):
    """System tray icon (best effort): Open + Quit. Returns the icon or None."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (64, 64), (15, 17, 21))
        draw = ImageDraw.Draw(image)
        draw.ellipse((14, 14, 50, 50), fill=(91, 157, 255))
        icon = pystray.Icon(
            "interview-copilot", image, "Interview Copilot",
            menu=pystray.Menu(
                pystray.MenuItem("Open Interview Copilot",
                                 lambda: webbrowser.open(url), default=True),
                pystray.MenuItem("Quit", lambda: stop()),
            ),
        )
        icon.run_detached()
        return icon
    except Exception as e:
        log.info("Tray icon unavailable: %s", e)
        return None


def main():
    _ensure_streams()  # must run before uvicorn/other libs touch stdout/stderr
    config = load_config()
    _setup_logging(config.log_path)

    import uvicorn  # imported late so any console message appears immediately

    port = find_free_port()
    url = f"http://127.0.0.1:{port}"

    engine = InterviewEngine(config, emit=lambda event: None)
    app = create_app(engine, port)
    engine.set_emitter(app.state.emit)  # server owns the transport
    engine.start()

    hotkeys = HotkeyManager(engine, config.hotkey)
    engine.on_hotkey_change = hotkeys.set_combo

    # log_config=None: don't let uvicorn build its own console logging (it
    # inspects sys.stderr and assumes a real terminal). Its loggers propagate
    # to our root file handler instead.
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", log_config=None,
    ))

    def stop():
        server.should_exit = True

    # Open the browser once the server is actually up (lifespan startup).
    app.state.on_ready = lambda: threading.Thread(
        target=webbrowser.open, args=(url,), daemon=True,
    ).start()

    tray = _start_tray(url, stop)

    _say(f"\n  Interview Copilot running at {url}")
    _say("  Use the tray icon or Ctrl+C here to quit.\n")
    log.info("Interview Copilot starting at %s (configured=%s)", url, config.configured)

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        hotkeys.stop()
        engine.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
