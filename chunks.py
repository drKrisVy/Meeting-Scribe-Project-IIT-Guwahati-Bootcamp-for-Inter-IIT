import subprocess
from pathlib import Path

MAX_UPLOAD_MB = 24
CHUNK_SECONDS = 10 * 60
SEARCH_SECONDS = 30


def needs_splitting(path, duration):
    mb = Path(path).stat().st_size / (1024 * 1024)
    return mb > MAX_UPLOAD_MB or duration > CHUNK_SECONDS * 1.5


def plan_cuts(duration, silences, chunk_seconds=CHUNK_SECONDS, search_seconds=SEARCH_SECONDS):
    # cut in the middle of the silence closest to every 10 min mark,
    # so no word gets cut in half
    middles = [(start + end) / 2 for start, end in silences if end is not None]
    cuts = []
    target = chunk_seconds
    while target < duration - chunk_seconds * 0.25:
        last = cuts[-1] if cuts else 0.0
        near = [m for m in middles if abs(m - target) <= search_seconds and m > last + 30]
        cut = min(near, key=lambda m: abs(m - target)) if near else target
        cuts.append(round(cut, 2))
        target = cut + chunk_seconds
    return cuts


def split(path, cuts, duration, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bounds = [0.0] + cuts + [duration]
    pieces = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        piece = out_dir / f"chunk_{i:03d}.flac"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
                        "-i", str(path), "-c:a", "flac", str(piece)],
                       check=True, capture_output=True)
        pieces.append((piece, start))
    return pieces


def make_pieces(audio, out_dir):
    if not needs_splitting(audio["decoded"], audio["duration"]):
        return [(Path(audio["decoded"]), 0.0)]
    cuts = plan_cuts(audio["duration"], audio["silences"])
    return split(audio["decoded"], cuts, audio["duration"], Path(out_dir) / "chunks")


if __name__ == "__main__":
    print(plan_cuts(1900, []))
    print(plan_cuts(1300, []))
    print(plan_cuts(1700, [(590.0, 592.0), (1201.0, 1203.0)]))
