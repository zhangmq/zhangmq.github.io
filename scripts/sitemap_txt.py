#!/usr/bin/env python3
"""Generate a plain-text sitemap (one URL per line) from the built XML sitemap.

Why: GitHub Pages serves `.xml` as `application/xml` *without* a charset, and
Google Search Console has a long history of failing to read sitemaps on
`*.github.io` even when the XML is well-formed. Pages serves `.txt` as
`text/plain; charset=utf-8`, and Google's URL-list format is plain text, so
this file is the charset-friendly fallback.
"""

import sys
import xml.etree.ElementTree as ET

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def main(site_dir: str) -> int:
    root = ET.parse(f"{site_dir}/sitemap.xml").getroot()
    urls = [el.text.strip() for el in root.findall("sm:url/sm:loc", NS) if el.text]
    if not urls:
        print("no URLs found in sitemap.xml", file=sys.stderr)
        return 1

    out = f"{site_dir}/sitemap.txt"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(urls) + "\n")
    print(f"{out}: {len(urls)} urls")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "_site"))
