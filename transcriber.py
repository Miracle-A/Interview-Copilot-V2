import json
import time
import threading
from enum import Enum
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions, Microphone

from gpt_processor import GPTProcessor
from configure import DEEPGRAM_API_KEY


class TranscriptionState(Enum):
    LISTENING = 1
    PROCESSING = 2
    DONE = 3


CAPTURE_CHANNELS = 1
CAPTURE_RATE = 16000


def _build_live_options():
    return LiveOptions(
        model="nova-2",
        language="en-US",
        encoding="linear16",
        channels=CAPTURE_CHANNELS,
        sample_rate=CAPTURE_RATE,
        punctuate=True,
        smart_format=True,
        numerals=True,
        endpointing="400",
    )


class DeepgramTranscriber:
    def __init__(self, deepgram_api_key, device_index=1, gpt_processor=None):
        self.deepgram = DeepgramClient(api_key=deepgram_api_key)
        self.transcript_parts = []
        self.device_index = device_index
        self.dg_connection = self.deepgram.listen.live.v("1")
        self.setup_listeners()
        self.state = TranscriptionState.DONE
        self.toggle_queued = False
        self.gpt_processor = gpt_processor
        self.keep_alive_thread = None
        self.keep_alive_active = False
        self.microphone = None
        self._open_session()

    def _open_session(self):
        self.dg_connection.start(_build_live_options())
        self.microphone = Microphone(
            self.dg_connection.send,
            device_index=self.device_index,
            channels=CAPTURE_CHANNELS,
            rate=CAPTURE_RATE,
        )
        print("Press tilde to toggle and escape to exit...")
        self.start_keep_alive()

    def on_message(self, *args, **kwargs):
        if self.state == TranscriptionState.DONE:
            return
        result = kwargs.get("result")
        if not result or not result.channel.alternatives:
            return
        snippet = result.channel.alternatives[0].transcript
        if snippet:
            self.transcript_parts.append(snippet + " ")

    def on_error(self, *args, **kwargs):
        error = kwargs.get("error")
        if error:
            print(f"\n\n{error}\n\n")

    def keep_alive_loop(self):
        while self.keep_alive_active:
            self.dg_connection.keep_alive()
            time.sleep(1.0)

    def start_keep_alive(self):
        if not self.keep_alive_thread:
            self.keep_alive_active = True
            self.keep_alive_thread = threading.Thread(
                target=self.keep_alive_loop, daemon=True
            )
            self.keep_alive_thread.start()

    def stop_keep_alive(self):
        if self.keep_alive_thread:
            self.keep_alive_active = False
            self.keep_alive_thread.join()
            self.keep_alive_thread = None

    def setup_listeners(self):
        self.dg_connection.on(LiveTranscriptionEvents.Transcript, self.on_message)
        self.dg_connection.on(LiveTranscriptionEvents.Error, self.on_error)

    def _start_listening(self):
        self.stop_keep_alive()
        self.transcript_parts.clear()
        self.microphone.start()
        self.state = TranscriptionState.LISTENING
        print("Listening...")

    def _finish_turn(self):
        self.state = TranscriptionState.PROCESSING
        time.sleep(1.2)
        self.microphone.finish()
        try:
            self.dg_connection.send(json.dumps({"type": "Finalize"}))
        except Exception as e:
            print(f"\n[Finalize send failed: {e}]")
        time.sleep(0.4)

        full_transcript = "".join(self.transcript_parts).strip()
        self.transcript_parts.clear()
        print(f"\nTranscript: {full_transcript}")

        if self.gpt_processor and full_transcript:
            print("\nProcessed Output: ", end="", flush=True)
            for response in self.gpt_processor.process_transcript(full_transcript):
                print(response, end="", flush=True)
            print()

        self.microphone = Microphone(
            self.dg_connection.send,
            device_index=self.device_index,
            channels=CAPTURE_CHANNELS,
            rate=CAPTURE_RATE,
        )
        self.start_keep_alive()
        self.state = TranscriptionState.DONE
        print("\nPress tilde to toggle and escape to exit...")

        if self.toggle_queued:
            self.toggle_queued = False
            self.toggle_transcription()

    def toggle_transcription(self):
        if self.state == TranscriptionState.DONE:
            self._start_listening()
            return "Started"
        elif self.state == TranscriptionState.LISTENING:
            self._finish_turn()
            return "Finished"
        elif self.state == TranscriptionState.PROCESSING:
            self.toggle_queued = True
            print("Transcription toggle is queued.")
            return "Queued"

    def shutdown(self):
        self.keep_alive_active = False
        try:
            if self.microphone:
                self.microphone.finish()
        except Exception:
            pass
        try:
            self.dg_connection.finish()
        except Exception:
            pass
