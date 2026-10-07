import json
import sys

from llm_client import chat_json

from apply_edits import apply_edits
from guardrails import build_support, check_edit, normalize, FLAG_RULES
from inventory import LOW_CONFIDENCE, build_inventory



MODEL = "openai/gpt-oss-120b"
WINDOW = 20
CONTEXT = 3

SYSTEM_PROMPT = """You fix speech recognition errors in a meeting transcript.

Each segment is shown as [seg_id] followed by numbered words, like 0:okay 1:team.
A * after the seg_id means recognition confidence was low there.
Lines under "CONTEXT" are only there to help you understand; never edit them.
"TERMS" lists checked domain terms for this meeting; prefer those spellings.

Fix only words that were clearly misheard: technical terms, names, acronyms,
words that sound alike, and words wrongly split or merged.

Never change grammar, filler words, numbers, negations (not, can't, never),
or words like will, should, must, can.
Never rephrase. If you are unsure, propose nothing. An empty list is a valid answer.

Each edit replaces a small run of words: at most 4 words in, at most 4 words out.
start_word is the number of the first word to replace.
end_word is the number just AFTER the last word to replace.
"original" must be exactly those words, copied from the transcript.

Return JSON only, in this shape:
{"edits": [{"seg_id": 0, "start_word": 0, "end_word": 1,
            "original": "...", "replacement": "...", "reason": "..."}]}"""


def numbered_line(seg):
    star = "*" if seg["avg_logprob"] < LOW_CONFIDENCE else ""
    numbered = [f"{i}:{w['w']}" for i, w in enumerate(seg["words"])]
    return f"[{seg['seg_id']}]{star} " + " ".join(numbered)


def format_window(before, window, after, terms):
    parts = []
    if terms:
        parts.append("TERMS: " + ", ".join(t["canonical"] for t in terms))
    if before:
        parts.append("CONTEXT:\n" + "\n".join(s["text"] for s in before))
    parts.append("SEGMENTS:\n" + "\n".join(numbered_line(s) for s in window))
    if after:
        parts.append("CONTEXT:\n" + "\n".join(s["text"] for s in after))
    return "\n\n".join(parts)


def propose_edits(transcript, terms):
    # 20 segments at a time so long meetings fit, with 3 read-only segments each side
    segments = transcript["segments"]
    edits = []
    for start in range(0, len(segments), WINDOW):
        window = segments[start:start + WINDOW]
        before = segments[max(0, start - CONTEXT):start]
        after = segments[start + WINDOW:start + WINDOW + CONTEXT]
        allowed = {s["seg_id"] for s in window}
        data = chat_json(MODEL, SYSTEM_PROMPT, format_window(before, window, after, terms))
        for edit in data.get("edits", []):
            if edit.get("seg_id") not in allowed:
                edit["outside_window"] = True
            edit["source"] = "llm"
            edits.append(edit)
    return edits


def fake_edits():
    return [
        {"seg_id": 3, "start_word": 4, "end_word": 7,
         "original": "move to launch", "replacement": "move the launch", "reason": "fake"},
        {"seg_id": 3, "start_word": 5, "end_word": 7,
         "original": "to launch", "replacement": "to lunch", "reason": "fake, overlaps"},
        {"seg_id": 1, "start_word": 5, "end_word": 6,
         "original": "revised", "replacement": "re vised", "reason": "fake, 1 word to 2"},
        {"seg_id": 3, "start_word": 9, "end_word": 10,
         "original": "15th", "replacement": "50th", "reason": "fake"},
    ]


def ranges_overlap(a, b):
    return a["start_word"] < b["end_word"] and b["start_word"] < a["end_word"]


