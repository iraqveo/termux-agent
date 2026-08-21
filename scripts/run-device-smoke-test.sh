#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

REPO_URL="${TERMUX_AGENT_REPO_URL:-https://github.com/iraqveo/termux-agent.git}"
TARGET_DIR="${TERMUX_AGENT_DIR:-${HOME}/termux-agent}"

command -v pkg >/dev/null 2>&1 || { echo 'This script must run inside Termux.' >&2; exit 2; }
pkg install -y git python

if [[ -d "$TARGET_DIR/.git" ]]; then
  git -C "$TARGET_DIR" fetch origin main
  git -C "$TARGET_DIR" checkout main
  git -C "$TARGET_DIR" reset --hard origin/main
else
  git clone --branch main "$REPO_URL" "$TARGET_DIR"
fi

cd "$TARGET_DIR"
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python scripts/device_smoke_test.py --root "$TARGET_DIR"
