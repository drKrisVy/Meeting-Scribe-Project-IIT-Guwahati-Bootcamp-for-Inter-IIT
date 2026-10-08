import difflib
import html
import json
from pathlib import Path

import gradio as gr

from pipeline import RUNS_DIR, STAGES, resume_pipeline, run_pipeline
from render import format_time
from validate import AudioError

STAGE_NAMES = {"validate": "Validate", "transcribe": "Transcribe", "refine": "Refine",
               "document": "Document", "export": "Export"}
PLAYABLE = {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".aac", ".flac"}

# clicking anything with data-t="12.5" jumps the player to 12.5 s
HEAD = """
<script>
document.addEventListener("click", function (event) {
  const link = event.target.closest("[data-t]");
  const player = document.getElementById("player");
  if (!link || !player) return;
  event.preventDefault();
  player.currentTime = parseFloat(link.dataset.t);
  player.play();
});
</script>
<style>
.ts { font-family: Menlo, monospace; font-size: 12px; color: #2563eb; cursor: pointer;
      margin-right: 6px; text-decoration: none; }
.ts:hover { text-decoration: underline; }
ins { background: rgba(34,197,94,.2); text-decoration: none; }
del { color: #b91c1c; }
.refused { color: #6b7280; font-size: 12px; margin: -6px 0 10px 48px; }
</style>
"""


def ts(seconds):
    return f'<a class="ts" data-t="{seconds:.2f}" href="#">{format_time(seconds)}</a>'


def status_markdown(done, running=None, failed=None):
    lines = []
    for stage in STAGES:
        name = STAGE_NAMES[stage]
        if stage in done:
            lines.append(f"✅ **{name}**: {done[stage]}")
        elif stage == failed:
            lines.append(f"❌ **{name}**: failed")
        elif stage == running:
            lines.append(f"⏳ **{name}**: running…")
        else:
            lines.append(f"▫️ {name}: waiting")
    return "\n\n".join(lines)


def player_html(run_dir):
    state = json.loads((run_dir / "state.json").read_text())
    path = run_dir / "input" / state["audio_file"]
    if path.suffix.lower() not in PLAYABLE:
        path = run_dir / "input" / "audio_16k.flac"
    return (f'<audio id="player" controls style="width:100%" '
            f'src="/gradio_api/file={html.escape(str(path.resolve()))}"></audio>'
            '<small>Click any timestamp to jump there.</small>')


def transcript_html(transcript):
    lines = [f"<p>{ts(seg['start'])}{html.escape(seg['text'])}</p>"
             for seg in transcript["segments"]]
    return "".join(lines) or "<p>No speech found.</p>"


def word_diff(raw_text, refined_text):
    raw_words = raw_text.split()
    new_words = refined_text.split()
    matcher = difflib.SequenceMatcher(a=raw_words, b=new_words)
    parts = []
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(html.escape(" ".join(raw_words[a1:a2])))
        else:
            if a2 > a1:
                parts.append("<del>" + html.escape(" ".join(raw_words[a1:a2])) + "</del>")
            if b2 > b1:
                parts.append("<ins>" + html.escape(" ".join(new_words[b1:b2])) + "</ins>")
    return " ".join(parts)


def refined_html(raw, refined, edits):
    lines = []
    for raw_seg, new_seg in zip(raw["segments"], refined["segments"]):
        text = word_diff(raw_seg["text"], new_seg["text"])
        lines.append(f"<p>{ts(raw_seg['start'])}{text}</p>")
        for e in edits:
            if e.get("seg_id") == raw_seg["seg_id"] and e["status"] != "accepted":
                lines.append(f'<div class="refused"><s>{html.escape(str(e.get("original")))} → '
                             f'{html.escape(str(e.get("replacement")))}</s> '
                             f'{e["status"]}: {e["rule"]}</div>')
    return "".join(lines)


def record_html(record):
    parts = [f"<h3>Summary</h3><p>{html.escape(record.get('summary') or '')}</p>", "<h3>Minutes</h3>"]
    for topic in record.get("minutes", []):
        parts.append(f"<h4>{ts(topic['start'])}{html.escape(topic['topic'])}</h4><ul>")
        for point in topic["points"]:
            parts.append(f"<li>{html.escape(point['text'])} {ts(point['evidence'][0]['t'])}</li>")
        parts.append("</ul>")

    parts.append("<h3>Decisions</h3>")
    for d in record["decisions"]:
        quotes = " ".join(ts(ev["t"]) for ev in d["evidence"])
        parts.append(f"<p><b>{d['id']}</b> [{d['status'].replace('_', ' ')}] "
                     f"{html.escape(d['text'])} {quotes}</p>")

    parts.append("<h3>Action items</h3><table><tr><th>ID</th><th>Task</th><th>Owner</th>"
                 "<th>Deadline</th><th>Status</th><th>When</th></tr>")
    for a in record["action_items"]:
        owner = a.get("owner") or ("Unspecified (" + a["owner_note"] + ")" if a.get("owner_note")
                                   else "Unspecified")
        when = " ".join(ts(ev["t"]) for ev in a["evidence"])
        parts.append(f"<tr><td>{a['id']}</td><td>{html.escape(a['task'])}</td>"
                     f"<td>{html.escape(owner)}</td><td>{html.escape(a.get('deadline') or 'Unspecified')}</td>"
                     f"<td>{a['commitment']}</td><td>{when}</td></tr>")
    parts.append("</table>")

    for q in record.get("open_questions", []):
        parts.append(f"<p><b>{q['id']}</b> [open] {html.escape(q['text'])}</p>")
    return "".join(parts)


