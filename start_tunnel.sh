#!/data/data/com.termux/files/usr/bin/bash
# Start the Termux listener + a Cloudflare quick tunnel.
# Persists the URL to $HOME/.tunnel_url so other scripts can read it.
# Auto-restarts the tunnel on crash.
#
# Prereqs (run once):
#   pkg install cloudflared
#   pip install -r requirements.txt
#
# Usage:
#   INGEST_TOKEN=... ./start_tunnel.sh
#
# If the tunnel URL changes, paste the new one into Render's SCRAPER_URL env.
# To get the current URL later: cat $HOME/.tunnel_url
#
# Optional: set RENDER_API_KEY + RENDER_SERVICE_ID to auto-update SCRAPER_URL
#   when the URL changes (no manual edit needed).
#

set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.tmp"

: "${INGEST_TOKEN:?INGEST_TOKEN must be set}"
TUNNEL="${TUNNEL:-cloudflared}"
PORT="${PORT:-5000}"
URL_FILE="$HOME/.tunnel_url"
LOG="$HOME/.tmp/tunnel.log"

# Kill any previous instances so we get a clean start
pkill -9 -f "termux_listener.py" 2>/dev/null || true
pkill -9 -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# Persist INGEST_TOKEN for the listener + render-updater subshells
export INGEST_TOKEN

echo "==> starting termux_listener on :$PORT"
python3 termux_listener.py >> "$LOG" 2>&1 &
LISTENER_PID=$!
echo "  listener pid=$LISTENER_PID"

sleep 2

if [ "$TUNNEL" = "ngrok" ]; then
  echo "==> starting ngrok tunnel"
  ngrok http "$PORT" --log "$HOME/.tmp/ngrok.log" --log-format json 2>>"$LOG" &
  TUNNEL_PID=$!
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    URL=$(grep -oE '"url":"https://[a-z0-9-]+\.ngrok[^"]+"' "$HOME/.tmp/ngrok.log" 2>/dev/null | head -1 | sed 's/.*"https/https/;s/".*//')
    [ -n "$URL" ] && break
  done
else
  echo "==> starting cloudflared quick tunnel"
  # --edge-ip-version 4 avoids the IPv6 path that fails on some mobile networks
  cloudflared tunnel --url "http://localhost:$PORT" --edge-ip-version 4 --no-autoupdate >> "$LOG" 2>&1 &
  TUNNEL_PID=$!
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    sleep 2
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -1)
    [ -n "$URL" ] && break
  done
fi

if [ -z "$URL" ]; then
  echo "!! tunnel didn't come up. tail of $LOG:"
  tail -30 "$LOG"
  kill $LISTENER_PID $TUNNEL_PID 2>/dev/null || true
  exit 1
fi

# Persist URL + detect change
OLD_URL=""
[ -f "$URL_FILE" ] && OLD_URL=$(cat "$URL_FILE")
echo "$URL" > "$URL_FILE"

echo
echo "================================================================"
echo "  PUBLIC URL:  $URL"
if [ "$OLD_URL" != "$URL" ] && [ -n "$OLD_URL" ]; then
  echo "  (was: $OLD_URL — URL changed, update Render SCRAPER_URL)"
fi
echo "  Persisted to: $URL_FILE"
echo "  INGEST_TOKEN: ${INGEST_TOKEN:0:8}..."
echo "================================================================"
echo
echo "test:"
echo "  curl -H 'Authorization: Bearer ***' $URL/health"
echo

# Optionally auto-update Render if both env vars are set
if [ -n "${RENDER_API_KEY:-}" ] && [ -n "${RENDER_SERVICE_ID:-}" ]; then
  if [ "$OLD_URL" != "$URL" ] && [ -n "$OLD_URL" ]; then
    echo "==> auto-updating Render SCRAPER_URL via API"
    curl -s -X PATCH \
      -H "Authorization: Bearer $RENDER_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"envVars\":[{\"key\":\"SCRAPER_URL\",\"value\":\"$URL\"}]}" \
      "https://api.render.com/v1/services/$RENDER_SERVICE_ID/env-vars" \
      | head -c 200
    echo
  fi
fi

echo "press Ctrl-C to stop"
trap "kill $LISTENER_PID $TUNNEL_PID 2>/dev/null || true" EXIT
wait $LISTENER_PID $TUNNEL_PID 2>/dev/null || true
echo "==> listener or tunnel died. tail of $LOG:"
tail -20 "$LOG"
