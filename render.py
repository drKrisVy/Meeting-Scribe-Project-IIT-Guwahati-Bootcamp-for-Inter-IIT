import json
import re
import sys
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader

HTML_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Meeting minutes</title>
<style>
body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 780px;
       margin: 32px auto; padding: 0 16px; line-height: 1.5; color: #1d1d1f; }}
h2 {{ border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 28px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f6; }}
</style></head><body>
{body}
</body></html>"""


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
    flagged_items = []
    for item in all_items:
        flags = [f for f in item.get("flags", []) if f not in ("repaired", "acceptance_found_after")]
        if flags:
            flagged_items.append({**item, "flags": flags})
    flagged_edits = [e for e in edits if e["status"] == "flagged"]

    segments = transcript["segments"]
    duration = transcript.get("audio", {}).get("duration_s") or (segments[-1]["end"] if segments else 0)

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


def export_minutes(run_dir, record, transcript, edits):
    text = render_minutes(record, transcript, edits)
    (run_dir / "minutes.md").write_text(text)

    html = HTML_PAGE.format(body=markdown.markdown(text, extensions=["tables"]))
    (run_dir / "minutes.html").write_text(html)
    made = ["minutes.md", "minutes.html"]

    # pdf needs weasyprint, which isn't always installed (see README)
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(run_dir / "minutes.pdf"))
        made.append("minutes.pdf")
    except Exception:
        pass
    return made


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