def review_html(record, edits, segments_by_id):
    rows = [f"<p>⚠️ {html.escape(w)}</p>" for w in record.get("warnings", [])]
    rows += [f"<p>Summary: {html.escape(p)}</p>" for p in record.get("summary_problems", [])]
    for key in ["decisions", "action_items", "open_questions"]:
        for item in record[key]:
            flags = [f for f in item.get("flags", []) if f not in ("repaired", "acceptance_found_after")]
            if flags:
                rows.append(f"<p>{ts(item['evidence'][0]['t'])}<b>{item['id']}</b> "
                            f"{html.escape(item.get('text') or item.get('task'))}: "
                            f"{html.escape('; '.join(flags))}</p>")
    for item in record["unverified"]:
        rows.append(f"<p><b>Not found in transcript</b> {html.escape(item.get('text') or item.get('task') or '')}"
                    f": {html.escape('; '.join(item['flags']))}</p>")
    for e in edits:
        if e["status"] == "flagged":
            seg = segments_by_id.get(e["seg_id"], {"start": 0})
            rows.append(f"<p>{ts(seg['start'])}Edit {e['edit_id']} not applied ({e['rule']}): "
                        f"\"{html.escape(e['original'])}\" → \"{html.escape(e['replacement'])}\". "
                        "Listen and check.</p>")
    return "".join(rows) or "<p>Nothing needs review.</p>"


def edits_rows(edits):
    return [[e.get("edit_id"), e.get("seg_id"), e.get("original"), e.get("replacement"),
             e.get("status"), e.get("rule") or "", e.get("source", ""), e.get("reason", "")]
            for e in edits]


def results(run_dir):
    raw = json.loads((run_dir / "raw_transcript.json").read_text())
    refined = json.loads((run_dir / "refined_transcript.json").read_text())
    edits = json.loads((run_dir / "edits.json").read_text())["edits"]
    record = json.loads((run_dir / "record.json").read_text())
    state = json.loads((run_dir / "state.json").read_text())
    segments_by_id = {s["seg_id"]: s for s in refined["segments"]}

    files = sorted(str(p) for p in run_dir.iterdir() if p.is_file() and p.name != "state.json")
    files.insert(0, state["zip"])
    return (player_html(run_dir), transcript_html(raw), refined_html(raw, refined, edits),
            record_html(record), edits_rows(edits), review_html(record, edits, segments_by_id),
            files)


EMPTY = ("", "", "", "", [], "", None)


def follow(steps, done):
    run_dir = None
    running = next((s for s in STAGES if s not in done), None)
    try:
        for stage, message in steps:
            if stage == "start":
                run_dir = Path(message)
                yield (status_markdown(done, running), str(run_dir), gr.update(visible=False), *EMPTY)
                continue
            if stage == "done":
                break
            done[stage] = message
            running = next((s for s in STAGES if s not in done), None)
            yield (status_markdown(done, running), str(run_dir), gr.update(visible=False), *EMPTY)
    except AudioError as error:
        yield (status_markdown(done, failed=running) + f"\n\n**{error.message}**",
               str(run_dir), gr.update(visible=False), *EMPTY)
        return
    except Exception as error:
        # anything after validate can be retried from the saved files
        yield (status_markdown(done, failed=running) + f"\n\n**Error:** {error}",
               str(run_dir), gr.update(visible=True), *EMPTY)
        return

    yield (status_markdown(done) + f"\n\nRun folder: `{run_dir}`", str(run_dir),
           gr.update(visible=False), *results(run_dir))


def process(file_path):
    if not file_path:
        yield ("Upload a recording first.", None, gr.update(visible=False), *EMPTY)
        return
    yield from follow(run_pipeline(file_path), {})


def retry(run_dir):
    state = json.loads((Path(run_dir) / "state.json").read_text())
    done = {stage: "saved" for stage in state.get("done", [])}
    yield from follow(resume_pipeline(run_dir), done)


with gr.Blocks(title="Meeting Scribe") as demo:
    gr.Markdown("# Meeting Scribe\nUpload a meeting recording to get a transcript, "
                "a refined transcript and checked meeting minutes.")
    run_dir_box = gr.State(None)

    with gr.Row():
        with gr.Column(scale=1):
            upload = gr.File(type="filepath", label="Meeting recording (audio or video)")
            run_button = gr.Button("Process", variant="primary")
            status = gr.Markdown(status_markdown({}))
            retry_button = gr.Button("Retry from where it failed", visible=False)
            player = gr.HTML()

        with gr.Column(scale=2):
            with gr.Tab("Meeting record"):
                record_box = gr.HTML()
            with gr.Tab("Raw transcript"):
                raw_box = gr.HTML()
            with gr.Tab("Refined transcript"):
                refined_box = gr.HTML()
            with gr.Tab("Edits log"):
                edits_table = gr.Dataframe(
                    headers=["id", "segment", "original", "replacement",
                             "status", "rule", "source", "reason"],
                    wrap=True,
                )
            with gr.Tab("Needs review"):
                review_box = gr.HTML()
            with gr.Tab("Downloads"):
                files_box = gr.File(file_count="multiple", label="Run files")

    outputs = [status, run_dir_box, retry_button, player, raw_box, refined_box, record_box,
               edits_table, review_box, files_box]
    run_button.click(process, inputs=upload, outputs=outputs)
    retry_button.click(retry, inputs=run_dir_box, outputs=outputs)

demo.queue(default_concurrency_limit=1)

if __name__ == "__main__":
    RUNS_DIR.mkdir(exist_ok=True)
    demo.launch(allowed_paths=[str(RUNS_DIR.resolve())], head=HEAD)
