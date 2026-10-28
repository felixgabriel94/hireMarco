# hireMarco

**Meet your new COO.** Marco is an AI operator you text. This repository
shows him in one role, built in ten days for one artist's world. hireMarco is
built to run the whole operation, business and personal.

Here he works for an artist. He lives in WhatsApp, which the
Meta glasses read aloud and answer by voice, and he runs the technical side
of a recording session so the artist can stay on the mic: "Marco, take me to
the chorus. New track. Record." He reads the email that matters, offers to
handle it, books the table by phone, and sends the proof.

Marco's brain is [Muse Spark](https://dev.meta.ai) on the Meta Model API.
Every action he takes passes one gate first, and anything that cannot be
taken back also passes a critic on Muse Wonder that checks the plan
against `RULES.md`. If either says no, Marco holds and asks.

Built for the **Meta Global AI Developer Hackathon**, Oct 26 to Nov 4, 2026
(Indie track, theme "Build for Your World").

## Meta models in Marco

Every judgment Marco makes runs on Meta's models through the Meta Model API
(Standard mode). This table grows with the build: a model is listed as live
only once the code that calls it is committed.

| Model | What it does for Marco | Status |
|---|---|---|
| `muse-spark-1.3` | His answers | live |
| `muse-wonder-1.0` | The critic: approves or holds anything that cannot be taken back, so only high-stakes calls use the top-tier model | live |
| `muse-wonder-1.0` | Computer use: clicks through Logic's export dialog for the ready-to-mix folder | this week |
| `muse-spark-1.3` | Turning a spoken studio command into one Logic action (structured output, minimal reasoning); reading the 6176 from a photo; the brain on the restaurant call; checking the restaurant's hours with search grounding before it dials | this week |
| `muse-spark-1.2` | "Marco, how was that take?": listens to the take and gives a producer's note (Meta's recommended version for audio input) | this week |
| `muse-voice-transcribe-1.0` | Hearing studio commands and take notes live from the mic (keyword biasing, endpointing); the call transcript with speaker labels behind the proof card | this week |
| `sam-3.1` | Isolating the 6176's knobs in the glasses photo before Muse Spark reads them; the clothes on the bed for Dress me | this week |
| `muse-image-1.0` | The look board for Dress me | this week |

## Built here

Every line in this repository was written inside the event window. The log
below grows as the build does; `git log` carries the dates.

| Date | Package | What it does |
|---|---|---|
| Oct 26 | `hiremarco.meta` | Muse Spark client on the Meta Model API with cost per call |
| Oct 26 | `hiremarco.joblog` | Append-only job log, one JSON line per call with its cost |
| Oct 26 | `hiremarco.rules` | Send switches read from `RULES.md`; absent means off |
| Oct 26 | `hiremarco.config` | Secrets from one file outside the repo; values never printed |
| Oct 28 | `hiremarco.gate` | One gate for every action: send switches, Owner-only WhatsApp, the call's recording notice, kill switch, duplicate refusal, daily limits, model spend cap |
| Oct 28 | `hiremarco.critic` | A second pass on Muse Wonder before anything irreversible; fails closed |
| Oct 28 | `hiremarco.whatsapp` | Cloud API client and webhook: signature check, Owner only, retries skipped, 24-hour window respected |
| Oct 28 | `hiremarco.google` | One Google sign-in (PKCE, loopback): Gmail read only from senders `RULES.md` grants, checked again by the From header; calendar check and add through the gate |
| Oct 28 | `hiremarco.studio.export` | The ready-to-mix folder: copies Logic's exported tracks, names them in order, checks one sample rate and one length, reads peaks, flags clipping and silence, writes mix notes, zips it |
| Oct 28 | `hiremarco.proof` | Resy's email, read by Muse Spark into fixed fields, checked against what Marco asked for; only a match becomes the proof card and the calendar entry |
| Oct 28 | `hiremarco.offer` | An email that matters becomes one WhatsApp question: Muse Spark reads the task, picks a place only from the Owner's own list, the calendar says if the time is clear |
| Oct 28 | `hiremarco.marco`, `server`, `livelog`, `cli` | Marco's voice through the gate, the running webhook, his on-screen log, the `marco` command |

Planned, in order: the studio (voice
commands in Logic, three plugin knobs, take notes, the ready-to-mix export,
the 6176 read), the call and its proof, the voice note, then Dress me.

## Setup used, not built here

These existed before the event; everything in the table above was built during it.

**Ours, from before the event**

- The hireMarco name, logo and brand
- Marco's personality files, kept private and read at runtime from a folder
  outside this repository; never published
- The design of the gate, from the private hireMarco product: its entry
  points and rules, not its code. The gate here, the critic and every other
  package were written new for the event

**Products used as they are**

- Meta Model API and its models (Muse Spark, Muse Voice Transcribe)
- Meta glasses as the camera and the voice interface
- WhatsApp (Cloud API), with Marco's own number registered as the sender
- The voice (ElevenLabs)
- Google Calendar and Resy
- Logic Pro

## Run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

    uv sync
    uv run pytest
    uv run marco env
    uv run marco demo first-answer

Secrets go in `~/.config/hiremarco/env` as `KEY=value` lines (see
`src/hiremarco/config.py` for the key names). The file is never committed.

## Rules

`RULES.md` governs what this code may do: nothing sends outbound without a
committed send-switch line, spend is logged and capped, secrets stay outside
the repository. The gate enforces the first two; the check script enforces
the third.

## About hireMarco

This demo shows what was built during the event. Marco does more in the
hireMarco product, which is private and in development:
[hiremarco.ai](https://hiremarco.ai).

## License

MIT, see `LICENSE`.
