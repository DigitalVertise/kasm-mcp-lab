#!/usr/bin/env bash
# Runs after KasmVNC starts. Creates a desktop shortcut to the shared folder.
set -u
export DISPLAY=:1
until xdpyinfo >/dev/null 2>&1; do sleep 1; done

mkdir -p "$HOME/Desktop"
ln -sfn "$HOME/shared" "$HOME/Desktop/shared"

# Kasm restarts custom_startup.sh when it exits, so stay alive.
sleep infinity
