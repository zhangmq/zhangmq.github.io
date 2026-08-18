---
layout: post
lang: zh-CN
title: "如何用很糙的办法让 Chirpy 支持双语文章"
date: 2026-08-18 12:00:00 +0800
categories: tech
tags: [jekyll, chirpy, i18n, github-pages]
permalink: /zh/2026/08/18/making-chirpy-bilingual/
translation: /en/2026/08/18/making-chirpy-bilingual/
description: 不换 SSG、不 fork 整个主题，只用覆盖层 + 一个插件 fork，让 Chirpy 支持中英双语文章——含全部踩坑记录。
---

[English](/en/2026/08/18/making-chirpy-bilingual/)

Chirpy 是 GitHub Pages 上很流行的 Jekyll 主题。但它的国际化（i18n）只覆盖**界面文案**（`_data/locales/` 里的按钮、标签、日期格式），不解决**内容层**问题：一篇中文文章和它的英文翻译如何配对、如何各占一个 URL、如何按语言分开展示。

这篇文章记录我怎么用一套"很糙"的办法补上内容层——不 fork 整个主题、不换 SSG、不维护两套独立站点，只用了**主题覆盖层 + 一个插件 fork**。全程真实踩坑，Liquid 的坑单独拎出来讲。

## 0. 背景：默认 Chirpy 的单语言现实

开箱的 Chirpy（7.6）+ GitHub Pages + Actions（官方 starter 的 `pages-deploy.yml`）：

- 所有文章进同一个列表，默认 URL 是 `/posts/:title/`
- 界面语言由 `lang: zh-CN` 决定，全站统一
- 没有任何"翻译配对"、"按语言过滤"的概念

我的需求：同一篇文章的中英文各占一个 URL（`/zh/...` 和 `/en/...`），中文首页只列中文，英文内容有独立入口 `/en/`，分类/归档/标签/搜索全部按语言分开。

## 1. 摸清边界：Chirpy 的 i18n 能做什么、不能做什么

**能做的：**

- 界面文案多语言：`site.data.locales[page.lang]`
- **每页语言跟随**：文章的 `lang: en` 会让整页界面（侧边栏、日期格式、按钮）自动切到英文——这个机制我们重度使用

**不能做的（所以要自己补）：**

- 中英版本互链（没有 `translation` 概念）
- 双 URL（默认一个标题只有一个 URL）
- 列表/归档/分类/标签按语言过滤
- 搜索引擎的双语标注（hreflang）

## 2. 内容层：文章配对 + 双 URL

核心约定（现在本站发双语文章就按这个来）：

```
_posts/2026-08-18-slug-zh.md    # 中文版
_posts/2026-08-18-slug-en.md    # 英文版
```

两篇的 front matter（差异点标注）：

```yaml
---
layout: post
lang: zh-CN                # 界面跟随：中文版 → 中文 UI
title: "..."
date: 2026-08-18 12:00:00 +0800
categories: tech
tags: [jekyll, chirpy]
permalink: /zh/2026/08/18/slug/       # 显式 permalink，绕开默认 /posts/:title/ 撞车
translation: /en/2026/08/18/slug/     # 互链
description: "..."
---
```

英文版多两个字段：

```yaml
lang: en
hidden: true              # 不进中文首页
permalink: /en/2026/08/18/slug/
translation: /zh/2026/08/18/slug/
```

要点：

- **显式 `permalink` 是必须的**。Chirpy 默认 `/posts/:title/`，两篇同名翻译会撞同一个 URL。
- **`hidden: true`** 是 Chirpy 首页布局内置的过滤开关（`where_exp: 'item', 'item.hidden != true'`），英文版直接消失，中文首页零改动。
- 正文顶部放一行互链：中文版 `[English](...)`，英文版 `[中文](...)`。
- 英文落地页：一个自定义 layout（复用 Chirpy 的卡片样式）列全部英文文章，挂到 `/en/`，加一个侧边栏 tab。

## 3. 列表与导航按语言拆分

这一步要覆盖一批主题模板。原则：**每个按语言过滤的地方，要么用 Chirpy 已有的机制，要么覆盖主题文件加过滤**。

覆盖清单（都是站点级覆盖，不动主题本体）：

| 文件 | 干什么 |
|---|---|
| `_includes/update-list.html` | 侧边栏「最近更新」按当前语言过滤 |
| `_includes/trending-tags.html` | 「热门标签」按语言过滤 + 链接加 `/en` 前缀 |
| `_includes/related-posts.html` | 相关文章只推荐同语言 |
| `_includes/post-nav.html` | 上一篇/下一篇只在本语言内跳 |
| `_includes/sidebar.html` | 侧边栏只显示当前语言的 tab + 语言切换入口 |
| `_includes/topbar.html` | 面包屑的 Home 链接按语言指向 |
| `_layouts/categories.html` / `tags.html` / `archives.html` | 分类/标签/归档页按语言过滤 |
| `_tabs/*-en.md` | 英文版 tab 套件（分类/标签/归档/关于） |

**两个容易忽略的小坑：**

1. **语言切换入口的链接也要按语言换**。侧边栏的切换 tab 在中文界面显示 "ENGLISH" 指向 `/en/`，在英文界面要显示「中文」并且**指向 `/`**——只换标签文字不换 href，点了等于没点。
2. **侧边栏 Home / 面包屑的 Home** 同理：英文页面里点 Home 应该回 `/en/` 而不是中文首页 `/`。

