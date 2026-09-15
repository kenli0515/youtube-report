#!/usr/bin/env python3
"""Build an index page that lists every report under a root directory.

    python3 build_index.py --root /path/to/reports

Walks the root looking for `report.html` files, reads the `report_assets.json` and `meta.json`
sitting beside each one, and writes `index.html` at the root: one card per report with its first
still as a thumbnail, plus a search box. Re-run it after building a report.

With `--generator` the page also carries the "paste a link, get a report" panel. That panel only
works where the site is served over http(s) and a sibling `assets/generate.js` exists (the
GitHub Pages setup in the youtube-report repository); the script is not inlined here because it
talks to the GitHub API for whatever repository the page is served from.

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


GENERATOR_CSS = """
.gen{margin-top:22px;background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:var(--shadow);overflow:hidden}
.gen>summary{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px;padding:15px 20px;
  cursor:pointer;font-weight:700;list-style:none}
.gen>summary::-webkit-details-marker{display:none}
.gen>summary::after{content:"\\25be";margin-left:auto;color:var(--muted);font-size:.85rem;
  transition:transform .2s ease}
.gen[open]>summary::after{transform:rotate(180deg)}
.gen>summary:hover{color:var(--accent)}
.gen-hint{font-weight:450;font-size:.83rem;color:var(--muted)}
.gen-body{padding:0 20px 18px;border-top:1px solid var(--line)}
.gen-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
  margin-top:16px}
.gen-field{display:flex;flex-direction:column;gap:6px}
.gen-field.gen-wide{grid-column:1/-1}
.gen-field span{font-size:.78rem;font-weight:650;letter-spacing:.02em;color:var(--muted)}
.gen-field input,.gen textarea{padding:10px 13px;border-radius:11px;border:1px solid var(--line-strong);
  background:var(--bg);color:var(--ink);font:inherit;font-size:.9rem;transition:border-color .15s ease}
