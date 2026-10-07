import json
import re
import sys

from rapidfuzz.fuzz import partial_ratio_alignment

from guardrails import normalize

QUOTE_MATCH_MIN = 90
QUOTE_ELSEWHERE_MIN = 95

FIRST_PERSON = ["i'll", "i will", "let me", "i can take", "i can do", "i'm on it", "i am on it"]
ACCEPTANCE_WORDS = ["yes", "yeah", "yep", "okay", "ok", "sure", "agreed", "agree",
                    "decided", "sounds good", "let's do", "fine", "done", "will do",
                    "deal", "go ahead", "makes sense", "works for me"]


def snap_to_words(text, start, end):
    while start > 0 and text[start - 1] != " ":
        start -= 1
    while end < len(text) and text[end] != " ":
        end += 1
    return text[start:end].strip()


def match_in_segment(quote, seg):
    text = seg["text"]
    if len(quote) > len(text) + 5:
        return 0, None
    result = partial_ratio_alignment(quote.lower(), text.lower())
    exact = snap_to_words(text, result.dest_start, result.dest_end)
    return result.score, exact


def verify_quote(evidence, segments_by_id):
    quote = evidence.get("quote", "")
    cited = evidence.get("seg_id")
    if not quote:
        return False

    for seg_id in [cited, cited - 1 if isinstance(cited, int) else None,
                   cited + 1 if isinstance(cited, int) else None]:
        seg = segments_by_id.get(seg_id)
        if seg is None:
            continue
        score, exact = match_in_segment(quote, seg)
        if score >= QUOTE_MATCH_MIN:
            evidence["seg_id"] = seg_id
            evidence["quote"] = exact
            evidence["t"] = seg["start"]
            return True

    for seg_id, seg in segments_by_id.items():
        score, exact = match_in_segment(quote, seg)
        if score >= QUOTE_ELSEWHERE_MIN:
            evidence["seg_id"] = seg_id
            evidence["quote"] = exact
            evidence["t"] = seg["start"]
            return True

    return False


def contains_phrase(phrase, text):
    phrase = normalize(phrase)
    if not phrase:
        return False
    return re.search(rf"\b{re.escape(phrase)}\b", normalize(text)) is not None


def verify_item(item, segments_by_id):
    item["flags"] = []

    good = []
    for ev in item.get("evidence", []):
        if verify_quote(ev, segments_by_id):
            good.append(ev)
        else:
            item["flags"].append(f"quote_not_found: {ev.get('quote')!r}")
    item["evidence"] = good
    item["verified"] = len(good) > 0

    for ev in good:
        if ev.get("role") == "acceptance":
            if not any(contains_phrase(w, ev["quote"]) for w in ACCEPTANCE_WORDS):
                ev["role"] = "statement"
                item["flags"].append(f"acceptance_without_agreement: {ev['quote']!r}")

    quotes = [ev["quote"] for ev in good]
    roles = [ev.get("role") for ev in good]

    owner = item.get("owner")
    if owner and not any(contains_phrase(owner, q) for q in quotes):
        item["flags"].append(f"owner_ungrounded: {owner!r}")
        item["owner"] = None

    deadline = item.get("deadline")
    if deadline and not any(contains_phrase(deadline, q) for q in quotes):
        item["flags"].append(f"deadline_ungrounded: {deadline!r}")
        item["deadline"] = None

    if item.get("status") == "agreed" and "acceptance" not in roles:
        item["status"] = "proposed"
        item["flags"].append("agreed_without_acceptance")

    if item.get("commitment") == "confirmed":
        volunteered = any(contains_phrase(p, q) for p in FIRST_PERSON for q in quotes)
        if "acceptance" not in roles and not volunteered:
            item["commitment"] = "assigned"
            item["flags"].append("confirmed_without_acceptance")

    if item.get("commitment") == "assigned" and not item.get("owner"):
        item["commitment"] = "suggested"
        item["flags"].append("assigned_without_owner")

    return item


def verify_record(draft, transcript):
    segments_by_id = {seg["seg_id"]: seg for seg in transcript["segments"]}
    record = {"decisions": [], "action_items": [], "open_questions": [], "unverified": []}

    for key in ["decisions", "action_items", "open_questions"]:
        for item in draft.get(key, []):
            item = verify_item(item, segments_by_id)
            if item["verified"]:
                record[key].append(item)
            else:
                item["kind"] = key
                record["unverified"].append(item)

    return record


def fake_draft():
    return {
        "decisions": [
            {"id": "D1", "text": "Move the launch to the 15th", "status": "agreed",
             "evidence": [{"seg_id": 3, "role": "statement",
                           "quote": "we agreed to move the launch"}]},
            {"id": "D2", "text": "Cancel the launch", "status": "agreed",
             "evidence": [{"seg_id": 3, "role": "acceptance",
                           "quote": "we decided to cancel the launch"}]},
            {"id": "D3", "text": "Check the logs", "status": "agreed",
             "evidence": [{"seg_id": 4, "role": "acceptance",
                           "quote": "Someone should check the Kubernetes logs"}]},
        ],
        "action_items": [
            {"id": "A1", "task": "Send the budget", "owner": "Priya", "deadline": "by Monday",
             "commitment": "confirmed",
             "evidence": [{"seg_id": 1, "role": "assignment",
                           "quote": "Priya can you send the revised budget by Friday"}]},
            {"id": "A2", "task": "Check the logs", "owner": "Rahul", "deadline": None,
             "commitment": "assigned",
             "evidence": [{"seg_id": 0, "role": "statement",
                           "quote": "someone should check the Kubernetes logs"}]},
        ],
        "open_questions": [],
    }


if __name__ == "__main__":
    with open("refined_transcript.json") as f:
        transcript = json.load(f)

    if "--fakes" in sys.argv:
        draft = fake_draft()
        out_path = "record_fakes.json"
    else:
        with open("record_draft.json") as f:
            draft = json.load(f)
        out_path = "record.json"

    record = verify_record(draft, transcript)

    with open(out_path, "w") as f:
        json.dump(record, f, indent=2)

    for key in ["decisions", "action_items", "open_questions", "unverified"]:
        print(key.upper())
        for item in record[key]:
            label = item.get("status") or item.get("commitment") or ""
            title = item.get("text") or item.get("task")
            print(f"  {item.get('id')} [{label}] {title}")
            if "owner" in item:
                print(f"      owner={item.get('owner')}  deadline={item.get('deadline')}")
            for ev in item.get("evidence", []):
                print(f"      {ev.get('role')}: seg {ev['seg_id']} \"{ev['quote']}\"")
            for flag in item["flags"]:
                print(f"      FLAG {flag}")
        print()