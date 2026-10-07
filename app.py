import difflib
import json
import shutil
from pathlib import Path

import gradio as gr

from pipeline import run_pipeline
from render import format_time
from validate import AudioError

STAGES = ["validate", "transcribe", "refine", "document", "export"]
STAGE_NAMES = {"validate": "Validate", "transcribe": "Transcribe", "refine": "Refine",
               "document": "Document", "export": "Export"}


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


def transcript_markdown(transcript):
    lines = []
    for seg in transcript["segments"]:
        lines.append(f"`{format_time(seg['start'])}` {seg['text']}")
    return "\n\n".join(lines) or "_No speech found._"


def word_diff(raw_text, refined_text):
    raw_words = raw_text.split()
    new_words = refined_text.split()
    matcher = difflib.SequenceMatcher(a=raw_words, b=new_words)
    parts = []
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(" ".join(raw_words[a1:a2]))
        else:
            if a2 > a1:
                parts.append("~~" + " ".join(raw_words[a1:a2]) + "~~")
            if b2 > b1:
                parts.append("**" + " ".join(new_words[b1:b2]) + "**")
    return " ".join(parts)


def refined_markdown(raw, refined):
    lines = []
    for raw_seg, new_seg in zip(raw["segments"], refined["segments"]):
        t = format_time(raw_seg["start"])
        if raw_seg["text"] == new_seg["text"]:
            lines.append(f"`{t}` {new_seg['text']}")
        else:
            lines.append(f"`{t}` {word_diff(raw_seg['text'], new_seg['text'])}")
    return "\n\n".join(lines) or "_No speech found._"


def edits_rows(edits):
    rows = []
    for e in edits:
        rows.append([e.get("edit_id"), e.get("seg_id"), e.get("original"),
                     e.get("replacement"), e.get("status"), e.get("rule") or "",
                     e.get("reason", "")])
    return rows


def zip_run(run_dir):
    return shutil.make_archive(str(run_dir), "zip", root_dir=run_dir)


def process(audio_path):
    empty = ("", "", "", [], None)
    done = {}

    if not audio_path:
        yield ("Upload an audio file first.", *empty)
        return

    running = "validate"
    yield (status_markdown(done, running), *empty)

    try:
        run_dir = None
        for stage, message in run_pipeline(audio_path):
            if stage == "start":
                continue
            if stage == "done":
                run_dir = Path(message)
                break
            done[stage] = message
            next_index = STAGES.index(stage) + 1
            running = STAGES[next_index] if next_index < len(STAGES) else None
            yield (status_markdown(done, running), *empty)
    except AudioError as error:
        yield (status_markdown(done, failed=running) + f"\n\n**{error.message}**", *empty)
        return
    except Exception as error:
        yield (status_markdown(done, failed=running) + f"\n\n**Error:** {error}", *empty)
        return

    raw = json.loads((run_dir / "raw_transcript.json").read_text())
    refined = json.loads((run_dir / "refined_transcript.json").read_text())
    edits = json.loads((run_dir / "edits.json").read_text())["edits"]
    minutes = (run_dir / "minutes.md").read_text()

    files = sorted(str(p) for p in run_dir.iterdir() if p.is_file())
    files.append(zip_run(run_dir))

    yield (
        status_markdown(done) + f"\n\nRun folder: `{run_dir}`",
        transcript_markdown(raw),
        refined_markdown(raw, refined),
        minutes,
        edits_rows(edits),
        files,
    )


with gr.Blocks(title="Meeting Scribe") as demo:
    gr.Markdown("# Meeting Scribe\nUpload a meeting recording to get a transcript, "
                "a refined transcript and checked meeting minutes.")

    with gr.Row():
        with gr.Column(scale=1):
            audio = gr.File(type="filepath", label="Meeting recording (audio or video)")
            run_button = gr.Button("Process", variant="primary")
            status = gr.Markdown(status_markdown({}))

        with gr.Column(scale=2):
            with gr.Tab("Raw transcript"):
                raw_box = gr.Markdown()
            with gr.Tab("Refined transcript"):
                refined_box = gr.Markdown()
            with gr.Tab("Meeting record"):
                minutes_box = gr.Markdown()
            with gr.Tab("Edits log"):
                edits_table = gr.Dataframe(
                    headers=["id", "segment", "original", "replacement",
                             "status", "rule", "reason"],
                    wrap=True,
                )
            with gr.Tab("Downloads"):
                files_box = gr.File(file_count="multiple", label="Run files")

    run_button.click(
        process,
        inputs=audio,
        outputs=[status, raw_box, refined_box, minutes_box, edits_table, files_box],
    )

demo.queue(default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch()