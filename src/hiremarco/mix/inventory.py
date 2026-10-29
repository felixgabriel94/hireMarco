"""The plugins the artist owns, so Marco only recommends what is already on the Mac.

Audio Unit plugins are bundles in the Components folders, named as Logic
lists them; Logic's own effects are always there. Each is named by kind with
the rulebook's classifier, and only effect kinds are offered to the model
(instruments and unknown names are left out). A plugin shell that hosts many
plugins under one bundle (WaveShell) appears as the shell only.
"""

from __future__ import annotations

from pathlib import Path

from hiremarco.mix.rules import kind

COMPONENT_DIRS = [Path("/Library/Audio/Plug-Ins/Components"), Path.home() / "Library/Audio/Plug-Ins/Components"]
LOGIC_STOCK = ["Channel EQ", "Linear Phase EQ", "Vintage Console EQ", "Vintage Graphic EQ", "Vintage Tube EQ",
               "Compressor", "Multipressor", "Limiter", "Adaptive Limiter", "DeEsser 2", "Noise Gate",
               "ChromaVerb", "Space Designer", "Silververb", "Stereo Delay", "Tape Delay", "Echo", "Delay Designer",
               "Chorus", "Ensemble", "Flanger", "Phaser", "Tremolo", "Pitch Correction", "Pitch Shifter",
               "Overdrive", "Distortion", "Bitcrusher", "ChromaGlow", "Exciter", "Phat FX"]
NOT_EFFECTS = {"unknown"}


def installed(dirs: list[Path] | None = None) -> list[str]:
    names = set(LOGIC_STOCK)
    for folder in dirs if dirs is not None else COMPONENT_DIRS:
        if folder.is_dir():
            names.update(p.stem for p in folder.glob("*.component"))
    return sorted(names)


def by_kind(names: list[str], per_kind: int = 25) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for name in names:
        k = kind(name)
        if k in NOT_EFFECTS:
            continue
        grouped.setdefault(k, [])
        if len(grouped[k]) < per_kind:
            grouped[k].append(name)
    return grouped
