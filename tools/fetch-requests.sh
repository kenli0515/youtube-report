#!/usr/bin/env bash
# Consumes requests/*.json: {"url": "https://www.youtube.com/watch?v=..."}
#
# Each request becomes work/<id>/ with the transcript, paragraphs and meta.json, and the request
# file is removed so the queue stays empty. A failure is written to work/<id>/error.txt and
# committed, because the submitter's page needs something to show and a runner log is not
# readable from outside.
set -u

shopt -s nullglob
pending=(requests/*.json)
if [ ${#pending[@]} -eq 0 ]; then
  echo "no pending requests"
  exit 0
fi

for request in "${pending[@]}"; do
  url=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('url',''))" "$request" 2>/dev/null || true)
  if [ -z "$url" ]; then
    echo "skipping $request: no usable url"
    rm -f "$request"
    continue
  fi
  id=$(python3 - "$url" <<'PY'
import sys, urllib.parse
u = urllib.parse.urlparse(sys.argv[1])
q = urllib.parse.parse_qs(u.query)
print(q.get("v", [u.path.rstrip("/").split("/")[-1]])[0])
PY
)
  echo "=== $id <- $url ==="
  mkdir -p "work/$id"
  printf '%s\n' "$url" >"work/$id/source.txt"

  log=$(mktemp)
  ok=0
  for attempt in 1 2; do
    # Subtitle endpoints answer 429 when asked too fast, so one retry is worth having.
    if python3 tools/fetch_transcript.py "$url" --out "work/$id" >"$log" 2>&1; then
      ok=1; break
    fi
    echo "attempt $attempt failed for $id"; sleep 10
  done

  if [ "$ok" = 1 ]; then
    rm -f "work/$id/error.txt"
    rm -f "$request"
    echo "ok $id"
  else
    {
      echo "fetch_transcript.py failed for $url"
      echo "runner time: $(date -u '+%Y-%m-%d %H:%M UTC')"
      echo
      tail -40 "$log"
    } >"work/$id/error.txt"
    rm -f "$request"
    echo "FAILED $id"
    tail -40 "$log"
  fi
  rm -f "$log"
done
