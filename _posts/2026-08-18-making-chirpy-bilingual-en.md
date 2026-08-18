---
layout: post
lang: en
hidden: true
title: "Making Chirpy bilingual the quick and dirty way"
date: 2026-08-18 12:00:00 +0800
categories: tech
tags: [jekyll, chirpy, i18n, github-pages]
permalink: /en/2026/08/18/making-chirpy-bilingual/
translation: /zh/2026/08/18/making-chirpy-bilingual/
description: Making Chirpy support Chinese/English article pairs with theme overrides plus one forked plugin — no SSG switch, no theme fork, with every pitfall we hit.
---

[中文](/zh/2026/08/18/making-chirpy-bilingual/)

Chirpy is a popular Jekyll theme for GitHub Pages. Its i18n support, however, only covers the *UI strings* (`_data/locales/` — buttons, labels, date formats). It does not solve the *content layer*: how a Chinese post and its English translation pair up, own separate URLs, and stay separated by language across every listing.

This post documents how I built that content layer the quick and dirty way — no full theme fork, no SSG switch, no second site. Just **site-level theme overrides plus one forked plugin**. Every pitfall below is real, and the Liquid one gets its own section.

## 0. The single-language reality of stock Chirpy

Out of the box, Chirpy 7.6 + GitHub Pages + Actions (the official starter's `pages-deploy.yml`):

- All posts share one list; the default URL is `/posts/:title/`
- UI language is site-wide, decided by `lang: zh-CN`
- There is no concept of "translation pairs" or "filter by language"

My requirements: each article has a Chinese and an English version at `/zh/...` and `/en/...`; the Chinese home lists Chinese posts only; English content has its own entry point at `/en/`; categories, archives, tags and search are all separated by language.

## 1. What Chirpy's i18n can and cannot do

**What it gives you out of the box:**

- Localized UI strings via `site.data.locales[page.lang]`
- **Per-page language**: a post with `lang: en` renders the whole page (sidebar, date formats, buttons) in English — we rely on this heavily

**What you must build yourself:**

- Translation linking between versions (no `translation` concept)
- Two URLs per article (the default gives one URL per title)
- Language filtering in lists / archives / categories / tags
- Bilingual SEO annotations (hreflang)

## 2. Content layer: pairing posts and URLs

The convention (this is what the blog uses for every bilingual post):

```
_posts/2026-08-18-slug-zh.md    # Chinese version
_posts/2026-08-18-slug-en.md    # English version
```

Front matter for the Chinese version:

```yaml
---
layout: post
lang: zh-CN                # UI follows: Chinese version → Chinese UI
title: "..."
date: 2026-08-18 12:00:00 +0800
categories: tech
tags: [jekyll, chirpy]
permalink: /zh/2026/08/18/slug/       # explicit permalink — avoids /posts/:title/ collision
translation: /en/2026/08/18/slug/     # the link to the other version
description: "..."
---
```

The English version adds two fields:

```yaml
lang: en
hidden: true              # kept off the Chinese home page
permalink: /en/2026/08/18/slug/
translation: /zh/2026/08/18/slug/
```

Key points:

- **The explicit `permalink` is mandatory.** Chirpy's default `/posts/:title/` would give both translations the same URL.
- **`hidden: true`** is a built-in filter in Chirpy's home layout (`where_exp: 'item', 'item.hidden != true'`) — English posts vanish from the Chinese home with zero changes to that layout.
- A one-line switch at the top of the body: `[English](...)` on the Chinese side, `[中文](...)` on the English side.
- An English landing page: a tiny custom layout (reusing Chirpy's card markup) listing all English posts at `/en/`, plus a sidebar tab.

## 3. Splitting lists and navigation by language

This step overrides a batch of theme templates. The rule of thumb: **either use a mechanism Chirpy already has, or override the theme file and add filtering.**

The override list (all site-level overrides; the theme itself stays untouched):

| File | What it does |
|---|---|
| `_includes/update-list.html` | "Recently Updated" filtered by the current language |
| `_includes/trending-tags.html` | trending tags filtered per language, links prefixed with `/en` |
| `_includes/related-posts.html` | related posts limited to the same language |
| `_includes/post-nav.html` | previous/next navigation stays inside the language |
| `_includes/sidebar.html` | sidebar shows only tabs of the current language + the language switch |
| `_includes/topbar.html` | breadcrumb "Home" points to the right language |
| `_layouts/categories.html` / `tags.html` / `archives.html` | category/tag/archive pages filtered by language |
| `_tabs/*-en.md` | English tab suite (categories/tags/archives/about) |

**Two easy-to-miss pitfalls:**

1. **The language-switch entry's link must switch too.** The switch tab shows "ENGLISH" → `/en/` on Chinese pages, but on English pages it must say 「中文」 and *point to `/`* — changing the label but not the href makes it a no-op.
2. **Sidebar Home / breadcrumb Home** behave the same way: on English pages they should go to `/en/`, not the Chinese `/`.

## 4. The big one: Liquid filters in `for` collection position silently no-op

This is the part where the quick-and-dirty nature of the whole setup really shows, and where the most time went.

**Symptom:** half of the language-filtered templates worked and half didn't — "Recently Updated" filtered correctly, the archives page listed every post in both languages, and both search index files were byte-identical (same md5).

**Debugging:** after cross-checking rendered pages and finding contradictory patterns, I added a temporary probe page that tested seven Liquid constructs in one build:

| Construct | Result |
|---|---|
| `{% raw %}{% for x in arr \| where: ... %}{% endraw %}` | ❌ **no-op** — returns the whole array |
| `{% raw %}{% assign x = arr \| where: ... %}{% endraw %}` (top level) | ✅ works |
| `{% raw %}{% assign x = arr \| where: ... %}{% endraw %}` (inside an include) | ✅ works |
| `{% raw %}{% for x in arr %}{% if x.lang == ... %}{% endraw %}` (plain control flow) | ✅ works |

Conclusion (tested on Jekyll 4.4.1 + Liquid 4.0.4): **filters in `{% raw %}{% for %}{% endraw %}` collection position are silently ignored** — no error, no warning, just the unfiltered array. A silent no-op is harder to debug than an explicit error.

**The rule we now follow everywhere:**

```liquid
{% raw %}
{%- comment -%} ✅ correct: filter in a top-level assign {%- endcomment -%}
{% assign lang_posts = site.posts | where: 'lang', 'zh-CN' %}
{% for post in lang_posts %}...{% endfor %}

{%- comment -%} ✅ correct: plain for + if {%- endcomment -%}
{% for post in site.posts %}
  {% if post.lang == 'zh-CN' %}...{% endif %}
{% endfor %}

{%- comment -%} ❌ wrong: filter in for collection position {%- endcomment -%}
{% for post in site.posts | where: 'lang', 'zh-CN' %}...{% endfor %}
{% endraw %}
```

## 5. Archive detail pages: forking jekyll-archives

Category/tag *detail pages* (`/categories/ai/`) are generated by the jekyll-archives plugin, which has no language concept — both languages ended up mixed in one page.

The call: fork the plugin (MIT, tiny codebase — four files). Three changes:

1. `read_tags` / `read_categories`: group by (name × language), one archive page per group
2. URL generation: prefix non-default languages → `/en/categories/ai/`; default language keeps `/categories/ai/` untouched
3. Write `page.lang` on the archive page → Chirpy's layouts localize automatically

Reference the fork from the Gemfile:

```ruby
gem "jekyll-archives", github: "zhangmq/jekyll-archives"
```

Result: `/categories/ai/` holds only Chinese posts, `/en/categories/ai/` only English ones. The diff is a few dozen lines, default-language behavior is unchanged, and merging upstream updates stays easy.

## 6. Bilingual SEO and search

- **hreflang**: post pages emit `<link rel="alternate" hreflang="zh-CN/en/x-default">` from the `translation` field, telling search engines the two URLs are translations of one article. Implemented by overriding `_includes/head.html` (a copy of the theme's head plus the hreflang block; Chirpy renders its own title with `seo title=false`).
- **Search**: the default search index is one site-wide JSON. Split into `search-zh-CN.json` / `search-en.json` and override `search-loader.html` to load the one matching the current language.
- **og:image / JSON-LD author**: pure config (`social_preview_image` + `author`) — and it upgraded the twitter:card to `summary_large_image` for free.

## 7. Cheat sheet: the publishing convention

Steps for every new bilingual post:

1. Write `_posts/YYYY-MM-DD-slug-zh.md`: `lang: zh-CN` + `permalink: /zh/YYYY/MM/DD/slug/` + `translation` pointing at the English version + a `[English](...)` link at the top
2. Write `_posts/YYYY-MM-DD-slug-en.md`: `lang: en` + `hidden: true` + `permalink: /en/YYYY/MM/DD/slug/` + `translation` pointing at the Chinese version
3. Add `description` to both (used for card excerpts and SEO meta)
4. Push to master — GitHub Actions builds and deploys in about a minute
5. Categories, tags, archives, search and hreflang all follow automatically

As for the "writing everything twice" concern — I'm lazy, and most of my articles are written by an AI anyway, so producing both versions comes almost for free.

## 8. Trade-offs

**What this costs you:**

- A batch of overridden templates (8+ files) — **re-check them after every Chirpy upgrade** (we're pinned at 7.6; diff the overrides before bumping)
- Reliance on a specific Liquid behavior (the `for`-filter no-op). The "filter in a top-level assign" workaround is safe regardless of Liquid version, so this is low-risk
- The forked jekyll-archives needs manual sync with upstream (the diff is small, so merging is easy)

**Why it's good enough:**

- No full theme fork, no second site, no extra build system
- Everything is a **site-level override layer** — the theme stays stock, and you can always fall back to pure Chirpy
- Content is decoupled from the theme: the front-matter convention survives a future theme switch untouched

---

**Live demo**: [zhangmq.github.io](https://zhangmq.github.io)
