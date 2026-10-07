import subprocess
import sys
import tempfile
from pathlib import Path

from meetings import MEETINGS

AUDIO_DIR = Path(__file__).parent / "audio"
PAUSE = 0.6


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make(meeting):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pause = tmp / "pause.wav"
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(PAUSE), str(pause))

        parts = []
        for i, (speaker, text) in enumerate(meeting["lines"]):
            aiff = tmp / f"{i:03d}.aiff"
            voice = meeting["voices"][speaker]
            # if this Mac doesn't have that voice, use the default one
            if subprocess.run(["say", "-v", voice, "-o", str(aiff), text]).returncode != 0:
                subprocess.run(["say", "-o", str(aiff), text], check=True)
            wav = tmp / f"{i:03d}.wav"
            ffmpeg("-i", str(aiff), "-ar", "22050", "-ac", "1", str(wav))
            parts += [wav, pause]

        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        AUDIO_DIR.mkdir(exist_ok=True)
        out = AUDIO_DIR / f"{meeting['name']}.m4a"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "aac", str(out))
    return out


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    for meeting in MEETINGS:
        if meeting["name"].startswith(only):
            print("made", make(meeting))
