import json

def word_middle(word):
    return (word["start"] + word["end"]) / 2

def find_segment(word, segments):
    middle = word_middle(word)

    for i, seg in enumerate(segments):
        if seg["start"] <= middle <= seg["end"]:
            return i
    #fallback: find the segment with the closest start or end time to the middle of the word
    best_i = 0
    best_distance = None
    for i, seg in enumerate(segments):
        distance = min(abs(middle - seg["start"]), abs(middle - seg["end"]))
        if best_distance is None or distance < best_distance:
            best_i = i
            best_distance = distance
    return best_i

def build_transcript(groq_data):
    segments = []

    for i, seg in enumerate(groq_data.get("segments", [])):
        segments.append({
            "seg_id": i,
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
            "speaker": None,
            "avg_logprob": seg["avg_logprob"],
            "no_speech_prob": seg["no_speech_prob"],
            "compression_ratio": seg["compression_ratio"],
            "words": [],
        })

    if segments:
        for word in groq_data.get("words", []):
            i = find_segment(word, segments)
            segments[i]["words"].append({
                "w": word["word"].strip(),
                "start": word["start"],
                "end": word["end"],
            })

    return {"schema_version": "1.0", "segments": segments}


if __name__ == "__main__":
    with open("groq_response.json") as f:
        groq_data = json.load(f)

    transcript = build_transcript(groq_data)

    with open("raw_transcript.json", "w") as f:
        json.dump(transcript, f, indent=2)

    for seg in transcript["segments"]:
        print(seg["seg_id"], len(seg["words"]), "words:", seg["text"])