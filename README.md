# youtube-report

把 YouTube 视频变成可读的中文要点报告：每个要点带精确到秒的深链、一张截图，以及一段可播放的片段。

## 目录

- `probe/` — yt-dlp 在 GitHub runner 上的可用性探测结果（能否访问 YouTube、能否抓字幕、能否切片段）
- `.github/workflows/probe.yml` — 运行上面这个探测的 workflow

报告站点与生成流程还在搭建中。
