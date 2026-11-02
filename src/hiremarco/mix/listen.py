"""Marco's ears beyond the meters: the hearing stack, when it is installed on this Mac.

The audit measures (loudness, spectrum, width, clicks). This module asks the
private hearing stack what a listener would hear: psychoacoustic loudness,
sharpness and roughness (MoSQITo), Meta's Audiobox Aesthetics scores (content
enjoyment, usefulness, production complexity, production quality, 1 to 10),
what the sound is like in words (CLAP against a few descriptions) and, when a
reference is given, how close the two sound to a human (Zimtohrli, as a MOS
out of 5). The stack lives outside the repository (its licenses do not mix with
this one) at HIREMARCO_HEARING, default ~/.local/share/hiremarco-hearing, with
its own interpreter and a ``listen.py`` that prints one JSON object. Absent,
Marco masters on the meters alone and says so in the record.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

HEARING = Path(os.environ.get("HIREMARCO_HEARING", "~/.local/share/hiremarco-hearing")).expanduser()
TIMEOUT_S = 900

GLOSS = {
    "psychoacoustics": "MoSQITo on a half minute from the body: loudness in sone (Zwicker, time-varying; a doubling "
                       "is twice as loud), sharpness in acum (above about 1.8 reads bright or harsh), roughness in "
                       "asper (above about 0.3 reads gritty or distorted)",
    "audiobox_aesthetics": "Meta Audiobox Aesthetics, 1 to 10: CE content enjoyment, CU content usefulness, PC "
                           "production complexity, PQ production quality (the one a master should raise)",
    "clap": "CLAP: cosine similarity of the sound to each description, higher is more alike; mix_vs_reference is "
            "the two files' similarity",
    "zimtohrli": "Zimtohrli: perceptual distance on ten seconds, mos_mix_vs_reference is a predicted listener "
                 "score out of 5 for how alike the two sound",
}


def available(home: Path = HEARING) -> bool:
    return (home / "env" / "bin" / "python").exists() and (home / "listen.py").exists()


def listen(path: Path, reference: Path | None = None, *, home: Path = HEARING, timeout: float = TIMEOUT_S,
           run: Callable = subprocess.run) -> dict | None:
    """What the stack hears in ``path`` (and against ``reference``); None when the stack is not installed. A stack
    that fails answers with an "error" key rather than stopping the job."""
    if not available(home):
        return None
    args = [str(home / "env" / "bin" / "python"), "-I", str(home / "listen.py"), str(path)]
    if reference is not None:
        args.append(str(reference))
    try:
        done = run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"the hearing stack took over {timeout:g} s"}
    if done.returncode != 0:
        return {"error": (done.stderr or "").strip()[-300:] or f"exit {done.returncode}"}
    try:
        data = json.loads(done.stdout)
    except ValueError:
        return {"error": "the hearing stack printed no JSON"}
    return data if isinstance(data, dict) else {"error": "the hearing stack printed something else"}


def for_model(hearing: dict | None) -> dict | None:
    """The stack's answer with a gloss per layer, so the brain reads sone and acum as an engineer would."""
    if not hearing:
        return None
    out = {}
    for layer, value in hearing.items():
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k != "took_s"}
        out[layer] = {"what": GLOSS.get(layer, ""), "heard": value}
    return out


def highlights(hearing: dict | None) -> list[str]:
    """One line per layer that answered, for the log and the artist."""
    if not hearing:
        return []
    lines = []
    psy = hearing.get("psychoacoustics")
    if isinstance(psy, dict):
        lines.append(f"heard: {psy.get('loudness_sone_mean', 0):.1f} sone, sharpness {psy.get('sharpness_acum_mean', 0):.2f} acum, "
                     f"roughness {psy.get('roughness_asper_mean', 0):.2f} asper")
    aes = hearing.get("audiobox_aesthetics")
    if isinstance(aes, dict) and isinstance(aes.get("mix"), dict):
        m = aes["mix"]
        lines.append("Audiobox: " + ", ".join(f"{k} {float(v):.1f}" for k, v in m.items() if k in ("CE", "CU", "PC", "PQ")))
        if isinstance(aes.get("reference"), dict):
            r = aes["reference"]
            lines.append("  the reference: " + ", ".join(f"{k} {float(v):.1f}" for k, v in r.items() if k in ("CE", "CU", "PC", "PQ")))
    clap = hearing.get("clap")
    if isinstance(clap, dict) and isinstance(clap.get("words"), dict):
        best = max(clap["words"].items(), key=lambda kv: kv[1])
        lines.append(f"sounds most like: {best[0]} ({best[1]:.2f})")
    zim = hearing.get("zimtohrli")
    if isinstance(zim, dict) and "mos_mix_vs_reference" in zim:
        lines.append(f"against the reference: {float(zim['mos_mix_vs_reference']):.2f} of 5 alike")
    if "error" in hearing:
        lines.append(f"the hearing stack failed: {hearing['error']}")
    return lines
