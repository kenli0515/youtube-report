#!/usr/bin/env python3
"""Build an index page that lists every report under a root directory.

    python3 build_index.py --root /path/to/reports

Walks the root looking for `report.html` files, reads the `report_assets.json` and `meta.json`
sitting beside each one, and writes `index.html` at the root: one card per report with its first
still as a thumbnail, plus a search box. Re-run it after building a report.

The cards are ordered by the time the report joined the folder, newest first: a report that
arrives without an `added` stamp gets one the first time the index sees it, and the stamp is kept
in its `meta.json`, so rebuilding a report never shuffles it back to the top.

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
ADDED_FILE = "_added.json"

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

.how{margin-top:14px;color:var(--muted);font-size:.86rem;line-height:1.7}
.how a{color:var(--accent)}

.rc-foot{flex-wrap:wrap}
.rc-foot .rc-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:12px}
.rc-foot .added{white-space:nowrap}
.readbtn{border:1px solid var(--line-strong);background:transparent;color:var(--muted);
  font:inherit;font-size:.76rem;font-weight:600;padding:3px 11px;border-radius:999px;
  cursor:pointer;transition:color .15s ease,border-color .15s ease,background .15s ease}
.readbtn:hover{color:var(--accent);border-color:var(--accent)}
.rcard.is-read{opacity:.45}
.rcard.is-read:hover{opacity:1}
.rcard.is-read .readbtn{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
/* .rcard is display:flex, so the hidden attribute needs a rule of its own. */
.rcard[hidden]{display:none}

@media (max-width:560px){.grid{grid-template-columns:1fr}.wrap{padding:0 16px 80px}}
"""

INDEX_JS = """
(function(){
  var KEY='yt-report-read';
  var box=document.getElementById('q');
  var cards=[].slice.call(document.querySelectorAll('.rcard'));
  var count=document.getElementById('count');
  var empty=document.getElementById('empty');
  var toggle=document.getElementById('read-toggle');
  if(!cards.length) return;

  /* Read marks live in this browser and nowhere else: no account, no server, nothing to sync. */
  var read={};
  try{ read=JSON.parse(localStorage.getItem(KEY)||'{}')||{}; }catch(e){ read={}; }
  var showRead=false;

  function save(){ try{ localStorage.setItem(KEY,JSON.stringify(read)); }catch(e){} }
  function isRead(card){ return !!read[card.dataset.id]; }
  function readTotal(){
    var n=0;
    cards.forEach(function(card){ if(isRead(card)) n++; });
    return n;
  }

  function apply(){
    var needle=box?box.value.trim().toLowerCase():'', shown=0, hidden=0;
    cards.forEach(function(card){
      var hit=!needle||(card.dataset.q||'').indexOf(needle)>=0;
      var mark=isRead(card);
      card.classList.toggle('is-read',mark);
      var button=card.querySelector('.readbtn');
      if(button) button.textContent=mark?'标记未读':'已读';
      var show=hit&&(showRead||!mark);
      card.hidden=!show;
      if(show) shown++;
      else if(hit) hidden++;
    });
    if(count) count.textContent='共 '+shown+' 份报告'+(hidden?'，其中已读 '+hidden+' 份':'');
    if(toggle){
      var total=readTotal();
      toggle.hidden=!total;
      toggle.textContent=(showRead?'隐藏已读':'显示已读')+(total?' ('+total+')':'');
    }
    if(empty){
      empty.hidden=shown>0;
      empty.textContent=needle?'没有匹配的报告。'
        :(hidden?'都读完了 —— 点右上角「显示已读」可以翻回来。':'这里还没有报告。');
    }
  }

  cards.forEach(function(card){
    var button=card.querySelector('.readbtn');
    if(!button) return;
    button.addEventListener('click',function(){
      var id=card.dataset.id;
      if(read[id]) delete read[id]; else read[id]=Date.now();
      save();
      apply();
    });
  });
  if(toggle) toggle.addEventListener('click',function(){ showRead=!showRead; apply(); });
  if(box){ box.addEventListener('input',apply); box.addEventListener('search',apply); }
  apply();
})();
"""


