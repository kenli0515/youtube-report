#!/usr/bin/env bash
# Consumes requests/*.json: {"url": "https://www.youtube.com/watch?v=..."}
#
# Each request becomes work/<id>/ with the transcript, paragraphs and meta.json. The request file
# is deleted afterwards so the queue stays empty; a later run with nothing pending does nothing.
set -u

shopt -s nullglob
pending=(requests/*.json)
if [ ${#pending[@]} -eq 0 ]; then
  echo "no pending requests"
  exit 0
fi

for request in "${pending[@]}"; do
  url=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('url',''))" "$request")
  if [ -z "$url" ]; then
    echo "skipping $request: no url"
    continue
  fi
  id=$(python3 -c "
import sys, urllib.parse
u = urllib.parse.urlparse(sys.argv[1])
q = urllib.parse.parse_qs(u.query)
print(q.get('v', [u.path.rstrip('/').split('/')[-1]])[0])
" "$url")
  echo "=== $id <- $url ==="
  mkdir -p "work/$id"
  echo "$url" >"work/$id/source.txt"
  if python3 tools/fetch_transcript.py "$url" --out "work/$id" 2>&1 | tail -20; then
    rm -f "$request"
  else
    echo "fetch failed for $id"
  fi
done
