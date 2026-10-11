#!/usr/bin/env python
"""Render docs/<manual>.md to a self-contained HTML and a printable PDF.

No external libraries: a small Markdown subset is converted here, the styling
matches the application's cream palette, and the screenshots are embedded as
base64 so the HTML file stays portable. The PDF is produced by QtWebEngine
(``printToPdf``), which is already a dependency of the app.

    D:\\DSH_Workspaces\\Ftp\\python.exe tools\\build_manual.py
"""

from __future__ import annotations

import base64
import html
import io
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

#: pull the version and author straight from the package so the banner can
#: never drift from the code
try:
    sys.path.insert(0, ROOT)
    from ftpclient import __author__, __version__ as _VERSION
except Exception:                                # pragma: no cover
    __author__, _VERSION = "silence", "1.32.0"

#: The two books.  The user manual is the one that ships inside the
#: executable's docs/ folder; the developer manual never leaves the repository.
#: ``prefix`` keeps the heading anchors distinct, since both books have
#: chapters with the same titles.
BOOKS = (
    {
        "source": "\u7528\u6237\u624b\u518c.md",
        "title": "\u9752\u9e1f BlueBird \u7528\u6237\u624b\u518c",
        "subtitle": "\u7248\u672c %s \u00b7 \u4f5c\u8005\uff1a%s \u00b7 "
                    "\u9002\u7528\u4e8e\u6253\u5305\u7248 BlueBird.exe \u00b7 "
                    "Windows",
        "footer": "\u7528\u6237\u624b\u518c",
        "prefix": "u-",
    },
    {
        "source": "\u5f00\u53d1\u624b\u518c.md",
        "title": "\u9752\u9e1f BlueBird \u5f00\u53d1\u624b\u518c",
        "subtitle": "\u7248\u672c %s \u00b7 \u4f5c\u8005\uff1a%s \u00b7 "
                    "Python 3.8.3 + PyQt5 5.15.11 \u00b7 Windows",
        "footer": "\u5f00\u53d1\u624b\u518c",
        "prefix": "d-",
    },
)

TOC_LABEL = "\u76ee\u5f55"

#: prepended to every heading anchor so the two books cannot share one
ANCHOR_PREFIX = "u-"

#: marks a list item line so later steps can find it inside the output list
CONTINUATION_MARK = "\x00li\x00"

# ---------------------------------------------------------------------------
# The rest of the module works on one book at a time; main() fills these in.
# ---------------------------------------------------------------------------
SOURCE = os.path.join(DOCS, BOOKS[0]["source"])
HTML_OUT = os.path.join(DOCS, "\u7528\u6237\u624b\u518c.html")
PDF_OUT = os.path.join(DOCS, "\u7528\u6237\u624b\u518c.pdf")
TITLE = BOOKS[0]["title"]
SUBTITLE = BOOKS[0]["subtitle"] % (_VERSION, __author__)
FOOTER = ("BlueBird %s \u00b7 %s \u00b7 \u4f5c\u8005\uff1a%s"
          % (_VERSION, BOOKS[0]["footer"], __author__))


def select_book(book: "dict") -> None:
    """Point the module level paths at one book."""
    global SOURCE, HTML_OUT, PDF_OUT, TITLE, SUBTITLE, FOOTER, ANCHOR_PREFIX
    SOURCE = os.path.join(DOCS, book["source"])
    stem = os.path.splitext(book["source"])[0]
    HTML_OUT = os.path.join(DOCS, stem + ".html")
    PDF_OUT = os.path.join(DOCS, stem + ".pdf")
    TITLE = book["title"]
    SUBTITLE = book["subtitle"] % (_VERSION, __author__)
    FOOTER = ("BlueBird %s \u00b7 %s \u00b7 \u4f5c\u8005\uff1a%s"
              % (_VERSION, book["footer"], __author__))
    ANCHOR_PREFIX = book["prefix"]

# ---------------------------------------------------------------------------
# Markdown -> HTML (the subset this manual uses)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """GitHub-style heading anchor, keeping CJK characters."""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = html.unescape(cleaned).strip().lower()
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned.strip("-") or "section"


def img_tag(match: "re.Match[str]") -> str:
    alt, src = match.group(1), match.group(2)
    return '<img src="%s" alt="%s">' % (src, html.escape(alt, quote=True))


def link_tag(match: "re.Match[str]") -> str:
    label, href = match.group(1), match.group(2)
    return '<a href="%s">%s</a>' % (html.escape(href, quote=True), label)


