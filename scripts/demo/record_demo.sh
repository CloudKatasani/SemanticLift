#!/usr/bin/env bash
# Record the demo walkthrough video shown on the "Demo walkthrough" page.
# Needs: the built UI (ui/dist), Python deps, Node with Playwright and Chromium, ffmpeg with libx264.
#   scripts/demo/record_demo.sh   -> ui/public/demo/{semanticlift-demo.mp4, poster.jpg, chapters.json}
# Then rebuild the UI (cd ui && npm run build) so the files are served.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT="${PORT:-8799}"
WORK="$(mktemp -d)"
DEST=ui/public/demo
mkdir -p "$DEST"

SEMLIFT_HOME="$WORK/home" python -m uvicorn semlift.api.app:app --port "$PORT" --log-level warning &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true; rm -rf "$WORK"' EXIT
for _ in $(seq 1 40); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.5; done

BASE="http://127.0.0.1:$PORT" OUT_DIR="$WORK/out" node scripts/demo/record_demo.mjs

ffmpeg -y -loglevel error -i "$WORK/out/semanticlift-demo.webm" -c:v libx264 -preset slow -crf 28 -pix_fmt yuv420p \
  -movflags +faststart -an "$DEST/semanticlift-demo.mp4"
ffmpeg -y -loglevel error -ss 3 -i "$DEST/semanticlift-demo.mp4" -frames:v 1 -q:v 4 "$DEST/poster.jpg"
cp "$WORK/out/chapters.json" "$DEST/chapters.json"
ls -lh "$DEST"
