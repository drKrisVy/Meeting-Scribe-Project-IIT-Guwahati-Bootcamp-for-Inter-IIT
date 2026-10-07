import json
import re
import sys

from llm_client import chat_json
from guardrails import is_spelled_acronym, normalize, sound_similarity

MODEL = "openai/gpt-oss-120b"
MAX_CHARS = 24000
LOW_CONFIDENCE = -0.6

SYSTEM_PROMPT = """You read a raw meeting transcript made by speech recognition and list the
domain terms it contains, including ones that were probably misheard.

Each line is [seg_id] text. A * after the seg_id means recognition confidence was low.

For each term give:
- "canonical": the correct spelling (e.g. "Kubernetes", "PostgreSQL", "Priya")
- "variants_heard": the exact word sequences in the transcript that mean this term,
  copied as written, correct and misheard forms (e.g. ["cube and eighties", "kubernetes"])
- "kind": tech, product, acronym, person or org

Rules:
- Only list terms that really occur. Every variant must be copied from the text.
- A misheard variant must sound like the canonical form.
- Only list a person's name if it is spelled clearly somewhere in the transcript.
- No ordinary words, numbers or dates.
- If there are no domain terms, return an empty list.

Return JSON only:
{"terms": [{"canonical": "...", "variants_heard": ["..."], "kind": "..."}]}"""


def format_lines(segments):
    lines = []
    for seg in segments:
        star = "*" if seg["avg_logprob"] < LOW_CONFIDENCE else ""
        lines.append(f"[{seg['seg_id']}]{star} {seg['text']}")
    return "\n".join(lines)


def windows(segments):
    window, size = [], 0
    for seg in segments:
        if window and size + len(seg["text"]) > MAX_CHARS:
            yield window
            window, size = [], 0
        window.append(seg)
        size += len(seg["text"]) + 10
    if window:
        yield window


def said(phrase, text):
    phrase = normalize(phrase)
    return bool(phrase) and re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def check_terms(terms, transcript):
    full_text = normalize(" ".join(seg["text"] for seg in transcript["segments"]))
    kept = {}

    for term in terms:
        canonical = (term.get("canonical") or "").strip()
        if not canonical:
            continue
        kind = term.get("kind") or "tech"

        # a name the model came up with, never actually said
        if kind == "person" and not said(canonical, full_text):
            continue

        variants = []
        for v in term.get("variants_heard") or []:
            if not said(v, full_text):
                continue
            if normalize(v) == normalize(canonical) or is_spelled_acronym(v, canonical) \
                    or sound_similarity(v, canonical) >= 0.5:
                variants.append(v)

        if not variants and not said(canonical, full_text):
            continue

        entry = kept.setdefault(normalize(canonical),
                                {"canonical": canonical, "variants_heard": [], "kind": kind})
        for v in variants:
            if v not in entry["variants_heard"]:
                entry["variants_heard"].append(v)

    return list(kept.values())


def build_inventory(transcript):
    proposed = []
    for window in windows(transcript["segments"]):
        data = chat_json(MODEL, SYSTEM_PROMPT, format_lines(window))
        proposed += data.get("terms") or []
    terms = check_terms(proposed, transcript)
    return {"terms": terms, "proposed": len(proposed), "kept": len(terms)}


if __name__ == "__main__":
    with open("raw_transcript.json") as f:
        transcript = json.load(f)

    if "--fakes" in sys.argv:
        fake = [
            {"canonical": "Kubernetes", "variants_heard": ["Kubernetes", "made up words"], "kind": "tech"},
            {"canonical": "Maria", "variants_heard": ["Priya"], "kind": "person"},
            {"canonical": "Priya", "variants_heard": ["Priya"], "kind": "person"},
        ]
        inventory = {"terms": check_terms(fake, transcript)}
    else:
        inventory = build_inventory(transcript)

    print(json.dumps(inventory, indent=2))
