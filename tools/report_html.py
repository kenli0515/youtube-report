#!/usr/bin/env python3
"""Render the standalone HTML report.

Kept apart from build_report.py so the presentation can be tuned without touching the
fetching logic. The report is always Simplified Chinese, so the chrome of the page is
Chinese too. Everything is inline - no fonts, scripts or stylesheets are fetched from
the network - so the file plays its own clips straight from disk.
"""

from __future__ import annotations

import html

# The accent pair is written straight into the CSS below. Keeping it as a placeholder
# that a str.replace has to remember to fill produced a broken --accent once already.
# Shared page furniture: colour tokens for both themes, the reading-progress bar, the
# toolbar buttons and the base type. build_index.py reuses it so the index page and the
# reports cannot drift apart.
TOKENS_CSS = """
:root{
  --bg:#f6f7fb; --card:#fff; --ink:#14161c; --ink-soft:#3d424e; --muted:#6b7280;
  --line:#e6e7ef; --line-strong:#d8dae6;
  --accent:#4f6ef7; --accent-2:#8b5cf6; --accent-soft:#eef1fe;
  --glow-a:rgba(79,110,247,.16); --glow-b:rgba(139,92,246,.13);
  --shadow:0 1px 2px rgba(16,18,27,.04),0 8px 24px -18px rgba(16,18,27,.28);
  --shadow-lift:0 18px 40px -22px rgba(16,18,27,.38);
  --radius:18px; --radius-sm:12px;
}
:root[data-theme="dark"]{
  --bg:#0b0c10; --card:#15171e; --ink:#e9eaee; --ink-soft:#c3c7d2; --muted:#8d94a2;
  --line:#242733; --line-strong:#31364a;
  --accent:#8ea2ff; --accent-2:#c4a8ff; --accent-soft:#1a1f33;
  --glow-a:rgba(79,110,247,.16); --glow-b:rgba(139,92,246,.12);
  --shadow:0 1px 2px rgba(0,0,0,.5),0 8px 24px -18px rgba(0,0,0,.7);
  --shadow-lift:0 18px 40px -22px rgba(0,0,0,.85);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0b0c10; --card:#15171e; --ink:#e9eaee; --ink-soft:#c3c7d2; --muted:#8d94a2;
    --line:#242733; --line-strong:#31364a;
    --accent:#8ea2ff; --accent-2:#c4a8ff; --accent-soft:#1a1f33;
    --glow-a:rgba(79,110,247,.16); --glow-b:rgba(139,92,246,.12);
    --shadow:0 1px 2px rgba(0,0,0,.5),0 8px 24px -18px rgba(0,0,0,.7);
    --shadow-lift:0 18px 40px -22px rgba(0,0,0,.85);
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0;color:var(--ink);background-color:var(--bg);
  background-image:
    radial-gradient(900px 340px at 10% -80px,var(--glow-a),transparent 70%),
    radial-gradient(760px 300px at 92% -110px,var(--glow-b),transparent 72%);
  background-repeat:no-repeat;
  font:16px/1.78 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
       "Noto Sans SC","Microsoft YaHei",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
}
.wrap{max-width:940px;margin:0 auto;padding:0 24px 110px;position:relative;z-index:0}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
::selection{background:var(--accent);color:#fff}

/* reading progress + back to top */
#bar{position:fixed;top:0;left:0;height:3px;width:100%;z-index:60;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));
  transform:scaleX(0);transform-origin:0 50%;transition:transform .12s linear}
#totop{position:fixed;right:26px;bottom:26px;z-index:60;width:44px;height:44px;
  border-radius:50%;border:1px solid var(--line-strong);background:var(--card);color:var(--ink);
  font-size:1.05rem;cursor:pointer;box-shadow:var(--shadow);opacity:0;visibility:hidden;
  transform:translateY(8px);transition:opacity .2s ease,transform .2s ease,visibility .2s}
#totop.on{opacity:1;visibility:visible;transform:none}
#totop:hover{border-color:var(--accent);color:var(--accent)}

/* hero */
.hero{padding:58px 0 26px}
.hero-top{display:flex;align-items:center;justify-content:space-between;gap:16px;
  margin-bottom:16px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:.76rem;font-weight:700;
  letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.eyebrow::before{content:"";width:22px;height:2px;border-radius:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent-2))}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.toolbtn{border:1px solid var(--line-strong);background:transparent;color:var(--muted);
  border-radius:999px;padding:5px 13px;font-size:.78rem;font-family:inherit;cursor:pointer;
  white-space:nowrap;transition:color .15s ease,border-color .15s ease}
.toolbtn:hover{color:var(--accent);border-color:var(--accent)}
h1{font-size:clamp(1.55rem,3.1vw,2.3rem);line-height:1.3;margin:0 0 22px;
  letter-spacing:-.022em;font-weight:800}
.sub{display:flex;flex-wrap:wrap;gap:9px;align-items:center}

/* pills */
.pill{display:inline-flex;align-items:center;gap:6px;padding:5px 13px;border-radius:999px;
  background:var(--accent-soft);color:var(--accent);font-size:.82rem;font-weight:650;
  font-variant-numeric:tabular-nums;white-space:nowrap}
a.pill:hover{text-decoration:none;filter:brightness(.97);border-color:var(--accent)}
.pill.ghost{background:transparent;border:1px solid var(--line-strong);color:var(--muted);
  font-weight:550}

"""

