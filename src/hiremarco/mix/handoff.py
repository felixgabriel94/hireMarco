"""The two handoffs: a session ready for a mix engineer, and a mix ready for mastering.

``ready_to_mix`` takes the tracks Logic exported and builds the folder a mix
engineer expects (``studio.export``: clean names, format and clipping checks,
mix notes, zipped) and adds Marco's measurements of every track.

``ready_for_mastering`` checks a bounced mix against what a mastering engineer
needs (true-peak headroom, no clipping, loudness left to master, mono low
end, sane stereo, 24-bit or float at the session rate) and only then files it
with its mastering notes. A mix that misses a line is reported, not filed.
"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import soundfile as sf

from hiremarco.mix.ears import listen, measure, mix_notes, summary
from hiremarco.studio.export import clean_name, prepare

GOOD_SUBTYPES = {"PCM_24", "PCM_32", "FLOAT", "DOUBLE"}


@dataclass
class MasterCheck:
    ready: bool
    problems: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    folder: Path | None = None


def ready_to_mix(stems: Path, dest_root: Path, *, song: str, **notes) -> Path:
    report = prepare(Path(stems), Path(dest_root), song=song, **notes)
    folder = Path(report.folder)
    analysis = listen(folder / "stems" if (folder / "stems").exists() else Path(stems))
    text = "Measured by Marco (loudness BS.1770, bands, collisions)\n\n" + summary(analysis) + "\n"
    (folder / "ANALYSIS.txt").write_text(text)
    with zipfile.ZipFile(report.zip_path, "a") as bundle:  # the zip carries the measurements too
        bundle.writestr(f"{folder.name}/ANALYSIS.txt", text)
    return folder


def ready_for_mastering(mix_file: Path, dest_root: Path, *, song: str, today: date | None = None) -> MasterCheck:
    mix_file = Path(mix_file)
    info = sf.info(mix_file)
    audio, rate = sf.read(mix_file, dtype="float32", always_2d=False)
    mix = measure(audio, rate, mix_file.stem)
    notes = mix_notes(mix)
    advice = [n for n in notes if "very quiet" in n]  # a quiet mix is the mastering engineer's to raise
    problems = [n for n in notes if n not in advice]
    if info.subtype not in GOOD_SUBTYPES:
        problems.append(f"{info.subtype} audio: bounce 24-bit or 32-bit float for mastering")
    if mix.seconds < 30:
        problems.append(f"only {mix.seconds} s long: bounce the whole song with its tails")
    facts = {"sample_rate": rate, "format": f"{info.format}/{info.subtype}", "seconds": mix.seconds,
             "lufs": mix.lufs, "true_peak_db": mix.true_peak_db, "headroom_db": round(-mix.true_peak_db, 1),
             "low_end_mono": mix.low_mono, "correlation": mix.correlation}
    if problems:
        return MasterCheck(False, problems, facts)
    day = (today or date.today()).isoformat()
    slug = clean_name(song)
    folder = Path(dest_root) / f"{slug}_for_mastering_{day}"
    if folder.exists():
        raise FileExistsError(f"{folder} already exists; nothing was overwritten")
    folder.mkdir(parents=True)
    target = folder / f"{slug} - mix for mastering.wav"
    shutil.copy2(mix_file, target)
    lines = [f"# {song}: mix for mastering", "", f"File: {target.name}",
             f"Format: {facts['format']}, {rate} Hz, {mix.seconds} s",
             f"Integrated loudness: {mix.lufs} LUFS", f"True peak: {mix.true_peak_db} dBTP "
             f"({facts['headroom_db']} dB headroom)",
             f"Low end below 120 Hz: correlation {mix.low_mono}", f"Stereo correlation: {mix.correlation}",
             *(["", "Note: " + "; ".join(advice)] if advice else []),
             "", "No limiter or loudness processing on the stereo output. Final loudness is the mastering "
             "engineer's call.", "", f"Checked by Marco, {day}."]
    (folder / "MASTERING_NOTES.md").write_text("\n".join(lines) + "\n")
    return MasterCheck(True, [], facts, folder)
