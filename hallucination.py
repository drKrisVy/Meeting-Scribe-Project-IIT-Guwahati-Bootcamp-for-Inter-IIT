import json
import re

COMPRESSION_RATIO_MAX = 2.4
NO_SPEECH_PROB_MAX = 0.5
LOGPROB_MIN = -1.0
REPEAT_MIN = 3

STOCK_PHRASES = [
    "thanks for watching", "thank you for watching", "please subscribe",
    "subscribe to my channel", "like and subscribe", "see you in the next video",
    "subtitles by", "transcribed by", "amara.org",
]


def plain(text):
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def find_loop(tokens):
    # same 3-5 word phrase said REPEAT_MIN or more times in a row
    for size in range(3, 6):
        for start in range(0, len(tokens) - size * REPEAT_MIN + 1):
            phrase = tokens[start:start + size]
            repeats = 1
            pos = start + size
            while tokens[pos:pos + size] == phrase:
                repeats += 1
                pos += size
            if repeats >= REPEAT_MIN:
                return start, size, repeats
    return None


def trim_loop(seg):
    words = seg["words"]
    loop = find_loop([plain(w["w"]) for w in words])
    if not loop:
        return None
    start, size, repeats = loop
    keep_until = start + size
    drop_until = start + size * repeats
    removed = " ".join(w["w"] for w in words[keep_until:drop_until])
    seg["words"] = words[:keep_until] + words[drop_until:]
    seg["text"] = " ".join(w["w"] for w in seg["words"])
    return removed


def reason_to_drop(seg):
    if seg["compression_ratio"] > COMPRESSION_RATIO_MAX:
        return f"compression ratio {seg['compression_ratio']:.2f}"

    quiet = seg["no_speech_prob"] > NO_SPEECH_PROB_MAX
    unsure = seg["avg_logprob"] < LOGPROB_MIN
    if quiet and unsure:
        return "probably silence"

    if (quiet or unsure) and any(p in plain(seg["text"]) for p in STOCK_PHRASES):
        return "stock phrase in a low confidence segment"

    return None


def filter_transcript(transcript):
    log = {"dropped": [], "trimmed": [], "repeated": []}
    kept = []

    for seg in transcript["segments"]:
        reason = reason_to_drop(seg)
        if reason:
            log["dropped"].append({"start": seg["start"], "text": seg["text"], "reason": reason})
            continue

        # "Thank you. Thank you. Thank you." as separate segments
        if kept and plain(seg["text"]) and plain(seg["text"]) == plain(kept[-1]["text"]):
            same_in_a_row = 0
            for k in reversed(kept):
                if plain(k["text"]) != plain(seg["text"]):
                    break
                same_in_a_row += 1
            if same_in_a_row >= REPEAT_MIN - 1:
                log["repeated"].append({"start": seg["start"], "text": seg["text"]})
                continue

        removed = trim_loop(seg)
        if removed:
            log["trimmed"].append({"start": seg["start"], "removed": removed})

        if seg["words"]:
            kept.append(seg)

    for i, seg in enumerate(kept):
        seg["seg_id"] = i
    transcript["segments"] = kept

    log["removed"] = len(log["dropped"]) + len(log["trimmed"]) + len(log["repeated"])
    return log


if __name__ == "__main__":
    def seg(text, t, cr=1.2, nsp=0.01, lp=-0.2):
        return {"seg_id": 0, "start": t, "end": t + 2, "text": text, "compression_ratio": cr,
                "no_speech_prob": nsp, "avg_logprob": lp,
                "words": [{"w": w, "start": t, "end": t + 0.1} for w in text.split()]}

    transcript = {"segments": [
        seg("Okay let's start the review.", 0),
        seg("we need to ship we need to ship we need to ship we need to ship by Friday", 2),
        seg("Thanks for watching!", 4, nsp=0.7, lp=-0.4),
        seg("Thanks for watching the demo earlier, it was great.", 6),
        seg("la la la la la la la la la la", 8, cr=3.1),
        seg("uh", 10, nsp=0.8, lp=-1.4),
        seg("Thank you.", 12), seg("Thank you.", 14), seg("Thank you.", 16), seg("Thank you.", 18),
        seg("Real speech after that.", 20),
    ]}
    log = filter_transcript(transcript)
    for s in transcript["segments"]:
        print(s["seg_id"], s["text"])
    print(json.dumps(log, indent=2))
