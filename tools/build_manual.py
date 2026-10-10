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
SOURCE = os.path.join(DOCS, "\u7528\u6237\u624b\u518c.md")
HTML_OUT = os.path.join(DOCS, "\u7528\u6237\u624b\u518c.html")
PDF_OUT = os.path.join(DOCS, "\u7528\u6237\u624b\u518c.pdf")
TITLE = "Smart FTP \u7528\u6237\u624b\u518c"

#: pull the version and author straight from the package so the banner can
#: never drift from the code
try:
    sys.path.insert(0, ROOT)
    from ftpclient import __author__, __version__ as _VERSION
except Exception:                                # pragma: no cover
    __author__, _VERSION = "silence", "1.0.0"

SUBTITLE = ("\u7248\u672c %s \u00b7 \u4f5c\u8005\uff1a%s \u00b7 "
            "Python 3.8.3 + PyQt5 5.15.11 \u00b7 "
            "FTP / FTPS / SFTP \u5ba2\u6237\u7aef" % (_VERSION, __author__))
FOOTER = ("Smart FTP %s \u00b7 \u7528\u6237\u624b\u518c \u00b7 \u4f5c\u8005\uff1a%s"
          " \u00b7 \u7531 docs/\u7528\u6237\u624b\u518c.md \u81ea\u52a8\u751f\u6210"
          % (_VERSION, __author__))
TOC_LABEL = "\u76ee\u5f55"

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


def convert(markdown: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    """Return (html_body, [(level, text, anchor)])."""
    lines = markdown.splitlines()
    out: List[str] = []
    headings: List[Tuple[int, str, str]] = []
    used: Dict[str, int] = {}
    index = 0
    list_stack: List[str] = []
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
            anchor = slugify(text)
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
            out.append("<li>%s</li>" % inline(match.group(3)))
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
    return "\n".join(out), headings


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
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
               "Hiragino Sans GB", "Source Han Sans SC", "Segoe UI", sans-serif;
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
  font-family: Consolas, "Cascadia Mono", "Courier New", monospace;
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
/* the application icon in the banner.  It is a light-blue cloud, so it needs
   a light backing to be visible against the blue gradient.  The box is
   border-box so the padding does not squeeze the image. */
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
.toc a { border-bottom: none; }
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


def embed_images(body: str, compress: bool = False,
                 max_width: int = 1180, quality: int = 82) -> str:
    """Inline every local screenshot so the HTML works on its own.

    With ``compress`` the screenshots are downscaled and re-encoded as JPEG,
    which keeps the print PDF to a sane size (raw PNGs produce a ~37 MB file).
    """
    def replace(match: "re.Match[str]") -> str:
        src = match.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = os.path.normpath(os.path.join(DOCS, src))
        if not os.path.isfile(path):
            print("  ! missing image: %s" % path)
            return match.group(0)
        if compress:
            encoded = _compressed_png(path, max_width, quality)
            if encoded is not None:
                return 'src="data:image/jpeg;base64,%s"' % encoded
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
        return 'src="data:image/png;base64,%s"' % encoded

    return re.sub(r'src="([^"]+)"', replace, body)


def _compressed_png(path: str, max_width: int, quality: int) -> Optional[str]:
    """Downscale + JPEG-encode one screenshot; None when Qt is unavailable."""
    try:
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        from PyQt5.QtGui import QImage
        from PyQt5.QtWidgets import QApplication
    except ImportError:
        return None
    app = QApplication.instance() or QApplication(sys.argv[:1])
    image = QImage(path)
    if image.isNull():
        return None
    if image.width() > max_width:
        image = image.scaledToWidth(max_width, 1)   # 1 == SmoothTransformation
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "JPG", quality)
    buffer.close()
    return bytes(data.toBase64()).decode("ascii")


def build_html(markdown: str, standalone: bool = True,
               compress_images: bool = False) -> str:
    body, headings = convert(markdown)
    body = embed_images(body, compress=compress_images)

    toc_items = [(text, anchor) for level, text, anchor in headings if level == 2]
    toc = ""
    if toc_items:
        entries = "".join('<li><a href="#%s">%s</a></li>' % (anchor, inline(text))
                          for text, anchor in toc_items)
        toc = '<nav class="toc"><h2>%s</h2><ol>%s</ol></nav>' % (TOC_LABEL, entries)

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
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n"
        "%s\n%s\n%s\n<div class=\"doc-footer\">%s</div>\n</body>\n</html>\n"
        % (html.escape(TITLE), CSS, header, toc, body, FOOTER)
    )


# ---------------------------------------------------------------------------
# PDF via QtWebEngine
# ---------------------------------------------------------------------------

def write_pdf(page_html: str, target: str) -> bool:
    try:
        from PyQt5.QtCore import QEventLoop, QMarginsF, QTimer, QUrl
        from PyQt5.QtGui import QPageLayout, QPageSize
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEnginePage
    except ImportError as exc:
        print("  ! QtWebEngine unavailable (%s); skipping PDF" % exc)
        return False

    app = QApplication.instance() or QApplication(sys.argv[:1])
    page = QWebEnginePage()
    state = {"ok": False, "printed": False}
    loop = QEventLoop()

    def finished(path: str, success: bool) -> None:
        state["ok"] = bool(success)
        if success and os.path.isfile(path):
            print("  wrote %s (%d bytes)" % (path, os.path.getsize(path)))
        else:
            print("  ! PDF rendering failed")
        loop.quit()

    def loaded(success: bool) -> None:
        if not success:
            print("  ! page failed to load")
            loop.quit()
            return
        layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                             QMarginsF(12, 12, 12, 14), QPageLayout.Millimeter)
        state["printed"] = True
        page.printToPdf(target, layout)

    page.pdfPrintingFinished.connect(finished)
    page.loadFinished.connect(loaded)
    page.setHtml(page_html, QUrl.fromLocalFile(DOCS + os.sep))
    QTimer.singleShot(180000, loop.quit)
    loop.exec_()
    page.deleteLater()
    return state["ok"]


def main() -> int:
    if not os.path.isfile(SOURCE):
        print("missing %s" % SOURCE)
        return 1

    with io.open(SOURCE, "r", encoding="utf-8") as handle:
        markdown = handle.read()

    print("converting %s" % os.path.relpath(SOURCE, ROOT))
    page = build_html(markdown)
    try:
        with io.open(HTML_OUT, "w", encoding="utf-8") as handle:
            handle.write(page)
    except (IOError, OSError) as exc:
        print("  ! cannot write %s: %s" % (HTML_OUT, exc))
        print("    (a viewer such as Word or a browser may still hold it open)")
        return 1
    print("  wrote %s (%d bytes)" % (HTML_OUT, os.path.getsize(HTML_OUT)))

    print("rendering PDF (screenshots recompressed)...")
    write_pdf(page, PDF_OUT)

    if os.path.isfile(PDF_OUT):
        size_mb = os.path.getsize(PDF_OUT) / 1048576.0
        if size_mb > 15:
            # QtWebEngine embeds the whole CJK font (~35 MB for the text alone)
            print("  ! the PDF is %.1f MB because QtWebEngine embeds the full "
                  "Chinese font." % size_mb)
            print("    For distribution, open 用户手册.html in a browser and use")
            print("    Print -> Save as PDF, or open it in Word; both subset the")
            print("    fonts and produce a ~1 MB file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
