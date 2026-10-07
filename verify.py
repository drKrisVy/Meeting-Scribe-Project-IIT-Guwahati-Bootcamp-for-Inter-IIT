import copy
import json
import re
import sys

from rapidfuzz.fuzz import partial_ratio_alignment, token_set_ratio
from rapidfuzz.utils import default_process

from guardrails import COMMON_WORDS, normalize, split_numbers

QUOTE_MATCH_MIN = 90
QUOTE_ELSEWHERE_MIN = 95
SAME_ITEM_MIN = 85

FIRST_PERSON = ["i'll", "i will", "let me", "i can take", "i can do", "i'm on it", "i am on it"]
SENTENCE_STARTERS = {"someone", "everyone", "nobody", "the", "team", "next", "finally",
                     "overall", "both", "after", "before", "later", "also"}
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
        elif volunteered and not item.get("owner"):
            # "I'll take it", but without speaker labels we don't know who "I" is
            item["owner_note"] = "someone volunteered"

    if item.get("commitment") == "assigned" and not item.get("owner"):
        item["commitment"] = "suggested"
        item["flags"].append("assigned_without_owner")

    return item


def title(item):
    return item.get("text") or item.get("task") or ""


def is_duplicate(a, b):
    # never merge "launch on the 15th" with "launch on the 16th"
    if split_numbers(title(a))[0] != split_numbers(title(b))[0]:
        return False
    a_segs = {ev["seg_id"] for ev in a["evidence"]}
    b_segs = {ev["seg_id"] for ev in b["evidence"]}
    score = token_set_ratio(title(a), title(b), processor=default_process)
    return bool(a_segs & b_segs) and score >= SAME_ITEM_MIN


def merge_duplicates(items):
    kept = []
    for item in items:
        twin = next((k for k in kept if is_duplicate(item, k)), None)
        if twin is None:
            kept.append(item)
            continue
        seen = {(ev["seg_id"], ev["quote"]) for ev in twin["evidence"]}
        twin["evidence"] += [ev for ev in item["evidence"] if (ev["seg_id"], ev["quote"]) not in seen]
    return kept


def renumber(items, prefix):
    for i, item in enumerate(items, start=1):
        item["id"] = f"{prefix}{i}"
    return items


def verify_minutes(topics, segments_by_id, unverified):
    minutes = []
    for topic in topics:
        points = []
        for point in topic.get("points", []):
            verify_item(point, segments_by_id)
            if point["verified"]:
                points.append(point)
            else:
                point["kind"] = "minutes"
                unverified.append(point)
        if not points:
            continue
        first = min(ev["seg_id"] for p in points for ev in p["evidence"])
        last = max(ev["seg_id"] for p in points for ev in p["evidence"])
        start_seg = topic.get("start_seg") if topic.get("start_seg") in segments_by_id else first
        end_seg = topic.get("end_seg") if topic.get("end_seg") in segments_by_id else last
        minutes.append({
            "topic": topic.get("topic") or "Discussion",
            "start": segments_by_id[min(start_seg, first)]["start"],
            "end": segments_by_id[max(end_seg, last)]["end"],
            "points": merge_duplicates(points),
        })
    return minutes


def verify_record(draft, transcript, repair=None):
    segments_by_id = {seg["seg_id"]: seg for seg in transcript["segments"]}
    record = {"decisions": [], "action_items": [], "open_questions": [], "unverified": []}
    originals = copy.deepcopy(draft)
    failed = []

    for key in ["decisions", "action_items", "open_questions"]:
        for item in draft.get(key, []):
            item = verify_item(item, segments_by_id)
            if item["verified"]:
                record[key].append(item)
            else:
                failed.append((key, item))

    # one more chance: send the failed items back once and check them again
    if failed and repair:
        by_id = {i["id"]: i for k in ["decisions", "action_items", "open_questions"]
                 for i in originals.get(k, [])}
        fixed = {i["id"]: i for i in repair([by_id[item["id"]] for _, item in failed])}
        still_failed = []
        for key, item in failed:
            new = fixed.get(item["id"])
            if new and verify_item(new, segments_by_id)["verified"]:
                new["flags"].append("repaired")
                record[key].append(new)
            else:
                still_failed.append((key, item))
        failed = still_failed

    for key, item in failed:
        item["kind"] = key
        record["unverified"].append(item)

    record["minutes"] = verify_minutes(draft.get("topics", []), segments_by_id, record["unverified"])

    for prefix, key in [("D", "decisions"), ("A", "action_items"), ("Q", "open_questions")]:
        record[key] = renumber(merge_duplicates(record[key]), prefix)
    return record


def check_summary(summary, transcript):
    # every number and every name in the summary has to be in the transcript
    if not summary:
        return ["the summary is empty"]
    said = " ".join(seg["text"] for seg in transcript["segments"])
    said_words = set(normalize(said).split())
    said_numbers = set(split_numbers(said)[0])
    problems = []

    for value in split_numbers(summary)[0]:
        if value not in said_numbers:
            problems.append(f"{value:g} was never said")

    for sentence in re.split(r"(?<=[.!?])\s+", summary):
        for i, word in enumerate(re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence)):
            lower = word.lower()
            first_word = i == 0 and sentence.startswith(word)
            if first_word and (lower in COMMON_WORDS or lower in SENTENCE_STARTERS):
                continue
            if lower not in said_words:
                problems.append(f"{word} was never said")
    return problems


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