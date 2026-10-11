"""Write LICENSE as the pristine GNU GPL, and keep the notes out of it.

GitHub classifies the licence by matching the file against known texts.  An
appendix of project notes is not part of the GPL, and it was enough to make the
detector report "Other" even with the GPL at the top.  So LICENSE now holds
only the two-line notice the GPL asks for followed by the licence itself, and
the explanation lives at the top of THIRD-PARTY-NOTICES.txt, which is where a
reader looks for the project's licensing position anyway.
"""
from __future__ import annotations

import glob
import io
import os
import site

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPL_HEADING = "GNU GENERAL PUBLIC LICENSE"
GPL_END = "END OF TERMS AND CONDITIONS"

#: what the GPL says to attach to the program's own licence
NOTICE = """\
BlueBird - a modern cream-themed FTP / FTPS / SFTP client
Copyright (C) 2026 silence

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

"""


def gpl_text() -> str:
    """The GNU GPL version 3, verbatim, from the installed Qt runtime."""
    site_dir = site.getsitepackages()[-1]
    for pattern in ("PyQt5_Qt5-*/LICENSE", "PyQt5-*/LICENSE"):
        found = glob.glob(os.path.join(site_dir, pattern))
        if not found:
            continue
        raw = io.open(found[0], encoding="utf-8", errors="replace").read()
        start = raw.find(GPL_HEADING)
        end = raw.find(GPL_END)
        if start >= 0 and end > start:
            end = raw.find("\n", end + len(GPL_END))
            return raw[start:end].rstrip() + "\n"
    raise SystemExit("could not find the GPL text in the Qt runtime wheel")


text = NOTICE + gpl_text()
target = os.path.join(ROOT, "LICENSE")
io.open(target, "w", encoding="utf-8", newline="\n").write(text)

print("wrote %s (%d bytes, %d lines)"
      % (target, os.path.getsize(target), text.count("\n")))
print("  notice lines : %d" % NOTICE.count("\n"))
print("  gpl lines    : %d" % gpl_text().count("\n"))
print("  is ASCII     : %s" % text.isascii())
print("  ends with    : %s" % text.rstrip().splitlines()[-1])
