import json
import re
import sys
from pathlib import Path

from rapidfuzz.fuzz import token_set_ratio
from rapidfuzz.utils import default_process

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from meetings import MEETINGS  # noqa: E402
from pipeline import run_pipeline  # noqa: E402

MATCH_MIN = 60


def words(text):
    return re.sub(r"[^\w\s']", " ", text.lower()).split()


def wer(reference, hypothesis):
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        new = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            new[j] = min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (r != h))
        row = new
    return row[-1] / max(len(ref), 1)


def terms_found(terms, text):
    joined = " " + " ".join(words(text)) + " "
    return sum(1 for t in terms if " " + " ".join(words(t)) + " " in joined)


def best_match(answer, items, key):
    best, best_score = None, 0
    for item in items:
        score = token_set_ratio(answer, item.get(key) or "", processor=default_process)
        if score > best_score:
            best, best_score = item, score
    return best if best_score >= MATCH_MIN else None


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return words(a) == words(b)


def score(meeting, run_dir):
    answers = meeting["answers"]
    raw = json.loads((run_dir / "raw_transcript.json").read_text())
    refined = json.loads((run_dir / "refined_transcript.json").read_text())
    record = json.loads((run_dir / "record.json").read_text())
    raw_text = " ".join(s["text"] for s in raw["segments"])
    refined_text = " ".join(s["text"] for s in refined["segments"])
    spoken = " ".join(text for _, text in meeting["lines"])

    s = {
        "terms raw": f"{terms_found(answers['terms'], raw_text)}/{len(answers['terms'])}",
        "terms refined": f"{terms_found(answers['terms'], refined_text)}/{len(answers['terms'])}",
        "WER raw": f"{wer(spoken, raw_text):.2f}",
        "WER refined": f"{wer(spoken, refined_text):.2f}",
    }

    decisions = record["decisions"] + [{**q, "status": "open_question"}
                                       for q in record["open_questions"]]
    found = right = proposal_as_agreed = 0
    notes = []
    for text, status in answers["decisions"]:
        match = best_match(text, decisions, "text")
        if not match:
            notes.append(f"missed decision: {text}")
            continue
        decisions.remove(match)
        found += 1
        right += match["status"] == status
        if status != "agreed" and match["status"] == "agreed":
            proposal_as_agreed += 1
            notes.append(f"shown as agreed but wasn't: {text}")
    s["decisions found"] = f"{found}/{len(answers['decisions'])}"
    s["status right"] = f"{right}/{found}"
    s["proposal shown as agreed"] = proposal_as_agreed

    tasks = list(record["action_items"])
    found = owner_right = deadline_right = invented = 0
    for task, owner, deadline, commitment in answers["tasks"]:
        match = best_match(task, tasks, "task")
        if not match:
            notes.append(f"missed task: {task}")
            continue
        tasks.remove(match)
        found += 1
        owner_right += same(owner, match.get("owner"))
        deadline_right += same(deadline, match.get("deadline"))
        # the worst mistake: filling in an owner or deadline nobody said
        invented += (owner is None and match.get("owner") is not None)
        invented += (deadline is None and match.get("deadline") is not None)
    s["tasks found"] = f"{found}/{len(answers['tasks'])}"
    s["owner right"] = f"{owner_right}/{found}"
    s["deadline right"] = f"{deadline_right}/{found}"
    s["invented owner/deadline"] = invented

    notes += [f"extra item: {i.get('text') or i.get('task')}" for i in decisions + tasks]
    return s, notes


if __name__ == "__main__":
    rows = []
    for meeting in MEETINGS:
        audio = HERE / "audio" / f"{meeting['name']}.m4a"
        if not audio.exists():
            print(f"skip {meeting['name']}: no audio, run make_audio.py first")
            continue
        print(f"running {meeting['name']} ...")
        steps = list(run_pipeline(audio))
        run_dir = Path(steps[-1][1])
        s, notes = score(meeting, run_dir)
        rows.append((meeting["name"], run_dir, s, notes))
        for key, value in s.items():
            print(f"  {key}: {value}")
        for note in notes:
            print(f"  - {note}")

    if rows:
        keys = list(rows[0][2])
        lines = ["# Eval results", "",
                 "Made by `python eval/score.py`. Matching is fuzzy, so check the notes by hand.", "",
                 "| meeting | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
        for name, _, s, _ in rows:
            lines.append(f"| {name} | " + " | ".join(str(s[k]) for k in keys) + " |")
        lines.append("")
        for name, run_dir, _, notes in rows:
            lines.append(f"**{name}** (`{run_dir}`)")
            lines += [f"- {n}" for n in notes] or ["- nothing missed"]
            lines.append("")
        (HERE / "results.md").write_text("\n".join(lines))
        print("\nwrote eval/results.md")
