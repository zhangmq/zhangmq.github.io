---
layout: post
lang: zh-CN
title: "给 vsr-player 接上 ff2mpv"
date: 2026-10-20 20:00:00 +0800
categories: tech
tags: [mpv, libmpv, ff2mpv, yt-dlp, qt]
permalink: /zh/2026/10/20/vsr-player-ff2mpv/
translation: /en/2026/10/20/vsr-player-ff2mpv/
description: 接 ff2mpv 首选就是把 mpv 选项放到 `--` 之后、打开 ytdl hook 的播放列表支持，两行配置就够；需要通知、回退和长列表省时间时再考虑 wrapper。
---

[English](/en/2026/10/20/vsr-player-ff2mpv/)

## 背景

vsr-player 是基于 libmpv + Qt 6/QML 的 Linux 播放器，把 AI 超分、插帧、HDR 做成滤镜链接进 mpv 的渲染管线，代码在 [github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player)。

VFX SDK 1.3 更新之后，视频增强这块基本齐了：插帧换成 SDK 自带的 `VideoFrameGeneration`（VFG），10-bit 通路接上，SDR→HDR10 上变换（TrueHDR）作为可选项补进来。这些在之前那篇（[Linux 视频播放器里的实时 AI 超分](/zh/2026/08/18/linux-ai-upscaling-player/)）之后又走了一段，细节不在这里展开。

视频增强这条线暂时没有必须做的事，注意力就挪到日常使用上：能不能少几步操作。

先说明一个前提：播网络视频这件事 vsr-player 一直就能做。libmpv 默认 `ytdl=yes`，`ytdl_hook.lua` 编译在库里，把页面链接丢进去它就调用 `yt-dlp` 解析出实际流地址——不需要先下载，也不需要转存。

所以接 ff2mpv 不是补一个缺失的能力，只是把"复制链接、切到播放器、粘贴"变成浏览器里点一下。

## ff2mpv 是什么

ff2mpv 是一个浏览器扩展：在视频页面上点一下图标，它就把当前页面的 URL 交给本机的播放器。它分两部分：

- **浏览器扩展**：负责取当前页面的 URL（Chrome、Firefox 都有）；
- **本机的 native host**：浏览器通过 native messaging 把 URL 交给它，它再按配置去启动播放器。这里用的是 `ff2mpv-rust`。

host 的配置就是一个 JSON，放在 `~/.config/ff2mpv-rust.json`，只有两个字段有意义：

```json
{
    "player_command": "/usr/bin/mpv",
    "player_args": ["--"]
}
```

它最终执行的东西等价于：

```
mpv -- <url>
```

也就是 `player_command`，加上 `player_args`，再加上扩展递过来的选项（通常为空），最后是 URL。`player_args` 里那个 `--` 是用来分隔的：它之后的参数不再当成播放器的选项，URL 就不会被误认成某个选项。

ff2mpv 自己不做别的事：不解析页面、不展开播放列表、不回报结果。执行完它就把子进程的 stdout/stderr 重定向到 `/dev/null`、用独立进程组、不等子进程退出——播放器这边什么回应都传不回去。

## 首选：两行配置打开列表支持

把 `player_command` 指向 vsr-player，`player_args` 里给它两样东西：

```json
{
    "player_command": "/home/<用户名>/.local/bin/vsr-player",
    "player_args": [
        "--",
        "--ytdl-raw-options=cookies-from-browser=chrome,yes-playlist="
    ]
}
```

拼出来是：

```
vsr-player -- --ytdl-raw-options=cookies-from-browser=chrome,yes-playlist=  <页面URL>
```

`--` 之后的内容由应用分开处理：`--xxx=yyy` 形式交给 mpv（libmpv 选项），不以 `--` 开头的参数是播放列表条目。所以 URL 跟在最后也没问题。

两个参数各自的作用：

- **`cookies-from-browser=chrome`**：让 yt-dlp 直接读 Chrome 的登录态。需要登录才能看的内容（私有收藏夹、会员视频）靠它才能解析。
- **`yes-playlist=`**：打开 ytdl_hook 的播放列表支持。默认情况下 hook 会在 yt-dlp 命令里加 `--no-playlist`，只解析当前页面那一个视频；显式给这个选项之后，它才会把整个列表展开成播放条目。

不需要 `--terminal=yes`、也不需要额外脚本——播放、切条、暂停全都由播放器自己做。

## 实测