# What the panel used to be: one line telling you how a report gets added now. Reading the
# captions needs a logged-in YouTube session, so the browser does it (tools/youtube-report.user.js)
# and this page only ever lists what is already there.
HOW_TO = """
<p class="how">装一次
<a href="tools/youtube-report.user.js">油猴脚本</a>，以后在 YouTube 视频页右下角点「生成要点报告」
就行 —— 字幕由你自己的浏览器读取，不经过任何服务器。</p>
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
        "date": meta.get("upload_date") or meta.get("publish_date") or "",
        "added": meta.get("added") or "",
        "points": len(points),
        "url": assets.get("url") or meta.get("webpage_url") or "",
        "still": f"{folder.relative_to(root).as_posix()}/{thumb}" if thumb else None,
        "cover": meta.get("thumbnail") or "",
    }


def added_label(stamp: str) -> str:
    """`2026-09-16T02:24:49+08:00` -> `09-16 02:24` (or the full date when it is not this year).

    The index is ordered by this stamp, so the card shows it too; the year and the seconds are
    dropped because they rarely help, and the full value stays in the span's title attribute.
    """
    if len(stamp) < 16:
        return stamp
    text = stamp[:16].replace("T", " ")
    return text if text[:4] != str(datetime.now().year) else text[5:]


def stamp_added(root: Path, reports, now: str) -> dict:
    """Work out when each report first turned up, and give the stamps back on the reports.

    The index is the only thing that knows this, so it keeps its own file next to the reports
    rather than trusting what is inside them: rebuilding a report copies its `meta.json` over,
    and a report must not climb back to the top of the list when that happens. First sight wins,
    and the stamp is written into the report's `meta.json` too, so a folder read on its own still
    says when it joined.

    A report that turns up without a stamp - the first run over an existing folder - is dated by
    the mtime of its `report.html`, the best guess left at that point; `now` is the last resort.
    """
    path = root / ADDED_FILE
    known = read_json(path)
    if not isinstance(known, dict):
        known = {}
    ids = {report["id"] for report in reports}

    for report in reports:
        stamp = report["added"] or known.get(report["id"]) or ""
        if not stamp:
            try:
                mtime = (report["dir"] / REPORT_FILE).stat().st_mtime
                stamp = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
            except OSError:
                stamp = now
            meta_path = report["dir"] / "meta.json"
            meta = read_json(meta_path)
            if isinstance(meta, dict):
                meta["added"] = stamp
                meta_path.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  stamped {report['id']} added={stamp}")
        known[report["id"]] = stamp
        report["added"] = stamp

    for gone in [vid for vid in known if vid not in ids]:  # reports that were removed
        del known[gone]
    path.write_text(json.dumps(dict(sorted(known.items())), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return known


def render(root: Path, reports, generated: str):
    out = [
        "<!doctype html>",
        '<html lang="zh-Hans">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>视频要点报告</title>",
        f"<style>{report_html.TOKENS_CSS}{INDEX_CSS}</style>",
        '<noscript><style>.toolbtn,.readbtn{display:none}</style></noscript>',
        "</head>",
        "<body>",
        '<div class="wrap">',
        '<header class="hero">',
        '<div class="hero-top">',
        '<span class="eyebrow">报告库</span>',
        '<div class="tools">',
        '<button id="read-toggle" class="toolbtn" type="button" hidden>显示已读</button>',
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
        HOW_TO.strip(),
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
        added = added_label(report["added"])

        out += [
            f'<article class="rcard" data-id="{esc(report["id"])}" '
            f'data-q="{esc(search_text)}">',
            f'<a class="cover" href="{esc(href)}">{cover}'
            f'<span class="badge">{report["points"]} 个要点</span></a>',
            '<div class="rc-body">',
            f'<h3><a href="{esc(href)}">{esc(report["title"])}</a></h3>',
            f'<div class="tags">{"".join(tags)}</div>',
            '<div class="rc-foot">',
            f'<span class="id">{esc(report["id"])}</span>',
            '<span class="rc-actions">',
        ]
        if added:
            out.append(f'<span class="added" title="加入于 {esc(report["added"])}">'
                       f'加入 {esc(added)}</span>')
        if report["url"]:
            out.append(f'<a href="{esc(report["url"])}">原视频 ↗</a>')
        out += [
            '<button class="readbtn" type="button">已读</button>',
            "</span>", "</div>", "</div>", "</article>",
        ]

    out += [
        "</main>",
        '<p class="empty" id="empty" hidden>没有匹配的报告。</p>',
        "<footer>",
        f"共 {len(reports)} 份报告，位于 <code>{esc(root.name)}/</code>，按加入时间从新到旧排列。<br>",
        "「已读」只记在这台浏览器里（localStorage），换设备或清缓存就没了。<br>",
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
    stamp_added(root, reports, datetime.now().isoformat(timespec="seconds"))
    # Newly added first. Three stable passes, so the tie-breaks are: video date descending, then
    # title ascending - both only ever matter for reports that arrived in the same second.
    reports.sort(key=lambda r: r["title"])
    reports.sort(key=lambda r: (r["date"], r["id"]), reverse=True)
    reports.sort(key=lambda r: r["added"], reverse=True)

    out = Path(args.out).expanduser() if args.out else root / INDEX_FILE
    out.write_text(
        render(root, reports, datetime.now().strftime("%Y-%m-%d %H:%M")),
        encoding="utf-8")
    print(f"{len(reports)} 份报告 -> {out}")


if __name__ == "__main__":
    main()
