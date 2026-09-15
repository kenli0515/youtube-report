#!/usr/bin/env python3
"""Extract a video's subtitles and metadata, and write readable transcript files.

Usage:
    python3 fetch_transcript.py <url> [--out DIR] [--lang LANG] [--paragraph-seconds N]

Writes into DIR:
    <id>.<lang>.vtt              raw subtitle file as downloaded
    transcript_timestamped.txt   one line per caption cue: [seconds] HH:MM:SS text
    transcript_paragraphs.txt    cues merged into readable paragraphs
    meta.json                    title, channel, duration, dates, chapters, thumbnail

The transcript files keep the original language. Translation happens later, when the
report is written.
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import subprocess
import sys

TIMING = re.compile(r"(\d{1,2}:\d{2}:\d{2})[.,](\d{3})\s*-+>\s*(\d{1,2}:\d{2}:\d{2})[.,](\d{3})")
TAG = re.compile(r"<[^>]+>")
# Word-level timings only appear in YouTube's rolled-up auto-captions.
WORD_TIMING = re.compile(r"<\d{1,2}:\d{2}:\d{2}[.,]\d{3}>")

# Some clients hide caption tracks behind a PO token. If the default client reports no
# captions, these are worth probing before concluding that the video has none.
PROBE_CLIENTS = ["ios", "android_vr", "tv", "web_safari", "mweb"]

ZH_LANGS = ("zh-hans", "zh-cn", "zh-sg", "zh-hans-cn")


def ytdlp(args, quiet=True, timeout=180):
    """Run yt-dlp with both ends of the wait bounded.

    A blocked IP does not always answer with an error; sometimes the connection just sits there,
    and a job that hangs is worse than one that fails, because the reader is left on a spinner
    until the job's own timeout kills it. The socket read and the whole process both get a
    deadline, and retries are kept short for the same reason.
    """
    cmd = ["yt-dlp", "--no-update", "--socket-timeout", "15",
           "--retries", "1", "--extractor-retries", "1"] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 1, "", f"yt-dlp timed out after {timeout}s\n")
    if proc.returncode != 0 and not quiet:
        sys.stderr.write(proc.stderr)
    return proc


def probe(url, client=None):
    """Return the video's info dict, optionally forcing a player client."""
    args = ["--skip-download", "--ignore-no-formats-error", "-J"]
    if client:
        args += ["--extractor-args", f"youtube:player_client={client}"]
    args.append(url)
    proc = ytdlp(args)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def caption_tracks(info):
    return (info.get("subtitles") or {}), (info.get("automatic_captions") or {})


def rank_lang(lang, declared):
    """Rank a caption track by how faithful it is likely to be.

    The track carrying the original audio wins; auto-translated tracks rank last because
    they are both the least faithful and the most likely to fail to download.
    """
    low = lang.lower()
    if low.endswith("-orig"):
        return (0, low)
    if declared and low == declared.lower():
        return (1, low)
    if declared and low.startswith(declared.lower()):
        return (2, low)
    if low.startswith("en"):
        return (3, low)
    if low.startswith("zh"):
        return (4, low)
    return (5, low)


def pick_tracks(info, wanted=None):
    """Rank the caption tracks to try, best first, as a list of (lang, is_auto)."""
    manual, auto = caption_tracks(info)
    declared = info.get("language")
    ordered = []

    if wanted:
        needle = wanted.lower()
        for pool in (manual, auto):
            for lang in pool:
                if lang.lower().startswith(needle):
                    entry = (lang, pool is auto)
                    if entry not in ordered:
                        ordered.append(entry)
    for pool in (manual, auto):
        for lang in sorted(pool, key=lambda k: rank_lang(k, declared)):
            entry = (lang, pool is auto)
            if entry not in ordered:
                ordered.append(entry)
    return ordered


def ts_to_seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_vtt(text):
    """Turn a WebVTT file into (start, end, text) cues.

    YouTube's auto-captions roll up: each cue repeats the previous line above the newly
    spoken one, so the last line is the only new speech and the earlier lines would
    duplicate what was already emitted. Manual subtitle files carry no word-level
    timings and are read as-is.
    """
    cues = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        timing_index = None
        for idx, line in enumerate(lines):
            if TIMING.search(line):
                timing_index = idx
                break
        if timing_index is None:
            continue
        match = TIMING.search(lines[timing_index])
        body_lines = lines[timing_index + 1:]
        if WORD_TIMING.search(block):
            # Blank lines matter here: a rolled-up cue whose last line is blank carries
            # no new speech at all.
            body = body_lines[-1] if body_lines else ""
        else:
            body = " ".join(line for line in body_lines if line.strip())
        body = html.unescape(TAG.sub("", body))
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        start = ts_to_seconds(match.group(1))
        end = ts_to_seconds(match.group(3))
        if cues and (cues[-1][2] == body or body.startswith(cues[-1][2])):
            cues[-1] = (cues[-1][0], end, body)
            continue
        cues.append((start, end, body))
    return cues


