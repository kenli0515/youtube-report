#!/usr/bin/env bash
# Builds a report for every work/<id>/points.json and refreshes the index.
#
# The reports use --embed youtube --still none: the player comes from YouTube and no video is
# downloaded, so this runs happily on a runner whose IP YouTube will not serve video to.
set -u

shopt -s nullglob
built=0
for points in work/*/points.json; do
  id=$(basename "$(dirname "$points")")
  url=$(cat "work/$id/source.txt" 2>/dev/null || true)
  url=${url:-https://www.youtube.com/watch?v=$id}
  echo "=== $id <- $url ==="
  mkdir -p "reports/$id"
  if [ -f "work/$id/meta.json" ]; then
    cp "work/$id/meta.json" "reports/$id/meta.json"
  fi
  cp "$points" "reports/$id/points.json"
  ( cd "reports/$id" && python3 ../../tools/build_report.py "$url" --points points.json \
      --out . --embed youtube --still none ) || exit 1
  built=$((built + 1))
done

if [ "$built" -gt 0 ]; then
  python3 tools/build_index.py --root . --generator
fi
echo "built $built report(s)"
