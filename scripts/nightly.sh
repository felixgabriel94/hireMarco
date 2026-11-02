#!/bin/zsh
# Marco's nightly run: the master job on a fixed session, so breakage shows in the morning before the Owner does.
# Loaded by launchd (com.hiremarco.nightly) at 03:00; runs by hand as scripts/nightly.sh. Writes one report per
# night to ~/Music/hireMarco Bounces/nightly/<date>.md with the run's last lines and the pass/fail verdict.
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SESSION="$HOME/Music/Logic/hireMarco Sessions/aguacero [INST] 99 bpm 2 2026-11-02.logicx"
SONG="aguacero"
END_BAR=90
TRACK="PROD"
BOUNCES="$HOME/Music/hireMarco Bounces/scratch"
REPORTS="$HOME/Music/hireMarco Bounces/nightly"
REPO="$HOME/Code/hiremarco"
STAMP="$(date +%Y-%m-%d)"
mkdir -p "$REPORTS"
LOG="$REPORTS/$STAMP.log"
REPORT="$REPORTS/$STAMP.md"
skip() {
  # the run does not happen tonight; the report says why, and nothing on the Mac is touched
  echo
  echo "**SKIPPED**: $1"
  exit 0
}
{
  echo "# Nightly run $STAMP"
  echo
  echo "Started $(date '+%Y-%m-%d %H:%M:%S %Z')"
  # the rules the host's world asked for (2026-11-02): never after a late wake, never on battery, never while the
  # screen is locked or Marco or the Owner is in Logic, never a restart of anything
  HOUR=$(date +%H)
  [ "$HOUR" -ge 5 ] && [ "$HOUR" -lt 23 ] && skip "started at ${HOUR}h, the Mac must have slept through 3 am; no run in the day"
  pmset -g batt 2>/dev/null | grep -q "Battery Power" && skip "the Mac is on battery"
  LOCKED=$(python3 -c 'import Quartz; d = Quartz.CGSessionCopyCurrentDictionary(); print(1 if d and d.get("CGSSessionScreenIsLocked") else 0)' 2>/dev/null)
  [ "$LOCKED" = "1" ] && skip "the screen is locked; Marco's hands need an unlocked session"
  pgrep -f "marco (master|organize|taste|mix)" >/dev/null && skip "Marco is already in Logic (a job is running)"
  if pgrep -x "Logic Pro" >/dev/null; then
    FRONT=$(osascript -e 'tell application "System Events" to tell process "Logic Pro" to get name of windows' 2>/dev/null)
    case "$FRONT" in
      *"aguacero [INST] 99 bpm 2 2026-11-02"*) echo "the session is open" ;;
      *) skip "Logic is open on another session ($FRONT); it may be the Owner's work" ;;
    esac
  else
    echo "Logic was closed: opening it with the session"
    open -a "Logic Pro" "$SESSION"
  fi
  # the Mac awake for the run; the screen may be dark
  caffeinate -dimsu -w $$ &
  for i in $(seq 1 60); do
    sleep 3
    N=$(osascript -e 'tell application "System Events" to tell process "Logic Pro" to get name of windows' 2>/dev/null)
    case "$N" in *"aguacero [INST] 99 bpm 2 2026-11-02"*" - Tracks"*) echo "Tracks window up after $((i*3)) s"; break ;; esac
  done
  # today's prints set aside so the run prints fresh, and only the last three nights' prints stay in the folder:
  # older ones move to nightly/older (moved, never deleted; a delete is the Owner's line). 70 GB free on this Mac.
  for f in "$BOUNCES/$SONG - mix $STAMP.wav" "$BOUNCES/$SONG - master $STAMP.wav" "$BOUNCES/$SONG - master v2 $STAMP.wav" "$BOUNCES/$SONG - master v3 $STAMP.wav"; do
    [ -f "$f" ] && mv "$f" "${f%.wav} (before the nightly).wav"
  done
  mkdir -p "$REPORTS/older"
  ls -t "$BOUNCES"/"$SONG"*" (before the nightly).wav" 2>/dev/null | tail -n +10 | while IFS= read -r old; do mv "$old" "$REPORTS/older/"; done
  cd "$REPO" || exit 1
  START=$(date +%s)
  PYTHONUNBUFFERED=1 uv run marco master --song "$SONG" --end-bar "$END_BAR" --track "$TRACK" --bounces "$BOUNCES" > "$LOG" 2>&1
  RC=$?
  echo
  echo "Finished $(date '+%Y-%m-%d %H:%M:%S %Z') after $(( $(date +%s) - START )) s, exit $RC"
  echo
  if [ "$RC" -eq 0 ]; then echo "**PASS**"; else echo "**FAIL** (exit $RC)"; fi
  echo
  echo '```'
  tail -14 "$LOG" | cut -c1-200
  echo '```'
} > "$REPORT" 2>&1
exit 0
