#!/usr/bin/env python3
"""Build a Simplified-Chinese timestamped report for a video.

Usage:
    python3 build_report.py <url> --points points.json --out DIR [options]

points.json is either a list of points or an object with an optional "title" and a
"points" list. Each point:

    {"sec": 1630, "section": "演示实录", "title": "飞书实测", "note": "一句话说明"}

The standalone HTML report is the primary output: it plays video inline in any browser,
so it does not depend on what a particular markdown viewer supports. Markdown is still
available with --md when a plain-text source is wanted.

With --embed youtube the report embeds the YouTube player at the point's own second and lets it
play on from there, keeping only the still frame: the shape that fits a website, where there is
nothing to host and nothing to serve.

Clips are fetched with yt-dlp's --download-sections, so only the seconds around each
point are downloaded - never the whole video.

Writes into DIR:
    report.html          the report (always)
    report.md            optional, with --md
    assets/frames/*.jpg  one still per point
    assets/clips/*.mp4   a few seconds around each point
    report_assets.json   what was built, for re-use or debugging

The report is always written in Simplified Chinese; `title` and `note` come from
points.json and are expected to be Chinese already.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

import report_html

# H.264 video plus AAC audio: the only combination that reliably lands in a real MP4.
# A bare `bv*` selector yields a silent clip, and pairing H.264 with Opus makes yt-dlp
# fall back to a Matroska container, which then does not play under an .mp4 name.
DEFAULT_FORMAT = (
    "bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/"
    "bv*[height<=1080][vcodec^=avc1]+ba/"
    "b[height<=1080][ext=mp4]/b"
)
VIDEO_ONLY_FORMAT = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/bv*"

# Used by --embed youtube: a couple of seconds at 360p is all the still frame needs.
STILL_ONLY_FORMAT = "bv*[height<=360][vcodec^=avc1]/bv*[height<=360]/bv*"
EMBED_STILL_WINDOW = (1, 1, 1.0)  # lead, tail, frame offset - lands on the point itself


def hms(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def slug(seconds, title):
    stem = f"{seconds // 3600:02d}h{(seconds % 3600) // 60:02d}m{seconds % 60:02d}s"
    keep = "".join(ch for ch in title if ch.isalnum())[:18]
    return f"{stem}_{keep}" if keep else stem


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def grab_clip(url, sec, fmt, lead, tail, stem):
    start = max(0, sec - lead)
    args = [
        "yt-dlp", "--no-update", "-q", "--no-warnings",
        "--merge-output-format", "mp4",
        "-f", fmt,
        "--download-sections", f"*{hms(start)}-{hms(sec + tail)}",
        "-o", f"{stem}.%(ext)s", url,
    ]
    run(args)
    for ext in ("mp4", "mkv", "webm"):
        if os.path.exists(f"{stem}.{ext}"):
            return f"{stem}.{ext}"
    return None


def grab_frame(clip, out, offset):
    run([
        "ffmpeg", "-loglevel", "error", "-y", "-ss", str(offset),
        "-i", clip, "-frames:v", "1", "-q:v", "2", out,
    ])
    return os.path.exists(out)


def has_audio(path):
    proc = run([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", path,
    ])
    return bool(proc.stdout.strip())


def clip_is_valid(path, require_audio=True):
    """A clip counts as reusable only if it plays as an MP4 and carries sound."""
    if not os.path.exists(path):
        return False
    container = run([
        "ffprobe", "-v", "error", "-show_entries", "format=format_name",
        "-of", "csv=p=0", path,
    ]).stdout
    if "mp4" not in container:
        return False
    return has_audio(path) if require_audio else True


def video_id(url):
    """The 11 character id, so the report can embed the player instead of shipping a clip."""
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0].split("/")[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if query.get("v"):
        return query["v"][0]
    return os.path.basename(url.rstrip("/"))


def embed_url(url, sec, lead):
    """The player starts a second before the point and then keeps playing.

    No `end=`: in the shared-link shape the reader is watching the real video, and cutting them
    off a few seconds in is worse than letting them watch on. The bounded version of a moment is
    what `--embed file` is for.
    """
    params = urllib.parse.urlencode({
        "start": max(0, sec - lead),
        "rel": "0",
        "modestbranding": "1",
    })
    return f"https://www.youtube.com/embed/{video_id(url)}?{params}"


def thumbnail_url(url, meta):
    """The video's own cover, which is a plain image URL - no video stream involved."""
    return (meta or {}).get("thumbnail") or f"https://i.ytimg.com/vi/{video_id(url)}/hqdefault.jpg"