CSS = TOKENS_CSS + """/* table of contents */
.toc{margin:36px 0 0;padding:22px 26px 24px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.toc-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:12px}
.toc h2{font-size:.82rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);
  margin:0;font-weight:750}
.toc .count{font-size:.8rem;color:var(--muted);font-variant-numeric:tabular-nums}
.toc ol{columns:2;column-gap:14px;margin:0;padding:0;list-style:none}
@media (max-width:720px){.toc ol{columns:1}}
.toc li{break-inside:avoid;margin:1px 0}
.toc a{display:flex;gap:10px;align-items:baseline;padding:5px 9px;border-radius:9px;
  color:var(--ink);font-size:.93rem;line-height:1.5}
.toc a:hover{background:var(--accent-soft);color:var(--accent);text-decoration:none}
.toc .stamp{color:var(--muted);font-variant-numeric:tabular-nums;font-size:.82rem;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.toc a:hover .stamp{color:var(--accent)}

/* section headings */
h2.section{display:flex;align-items:center;gap:12px;font-size:1.1rem;font-weight:750;
  margin:60px 0 20px;letter-spacing:-.01em}
h2.section .n{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.76rem;
  font-weight:700;color:var(--accent);background:var(--accent-soft);border-radius:7px;
  padding:3px 8px;letter-spacing:.02em}
h2.section::after{content:"";flex:1;height:1px;background:var(--line)}

/* point cards */
.point{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:22px 24px 18px;margin:16px 0;box-shadow:var(--shadow);
  transition:box-shadow .2s ease,transform .2s ease,border-color .2s ease}
.point:hover{box-shadow:var(--shadow-lift);transform:translateY(-2px);
  border-color:var(--line-strong)}
.head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
h3{font-size:1.06rem;line-height:1.5;margin:0;font-weight:700;flex:1;min-width:60%;
  letter-spacing:-.005em}
.head .stamp{background:var(--accent-soft);color:var(--accent);border-radius:9px;
  padding:3px 10px;font-size:.82rem;font-weight:700;font-variant-numeric:tabular-nums;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.head .stamp:hover{text-decoration:none;filter:brightness(.95)}
.toggle{border:1px solid var(--line-strong);background:transparent;color:var(--muted);
  border-radius:999px;padding:3px 11px;font-size:.77rem;font-family:inherit;cursor:pointer;
  white-space:nowrap;transition:color .15s ease,border-color .15s ease}
.toggle:hover{color:var(--accent);border-color:var(--accent)}
.point.collapsed .media{display:none}
.point.collapsed{padding-bottom:16px}

/* media */
.media{position:relative;margin:16px 0 0;line-height:0}
video{display:block;width:100%;height:auto;border-radius:var(--radius-sm);background:#000}
img{display:block;width:100%;height:auto;border-radius:var(--radius-sm);
  border:1px solid var(--line)}
.chip-dur{position:absolute;top:10px;right:10px;pointer-events:none;line-height:1.5;
  background:rgba(8,10,16,.62);color:#fff;font-size:.74rem;font-weight:600;
  padding:3px 9px;border-radius:999px;font-variant-numeric:tabular-nums;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}
.play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:64px;height:64px;padding:0 0 0 4px;border-radius:50%;cursor:pointer;
  display:grid;place-items:center;font-size:1.05rem;line-height:1;color:#fff;
  border:1.5px solid rgba(255,255,255,.7);background:rgba(8,10,16,.5);
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
  box-shadow:0 10px 30px rgba(0,0,0,.4);
  transition:transform .18s ease,opacity .25s ease,background .18s ease}
.play:hover{transform:translate(-50%,-50%) scale(1.07);background:rgba(8,10,16,.72)}
/* YouTube facade: the poster is what loads first, the player only appears on click. */
.media.facade{aspect-ratio:16/9;background:#07080c}
.media.facade img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;
  border:0;border-radius:var(--radius-sm)}
.media.facade iframe{position:absolute;inset:0;width:100%;height:100%;border:0;
  border-radius:var(--radius-sm);background:#000}
/* With no still frame to show, the player says what it is instead of showing an empty box. */
.facade-hint{position:absolute;left:0;right:0;top:calc(50% + 48px);text-align:center;
  color:#98a0b0;font-size:.82rem;letter-spacing:.03em;pointer-events:none}
.media.playing .facade-hint{display:none}
.media.playing img{opacity:1}
.media.playing .play{opacity:0;visibility:hidden}
.media.playing .chip-dur{opacity:0;transition:opacity .25s ease}

.note{margin:16px 0 0;color:var(--ink-soft);font-size:.97rem}
.actions{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;padding-top:12px;
  border-top:1px dashed var(--line);font-size:.84rem}
.actions a{color:var(--muted)}
.actions a:hover{color:var(--accent)}
.actions a::before{content:"↗ ";font-size:.8em}

footer{margin-top:76px;padding-top:22px;border-top:1px solid var(--line);
  color:var(--muted);font-size:.83rem;line-height:1.95}
footer a{color:var(--muted);text-decoration:underline}
footer a:hover{color:var(--accent)}

@media (max-width:560px){
  .wrap{padding:0 16px 80px}
  .point{padding:18px 16px 14px}
  h2.section{margin-top:44px}
  #totop{right:16px;bottom:16px}
}
@media print{
  #bar,#totop,.toolbtn,.toggle,.play{display:none}
  body{background:#fff}
  .point{break-inside:avoid;box-shadow:none}
}
"""

