#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# This script is intentionally explicit and idempotent. It does not run as root.
command -v pkg >/dev/null 2>&1 || { echo 'Run this script inside Termux.' >&2; exit 1; }

pkg update -y
pkg install -y python git ripgrep proot-distro termux-api cmake clang make
termux-setup-storage || true

if ! proot-distro list | grep -q '^debian'; then
  proot-distro install debian
fi

python -m venv "${HOME}/.termux-agent-venv"
# shellcheck disable=SC1091
. "${HOME}/.termux-agent-venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e "${TERMUX_AGENT_ROOT:-.}"

if command -v termux-notification >/dev/null 2>&1; then
  termux-notification --title 'Termux Agent' --content 'Bootstrap completed'
else
  echo 'Termux:API is not available; notifications remain disabled.'
fi

echo 'Bootstrap completed. Use: termux-agent plan --root . --task "inspect project"'
