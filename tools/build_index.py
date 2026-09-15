#!/usr/bin/env python3
"""Build an index page that lists every report under a root directory.

    python3 build_index.py --root /path/to/reports

Walks the root looking for `report.html` files, reads the `report_assets.json` and `meta.json`
sitting beside each one, and writes `index.html` at the root: one card per report with its first
still as a thumbnail, plus a search box. Re-run it after building a report.

The page reuses the report's colour tokens and light/dark switch (see report_html), so the index
and the reports look like one product.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import report_html
from report_html import esc, pretty_date, pretty_duration

INDEX_FILE = "index.html"
REPORT_FILE = "report.html"

# Directories that never contain a report, or that would only add noise when descending.
SKIP_DIRS = {"assets", "node_modules", ".git", ".obsidian", ".trash"}
MAX_DEPTH = 3

INDEX_CSS = """
.search{width:100%;margin-top:26px;padding:12px 16px;border-radius:13px;
  border:1px solid var(--line-strong);background:var(--card);color:var(--ink);
  font:inherit;font-size:.95rem;transition:border-color .15s ease,box-shadow .15s ease}
.search::placeholder{color:var(--muted)}
.search:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}

.grid{display:grid;gap:18px;margin-top:26px;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}

.rcard{display:flex;flex-direction:column;overflow:hidden;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);
  transition:transform .2s ease,box-shadow .2s ease,border-color .2s ease}
.rcard:hover{transform:translateY(-3px);box-shadow:var(--shadow-lift);
  border-color:var(--line-strong)}
.rcard .cover{position:relative;display:block;aspect-ratio:16/9;background:#0d0f16;
  overflow:hidden}
.rcard .cover img{width:100%;height:100%;object-fit:cover;display:block;
  transition:transform .35s ease}
.rcard:hover .cover img{transform:scale(1.03)}
.rcard .ph{display:grid;place-items:center;width:100%;height:100%;color:#7c8394;
  font-size:.82rem;letter-spacing:.04em}
.rcard .badge{position:absolute;left:10px;top:10px;padding:3px 10px;border-radius:999px;
  background:rgba(8,10,16,.62);color:#fff;font-size:.74rem;font-weight:600;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
  font-variant-numeric:tabular-nums}
.rc-body{display:flex;flex-direction:column;gap:11px;flex:1;padding:16px 18px 14px}
.rc-body h3{font-size:1rem;font-weight:700;line-height:1.5;margin:0;letter-spacing:-.005em}
.rc-body h3 a{color:var(--ink)}
.rc-body h3 a:hover{color:var(--accent);text-decoration:none}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{padding:3px 9px;border-radius:999px;background:var(--accent-soft);color:var(--accent);
  font-size:.75rem;font-weight:600;white-space:nowrap}
.tag.ghost{background:transparent;border:1px solid var(--line-strong);color:var(--muted);
  font-weight:550;font-variant-numeric:tabular-nums}
.rc-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:auto;
  padding-top:12px;border-top:1px dashed var(--line);font-size:.8rem;color:var(--muted)}
.rc-foot .id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.78rem;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rc-foot a{color:var(--muted)}
.rc-foot a:hover{color:var(--accent)}
.empty{margin-top:30px;padding:34px;text-align:center;color:var(--muted);
  border:1px dashed var(--line-strong);border-radius:var(--radius);font-size:.92rem}
.empty[hidden]{display:none}

footer{margin-top:64px;padding-top:22px;border-top:1px solid var(--line);
  color:var(--muted);font-size:.83rem;line-height:1.95}
footer code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
  background:var(--accent-soft);color:var(--accent);border-radius:6px;padding:1px 6px}

