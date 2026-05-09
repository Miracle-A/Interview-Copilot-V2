from configure import PROMPT, ANTHROPIC_API_KEY
from anthropic import Anthropic


class GPTProcessor:
    def __init__(self, ai_model="claude-sonnet-4-6"):
        self.model = ai_model
        self.client = Anthropic(api_key=ANTHROPIC_API_KEY)
        self.messages = []
        self.assistant_reply = ""
        self.append_message(
            "user",
            "Note: Remember to always be concise, brief, straight-to-the-point...",
        )

    def append_message(self, role, message):
        self.messages.append({"role": role, "content": message})

    def process_transcript(self, transcript):
        self.append_message("user", transcript)
        self.assistant_reply = ""
        for response_chunk in self.get_response_from_anthropic():
            yield response_chunk
        self.append_message("assistant", self.assistant_reply)

    def get_response_from_anthropic(self):
        with self.client.messages.stream(
            model=self.model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=self.messages,
        ) as stream:
            for text in stream.text_stream:
                self.assistant_reply += text
                yield text


if __name__ == "__main__":
    processor = GPTProcessor()
