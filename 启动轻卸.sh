#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$APP_DIR/main.py" "$@"
