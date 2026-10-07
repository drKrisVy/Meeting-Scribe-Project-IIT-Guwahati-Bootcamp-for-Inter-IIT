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


def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def format_transcript(transcript):
    lines = []
    for seg in transcript["segments"]:
        lines.append(f"[{seg['seg_id']} | {format_time(seg['start'])}] {seg['text']}")
    return "\n".join(lines)


def draft_record(transcript):
    return chat_json(MODEL, SYSTEM_PROMPT, format_transcript(transcript))


if __name__ == "__main__":
    with open("refined_transcript.json") as f:
        transcript = json.load(f)

    print(format_transcript(transcript))
    print()

    record = draft_record(transcript)

    with open("record_draft.json", "w") as f:
        json.dump(record, f, indent=2)

    print(json.dumps(record, indent=2))