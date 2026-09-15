// ==UserScript==
// @name         YouTube 要点报告
// @namespace    https://github.com/kenli0515/youtube-report
// @version      1.0.0
// @description  在 YouTube 视频页直接读字幕，用你自己的 DeepSeek key 生成简体中文要点报告
// @author       kenli0515
// @match        https://www.youtube.com/watch*
// @grant        GM_getValue
// @grant        GM_setValue
// @run-at       document-idle
// @noframes
// ==/UserScript==

/*
 * Why this exists: a page on github.io cannot read YouTube captions. The watch page sends no
 * CORS headers, /api/timedtext only answers the signed URL from the player response, and the
 * watch page refuses to be framed (X-Frame-Options: SAMEORIGIN). A runner can read captions but
 * YouTube blocks its datacenter IP more often than not. This script runs inside youtube.com,
 * where the captions are one same-origin fetch away, and hands the result to the same Actions
 * pipeline the website uses - so the browser does the fetching and nothing needs a runner.
 */

(function () {
  'use strict';

  var REPO = 'kenli0515/youtube-report';
  var SITE = 'https://kenli0515.github.io/youtube-report/';
  var BRANCH = 'main';
  var API = 'https://api.github.com/repos/' + REPO;
  var POLL_MS = 8000;
  var MAX_TRANSCRIPT = 150000;
  var MAX_POINTS = 30;
  var KEY_TOKEN = 'yt-report-gh-token';
  var KEY_DEEPSEEK = 'yt-report-deepseek';

  /* ---------- storage: Tampermonkey when available, localStorage otherwise ---------- */

  function store(key, value) {
    try {
      if (typeof GM_setValue === 'function') return GM_setValue(key, value);
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* private mode */ }
  }

  function read(key) {
    try {
      if (typeof GM_getValue === 'function') return GM_getValue(key, '');
      return localStorage.getItem(key) || '';
    } catch (e) {
      return '';
    }
  }

  /* ---------- the page we are running in ---------- */

  /* unsafeWindow is the page's own context, where ytcfg and ytInitialPlayerResponse live. */
  function page() {
    return typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
  }

  function videoId() {
    return new URLSearchParams(location.search).get('v');
  }

  function usable(pr, id) {
    return pr && pr.videoDetails && pr.videoDetails.videoId === id ? pr : null;
  }

  /* ---------- the transcript ---------- */

  /* YouTube hands the caption file to its own player as a signed, short-lived URL, and the plain
     /api/timedtext endpoint answers with an empty body to anyone who asks without it. So the
     first choice is the page's own transcript panel: the player fetches the cues correctly, and
     all we do is read them out of the DOM it renders. The two API shapes behind it are kept as
     fallbacks, because a layout change should not take the whole flow down. */

  function parseStamp(text) {
    var m = String(text || '').trim().match(/^(?:(\d+):)?(\d+):(\d+)$/);
    if (!m) return null;
    return Number(m[1] || 0) * 3600 + Number(m[2]) * 60 + Number(m[3]);
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function panelIsOpen() {
    var panel = document.querySelector('ytd-engagement-panel-section-list-renderer[target-id*="transcript"]');
    return !!panel && panel.getAttribute('visibility') === 'ENGAGEMENT_PANEL_VISIBILITY_EXPANDED';
  }

  /* The description hides the transcript button inside its expanded/structured section, so a
     programmatic click only lands once that section is laid out. Both the inline expander and
     the "...more" button are tried, and the caller gets told which step failed. */
  async function openTranscriptPanel() {
    if (panelIsOpen()) return 'already-open';
    var expanders = [
      'ytd-text-inline-expander tp-yt-paper-button#expand',
      'ytd-watch-metadata #expand',
      'tp-yt-paper-button#expand'
    ];
    for (var i = 0; i < expanders.length; i++) {
      var expander = document.querySelector(expanders[i]);
      if (expander && expander.offsetParent) {
        expander.click();
        await sleep(500);
      }
    }
    var byText = [].slice.call(document.querySelectorAll('button, tp-yt-paper-button'))
      .filter(function (b) {
        var text = (b.innerText || b.textContent || '').trim();
        return /^(?:\.{3})?more$|^更多$|Show more/i.test(text);
      })[0];
    if (byText && byText.offsetParent) {
      byText.click();
      await sleep(700);
    }
    var button = transcriptButton();
    if (!button) return 'no-button';
    button.click();
    return 'clicked';
  }

  function transcriptButton() {
    var structural = document.querySelector(
      'ytd-video-description-transcript-section-renderer button');
    if (structural) return structural;
    return [].slice.call(document.querySelectorAll('button, tp-yt-paper-button')).filter(function (b) {
      var text = (b.innerText || b.textContent || '').trim();
      return /transcript|字幕记录|字幕/i.test(text) && text.length < 30;
    })[0] || null;
  }

  function panelSummary() {
    var panel = document.querySelector(
      'ytd-engagement-panel-section-list-renderer[target-id*="transcript"]');
    return {
      panel: panel ? panel.getAttribute('visibility') : 'none',
      segments: segments().length,
      button: !!transcriptButton()
    };
  }

  function segments() {
    return [].slice.call(document.querySelectorAll('ytd-transcript-segment-renderer'));
  }

  async function scrapePanel() {
    var how = await openTranscriptPanel();
    var waitFor = how === 'no-button' ? 10 : 25;
    for (var i = 0; i < waitFor; i++) {
      if (segments().length) break;
      await sleep(400);
    }
    /* The list renders as it is scrolled; keep nudging it until the count stops growing. */
    var scroller = document.querySelector('#segments-container') ||
      document.querySelector('ytd-transcript-renderer #contents') || null;
    var seen = 0;
    for (var pass = 0; pass < 25 && scroller; pass++) {
      var count = segments().length;
      if (count === seen && pass > 2) break;
      seen = count;
      scroller.scrollTop = scroller.scrollHeight;
      await sleep(300);
    }
    var out = [];
    segments().forEach(function (el) {
      var time = el.querySelector('.segment-timestamp, [class*="timestamp"]');
      var text = el.querySelector('.segment-text, [class*="segment-text"]');
      var sec = time ? parseStamp(time.textContent) : null;
      var body = text ? (text.textContent || '').replace(/\s+/g, ' ').trim() : '';
      if (sec === null || !body) {
        /* Class names drift; the rendered text of a segment is always "<stamp> <text>". */
        var lines = (el.innerText || el.textContent || '').split('\n')
          .map(function (line) { return line.trim(); }).filter(Boolean);
        sec = lines.length > 1 ? parseStamp(lines[0]) : null;
        body = lines.length > 1 ? lines.slice(1).join(' ').replace(/\s+/g, ' ').trim() : '';
      }
      if (sec === null || !body) return;
      var last = out[out.length - 1];
      if (last && last.text === body) return;
      out.push({ sec: sec, text: body });
    });
    return { cues: out, how: how };
  }

  function cuesFromJson3(data) {
    var cues = [];
    (data.events || []).forEach(function (event) {
      if (!event.segs) return;
      var text = event.segs.map(function (seg) { return seg.utf8 || ''; })
        .join('').replace(/\s+/g, ' ').trim();
      if (!text) return;
      var sec = Math.round((event.tStartMs || 0) / 1000);
      var last = cues[cues.length - 1];
      if (last && last.text === text) return;
      cues.push({ sec: sec, text: text });
    });
    return cues;
  }

  function captionTracks(pr) {
    var renderer = pr && pr.captions && pr.captions.playerCaptionsTracklistRenderer;
    return (renderer && renderer.captionTracks) || [];
  }

  function pickTrack(tracks) {
    if (!tracks.length) return null;
    var manual = tracks.filter(function (t) { return t.kind !== 'asr'; });
    var pool = manual.length ? manual : tracks;
    return pool.filter(function (t) {
      return /^zh/i.test(t.languageCode || '');
    })[0] || pool[0];
  }

  async function cuesFromTracks(pr) {
    var track = pickTrack(captionTracks(pr));
    if (!track) return null;
    var res = await fetch(track.baseUrl + '&fmt=json3', { credentials: 'same-origin' });
    if (!res.ok) return null;
    /* YouTube answers this without a poToken with an empty body, so never assume JSON. */
    var text = await res.text();
    if (!text) return null;
    var cues;
    try {
      cues = cuesFromJson3(JSON.parse(text));
    } catch (e) {
      return null;
    }
    if (!cues.length) return null;
    return { cues: cues, lang: track.languageCode, isAuto: track.kind === 'asr' };
  }

  /* Same call the transcript panel itself makes, with the page's own config. */
  async function innertubePlayerContext() {
    var cfg = page().ytcfg;
    if (!cfg || !cfg.get) return null;
    var key = cfg.get('INNERTUBE_API_KEY');
    var context = cfg.get('INNERTUBE_CONTEXT');
    if (!key || !context) return null;
    return { key: key, context: context };
  }

  async function playerResponse(id) {
    return usable(page().ytInitialPlayerResponse, id) ||
      usable(page().ytdWatchFlexy && page().ytdWatchFlexy.playerResponse, id);
  }

  async function transcript(id) {
    var problems = [];

    var panel = await scrapePanel();
    if (panel.cues.length) {
      return { cues: panel.cues, lang: 'panel', isAuto: false, source: '字幕面板' };
    }
    problems.push('字幕面板：' + panel.how + '（依次尝试展开描述、点「显示字幕记录」）');

    var pr = await playerResponse(id);
    if (pr) {
      var fromTrack = await cuesFromTracks(pr);
      if (fromTrack) {
        return {
          cues: fromTrack.cues, lang: fromTrack.lang, isAuto: fromTrack.isAuto, source: '播放器字幕轨'
        };
      }
      problems.push('播放器字幕轨：拿不到内容（YouTube 现在要 poToken）');
    } else {
      problems.push('读不到播放器数据');
    }

    var ctx = await innertubePlayerContext();
    if (ctx) {
      var res = await fetch('/youtubei/v1/player?key=' + encodeURIComponent(ctx.key), {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ context: ctx.context, videoId: id })
      });
      if (res.ok) {
        var viaTrack = await cuesFromTracks(await res.json());
        if (viaTrack) {
          return {
            cues: viaTrack.cues, lang: viaTrack.lang, isAuto: viaTrack.isAuto, source: 'innerTube'
          };
        }
      }
      problems.push('innerTube 同样拿不到字幕');
    }

    throw new Error('取不到字幕。\n' + problems.join('\n') +
      '\n办法：在视频下方点开「显示字幕记录」（把字幕面板打开），再按一次生成。');
  }

  function transcriptText(cues) {
    var lines = cues.map(function (c) { return '[' + c.sec + '] ' + c.text; });
    while (lines.length > 2 && lines.join('\n').length > MAX_TRANSCRIPT) {
      lines = lines.filter(function (_, index) { return index % 2 === 0; });
    }
    return lines.join('\n') + '\n';
  }

  /* title / channel / length: the player response when there is one, oEmbed otherwise
     (YouTube's oEmbed endpoint answers this page - no key, no cookies, no CORS trouble). */
  async function pageMeta(id) {
    var pr = await playerResponse(id);
    if (pr) return metaFrom(pr, location.href);
    try {
      var res = await fetch('https://www.youtube.com/oembed?format=json&url=' +
        encodeURIComponent(location.href));
      if (res.ok) {
        var data = await res.json();
        return {
          title: data.title || document.title.replace(/ - YouTube$/, ''),
          channel: data.author_name || '',
          duration: null,
          webpage_url: location.href,
          thumbnail: data.thumbnail_url || ''
        };
      }
    } catch (e) { /* fall through */ }
    return { title: document.title.replace(/ - YouTube$/, ''), webpage_url: location.href };
  }

  function metaFrom(pr, url) {
    var details = pr.videoDetails || {};
    var micro = pr.microformat && pr.microformat.playerMicroformatRenderer;
    var thumbs = (details.thumbnail && details.thumbnail.thumbnails) || [];
    return {
      title: details.title || '',
      channel: details.author || '',
      duration: Number(details.lengthSeconds) || null,
      webpage_url: url,
      thumbnail: (thumbs[thumbs.length - 1] || {}).url || ''
    };
  }

  /* ---------- DeepSeek ---------- */

  var SYSTEM_PROMPT = [
    '你是一个视频要点编辑。输入是视频字幕，每行以 [秒数] 开头。',
    '任务：挑出值得读者花时间看的要点，输出 JSON。',
    '',
    '要求：',
    '1. 输出严格 JSON：{"title": "...", "points": [{"sec": 整数, "section": "...", "title": "...", "note": "..."}]}',
    '2. sec 必须是输入里真实出现过的秒数，不要自己编时间。',
    '3. 15-30 个要点，最多 30 个；同一个 section 的要点放在一起，' +
    'section 用 3-6 个字概括一段内容。视频再长也别超过 30 个，同话题的合并成一条。',
    '4. 跳过寒暄、广告、抽奖、串场、重复的口头禅。优先选：演示、结论、具体数字、转折点、争议观点。',
    '5. title 不超过 20 字，note 一到两句说清发生了什么。',
    '6. 全部用简体中文，无论视频原本是什么语言。人名、产品名、技术术语保留原文。',
    '7. title 用视频本身的主题，不要写成「视频要点」这种空话。'
  ].join('\n');

  async function askDeepSeek(key, transcript, meta) {
    var res = await fetch('https://api.deepseek.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          {
            role: 'user',
            content: '视频标题：' + (meta.title || '未知') + '\n频道：' + (meta.channel || '未知') +
              '\n时长（秒）：' + (meta.duration || '未知') + '\n\n字幕：\n' + transcript
          }
        ],
        response_format: { type: 'json_object' },
        temperature: 0.3,
        max_tokens: 8000
      })
    });
    if (!res.ok) throw new Error('DeepSeek 返回 HTTP ' + res.status + '：' + (await res.text()).slice(0, 200));
    var data = await res.json();
    return data.choices[0].message.content;
  }

  function normalise(raw, transcript) {
    var known = [];
    transcript.replace(/\[(\d+)\]/g, function (_, sec) { known.push(Number(sec)); return _; });
    if (!known.length) throw new Error('字幕里没有时间戳');
    known.sort(function (a, b) { return a - b; });
    var set = new Set(known);
    function snap(sec) {
      sec = Math.max(0, Math.round(Number(sec) || 0));
      if (set.has(sec)) return sec;
      var best = known[0];
      known.forEach(function (k) { if (Math.abs(k - sec) < Math.abs(best - sec)) best = k; });
      return best;
    }
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      var match = raw.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('DeepSeek 没有返回 JSON');
      parsed = JSON.parse(match[0]);
    }
    var points = (parsed.points || []).filter(function (p) {
      return p && p.title && p.sec !== undefined;
    }).map(function (p) {
      return {
        sec: snap(p.sec),
        section: (p.section || '要点').toString().slice(0, 24),
        title: p.title.toString().slice(0, 60),
        note: (p.note || '').toString().slice(0, 400)
      };
    }).sort(function (a, b) { return a.sec - b.sec; });
    var seen = new Set();
    points = points.filter(function (p) {
      if (seen.has(p.sec)) return false;
      seen.add(p.sec);
      return true;
    });
    if (points.length > MAX_POINTS) {
      var step = (points.length - 1) / (MAX_POINTS - 1);
      var kept = [];
      for (var k = 0; k < MAX_POINTS; k++) kept.push(points[Math.round(k * step)]);
      points = kept;
    }
    if (!points.length) throw new Error('DeepSeek 没有给出可用的要点');
    return { title: (parsed.title || '').toString().slice(0, 80), points: points };
  }

  /* ---------- GitHub ---------- */

  function headers(extra) {
    return Object.assign({
      Accept: 'application/vnd.github+json',
      Authorization: 'Bearer ' + read(KEY_TOKEN).trim()
    }, extra || {});
  }

  function b64encode(text) {
    var bytes = new TextEncoder().encode(text);
    var binary = '';
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  async function getFile(path) {
    var res = await fetch(API + '/contents/' + path + '?ref=' + BRANCH, { headers: headers() });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('读取 ' + path + ' 失败：HTTP ' + res.status + '（token 权限？）');
    var data = await res.json();
    return data.content ? atob(data.content.replace(/\s/g, '')) : '';
  }

  async function putFile(path, text, message) {
    var existing = await fetch(API + '/contents/' + path + '?ref=' + BRANCH, { headers: headers() });
    var body = { message: message, content: b64encode(text), branch: BRANCH };
    if (existing.ok) {
      var sha = (await existing.json()).sha;
      if (sha) body.sha = sha;
    } else if (existing.status !== 404) {
      throw new Error('写入前检查 ' + path + ' 失败：HTTP ' + existing.status);
    }
    var res = await fetch(API + '/contents/' + path, {
      method: 'PUT',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error('写入 ' + path + ' 失败：HTTP ' + res.status + ' ' +
      (await res.text()).slice(0, 160));
  }

  async function waitForReport(id, log) {
    for (var i = 0; i < 60; i++) {
      if (await getFile('reports/' + id + '/report.html') !== null) return true;
      if (!i) log('等 Actions 生成报告（约 1-2 分钟）…');
      await sleep(POLL_MS);
    }
    return false;
  }

  /* ---------- the panel ---------- */

  var CSS = [
    '#ytrep{position:fixed;right:18px;bottom:18px;z-index:2147483000;font:14px/1.7 -apple-system,',
    '"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:#e9eaee}',
    '#ytrep *{box-sizing:border-box}',
    '#ytrep .fab{border:0;border-radius:999px;padding:10px 18px;font:inherit;font-weight:650;color:#fff;',
    'cursor:pointer;background:linear-gradient(135deg,#4f6ef7,#8b5cf6);box-shadow:0 12px 26px -14px #4f6ef7}',
    '#ytrep .card{width:330px;background:#15171e;border:1px solid #242733;border-radius:16px;',
    'box-shadow:0 24px 50px -24px #000;padding:16px}',
    '#ytrep .card[hidden]{display:none}',
    '#ytrep h4{margin:0 0 10px;font-size:14px;display:flex;justify-content:space-between;align-items:center}',
    '#ytrep label{display:block;font-size:12px;color:#8d94a2;margin:10px 0 4px}',
    '#ytrep input{width:100%;padding:8px 11px;border-radius:9px;border:1px solid #31364a;',
    'background:#0b0c10;color:#e9eaee;font:inherit;font-size:13px}',
    '#ytrep input:focus{outline:none;border-color:#8ea2ff}',
    '#ytrep .row{display:flex;gap:8px;align-items:center;margin-top:12px}',
    '#ytrep .go{flex:1;border:0;border-radius:10px;padding:9px 14px;font:inherit;font-weight:650;color:#fff;',
    'cursor:pointer;background:linear-gradient(135deg,#4f6ef7,#8b5cf6)}',
    '#ytrep .go:disabled{opacity:.5;cursor:progress}',
    '#ytrep .x{border:0;background:transparent;color:#8d94a2;cursor:pointer;font-size:16px;line-height:1}',
    '#ytrep .log{list-style:none;margin:12px 0 0;padding:0;max-height:190px;overflow:auto;font-size:12px}',
    '#ytrep .log li{padding:6px 9px;border-radius:7px;background:#1a1f33;margin-bottom:5px;',
    'overflow-wrap:anywhere}',
    '#ytrep .log li.ok{background:rgba(34,197,94,.13);color:#3ec46d}',
    '#ytrep .log li.err{background:rgba(229,72,77,.14);color:#e5484d}',
    '#ytrep .hint{font-size:11px;color:#8d94a2;margin:10px 0 0;line-height:1.6}',
    '#ytrep a{color:#8ea2ff;text-decoration:none}',
    '#ytrep a:hover{text-decoration:underline}'
  ].join('');

  function build() {
    var style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    var host = document.createElement('div');
    host.id = 'ytrep';
    host.innerHTML = [
      '<button class="fab" type="button">生成要点报告</button>',
      '<div class="card" hidden>',
      '<h4><span>要点报告</span><button class="x" type="button" title="收起">×</button></h4>',
      '<div class="id"></div>',
      '<label>GitHub token（fine-grained）</label>',
      '<input class="token" type="password" placeholder="github_pat_..." autocomplete="off">',
      '<label>DeepSeek API key</label>',
      '<input class="key" type="password" placeholder="sk-..." autocomplete="off">',
      '<div class="row"><button class="go" type="button">生成</button>',
      '<span class="state"></span></div>',
      '<ul class="log"></ul>',
      '<p class="hint">字幕从当前页面读（等于你在网页上点开「显示字幕记录」拿到的那份），',
      '不经过 GitHub runner，所以不会被 YouTube 的数据中心 IP 限制拖累。',
      '若读不到，先在视频简介里点开「显示字幕记录」，再按生成。</p>',
      '<p class="hint">两个 key 只存在这台浏览器里，用来写 <code>' + REPO + '</code> 的 work/ 目录；',
      '字幕直接从当前页面读，不经过 GitHub runner，所以不会被 YouTube 拦。</p>',
      '<p class="hint">报告做好后会出现在 <a href="' + SITE + '" target="_blank">报告库</a>。</p>',
      '</div>'
    ].join('');
    document.body.appendChild(host);

    var ui = {
      host: host,
      fab: host.querySelector('.fab'),
      card: host.querySelector('.card'),
      close: host.querySelector('.x'),
      id: host.querySelector('.id'),
      token: host.querySelector('.token'),
      key: host.querySelector('.key'),
      go: host.querySelector('.go'),
      state: host.querySelector('.state'),
      log: host.querySelector('.log')
    };
    ui.token.value = read(KEY_TOKEN);
    ui.key.value = read(KEY_DEEPSEEK);
    return ui;
  }

  var ui = build();

  function log(ui, message, kind) {
    var line = document.createElement('li');
    if (kind) line.className = kind;
    line.textContent = message;
    ui.log.appendChild(line);
    ui.log.scrollTop = ui.log.scrollHeight;
  }

  function show(ui, open) {
    ui.card.hidden = !open;
    ui.fab.hidden = open;
    if (open) ui.id.textContent = '视频 ID：' + (videoId() || '（这不是视频页）');
  }

  async function run(ui) {
    var id = videoId();
    ui.log.innerHTML = '';
    ui.go.disabled = true;
    ui.state.textContent = '';
    try {
      if (!id) throw new Error('这不是 YouTube 视频页');
      read(KEY_TOKEN) === ui.token.value.trim() || store(KEY_TOKEN, ui.token.value.trim());
      read(KEY_DEEPSEEK) === ui.key.value.trim() || store(KEY_DEEPSEEK, ui.key.value.trim());
      var token = ui.token.value.trim();
      var key = ui.key.value.trim();
      if (!token) throw new Error('请填 GitHub token');
      if (!key) throw new Error('请填 DeepSeek API key');

      if (await getFile('reports/' + id + '/report.html') !== null) {
        log(ui, '这条视频已经有报告了', 'ok');
        window.open(SITE + 'reports/' + id + '/report.html', '_blank');
        return;
      }

      log(ui, '① 正在读这条视频的字幕…');
      ui.state.textContent = '读字幕…';
      var got = await transcript(id);
      log(ui, '① 字幕就绪：' + got.cues.length + ' 段（' + got.lang +
        (got.isAuto ? ' 自动生成' : '') + '）', 'ok');

      var text = transcriptText(got.cues);
      var meta = await pageMeta(id);

      log(ui, '② 调用 DeepSeek 挑选要点…');
      ui.state.textContent = 'DeepSeek 正在读字幕…';
      var answer = await askDeepSeek(key, text, meta);
      var points = normalise(answer, text);
      log(ui, '② 得到 ' + points.points.length + ' 个要点：' + (points.title || '（未命名）'), 'ok');

      log(ui, '③ 提交给 Actions 生成报告…');
      ui.state.textContent = '等 Actions…';
      await putFile('work/' + id + '/source.txt', location.href + '\n', 'source: ' + id);
      await putFile('work/' + id + '/meta.json', JSON.stringify(meta, null, 2) + '\n', 'meta: ' + id);
      await putFile('work/' + id + '/transcript_timestamped.txt', text, 'transcript: ' + id);
      await putFile('work/' + id + '/points.json', JSON.stringify(points, null, 2) + '\n', 'points: ' + id);

      if (!(await waitForReport(id, function (m) { log(ui, m); }))) {
        throw new Error('报告还没出现，稍后到报告库看：' + SITE);
      }
      log(ui, '完成，正在打开报告', 'ok');
      ui.state.textContent = '';
      window.open(SITE + 'reports/' + id + '/report.html', '_blank');
    } catch (error) {
      log(ui, error.message, 'err');
      ui.state.textContent = '';
    } finally {
      ui.go.disabled = false;
    }
  }

  ui.fab.addEventListener('click', function () { show(ui, true); });
  ui.close.addEventListener('click', function () { show(ui, false); });
  ui.go.addEventListener('click', function () { run(ui); });
})();
