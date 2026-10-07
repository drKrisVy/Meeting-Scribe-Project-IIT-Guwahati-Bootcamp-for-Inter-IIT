# Technical description

## Models

| Stage | Model | Job |
|---|---|---|
| Speech-to-text | Whisper Large V3 Turbo (`whisper-large-v3-turbo`, on Groq) | audio to text, with timestamps for every segment and word, and a confidence score per segment |
| Language model 1, refiner | GPT-OSS 120B (`openai/gpt-oss-120b`, on Groq) | fixes words speech recognition got wrong: tech terms, names, acronyms, words wrongly split or joined |
| Language model 2, documenter | GPT-OSS 120B (`openai/gpt-oss-120b`, on Groq) | writes the summary, minutes by topic, decisions, action items and open questions |

The two language model stages are separate: different prompts, different calls,
different output files, and they run one after the other. Each one's model name is a
single line at the top of its file, so either can be swapped.

Why these: Groq runs Whisper and the LLMs without needing a GPU, has a free tier, and
is fast. GPT-OSS 120B was the strongest model Groq offered without an enterprise plan
when this was built.

## How the outputs move between stages

1. **Validate** (`validate.py`). ffprobe checks the file has audio and a sensible
   length; ffmpeg converts it to 16 kHz mono flac. Empty, damaged, silent, too short
   or non-audio files stop here with a plain message.

2. **Transcribe** (`transcribe.py`). Groq takes at most 25 MB per request, so long
   recordings are cut into about 10 minute pieces at silences (`chunks.py`) and the
   timestamps are joined back up. `shape.py` gives each segment an id and its own words.
   `hallucination.py` removes Whisper's known mistakes (repeated phrases, high
   compression ratio, "thanks for watching" in silence) and logs each removal.
   Output: `raw_transcript.json`.

3. **Refine** (`refine.py`). First the model lists the meeting's terms
   (`inventory.py`); code keeps a term only if it was really said and the misheard form
   sounds like it. Then the model proposes small edits that point at exact word
   positions. Eight checks in `guardrails.py` decide each edit:

   | Check | Rule |
   |---|---|
   | anchor | the words being replaced really are at those positions |
   | size | at most 4 words in and out |
   | numbers | numbers can't change, and "fifteen" → "15" isn't allowed either |
   | negation | can't add or remove not / never / n't (flagged for review) |
   | commitment | can't change will / should / must / going to (flagged for review) |
   | sound-alike | the new words have to sound like the old ones |
   | supported | every new word was said in the meeting, is a checked term, or is a common word |
   | overlap | two edits can't touch the same words |

   Once a misheard term is fixed, the same mishearing elsewhere gets the same fix.
   Output: `edits.json` and `refined_transcript.json`; the raw transcript is not changed.

4. **Document** (`document.py`, `verify.py`). The model writes topics with minutes,
   then decisions and tasks, quoting the refined transcript for each. Code checks:

   - every quote is really in the transcript (and swaps in the exact words),
   - an owner or deadline is kept only if it's in a quote,
   - "agreed" needs a quote where someone agreed; otherwise it becomes "proposed",
   - "confirmed" needs a yes or a volunteer; otherwise it drops to "assigned" or "suggested".

   Items that fail get one repair try, then go to Needs review. Duplicates are merged.
   The summary is written last, only from checked items, and is rejected if it uses a
   number or name nobody said. Output: `record.json`.

5. **Export** (`render.py`). A fixed template turns `record.json` into minutes.md,
   minutes.html and minutes.pdf, so the readable minutes and the JSON always hold the
   same items.

Every stage saves its files before the next one starts, so a failed run can carry on
from the stage that failed. Same input gives the same output: temperature is 0 and LLM
answers are cached by a hash of the model, prompt and input.
