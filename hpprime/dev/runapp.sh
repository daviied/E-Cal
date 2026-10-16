#!/usr/bin/env bash
# Build the CalcVault app, install it alone into the emulator, compile its
# program (Program Catalog > Edit > Check), and start it from the Apps screen.
#   runapp.sh OUT.png
set -e
HPK=${HPK:-/c/Users/nyg4/ref/hpk}
DIR=$(cd "$(dirname "$0")" && pwd)
D="python $DIR/emudrive.py"
EMU="$HOME/Documents/HP Prime/Calculators/Prime"
python "$DIR/../calc/build.py" >/dev/null
$D close
rm -rf "$EMU/CalcVault.hpappdir" "$EMU"/CV*.hpprgm "$EMU/CALCVAULT.hpprgm"
python "$HPK/hpprime.py" install "$DIR/../calc/CalcVault.hpappdir" >/dev/null
$D launch
$D place
# The app's program is the only one, so it is the first row.
$D keys ESC CLICK:124,882 CLICK:186,882 WAIT:1 CLICK:200,303 WAIT:0.5 CLICK:127,503 WAIT:2 CLICK:393,503 WAIT:2
$D lcd "${1%.png}.check.png"
$D keys CLICK:393,503 WAIT:0.5 ESC WAIT:0.5 ESC CLICK:124,557 WAIT:1.5 CLICK:393,503 WAIT:3
$D lcd "$1"
