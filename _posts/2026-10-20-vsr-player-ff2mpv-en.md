---
layout: post
lang: en
hidden: true
title: "Adding ff2mpv support to vsr-player"
date: 2026-10-20 20:00:00 +0800
categories: tech
tags: [mpv, libmpv, ff2mpv, yt-dlp, qt]
permalink: /en/2026/10/20/vsr-player-ff2mpv/
translation: /zh/2026/10/20/vsr-player-ff2mpv/
description: The preferred way to hook up ff2mpv is two lines of config — mpv options after `--`, plus the ytdl hook's playlist support turned on. A wrapper is only worth it for notifications, fallback, and long playlists.
---

[中文](/zh/2026/10/20/vsr-player-ff2mpv/)

## Background

vsr-player is a Linux player built on libmpv + Qt 6/QML that wires AI super-resolution, frame interpolation and HDR into mpv's render pipeline as a filter chain. Code: [github.com/zhangmq/vsr-player](https://github.com/zhangmq/vsr-player).

With VFX SDK 1.3 the video-enhancement side is basically complete: frame interpolation moved to the SDK's own `VideoFrameGeneration` (VFG), a 10-bit path went in, and SDR→HDR10 upscaling (TrueHDR) was added as an option. That work happened after the earlier post ([Real-time AI upscaling in a Linux video player](/en/2026/08/18/linux-ai-upscaling-player/)); the details stay there.

With that line temporarily done, attention moved to daily use: can we save a few steps?

One thing to get out of the way first: playing network video has always worked in vsr-player. libmpv defaults to `ytdl=yes` and ships `ytdl_hook.lua`, so handing it a page URL makes it call `yt-dlp` and resolve the actual stream address — no downloading, no saving to disk.

So hooking up ff2mpv doesn't add a missing capability. It just turns "copy the link, switch to the player, paste" into one click in the browser.

## What ff2mpv is

ff2mpv is a browser extension: click its icon on a video page and it hands the current page URL to a local player. It has two parts:

- **the browser extension**, which grabs the current page URL (available for Chrome and Firefox);
- **a native host** on the machine. The browser passes the URL over native messaging, and the host starts the player according to its config. Here that host is `ff2mpv-rust`.

The host config is a single JSON file at `~/.config/ff2mpv-rust.json`, and only two fields matter:

```json
{
    "player_command": "/usr/bin/mpv",
    "player_args": ["--"]
}
```

What it ultimately runs is equivalent to:

```
mpv -- <url>
```

That is `player_command`, then `player_args`, then any options the extension sends (usually none), and finally the URL. The `--` in `player_args` is a separator: everything after it stops being treated as player options, so the URL can't be mistaken for one.

ff2mpv does nothing else: it doesn't parse pages, doesn't expand playlists, and reports nothing back. When it's done it redirects the child process's stdout/stderr to `/dev/null`, detaches it into its own process group, and doesn't wait for it to exit — so nothing the player says can get back out.

## The preferred way: two lines of config

Point `player_command` at vsr-player and give `player_args` two things:

```json
{
    "player_command": "/home/<user>/.local/bin/vsr-player",
    "player_args": [
        "--",
        "--ytdl-raw-options=cookies-from-browser=chrome,yes-playlist="
    ]
}
```

Which expands to:

```
vsr-player -- --ytdl-raw-options=cookies-from-browser=chrome,yes-playlist=  <page URL>
```

The app splits everything after `--`: items shaped like `--key=value` go to mpv (libmpv options), and anything not starting with `--` becomes a playlist entry. So the URL sitting at the end is fine.

What the two options do:

- **`cookies-from-browser=chrome`** lets yt-dlp read Chrome's login state directly. Content behind a login (private favourites, member-only videos) can't be resolved without it.
- **`yes-playlist=`** turns on the ytdl hook's playlist support. By default the hook adds `--no-playlist` to the yt-dlp command and resolves only the single video on that page; with this option it expands the whole list into playlist entries.

No `--terminal=yes`, no extra scripts — playback, skipping between entries and pausing are all the player's own business.

## Measurements

