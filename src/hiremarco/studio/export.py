"""The ready-to-mix folder.

Logic's "Export All Tracks as Audio Files" writes one file per track. Marco
copies them (the originals are never moved or changed), names them in
order, checks that every stem shares one sample rate and one length, reads
each stem's peak, flags clipping, writes MIX_NOTES.md and zips the folder.
"""

from __future__ import annotations

import math
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import soundfile as sf

AUDIO_SUFFIXES = {".wav", ".aif", ".aiff", ".caf"}
CLIP_LEVEL = 0.999  # a sample this close to full scale counts as touching it
CLIP_RUN = 3        # consecutive samples at that level count as a clip


@dataclass
class Stem:
    source: Path
    name: str
    samplerate: int
    subtype: str
    channels: int
    frames: int
    peak_dbfs: float
    clips: int
    silent: bool

    @property
    def seconds(self) -> float:
        return self.frames / self.samplerate if self.samplerate else 0.0


@dataclass
class ExportReport:
    folder: Path
    zip_path: Path
    stems: list[Stem]
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """The short line Marco says out loud."""
        count = len(self.stems)
        if not self.problems:
            return f"{count} stems, all clean. The folder is ready for mix."
        return f"{count} stems. {len(self.problems)} to look at: " + "; ".join(self.problems[:2]) + "."


def clean_name(stem: str, project: str = "") -> str:
    """'Song Title_Lead Vox#02' -> 'Lead_Vox_2'."""
    name = stem
    if project and name.lower().startswith(project.lower()):
        name = name[len(project):]
    name = re.sub(r"#0*(\d+)$", r" \1", name)
    name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return name or "Track"


def _clip_count(data: np.ndarray) -> int:
    hot = np.abs(data) >= CLIP_LEVEL
    if hot.ndim > 1:
        hot = hot.any(axis=1)
    if not hot.any():
        return 0
    edges = np.diff(np.concatenate(([0], hot.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return int(np.sum((ends - starts) >= CLIP_RUN))


def inspect(path: Path, name: str) -> Stem:
    info = sf.info(str(path))
    data, _ = sf.read(str(path), dtype="float32", always_2d=True)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    return Stem(
        source=path, name=name, samplerate=info.samplerate, subtype=info.subtype, channels=info.channels,
        frames=info.frames, peak_dbfs=20 * math.log10(peak) if peak > 0 else float("-inf"),
        clips=_clip_count(data), silent=peak < 1e-5,
    )


def prepare(source: Path, dest_root: Path, *, song: str, take_notes: list[str] | None = None,
            producer_notes: list[str] | None = None, bpm: float | None = None, key: str | None = None,
            today: date | None = None) -> ExportReport:
    source, dest_root = Path(source), Path(dest_root)
    files = sorted(p for p in source.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES and not p.name.startswith("."))
    if not files:
        raise FileNotFoundError(f"no audio files in {source}")
    day = (today or date.today()).isoformat()
    slug = clean_name(song)
    folder = dest_root / f"{slug}_ready_to_mix_{day}"
    if folder.exists():
        raise FileExistsError(f"{folder} already exists; nothing was overwritten")
    stems_dir = folder / "stems"
    stems_dir.mkdir(parents=True)

    stems: list[Stem] = []
    for number, path in enumerate(files, start=1):
        name = f"{number:02d}_{clean_name(path.stem, song)}{path.suffix.lower()}"
        shutil.copy2(path, stems_dir / name)
        stems.append(inspect(stems_dir / name, name))

    problems: list[str] = []
    rates = {s.samplerate for s in stems}
    if len(rates) > 1:
        problems.append("sample rates differ: " + ", ".join(f"{r} Hz" for r in sorted(rates)))
    lengths = {s.frames for s in stems}
    if len(lengths) > 1:
        problems.append("stems are not the same length, so they will not line up")
    for s in stems:
        if s.clips:
            problems.append(f"{s.name} clips {s.clips} time{'s' if s.clips != 1 else ''}")
        if s.silent:
            problems.append(f"{s.name} is silent")

    (folder / "MIX_NOTES.md").write_text(_notes(song, day, stems, problems, take_notes, producer_notes, bpm, key))
    zip_path = dest_root / f"{folder.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(folder.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(dest_root))
    return ExportReport(folder=folder, zip_path=zip_path, stems=stems, problems=problems)


def _notes(song, day, stems, problems, take_notes, producer_notes, bpm, key) -> str:
    first = stems[0]
    lines = [f"# {song}: ready to mix", "", f"Prepared by Marco on {day}.", ""]
    lines.append(f"- Sample rate: {first.samplerate} Hz" + (" (mixed, see below)" if problems and "sample rates differ" in problems[0] else ""))
    lines.append(f"- Format: {first.subtype}, {len(stems)} stems, {first.seconds:.1f} s each")
    if bpm:
        lines.append(f"- Tempo: {bpm:g} BPM")
    if key:
        lines.append(f"- Key: {key}")
    lines += ["", "## Stems", "", "| Stem | Peak | Notes |", "|---|---|---|"]
    for s in stems:
        peak = "silent" if s.silent else f"{s.peak_dbfs:.1f} dBFS"
        note = f"clips {s.clips}x" if s.clips else ""
        lines.append(f"| {s.name} | {peak} | {note} |")
    lines += ["", "## Checks", ""]
    lines += [f"- {p}" for p in problems] if problems else ["- All stems share one sample rate and one length; no clipping found."]
    if take_notes:
        lines += ["", "## From the session", ""] + [f"- {n}" for n in take_notes]
    if producer_notes:
        lines += ["", "## For the mix", ""] + [f"- {n}" for n in producer_notes]
    return "\n".join(lines) + "\n"
