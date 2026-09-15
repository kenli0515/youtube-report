# youtube-report

把 YouTube 视频变成可读的简体中文要点报告：每个要点带精确到秒的深链、一小段可播放的片段（直接内嵌 YouTube 播放器），以及一张该时刻的截图。

站点：<https://kenli0515.github.io/youtube-report/>

## 目录结构

- `index.html` — 报告库首页，由 `build_index.py` 生成
- `reports/<videoId>/report.html` — 单份报告，`assets/frames/` 里是每个要点的截图
- `probe/` — yt-dlp 在 GitHub runner 上的可用性探测结果
- `.github/workflows/pages.yml` — 部署站点
- `.github/workflows/probe.yml` — 运行上面的探测

## 生成方式

报告目前在本机生成后推送：

```bash
python3 build_report.py <url> --points points.json --out reports/<videoId> --embed youtube
python3 build_index.py --root .
```

`--embed youtube` 让报告内嵌播放器而不是携带 mp4，所以仓库里只有文字和截图。

## 两种形态

| 形态 | 命令 | 目录里有什么 |
| --- | --- | --- |
| 本机 / Obsidian | `--embed file`（默认） | 切好的 mp4 片段 + 每个要点的截图 |
| 网页 / 分享链接 | `--embed youtube` | 没有视频文件，直接内嵌 YouTube 播放器 |

网页版还可以用 `--still none`：连截图都不抓，报告只依赖字幕，**一个字节的视频都不下载**。

## 已知限制

GitHub runner 的数据中心 IP 会被 YouTube 要求做人机验证（`Sign in to confirm you're not a bot`），
因此**在 CI 上只能拿到字幕和元数据，拿不到视频流**。详见 `probe/standalone/summary.md`。
