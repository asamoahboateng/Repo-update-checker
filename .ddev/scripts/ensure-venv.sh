#!/usr/bin/env bash
# Create /opt/venv and (re)install requirements when they change.
set -euo pipefail
cd /var/www/html

VENV=/opt/venv
STAMP="$VENV/.requirements.sha"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating Python venv in $VENV"
  python3 -m venv "$VENV"
fi

want=$(cat requirements.txt requirements-dev.txt | sha256sum | cut -d' ' -f1)
have=$(cat "$STAMP" 2>/dev/null || true)
if [ "$want" != "$have" ]; then
  echo "Installing Python requirements"
  "$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements-dev.txt
  echo "$want" > "$STAMP"
fi
