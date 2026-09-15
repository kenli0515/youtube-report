/*
 * The report generator panel.
 *
 * A GitHub Pages site cannot run yt-dlp, so the work is split three ways:
 *   1. this page drops a request file in requests/  -> Actions fetches the transcript
 *   2. this page calls DeepSeek with the reader's own key -> produces points.json
 *   3. this page writes work/<id>/points.json       -> Actions builds the report and the index
 *
 * Both secrets stay in this browser's localStorage. The GitHub token only needs the
 * Contents permission on this one repository.
 */
(function () {
  'use strict';

  var REPO = 'kenli0515/youtube-report';
  var BRANCH = 'main';
  var API = 'https://api.github.com/repos/' + REPO;
  var KEY_TOKEN = 'yt-report-gh-token';
  var KEY_DEEPSEEK = 'yt-report-deepseek';
  var KEY_REMEMBER = 'yt-report-remember';
  var POLL_MS = 8000;

  var el = {
    url: document.getElementById('gen-url'),
    token: document.getElementById('gen-token'),
    key: document.getElementById('gen-key'),
    remember: document.getElementById('gen-remember'),
    run: document.getElementById('gen-run'),
    state: document.getElementById('gen-state'),
    log: document.getElementById('gen-log')
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

  function state(text) { el.state.textContent = text || ''; }

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
    if (!res.ok) throw new Error('读取 ' + path + ' 失败：HTTP ' + res.status);
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
      throw new Error('写入 ' + path + ' 失败：HTTP ' + res.status + ' ' + detail.slice(0, 240));
    }
  }

  async function pollFor(path, describe, tries) {
    for (var i = 0; i < (tries || 45); i++) {
      var text = await getFile(path);
      if (text !== null) return text;
      if (!i) log('等待 ' + describe + '（Actions 正在跑，约 1-2 分钟）…');
      state('等待 ' + describe + '…');
      await sleep(POLL_MS);
    }
    throw new Error(describe + ' 超时，可以到 Actions 页面看 run 日志');
  }

  /* ---------- DeepSeek ---------- */

  var SYSTEM_PROMPT = [
    '你是一个视频要点编辑。输入是视频字幕，每行以 [秒数] 开头。',
    '任务：挑出值得读者花时间看的要点，输出 JSON。',
    '',
    '要求：',
    '1. 输出严格 JSON：{"title": "...", "points": [{"sec": 整数, "section": "...", "title": "...", "note": "..."}]}',
    '2. sec 必须是输入里真实出现过的秒数，不要自己编时间。',
    '3. 15-30 个要点；同一个 section 的要点放在一起，section 用 3-6 个字概括一段内容。',
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

  async function run() {
    var url = el.url.value.trim();
    var token = el.token.value.trim();
    var key = el.key.value.trim();
    var id = videoId(url);
    el.log.innerHTML = '';

    if (!id) { log('请填一个 YouTube 视频链接', 'error'); return; }
    if (!token) { log('请填 GitHub token（fine-grained，Contents: Read and write）', 'error'); return; }
    if (!key) { log('请填 DeepSeek API key', 'error'); return; }
    saveSecrets();

    el.run.disabled = true;
    try {
      log('视频 ID：' + id);

      var report = await getFile('reports/' + id + '/report.html');
      if (report !== null) {
        log('这个视频已经有报告了，直接打开', 'ok');
        state('');
        window.location.href = 'reports/' + id + '/report.html';
        return;
      }

      var transcript = await getFile('work/' + id + '/transcript_paragraphs.txt');
      var stamp = await getFile('work/' + id + '/transcript_timestamped.txt');
      if (transcript === null || stamp === null) {
        var failure = await getFile('work/' + id + '/error.txt');
        if (failure !== null) {
          log('上一次抓字幕失败了：', 'error');
          failure.split('\n').slice(0, 6).forEach(function (line) { log('  ' + line, 'error'); });
          throw new Error('字幕不可用，见上面的原因');
        }
        log('① 排队：让 Actions 去抓字幕…');
        await putFile('requests/' + id + '.json',
          JSON.stringify({ url: url, requestedAt: new Date().toISOString() }, null, 2) + '\n',
          'request: ' + id);
        transcript = await pollFor('work/' + id + '/transcript_paragraphs.txt', '字幕');
        stamp = await pollFor('work/' + id + '/transcript_timestamped.txt', '字幕');
        var lateFailure = await getFile('work/' + id + '/error.txt');
        if (lateFailure !== null) throw new Error('字幕抓取失败：' + lateFailure.split('\n')[0]);
      }
      log('① 字幕就绪（' + stamp.split('\n').filter(Boolean).length + ' 行）', 'ok');

      var meta = {};
      try { meta = JSON.parse(await getFile('work/' + id + '/meta.json') || '{}'); } catch (e) {}

      log('② 调用 DeepSeek 挑选要点…');
      state('DeepSeek 正在读字幕…');
      var answer = await askDeepSeek(key, stamp, meta);
      var points = normalise(answer, stamp);
      log('② 得到 ' + points.points.length + ' 个要点，标题：' + (points.title || '（未命名）'), 'ok');

      log('③ 提交 points.json，让 Actions 生成报告…');
      await putFile('work/' + id + '/points.json',
        JSON.stringify(points, null, 2) + '\n',
        'points: ' + id);
      await pollFor('reports/' + id + '/report.html', '报告', 60);

      log('完成，正在打开报告', 'ok');
      state('');
      window.location.reload();
    } catch (error) {
      log(error.message, 'error');
      state('');
    } finally {
      el.run.disabled = false;
    }
  }

  loadSecrets();
  el.run.addEventListener('click', run);
  el.url.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') run();
  });
})();
