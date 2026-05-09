"""Probe which (device_index, channels, rate) combos pyaudio can actually open."""
import pyaudio

DEVICES_TO_TRY = [17, 9, 4, 1]
CHANNEL_OPTIONS = [1, 2]
RATE_OPTIONS = [16000, 22050, 44100, 48000]

p = pyaudio.PyAudio()
print(f"\nProbing devices for input capture (showing only successful combos):\n")
for idx in DEVICES_TO_TRY:
    try:
        info = p.get_device_info_by_index(idx)
        name = info["name"]
        max_ch = int(info["maxInputChannels"])
        default_rate = int(info["defaultSampleRate"])
    except Exception as e:
        print(f"[{idx}] ERROR getting info: {e}")
        continue
    if max_ch == 0:
        continue
    print(f"\n--- Device {idx}: {name} (maxInputChannels={max_ch}, defaultRate={default_rate}) ---")
    for ch in CHANNEL_OPTIONS:
        if ch > max_ch:
            continue
        for rate in RATE_OPTIONS:
            try:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=ch,
                    rate=rate,
                    input=True,
                    input_device_index=idx,
                    frames_per_buffer=1024,
                )
                stream.close()
                print(f"  OK   channels={ch}, rate={rate}")
            except Exception as e:
                msg = str(e).strip().splitlines()[0][:80]
                print(f"  FAIL channels={ch}, rate={rate} -> {msg}")
p.terminate()
