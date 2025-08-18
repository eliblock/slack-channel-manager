#!/usr/bin/env bash

set -euo pipefail

# Find the directory of this script in the repo.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$SCRIPT_DIR/.."

stderr_with_timestamp() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $*" >&2
}

uv_run_command() {
  "$1" run manager sort | perl -pe 'use POSIX strftime; $_ = strftime("%Y-%m-%d %H:%M:%S", localtime) . " - $_"'
}

# Use `uv` if it can be found
if command -v uv &> /dev/null; then
  uv_run_command uv
# Brew installs to different places on apple silicon vs. intel, and these
# directories may not be on the path. Check the most likely locations:
elif [ -x /opt/homebrew/bin/uv ]; then # apple silicon
  uv_run_command /opt/homebrew/bin/uv
elif [ -x /usr/local/bin/uv ]; then # intel
  uv_run_command /usr/local/bin/uv
else
  stderr_with_timestamp "Could not find uv. Install it!" >&2
  exit 1
fi
