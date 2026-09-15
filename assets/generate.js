/*
 * The report generator panel on the index page.
 *
 * A GitHub Pages site cannot run yt-dlp, so the work is split three ways:
 *   1. this page drops a request file in requests/  -> an Action fetches the transcript
 *   2. this page calls DeepSeek with the reader's own key -> produces points.json
 *   3. this page writes work/<id>/points.json       -> an Action builds the report and the index
 *
 * Both secrets stay in this browser's localStorage. The GitHub token only needs the Contents
 * permission on this one repository. When the runner's IP is blocked by YouTube, the reader can
 * paste a transcript by hand and skip step 1 entirely.
 */
(function () {
  'use strict';

  var BRANCH = 'main';
  var KEY_TOKEN = 'yt-report-gh-token';
  var KEY_DEEPSEEK = 'yt-report-deepseek';
  var KEY_REMEMBER = 'yt-report-remember';
  var POLL_MS = 8000;
  var MAX_TRANSCRIPT = 150000;
  var MAX_POINTS = 30;
  var FALLBACK_REPO = 'kenli0515/youtube-report';

  /* On Pages the site is served from <owner>.github.io/<repo>/, so a fork works without edits. */
  function detectRepo() {
    var host = location.hostname;
    var parts = location.pathname.split('/').filter(Boolean);
    if (/\.github\.io$/.test(host) && parts.length) {
      return host.replace(/\.github\.io$/, '') + '/' + parts[0];
    }
    return FALLBACK_REPO;
  }

  var REPO = detectRepo();
  var API = 'https://api.github.com/repos/' + REPO;

  var el = {
    url: document.getElementById('gen-url'),
    token: document.getElementById('gen-token'),
    key: document.getElementById('gen-key'),
    remember: document.getElementById('gen-remember'),
    run: document.getElementById('gen-run'),
    state: document.getElementById('gen-state'),
    log: document.getElementById('gen-log'),
    more: document.getElementById('gen-more'),
    paste: document.getElementById('gen-paste'),
    pasteRun: document.getElementById('gen-paste-run'),
    pasteState: document.getElementById('gen-paste-state')
  };
  if (!el.run) return;

  /* ---------- helpers ---------- */

  function log(message, kind) {
    var line = document.createElement('li');
    line.className = 'gen-' + (kind || 'info');
    line.textContent = message;
    el.log.appendChild(line);
    el.log.scrollTop = el.log.scrollHeight;
    return line;
  }

  function state(text) { if (el.state) el.state.textContent = text || ''; }
  function pasteState(text) { if (el.pasteState) el.pasteState.textContent = text || ''; }
  function offerPaste() { if (el.more) { el.more.open = true; el.more.scrollIntoView({ block: 'center' }); } }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function b64encode(text) {
    var bytes = new TextEncoder().encode(text);
    var binary = '';
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  function b64decode(text) {
    var binary = atob(text.replace(/\s/g, ''));
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }

  function videoId(url) {
    try {
      var parsed = new URL(url.trim());
      if (parsed.hostname === 'youtu.be') return parsed.pathname.slice(1).split('/')[0];
      var v = parsed.searchParams.get('v');
      if (v) return v;
      var parts = parsed.pathname.split('/').filter(Boolean);
      if (parts.length >= 2 && (parts[0] === 'shorts' || parts[0] === 'live' || parts[0] === 'embed')) {
        return parts[1];
      }
    } catch (e) {
      return null;
    }
    return null;
  }

  function headers(extra) {
    var head = { Accept: 'application/vnd.github+json' };
    var token = el.token.value.trim();
    if (token) head.Authorization = 'Bearer ' + token;
    return Object.assign(head, extra || {});
  }

  async function getFile(path) {
    var res = await fetch(API + '/contents/' + path + '?ref=' + BRANCH, { headers: headers() });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error('读取 ' + path + ' 失败：HTTP ' + res.status + '（token 有 Contents: Read and write 吗？）');
    var data = await res.json();
    return data.content ? b64decode(data.content) : '';
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
    if (!res.ok) {
      var detail = await res.text();
      throw new Error('写入 ' + path + ' 失败：HTTP ' + res.status + ' ' + detail.slice(0, 200));
    }
  }

  async function deleteFile(path, message) {
    var existing = await fetch(API + '/contents/' + path + '?ref=' + BRANCH, { headers: headers() });
    if (!existing.ok) return;
    var sha = (await existing.json()).sha;
    if (!sha) return;
    await fetch(API + '/contents/' + path, {
      method: 'DELETE',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ message: message, sha: sha, branch: BRANCH })
    });
  }

  /* Waits for the transcript, but stops as soon as the Action writes a failure - a blocked
     runner should not cost the reader six minutes of polling before they hear about it. */
  async function pollTranscript(id) {
    for (var i = 0; i < 45; i++) {
      var text = await getFile('work/' + id + '/transcript_timestamped.txt');
      if (text !== null) return text;
      var failure = await getFile('work/' + id + '/error.txt');
      if (failure !== null) {
        log('① 字幕抓取失败：', 'error');
        failure.split('\n').slice(0, 5).forEach(function (line) { log('  ' + line, 'error'); });
        offerPaste();
        throw new Error('runner 的 IP 被 YouTube 拦下来了：展开下面的「自己贴一份」，或者用本机的 skill');
      }
      if (!i) log('等待字幕（Actions 正在跑，约 1-2 分钟）…');
      state('等待字幕…');
      await sleep(POLL_MS);
    }
    throw new Error('等字幕超时了，可以到 https://github.com/' + REPO + '/actions 看 run 日志');
  }

  async function pollFor(path, describe, tries) {
    for (var i = 0; i < (tries || 45); i++) {
      var text = await getFile(path);
      if (text !== null) return text;
      if (!i) log('等待 ' + describe + '（Actions 正在跑，约 1-2 分钟）…');
      state('等待 ' + describe + '…');
      await sleep(POLL_MS);
    }
    throw new Error(describe + ' 超时，可以到 ' + REPO + '/actions 看 run 日志');
  }

  /* ---------- the video's own metadata (YouTube oEmbed sends CORS headers) ---------- */

  async function oembed(id) {
    try {
      var res = await fetch('https://www.youtube.com/oembed?format=json&url=' +
        encodeURIComponent('https://www.youtube.com/watch?v=' + id));
      if (!res.ok) return {};
      var data = await res.json();
      return {
        title: data.title || '',
        channel: data.author_name || '',
        thumbnail: data.thumbnail_url || ''
      };
    } catch (e) {
      return {};
    }
  }

  /* ---------- transcript pasted by hand ---------- */

  function secOf(a, b, c) {
    return c === undefined ? (+a) * 60 + (+b) : (+a) * 3600 + (+b) * 60 + (+c);
  }

  var RE_ARROW = /(\d{1,2}):(\d{2})(?::(\d{2}))?[.,]\d{1,3}\s*-->/;
  var RE_SEC_BRACKET = /^\[(\d{1,4})\]\s*[:：]?\s*(.*)$/;
  var RE_STAMP_ONLY = /^(?:\[|\()?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,]\d{1,3})?(?:\]|\))?$/;
  var RE_STAMP_LEAD = /^(?:\[|\()?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,]\d{1,3})?(?:\]|\))?[\s:：|,]+(.+)$/;

  /* Accepts YouTube's "show transcript" copy, .srt and .vtt, and [sec] lines. */
  function parseCues(raw) {
    var cues = [];
    var pending = null;
    function flush() {
      if (pending && pending.parts.length) {
        var text = pending.parts.join(' ').replace(/\s+/g, ' ').trim();
        var last = cues[cues.length - 1];
        if (text && !(last && last.text === text)) cues.push({ sec: pending.sec, text: text });
      }
      pending = null;
    }
    String(raw || '').replace(/\r\n?/g, '\n').split('\n').forEach(function (line) {
      var t = line.trim();
      if (!t) { flush(); return; }
      var match = t.match(RE_ARROW);
      if (match) {                        // SRT / VTT timing line
        flush();
        pending = { sec: secOf(match[1], match[2], match[3]), parts: [] };
        return;
      }
      match = t.match(RE_SEC_BRACKET);
      if (match) {                        // our own "[12] text" shape: seconds in brackets
        flush();
        pending = { sec: Math.round(+match[1]), parts: match[2] ? [match[2]] : [] };
        return;
      }
      match = t.match(RE_STAMP_ONLY);
      if (match) {                        // a bare "0:05" line: the cue starts here
        flush();
        pending = { sec: secOf(match[1], match[2], match[3]), parts: [] };
        return;
      }
      match = t.match(RE_STAMP_LEAD);
      if (match) {                        // "0:05 今天聊聊…"
        flush();
        pending = { sec: secOf(match[1], match[2], match[3]), parts: [match[4]] };
        return;
      }
      if (/^(WEBVTT|Kind:|Language:|NOTE\b|\d+$)/i.test(t)) return;
      if (pending) pending.parts.push(t);
    });
    flush();
    return cues;
  }

  function transcriptText(cues) {
    var lines = cues.map(function (c) { return '[' + c.sec + '] ' + c.text; });
    while (lines.length > 2 && lines.join('\n').length > MAX_TRANSCRIPT) {
      lines = lines.filter(function (_, index) { return index % 2 === 0; });
    }
    return lines.join('\n') + '\n';
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
    var context = '视频标题：' + (meta.title || '未知') + '\n频道：' +
      (meta.channel || '未知') + '\n时长（秒）：' + (meta.duration || '未知') + '\n\n字幕：\n';
    var body = {
      model: 'deepseek-chat',
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: context + transcript }
      ],
      response_format: { type: 'json_object' },
      temperature: 0.3,
      max_tokens: 8000
    };
    var res = await fetch('https://api.deepseek.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      var detail = await res.text();
      throw new Error('DeepSeek 返回 HTTP ' + res.status + '：' + detail.slice(0, 300));
    }
    var data = await res.json();
    return data.choices[0].message.content;
  }

  /* The model may round a timestamp or invent one; snap every sec to a second that exists. */
  function normalise(raw, transcript) {
    var known = [];
    transcript.replace(/\[(\d+)\]/g, function (_, sec) { known.push(Number(sec)); return _; });
    if (!known.length) throw new Error('字幕里没有找到时间戳，无法定位要点');
    known.sort(function (a, b) { return a - b; });
    var set = new Set(known);

    function snap(sec) {
      sec = Math.max(0, Math.round(Number(sec) || 0));
      if (set.has(sec)) return sec;
      var best = known[0];
      for (var i = 0; i < known.length; i++) {
        if (Math.abs(known[i] - sec) < Math.abs(best - sec)) best = known[i];
      }
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
    /* A long video can tempt the model past the cap. Thin the list evenly rather than
       keeping only the opening - a report that stops halfway through is worse. */
    if (points.length > MAX_POINTS) {
      var step = (points.length - 1) / (MAX_POINTS - 1);
      var kept = [];
      for (var k = 0; k < MAX_POINTS; k++) kept.push(points[Math.round(k * step)]);
      points = kept;
    }
    if (!points.length) throw new Error('DeepSeek 没有给出可用的要点');
    return { title: (parsed.title || '').toString().slice(0, 80), points: points };
  }

  /* ---------- the flow ---------- */

  function saveSecrets() {
    try {
      if (el.remember.checked) {
        localStorage.setItem(KEY_TOKEN, el.token.value.trim());
        localStorage.setItem(KEY_DEEPSEEK, el.key.value.trim());
        localStorage.setItem(KEY_REMEMBER, '1');
      } else {
        localStorage.removeItem(KEY_TOKEN);
        localStorage.removeItem(KEY_DEEPSEEK);
        localStorage.removeItem(KEY_REMEMBER);
      }
    } catch (e) { /* private mode */ }
  }

  function loadSecrets() {
    try {
      if (localStorage.getItem(KEY_REMEMBER) === '1') {
        el.token.value = localStorage.getItem(KEY_TOKEN) || '';
        el.key.value = localStorage.getItem(KEY_DEEPSEEK) || '';
        el.remember.checked = true;
      }
    } catch (e) { /* private mode */ }
  }

  function credentials() {
    var url = el.url.value.trim();
    var token = el.token.value.trim();
    var key = el.key.value.trim();
    var id = videoId(url);
    if (!id) { log('请填一个 YouTube 视频链接', 'error'); return null; }
    if (!token) { log('请填 GitHub token（fine-grained，本仓库的 Contents: Read and write）', 'error'); return null; }
    if (!key) { log('请填 DeepSeek API key', 'error'); return null; }
    return { url: url, token: token, key: key, id: id };
  }

  /* Points -> work/<id>/points.json -> the Publish report Action -> the report itself. */
  async function publish(creds, answer, stamp, meta, writeTranscript) {
    var points = normalise(answer, stamp);
    log('② 得到 ' + points.points.length + ' 个要点，标题：' + (points.title || '（未命名）'), 'ok');

    if (writeTranscript) {
      log('③ 把字幕和元数据一并存进 work/' + creds.id + '/');
      await putFile('work/' + creds.id + '/source.txt', creds.url + '\n', 'source: ' + creds.id);
      await putFile('work/' + creds.id + '/meta.json',
        JSON.stringify(Object.assign({}, meta, { webpage_url: creds.url }), null, 2) + '\n',
        'meta: ' + creds.id);
      await putFile('work/' + creds.id + '/transcript_timestamped.txt', stamp,
        'transcript: ' + creds.id);
    }

    log('③ 提交 points.json，让 Actions 生成报告…');
    await putFile('work/' + creds.id + '/points.json',
      JSON.stringify(points, null, 2) + '\n',
      'points: ' + creds.id);
    await pollFor('reports/' + creds.id + '/report.html', '报告', 60);

    log('完成，正在打开报告', 'ok');
    state('');
    window.location.href = 'reports/' + creds.id + '/report.html';
  }

  async function run() {
    var creds = credentials();
    if (!creds) return;
    saveSecrets();
    el.log.innerHTML = '';
    el.run.disabled = true;
    try {
      log('视频 ID：' + creds.id + '（仓库 ' + REPO + '）');

      var report = await getFile('reports/' + creds.id + '/report.html');
      if (report !== null) {
        log('这个视频已经有报告了，直接打开', 'ok');
        state('');
        window.location.href = 'reports/' + creds.id + '/report.html';
        return;
      }

      var stamp = await getFile('work/' + creds.id + '/transcript_timestamped.txt');
      if (stamp === null) {
        var failure = await getFile('work/' + creds.id + '/error.txt');
        if (failure !== null) {
          log('上一次没抓到字幕，换一个 runner 再排一次（出口 IP 会变）：', 'error');
          failure.split('\n').slice(0, 3).forEach(function (line) { log('  ' + line, 'error'); });
          offerPaste();
          await deleteFile('work/' + creds.id + '/error.txt', 'retry: ' + creds.id);
        }
        log('① 排队：让 Actions 去抓字幕…');
        await putFile('requests/' + creds.id + '.json',
          JSON.stringify({ url: creds.url, requestedAt: new Date().toISOString() }, null, 2) + '\n',
          'request: ' + creds.id);
        stamp = await pollTranscript(creds.id);
      }
      log('① 字幕就绪（' + stamp.split('\n').filter(Boolean).length + ' 行）', 'ok');

      var meta = {};
      try { meta = JSON.parse(await getFile('work/' + creds.id + '/meta.json') || '{}'); } catch (e) {}
      if (!meta.title) meta = Object.assign(await oembed(creds.id), meta);

      log('② 调用 DeepSeek 挑选要点…');
      state('DeepSeek 正在读字幕…');
      var answer = await askDeepSeek(creds.key, stamp, meta);
      await publish(creds, answer, stamp, meta, false);
    } catch (error) {
      log(error.message, 'error');
      state('');
    } finally {
      el.run.disabled = false;
    }
  }

  /* The runner can be blocked; the reader's own transcript is always good enough. */
  async function runFromPaste() {
    var creds = credentials();
    if (!creds) return;
    saveSecrets();
    el.log.innerHTML = '';
    el.pasteRun.disabled = true;
    try {
      var cues = parseCues(el.paste.value);
      if (!cues.length) {
        log('没解析出带时间戳的字幕：请连时间戳一起贴（YouTube 字幕面板的复制内容就带时间戳）', 'error');
        return;
      }
      log('用你贴的字幕（' + cues.length + ' 段，' + cues[0].sec + 's - ' +
        cues[cues.length - 1].sec + 's）', 'ok');
      pasteState('');
      var stamp = transcriptText(cues);
      var meta = await oembed(creds.id);
      log('② 调用 DeepSeek 挑选要点…');
      pasteState('DeepSeek 正在读字幕…');
      var answer = await askDeepSeek(creds.key, stamp, meta);
      await publish(creds, answer, stamp, meta, true);
    } catch (error) {
      log(error.message, 'error');
      pasteState('');
    } finally {
      el.pasteRun.disabled = false;
    }
  }

  /* The userscript lives in this repository, so the link works on a fork too. */
  var userscript = document.getElementById('gen-userscript');
  if (userscript) {
    userscript.href = 'https://raw.githubusercontent.com/' + REPO + '/' + BRANCH +
      '/tools/youtube-report.user.js';
  }

  loadSecrets();
  el.run.addEventListener('click', run);
  el.url.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') run();
  });
  if (el.pasteRun) el.pasteRun.addEventListener('click', runFromPaste);
})();
