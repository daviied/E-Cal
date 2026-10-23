#!/usr/bin/env bash
# Build a PPL file, install it into the emulator, compile it there, run its
# entry point from Home and save a picture of the screen.
#   runprobe.sh FILE.txt ENTRY OUT.png [ROW]
# ROW is the program's position in the Program Catalogue (default 2).
set -e
HPK=${HPK:-/c/Users/nyg4/ref/hpk}
SRC=$1; ENTRY=$2; OUT=$3; ROW=${4:-2}
DIR=$(cd "$(dirname "$0")" && pwd)
PRG="${SRC%.txt}.hpprgm"
py -3.14 "$HPK/hpprime.py" lint "$SRC" --quiet
py -3.14 "$HPK/hpprime.py" write "$SRC" -o "$PRG" >/dev/null
py -3.14 "$HPK/hpprime.py" install "$PRG" --restart >/dev/null
D="py -3.14 $DIR/emudrive.py"
$D launch
$D place
# Program Catalogue, tap the program's row (the list wraps, so arrows do not
# reliably reach it), Edit, Check, OK, back to Home.
ROWY=$((270 + 33 + 22 * (ROW - 1)))
$D keys ESC CLICK:124,882 CLICK:186,882 WAIT:1 CLICK:200,$ROWY WAIT:0.5 CLICK:127,503 WAIT:1.5 CLICK:393,503 WAIT:1.5
$D lcd "${OUT%.png}.check.png"
$D keys CLICK:393,503 WAIT:0.5 ESC WAIT:0.5 ESC CLICK:124,603 WAIT:0.5 "$ENTRY" ENTER WAIT:${WAITSECS:-4}
$D lcd "$OUT"
