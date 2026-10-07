import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from document import MODEL as DOCUMENTER_MODEL
from document import draft_record, repair, write_summary
from refine import MODEL as REFINER_MODEL
from refine import refine
from shape import build_transcript
from transcribe import STT_MODEL, transcribe_long
from verify import check_summary, verify_record
from render import export_minutes
from validate import validate
from hallucination import filter_transcript

RUNS_DIR = Path("runs")
STAGES = ["validate", "transcribe", "refine", "document", "export"]


def make_run_id(audio_path):
    digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:6]
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_id = f"{stamp}_{digest}"
    n = 2
    while (RUNS_DIR / run_id).exists():
        run_id = f"{stamp}_{digest}_{n}"
        n += 1
    return run_id


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def load_json(path):
    return json.loads(path.read_text())


# each stage reads the files the stage before it saved, so a run that
# failed halfway can carry on from there without transcribing again

def stage_validate(run_dir, state):
    audio = validate(run_dir / "input" / state["audio_file"], run_dir / "input")
    state["audio"] = audio
    state["warnings"] = audio["warnings"]
    return f"{audio['duration'] / 60:.1f} min, {audio['speech_ratio']:.0%} not silent"


def stage_transcribe(run_dir, state):
    groq_data = transcribe_long(state["audio"], run_dir / "input")
    save_json(run_dir / "groq_response.json", groq_data)
    raw = build_transcript(groq_data)

    stt_log = filter_transcript(raw)
    stt_log["chunks"] = groq_data["chunks"]
    save_json(run_dir / "stt_log.json", stt_log)
    if stt_log["removed"]:
        state["warnings"].append(f"Removed {stt_log['removed']} bits that looked like Whisper "
                                 "hallucinations (see stt_log.json).")

    raw["run_id"] = run_dir.name
    raw["audio"] = {"file": state["audio_file"], "duration_s": state["audio"]["duration"]}
    save_json(run_dir / "raw_transcript.json", raw)

    pieces = len(groq_data["chunks"])
    return f"{len(raw['segments'])} segments" + (f" from {pieces} pieces" if pieces > 1 else "")


def stage_refine(run_dir, state):
    raw = load_json(run_dir / "raw_transcript.json")
    edits, refined, inventory = refine(raw)
    save_json(run_dir / "edits.json", {"inventory": inventory, "edits": edits})
    save_json(run_dir / "refined_transcript.json", refined)
    accepted = sum(1 for e in edits if e["status"] == "accepted")
    return f"{len(inventory['terms'])} terms, {accepted} of {len(edits)} edits accepted"


def stage_document(run_dir, state):
    refined = load_json(run_dir / "refined_transcript.json")
    draft = draft_record(refined)
    save_json(run_dir / "record_draft.json", draft)

    checked = verify_record(draft, refined, repair=lambda items: repair(items, refined))
    summary = write_summary(checked)
    problems = check_summary(summary, refined)
    if problems:
        summary = write_summary(checked, problems)
        problems = check_summary(summary, refined)

    record = {
        "schema_version": "1.0",
        "run_id": run_dir.name,
        "models": {"stt": STT_MODEL, "refiner": REFINER_MODEL, "documenter": DOCUMENTER_MODEL},
        "summary": summary,
        "summary_problems": problems,
        **checked,
        "warnings": state["warnings"],
    }
    save_json(run_dir / "record.json", record)
    return (f"{len(record['decisions'])} decisions, {len(record['action_items'])} action items, "
            f"{len(record['unverified'])} not found")


def stage_export(run_dir, state):
    record = load_json(run_dir / "record.json")
    refined = load_json(run_dir / "refined_transcript.json")
    edits = load_json(run_dir / "edits.json")["edits"]
    made = export_minutes(run_dir, record, refined, edits)
    state["zip"] = shutil.make_archive(str(run_dir), "zip", root_dir=run_dir)
    return ", ".join(made) + ", zip"


STAGE_FUNCTIONS = {
    "validate": stage_validate,
    "transcribe": stage_transcribe,
    "refine": stage_refine,
    "document": stage_document,
    "export": stage_export,
}


def run_stages(run_dir, state, first):
    for stage in STAGES[STAGES.index(first):]:
        t0 = time.perf_counter()
        try:
            message = STAGE_FUNCTIONS[stage](run_dir, state)
        except Exception as error:
            state["failed"] = {"stage": stage, "error": str(error)}
            save_json(run_dir / "state.json", state)
            raise
        state.pop("failed", None)
        state["done"] = state.get("done", []) + [stage]
        save_json(run_dir / "state.json", state)
        yield stage, f"{message} in {time.perf_counter() - t0:.1f}s"
    yield "done", str(run_dir)


def run_pipeline(audio_path):
    audio_path = Path(audio_path)
    run_dir = RUNS_DIR / make_run_id(audio_path)
    (run_dir / "input").mkdir(parents=True)
    shutil.copy(audio_path, run_dir / "input" / audio_path.name)
    state = {"audio_file": audio_path.name, "warnings": []}
    save_json(run_dir / "state.json", state)
    yield "start", str(run_dir)
    yield from run_stages(run_dir, state, "validate")


def resume_pipeline(run_dir):
    run_dir = Path(run_dir)
    state = load_json(run_dir / "state.json")
    first = state.get("failed", {}).get("stage", "refine")
    yield "start", str(run_dir)
    yield from run_stages(run_dir, state, first)


if __name__ == "__main__":
    if sys.argv[1] == "--resume":
        steps = resume_pipeline(sys.argv[2])
    else:
        steps = run_pipeline(sys.argv[1])
    for stage, message in steps:
        print(f"[{stage}] {message}")
