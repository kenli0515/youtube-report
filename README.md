# youtube-report

把 YouTube 视频变成可读的简体中文要点报告：每个要点带精确到秒的深链、一小段可播放的片段（直接内嵌 YouTube 播放器），以及一张该时刻的截图。

站点：<https://kenli0515.github.io/youtube-report/>

## 目录结构

- `index.html` — 报告库首页，由 `tools/build_index.py --root .` 生成，最新视频排在最上面
- `reports/<videoId>/report.html` — 单份报告，`assets/frames/` 里是每个要点的截图
- `requests/<videoId>.json` — 待抓字幕的队列，`work/<videoId>/` 是抓下来的字幕与要点
- `tools/` — skill（`youtube-timestamped-report`）脚本的副本，本机和 runner 跑同一份代码
- `probe/` — yt-dlp 在 GitHub runner 上的可用性探测结果

## 生成一份报告

首页没有输入框：读字幕需要已登录的 YouTube 会话，这件事只有浏览器做得到，所以入口是
`tools/youtube-report.user.js`（油猴脚本）——在 YouTube 视频页右下角点「生成要点报告」。

```
① 浏览器从页面读出字幕                        → 一条视频都不用下载
② 浏览器拿字幕直接调 DeepSeek（BYOK）          → 得到 points.json
③ 浏览器把 work/<id>/points.json 写进仓库      → Action「Publish report」生成报告并刷新索引
④ 浏览器轮询到 reports/<id>/report.html 出现   → 打开报告
```

两个 key 都只活在你自己的浏览器里（Tampermonkey 的 `GM_setValue`，退化为 localStorage）：
GitHub token 需要 fine-grained、只勾本仓库的 `Contents: Read and write`；DeepSeek key 由浏览器
直接调用 `api.deepseek.com`，不经过任何服务器。

`requests/<videoId>.json` + Action「Transcript」那条旧链路还留着：手写一个文件丢进仓库，runner
会替你去抓字幕。但 runner 是数据中心 IP，YouTube 经常要求它做人机验证，所以它只当备用。

## 油猴脚本（就是上面那个入口）

安装（Tampermonkey / Violentmonkey）：

1. 先装 Tampermonkey 扩展；
2. 打开 <https://raw.githubusercontent.com/kenli0515/youtube-report/main/tools/youtube-report.user.js>；
3. Tampermonkey 会弹出安装页，确认；
4. 回到任意 YouTube 视频页，右下角出现「生成要点报告」，填一次 token + key 即可。

两个 key 存在油猴自己的存储里（Tampermonkey 的 `GM_setValue`，退化为 `localStorage`）。

已知限制：YouTube 现在要求 **poToken** 才肯把字幕文件交出来，所以脚本读的是页面自己渲染的
「显示字幕记录」面板（等于你手动点开它拿到的那份）。面板换过一次标签（新版是
`transcript-segment-view-model`，旧版是 `ytd-transcript-segment-renderer`），脚本两套都读，
自动生成的字幕（asr）也一样读得到。脚本会自己试着点开；点不开时它会在日志里写上原因（含面板
的行元素名和读到的条数），你手动点开面板再按一次生成就行。

## 在本机生成

```bash
python3 tools/build_report.py <url> --points points.json --out reports/<videoId> --embed youtube
python3 tools/build_index.py --root .
```

`--embed youtube` 让报告内嵌播放器而不是携带 mp4，所以网页版仓库里只有文字和截图。

## 两种形态

| 形态 | 命令 | 目录里有什么 |
| --- | --- | --- |
| 本机 / Obsidian | `--embed file`（默认） | 切好的 mp4 片段 + 每个要点的截图 |
| 网页 / 分享链接 | `--embed youtube` | 没有视频文件，直接内嵌 YouTube 播放器 |

网页版还可以用 `--still none`：连截图都不抓，报告只依赖字幕，**一个字节的视频都不下载**。

## 已知限制

GitHub runner 的数据中心 IP 会被 YouTube 要求做人机验证（`Sign in to confirm you're not a bot`），
因此**在 CI 上只能拿到字幕和元数据，拿不到视频流**——有的视频连字幕都不给（`LOGIN_REQUIRED`）。
详见 `probe/standalone/summary.md`。字幕抓不到时，用本机 skill 或油猴脚本。
