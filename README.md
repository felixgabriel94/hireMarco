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
| Oct 28 | `hiremarco.studio.commands`, `studio.logic` | A spoken line becomes one command: the common ones by rule, instantly; the rest by Muse Spark with structured output, held to a fixed list. Logic's key commands for transport and punch-ins, a virtual MIDI port for three bounded plugin knobs, all through the gate, with a dry run that touches nothing |
| Oct 28 | `hiremarco.relay` | The call's brain: an OpenAI-style endpoint on the Mac for the voice agent, token-checked, gated, pinned to Muse Spark, streaming, cost-logged; the Meta key never leaves the machine |
| Oct 28 | `hiremarco.hearing` | Marco's ears on Muse Voice Transcribe: the booth mic streamed in realtime with model endpointing and studio keywords; the call transcribed in speaker-labelled turns |
| Oct 28 | `hiremarco.voice` | Marco's voice in the booth: ElevenLabs speech played into the headphones between takes only (checked again just before it plays), every line kept as a timestamped WAV for the film; the closing voice note as a WhatsApp voice message, mono OGG/OPUS, through the gate and the critic, sent on the Owner's Return |
| Oct 28 | `hiremarco.film` | The film's sound on one clock: the mic and the interface's virtual channels (Logic's output, Marco's voice) recorded the whole session long in 15-minute 24-bit segments, each one's first sample logged so the edit lines them up; overflows counted, not hidden |
| Oct 28 | `hiremarco.studio.feedback` | "Marco, how was that take?": Muse Spark 1.2 listens to the take and gives one producer's note in structured output; when one spot would fix it, the note ends "Want to punch it?" and Marco waits for the answer |
| Oct 28 | `hiremarco.hours` | Before the call, Muse Spark with search grounding checks the restaurant is open at that hour; read-only by construction: the answer is reduced to OPEN, CLOSED or UNSURE plus a cleaned hours line and the cited sources, so a web page can make Marco hold but never add an action, a number or a message |
| Oct 28 | `hiremarco.sam`, `studio.six176` | The 6176 read: SAM 3.1 finds every knob in the photo, then Muse Spark reads each numbered knob's label and setting in structured output; a knob it cannot read is left out, not guessed, and the line goes into the mix notes |
| Oct 28 | `hiremarco.studio.export_cu` | Logic's export dialog filled by Muse Wonder computer use on a short leash: dialog keys, clicks inside Logic's window and the one folder name only; a safety check, a stray action or twenty steps hands it back to Felix; every action through the gate |
| Oct 28 | `hiremarco.studio.booth` | The session by voice, end to end: the mic feeds Voice Transcribe and a tape of the take at once; each sentence for Marco becomes one command; the loop keeps the transport state so talkback holds during a take; "how was that take?" hears the tape, and "punch it" punches the spot the note named |
| Oct 28 | `hiremarco.studio.presets` | "Marco, my adlib preset": the saved Performances are read from Logic's own files, the spoken name matches one or none, and it loads through Logic's Setting menu by keyboard, the same keys every time, with the open menus counted before each typed step so a stray key never reaches Logic |
| Oct 28 | `hiremarco.studio.pitch` | Marco's pitch ear, built here: a YIN pitch detector, note segmentation and key-aware correction measure every note of a run in cents; the transcript finds the lyric; the corrected run plays back as a guide in the headphones or goes to Logic as MIDI |
| Oct 28 | `hiremarco.studio.plugins` | Full control of any open plugin with no knob learned: Logic's Controls view exposes every parameter by name, Marco reads and sets them and checks each value took; "make it spacey and a bit metallic" goes to Muse Spark with the plugin's real parameters in structured output, and "put it back" restores the exact settings before |
| Oct 28 | `hiremarco.studio.chain` | The whole channel from one description: Marco opens every active insert on the track in Controls view and reads it; Muse Wonder decides the changes across the chain like a mix engineer; only real plugins and parameters, at most twelve changes, level controls one step at a time, each value read back, and one "put it back" for all of it |
| Oct 28 | `hiremarco.mix.ears` | Marco's mix ears, built here: BS.1770 loudness (checked against the reference tone), true peak, crest, energy in seven mix bands, stereo and low-end mono; collisions where two tracks fight in a band; and what a mastering engineer needs from the mix: headroom, no clipping, loudness left to master |
| Oct 28 | `hiremarco.mix.rules` | The craft written down: where each instrument lives in the spectrum, how two parts that fight are separated, inserts for character and buses for space, small moves, and the lines a mix keeps for mastering; every plugin in the session is named by kind so Marco knows a reverb belongs on a bus |
| Oct 28 | `hiremarco.mix.loop` | The mix loop: Marco measures the exported tracks, Muse Wonder plans one pass across the session with the rulebook, the measurements and the artist's direction, Marco applies it inside the same limits, exports and measures again, and keeps the pass only if the collisions it targeted moved apart and the mix kept its headroom, otherwise he puts it all back |
| Oct 28 | `hiremarco.mix.handoff` | The two handoffs: the session folder a mix engineer expects, now with Marco's measurements of every track; and a bounced mix checked against what mastering needs (headroom, no clipping, mono low end, 24-bit or float, the whole song) and filed with its mastering notes only when it passes |
| Oct 28 | `hiremarco.mix.profiles`, `mix.inventory` | Expert profiles: Pro-Q 3 read in real units (Hz, dB, Q, worked out from its defaults) with its dynamic bands, external side chain and recipes such as ducking the bass under the kick, checked against the controls Logic exposes before use; a reason on every move; recommendations limited to the plugins installed on the Mac |
| Oct 28 | `hiremarco.mix.session` | The session view, a Controls view for the whole song: each track's role (from its name, confirmed by its reading), its own measurement, the collision grid over every pair and band ranked by energy, what the rest of the mix masks on each track, each track against its role's target for a clean balanced mix, and the hardware in front of Logic with the rule for where a fix lives |
| Oct 28 | `hiremarco.studio.tracks` | Recording and mixing are different jobs: Marco scans the session and knows which he is in, gives no mix opinion while recording unless asked, and keeps the session tidy as it grows: "we're on a harmony" names the track (color and summing stacks planned, mapped next), takes land on the same track, a mix pass runs on request, "keep it balanced as we go" turns on the light watch |
| Oct 28 | `hiremarco.mix.hearing` | The mix hearing: on a developed session Marco reads everything first, says what he hears in plain words, and asks how the artist feels; the answer becomes the song's guardrails (tracks to keep, wishes per track, a reference sound as Muse Wonder's understanding of it, measured numbers when a reference file is given), saved with the song and honored by every later pass. The artist is the CEO |
| Oct 28 | `hiremarco.marco`, `server`, `livelog`, `cli` | Marco's voice through the gate, the running webhook, his on-screen log, the `marco` command |

Planned, in order: the studio (voice
commands in Logic, three plugin knobs, take notes, the ready-to-mix export,
the 6176 read), the call and its proof, then Dress me.

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