Setup: libmpv plus a real Bilibili favourites list (39 entries, login required), using `--cookies-from-browser chrome`.

| Case | Result |
|---|---|
| Single video page (no list parameter in the URL) | 1 entry, plays normally |
| List page without `yes-playlist=` | 1 entry, only the current video |
| List page with `yes-playlist=` | **39 entries**, expanded in about 2.0–2.4 s |
| Loading the same list again | Drops back to 1 entry, then re-expands to 39 — no stacking |
| Playing one of the expanded entries | Picture in about 3.9–4.2 s |

One expected behaviour worth knowing: per yt-dlp semantics, with `yes-playlist=` on, a "video + its playlist" URL (YouTube's `watch?v=…&list=…`) resolves to the whole list rather than the single video. If you only want one video, open it from the entry title, or turn the option off for that click.

## What this costs

Three things, all measured:

1. **Failures are silent.** Under rapid repeated calls, yt-dlp occasionally reports `Unable to extract initial state` (the site's anti-crawling) — 1 out of 10 runs here. The hook then treats the page URL as a single entry and carries on: no retry, no message, nothing outside to show that the list simply came up short.
2. **Every resolution re-reads the browser.** Each one runs `--cookies-from-browser chrome` (1.87–1.98 s), versus 1.06–1.21 s against an exported cookie file — about 0.8 s more per entry.
3. **Startup is slower than a single video.** Time to first frame: 3.2–3.5 s for a single video, 5.1–5.6 s for a list page (one full browser-cookie yt-dlp call to expand, another to resolve the first entry).

For a quick click-and-watch, none of this matters. It shows up when a list is long and you watch it entry by entry.

## Optional: a wrapper

If those three things bother you, put a wrapper between ff2mpv and the player. It does four things:

- exports cookies once per invocation (`yt-dlp --cookies-from-browser chrome`);
- expands entries with `yt-dlp --flat-playlist --print url` (URLs only, no full metadata);
- decides the shape from the entry count: several entries go through `--playlist=-` (URL list on stdin), 0 or 1 entries open the current URL directly;
- while playing, reads the player's stdout: `AV:` dismisses the startup notification, `[ytdl_hook] ERROR` increments a counter, and repeated failures terminate the player with a notification.

Gist (not shipped with the release; the script's header comment lists dependencies and argument rules — drop it in `~/.local/bin/` and `chmod +x`):

<https://gist.github.com/zhangmq/3f9df36b91214bdcd82f417ba9e50619>

Point the config at the script instead:

```json
{
    "player_command": "/home/<user>/.local/bin/vsr-player-wrapper-for-ff2mpv.py",
    "player_args": ["--"]
}
```

When it's worth it:

- **Watching a long list entry by entry** — the cookie file saves about 0.8 s per resolution. We checked the argv for each entry: it is always `--cookies <file>`, never back to the browser, so the browser is read once at the start and playback is unaffected afterwards.
- **You want to be told when resolution fails** — the wrapper sees yt-dlp's result, falls back to opening the current URL on 0/1 entries, and notifies, so a list can't quietly come up half empty.
- **The cost** — startup is slower than the direct config: about 3 s for a single video and about 1 s for a list page (the expansion would happen anyway there). Most of it is the export step (the current implementation runs yt-dlp against `https://httpbin.org/ip` once, 2.4–3.7 s). Folding the export into the first real fetch brings that down to about 1 s.

## Where the app-side `--playlist` came from

v0.4.1 added mpv-style list input: multiple positional arguments become a playlist, and `--playlist <file|->` reads one (`-` means stdin). It came directly out of the wrapper route — once the wrapper has expanded a list of addresses, it needs an entry point that plays them in order.

That feature doesn't depend on ff2mpv at all: multi-select from a file manager, scripts feeding a list, `-- a b` all use it. With the two-line config above, though, it goes unused — libmpv expands the list itself.

## Which to pick

- If you just want one click to work: use the two-line config. Single videos are fastest, and lists expand too.
- If lists are long and watched entry by entry, or you want to know when resolution fails: use the wrapper, and fold the cookie export into the first fetch while you're at it.
- Switching is one line: `player_command`.
