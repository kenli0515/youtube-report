#!/usr/bin/env bash
# Can a GitHub-hosted runner reach YouTube?
#
# Runs the operations the real pipeline needs - metadata, subtitles, and a six second section
# download with audio - and writes everything into probe/: a markdown summary plus one log per
# check, so a run can be judged from the repository alone.
#
# usage: bash probe/run-probe.sh

set -u

OUT=probe
LOGS="$OUT/logs"
ROWS="$OUT/rows.md"
FAILS="$OUT/failures.md"
MEDIA="$OUT/media"

mkdir -p "$LOGS" "$MEDIA"
: >"$ROWS"
: >"$FAILS"

# name|url|subtitle pattern. One language pattern per video on purpose: asking for several at
# once makes YouTube answer 429, which would read as a block when it is only rate limiting.
VIDEOS=(
  "S7CrlFLAmEA|https://www.youtube.com/watch?v=S7CrlFLAmEA|en.*"
  "96UZNMMDKXw|https://www.youtube.com/watch?v=96UZNMMDKXw|zh-Hans.*"
)
CLIENTS=(default web_safari tv mweb android_vr)

# The selector the report builder uses, capped at 360p here so the probe stays quick.
FORMAT='bv*[height<=360][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=360][vcodec^=avc1]/bv*[height<=360]/b[height<=360]'

row() { printf '| %s | %s | %s |\n' "$1" "$2" "$3" >>"$ROWS"; }

fail_block() {  # fail_block <label> <logfile>
  {
    printf '<details><summary><code>%s</code> 失败输出</summary>\n\n```\n' "$1"
    tail -n 15 "$2"
    printf '```\n\n</details>\n\n'
  } >>"$FAILS"
}

check() {  # check <label> <slug> <cmd...>
  local label="$1" slug="$2"; shift 2
  local log="$LOGS/$slug.log" start=$SECONDS code
  "$@" >"$log" 2>&1
  code=$?
  local secs=$((SECONDS - start))

  if [ "$code" = 0 ]; then
    row "$label" "✅" "${secs}s"
  elif grep -q "HTTP Error 429" "$log"; then
    # Rate limiting, not a block: worth flagging but not a failure of the pipeline's approach.
    row "$label" "⚠️ 429 限流" "${secs}s"
    fail_block "$label" "$log"
  else
    row "$label" "❌ exit $code" "${secs}s"
    fail_block "$label" "$log"
  fi
  echo "[$label] exit=$code ${secs}s"
  return 0
}

note() { row "$1" "$2" "—"; }

for entry in "${VIDEOS[@]}"; do
  IFS='|' read -r name url subs <<<"$entry"

  printf '\n### %s\n\n| check | 结果 | 耗时 |\n| --- | --- | --- |\n' "$name" >>"$ROWS"

  # --ignore-no-formats-error is what the pipeline passes: without it, a subtitle-only run dies
  # on format selection and looks like a network block.
  check "$name · metadata" "$name-metadata" \
    yt-dlp --no-warnings --skip-download --ignore-no-formats-error \
      --print "%(title)s|%(duration)s|%(view_count)s" "$url"

  check "$name · format list" "$name-formats" \
    yt-dlp --no-warnings --skip-download --ignore-no-formats-error -F "$url"

  check "$name · verbose run" "$name-verbose" \
    yt-dlp --skip-download --ignore-no-formats-error -J --verbose "$url"

  hint=$(grep -iE "js runtime|ejs|nsig|signature|po.?token|player.*error" "$LOGS/$name-verbose.log" \
    | head -2 | cut -c1-90 | tr '\n' ' ')
  note "$name · 警告摘要" "${hint:-未提及 JS 运行时或签名问题}"

  check "$name · auto subtitles" "$name-subs" \
    yt-dlp --no-warnings --skip-download --ignore-no-formats-error --write-auto-subs \
      --sub-langs "$subs" --sub-format vtt -o "$MEDIA/%(id)s.%(ext)s" "$url"

  check "$name · 6s section (video+audio)" "$name-clip" \
    yt-dlp --no-warnings --ignore-no-formats-error --merge-output-format mp4 -f "$FORMAT" \
      --download-sections "*00:00:10-00:00:16" -o "$MEDIA/$name-clip.%(ext)s" "$url"

  if [ -f "$MEDIA/$name-clip.mp4" ]; then
    if ffprobe -v error -show_entries format=format_name,duration \
         -show_entries stream=codec_name,codec_type "$MEDIA/$name-clip.mp4" \
         >"$LOGS/$name-clip-probe.log" 2>&1 &&
       grep -q codec_type=audio "$LOGS/$name-clip-probe.log"; then
      note "$name · 片段含音轨" "是（$(grep -m1 duration "$LOGS/$name-clip-probe.log" | tr -d 'duration=')s）"
    else
      note "$name · 片段含音轨" "❌ 无音轨"
      fail_block "$name · 片段探针" "$LOGS/$name-clip-probe.log"
    fi
  fi

  for client in "${CLIENTS[@]}"; do
    if [ "$client" = default ]; then
      check "$name · client default" "$name-client-default" \
        yt-dlp --no-warnings --skip-download --ignore-no-formats-error \
          --print "%(title)s" "$url"
    else
      check "$name · client $client" "$name-client-$client" \
        yt-dlp --no-warnings --skip-download --ignore-no-formats-error \
          --extractor-args "youtube:player_client=$client" --print "%(title)s" "$url"
    fi
  done
done

{
  echo "# yt-dlp probe"
  echo
  echo "- 运行时间：$(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "- yt-dlp：$(yt-dlp --version)"
  echo "- 出口 IP：$(curl -s --max-time 10 https://ipinfo.io/ip) — $(curl -s --max-time 10 https://ipinfo.io/json | python3 -c "import sys,json;print(json.load(sys.stdin).get('org','?'))" 2>/dev/null)"
  echo "- JS 运行时：node $(node --version 2>/dev/null || echo 无)，deno $(deno --version 2>/dev/null | head -1 || echo 未安装)"
  echo
  echo "✅ 成功、⚠️ 限流（不是封锁）、❌ 失败；完整日志在 \`logs/\`。"
  echo
  cat "$ROWS"
  echo
  cat "$FAILS"
} >"$OUT/summary.md"

echo "probe done"
