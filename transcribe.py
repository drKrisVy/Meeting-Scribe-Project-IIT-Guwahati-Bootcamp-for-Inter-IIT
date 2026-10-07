import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq()

STT_MODEL = "whisper-large-v3-turbo"


def transcribe(audio_path):
    audio_path = Path(audio_path)
    result = client.audio.transcriptions.create(
        file=(audio_path.name, audio_path.read_bytes()),
        model=STT_MODEL,
        language="en",
        temperature=0,
        response_format="verbose_json",
        timestamp_granularities=["word", "segment"],
    )
    return result.model_dump()


if __name__ == "__main__":
    data = transcribe(sys.argv[1])

    with open("groq_response.json", "w") as f:
        json.dump(data, f, indent=2)

    for seg in data.get("segments", []):
        print(f"[{seg['start']:6.2f} - {seg['end']:6.2f}]  {seg['text'].strip()}")