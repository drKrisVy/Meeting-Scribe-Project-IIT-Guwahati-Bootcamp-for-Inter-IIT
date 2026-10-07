import json
import sys

from llm_client import chat_json

from apply_edits import apply_edits
from guardrails import check_edit, FLAG_RULES



MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You fix speech recognition errors in a meeting transcript.

Each segment is shown as [seg_id] followed by numbered words, like 0:okay 1:team.

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


def format_transcript(transcript):
    lines = []
    for seg in transcript["segments"]:
        numbered = [f"{i}:{w['w']}" for i, w in enumerate(seg["words"])]
        lines.append(f"[{seg['seg_id']}] " + " ".join(numbered))
    return "\n".join(lines)


def propose_edits(transcript):
    data = chat_json(MODEL, SYSTEM_PROMPT, format_transcript(transcript))
    return data.get("edits", [])


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


def decide_statuses(edits, segments_by_id):
    accepted = []

    for i, edit in enumerate(edits):
        edit["edit_id"] = f"e{i + 1}"
        rule = check_edit(edit, segments_by_id)

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


def refine(transcript, edits=None):
    if edits is None:
        edits = propose_edits(transcript)

    segments_by_id = {seg["seg_id"]: seg for seg in transcript["segments"]}
    decide_statuses(edits, segments_by_id)
    refined = apply_edits(transcript, edits)
    return edits, refined


if __name__ == "__main__":
    with open("raw_transcript.json") as f:
        transcript = json.load(f)

    if "--fakes" in sys.argv:
        edits, refined = refine(transcript, fake_edits())
        suffix = "_fakes"
    else:
        edits, refined = refine(transcript)
        suffix = ""

    with open(f"edits{suffix}.json", "w") as f:
        json.dump({"edits": edits}, f, indent=2)

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