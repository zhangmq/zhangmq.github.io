---
layout: post
lang: en
hidden: true
title: "Hello, World"
date: 2026-08-18 12:00:00 +0800
categories: misc
tags: [blog]
permalink: /en/2026/08/18/hello-world/
translation: /zh/2026/08/18/hello-world/
description: The first post of the blog.
---

[中文](/zh/2026/08/18/hello-world/)

This is the first post of the blog.

Writing with Jekyll is simple: add a `YYYY-MM-DD-title-zh.md` (Chinese) or `-en.md` (English)
file to `_posts/`, start it with YAML front matter (title, date, language, categories, tags,
permalink, translation), and write the body in Markdown. GitHub Actions rebuilds the site on push.

Bilingual conventions on this site:

- Chinese posts: `lang: zh-CN`, `permalink: /zh/2026/08/18/title/`, with an `[English](...)` link at the top
- English posts: `lang: en`, `hidden: true` (kept off the Chinese home page), `permalink: /en/2026/08/18/title/`
- The pair links to each other via the `translation` front matter field.