def merge_paragraphs(cues, window):
    merged = []
    buffer, start = [], None
    for cstart, cend, text in cues:
        if start is None:
            start = cstart
        buffer.append(text)
        if cend - start >= window:
            merged.append((start, join_text(buffer)))
            buffer, start = [], None
    if buffer:
        merged.append((start, join_text(buffer)))
    return merged


CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


def join_text(parts):
    """Join cues, adding a space only where the language needs one.

    Chinese and Japanese read correctly when cues are concatenated directly; Latin,
    Cyrillic and other spaced scripts do not.
    """
    out = ""
    for part in parts:
        if out and not CJK.search(out[-1]) and not CJK.search(part[:1]):
            out += " "
        out += part
    return out


def hms(seconds):
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def download_subs(url, outdir, lang, is_auto, client=None):
    args = [
        "--skip-download", "--ignore-no-formats-error",
        "--sub-langs", lang, "--sub-format", "vtt/best",
        "--write-auto-subs" if is_auto else "--write-subs",
        "-o", os.path.join(outdir, "%(id)s.%(ext)s"),
    ]
    if client:
        args += ["--extractor-args", f"youtube:player_client={client}"]
    args.append(url)
    ytdlp(args)
    # Only this language's file, so a failed attempt cannot masquerade as a success.
    return sorted(
        path for path in glob.glob(os.path.join(outdir, "*.vtt"))
        if f".{lang}." in os.path.basename(path)
    )


def main():
    ap = argparse.ArgumentParser(description="fetch a video transcript with yt-dlp")
    ap.add_argument("url")
    ap.add_argument("--out", default=".")
    ap.add_argument("--lang", help="preferred caption language, e.g. en or zh-Hans")
    ap.add_argument("--paragraph-seconds", type=int, default=45)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    info = probe(args.url)
    if info is None:
        sys.exit("error: yt-dlp could not read this video")

    used_client = None
    candidates = pick_tracks(info, args.lang)

    if not candidates:
        for client in PROBE_CLIENTS:
            alt = probe(args.url, client=client)
            if not alt:
                continue
            candidates = pick_tracks(alt, args.lang)
            if candidates:
                info, used_client = alt, client
                break

    if not candidates:
        sys.exit("error: no caption track is exposed for this video, so there is nothing to transcribe")

    # A listed track is not always a downloadable one, so walk the ranking until one works.
    files, lang, is_auto = [], None, None
    for candidate, candidate_is_auto in candidates[:8]:
        files = download_subs(args.url, args.out, candidate, candidate_is_auto, client=used_client)
        if not files and used_client:
            files = download_subs(args.url, args.out, candidate, candidate_is_auto)
        if files:
            lang, is_auto = candidate, candidate_is_auto
            break

    if not files:
        sys.exit("error: caption tracks were listed but none could be downloaded")

    cues = parse_vtt(open(files[0], encoding="utf-8", errors="replace").read())
    if not cues:
        sys.exit(f"error: {files[0]} contained no usable cues")

    with open(os.path.join(args.out, "transcript_timestamped.txt"), "w", encoding="utf-8") as fh:
        for start, _end, text in cues:
            fh.write(f"[{start}] {hms(start)} {text}\n")

    with open(os.path.join(args.out, "transcript_paragraphs.txt"), "w", encoding="utf-8") as fh:
        for start, text in merge_paragraphs(cues, args.paragraph_seconds):
            fh.write(f"[{start}] {text}\n")

    meta = {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "webpage_url": info.get("webpage_url"),
        # The index page uses this as a card cover, falling back to a still from the report.
        "thumbnail": info.get("thumbnail"),
        "chapters": info.get("chapters"),
        "video_language": info.get("language"),
        "subtitle_language": lang,
        "subtitle_is_automatic": is_auto,
        "player_client_used": used_client,
        "cue_count": len(cues),
    }
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n{len(cues)} cues -> {os.path.abspath(args.out)}", file=sys.stderr)


if __name__ == "__main__":
    main()
