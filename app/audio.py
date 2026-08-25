"""Audio capture: microphone, system audio (WASAPI loopback), or both mixed.

Uses PyAudioWPatch (a PortAudio fork) so "the other person's voice" on a
Teams/Zoom call can be captured from any output device — no Stereo Mix needed.
Everything is normalized to 16 kHz mono int16 before it reaches the
transcriber. One persistent PyAudio instance for the whole session; streams
are paused/resumed between turns, never rebuilt.
"""
import threading
import time
from array import array

try:
    import pyaudiowpatch as pyaudio
    HAS_LOOPBACK = True
except ImportError:  # non-Windows dev fallback
    import pyaudio
    HAS_LOOPBACK = False

CAPTURE_RATE = 16000
CAPTURE_CHANNELS = 1
# 100 ms buffers: half the SDK Microphone's 200 ms for snappier finalization.
FRAMES_PER_BUFFER = 1600
# Cap the loopback-ahead buffer at ~2 s so drift can't grow unbounded.
MAX_MIX_BUFFER_BYTES = CAPTURE_RATE * 2 * 2
LEVEL_INTERVAL_S = 0.08


class MicError(Exception):
    pass


def to_mono_16k(data: bytes, src_rate: int, src_channels: int) -> bytes:
    """Downmix + resample int16 PCM to 16 kHz mono (nearest-neighbor).

    Pure Python on purpose: a 100 ms chunk of 48 kHz stereo is only ~4800
    output samples, far too small to justify a numpy dependency in the exe.
    """
    if src_rate == CAPTURE_RATE and src_channels == 1:
        return data
    samples = array("h")
    samples.frombytes(data)
    frames = len(samples) // src_channels
    if frames == 0:
        return b""
    out_frames = max(1, int(frames * CAPTURE_RATE / src_rate))
    step = frames / out_frames
    out = array("h", bytes(2 * out_frames))
    for i in range(out_frames):
        base = int(i * step) * src_channels
        if src_channels == 1:
            out[i] = samples[base]
        else:
            acc = 0
            for c in range(src_channels):
                acc += samples[base + c]
            out[i] = acc // src_channels
    return out.tobytes()


def _mix_int16(a: bytes, b: bytes) -> bytes:
    """Add two equal-length int16 PCM buffers with clipping."""
    xs = array("h")
    xs.frombytes(a)
    ys = array("h")
    ys.frombytes(b)
    n = min(len(xs), len(ys))
    for i in range(n):
        v = xs[i] + ys[i]
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        xs[i] = v
    return xs.tobytes()


def _peak(data: bytes) -> float:
    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return 0.0
    return min(1.0, max(abs(s) for s in samples) / 32768.0)


