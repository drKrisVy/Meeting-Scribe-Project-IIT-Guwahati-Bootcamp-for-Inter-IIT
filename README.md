# Meeting Scribe

Upload a meeting recording and get:

1. the **raw transcript** from speech-to-text,
2. a **refined transcript** where misheard terms and names are fixed,
3. the **meeting record**: summary, minutes by topic, decisions and action items.

The idea behind it: **the AI suggests, plain code checks.** The refiner only proposes
small word edits, and eight code checks decide which ones are applied. The documenter
has to quote the transcript for every decision and task, and code checks each quote,
owner and deadline before it goes in the record. Anything that fails a check is shown
under **Needs review** instead of being quietly kept or dropped.

Made for the Inter IIT Tech Meet 15.0 ML problem statement.

## How it works

```
upload → validate → transcribe → refine → document → export
```

| Stage | File | What happens |
|---|---|---|
| Validate | `validate.py` | checks the file with ffprobe, converts it to 16 kHz mono flac, clear error for bad files |
| Transcribe | `transcribe.py`, `chunks.py`, `shape.py`, `hallucination.py` | Whisper on Groq; long audio split at silences; known Whisper hallucinations removed |
| Refine | `inventory.py`, `refine.py`, `guardrails.py`, `apply_edits.py` | LLM #1 lists the meeting's terms, then proposes word edits; guardrails accept, reject or flag each one |
| Document | `document.py`, `verify.py` | LLM #2 writes topics, decisions, tasks, summary; every quote, owner and deadline is checked |
| Export | `render.py`, `templates/` | minutes.md, minutes.html, minutes.pdf and a zip of the run |

`pipeline.py` runs the stages in order and `app.py` is the web UI.
Models and data flow are explained in [TECHNICAL_DESCRIPTION.md](TECHNICAL_DESCRIPTION.md).

## Setup (Mac)

```bash
brew install python@3.12 ffmpeg
cd meeting-scribe
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Make a file called `.env` with your Groq key (free at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=gsk_your_key_here
```

For PDF minutes also run `brew install pango` and `pip install weasyprint`. Without it
you still get minutes.md and minutes.html.

## Run

Web app:

```bash
python app.py
```

Open http://127.0.0.1:7860, upload an audio or video file and press **Process**.
Click any timestamp to hear that moment. If a later stage fails (say the LLM is down),
press **Retry from where it failed**; it carries on from the saved files without
transcribing again.

Command line:

```bash
python pipeline.py meeting.m4a
python pipeline.py --resume runs/<run folder>
```

Each stage also runs on its own, for testing: `python guardrails.py` runs the guardrail
checks, and `python refine.py --fakes` / `python verify.py --fakes` run with made-up
mistakes to show they get caught.

## What a run produces

Everything goes in `runs/<run id>/`, plus `runs/<run id>.zip`.

| File | |
|---|---|
| `raw_transcript.json` | speech-to-text output after removing hallucinations |
| `stt_log.json` | what was removed and why, where long audio was split |
| `edits.json` | the term list, and every proposed edit with its status and the check that decided it |
| `refined_transcript.json` | transcript with the accepted edits; the raw one is never changed |
| `record_draft.json` | what the documenter wrote, before checking |
| `record.json` | the checked meeting record |
| `minutes.md`, `.html`, `.pdf` | made from `record.json` with a fixed template, so they always match it |

Missing owners and deadlines say **Unspecified**, never a guess. Deadlines stay as
spoken ("by Friday"), never turned into dates.

## Testing on the eval meetings

`eval/meetings.py` has four scripted meetings with the right answers written down,
each full of traps (a proposal nobody accepted, "let's not", a task nobody owns, a
corrected number, tech terms).

```bash
python eval/make_audio.py     # makes the audio with the Mac's voices
python eval/score.py          # runs the pipeline on each and writes eval/results.md
```

Computer voices are very clear, so these mostly test the documenter. To test speech
recognition properly, record the same scripts with real people and save them as
`eval/audio/<name>.m4a`.

## Limits

- **No speaker labels.** Groq's Whisper doesn't say who spoke. So an owner only comes
  from a name said in the quote, and "I'll take it" shows as "Unspecified (someone
  volunteered)".
- **Confidence is per sentence, not per word.** Groq doesn't return word probabilities,
  so low-confidence marking uses each segment's `avg_logprob`.
- Groq changes its model list now and then. Check the model names at the top of
  `transcribe.py`, `refine.py`, `inventory.py` and `document.py` before a demo.