环境：libmpv + 真实 B 站收藏夹（39 条，需登录），`--cookies-from-browser chrome`。

| 场景 | 结果 |
|---|---|
| 单个视频页（地址里没有列表参数） | 1 条，正常播放 |
| 收藏夹页面，不加 `yes-playlist=` | 1 条，只播当前视频 |
| 收藏夹页面，加 `yes-playlist=` | **39 条**，约 2.0–2.4 s 展开完 |
| 重复载入同一列表 | 先回到 1 条、再重新展开成 39 条，不会叠加 |
| 展开出的条目起播 | 约 3.9–4.2 s 出画面 |

顺带一个预期内的行为：按 yt-dlp 的语义，开着 `yes-playlist=` 时，如果点的是"视频 + 所属列表"式地址（比如 YouTube 的 `watch?v=…&list=…`），拿到的是整个列表而不是单个视频。只想要单条时，反而要按条目标题点进去，或临时关掉这个选项。

## 这条路的代价

三条，都是实测结果：

1. **失败是静默的。** 快速连续调用时 yt-dlp 偶尔会报 `Unable to extract initial state`（站点反爬），10 次连打里出现过 1 次。这时 hook 会把页面 URL 当单条继续播——不重试、不提示，外面看到的只是"列表只有一条"。
2. **每条解析都重新读浏览器。** 每次解析都是 `--cookies-from-browser chrome`（1.87–1.98 s），比读一个导出的 cookie 文件（1.06–1.21 s）每条多约 0.8 s。
3. **启动稍慢于单视频。** 到首帧：单视频 3.2–3.5 s；列表面 5.1–5.6 s（展开和首条解析各跑了一次带浏览器 cookie 的 yt-dlp）。

点一下随便看看，这些都不影响；列表长、要一条条看下去时才感觉得到。

## 可选：wrapper

在意上面几条的话，可以在 ff2mpv 和播放器之间加一层 wrapper。它做四件事：

- 每次调用先导出一次 cookie（`yt-dlp --cookies-from-browser chrome`）；
- 用 `yt-dlp --flat-playlist --print url` 展开出条目地址（只取 URL，不取完整元数据）；
- 按条目数决定形状：多条走 `--playlist=-`（stdin 喂 URL 列表），0 条或 1 条就直接打开当前 URL；
- 播放期间读播放器 stdout，出现 `AV:` 关掉启动通知，`[ytdl_hook] ERROR` 计数，连续失败就终止播放器并通知。

gist（不随发布包分发，脚本头注释里有依赖和参数规则；放到 `~/.local/bin/` 并 `chmod +x`）：

<https://gist.github.com/zhangmq/3f9df36b91214bdcd82f417ba9e50619>

配置改成指向脚本：

```json
{
    "player_command": "/home/<用户名>/.local/bin/vsr-player-wrapper-for-ff2mpv.py",
    "player_args": ["--"]
}
```

什么时候值得用：

- **长列表逐条看**：cookie 文件让每条解析省 0.8 s 左右。实测每条解析的 argv 都是 `--cookies <文件>`，不会再回浏览器读——所以浏览器只在开头被读一次，播放期间不受影响。
- **需要失败提示**：wrapper 能看到 yt-dlp 的结果，0/1 条时退回直接打开当前 URL 并通知，不会出现"列表悄悄少了一大半"。
- **代价**：启动比直连慢——单视频约 3 s，列表页约 1 s（列表场景下展开那步本来就要做）。这些主要花在导出那一步（现在实现是单独对 `https://httpbin.org/ip` 跑一次 yt-dlp，2.4–3.7 s）。把导出挂在第一次真实抓取上能降到约 1 s。

## 应用侧的 `--playlist` 是哪来的

v0.4.1 加了 mpv 语义的列表输入：多个位置参数即列表、`--playlist <文件|->`（`-` 从 stdin 读）。它直接的来由就是 wrapper 路线——wrapper 展开出地址列表后，需要一个"按顺序播这些地址"的入口。

它本身不依赖 ff2mpv：文件管理器多选、脚本喂列表、`-- a b` 都用得上。但如果只用上面的两行配置，这一项就用不到，列表由 libmpv 自己展开。

## 怎么选

- 只想点一下能播：用两行配置。单视频最快，列表也能展开。
- 列表长、要一条条看，或希望解析失败时有人告诉你：用 wrapper，顺手把 cookie 导出改成挂在第一次抓取上。
- 两者随时可换，只改 `player_command` 一行。
