from pynput import keyboard

from configure import DEEPGRAM_API_KEY
from transcriber import DeepgramTranscriber
from gpt_processor import GPTProcessor


def on_press(key, transcriber):
    try:
        if key.char == '`':
            transcriber.toggle_transcription()
    except AttributeError:
        if key == keyboard.Key.esc:
            return False


def main():
    gpt_processor = GPTProcessor()
    transcriber = DeepgramTranscriber(
        deepgram_api_key=DEEPGRAM_API_KEY, gpt_processor=gpt_processor
    )

    try:
        with keyboard.Listener(on_press=lambda key: on_press(key, transcriber)) as listener:
            listener.join()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        transcriber.shutdown()


if __name__ == "__main__":
    main()
