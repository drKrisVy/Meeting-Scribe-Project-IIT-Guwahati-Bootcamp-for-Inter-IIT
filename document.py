import json

from llm_client import chat_json

MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """You write the record of a meeting from its transcript.
Each line is [seg_id | time] text.

Extract decisions and action items. Every item must quote the transcript.

DECISIONS have a status:
- "agreed": someone raised it AND acceptance was heard ("okay", "yes let's do that",
  "we agreed to"). Quote the acceptance with role "acceptance".
- "proposed": raised, but no acceptance was heard.
- "open_question": explicitly left unresolved ("let's decide next week").
"Let's not do X" is a decision too: the decision is NOT doing X.
If a speaker states that the group already agreed or decided ("we agreed to",
"we decided to"), quote that sentence with role "acceptance".

ACTION ITEMS have a commitment level:
- "confirmed": someone volunteered ("I'll take it"), or was asked and said yes.
- "assigned": directed at a named person, but no reply was heard.
- "suggested": nobody was asked ("someone should check the logs").

OWNER: the person's name only if it was said in the quotes. Otherwise null.
Never guess an owner.
DEADLINE: copy the exact words spoken ("by Friday", "the fifteenth").
Never convert to a date. If no deadline was said, null.

EVIDENCE: each item lists quotes copied word for word from the transcript,
with the seg_id they come from and a role:
- "statement": where the item was raised
- "acceptance": where someone agreed or accepted
- "assignment": where someone was asked to do it

Examples of correct output:

Transcript:
[10 | 01:02] what if we switch to postgres
[11 | 01:05] hmm maybe, let me think about it
Decision: {"text": "Switch to Postgres", "status": "proposed",
  "evidence": [{"seg_id": 10, "role": "statement", "quote": "what if we switch to postgres"}]}
(Nobody accepted, so it is proposed, not agreed.)

Transcript:
[20 | 03:40] someone should look into the login bug
Action item: {"task": "Look into the login bug", "owner": null, "deadline": null,
  "commitment": "suggested",
  "evidence": [{"seg_id": 20, "role": "statement", "quote": "someone should look into the login bug"}]}
(No one was named, so owner is null.)

Transcript:
[30 | 05:12] ravi can you update the docs by end of next week
Action item: {"task": "Update the docs", "owner": "Ravi", "deadline": "by end of next week",
  "commitment": "assigned",
  "evidence": [{"seg_id": 30, "role": "assignment", "quote": "ravi can you update the docs by end of next week"}]}
(Ravi was asked but no reply was heard, so it is assigned, not confirmed.)

Return JSON only, in this shape:
{"decisions": [{"id": "D1", "text": "...", "status": "...", "evidence": [...]}],
 "action_items": [{"id": "A1", "task": "...", "owner": null, "deadline": null,
                   "commitment": "...", "evidence": [...]}],
 "open_questions": [{"id": "Q1", "text": "...", "evidence": [...]}]}"""


STRUCTURE_PROMPT = """You split a meeting transcript into the topics it covered and write short minutes.
Each line is [seg_id | time] text.

For each topic, in order:
- "topic": a short title (2-6 words)
- "start_seg" and "end_seg": the first and last seg_id of the topic
- "points": the key points, one plain sentence each. Every point needs evidence:
  quotes copied word for word from the transcript, with their seg_id.

Rules:
- Only write what was said. No advice, no conclusions nobody stated.
- A proposal is not a decision. Write "X was proposed" unless someone accepted it.
- Keep numbers, names and negations exactly as spoken.
- Greetings and small talk need no points. A short meeting can have one topic.

Return JSON only:
{"topics": [{"topic": "...", "start_seg": 0, "end_seg": 5,
             "points": [{"text": "...", "evidence": [{"seg_id": 2, "quote": "..."}]}]}]}"""

SUMMARY_PROMPT = """You write the summary at the top of a meeting record.

You only get facts that were already checked against the transcript: topics with
their minutes, decisions with their status, and action items.

Write 3 to 5 plain sentences telling someone who missed the meeting what it was
about, what was decided and what happens next.

Rules:
- Use only the facts given. Add nothing.
- Say "agreed" only for agreed decisions; say "proposed" or "still open" for the rest.
- Mention an owner or deadline only if the facts give one.
- Copy names and numbers exactly.

Return JSON only: {"summary": "..."}"""

REPAIR_PROMPT = """Some items in a meeting record quote things that could not be found in the
transcript. Each transcript line is [seg_id | time] text.

For each item, either fix its evidence so every quote is copied word for word from
the transcript with the right seg_id, keeping its other fields, or leave the item
out if the transcript doesn't support it. Don't add items. Don't change ids.

Return JSON only: {"items": [ ...the fixed items, same fields as given... ]}"""


def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def format_transcript(transcript):
    lines = []
    for seg in transcript["segments"]:
        lines.append(f"[{seg['seg_id']} | {format_time(seg['start'])}] {seg['text']}")
    return "\n".join(lines)


def number_items(draft):
    for prefix, key in [("D", "decisions"), ("A", "action_items"), ("Q", "open_questions")]:
        for i, item in enumerate(draft.get(key, []), start=1):
            item["id"] = f"{prefix}{i}"
    return draft


def draft_record(transcript):
    text = format_transcript(transcript)
    topics = chat_json(MODEL, STRUCTURE_PROMPT, text).get("topics", [])
    draft = chat_json(MODEL, SYSTEM_PROMPT, text)
    draft = {key: draft.get(key) or [] for key in ["decisions", "action_items", "open_questions"]}
    draft["topics"] = topics
    return number_items(draft)


def repair(items, transcript):
    user = ("ITEMS:\n" + json.dumps(items, indent=1)
            + "\n\nTRANSCRIPT:\n" + format_transcript(transcript))
    data = chat_json(MODEL, REPAIR_PROMPT, user)
    ids = {item["id"] for item in items}
    return [item for item in data.get("items", []) if item.get("id") in ids]


def summary_facts(record):
    lines = []
    for topic in record["minutes"]:
        lines.append(f"Topic: {topic['topic']}")
        for point in topic["points"]:
            lines.append(f"  - {point['text']}")
    for d in record["decisions"]:
        lines.append(f"Decision ({d['status']}): {d['text']}")
    for a in record["action_items"]:
        lines.append(f"Action ({a['commitment']}): {a['task']}; "
                     f"owner: {a.get('owner') or 'not stated'}; "
                     f"deadline: {a.get('deadline') or 'not stated'}")
    for q in record["open_questions"]:
        lines.append(f"Open question: {q['text']}")
    return "\n".join(lines) or "Nothing was recorded."


def write_summary(record, problems=None):
    user = summary_facts(record)
    if problems:
        user += ("\n\nYour last summary had these problems: " + "; ".join(problems)
                 + ". Only use names and numbers from the facts.")
    return chat_json(MODEL, SUMMARY_PROMPT, user).get("summary", "").strip()


if __name__ == "__main__":
    with open("refined_transcript.json") as f:
        transcript = json.load(f)

    print(format_transcript(transcript))
    print()

    record = draft_record(transcript)

    with open("record_draft.json", "w") as f:
        json.dump(record, f, indent=2)

    print(json.dumps(record, indent=2))