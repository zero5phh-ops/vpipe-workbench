#!/bin/bash
# Start the vpipe工作台 server if it is not running, then open it in the browser.
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${VPIPE_PORT:-8765}"
WORK="${VPIPE_WORK:-$HOME/vpipe-work}"
mkdir -p "$WORK"
if ! curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/api/config"; then
  nohup /usr/bin/env python3 -I "$DIR/server.py" > "$WORK/workbench-server.log" 2>&1 &
  for i in $(seq 1 20); do
    curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/api/config" && break
    sleep 0.3
  done
fi
open "http://127.0.0.1:$PORT"
