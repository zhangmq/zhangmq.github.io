---
layout: page
permalink: /debug-probe/
lang: zh-CN
---
# Liquid 探测

- A for+where 字面量: `{% for post in site.posts | where: 'lang', 'zh-CN' %}{{ post.title }};{% endfor %}`
- B assign+where 字面量: `{% assign bp = site.posts | where: 'lang', 'zh-CN' %}{{ bp | size }}`
- C assign+where 变量: `{% assign cp = site.posts | where: 'lang', page.lang %}{{ cp | size }}`
- D where_exp: `{% assign dp = site.posts | where_exp: 'item', 'item.lang == "zh-CN"' %}{{ dp | size }}`
- E site.posts.size: `{{ site.posts | size }}`
- F 纯 for + if: `{% for post in site.posts %}{% if post.lang == 'zh-CN' %}{{ post.title }};{% endif %}{% endfor %}`
- G include 内 where: `{% include debug-include.html %}`
