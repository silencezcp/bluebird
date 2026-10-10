"""Verify the packaged manual: size, navigation and self-containedness."""
from __future__ import annotations

import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
docs = os.path.join(ROOT, "dist", "BlueBird", "docs")

pdf = os.path.join(docs, "\u7528\u6237\u624b\u518c.pdf")
html = os.path.join(docs, "\u7528\u6237\u624b\u518c.html")

print("PDF  : %.2f MB" % (os.path.getsize(pdf) / 1048576))
import fitz  # noqa: E402
document = fitz.open(pdf)
links = sum(len(document[i].get_links()) for i in range(document.page_count))
outline = document.get_toc()
print("       %d pages, %d links, %d bookmarks" % (document.page_count,
                                                   links, len(outline)))
toc_page_links = [link for link in document[0].get_links()
                  if link.get("kind") == fitz.LINK_GOTO]
print("       table of contents page: %d clickable entries -> pages %s"
      % (len(toc_page_links),
         sorted({link["page"] + 1 for link in toc_page_links})[:6]))
document.close()

page = io.open(html, encoding="utf-8").read()
print()
print("HTML : %.2f MB" % (len(page) / 1048576))
print("       internal links: %d" % len(re.findall(r'<a href="#', page)))
print("       embedded fonts: %d" % page.count("@font-face"))
print("       embedded images: %d" % len(re.findall(r"data:image/", page)))
print("       external references left: %d"
      % len(re.findall(r'src="(?!data:)[^"]+"', page)))
print("       CLI chapter present: %s"
      % ("BlueBird-cli" in page or "命令行版本" in page))
