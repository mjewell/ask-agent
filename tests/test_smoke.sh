#!/usr/bin/env sh
set -eu
exec python3 "$(dirname "$0")/test_runner.py" "$@"
