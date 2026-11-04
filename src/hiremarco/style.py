"""How Marco writes to the artist on WhatsApp (Owner 2026-11-02): proper capitals and punctuation, warm and short.
Capitals are his brand, like his tie and his logo, so nothing here changes a letter's case except the one name below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, timedelta

NAME_RULE = "Spell hireMarco exactly that way, with that capital M and a small h, even at the start of a sentence."
_NAME = re.compile(r"(?<![\w./@-])hiremarco(?!\.\w|[\w@-])", re.I)


# Owner 2026-11-02: a time he writes is exact, because "eight" could be morning or night: digits with am or pm and no
# space (8pm, 8:30pm, 12:30am, 12:35pm), and exactly 12:00 is noon or midnight. Other numbers can stay spelled out.
TIME_RULE = ("Write every time with digits and am or pm, no space: 8pm, 8:30pm, 12:30am, 12:35pm. Exactly 12:00 is noon or "
             "midnight, never twelve or 12pm. Never spell a time out. Other numbers can stay spelled out.")
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12}
MINUTES = {"oh five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25, "thirty": 30, "thirty five": 35,
           "forty": 40, "forty five": 45, "fifty": 50, "fifty five": 55}
_NUMBER = "|".join(NUMBERS)
_MINUTE = "|".join(sorted((m.replace(" ", "[ -]") for m in MINUTES), key=len, reverse=True))
_DIGITS = re.compile(r"(?<![\w:.])(\d{1,2})(?::(\d{2}))?\s*([ap])(?:\.m\.|\.?m\b)(?!\s+i\b)", re.I)
_SPELLED_PM = re.compile(rf"\b({_NUMBER})(?:[ -]({_MINUTE}))?\s+p(?:\.m\.|\.?m\b)", re.I)
_SPELLED_AM = re.compile(rf"(\bat\s+)({_NUMBER})(?:[ -]({_MINUTE}))?\s+a(?:\.m\.|\.?m\b)", re.I)
_TWELVE = re.compile(r"\b(?:12|twelve)\s+(noon|midnight)\b", re.I)
_BEFORE_A_TIME = re.compile(r"(?:\b(?:at|by|from|to|until|till|around|before|after)|day,?)\s*$", re.I)
_QUOTED = re.compile(r"(\"[^\"]*\"|“[^”]*”)")


def clock_time(hour: int, minute: int = 0) -> str:
    """A time as Marco writes it, from a 24-hour hour and a minute."""
    if minute == 0 and hour % 12 == 0:
        return "noon" if hour == 12 else "midnight"
    shown = hour % 12 or 12
    return f"{shown}{f':{minute:02d}' if minute else ''}{'am' if hour < 12 else 'pm'}"


def _hour24(hour: int, half: str) -> int:
    return hour % 12 + (12 if half.lower() == "p" else 0)


def _minute_of(words: str | None) -> int:
    return MINUTES[re.sub(r"[ -]+", " ", words.lower())] if words else 0


def written_times(text: str) -> str:
    """Times in Marco's outgoing words put in the exact form. It touches only what already says am or pm, so a count, a
    bar number or a BPM can't change; words inside quotes stay, since a subject or a title is someone else's. A bare
    "12 pm" becomes noon only after "at", "by", a weekday and the like: "12 AM" alone can be a song. A spelled time with
    no am or pm stays as it is: the guard can't know which, and that is what the writers' rule and clock_time are for."""
    def digits(m: re.Match) -> str:
        hour, minute = int(m[1]), int(m[2] or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return m[0]
        whole = clock_time(_hour24(hour, m[3]), minute)
        if whole in ("noon", "midnight") and not _BEFORE_A_TIME.search(m.string[:m.start()]):
            return f"12{m[3].lower()}m"
        return whole

    def spelled_pm(m: re.Match) -> str:
        return clock_time(_hour24(NUMBERS[m[1].lower()], "p"), _minute_of(m[2]))

    def spelled_am(m: re.Match) -> str:
        return m[1] + clock_time(_hour24(NUMBERS[m[2].lower()], "a"), _minute_of(m[3]))

    def plain_part(part: str) -> str:
        part = _TWELVE.sub(lambda m: m[1].lower(), part)
        return _DIGITS.sub(digits, _SPELLED_AM.sub(spelled_am, _SPELLED_PM.sub(spelled_pm, part)))

    return "".join(piece if i % 2 else plain_part(piece) for i, piece in enumerate(_QUOTED.split(text or "")))


def times_settled_on(text: str, pm: bool) -> str:
    """What a call settled, where a time needs no guessing: "at nine thirty" or "at 9:30" after a booking for the evening
    is 9:30pm. Only straight after "at", and only with no am or pm of its own."""
    half = "p" if pm else "a"
    text = written_times(text)

    def spelled(m: re.Match) -> str:
        return m[1] + clock_time(_hour24(NUMBERS[m[2].lower()], half), _minute_of(m[3]))

    def digits(m: re.Match) -> str:
        hour, minute = int(m[2]), int(m[3] or 0)
        return m[1] + clock_time(_hour24(hour, half), minute) if 1 <= hour <= 12 and minute < 60 else m[0]

    text = re.sub(rf"(\bat\s+)({_NUMBER})(?:[ -]({_MINUTE}))?\b", spelled, text, flags=re.I)
    return re.sub(r"(\bat\s+)(\d{1,2})(?::(\d{2}))?\b(?![:\w]|\s*[ap]\.?m)", digits, text, flags=re.I)


# Owner 2026-11-02: open days read as a range, not a roll call: a list of every day was clutter on his phone.
DAYS_RULE = ("Write a day as weekday, month and ordinal: Tuesday, November 3rd. Say days in a row as one range: Tuesday, "
             "November 3rd, to Saturday, November 7th. Separate days: Tuesday, November 3rd, and Thursday, November 5th. "
             "Never list each day of a run, and never say every single day.")
_WEEKDAY = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")
_A_DAY = rf"(?:(?:{_WEEKDAY}),? )?(?:{'|'.join(MONTHS)}) \d{{1,2}}(?:st|nd|rd|th)?\b"
_ONE_DAY = re.compile(rf"(?:({_WEEKDAY}),? )?({'|'.join(MONTHS)}) (\d{{1,2}})")
_DAY_LIST = re.compile(rf"{_A_DAY}(?:(?:, (?:(?:and|or) )?| (?:and|or) ){_A_DAY}){{2,}}")
_EVERY_DAY = re.compile(rf"(?i:every(?: single)? day(?: from| between)?) ({_A_DAY}),? (?i:to|through|until|and) ({_A_DAY})")


def ordinal(n: int) -> str:
    """3rd, 11th, 22nd."""
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def spelled_day(day: date) -> str:
    """A day as Marco writes it: Tuesday, November 3rd."""
    return f"{day.strftime('%A, %B')} {ordinal(day.day)}"


def _runs(days: Iterable[date]) -> list[list[date]]:
    runs: list[list[date]] = []
    for day in sorted(set(days)):
        if runs and day - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


def days_span(days: Iterable[date]) -> str:
    """Days as one phrase, every channel's one way of saying them: days in a row become a range and the rest stand alone.
    Tuesday, November 3rd, to Thursday, November 5th, and Saturday, November 7th."""
    parts = [spelled_day(r[0]) if len(r) == 1 else f"{spelled_day(r[0])}, to {spelled_day(r[-1])}" for r in _runs(days)]
    return ", ".join(parts[:-1]) + ", and " + parts[-1] if len(parts) > 1 else "".join(parts)


def _read_days(text: str, today: date) -> list[date] | None:
    """The days a phrase names, in the year nearest today. None when one can't be a date or its weekday doesn't fit the
    date: a wrong date is not this guard's to tidy up."""
    days = []
    for m in _ONE_DAY.finditer(text):
        try:
            years = [date(today.year + n, MONTHS.index(m[2]) + 1, int(m[3])) for n in (-1, 0, 1)]
        except ValueError:
            return None
        day = min(years, key=lambda d: abs(d - today))
        if m[1] and day.strftime("%A") != m[1]:
            return None
        days.append(day)
    return days