CORE_JS = """
(function(){
  var root=document.documentElement;

  var bar=document.getElementById('bar'), totop=document.getElementById('totop');
  function onScroll(){
    var h=root, max=h.scrollHeight-h.clientHeight, y=h.scrollTop;
    if(bar) bar.style.transform='scaleX('+(max>0?y/max:0)+')';
    if(totop) totop.classList.toggle('on', y>620);
  }
  addEventListener('scroll',onScroll,{passive:true});
  addEventListener('resize',onScroll);
  onScroll();
  if(totop) totop.addEventListener('click',function(){
    scrollTo({top:0,behavior:'smooth'});
  });

  document.querySelectorAll('.media').forEach(function(fig){
    var video=fig.querySelector('video'), btn=fig.querySelector('.play');
    if(!video) return;
    if(btn) btn.addEventListener('click',function(){ video.play(); });
    video.addEventListener('play',function(){ fig.classList.add('playing'); });
    video.addEventListener('ended',function(){ fig.classList.remove('playing'); });
  });

  /* The facade keeps a page of embeds light: nothing is requested from YouTube until the
     reader actually asks to watch something. */
  document.querySelectorAll('.facade').forEach(function(fig){
    var btn=fig.querySelector('.play');
    if(!btn) return;
    btn.addEventListener('click',function(){
      var frame=document.createElement('iframe');
      frame.src=fig.dataset.embed+(fig.dataset.embed.indexOf('?')<0?'?':'&')+'autoplay=1';
      frame.title='YouTube player';
      frame.allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
      frame.setAttribute('allowfullscreen','');
      fig.appendChild(frame);
      fig.classList.add('playing');
      btn.remove();
    });
  });

  /* collapse and expand the clip players, so a long report stays readable */
  var cards=[].slice.call(document.querySelectorAll('.point')).filter(function(card){
    return !!card.querySelector('[data-toggle]');
  });
  function setCard(card,collapsed){
    card.classList.toggle('collapsed',collapsed);
    var btn=card.querySelector('[data-toggle]');
    if(btn){
      btn.textContent=collapsed?(btn.dataset.secs?'展开视频 · '+btn.dataset.secs+' 秒':'展开视频'):'收起视频';
      btn.setAttribute('aria-expanded',collapsed?'false':'true');
    }
    if(collapsed){
      var v=card.querySelector('video');
      if(v&&!v.paused) v.pause();
    }
  }
  function anyExpanded(){
    return cards.some(function(card){ return !card.classList.contains('collapsed'); });
  }
  var clipsBtn=document.getElementById('clips');
  function syncClipsLabel(){
    if(clipsBtn) clipsBtn.textContent=anyExpanded()?'收起全部视频':'展开全部视频';
  }
  document.querySelectorAll('[data-toggle]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var card=btn.closest('.point');
      setCard(card,!card.classList.contains('collapsed'));
      syncClipsLabel();
    });
  });
  var clipKey='yt-report-clips';
  if(clipsBtn){
    clipsBtn.addEventListener('click',function(){
      var collapse=anyExpanded();
      cards.forEach(function(card){ setCard(card,collapse); });
      try{ localStorage.setItem(clipKey,collapse?'collapsed':'expanded'); }catch(e){}
      syncClipsLabel();
    });
  }
  var clipPref=null;
  try{ clipPref=localStorage.getItem(clipKey); }catch(e){}
  if(clipPref==='expanded') cards.forEach(function(card){ setCard(card,false); });
  syncClipsLabel();

})();
"""

