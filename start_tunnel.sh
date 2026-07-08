#!/data/data/com.termux/files/usr/bin/bash
# Start the Termux listener and a Cloudflare quick tunnel.
# Prints the public URL Render needs as SCRAPER_URL.
#
# Prereqs (run once):
#   pkg install cloudflared   # or download from https://github.com/cloudflare/cloudflared/releases
#   pip install -r requirements.txt
#
# Usage:
#   INGEST_TOKEN=... ./start_tunnel.sh
#
# Or with ngrok instead of cloudflared:
#   TUNNEL=ngrok ./start_tunnel.sh
#

set -e
cd "$(dirname "$0")"

: "${INGEST_TOKEN:?INGEST_TOKEN must be set}"
TUNNEL="${TUNNEL:-cloudflared}"
PORT="${PORT:-5000}"

echo "==> starting termux_listener on :$PORT"
INGEST_TOKEN="$INGEST_TOKEN" PORT="$PORT" python3 termux_listener.py &
LISTENER_PID=$!
trap "kill $LISTENER_PID 2>/dev/null" EXIT

sleep 2

if [ "$TUNNEL" = "ngrok" ]; then
  echo "==> starting ngrok tunnel"
  ngrok http "$PORT" --log=stdout 2>&1 | tee /tmp/ngrok.log &
  TUNNEL_PID=$!
  sleep 5
  URL=$(grep -oE 'https://[a-z0-9-]+\.ngrok[^ ]*' /tmp/ngrok.log | head -1)
else
  echo "==> starting cloudflared quick tunnel"
  cloudflared tunnel --url "http://localhost:$PORT" --logfile /tmp/cf.log 2>/dev/null &
  TUNNEL_PID=$!
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 2
    URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log 2>/dev/null | head -1)
    [ -n "$URL" ] && break
  done
fi

if [ -z "$URL" ]; then
  echo "!! tunnel didn't come up. check /tmp/cf.log or /tmp/ngrok.log"
  wait
  exit 1
fi

echo
echo "================================================================"
echo "  PUBLIC URL:  $URL"
echo "  Set this on Render as:  SCRAPER_URL=$URL"
echo "  INGEST_TOKEN:  ${INGEST_TOKEN:0:8}..."
echo "================================================================"
echo
echo "test:"
echo "  curl -H 'Authorization: Bearer $INGEST_TOKEN' $URL/health"
echo

# Keep both alive
wait $LISTENER_PID $TUNNEL_PID 2>/dev/null