def written_days(text: str, today: date | None = None) -> str:
    """A run of three or more listed days, or "every single day from November 3rd to November 7th", put as a range. It
    reads only full month names; days in another shape stay as they are and the writers' rule is what covers them. Words
    inside quotes stay, as with times."""
    today = today or date.today()

    def listed(m: re.Match) -> str:
        days = _read_days(m[0], today)
        if not days or days != sorted(set(days)) or max(map(len, _runs(days))) < 3:
            return m[0]
        return days_span(days)

    def every(m: re.Match) -> str:
        ends = _read_days(f"{m[1]} {m[2]}", today)
        if not ends or len(ends) != 2 or ends[0] >= ends[1]:
            return m[0]
        return days_span(ends[0] + timedelta(days=n) for n in range((ends[1] - ends[0]).days + 1))

    return "".join(piece if i % 2 else _DAY_LIST.sub(listed, _EVERY_DAY.sub(every, piece))
                   for i, piece in enumerate(_QUOTED.split(text or "")))


# The Owner's name to him (Owner 2026-11-04): FEGA, his artist name, in capitals with no exceptions. "Felix" said to
# him becomes FEGA; "Felix's", "Felix Gabriel", "Felix Betancourt" and an address (felix@) stay as they are, since
# those are about him to others. Calls and bookings for him use "Felix Gabriel" and never pass through here.
OWNER_NAME = "FEGA"
OWNER_NAME_RULE = ("His artist name is FEGA. When you talk or write to him, call him FEGA, always written in capitals "
                   "as FEGA, never Fega or Felix. To anyone else, on a call or a booking, he is Felix Gabriel.")
_FEGA = re.compile(r"\bfega\b", re.I)
_FELIX_TO_HIM = re.compile(r"(?<![@\w.])Felix\b(?!['\u2019]s|\s+(?:Gabriel|Betancourt)\b|@)")


def to_owner(text: str) -> str:
    """What Marco writes or says to the Owner, with his name as he wants it: FEGA, in capitals."""
    return _FEGA.sub(OWNER_NAME, _FELIX_TO_HIM.sub(OWNER_NAME, text or ""))


def written(text: str) -> str:
    """Marco's text as it goes out on WhatsApp: times exact, runs of days as ranges, his company's name as it is
    spelled, and the Owner's name as FEGA, wherever they stand. A link or an address with the name in it stays."""
    return to_owner(_NAME.sub("hireMarco", written_days(written_times(text))))


# Owner 2026-10-31: Marco never shows the client what is under the hood. A text that would name a part of the
# system, a tool, a model or an error goes out as a plain line instead; the raw text goes to the log only.
INTERNAL = re.compile(
    r"\b(critic|gate(?! code)|relay|send switch|idempotenc\w*|refused|webhook|tunnel|elevenlabs|twilio|"
    r"muse (spark|wonder)|model call|traceback|exception|callsid|conv_\w+|end_call|voicemail_detection|skip_turn|"
    r"rules\.md|(the|call|a) brief)\b|\bhttp \d{3}\b", re.I)
PLAIN = "Something didn't go through on my side just now. I'm on it."


def plain(text: str) -> tuple[str, str | None]:
    """The text as it may go to the client, and the raw text when it had to be replaced (for the log only)."""
    return (PLAIN, text) if INTERNAL.search(text or "") else (text, None)
