#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DECK="${1:-$ROOT/tests/fixtures/linux-ui/deck}"
ARTIFACTS="${MANIMBLE_UI_ARTIFACTS:-$(mktemp -d "${TMPDIR:-/tmp}/manimble-ui-smoke.XXXXXX")}"
mkdir -p "$ARTIFACTS"
LOG="$ARTIFACTS/app.log"
APP_PID=""
XVFB_PID=""
TEST_DECK="$ARTIFACTS/deck"

if ! command -v xdotool >/dev/null 2>&1 || { ! command -v xwd >/dev/null 2>&1 && ! command -v import >/dev/null 2>&1; }; then
  echo "The Linux UI smoke test needs xdotool and either xwd or ImageMagick's import." >&2
  exit 2
fi

cleanup() {
  if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID"
    wait "$APP_PID" || true
  fi
  if [[ -n "$XVFB_PID" ]] && kill -0 "$XVFB_PID" 2>/dev/null; then
    kill "$XVFB_PID"
    wait "$XVFB_PID" || true
  fi
}
trap cleanup EXIT

if [[ -z "${DISPLAY:-}" ]]; then
  if ! command -v Xvfb >/dev/null 2>&1; then
    echo "No X display is active; install Xvfb or run this test under xvfb-run." >&2
    exit 2
  fi
  DISPLAY_FILE="$ARTIFACTS/display"
  Xvfb -displayfd 3 -screen 0 1280x1024x24 3>"$DISPLAY_FILE" >"$ARTIFACTS/xvfb.log" 2>&1 &
  XVFB_PID=$!
  DISPLAY_NUMBER=""
  for _ in $(seq 1 50); do
    DISPLAY_NUMBER="$(cat "$DISPLAY_FILE")"
    if [[ -n "$DISPLAY_NUMBER" ]] && DISPLAY=":$DISPLAY_NUMBER" xdotool getdisplaygeometry >/dev/null 2>&1; then
      export DISPLAY=":$DISPLAY_NUMBER"
      break
    fi
    sleep 0.1
  done
  if [[ -z "${DISPLAY:-}" ]]; then
    echo "Xvfb did not start. Log:" >&2
    cat "$ARTIFACTS/xvfb.log" >&2
    exit 1
  fi
fi

capture_screen() {
  if command -v xwd >/dev/null 2>&1; then
    xwd -root -silent -out "$1.xwd"
  else
    import -window root "$1.png"
  fi
}

cp -a "$DECK" "$TEST_DECK"

XDG_DATA_HOME="$ARTIFACTS/xdg" XDG_CACHE_HOME="$ARTIFACTS/cache" \
  manimble-linux "$TEST_DECK" >"$LOG" 2>&1 &
APP_PID=$!

window=""
rendered=""
for _ in $(seq 1 240); do
  window="$(xdotool search --onlyvisible --name '^Manimble' 2>/dev/null | head -n 1 || true)"
  rendered="$(find "$ARTIFACTS/cache/manimble/render" -type f -path '*/Welcome/*/stop0.png' -print -quit 2>/dev/null || true)"
  if [[ -n "$window" && -n "$rendered" ]] && xdotool getwindowname "$window" | grep -q 'Welcome'; then
    break
  fi
  sleep 0.5
done
if [[ -z "$window" || -z "$rendered" ]] || ! xdotool getwindowname "$window" | grep -q 'Welcome'; then
  echo "Manimble did not render the first slide. App log:" >&2
  cat "$LOG" >&2
  exit 1
fi
capture_screen "$ARTIFACTS/welcome"

xdotool windowfocus --sync "$window"
xdotool mousemove --window "$window" 650 650 click 1
xdotool key --clearmodifiers ctrl+a
xdotool type --clearmodifiers --delay 1 "class Welcome(Deck):"
xdotool key Return
xdotool type --clearmodifiers --delay 1 "    def construct(self): self.add(Text('X11 smoke edited'))"
xdotool key ctrl+Return
WORKING_SOURCE=""
for _ in $(seq 1 120); do
  WORKING_SOURCE="$(find "$ARTIFACTS/xdg/manimble/work" -path '*/deck/slides.py' -type f -print -quit 2>/dev/null || true)"
  if [[ -n "$WORKING_SOURCE" ]] && grep -q 'X11 smoke edited' "$WORKING_SOURCE"; then
    break
  fi
  sleep 0.25
done
if [[ -z "$WORKING_SOURCE" ]] || ! grep -q 'X11 smoke edited' "$WORKING_SOURCE"; then
  echo "Source editing was not applied through the UI. App log:" >&2
  cat "$LOG" >&2
  exit 1
fi
sleep 3
for _ in $(seq 1 120); do
  if xdotool getwindowname "$window" | grep -q '\*'; then
    break
  fi
  sleep 0.25
done
if ! xdotool getwindowname "$window" | grep -q '\*'; then
  echo "The UI did not acknowledge the source edit." >&2
  exit 1
fi
xdotool key ctrl+s
for _ in $(seq 1 120); do
  if grep -q 'X11 smoke edited' "$TEST_DECK/slides.py" && ! xdotool getwindowname "$window" | grep -q '\*'; then
    break
  fi
  sleep 0.25
done
if ! grep -q 'X11 smoke edited' "$TEST_DECK/slides.py" || xdotool getwindowname "$window" | grep -q '\*'; then
  echo "Save did not copy the edited source back to the deck." >&2
  echo "Window title: $(xdotool getwindowname "$window")" >&2
  capture_screen "$ARTIFACTS/save-failed"
  cat "$LOG" >&2
  exit 1
fi

xdotool mousemove --window "$window" 50 95 click 1
xdotool key --clearmodifiers Down
for _ in $(seq 1 120); do
  if xdotool getwindowname "$window" | grep -q 'Shapes'; then
    break
  fi
  sleep 0.25
done
if ! xdotool getwindowname "$window" | grep -q 'Shapes'; then
  echo "Keyboard navigation did not select the next slide." >&2
  exit 1
fi

xdotool windowsize "$window" 900 620
sleep 1
capture_screen "$ARTIFACTS/shapes-resized"
test -s "$ARTIFACTS"/welcome.*
test -s "$ARTIFACTS"/shapes-resized.*
echo "Headless UI flow passed; inspect screenshots in $ARTIFACTS"
