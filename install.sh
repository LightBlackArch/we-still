#!/bin/sh
# User install, no sudo. Usage: ./install.sh
set -e
cd "$(dirname "$0")"
missing=""
python3 -c 'import PIL, numpy' 2>/dev/null || missing="$missing python-pillow python-numpy"
command -v ffmpeg >/dev/null || missing="$missing ffmpeg"
if [ -n "$missing" ]; then
  echo "Missing system packages. Install them with:"
  echo "  sudo pacman -S --needed$missing"
  echo "(or let pip fetch Pillow/numpy into your user site below; ffmpeg must come from pacman)"
fi
if command -v pipx >/dev/null; then
  pipx install --force --system-site-packages .
elif command -v pip >/dev/null; then
  pip install --user --break-system-packages .
else
  # no pip/pipx (common on a bare Arch): run straight from this checkout
  mkdir -p "$HOME/.local/bin"
  printf '#!/bin/sh\nPYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m we_still "$@"\n' "$PWD" > "$HOME/.local/bin/we-still"
  chmod +x "$HOME/.local/bin/we-still"
  echo "No pip found: installed a launcher that runs from $PWD (keep this folder)."
fi
echo "Installed. Make sure ~/.local/bin is in PATH, then run: we-still doctor && we-still setup"