def inline(text: str) -> str:
    """Escape then apply the inline Markdown this manual uses."""
    codes: List[str] = []

    def stash(match: "re.Match[str]") -> str:
        codes.append(match.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_tag, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link_tag, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    for index, code in enumerate(codes):
        text = text.replace("\x00%d\x00" % index,
                            "<code>%s</code>" % html.escape(code, quote=False))
    return text


def is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", line)) and "-" in line


def split_row(line: str) -> List[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def _is_block_start(line: str) -> bool:
    """True when a line begins a new block rather than continuing a paragraph."""
    stripped = line.lstrip()
    if not stripped:
        return True
    if stripped[0] in "#>|":
        return True
    if stripped.startswith("```"):
        return True
    if re.match(r"^[-*+]\s+\S", stripped):
        return True
    if re.match(r"^\d+[.)]\s+\S", stripped):
        return True
    if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", stripped):
        return True
    if stripped.startswith(("![", "[!")):
        return True
    return False


#: Box-drawing and block characters.  Consecutive lines made of these are an
#: ASCII art diagram: their line breaks are meaningful, so they are never
#: joined, even though they look like wrapped text.
DIAGRAM_CHARS = "\u2500\u2502\u250c\u2510\u2514\u2518\u251c\u2524\u252c" \
                "\u2534\u253c\u2550\u2551\u2554\u2557\u255a\u255d\u2560" \
                "\u2563\u2566\u2569\u256c\u25a0\u25a1"


def _looks_like_diagram(text: str) -> bool:
    """True for a line that is part of an ASCII art frame."""
    stripped = text.strip()
    return bool(stripped) and any(char in DIAGRAM_CHARS for char in stripped)


def _join_soft_wraps(markdown: str) -> str:
    """Join lines that are wrapped for width, not meant as separate blocks.

    Markdown wraps a paragraph, and the continuation lines of a list item, at
    whatever column fits; a newline inside one is a space, not a break.  The
    converter below is line oriented, so without this every wrapped line became
    its own block: paragraphs were split mid sentence, and a numbered list whose
    items have continuation lines came out as one separate ``<ol>`` per item,
    which browsers then renumber from 1.

    Two shapes are handled:

    * plain wrapping, where the next line continues the sentence;
    * a list item's continuation, which markdown indents and which may follow a
      blank line - that one has to stay attached to its item.

    A line ending in a backslash keeps its break, which is what the ASCII art
    diagrams use.
    """
    out: "List[str]" = []
    buffer = ""
    blank_pending = False      # a blank line just went by

    def flush() -> None:
        nonlocal buffer
        if buffer:
            out.append(buffer)
            buffer = ""

    #: A markdown list is "loose" when its items are separated by blank lines,
    #: and then the item's continuation is indented by four spaces.  Anything
    #: indented less, or that starts a block of its own, is not a continuation.
    LOOSE_INDENT = 4
    LIST_ITEM = re.compile(r"^ {0,3}(?:\d+[.)]|[-*+])\s+\S")

    def starts_list(text: str) -> bool:
        return bool(LIST_ITEM.match(text))

    def indented_continuation(text: str) -> bool:
        """An indented line continuing the item above, not a block of its own."""
        if not text[:1].isspace():
            return False
        stripped = text.lstrip()
        if not stripped or stripped[0] in "|>#" or stripped.startswith("```"):
            return False
        if starts_list(stripped):
            return False
        return (len(text) - len(stripped)) >= LOOSE_INDENT

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            out.append("")
            blank_pending = True
            continue

        # a continuation of the list item above, possibly after a blank line
        if buffer and (indented_continuation(line)
                       or (blank_pending and starts_list(buffer))):
            buffer += stripped if (not buffer[-1].isascii()
                                   or not stripped[:1].isascii()) else \
                " " + stripped
            blank_pending = False
            continue

        if stripped.endswith("\\"):
            buffer += line.rstrip()[:-1]
            flush()
            blank_pending = False
            continue
        if not buffer:
            # A list item is a block, but its indented continuations belong to
            # it, so the item has to open the buffer rather than be emitted on
            # its own - otherwise the item and its continuation end up as two
            # separate lists, which is the renumbering bug.
            out.append(line)
            blank_pending = False
            continue
        # an ASCII art frame keeps its own line breaks
        if _looks_like_diagram(buffer) and _looks_like_diagram(line):
            flush()
            out.append(line)
            blank_pending = False
            continue
        if _is_block_start(line) and not starts_list(line):
            flush()
            out.append(line)
            blank_pending = False
            continue
        joiner = "" if (not buffer[-1].isascii() or not stripped[:1].isascii()) \
            else " "
        buffer += joiner + stripped
        blank_pending = False
    flush()
    return "\n".join(out)


def convert(markdown: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    """Return (html_body, [(level, text, anchor)])."""
    lines = _join_soft_wraps(markdown).splitlines()
    out: List[str] = []
    headings: List[Tuple[int, str, str]] = []
    used: Dict[str, int] = {}
    index = 0
    list_stack: List[str] = []
    #: indentation of the marker that opened the innermost list, for deciding
    #: whether an indented line continues that item
    list_indent = 0
    in_quote = False

    def close_lists() -> None:
        while list_stack:
            out.append("</%s>" % list_stack.pop())

    def close_quote() -> None:
        nonlocal in_quote
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    while index < len(lines):
        line = lines[index]

        # ---- fenced code -------------------------------------------
        if re.match(r"^\s*```", line):
            close_lists()
            close_quote()
            language = line.strip().strip("`").strip()
            index += 1
            buffer: List[str] = []
            while index < len(lines) and not re.match(r"^\s*```\s*$", lines[index]):
                buffer.append(lines[index])
                index += 1
            index += 1
            css = ' class="lang-%s"' % language if language else ""
            out.append("<pre%s><code>%s</code></pre>"
                       % (css, html.escape("\n".join(buffer), quote=False)))
            continue

        # ---- horizontal rule ---------------------------------------
        if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
            close_lists()
            close_quote()
            out.append("<hr>")
            index += 1
            continue

        # ---- table --------------------------------------------------
        if "|" in line and index + 1 < len(lines) \
                and is_table_separator(lines[index + 1]):
            close_lists()
            close_quote()
            header = split_row(line)
            index += 2
            rows: List[List[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(split_row(lines[index]))
                index += 1
            parts = ["<table>", "<thead><tr>"]
            for cell in header:
                parts.append("<th>%s</th>" % inline(cell))
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                for position in range(len(header)):
                    value = row[position] if position < len(row) else ""
                    parts.append("<td>%s</td>" % inline(value))
                parts.append("</tr>")
            parts.append("</tbody></table>")
            out.append("".join(parts))
            continue

        # ---- blockquote --------------------------------------------
        if re.match(r"^\s*>\s?", line):
            if not in_quote:
                close_lists()
                out.append("<blockquote>")
                in_quote = True
            out.append("<p>%s</p>" % inline(re.sub(r"^\s*>\s?", "", line)))
            index += 1
            continue
        close_quote()

        # ---- headings ----------------------------------------------
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_lists()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            # the prefix keeps anchors distinct between the two books, which
            # share chapter titles; within a page it changes nothing
            anchor = ANCHOR_PREFIX + slugify(text)
            if anchor in used:
                used[anchor] += 1
                anchor = "%s-%d" % (anchor, used[anchor])
            else:
                used[anchor] = 0
            headings.append((level, re.sub(r"[*`]", "", text), anchor))
            out.append('<h%d id="%s">%s</h%d>'
                       % (level, anchor, inline(text), level))
            index += 1
            continue

        # ---- lists --------------------------------------------------
        bullet = re.match(r"^(\s*)([-*+])\s+(.*)$", line)
        ordered = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if bullet or ordered:
            match = bullet or ordered
            indent = len(match.group(1))
            kind = "ul" if bullet else "ol"
            depth = (indent // 2) + 1
            while len(list_stack) > depth:
                out.append("</%s>" % list_stack.pop())
            if len(list_stack) < depth:
                while len(list_stack) < depth:
                    out.append("<%s>" % kind)
                    list_stack.append(kind)
            out.append("<li>%s%s</li>" % (CONTINUATION_MARK,
                                          inline(match.group(3))))
            list_indent = indent
            index += 1
            continue

        # ---- a list item's continuation -----------------------------
        # Markdown indents the rest of an item under its marker, and that text
        # belongs inside the same <li>.  Emitting it as a paragraph instead
        # closes the list, and a browser then renumbers the following items
        # from 1 - which is exactly what the known-limitations list did.
        if list_stack and line[:1].isspace() and line.strip() \
                and (len(line) - len(line.lstrip())) > list_indent:
            stripped = line.strip()
            if stripped[0] not in "|>#" and not re.match(
                    r"^(\s*)([-*+]|\d+[.)])\s+\S", line) \
                    and not stripped.startswith("```"):
                out[-1] = out[-1].replace(
                    "</li>", " " + inline(stripped) + "</li>")
                index += 1
                continue

        close_lists()

        # ---- blank / paragraph -------------------------------------
        if not line.strip():
            index += 1
            continue
        out.append("<p>%s</p>" % inline(line))
        index += 1

    close_lists()
    close_quote()
    # the marker that let a continuation find its item is internal only
    return ("\n".join(out).replace(CONTINUATION_MARK, ""), headings)


# ---------------------------------------------------------------------------
# Styling - same cream family as the application
# ---------------------------------------------------------------------------

CSS = """
:root {
  --window:#F7F3EA; --surface:#FFFCF5; --alt:#FBF7EE; --sunken:#F1EBDE;
  --border:#E2D8C4; --border-strong:#D2C4A9; --text:#3B352C; --muted:#8A8072;
  --accent:#3E7CB1; --folder:#2E6FA8;
}
* { box-sizing: border-box; }
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
body {
  margin: 0 auto; padding: 34px 46px 60px 46px; max-width: 940px;
  background: var(--window); color: var(--text);
  font-family: "BlueBird Sans", sans-serif;
  font-size: 14.5px; line-height: 1.78;
}
h1, h2, h3, h4 { color: var(--text); line-height: 1.32; font-weight: 700; }
h1 { font-size: 30px; margin: 0 0 6px 0; letter-spacing: .5px; }
h2 {
  font-size: 22px; margin: 40px 0 14px 0; padding: 8px 0 8px 12px;
  border-left: 5px solid var(--accent);
  background: linear-gradient(90deg, rgba(62,124,177,.10), rgba(62,124,177,0));
  border-radius: 0 8px 8px 0;
}
h3 { font-size: 17.5px; margin: 28px 0 10px 0; color: var(--folder); }
h4 { font-size: 15.5px; margin: 20px 0 8px 0; }
p { margin: 10px 0; }
a { color: var(--accent); text-decoration: none;
    border-bottom: 1px solid rgba(62,124,177,.35); }
hr { border: none; border-top: 1px solid var(--border); margin: 30px 0 24px 0; }
strong { color: #2F2A23; }
code {
  background: var(--sunken); border: 1px solid var(--border);
  border-radius: 5px; padding: 1px 5px; font-size: 13px;
  /* Code uses the mono subset for ASCII, and the sans subset for anything the
     mono font has no glyph for - Chinese inside a code span, most often.  The
     fallback must be a page font: naming a system monospace family here makes
     WebEngine embed that entire file (Consolas alone added 9 MB). */
  font-family: "BlueBird Mono", "BlueBird Sans";
  color: #23578A;
}
pre {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 13px 16px; overflow-x: auto;
}
pre code {
  background: none; border: none; padding: 0; color: var(--text);
  font-size: 13px; line-height: 1.65;
}
table {
  border-collapse: separate; border-spacing: 0; width: 100%;
  margin: 14px 0 18px 0; background: var(--surface);
  border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
  font-size: 13.6px;
}
th {
  background: var(--sunken); color: var(--muted); font-weight: 700;
  text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border);
}
td { padding: 8px 12px; border-bottom: 1px solid #F0E9DA; vertical-align: top; }
tr:last-child td { border-bottom: none; }
tbody tr:nth-child(even) { background: var(--alt); }
blockquote {
  margin: 14px 0; padding: 10px 16px; background: #FDF6E6;
  border-left: 4px solid #C08A2E; border-radius: 0 8px 8px 0; color: #6B5F4A;
}
blockquote p { margin: 4px 0; }
ul, ol { margin: 10px 0; padding-left: 26px; }
li { margin: 5px 0; }
img {
  display: block; max-width: 100%; height: auto; margin: 18px auto;
  border: 1px solid var(--border-strong); border-radius: 10px;
  box-shadow: 0 3px 12px rgba(60,50,30,.10); background: var(--surface);
}
.doc-header {
  background: linear-gradient(135deg, #3E7CB1, #23578A 70%);
  color: #FFFFFF; border-radius: 14px; padding: 26px 30px; margin-bottom: 26px;
}
.doc-header h1 { color: #FFFFFF; margin: 0 0 6px 0; }
.doc-header .meta { color: #D8E6F2; font-size: 13.5px; }
/* the application icon in the banner: the blue bird carrying a letter.  It is
   mostly light blue, so it needs a white backing to stand out against the blue
   gradient.  The box is border-box so the padding does not squeeze it. */
p.doc-mark {
  margin: 2px 0 0 0; padding: 9px; background: #FFFFFF;
  border: none; border-radius: 22px;
  width: 96px; height: 96px; box-sizing: border-box; overflow: hidden;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.20);
}
p.doc-mark img {
  width: 78px; height: 78px; max-width: none; display: block; margin: 0;
  border: none; border-radius: 12px; box-shadow: none;
}
.toc {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 16px 22px 18px 22px; margin: 0 0 30px 0;
}
.toc h2 {
  font-size: 16px; margin: 0 0 10px 0; padding: 0; border: none;
  background: none; color: var(--muted); letter-spacing: 1px;
}
.toc ol { margin: 0; padding-left: 4px; list-style: none; }
.toc li { margin: 4px 0; }
.toc li.lvl2 { font-weight: 600; }
.toc li.lvl3 {
  margin: 2px 0 2px 18px; font-size: 12.8px; font-weight: 400;
  color: var(--muted);
}
.toc li.lvl3 a { color: var(--muted); }
.toc a { border-bottom: none; }
.toc a:hover { color: var(--accent); }
.doc-footer {
  margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 12.5px; text-align: center;
}
@media print {
  body { background: #FFFFFF; padding: 0; max-width: none; font-size: 11.2pt; }
  h2 { page-break-after: avoid; }
  h3, h4 { page-break-after: avoid; }
  table, pre, img, blockquote, tr { page-break-inside: avoid; }
  a { border-bottom: none; color: #23578A; }
  .toc { page-break-after: always; }
  .doc-header {
    background: #23578A !important;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
  th, tbody tr:nth-child(even) {
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
  }
}
"""


# ---------------------------------------------------------------------------
# font subsetting
#
# QtWebEngine's printToPdf embeds the *entire* font file for every family the
# page uses, it does not subset.  Microsoft YaHei UI alone is 19 MB and it went
# in twice (regular and bold), which is what made the PDF 37 MB.
#
# So the fonts are subset here, to just the characters this manual actually
# contains, and handed to the page as @font-face data.  A few hundred glyphs
# instead of twenty thousand: the PDF drops from 37 MB to about 1 MB and the
# standalone HTML shrinks by the same amount.
# ---------------------------------------------------------------------------

#: family name -> (path, TrueType index, weight, style)
#: "Microsoft YaHei UI" and "Microsoft YaHei" share one collection file.
FONT_CANDIDATES = {
    "BlueBird Sans": [
        ("C:/Windows/Fonts/msyh.ttc", 0, "normal", "normal"),
        ("C:/Windows/Fonts/msyh.ttf", 0, "normal", "normal"),
    ],
    "BlueBird Sans Bold": [
        ("C:/Windows/Fonts/msyhbd.ttc", 0, "normal", "normal"),
        ("C:/Windows/Fonts/msyhbd.ttf", 0, "normal", "normal"),
    ],
    "BlueBird Mono": [
        ("C:/Windows/Fonts/consola.ttf", 0, "normal", "normal"),
        ("C:/Windows/Fonts/consolas.ttf", 0, "normal", "normal"),
    ],
    "BlueBird Mono Bold": [
        ("C:/Windows/Fonts/consolab.ttf", 0, "normal", "normal"),
        ("C:/Windows/Fonts/consolasb.ttf", 0, "normal", "normal"),
    ],
}


def _collect_characters(page_html: str) -> set:
    """Every character the page renders, minus the ones the font lacks.

    Two things matter.  The set must cover the text, because a missing glyph is
    a blank box.  It must also be *small and satisfiable*, because WebEngine
    falls back to a system font for any character the page fonts lack - and it
    then embeds that whole font file.  A single fallback to Cambria Math put
    9 MB into the PDF, so characters the CJK font cannot draw (the handful of
    emoji in the source) are dropped here rather than pushed into a fallback.
    """
    text = re.sub(r"<[^>]*>", "", page_html)
    characters = set(html.unescape(text))

    # ASCII, for code samples and file paths
    for code in range(0x20, 0x7F):
        characters.add(chr(code))

    # CJK punctuation and fullwidth forms, used freely in Chinese prose
    characters.update("\u3000\u3001\u3002\u3008\u3009\u300a\u300b\u300c"
                      "\u300d\u300e\u300f\u3010\u3011\u3014\u3015"
                      "\uff01\uff08\uff09\uff0c\uff0e\uff1a\uff1b\uff1f"
                      "\uff5e\uff0d\uff0b\uff1d\uff5b\uff5d\uff3b\uff3d"
                      "\uff0f\uff3c\uff5c\uff20\uff03\uff05\uff06\uff0a"
                      "\uff1c\uff1e\uff02\uff07")
    # punctuation and symbols the markup relies on
    characters.update("\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00b7"
                      "\u00a0\u00a9\u00ae\u2122\u00b0\u00b1\u00d7\u00f7"
                      "\u2264\u2265\u2260\u221e\u00a7\u00b6\u2022"
                      "\u2190\u2191\u2192\u2193\u2500\u2502\u250c\u2510"
                      "\u2514\u2518\u251c\u2524\u252c\u2534\u253c")
    # accented letters for author names
    characters.update("\u00e9\u00e8\u00ea\u00fc\u00f6\u00e4\u00df\u00e7")

    characters.discard("\x00")

    # keep only what the page font can actually draw
    coverage = _sans_coverage()
    if coverage:
        dropped = sorted(c for c in characters if ord(c) not in coverage)
        if dropped:
            print("    dropping %d character(s) the page font lacks: %s"
                  % (len(dropped),
                     " ".join("U+%04X" % ord(c) for c in dropped[:8])))
        characters = {c for c in characters if ord(c) in coverage}

    for blank in ("\n", "\r", "\t"):
        characters.discard(blank)
    return characters


_coverage_cache: Optional[set] = None


def _sans_coverage() -> Optional[set]:
    """Codepoints the CJK page font can render, or None if it cannot be read."""
    global _coverage_cache
    if _coverage_cache is not None:
        return _coverage_cache or None
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    for source, index, _w, _s in FONT_CANDIDATES["BlueBird Sans"]:
        if not os.path.isfile(source):
            continue
        try:
            font = TTFont(source, fontNumber=index, lazy=True)
            coverage = set(font.getBestCmap().keys())
            font.close()
        except Exception:
            continue
        if coverage:
            _coverage_cache = coverage
            return coverage
    _coverage_cache = set()
    return None


def _subset_one(source: str, index: int, characters: set,
                family: str) -> "tuple":
    """Subset one font file, returning (family, woff2 bytes) or None."""
    from fontTools import subset as ft_subset
    from fontTools.ttLib import TTFont

    if not os.path.isfile(source):
        return None

    font = TTFont(source, fontNumber=index, lazy=False)
    options = ft_subset.Options()
    options.desubroutinize = True
    options.drop_tables += ["DSIG"]
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.recalc_bounds = True
    options.notdef_outline = True
    options.glyph_names = False

    subsetter = ft_subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(characters)))
    subsetter.subset(font)

    # Options.flavor only reaches the compiler when saving to a file name.
    # Saving to a buffer needs the flavour on the font object itself, otherwise
    # the bytes are plain TrueType while the CSS claims woff2, and the browser
    # rejects them.
    buffer = io.BytesIO()
    try:
        font.flavor = "woff2"
        font.save(buffer)
    except Exception:
        # brotli missing: woff is zlib based and just as widely supported
        font.flavor = "woff"
        buffer = io.BytesIO()
        font.save(buffer)
    font.close()
    return (family, buffer.getvalue())


def _widen_for(characters: set, candidates: "list") -> set:
    """Widen a character set so nothing falls through to a system font.

    Chinese in a code span is the case that matters: the font picked for that
    span has to be able to draw it, or WebEngine reaches for a system font and
    embeds it whole.  Characters no available font can draw are dropped, since
    drawing them was never possible anyway.
    """
    from fontTools.ttLib import TTFont

    coverage = None
    for source, index, _weight, _style in candidates:
        if not os.path.isfile(source):
            continue
        try:
            font = TTFont(source, fontNumber=index, lazy=True)
            coverage = set(font.getBestCmap().keys())
            font.close()
        except Exception:
            coverage = None
        if coverage:
            break
    if not coverage:
        return characters
    return {c for c in characters if ord(c) in coverage}


def build_font_face_css(page_html: str) -> str:
    """@font-face rules for subsetted copies of the manual's fonts.

    Returns an empty string when fontTools or the system fonts are missing, in
    which case the page falls back to the named system fonts as before.
    """
    try:
        import fontTools  # noqa: F401
    except ImportError:
        print("  ! fontTools is not installed; the PDF will embed whole fonts")
        print("    (pip install fonttools). Falling back to system fonts.")
        return ""

    characters = _collect_characters(page_html)
    print("  subsetting fonts for %d distinct characters" % len(characters))

    rules = []
    for family, candidates in FONT_CANDIDATES.items():
        result = None
        # Every family gets the *same* character set, not just its own.  Code
        # spans contain Chinese (a path with a folder name, say), so a mono
        # subset built from ASCII alone would fall back to a system CJK font
        # and drag the whole 9 MB Consolas file into the PDF.  Giving each font
        # full coverage costs a few hundred KB of subset and saves megabytes.
        subset_characters = _widen_for(characters, candidates)
        for source, index, _weight, _style in candidates:
            try:
                result = _subset_one(source, index, subset_characters, family)
            except Exception as exc:            # a broken or locked font file
                print("  ! %s: %s" % (os.path.basename(source), exc))
                result = None
            if result:
                print("    %-20s %-14s %6.1f KB"
                      % (family, os.path.basename(source),
                         len(result[1]) / 1024.0))
                break
        if not result:
            print("    %-20s unavailable" % family)
            continue
        encoded = base64.b64encode(result[1]).decode("ascii")
        flavour = "woff2" if result[1][:4] == b"wOF2" else "woff"
        rules.append(
            "@font-face { font-family: '%s'; font-style: normal; "
            "font-weight: %s; font-display: block; "
            "src: url(data:font/%s;base64,%s) format('%s'); }"
            % (family, "700" if family.endswith("Bold") else "400",
               flavour, encoded, flavour))

    if not rules:
        return ""
    return "\n".join(rules) + "\n"


def embed_images(body: str, compress: bool = False,
                 max_width: int = 1180, quality: int = 82) -> str:
    """Inline every local screenshot so the HTML works on its own.

    With ``compress`` each screenshot is downscaled and re-encoded as whichever
    of PNG or JPEG comes out smaller, and the bytes are base64 encoded exactly
    once.  Double encoding here was costing a factor of 2.4 on its own.
    """
    stats = {"png": 0, "jpeg": 0, "raw": 0}

    def replace(match: "re.Match[str]") -> str:
        src = match.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = os.path.normpath(os.path.join(DOCS, src))
        if not os.path.isfile(path):
            print("  ! missing image: %s" % path)
            return match.group(0)
        if compress:
            encoded = _compressed_image(path, max_width, quality)
            if encoded is not None:
                mime, payload = encoded
                stats["jpeg" if "jpeg" in mime else "png"] += len(payload)
                return 'src="data:%s;base64,%s"' % (
                    mime, base64.b64encode(payload).decode("ascii"))
        with open(path, "rb") as handle:
            raw = handle.read()
        stats["raw"] += len(raw)
        return 'src="data:image/png;base64,%s"' % (
            base64.b64encode(raw).decode("ascii"))

    result = re.sub(r'src="([^"]+)"', replace, body)
    if compress and (stats["png"] or stats["jpeg"] or stats["raw"]):
        print("  screenshots: %d as PNG (%.2f MB), %d as JPEG (%.2f MB)"
              % (stats["png"] and 1 or 0, stats["png"] / 1048576.0,
                 stats["jpeg"] and 1 or 0, stats["jpeg"] / 1048576.0))
    return result


def _encode_image(image: Any, fmt: str, quality: int = -1) -> bytes:
    from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if quality >= 0:
        image.save(buffer, fmt, quality)
    else:
        image.save(buffer, fmt)
    buffer.close()
    return bytes(data)


def _flatten(image: Any) -> Any:
    """Composite onto white.

    JPEG has no alpha channel, and a 32-bit PNG is converted to RGBA before
    encoding, which the JPEG writer then handles badly - that was inflating
    these screenshots by a factor of two.
    """
    from PyQt5.QtGui import QImage, QPainter
    from PyQt5.QtCore import Qt
    if not image.hasAlphaChannel():
        return image.convertToFormat(QImage.Format_RGB888)
    canvas = QImage(image.size(), QImage.Format_RGB888)
    canvas.fill(Qt.white)
    painter = QPainter(canvas)
    painter.drawImage(0, 0, image)
    painter.end()
    return canvas


def _compressed_image(path: str, max_width: int,
                      quality: int) -> "Optional[tuple]":
    """Encode one screenshot as (mime, base64); None when Qt is unavailable.

    These are UI screenshots - flat colours, thin borders and small text, with
    Chinese in them.  JPEG smears that text, so PNG is used whenever it is not
    much bigger, and JPEG only wins when it clearly does.  The smaller result
    is kept either way.
    """
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QImage
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        return None
    app = QApplication.instance() or QApplication(sys.argv[:1])
    image = QImage(path)
    if image.isNull():
        return None
    if image.width() > max_width:
        image = image.scaledToWidth(max_width, Qt.SmoothTransformation)

    flat = _flatten(image)
    png = _encode_image(flat, "PNG")
    jpeg = _encode_image(flat, "JPG", quality)
    if len(png) <= len(jpeg) * 1.25:
        return ("image/png", png)
    return ("image/jpeg", jpeg)


def add_pdf_navigation(target: str, headings: "List[Tuple[int, str, str]]") -> bool:
    """Make the printed PDF navigable.

    QtWebEngine's printToPdf writes no link annotations and no bookmarks at all,
    so the table of contents in the PDF is dead text.  This walks the finished
    file and adds two things: a link on every table of contents entry, and a
    bookmark outline, so the reader's sidebar can jump around as well.
    """
    try:
        import fitz                              # PyMuPDF
    except ImportError:
        print("  ! PyMuPDF is not installed, so the PDF has no clickable")
        print("    table of contents (pip install pymupdf)")
        return False

    wanted = [(level, inline(text)) for level, text, _anchor in headings
              if level in (2, 3)]
    if not wanted:
        return False

    document = fitz.open(target)
    try:
        # Resolve every heading to (page, rect) once.  Each title appears twice,
        # in the table of contents and as the heading itself, so the last match
        # on the last page found is the heading.
        resolved = []
        for level, label in wanted:
            destination = None
            occurrences = []
            for page_index in range(document.page_count):
                for rect in document[page_index].search_for(label):
                    occurrences.append((page_index, rect))
            if occurrences:
                destination = occurrences[-1]
            if destination is not None:
                resolved.append((level, label, destination[0], destination[1]))

        # bookmarks: chapters at level 1, sections nested under them
        outline = [[1, label, page + 1] if level == 2
                   else [2, label, page + 1]
                   for level, label, page, _rect in resolved]

        # links: pair each table of contents entry with its heading
        toc_pages = [index for index in range(min(4, document.page_count))
                     if TOC_LABEL in document[index].get_text()]
        links_added = 0
        if toc_pages and resolved:
            toc_entries = []
            for page_index in toc_pages:
                for rect in document[page_index].search_for(TOC_LABEL):
                    toc_entries.append((page_index, rect))
            if toc_entries:
                toc_page = toc_entries[0][0]
                page = document[toc_page]
                for level, label, page_number, _rect in resolved:
                    hits = page.search_for(label)
                    if not hits:
                        continue
                    page.insert_link({"kind": fitz.LINK_GOTO, "from": hits[0],
                                      "page": page_number,
                                      "to": fitz.Point(0, 0)})
                    links_added += 1

        if not (links_added or outline):
            print("  ! no navigation could be derived for the PDF")
            return False

        document.set_toc(outline)
        try:
            document.save(target, incremental=True,
                          encryption=fitz.PDF_ENCRYPT_KEEP)
        except Exception as exc:                 # usually a viewer holding it
            print("  ! could not write the navigation into %s: %s"
                  % (os.path.basename(target), exc))
            print("    the PDF has no clickable contents; close it in your PDF "
                  "viewer and run this again")
            return False
        print("  navigation: %d table of contents link(s), %d bookmark(s)"
              % (links_added, len(outline)))
        return True
    finally:
        document.close()


def build_html(markdown: str, standalone: bool = True,
               compress_images: bool = False, font_css: str = "") -> str:
    body, headings = convert(markdown)
    body = embed_images(body, compress=compress_images)

    # The table of contents lists the chapters and their sections, and every
    # entry links to the anchor on its heading, so both the HTML and the PDF
    # can jump straight to a topic.
    toc = ""
    chapters = [item for item in headings if item[0] == 2]
    if chapters:
        entries = []
        for level, text, anchor in headings:
            if level == 2:
                entries.append('<li class="lvl2"><a href="#%s">%s</a></li>'
                               % (anchor, inline(text)))
            elif level == 3:
                entries.append('<li class="lvl3"><a href="#%s">%s</a></li>'
                               % (anchor, inline(text)))
        toc = ('<nav class="toc"><h2>%s</h2><ol>%s</ol></nav>'
               % (TOC_LABEL, "".join(entries)))

    header = ""
    first = re.search(r"<h1[^>]*>.*?</h1>", body, re.S)
    if first:
        title_html = first.group(0)
        body = body.replace(title_html, "", 1)
        body = body.lstrip()

        # The markdown puts the app icon and a version line right under the
        # title; both belong in the banner, not in the flow of the document.
        # They are lifted out here, otherwise the icon ends up below the table
        # of contents where nobody sees it.
        mark = ""
        mark_match = re.search(
            r'<p>\s*(<img src="data:image/[^"]*"[^>]*>)\s*</p>', body)
        if mark_match:
            mark = '<p class="doc-mark">%s</p>' % mark_match.group(1)
            body = body.replace(mark_match.group(0), "", 1)

        # the line under the title repeats the version/author of the banner
        body = re.sub(r"<p>(?:\s*<strong>)?\s*版本[^<]*(?:</strong>)?.*?</p>",
                      "", body, count=1)
        body = body.lstrip()

        header = ('<header class="doc-header">%s<div class="meta">%s</div>'
                  '%s</header>' % (title_html, SUBTITLE, mark))

    if not standalone:
        return body
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>%s</title>\n<style>%s\n%s</style>\n</head>\n<body>\n"
        "%s\n%s\n%s\n<div class=\"doc-footer\">%s</div>\n</body>\n</html>\n"
        % (html.escape(TITLE), font_css, CSS, header, toc, body, FOOTER)
    )


# ---------------------------------------------------------------------------
# PDF via QtWebEngine
# ---------------------------------------------------------------------------

#: The QtWebEngine page, kept alive between books.  Creating a second page
#: before the first is fully destroyed upsets the profile: the print then fails
#: with "printer reported failure" and Qt warns that the page is still around.
_PDF_PAGE: Any = None


def _reap(app: Any, rounds: int = 60) -> None:
    """Let Qt deliver the pending deletions."""
    for _ in range(rounds):
        app.processEvents()


def _destroy_page(app: Any, page: Any) -> None:
    """Tear a page down and wait until Qt has actually released it.

    The page sometimes tears itself down after a print, so a deleted C++ object
    here is a normal outcome rather than an error: both mean "this page is gone
    and the next one may be created".
    """
    try:
        from PyQt5.QtCore import QCoreApplication, QEvent
        from PyQt5 import sip
    except ImportError:
        return
    if sip.isdeleted(page):
        return
    page.deleteLater()
    for _ in range(120):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        if sip.isdeleted(page):
            return
    print("  ! the web page did not shut down cleanly")


def write_pdf(page_html: str, target: str) -> bool:
    try:
        from PyQt5.QtCore import QEventLoop, QMarginsF, QTimer, QUrl
        from PyQt5.QtGui import QPageLayout, QPageSize
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
    except ImportError as exc:
        print("  ! QtWebEngine unavailable (%s); skipping PDF" % exc)
        return False

    # A PDF left open in a viewer makes the printer fail with no useful reason,
    # and a stale file left behind would be mistaken for a fresh one.
    if os.path.isfile(target):
        try:
            os.remove(target)
        except OSError as exc:
            print("  ! cannot replace %s: %s" % (target, exc))
            print("    close it in your PDF viewer and run this again")
            return False

    global _PDF_PAGE
    app = QApplication.instance() or QApplication(sys.argv[:1])
    _reap(app)
    # A fresh page per book, and the previous one is gone before this one is
    # made; reusing a page across books is not reliable here.
    if _PDF_PAGE is not None:
        _destroy_page(app, _PDF_PAGE)
        _PDF_PAGE = None
    # Its own profile per page: the default one keeps the render process alive
    # between books, and the second print then fails with "printer reported
    # failure" while Qt complains that the page was never deleted.
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineProfile
        profile = QWebEngineProfile(parent=app)
        page = QWebEnginePage(profile, app)
    except (ImportError, TypeError):
        page = QWebEnginePage()
    _PDF_PAGE = page
    state = {"ok": False, "printed": False, "why": ""}
    loop = QEventLoop()

    def detach() -> None:
        """Drop our handlers: the page is reused for the next book."""
        for signal, slot in ((page.pdfPrintingFinished, finished),
                             (page.loadFinished, loaded)):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def finished(path: str, success: bool) -> None:
        state["ok"] = bool(success)
        if success and os.path.isfile(path):
            print("  wrote %s (%.1f MB)"
                  % (path, os.path.getsize(path) / 1048576.0))
        else:
            print("  ! PDF rendering failed (%s)"
                  % (state["why"] or "printer reported failure"))
        detach()
        loop.quit()

    def loaded(success: bool) -> None:
        if not success:
            state["why"] = "page failed to load"
            print("  ! page failed to load")
            detach()
            loop.quit()
            return
        # The data: fonts have to be decoded before printing, otherwise the
        # first pages can come out with fallback glyphs.  A short settle time
        # after load is enough and makes the render reliable.
        QTimer.singleShot(1200, do_print)

    def do_print() -> None:
        layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                             QMarginsF(12, 12, 12, 14), QPageLayout.Millimeter)
        state["printed"] = True
        page.printToPdf(target, layout)

    def timed_out() -> None:
        if not state["printed"]:
            state["why"] = "timed out before printing"
        elif not state["ok"]:
            state["why"] = "timed out waiting for the printer"
        print("  ! PDF rendering timed out")
        loop.quit()

    def on_done(path: str, success: bool) -> None:
        """Disconnect before quitting: the page outlives this call."""
        try:
            page.pdfPrintingFinished.disconnect(finished)
            page.loadFinished.disconnect(loaded)
        except TypeError:
            pass
        finished(path, success)

    page.pdfPrintingFinished.connect(finished)
    page.loadFinished.connect(loaded)
    page.setHtml(page_html, QUrl.fromLocalFile(DOCS + os.sep))
    QTimer.singleShot(240000, timed_out)
    loop.exec_()

    # Leave the page in a clean state for the next book rather than destroying
    # it; Qt reuses the profile and the print keeps working.  Done by hand
    # because loop.quit() can return while a signal is still being delivered.
    app.processEvents()
    return state["ok"]


def build_book(book: "dict", font_cache: "dict") -> bool:
    """Render one book to HTML and PDF.  Returns True when both were written."""
    select_book(book)
    if not os.path.isfile(SOURCE):
        print("missing %s" % SOURCE)
        return False

    with io.open(SOURCE, "r", encoding="utf-8") as handle:
        markdown = handle.read()

    print("converting %s" % os.path.relpath(SOURCE, ROOT))

    # Two passes: the first renders the page so the exact set of characters is
    # known, then the fonts are subset to it and the page is built again with
    # the @font-face rules in place.  Without this the PDF embeds whole fonts.
    # Screenshots are recompressed in both passes: the PDF carries whichever
    # form the page ends up with, and raw PNGs alone account for several MB.
    # The heading list is needed again for the PDF navigation pass.
    _body, headings = convert(markdown)

    first_pass = build_html(markdown, compress_images=True)
    if "css" in font_cache:
        font_css = font_cache["css"]           # both books use the same fonts
    else:
        font_css = build_font_face_css(first_pass)
        font_cache["css"] = font_css
    page = build_html(markdown, compress_images=True, font_css=font_css) \
        if font_css else first_pass

    try:
        with io.open(HTML_OUT, "w", encoding="utf-8") as handle:
            handle.write(page)
    except (IOError, OSError) as exc:
        print("  ! cannot write %s: %s" % (HTML_OUT, exc))
        print("    (a viewer such as Word or a browser may still hold it open)")
        return False
    print("  wrote %s (%.2f MB)" % (HTML_OUT,
                                    os.path.getsize(HTML_OUT) / 1048576.0))

    print("  rendering PDF...")
    ok = write_pdf(page, PDF_OUT)
    if ok:
        add_pdf_navigation(PDF_OUT, headings)

    if ok and os.path.isfile(PDF_OUT):
        size_mb = os.path.getsize(PDF_OUT) / 1048576.0
        print("  final PDF %.2f MB" % size_mb)
        if size_mb > 8:
            print("  ! larger than expected.  QtWebEngine embeds a whole font "
                  "file per family unless it is subset first: check that "
                  "fontTools is installed (pip install fonttools) and that "
                  "C:/Windows/Fonts has msyh.ttc.")
    return ok


def main() -> int:
    """Build the books.

    ``--only NAME``    build a single book, in this process
    ``--one NAME``     internal: build one book and exit, used by the parent
    ``--jobs``         build each book in its own process (the default)

    Each book gets its own process because QtWebEngine cannot survive a page
    being destroyed and another created afterwards: the second print makes the
    whole process die with an access violation.  A fresh interpreter per book
    costs a second of startup and removes the problem entirely.
    """
    argv = sys.argv[1:]

    def value_of(flag: str) -> str:
        if flag in argv:
            index = argv.index(flag)
            if index + 1 < len(argv):
                return argv[index + 1]
        return ""

    one = value_of("--one")
    if one:
        book = next((item for item in BOOKS if one in item["source"]), None)
        if book is None:
            print("unknown book: %s" % one)
            return 1
        return 0 if build_book(book, {}) else 1

    only = value_of("--only")
    wanted = [book for book in BOOKS
              if not only or only in book["source"]]
    if not wanted:
        print("no book matches %r" % only)
        return 1

    import subprocess

    built = []
    for number, book in enumerate(wanted):
        if number:
            print()
        result = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--one",
             book["source"]],
            cwd=ROOT)
        if result.returncode == 0:
            built.append(book["source"])
        else:
            print("  ! %s failed (exit %d)"
                  % (book["source"], result.returncode))

    print()
    print("built: %s" % (", ".join(built) if built else "nothing"))
    return 0 if built else 1


if __name__ == "__main__":
    sys.exit(main())
