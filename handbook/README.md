# Marco's handbook

What Marco the mixing and mastering engineer knows, written to be checked.
Three kinds of file, kept apart on purpose:

- `roles.md`: the two jobs, mixing and mastering, as two intentions and two
  ways of thinking. The artist's standing rules live here and in the code's
  rulebooks (`src/hiremarco/master/rules.py`, `src/hiremarco/mix/rules.py`);
  a rule is never dressed as a sourced claim.
- `claims/R-AUD-NNNN.md`: one sourced claim per file, in the entry shape of
  the ecosystem's Library (header fields, then Claim, Covers, Does not
  cover, Sources with the sentence seen, word for word, and the date read).
  A claim carries no song name, no session and no taste note. The lane
  `audio engineering` is provisional: it opens in the Library only by a
  decision record, and these IDs move there intact after that.
- `situations/*.md`: what Marco looks for, the threshold that makes it a
  finding, why it matters (by claim ID), when the move applies and when it
  does not, the move with the plug-in and the control in real units, the
  expected effect, and how the print is verified. The audit's findings pick
  the situations; the plan reads only those, cites their IDs in its reasons,
  and the running log shows the citation.
- `plugins/*.md`: one profile per plug-in the artist owns, every control in
  the units the plug-in prints, every shape and mode with when it is the
  right one, from the manual installed on this Mac for the version he owns.

Source grades follow the Library: primary (the standard or the maker's own
manual), institutional (a platform's or vendor's published page),
practitioner (a working engineer's published words), popular (a magazine or
blog; never the source of a number). Every source line carries the date it
was read and where. A claim whose source cannot be re-opened is marked
stale, not deleted.

How Marco reads it: `src/hiremarco/master/handbook.py` loads the situations
whose triggers match the audit (a finding's words, or a measure against a
threshold) and hands them to the plan with their IDs; the rulebook stays the
rules. One shoe size does not fit all: a situation's numbers are the start of
the reasoning, and the reason written in the log names the number measured
on this track.
