import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from chunks import make_pieces

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


def shift(items, offset):
    for item in items:
        item["start"] = round(item["start"] + offset, 3)
        item["end"] = round(item["end"] + offset, 3)
    return items


def transcribe_long(audio, out_dir):
    pieces = make_pieces(audio, out_dir)
    merged = {"segments": [], "words": [], "chunks": []}
    for path, offset in pieces:
        data = transcribe(path)
        # each piece starts at 0 s, so move its times back onto the full recording
        merged["segments"] += shift(data.get("segments") or [], offset)
        merged["words"] += shift(data.get("words") or [], offset)
        merged["chunks"].append({"file": Path(path).name, "start": offset})
    return merged


if __name__ == "__main__":
    data = transcribe(sys.argv[1])

    with open("groq_response.json", "w") as f:
        json.dump(data, f, indent=2)

    for seg in data.get("segments", []):
        print(f"[{seg['start']:6.2f} - {seg['end']:6.2f}]  {seg['text'].strip()}")