@media (max-width:560px){.grid{grid-template-columns:1fr}.wrap{padding:0 16px 80px}}
"""

INDEX_JS = """
(function(){
  var box=document.getElementById('q');
  if(!box) return;
  var cards=[].slice.call(document.querySelectorAll('.rcard'));
  var count=document.getElementById('count');
  var empty=document.getElementById('empty');
  function apply(){
    var needle=box.value.trim().toLowerCase(), shown=0;
    cards.forEach(function(card){
      var hit=!needle||(card.dataset.q||'').indexOf(needle)>=0;
      card.style.display=hit?'':'none';
      if(hit) shown++;
    });
    if(count) count.textContent='共 '+shown+' 份报告';
    if(empty) empty.hidden=shown>0;
  }
  box.addEventListener('input',apply);
  box.addEventListener('search',apply);
  apply();
})();
"""


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_reports(root: Path):
    reports = []
    for path in sorted(root.rglob(REPORT_FILE)):
        parts = path.relative_to(root).parts[:-1]
        if len(parts) > MAX_DEPTH:
            continue
        if any(p.startswith(".") or p.startswith("_") or p in SKIP_DIRS for p in parts):
            continue
        reports.append(path)
    return reports


def load_report(path: Path, root: Path):
    folder = path.parent
    assets = read_json(folder / "report_assets.json") or {}
    meta = read_json(folder / "meta.json") or {}
    points = assets.get("points") or []
    thumb = next((p.get("frame") for p in points if p.get("frame")), None)
    return {
        "dir": folder,
        "rel": folder.relative_to(root).as_posix(),
        "id": folder.name,
        "title": assets.get("title") or meta.get("title") or folder.name,
        "channel": meta.get("channel") or "",
        "duration": meta.get("duration"),
        "date": meta.get("upload_date") or "",
        "points": len(points),
        "url": assets.get("url") or meta.get("webpage_url") or "",
        "still": f"{folder.relative_to(root).as_posix()}/{thumb}" if thumb else None,
        "cover": meta.get("thumbnail") or "",
    }


def render(root: Path, reports, generated: str):
    out = [
        "<!doctype html>",
        '<html lang="zh-Hans">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>视频要点报告</title>",
        f"<style>{report_html.TOKENS_CSS}{INDEX_CSS}</style>",
        '<noscript><style>.toolbtn{display:none}</style></noscript>',
        "</head>",
        "<body>",
        '<div class="wrap">',
        '<header class="hero">',
        '<div class="hero-top">',
        '<span class="eyebrow">报告库</span>',
        '<div class="tools">',
        '<button id="theme" class="toolbtn" type="button" '
        'title="切换浅色 / 深色 / 跟随系统">跟随系统</button>',
        "</div>",
        "</div>",
        "<h1>视频要点报告</h1>",
        '<div class="sub">',
        f'<span class="pill ghost" id="count">共 {len(reports)} 份报告</span>',
        f'<span class="pill ghost">{esc(root.name)}/</span>',
        "</div>",
        '<input id="q" class="search" type="search" autocomplete="off" '
        'placeholder="搜索标题或频道…">',
        "</header>",
        '<main class="grid">',
    ]

    for report in reports:
        tags = []
        if report["channel"]:
            tags.append(f'<span class="tag">{esc(report["channel"])}</span>')
        for value in (pretty_duration(report["duration"]),
                      pretty_date(report["date"])):
            if value:
                tags.append(f'<span class="tag ghost">{esc(value)}</span>')
        if report["points"]:
            tags.append(f'<span class="tag ghost">{report["points"]} 个要点</span>')

        # Prefer the video's own cover, fall back to a still from the report, then to a
        # placeholder - so the index still works with no network.
        if report["cover"] and report["still"]:
            cover = (f'<img src="{esc(report["cover"])}" alt="" loading="lazy" '
                     f'data-still="{esc(report["still"])}" '
                     'onerror="this.onerror=null;this.src=this.dataset.still">')
        elif report["cover"]:
            cover = f'<img src="{esc(report["cover"])}" alt="" loading="lazy">'
        elif report["still"]:
            cover = f'<img src="{esc(report["still"])}" alt="" loading="lazy">'
        else:
            cover = '<div class="ph">这一份还没有截图</div>'
        href = f'{report["rel"]}/{REPORT_FILE}'
        search_text = f'{report["title"]} {report["channel"]} {report["id"]}'.lower()

        out += [
            f'<article class="rcard" data-q="{esc(search_text)}">',
            f'<a class="cover" href="{esc(href)}">{cover}'
            f'<span class="badge">{report["points"]} 个要点</span></a>',
            '<div class="rc-body">',
            f'<h3><a href="{esc(href)}">{esc(report["title"])}</a></h3>',
            f'<div class="tags">{"".join(tags)}</div>',
            '<div class="rc-foot">',
            f'<span class="id">{esc(report["id"])}</span>',
        ]
        if report["url"]:
            out.append(f'<a href="{esc(report["url"])}">原视频 ↗</a>')
        out += ["</div>", "</div>", "</article>"]

    out += [
        "</main>",
        '<p class="empty" id="empty" hidden>没有匹配的报告。</p>',
        "<footer>",
        f"共 {len(reports)} 份报告，位于 <code>{esc(str(root))}</code>。<br>",
        f"索引生成于 {esc(generated)}；新增报告后重新运行 "
        "<code>build_index.py --root</code> 即可刷新。<br>",
        "每份报告由 yt-dlp 与 ffmpeg 从原视频的字幕与片段自动整理生成，内容为对原视频的转述与摘要。",
        "</footer>",
        "</div>",
        f"<script>{report_html.THEME_JS}\n{INDEX_JS}</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="build an index page for a folder of reports")
    ap.add_argument("--root", default=".", help="folder holding the report directories")
    ap.add_argument("--out", help="index file to write (default: <root>/index.html)")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"error: {root} is not a directory")

    reports = [load_report(path, root) for path in find_reports(root)]
    reports.sort(key=lambda r: (r["date"], r["title"]), reverse=True)

    out = Path(args.out).expanduser() if args.out else root / INDEX_FILE
    out.write_text(render(root, reports, datetime.now().strftime("%Y-%m-%d %H:%M")),
                   encoding="utf-8")
    print(f"{len(reports)} 份报告 -> {out}")


if __name__ == "__main__":
    main()