# The light/dark switch stands on its own so other pages (the index) can drop it in.
THEME_JS = """(function(){
  var root=document.documentElement;
  var key='yt-report-theme', saved=null;
  try{ saved=localStorage.getItem(key); }catch(e){}
  if(saved) root.setAttribute('data-theme',saved);
  var btn=document.getElementById('theme');
  if(!btn) return;
  var order=['auto','light','dark'];
  function paint(){
    var cur=root.getAttribute('data-theme')||'auto';
    btn.textContent=cur==='dark'?'\\u263e 深色':cur==='light'?'\\u2600 浅色':'\\u25d0 跟随系统';
  }
  btn.addEventListener('click',function(){
    var cur=root.getAttribute('data-theme')||'auto';
    var next=order[(order.indexOf(cur)+1)%order.length];
    if(next==='auto'){ root.removeAttribute('data-theme');
      try{ localStorage.removeItem(key); }catch(e){} }
    else { root.setAttribute('data-theme',next);
      try{ localStorage.setItem(key,next); }catch(e){} }
    paint();
  });
  paint();
})();"""


def esc(value):
    return html.escape(str(value), quote=True)


def hms(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def pretty_duration(seconds):
    if not seconds:
        return None
    seconds = int(seconds)
    hours, minutes, secs = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def pretty_date(stamp):
    if not stamp or len(str(stamp)) != 8:
        return None
    stamp = str(stamp)
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"


def pretty_views(count):
    try:
        count = int(count)
    except (TypeError, ValueError):
        return None
    if count >= 10000:
        value = f"{count / 10000:.1f}".rstrip("0").rstrip(".")
        return f"{value} 万次观看"
    return f"{count} 次观看"


JS = CORE_JS + "\n" + THEME_JS


def render(title, url, meta, sep, points, has_media, source_note=""):
    meta = meta or {}
    out = [
        "<!doctype html>",
        '<html lang="zh-Hans">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)}</title>",
        f"<style>{CSS}</style>",
        "<noscript><style>.point.collapsed .media{display:block}"
        ".toggle,.toolbtn{display:none}</style></noscript>",
        "</head>",
        "<body>",
        '<div id="bar"></div>',
        '<div class="wrap">',
        '<header class="hero">',
        '<div class="hero-top">',
        '<span class="eyebrow">视频要点报告</span>',
        '<div class="tools">',
        '<button id="theme" class="toolbtn" type="button" '
        'title="切换浅色 / 深色 / 跟随系统">跟随系统</button>',
        ]
    if has_media:
        out.append('<button id="clips" class="toolbtn" type="button">展开全部视频</button>')
    out += [
        "</div>",
        "</div>",
        f"<h1>{esc(title)}</h1>",
        '<div class="sub">',
    ]

    if meta.get("channel"):
        out.append(f'<span class="pill">{esc(meta["channel"])}</span>')
    for value in (pretty_duration(meta.get("duration")),
                  pretty_date(meta.get("upload_date")),
                  pretty_views(meta.get("view_count"))):
        if value:
            out.append(f'<span class="pill ghost">{esc(value)}</span>')
    if len(points) > 1:
        out.append(f'<span class="pill ghost">{len(points)} 个要点</span>')
    out.append(f'<a class="pill ghost" href="{esc(url)}">在 YouTube 打开原视频 ↗</a>')
    out += ["</div>", "</header>"]

    out += ['<nav class="toc">', '<div class="toc-head">', "<h2>目录</h2>"]
    summary = [f"{len(points)} 个要点"]
    if pretty_duration(meta.get("duration")):
        summary.append(f"全长 {pretty_duration(meta['duration'])}")
    out.append(f'<span class="count">{" · ".join(summary)}</span>')
    out += ["</div>", "<ol>"]
    for point in points:
        out.append(
            f'<li><a href="{esc(url)}{sep}t={point["sec"]}s">'
            f'<span class="stamp">{hms(point["sec"])}</span>'
            f'<span class="ttl">{esc(point["title"])}</span></a></li>'
        )
    out += ["</ol>", "</nav>", "<main>"]

    current, chapter = None, 0
    for point in points:
        if point["section"] != current:
            current = point["section"]
            chapter += 1
            out.append(
                f'<h2 class="section" id="s{chapter}"><span class="n">{chapter:02d}</span>'
                f'<span class="t">{esc(current)}</span></h2>'
            )
        deep = f"{esc(url)}{sep}t={point['sec']}s"
        # A player is either a local clip or an embedded YouTube frame; both collapse.
        has_player = bool(point.get("clip") or point.get("embed"))
        # Rendered collapsed so a report full of players never flashes a wall of video.
        # The noscript rule below keeps the players reachable when JS is off.
        out += [
            f'<article class="point{" collapsed" if has_player else ""}">',
            '<div class="head">',
            f'<a class="stamp" href="{deep}">{hms(point["sec"])}</a>',
            f'<h3>{esc(point["title"])}</h3>',
        ]
        if has_player:
            # The embedded shape has no fixed length - the player runs on - so it says nothing
            # about seconds rather than claiming an empty one.
            secs = point.get("clip_len")
            out.append(
                '<button class="toggle" type="button" data-toggle '
                f'data-secs="{esc(secs or "")}" aria-expanded="false">'
                f'{f"展开视频 · {esc(secs)} 秒" if secs else "展开视频"}</button>'
            )
        out.append("</div>")
        if point.get("embed"):
            poster = point.get("frame")
            still = (f'<img src="{esc(poster)}" alt="{esc(point["title"])}">' if poster
                     else '<span class="facade-hint">点击播放这一秒</span>')
            duration = point.get("clip_len")
            chip = f'<span class="chip-dur">{duration} 秒</span>' if duration else ""
            out.append(
                f'<figure class="media facade" data-embed="{esc(point["embed"])}">{still}'
                f'{chip}<button class="play" type="button" aria-label="播放这个片段">▶</button>'
                "</figure>"
            )
        elif point.get("clip"):
            poster = point.get("frame")
            poster_attr = f' poster="{esc(poster)}"' if poster else ""
            duration = point.get("clip_len")
            chip = f'<span class="chip-dur">{duration} 秒片段</span>' if duration else ""
            # preload="metadata" is what makes the poster still visible before playback;
            # with "none" the browser paints an empty black box instead of the frame.
            out.append(
                f'<figure class="media"><video src="{esc(point["clip"])}"{poster_attr} '
                f'controls playsinline preload="metadata"></video>{chip}'
                '<button class="play" type="button" aria-label="播放这个片段">▶</button>'
                "</figure>"
            )
        elif point.get("frame"):
            out.append(
                f'<figure class="media"><img src="{esc(point["frame"])}" '
                f'alt="{esc(point["title"])}"></figure>'
            )

        if point.get("note"):
            out.append(f'<p class="note">{esc(point["note"])}</p>')

        links = [f'<a href="{deep}">在 YouTube 打开这一秒</a>']
        if point.get("frame"):
            links.append(f'<a href="{esc(point["frame"])}">查看截图原图</a>')
        out += [f'<div class="actions">{"".join(links)}</div>', "</article>"]

    out += ["</main>", "<footer>"]
    out.append(f'原视频：<a href="{esc(url)}">{esc(url)}</a><br>')
    if source_note:
        out.append(f"{esc(source_note)}<br>")
    elif has_media:
        out.append("片段与截图取自原视频，每个要点只用 <code>yt-dlp --download-sections</code> "
                   "截取前后数秒，未下载整片。<br>")
    out.append("本报告由 yt-dlp 与 ffmpeg 从原视频的字幕与片段自动整理生成，"
               "内容为对原视频的转述与摘要。")
    out += ["</footer>", "</div>",
            '<button id="totop" type="button" aria-label="回到顶部">↑</button>',
            f"<script>{JS}</script>", "</body>", "</html>", ""]
    return "\n".join(out)
