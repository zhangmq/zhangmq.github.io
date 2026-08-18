---
layout: post
lang: zh-CN
title: "你好，世界"
date: 2026-08-18 12:00:00 +0800
categories: misc
tags: [blog]
permalink: /zh/2026/08/18/hello-world/
translation: /en/2026/08/18/hello-world/
description: 博客的第一篇文章。
---

[English](/en/2026/08/18/hello-world/)

这是博客的第一篇文章。

用 Jekyll 写博客很简单：在 `_posts/` 下新建 `YYYY-MM-DD-标题-zh.md`（中文）或 `-en.md`（英文），
开头写一段 YAML 头信息（标题、日期、语言、分类、标签、permalink、translation），正文直接用 Markdown 写。
推送到 GitHub 后，Actions 会自动构建发布。

本站的双语约定：

- 中文篇：`lang: zh-CN`，`permalink: /zh/2026/08/18/标题/`，正文顶部放 `[English](...)` 链接
- 英文篇：`lang: en`、`hidden: true`（不进中文首页），`permalink: /en/2026/08/18/标题/`
- 两篇通过 `translation` 字段互相链接
