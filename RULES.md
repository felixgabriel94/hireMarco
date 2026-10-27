# Rules

The rules this repository runs under. They bind every session that writes
here, human or model. Written 2026-10-26 for the Meta Global AI Developer
Hackathon window (Oct 26 to Nov 4, 2026); reopen each at the window's end.

## What goes out

**Nothing sends outbound without a send switch.** A send is a message or a
call to anyone, including the Owner. A switch is a line in the section below,
committed; absent means off, and nothing said in conversation is a switch.
The code reads this file at run time (`hiremarco.rules.require`) and refuses
a tool or destination with no live line. Check: `tests/test_rules.py`.

Grammar, one line each, under the heading that follows:

    send: <tool> -> <destination> ; <purpose> ; until <YYYY-MM-DD>

`<tool>` is the package that sends (`whatsapp`, `calls`); `<destination>` is a
phone number in E.164 without the plus. A new destination is a new line.

## Send switches

(none yet; every tool is off)

## Money

Caps in code: 10 minutes per call, 30 calls per day, and every model call,
message and call lands in the job log with its cost. The Meta Model API runs
on the hackathon credits with the spend limit set at the console. Twilio and
ElevenLabs spend is reported to the Owner when it passes 50 USD; the figure is
a stop point for a report, not a ceiling. Check: the job log's daily total.

## Secrets

Secrets live in one file outside the repository, `~/.config/hiremarco/env`,
mode 600, as `KEY=value` lines. No secret appears in this repository, a log,
a test, a commit message or a chat. Code reports which keys are present,
not their values. Check: `scripts/check.sh` greps tracked and staged files
for secret shapes; `.gitignore` excludes env files.

## What counts as built here

Everything in this repository was written from Oct 26, 2026, inside the
event. Pre-existing tools and accounts (the Meta glasses, a phone number, the
Twilio and ElevenLabs accounts, the Meta Model API, the WhatsApp Cloud API) are
setup, used and labelled as such in the README and the video, not presented
as built. No code from any earlier private project is copied in. Check: the
README's "Built here" and "Setup used" sections; `git log` dates.

## Shape

Small packages under `src/hiremarco/`, each with its own tests under
`tests/`. A commit is a subject line, a blank line and a short body. The
check script runs before every commit: `scripts/check.sh`. A failing check
is reported, not worked around.

## Writing

No em dashes. An estimate is called an estimate. A claim about what runs is
backed by a test or a logged run.
