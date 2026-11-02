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
{
  echo "# Nightly run $STAMP"
  echo
  echo "Started $(date '+%Y-%m-%d %H:%M:%S %Z')"
  # the Mac awake for the run; the screen may be dark
  caffeinate -dimsu -w $$ &
  # Logic open on the fixed session: opened if it is not running, the session opened if another is in front
  if ! pgrep -x "Logic Pro" >/dev/null; then
    echo "Logic was closed: opening it with the session"
    open -a "Logic Pro" "$SESSION"
  else
    FRONT=$(osascript -e 'tell application "System Events" to tell process "Logic Pro" to get name of windows' 2>/dev/null)
    case "$FRONT" in
      *"aguacero [INST] 99 bpm 2 2026-11-02"*) echo "the session is open" ;;
      *) echo "another session is open ($FRONT); opening the fixed one"; open -a "Logic Pro" "$SESSION" ;;
    esac
  fi
  for i in $(seq 1 60); do
    sleep 3
    N=$(osascript -e 'tell application "System Events" to tell process "Logic Pro" to get name of windows' 2>/dev/null)
    case "$N" in *"aguacero [INST] 99 bpm 2 2026-11-02"*" - Tracks"*) echo "Tracks window up after $((i*3)) s"; break ;; esac
  done
  # yesterday's prints set aside so the run prints fresh
  for f in "$BOUNCES/$SONG - mix $STAMP.wav" "$BOUNCES/$SONG - master $STAMP.wav" "$BOUNCES/$SONG - master v2 $STAMP.wav" "$BOUNCES/$SONG - master v3 $STAMP.wav"; do
    [ -f "$f" ] && mv "$f" "${f%.wav} (before the nightly).wav"
  done
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