class AudioCapture:
    """Captures from the selected source(s) and delivers 16 kHz mono chunks.

    Sources:
      mic    — your microphone (default input device)
      system — what the computer is playing (WASAPI loopback): the other
               side of a call, with any headphones
      both   — mic + system mixed into one stream

    In "both" mode the mic stream sets the cadence: each mic chunk pulls the
    matching amount of resampled loopback audio from a small ring buffer
    (zero-padded when the computer is silent).
    """

    def __init__(self, send, level_cb=None,
                 mic_device: int | None = None,
                 system_device: int | None = None):
        self._send = send
        self._level_cb = level_cb or (lambda v: None)
        self._pa = pyaudio.PyAudio()
        self._lock = threading.Lock()
        self._capturing = False
        self._mic_stream = None
        self._sys_stream = None
        self._sys_rate = CAPTURE_RATE
        self._sys_channels = 1
        self._mix_buf = bytearray()
        self._last_level = 0.0
        self.source = "mic"
        self.mic_device = mic_device if mic_device is not None else self._default_input_index()
        self.system_device = system_device

    # -- device discovery ----------------------------------------------------

    def _default_input_index(self) -> int:
        try:
            return int(self._pa.get_default_input_device_info()["index"])
        except Exception:
            return 0

    def _default_loopback_index(self) -> int | None:
        if not HAS_LOOPBACK:
            return None
        try:
            return int(self._pa.get_default_wasapi_loopback()["index"])
        except Exception:
            return None

    def list_devices(self) -> dict:
        default_in = self._default_input_index()
        mics, loopbacks = [], []
        loopback_indexes = set()
        if HAS_LOOPBACK:
            try:
                for info in self._pa.get_loopback_device_info_generator():
                    loopback_indexes.add(int(info["index"]))
                    loopbacks.append({
                        "index": int(info["index"]),
                        "name": str(info["name"]).replace(" [Loopback]", ""),
                        "default": int(info["index"]) == self._default_loopback_index(),
                    })
            except Exception:
                pass
        for i in range(self._pa.get_device_count()):
            try:
                info = self._pa.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0)) < 1 or i in loopback_indexes:
                continue
            mics.append({
                "index": i,
                "name": str(info.get("name", f"Device {i}")),
                "default": i == default_in,
            })
        return {
            "mics": mics,
            "loopbacks": loopbacks,
            "has_loopback": bool(loopbacks),
        }

    # -- stream callbacks (PortAudio threads) --------------------------------

    def _emit_level(self, data: bytes):
        now = time.monotonic()
        if now - self._last_level >= LEVEL_INTERVAL_S:
            self._last_level = now
            try:
                self._level_cb(_peak(data))
            except Exception:
                pass

    def _deliver(self, data: bytes):
        self._emit_level(data)
        try:
            self._send(data)
        except Exception:
            pass  # transport hiccup; transcriber surfaces its own errors

    def _mic_callback(self, in_data, frame_count, time_info, status):
        if self._capturing and in_data:
            if self.source == "both":
                with self._lock:
                    take = min(len(in_data), len(self._mix_buf))
                    other = bytes(self._mix_buf[:take])
                    del self._mix_buf[:take]
                if len(other) < len(in_data):
                    other += b"\x00" * (len(in_data) - len(other))
                self._deliver(_mix_int16(in_data, other))
            else:
                self._deliver(in_data)
        return (None, pyaudio.paContinue)

    def _sys_callback(self, in_data, frame_count, time_info, status):
        if self._capturing and in_data:
            converted = to_mono_16k(in_data, self._sys_rate, self._sys_channels)
            if self.source == "both":
                with self._lock:
                    self._mix_buf.extend(converted)
                    if len(self._mix_buf) > MAX_MIX_BUFFER_BYTES:
                        del self._mix_buf[:len(self._mix_buf) - MAX_MIX_BUFFER_BYTES]
            else:
                self._deliver(converted)
        return (None, pyaudio.paContinue)

    # -- lifecycle -----------------------------------------------------------

    def open(self):
        """(Re)open the streams the current source needs."""
        with self._lock:
            self._close_streams_locked()
            self._mix_buf.clear()
            errors = []
            if self.source in ("mic", "both"):
                try:
                    self._mic_stream = self._pa.open(
                        format=pyaudio.paInt16,
                        channels=CAPTURE_CHANNELS,
                        rate=CAPTURE_RATE,
                        input=True,
                        input_device_index=self.mic_device,
                        frames_per_buffer=FRAMES_PER_BUFFER,
                        stream_callback=self._mic_callback,
                        start=False,
                    )
                except Exception as e:
                    errors.append(f"microphone: {e}")
            if self.source in ("system", "both"):
                index = self.system_device
                if index is None:
                    index = self._default_loopback_index()
                if index is None:
                    errors.append(
                        "system audio: no loopback device found "
                        "(is this Windows with an output device active?)"
                    )
                else:
                    try:
                        info = self._pa.get_device_info_by_index(index)
                        self._sys_rate = int(info["defaultSampleRate"])
                        self._sys_channels = max(1, int(info["maxInputChannels"]))
                        self._sys_stream = self._pa.open(
                            format=pyaudio.paInt16,
                            channels=self._sys_channels,
                            rate=self._sys_rate,
                            input=True,
                            input_device_index=index,
                            frames_per_buffer=int(self._sys_rate // 10),
                            stream_callback=self._sys_callback,
                            start=False,
                        )
                    except Exception as e:
                        errors.append(f"system audio: {e}")
            if errors and self._mic_stream is None and self._sys_stream is None:
                raise MicError("Could not open audio: " + "; ".join(errors))
            if errors:
                raise MicError("Partially opened audio: " + "; ".join(errors))

    def resume(self):
        with self._lock:
            if self._mic_stream is None and self._sys_stream is None:
                raise MicError("Audio is not open.")
            self._capturing = True
            for stream in (self._mic_stream, self._sys_stream):
                if stream is not None and not stream.is_active():
                    stream.start_stream()

    def pause(self):
        with self._lock:
            self._capturing = False
            for stream in (self._mic_stream, self._sys_stream):
                if stream is not None and stream.is_active():
                    try:
                        stream.stop_stream()
                    except Exception:
                        pass

    def set_source(self, source: str):
        self.source = source
        self.open()

    def set_mic_device(self, index: int):
        self.mic_device = index
        self.open()

    def set_system_device(self, index: int):
        self.system_device = index
        self.open()

    def _close_streams_locked(self):
        for name in ("_mic_stream", "_sys_stream"):
            stream = getattr(self, name)
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
                setattr(self, name, None)

    def terminate(self):
        with self._lock:
            self._capturing = False
            self._close_streams_locked()
        try:
            self._pa.terminate()
        except Exception:
            pass