def decide(edit, segments_by_id, support, accepted):
    if edit.pop("outside_window", False):
        rule = "outside_window"
    else:
        rule = check_edit(edit, segments_by_id, support)

    if rule is None:
        for other in accepted:
            if other["seg_id"] == edit["seg_id"] and ranges_overlap(edit, other):
                rule = "overlap"
                break

    if rule is None:
        edit["status"] = "accepted"
        accepted.append(edit)
    elif rule in FLAG_RULES:
        edit["status"] = "flagged"
    else:
        edit["status"] = "rejected"
    edit["rule"] = rule


def find_phrase(words, phrase):
    target = normalize(phrase).split()
    tokens = [normalize(w["w"]) for w in words]
    for i in range(len(tokens) - len(target) + 1):
        if target and tokens[i:i + len(target)] == target:
            yield i, i + len(target)


def consistency_edits(transcript, terms, accepted):
    # if "cube and eighties" got fixed once, fix it everywhere else too
    variant_to_term = {}
    for term in terms:
        for v in term["variants_heard"]:
            if normalize(v) != normalize(term["canonical"]):
                variant_to_term[normalize(v)] = term["canonical"]

    fixed = {}
    for edit in accepted:
        key = normalize(edit["original"])
        if key in variant_to_term and normalize(edit["replacement"]) == normalize(variant_to_term[key]):
            fixed[key] = edit["replacement"]

    new_edits = []
    for variant, replacement in fixed.items():
        for seg in transcript["segments"]:
            for start, end in find_phrase(seg["words"], variant):
                spot = {"start_word": start, "end_word": end}
                if any(e["seg_id"] == seg["seg_id"] and ranges_overlap(e, spot) for e in accepted):
                    continue
                new_edits.append({
                    "seg_id": seg["seg_id"], "start_word": start, "end_word": end,
                    "original": " ".join(w["w"] for w in seg["words"][start:end]),
                    "replacement": replacement, "reason": "same fix as elsewhere",
                    "source": "consistency",
                })
    return new_edits


def decide_statuses(edits, segments_by_id, support=None, transcript=None, terms=()):
    accepted = []

    for i, edit in enumerate(edits):
        edit["edit_id"] = f"e{i + 1}"
        decide(edit, segments_by_id, support, accepted)

    if transcript is not None:
        for edit in consistency_edits(transcript, terms, accepted):
            edit["edit_id"] = f"e{len(edits) + 1}"
            decide(edit, segments_by_id, support, accepted)
            edits.append(edit)


def refine(transcript, edits=None):
    if edits is None:
        inventory = build_inventory(transcript)
        edits = propose_edits(transcript, inventory["terms"])
    else:
        inventory = {"terms": []}

    segments_by_id = {seg["seg_id"]: seg for seg in transcript["segments"]}
    support = build_support(transcript, inventory["terms"])
    decide_statuses(edits, segments_by_id, support, transcript, inventory["terms"])
    refined = apply_edits(transcript, edits)
    return edits, refined, inventory


if __name__ == "__main__":
    with open("raw_transcript.json") as f:
        transcript = json.load(f)

    if "--fakes" in sys.argv:
        edits, refined, inventory = refine(transcript, fake_edits())
        suffix = "_fakes"
    else:
        edits, refined, inventory = refine(transcript)
        suffix = ""

    with open(f"edits{suffix}.json", "w") as f:
        json.dump({"inventory": inventory, "edits": edits}, f, indent=2)

    with open(f"refined_transcript{suffix}.json", "w") as f:
        json.dump(refined, f, indent=2)

    print("Edits:")
    for e in edits:
        print(f"  {e['edit_id']} [{e['status']}] seg {e.get('seg_id')} words "
              f"{e.get('start_word')}-{e.get('end_word')}: "
              f"'{e.get('original')}' -> '{e.get('replacement')}'  rule={e['rule']}")

    print("\nChanged segments:")
    for raw_seg, new_seg in zip(transcript["segments"], refined["segments"]):
        if raw_seg["text"] != new_seg["text"]:
            print(f"  [{raw_seg['seg_id']}] raw:     {raw_seg['text']}")
            print(f"       refined: {new_seg['text']}")