def load_points(path):
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        title, points = data.get("title"), data.get("points") or []
    else:
        title, points = None, data
    cleaned = []
    for point in points:
        if "sec" not in point or "title" not in point:
            sys.exit("error: every point needs at least 'sec' and 'title'")
        cleaned.append({
            "sec": int(point["sec"]),
            "section": point.get("section") or "要点",
            "title": point["title"],
            "note": point.get("note", ""),
        })
    if not cleaned:
        sys.exit("error: points.json contained no points")
    return title, cleaned


def load_meta(outdir):
    path = os.path.join(outdir, "meta.json")
    if not os.path.exists(path):
        return {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def render_md(title, url, sep, points, has_media):
    lines = [f"# {title}", ""]
    if has_media:
        lines.append(
            "- **素材**：每个要点用 `yt-dlp --download-sections` 只抓前后数秒的片段（未下载整片），"
            "截图取自同一段视频"
        )
    lines += [
        f"- **视频**：{url}",
        "- **报告语言**：简体中文（无论原视频使用何种语言）",
        "",
        "## 目录",
        "",
    ]
    for point in points:
        lines.append(f"- [`{hms(point['sec'])}` {point['title']}]({url}{sep}t={point['sec']}s)")
    lines.append("")

    current = None
    for point in points:
        if point["section"] != current:
            current = point["section"]
            lines += ["---", "", f"## {current}", ""]
        deep = f"{url}{sep}t={point['sec']}s"
        lines += [f"### `{hms(point['sec'])}` · {point['title']}", "", f"[在 YouTube 打开这一秒]({deep})", ""]
        if point.get("frame"):
            lines += [f"![{point['title']}]({point['frame']})", ""]
        if point.get("clip"):
            lines += [
                f'<video src="{point["clip"]}" controls preload="metadata" width="720"></video>',
                "",
                f"[▶ 播放这一段片段]({point['clip']})",
                "",
            ]
        if point.get("note"):
            lines += [point["note"], ""]
    return "\n".join(lines)


def render_md_obsidian(title, url, sep, points, has_media):
    """Same report, but clips embedded the way Obsidian resolves local media."""
    md = render_md(title, url, sep, points, has_media)
    lines = []
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith('<video src="'):
            clip = stripped.split('"')[1]
            lines.append(f"![[{clip}]]")
        elif stripped.startswith("[▶ 播放这一段片段]"):
            continue
        elif stripped.startswith("!["):
            alt = stripped[2:stripped.index("]")]
            path = stripped[stripped.index("](") + 2:stripped.rindex(")")]
            lines.append(f"![[{path}]]" if alt else line)
        else:
            lines.append(line)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="build a Chinese timestamped video report")
    ap.add_argument("url")
    ap.add_argument("--points", required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--title", help="override the report title")
    ap.add_argument("--format", default=DEFAULT_FORMAT)
    ap.add_argument("--lead", type=int, default=1, help="seconds of lead-in per clip")
    ap.add_argument("--tail", type=int, default=5, help="seconds after the point per clip")
    ap.add_argument("--frame-at", type=float, default=1.5, help="seconds into the clip for the still")
    ap.add_argument("--no-clips", action="store_true", help="render the report without fetching media")
    ap.add_argument("--no-audio", action="store_true", help="fetch video-only clips (silent)")
    ap.add_argument("--refresh", action="store_true", help="re-fetch clips and stills even if present")
    ap.add_argument("--html-file", default="report.html")
    ap.add_argument(
        "--embed", choices=("file", "youtube"), default="file",
        help="play a local mp4, or embed the YouTube player from the same second",
    )
    ap.add_argument(
        "--still", choices=("frame", "thumbnail", "none"), default="frame",
        help="what the player shows before playback (--embed youtube only): a frame cut out "
             "of the video, the video's own cover image, or nothing at all. 'none' means "
             "the report never touches the video stream",
    )
    ap.add_argument("--md", action="store_true", help="also write a markdown report")
    ap.add_argument("--md-file", default="report.md")
    ap.add_argument(
        "--embed-style", choices=("html", "obsidian"), default="html",
        help="markdown only: <video> tags, or ![[...]] embeds for Obsidian",
    )
    args = ap.parse_args()

    embed_mode = args.embed == "youtube"
    if args.no_audio:
        args.format = VIDEO_ONLY_FORMAT
    if embed_mode:
        # The player comes from YouTube, so the only thing worth downloading is the still.
        args.format = STILL_ONLY_FORMAT

    points_title, points = load_points(args.points)
    meta = load_meta(args.out)
    title = args.title or points_title or meta.get("title") or "视频要点报告"
    sep = "&" if "?" in args.url else "?"

    clips_dir = os.path.join(args.out, "assets", "clips")
    frames_dir = os.path.join(args.out, "assets", "frames")
    if not args.embed == "youtube":
        os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(frames_dir, exist_ok=True)

    built, failures = [], []
    for index, point in enumerate(points, 1):
        sec, label = point["sec"], slug(point["sec"], point["title"])
        clip_path = os.path.join(clips_dir, f"{label}.mp4")
        frame_path = os.path.join(frames_dir, f"{label}.jpg")
        point["clip"] = None
        point["frame"] = None

        if args.no_clips:
            if os.path.exists(frame_path):
                point["frame"] = os.path.relpath(frame_path, args.out)
            built.append(point)
            continue

        if embed_mode:
            if args.still == "frame" and (args.refresh or not os.path.exists(frame_path)):
                scratch = tempfile.mkdtemp(prefix="still-")
                lead, tail, offset = EMBED_STILL_WINDOW
                got = grab_clip(args.url, sec, args.format, lead, tail,
                                os.path.join(scratch, label))
                ok = bool(got) and grab_frame(got, frame_path, offset)
                shutil.rmtree(scratch, ignore_errors=True)
                if not ok:
                    failures.append(point)
                    print(f"[{index}/{len(points)}] 截图抓取失败 {hms(sec)} {point['title']}", flush=True)
                    continue
            if args.still == "frame" and os.path.exists(frame_path):
                point["frame"] = os.path.relpath(frame_path, args.out)
            elif args.still == "thumbnail":
                point["frame"] = thumbnail_url(args.url, meta)
            point["embed"] = embed_url(args.url, sec, args.lead)
            built.append(point)
            print(f"[{index}/{len(points)}] ok {hms(sec)} {point['title']}", flush=True)
            continue

        require_audio = not args.no_audio
        refreshed = args.refresh or not clip_is_valid(clip_path, require_audio)
        if refreshed:
            # Download beside the target and replace, so a half-written or silent file
            # can never be mistaken for a good one.
            got = grab_clip(args.url, sec, args.format, args.lead, args.tail,
                            os.path.join(clips_dir, label + ".new"))
            if not got:
                failures.append(point)
                print(f"[{index}/{len(points)}] 片段抓取失败 {hms(sec)} {point['title']}", flush=True)
                continue
            os.replace(got, clip_path)

        # A re-fetched clip needs a fresh still, or the still and the video drift apart.
        if (refreshed or not os.path.exists(frame_path)) and not grab_frame(
            clip_path, frame_path, args.frame_at
        ):
            failures.append(point)
            print(f"[{index}/{len(points)}] 截图失败 {hms(sec)} {point['title']}", flush=True)
            continue

        point["clip"] = os.path.relpath(clip_path, args.out)
        point["frame"] = os.path.relpath(frame_path, args.out)
        point["clip_len"] = args.lead + args.tail
        built.append(point)
        print(f"[{index}/{len(points)}] ok {hms(sec)} {point['title']}", flush=True)

    source_note = ""
    if embed_mode and args.still == "none":
        source_note = ("每个要点直接内嵌 YouTube 播放器并从该秒开始播放，"
                       "本报告没有下载任何视频文件。")
    with open(os.path.join(args.out, args.html_file), "w", encoding="utf-8") as fh:
        fh.write(report_html.render(title, args.url, meta, sep, built,
                                    not args.no_clips, source_note))

    if args.md:
        renderer = render_md_obsidian if args.embed_style == "obsidian" else render_md
        with open(os.path.join(args.out, args.md_file), "w", encoding="utf-8") as fh:
            fh.write(renderer(title, args.url, sep, built, not args.no_clips))

    with open(os.path.join(args.out, "report_assets.json"), "w", encoding="utf-8") as fh:
        json.dump({"title": title, "url": args.url, "points": built,
                   "failures": failures}, fh, ensure_ascii=False, indent=2)

    print(f"\n{len(built)}/{len(points)} 个要点 -> {args.html_file}", file=sys.stderr)
    if failures:
        print(f"{len(failures)} 个要点缺少素材，已在报告中省略", file=sys.stderr)


if __name__ == "__main__":
    main()
