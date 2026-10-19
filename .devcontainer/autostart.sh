#!/usr/bin/env bash
# Starts the lab automatically every time the Codespace starts, so nothing
# has to be typed (made for using the lab from a phone).
# Progress and login details are written to LOGIN.txt in the repo root.
set -uo pipefail
cd "$(dirname "$0")/.."

LOGIN=LOGIN.txt
note() { printf '%s\n' "$@" >"$LOGIN"; }

note "Lab is starting... (first start builds the desktops: about 10-15 minutes)" \
     "This file updates itself when it's ready. Re-open it to refresh."

# Wait for docker-in-docker to come up.
for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
if ! docker info >/dev/null 2>&1; then
  sudo service docker start >/dev/null 2>&1 || true
  sleep 5
fi

# Build only the first time; reuse the images on later starts.
args=()
docker image inspect "kasm-mcp/linux:${KASM_TAG:-1.18.0}" >/dev/null 2>&1 && args+=(--no-build)

if ./setup.sh "${args[@]}" >/tmp/lab-setup.log 2>&1; then status="READY"; else status="STARTED WITH WARNINGS (details: /tmp/lab-setup.log)"; fi

pw=$(grep -E '^VNC_PW=' .env | cut -d= -f2-)
base="https://${CODESPACE_NAME:-localhost}"
dom="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"

note "Lab status: $status" \
     "" \
     "Linux desktop:   ${base}-6901.${dom}" \
     "Windows apps:    ${base}-6902.${dom}" \
     "macOS-style:     ${base}-6903.${dom}" \
     "Portal:          ${base}-3000.${dom}" \
     "" \
     "Username: kasm_user" \
     "Password: ${pw}" \
     "" \
     "Tip: stop the Codespace when you're done to save your free hours."
