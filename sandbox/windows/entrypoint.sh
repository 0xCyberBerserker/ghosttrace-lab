#!/bin/sh
set -eu

CREDENTIALS_DIR="${WINDOWS_SANDBOX_CREDENTIALS_DIR:-/run/ghosttrace-credentials}"
CREDENTIALS_FILE="${WINDOWS_SANDBOX_CREDENTIALS_FILE:-$CREDENTIALS_DIR/windows-sandbox.env}"
DEFAULT_USERNAME="${WINDOWS_SANDBOX_USERNAME:-Docker}"

mkdir -p "$CREDENTIALS_DIR"

if [ -f "$CREDENTIALS_FILE" ]; then
  # shellcheck disable=SC1090
  . "$CREDENTIALS_FILE"
fi

USERNAME="${USERNAME:-$DEFAULT_USERNAME}"
PASSWORD="${PASSWORD:-}"

if [ -z "$PASSWORD" ]; then
  PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"
fi

cat >"$CREDENTIALS_FILE" <<EOF
# Auto-generated Windows sandbox credentials for the local lab.
USERNAME=$USERNAME
PASSWORD=$PASSWORD
EOF

chmod 600 "$CREDENTIALS_FILE" 2>/dev/null || true

export USERNAME
export PASSWORD

exec /run/entry.sh
