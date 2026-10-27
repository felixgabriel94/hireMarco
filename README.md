# hireMarco

Marco is a personal assistant who lives in your texts. A message comes in
while you are at the keys ("Saturday? We still need a reservation"), Marco
reads it, checks your calendar, and asks on WhatsApp: "Want me to book 7:30
for two?" You say yes. Marco calls the restaurant, books it, and sends you the
proof: the transcript card and the calendar entry. Then he asks whether you
also want him to check if Guitar Center has that pedal in stock.

Marco's brain is [Muse Spark](https://dev.meta.ai) on the Meta Model API. He
talks to you over WhatsApp, which the Meta glasses read aloud and answer by
voice, so the whole exchange happens without touching a phone.

Built for the **Meta Global AI Developer Hackathon**, Oct 26 to Nov 4, 2026
(Indie track, theme "Build for Your World").

## Built here

Every line in this repository was written inside the event window. The log
below grows as the build does; `git log` carries the dates.

| Date | Package | What it does |
|---|---|---|
| Oct 26 | `hiremarco.meta` | Muse Spark client on the Meta Model API with cost per call |
| Oct 26 | `hiremarco.joblog` | Append-only job log, one JSON line per call with its cost |
| Oct 26 | `hiremarco.rules` | Send switches read from `RULES.md`; absent means off |
| Oct 26 | `hiremarco.config` | Secrets from one file outside the repo; values never printed |

Planned, in order: `whatsapp` (Cloud API client and webhook), `offer` (Marco
finds the task, checks the calendar, asks), `calls` (the voice agent with
Muse Spark as its brain), `proof` (Muse Voice Transcribe, the transcript
card, the calendar entry). Stretches after Oct 30: the studio effect written
live by Muse Code, and a browser booking.

## Setup used, not built here

These existed before the event or are products used as they are. They are
labelled the same way in the video.

- Meta Model API and its models (Muse Spark, Muse Voice Transcribe)
- WhatsApp Cloud API, with Marco's phone number registered as the sender
- Meta glasses as the camera and the voice interface
- Twilio (a phone number for outbound calls) and ElevenLabs (the voice)
- The developer's own phone, calendar and contacts

hireMarco is also the name of a private product in development by the same
author. None of its code is in this repository; the demo's Marco, his voice
and every package here were written new for the event.

## Run

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

    uv sync
    uv run pytest
    uv run python -m hiremarco.meta.ping "Say hello in five words."

Secrets go in `~/.config/hiremarco/env` as `KEY=value` lines (see
`src/hiremarco/config.py` for the key names). The file is never committed.

## Rules

`RULES.md` governs what this code may do: nothing sends outbound without a
committed send-switch line, spend is logged and capped, secrets stay outside
the repository. The code enforces the first; the check script enforces the
third.

## License

MIT, see `LICENSE`.
