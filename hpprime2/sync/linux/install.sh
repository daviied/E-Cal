#!/usr/bin/env bash
# Installs the CalcVault sync tool on Linux Mint (or Ubuntu/Debian).
#
#   bash install.sh             install, or update after copying a new version
#   bash install.sh --service   also run live sync in the background whenever
#                               you are logged in (a systemd user service)
#   bash install.sh --remove    take it all out again
#
# What it does, so nothing is a surprise:
#   - copies the tool to ~/.local/share/calcvault-sync, with its own Python
#     environment there (Mint does not allow pip into the system Python)
#   - adds commands calcvault-sync and calcvault-live to ~/.local/bin
#   - adds "CalcVault Sync" and "CalcVault Live Sync" to the applications menu
#   - adds a udev rule (asks for your password once, via sudo) so your user
#     can talk to an HP Prime over USB without root
set -euo pipefail

APP="$HOME/.local/share/calcvault-sync"
BIN="$HOME/.local/bin"
MENU="$HOME/.local/share/applications"
UNIT_DIR="$HOME/.config/systemd/user"
RULE=/etc/udev/rules.d/70-hp-prime.rules
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$HERE/.." && pwd)"          # the sync folder: cvsync/, requirements.txt

say() { printf '\n== %s\n' "$*"; }

if [[ "${1:-}" == "--remove" ]]; then
    systemctl --user disable --now calcvault-live.service 2>/dev/null || true
    rm -f "$UNIT_DIR/calcvault-live.service" "$BIN/calcvault-sync" "$BIN/calcvault-live" \
          "$MENU/calcvault-sync.desktop" "$MENU/calcvault-live.desktop"
    rm -rf "$APP"
    if [[ -f "$RULE" ]]; then sudo rm -f "$RULE" && sudo udevadm control --reload-rules; fi
    echo "Removed. Your settings and backups in ~/.config/CalcVaultSync were kept."
    exit 0
fi

if [[ ! -d "$SRC/cvsync" ]]; then
    echo "Run this from the hpprime/sync/linux folder (cvsync/ was not found next to it)." >&2
    exit 1
fi

say "Checking Python"
if ! command -v python3 >/dev/null; then
    echo "Installing Python 3 (needs your password)"
    sudo apt-get update && sudo apt-get install -y python3
fi
if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    echo "Installing python3-venv (needs your password)"
    sudo apt-get update && sudo apt-get install -y python3-venv
fi
python3 --version

say "Copying the tool to $APP"
mkdir -p "$APP"
rm -rf "$APP/cvsync"
cp -r "$SRC/cvsync" "$SRC/requirements.txt" "$APP/"
find "$APP/cvsync" -name __pycache__ -prune -exec rm -rf {} +

say "Setting up its Python environment"
if [[ ! -x "$APP/venv/bin/python" ]]; then
    python3 -m venv "$APP/venv"
fi
"$APP/venv/bin/python" -m pip install --quiet --upgrade pip
if ! "$APP/venv/bin/python" -m pip install --quiet -r "$APP/requirements.txt"; then
    # No ready-made wheel for this Python: build hidapi, which needs these.
    echo "Building hidapi (needs your password for the build tools)"
    sudo apt-get install -y build-essential python3-dev libusb-1.0-0-dev libudev-dev
    "$APP/venv/bin/python" -m pip install -r "$APP/requirements.txt"
fi

say "Adding commands to $BIN"
mkdir -p "$BIN"
cat > "$BIN/calcvault-sync" <<EOF
#!/usr/bin/env bash
# CalcVault sync: calcvault-sync [sync|live|online|status|login|restore FILE] [options]
cd "$APP" && exec "$APP/venv/bin/python" -m cvsync "\${@:-sync}"
EOF
cat > "$BIN/calcvault-live" <<EOF
#!/usr/bin/env bash
# Keeps CalcVault in sync while the HP Prime is plugged in.
cd "$APP" && exec "$APP/venv/bin/python" -u -m cvsync live "\$@"
EOF
chmod +x "$BIN/calcvault-sync" "$BIN/calcvault-live"

say "Adding menu entries"
mkdir -p "$MENU"
cat > "$MENU/calcvault-sync.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CalcVault Sync
Comment=Sync the HP Prime's CalcVault with the web app once
Exec=bash -c '"$BIN/calcvault-sync" sync; echo; read -rp "Press Enter to close. "'
Terminal=true
Icon=accessories-calculator
Categories=Utility;Education;
EOF
cat > "$MENU/calcvault-live.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CalcVault Live Sync
Comment=Keep the HP Prime's CalcVault in sync while it is plugged in
Exec=bash -c '"$BIN/calcvault-live"; echo; read -rp "Press Enter to close. "'
Terminal=true
Icon=accessories-calculator
Categories=Utility;Education;
EOF
update-desktop-database "$MENU" 2>/dev/null || true

say "Allowing USB access to the HP Prime (udev rule, needs your password)"
sudo tee "$RULE" >/dev/null <<'EOF'
# HP Prime graphing calculator (all generations): readable and writable by
# the person logged in at the desk, for the CalcVault sync tool.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="03f0", ATTRS{idProduct}=="0441|1541|2441", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="03f0", ATTRS{idProduct}=="0441|1541|2441", MODE="0660", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=usb || true

if [[ "${1:-}" == "--service" ]]; then
    say "Running live sync in the background"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/calcvault-live.service" <<EOF
[Unit]
Description=CalcVault live sync for the HP Prime

[Service]
ExecStart=$BIN/calcvault-live
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now calcvault-live.service
    echo "Started. See what it is doing with:  journalctl --user -u calcvault-live -f"
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo; echo "Note: $BIN is not on your PATH yet; log out and back in (Mint adds it then)." ;;
esac

say "Done"
cat <<EOF
Next:
  1. Unplug and replug the calculator (so the new USB rule applies).
  2. Log in once:   calcvault-sync login     (asks for the web address and password)
  3. Sync:          calcvault-sync           or "CalcVault Sync" in the menu
     Live:          calcvault-live           or "CalcVault Live Sync" in the menu
  Status:           calcvault-sync status
EOF
if [[ "${1:-}" != "--service" ]]; then
    echo "  To run live sync in the background at every login: bash install.sh --service"
    echo "  (log in with step 2 first: the background service cannot ask for the password)"
fi
