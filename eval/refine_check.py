import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from refine import refine  # noqa: E402

# sentences the way Whisper often mishears them, and what each should become
SENTENCES = [
    ("Okay team, let's start the infra review.", None),
    ("We moved the cluster to cube and eighties last week.", "Kubernetes"),
    ("The cube and eighties pods keep restarting at night.", "Kubernetes"),
    ("Priya, can you push the fix to get hub by Friday?", "GitHub"),
    ("Yes, I'll do that.", None),
    ("We need to by two more servers for the beta.", "buy"),
    ("The a p i is timing out when the load goes up.", "API"),
    ("We can't ship until the post grass migration is done.", "Postgres"),
    ("We'll need fifteen test devices.", None),
]


def make_transcript(sentences):
    segments, t = [], 0.0
    for i, text in enumerate(sentences):
        words = []
        for w in text.split():
            words.append({"w": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
            t += 0.35
        segments.append({"seg_id": i, "start": words[0]["start"], "end": words[-1]["end"],
                         "text": text, "speaker": None, "avg_logprob": -0.4,
                         "no_speech_prob": 0.01, "compression_ratio": 1.2, "words": words})
        t += 0.5
    return {"segments": segments}


if __name__ == "__main__":
    transcript = make_transcript([s for s, _ in SENTENCES])
    edits, refined, inventory = refine(transcript)

    print("Terms found:", [t["canonical"] for t in inventory["terms"]])
    print("\nEdits:")
    for e in edits:
        print(f"  [{e['status']}] '{e['original']}' -> '{e['replacement']}'  rule={e['rule']}")

    print("\nResult:")
    for (raw, expected), seg in zip(SENTENCES, refined["segments"]):
        if expected:
            mark = "OK  " if expected.lower() in seg["text"].lower() else "MISS"
        else:
            mark = "OK  " if seg["text"] == raw else "CHANGED"
        print(f"  {mark} {seg['text']}")
