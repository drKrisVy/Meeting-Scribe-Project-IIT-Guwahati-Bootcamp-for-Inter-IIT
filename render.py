import json
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def format_time(seconds):
    if seconds is None:
        return "--:--"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["mmss"] = format_time
env.filters["cell"] = lambda text: str(text).replace("|", "\\|").replace("\n", " ")


def render_minutes(record, transcript, edits):
    decisions = record["decisions"]
    agreed = [d for d in decisions if d.get("status") == "agreed"]
    proposed = [d for d in decisions if d.get("status") == "proposed"]
    open_questions = [d for d in decisions if d.get("status") == "open_question"]
    open_questions += record["open_questions"]

    all_items = decisions + record["action_items"] + record["open_questions"]
    flagged_items = [item for item in all_items if item.get("flags")]
    flagged_edits = [e for e in edits if e["status"] == "flagged"]

    segments = transcript["segments"]
    duration = segments[-1]["end"] if segments else 0

    template = env.get_template("minutes.md.j2")
    return template.render(
        record=record,
        audio_file=transcript.get("audio", {}).get("file", "unknown"),
        duration=duration,
        agreed=agreed,
        proposed=proposed,
        open_questions=open_questions,
        flagged_items=flagged_items,
        flagged_edits=flagged_edits,
    )


def check_ids(markdown, record):
    in_md = set()
    for bold, cell in re.findall(r"\*\*([DAQ]\d+)\*\*|^\| ([DAQ]\d+) \|", markdown, re.MULTILINE):
        in_md.add(bold or cell)
    in_json = {item["id"] for key in ["decisions", "action_items", "open_questions"]
               for item in record[key]}
    return in_md == in_json, in_md, in_json


if __name__ == "__main__":
    run_dir = Path(sys.argv[1])
    record = json.loads((run_dir / "record.json").read_text())
    transcript = json.loads((run_dir / "refined_transcript.json").read_text())
    edits = json.loads((run_dir / "edits.json").read_text())["edits"]

    markdown = render_minutes(record, transcript, edits)
    (run_dir / "minutes.md").write_text(markdown)
    print(markdown)

    same, in_md, in_json = check_ids(markdown, record)
    print("IDs match:", same, sorted(in_md), sorted(in_json))