## 4. 最大的坑：Liquid 的 for 集合过滤器不生效

这是整套方案最"糙"的地方，也是花时间最多的地方。

**现象**：按语言过滤的模板一半生效一半不生效——「最近更新」过滤了，归档页却把中英全列出来，搜索索引两份文件内容一模一样（md5 都相同）。

**排查**：先在线上核对渲染结果，发现规律矛盾；然后加了一个临时探测页，把 7 种写法全部实测了一遍：

| 写法 | 实测结果 |
|---|---|
| `{% for x in arr \| where: ... %}` | ❌ **不生效**，返回全部元素 |
| `{% assign x = arr \| where: ... %}`（顶层） | ✅ 生效 |
| `{% assign x = arr \| where: ... %}`（include 内） | ✅ 生效 |
| `{% for x in arr %}{% if x.lang == ... %}`（纯控制流） | ✅ 生效 |

结论（Jekyll 4.4.1 + Liquid 4.0.4 实测）：**`{% for %}` 集合位置的过滤器被静默忽略**，不报错、不警告，直接返回未过滤的集合——静默失败比直接报错更难排查。

**规避铁律**（现在全站遵守）：

```liquid
{%- comment -%} ✅ 正确：assign 顶层过滤 {%- endcomment -%}
{% assign lang_posts = site.posts | where: 'lang', 'zh-CN' %}
{% for post in lang_posts %}...{% endfor %}

{%- comment -%} ✅ 正确：纯 for + if {%- endcomment -%}
{% for post in site.posts %}
  {% if post.lang == 'zh-CN' %}...{% endif %}
{% endfor %}

{%- comment -%} ❌ 错误：for 集合位置用过滤器 {%- endcomment -%}
{% for post in site.posts | where: 'lang', 'zh-CN' %}...{% endfor %}
```

## 5. 归档详情页：fork jekyll-archives

分类/标签的**详情页**（`/categories/ai/` 这种）由 jekyll-archives 插件生成，它不支持按语言分组——中英文混在一个分类页里。

选择：fork 插件（MIT 协议，源码很小，只有 4 个文件）。改了 3 处：

1. `read_tags` / `read_categories`：按（分类 × 语言）分组，每组生成一个归档页
2. URL 生成：非默认语言加前缀 → `/en/categories/ai/`，默认语言保持 `/categories/ai/` 不变
3. 归档页写入 `page.lang` → Chirpy 布局自动本地化

Gemfile 直接引用 fork：

```ruby
gem "jekyll-archives", github: "zhangmq/jekyll-archives"
```

效果：`/categories/ai/` 只有中文文章，`/en/categories/ai/` 只有英文文章。改动只有几十行，且默认语言的行为完全不变，上游升级时可以随时对照合并。

## 6. 双语 SEO 与搜索

- **hreflang**：文章页根据 `translation` 字段自动生成 `<link rel="alternate" hreflang="zh-CN/en/x-default">`，告诉搜索引擎两个 URL 是同一篇的翻译。实现方式是覆盖 `_includes/head.html`（复制主题原版 + 插入 hreflang 块，`seo title=false` 由 Chirpy 自己处理标题）。
- **搜索**：默认的搜索索引是全站一份 JSON。按语言拆成 `search-zh-CN.json` / `search-en.json`，覆盖 `search-loader.html` 按当前语言加载。
- **og:image / JSON-LD author**：配置项就能解决（`social_preview_image` + `author`），顺带把 twitter:card 升级成了 summary_large_image。

## 7. 备忘：本站的发布约定（可直接抄）

新发一篇双语文章的完整步骤：

1. 写 `_posts/YYYY-MM-DD-slug-zh.md`：`lang: zh-CN` + `permalink: /zh/YYYY/MM/DD/slug/` + `translation` 指向英文版 + 正文顶部 `[English](...)`
2. 写 `_posts/YYYY-MM-DD-slug-en.md`：`lang: en` + `hidden: true` + `permalink: /en/YYYY/MM/DD/slug/` + `translation` 指向中文版
3. 两篇都写 `description`（卡片摘要 + SEO meta 用）
4. 推送到 master，GitHub Actions 自动构建部署（约 1-2 分钟）
5. 分类、标签、归档、搜索、hreflang 全部自动按语言处理，无需额外配置

至于"双语文章要写两遍"的顾虑：我很懒，文章基本都是让 AI 写的，双语版本顺手就出来了，似乎也不是很麻烦。

## 8. 局限与取舍

**这套方案的代价：**

- 覆盖了一批主题模板（8+ 个文件），**Chirpy 升级后要复查**哪些覆盖还需要调整——版本锁在 7.6，升级先 diff 覆盖文件
- 依赖了 Liquid 的特定行为（for 过滤器不生效的规避），换个 Jekyll 版本可能行为变化，但"assign 顶层过滤"是安全写法，不受影响
- fork 的 jekyll-archives 要手动跟上游同步（改动很小，合并容易）

**为什么说"够用"：**

- 不 fork 整个主题、不维护两套站点、不引入第二个构建系统
- 所有自定义都是**站点级覆盖层**，主题本体保持原样，随时可以退回到纯 Chirpy
- 文章内容与主题完全解耦，哪天换主题，文章本身（front matter 约定）可以原样带走

---

**Demo 直达**：[zhangmq.github.io](https://zhangmq.github.io)
