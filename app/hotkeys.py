import logging

from pynput import keyboard

log = logging.getLogger("app.hotkeys")


class HotkeyManager:
    """Global hotkey: fires even when another window has focus — that's the
    point. Default is a chord (Ctrl+Space) so typing normal text in other
    apps can't trigger it; the bare-backtick legacy option still exists.

    The callback only enqueues, so the listener thread never blocks.
    """

    def __init__(self, engine, combo: str):
        self.engine = engine
        self.combo = combo
        self._listener = None
        self.start()

    def _fire(self):
        self.engine.toggle()

    def start(self):
        self.stop()
        combo = self.combo
        try:
            if len(combo) == 1:  # single printable character (legacy backtick)
                char = combo

                def on_press(key):
                    try:
                        if key.char == char:
                            self._fire()
                    except AttributeError:
                        pass  # modifier / non-character key

                self._listener = keyboard.Listener(on_press=on_press, daemon=True)
            else:
                self._listener = keyboard.GlobalHotKeys({combo: self._fire})
                self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            log.warning("Could not start hotkey listener for %r: %s", combo, e)
            self._listener = None

    def set_combo(self, combo: str):
        self.combo = combo
        self.start()

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