.gen-field input:focus,.gen textarea:focus{outline:none;border-color:var(--accent)}
.gen textarea{width:100%;margin-top:12px;resize:vertical;font-size:.85rem;line-height:1.7;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.gen-remember{display:inline-flex;align-items:center;gap:8px;margin-top:14px;font-size:.83rem;
  color:var(--muted);cursor:pointer}
.gen-actions{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:16px}
.gen-btn{border:0;border-radius:11px;padding:10px 20px;font:inherit;font-size:.9rem;font-weight:650;
  color:#fff;cursor:pointer;background:linear-gradient(135deg,var(--accent),var(--accent-2));
  box-shadow:0 10px 22px -14px var(--accent);transition:filter .15s ease,opacity .15s ease}
/* In the dark palette the accent is a light colour, so white on it would wash out. */
:root[data-theme="dark"] .gen-btn{color:#0b0c10}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .gen-btn{color:#0b0c10}}
.gen-btn:hover{filter:brightness(1.06)}
.gen-btn:disabled{opacity:.5;cursor:progress}
.gen-state{font-size:.83rem;color:var(--accent);font-variant-numeric:tabular-nums}
.gen-log{display:flex;flex-direction:column;gap:6px;margin:16px 0 0;padding:0;list-style:none;
  max-height:280px;overflow:auto;font-size:.85rem;font-variant-numeric:tabular-nums}
.gen-log:empty{display:none}
.gen-log li{padding:8px 12px;border-radius:9px;background:var(--accent-soft);color:var(--ink-soft);
  overflow-wrap:anywhere}
.gen-log li.gen-ok{background:rgba(34,197,94,.13);color:#1a9f52}
.gen-log li.gen-error{background:rgba(229,72,77,.14);color:#e5484d}
.gen-more{margin-top:18px;border:1px dashed var(--line-strong);border-radius:var(--radius-sm);
  padding:12px 15px}
.gen-more>summary{cursor:pointer;font-size:.85rem;color:var(--muted)}
.gen-more>summary:hover{color:var(--accent)}
.gen-more p{margin:12px 0 0;font-size:.83rem;color:var(--muted);line-height:1.8}
.gen-note{margin:18px 0 0;font-size:.82rem;line-height:1.9;color:var(--muted)}
.gen-note code,.gen-more code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.92em;
  background:var(--accent-soft);color:var(--accent);border-radius:6px;padding:1px 6px}

@media (max-width:560px){.gen-body{padding:0 15px 16px}.gen>summary{padding:14px 15px}}
"""

# The panel outside the reports grid. Every id here is read by assets/generate.js.
GENERATOR_PANEL = """
<details class="gen" id="gen" open>
<summary><span>生成新报告</span><span class="gen-hint">贴一条 YouTube 链接，剩下的交给 GitHub Actions
和 DeepSeek</span></summary>
<div class="gen-body">
<div class="gen-grid">
<label class="gen-field gen-wide"><span>YouTube 链接</span>
<input id="gen-url" type="url" autocomplete="off" spellcheck="false"
 placeholder="https://www.youtube.com/watch?v=..."></label>
<label class="gen-field"><span>GitHub token（fine-grained）</span>
<input id="gen-token" type="password" autocomplete="off" spellcheck="false"
 placeholder="github_pat_..."></label>
<label class="gen-field"><span>DeepSeek API key</span>
<input id="gen-key" type="password" autocomplete="off" spellcheck="false" placeholder="sk-..."></label>
</div>
<label class="gen-remember"><input id="gen-remember" type="checkbox">
记住这两个 key（只写进这台浏览器的 localStorage）</label>
<div class="gen-actions">
<button id="gen-run" class="gen-btn" type="button">生成报告</button>
<span class="gen-state" id="gen-state"></span>
</div>
<ol class="gen-log" id="gen-log"></ol>
<details class="gen-more" id="gen-more">
<summary>抓不到字幕？自己贴一份</summary>
<p>runner 的 IP 偶尔会被 YouTube 拦下来（数据中心 IP 要过人机验证）。打开视频页的「显示字幕记录」，
全选复制贴进下面，时间戳会自动解析；字幕文件（<code>.srt</code> / <code>.vtt</code>）也可以直接贴。</p>
<textarea id="gen-paste" rows="7" spellcheck="false"
 placeholder="0:01&#10;大家好，欢迎回来&#10;0:05&#10;今天聊聊..."></textarea>
<div class="gen-actions">
<button id="gen-paste-run" class="gen-btn" type="button">用这份字幕生成</button>
<span class="gen-state" id="gen-paste-state"></span>
</div>
</details>
<p class="gen-note">两个 key 都只活在这个页面里：GitHub token 是 fine-grained、只勾本仓库的
<code>Contents: Read and write</code>，用来往 <code>requests/</code> 和 <code>work/</code>
写文件；DeepSeek key 由浏览器直接调用 DeepSeek（<code>api.deepseek.com</code>），不经过任何服务器。流程：① Action 抓字幕 →
② 浏览器调 DeepSeek 挑要点 → ③ Action 生成报告页并刷新这个索引，通常 1-2 分钟。</p>
</div>
</details>
"""

GENERATOR_SCRIPT = '<script src="assets/generate.js" defer></script>'


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
        # Only hidden folders are skipped: a video id may well start with an underscore
        # (YouTube's own ids do), and dropping those would silently hide a real report.
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts):
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


def render(root: Path, reports, generated: str, generator: bool = False):
    out = [
        "<!doctype html>",
        '<html lang="zh-Hans">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>视频要点报告</title>",
        f"<style>{report_html.TOKENS_CSS}{INDEX_CSS}"
        f"{GENERATOR_CSS if generator else ''}</style>",
        '<noscript><style>.toolbtn,.gen{display:none}</style></noscript>',
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
        GENERATOR_PANEL.strip() if generator else "",
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
        f"共 {len(reports)} 份报告，位于 <code>{esc(root.name)}/</code>。<br>",
        f"索引生成于 {esc(generated)}；新增报告后重新运行 "
        "<code>build_index.py --root</code> 即可刷新。<br>",
        "每份报告由 yt-dlp 与 ffmpeg 从原视频的字幕与片段自动整理生成，内容为对原视频的转述与摘要。",
        "</footer>",
        "</div>",
        GENERATOR_SCRIPT if generator else "",
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
    ap.add_argument(
        "--generator",
        action="store_true",
        help="also render the link -> report panel (needs assets/generate.js beside the index)",
    )
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"error: {root} is not a directory")

    reports = [load_report(path, root) for path in find_reports(root)]
    reports.sort(key=lambda r: (r["date"], r["title"]), reverse=True)

    out = Path(args.out).expanduser() if args.out else root / INDEX_FILE
    out.write_text(
        render(root, reports, datetime.now().strftime("%Y-%m-%d %H:%M"), generator=args.generator),
        encoding="utf-8")
    print(f"{len(reports)} 份报告 -> {out}")


if __name__ == "__main__":
    main()
