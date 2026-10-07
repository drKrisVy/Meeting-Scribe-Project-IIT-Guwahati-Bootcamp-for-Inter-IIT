import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from document import MODEL as DOCUMENTER_MODEL
from document import draft_record
from refine import MODEL as REFINER_MODEL
from refine import refine
from shape import build_transcript
from transcribe import STT_MODEL, transcribe_long
from verify import verify_record
from render import render_minutes
from validate import validate
from hallucination import filter_transcript

RUNS_DIR = Path("runs")


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


def run_pipeline(audio_path):
    audio_path = Path(audio_path)
    run_id = make_run_id(audio_path)
    run_dir = RUNS_DIR / run_id
    (run_dir / "input").mkdir(parents=True)
    shutil.copy(audio_path, run_dir / "input" / audio_path.name)
    yield "start", f"run {run_id}"

    t0 = time.perf_counter()
    audio = validate(run_dir / "input" / audio_path.name, run_dir / "input")
    yield "validate", (f"{audio['duration'] / 60:.1f} min, {audio['speech_ratio']:.0%} not silent "
                       f"in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    groq_data = transcribe_long(audio, run_dir / "input")
    save_json(run_dir / "groq_response.json", groq_data)
    raw = build_transcript(groq_data)
    stt_log = filter_transcript(raw)
    stt_log["chunks"] = groq_data["chunks"]
    save_json(run_dir / "stt_log.json", stt_log)
    if stt_log["removed"]:
        audio["warnings"].append(f"Removed {stt_log['removed']} bits that looked like Whisper "
                                 "hallucinations (see stt_log.json).")
    raw["run_id"] = run_id
    raw["audio"] = {"file": audio_path.name, "duration_s": audio["duration"]}
    save_json(run_dir / "raw_transcript.json", raw)
    pieces = len(groq_data["chunks"])
    yield "transcribe", (f"{len(raw['segments'])} segments"
                         f"{f' from {pieces} pieces' if pieces > 1 else ''} "
                         f"in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    edits, refined, inventory = refine(raw)
    save_json(run_dir / "edits.json", {"inventory": inventory, "edits": edits})
    save_json(run_dir / "refined_transcript.json", refined)
    accepted = sum(1 for e in edits if e["status"] == "accepted")
    yield "refine", (f"{len(inventory['terms'])} terms, {accepted} of {len(edits)} edits accepted "
                     f"in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    draft = draft_record(refined)
    save_json(run_dir / "record_draft.json", draft)
    checked = verify_record(draft, refined)
    record = {
        "schema_version": "1.0",
        "run_id": run_id,
        "models": {"stt": STT_MODEL, "refiner": REFINER_MODEL, "documenter": DOCUMENTER_MODEL},
        **checked,
        "warnings": audio["warnings"],
    }
    save_json(run_dir / "record.json", record)
    yield "document", (f"{len(record['decisions'])} decisions, "
                       f"{len(record['action_items'])} action items, "
                       f"{len(record['unverified'])} unverified "
                       f"in {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    minutes = render_minutes(record, refined, edits)
    (run_dir / "minutes.md").write_text(minutes)
    yield "export", f"minutes.md in {time.perf_counter() - t0:.2f}s"
    yield "done", str(run_dir)


if __name__ == "__main__":
    for stage, message in run_pipeline(sys.argv[1]):
        print(f"[{stage}] {message}")