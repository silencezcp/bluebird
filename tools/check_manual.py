"""Check a built manual: size, navigation, and that it is self contained.

    python tools/check_manual.py                 # every book in docs
    python tools/check_manual.py 用户手册         # just one
    python tools/check_manual.py --dist          # the copies in dist/
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = ("\u7528\u6237\u624b\u518c", "\u5f00\u53d1\u624b\u518c")


def report(where: str, stem: str) -> bool:
    html = os.path.join(where, stem + ".html")
    pdf = os.path.join(where, stem + ".pdf")
    if not (os.path.isfile(html) or os.path.isfile(pdf)):
        print("  %s: not built" % stem)
        return False

    print("  %s" % stem)
    if os.path.isfile(pdf):
        try:
            import fitz
            document = fitz.open(pdf)
            links = sum(len(document[i].get_links())
                        for i in range(document.page_count))
            goto = [link for link in document[0].get_links()
                    if link.get("kind") == fitz.LINK_GOTO]
            print("    PDF  %5.2f MB, %d pages, %d links, %d bookmarks"
                  % (os.path.getsize(pdf) / 1048576, document.page_count,
                     links, len(document.get_toc())))
            if goto:
                print("         table of contents: %d clickable entries"
                      % len(goto))
            document.close()
        except ImportError:
            print("    PDF  %5.2f MB (install PyMuPDF to check navigation)"
                  % (os.path.getsize(pdf) / 1048576))

    if os.path.isfile(html):
        page = io.open(html, encoding="utf-8").read()
        external = re.findall(r'src="(?!data:)[^"]+"', page)
        print("    HTML %5.2f MB, %d internal links, %d fonts, %d images"
              % (len(page) / 1048576, len(re.findall(r'<a href="#', page)),
                 page.count("@font-face"), len(re.findall(r"data:image/", page))))
        if external:
            print("         ! %d external reference(s): %s"
                  % (len(external), external[:3]))
        chapters = re.findall(r'<li class="lvl2"><a href="#[^"]*">(.*?)</a>',
                              page)
        print("         chapters: %s" % " / ".join(chapters[:3]) or "-")
    return True


def main() -> int:
    use_dist = "--dist" in sys.argv
    names = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    where = os.path.join(ROOT, "dist", "BlueBird", "docs") if use_dist \
        else os.path.join(ROOT, "docs")
    print("checking %s" % where)
    print()
    stems = names or list(BOOKS)
    found = sum(1 for stem in stems if report(where, stem))
    print()
    print("%d of %d book(s) present" % (found, len(stems)))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
