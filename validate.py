import json
import re
import subprocess
import sys
from pathlib import Path

MIN_SECONDS = 3
MAX_SECONDS = 3 * 60 * 60
MAX_MB = 1024
MIN_SPEECH_RATIO = 0.02
SILENCE_DB = -35
SILENCE_MIN_SECONDS = 0.5

MESSAGES = {
    "EMPTY_FILE": "The file is empty.",
    "TOO_LARGE": "The file is {mb:.0f} MB, the limit is {limit} MB.",
    "UNSUPPORTED_FORMAT": "This isn't an audio or video file (looks like {kind}). "
                          "Upload wav, mp3, m4a, flac, ogg, mp4 or similar.",
    "NO_AUDIO_STREAM": "This video has no audio track.",
    "UNREADABLE": "The file looks damaged and can't be decoded. Try exporting it again.",
    "TOO_SHORT": "The recording is {seconds:.1f} s long, it needs at least {limit} s.",
    "TOO_LONG": "The recording is {minutes:.0f} minutes long, the limit is {limit:.0f} minutes.",
    "NO_SPEECH": "No speech found. The file may be silent or only music.",
}


class AudioError(Exception):
    def __init__(self, code, **details):
        self.code = code
        self.message = MESSAGES[code].format(**details)
        super().__init__(self.message)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def what_is_it(path):
    head = path.read_bytes()[:512]
    if head.startswith(b"PK"):
        kind = "a zip or Office document"
    elif head.startswith(b"%PDF"):
        kind = "a PDF"
    elif head and all(32 <= b < 127 or b in (9, 10, 13) for b in head):
        kind = "a text file"
    else:
        kind = "an unknown file type"
    return f"{kind}, named {path.suffix or 'without an extension'}"


def probe(path):
    result = run(["ffprobe", "-v", "error", "-print_format", "json",
                  "-show_format", "-show_streams", str(path)])
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def duration_of(path):
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (TypeError, KeyError, ValueError):
        return 0.0


def find_silences(path):
    result = run(["ffmpeg", "-v", "info", "-i", str(path), "-af",
                  f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_MIN_SECONDS}",
                  "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", result.stderr)]
    silences = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else None
        silences.append((start, end))
    return silences


def validate(path, out_dir):
    path = Path(path)
    out_dir = Path(out_dir)

    if not path.exists() or path.stat().st_size == 0:
        raise AudioError("EMPTY_FILE")

    mb = path.stat().st_size / (1024 * 1024)
    if mb > MAX_MB:
        raise AudioError("TOO_LARGE", mb=mb, limit=MAX_MB)

    info = probe(path)
    if info is None:
        raise AudioError("UNSUPPORTED_FORMAT", kind=what_is_it(path))

    streams = [s.get("codec_type") for s in info.get("streams", [])]
    if "audio" not in streams:
        if "video" in streams:
            raise AudioError("NO_AUDIO_STREAM")
        raise AudioError("UNSUPPORTED_FORMAT", kind=what_is_it(path))

    claimed = float(info.get("format", {}).get("duration") or 0)
    if claimed > MAX_SECONDS:
        raise AudioError("TOO_LONG", minutes=claimed / 60, limit=MAX_SECONDS / 60)

    # whisper wants 16 kHz mono, and flac keeps it small without losing quality
    out_dir.mkdir(parents=True, exist_ok=True)
    decoded = out_dir / "audio_16k.flac"
    result = run(["ffmpeg", "-v", "error", "-y", "-i", str(path),
                  "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(decoded)])
    if result.returncode != 0 or not decoded.exists():
        raise AudioError("UNREADABLE")

    duration = duration_of(decoded)
    if duration <= 0:
        raise AudioError("UNREADABLE")

    # a cut-off file still says it's 20 s long, but only a bit of it decodes
    if claimed and duration < 0.5 * claimed and duration < MIN_SECONDS:
        raise AudioError("UNREADABLE")
    if duration < MIN_SECONDS:
        raise AudioError("TOO_SHORT", seconds=duration, limit=MIN_SECONDS)

    warnings = []
    if claimed and duration < 0.5 * claimed:
        warnings.append(f"Only {duration:.0f} s of the {claimed:.0f} s file could be read.")

    silences = find_silences(decoded)
    silent = sum((end if end is not None else duration) - start for start, end in silences)
    speech_ratio = max(0.0, 1 - silent / duration)
    if speech_ratio < MIN_SPEECH_RATIO:
        raise AudioError("NO_SPEECH")

    return {
        "decoded": str(decoded),
        "duration": round(duration, 2),
        "speech_ratio": round(speech_ratio, 3),
        "silences": silences,
        "warnings": warnings,
    }


if __name__ == "__main__":
    try:
        audio = validate(sys.argv[1], "validate_out")
        print(f"OK  {audio['duration']} s, {audio['speech_ratio']:.0%} not silent, "
              f"{len(audio['silences'])} silences")
        for w in audio["warnings"]:
            print("warning:", w)
    except AudioError as error:
        print(f"{error.code}: {error.message}")
