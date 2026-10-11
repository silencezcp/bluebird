"""Rebuild LICENSE the way GitHub's licence detector expects to read it.

The detector looks for a known licence at the top of the file, so a bespoke
preamble made it report "Other".  The GNU GPL text therefore comes first, with
the program name and copyright line the GPL itself says to add, and the notes
this project wants to make follow it as an appendix.
"""
from __future__ import annotations

import glob
import io
import os
import site

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GPL_HEADING = "GNU GENERAL PUBLIC LICENSE"
GPL_END = "END OF TERMS AND CONDITIONS"


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


#: the two lines the GPL asks a program to put at the top of its licence
NOTICE = """\
    BlueBird - a modern cream-themed FTP / FTPS / SFTP client
    Copyright (C) 2026 silence

"""

APPENDIX = """

==============================================================================
APPENDIX - why this project is licensed this way, and what it is built on
==============================================================================

The licence above applies to BlueBird.  The program name and copyright line
have been added to it as the GNU GPL itself instructs ("How to Apply These
Terms to Your New Programs").

Why the GPL
-----------

BlueBird is built on PyQt5 and PyQtWebEngine.  Riverbank Computing licenses
those under the GNU GPL version 3 or a commercial licence, at your choice.
Distributing BlueBird under the GPL is what makes that use compliant.  A build
that is distributed as closed source would instead need the commercial licence
from Riverbank.

The Qt libraries that ship alongside (PyQt5-Qt5, PyQtWebEngine-Qt5) are used
under the LGPL option.  They are installed as separate DLLs next to the
executable rather than linked into it, which is the arrangement the LGPL asks
for, and their licence texts are in THIRD-PARTY-NOTICES.txt.

Third-party components
----------------------

THIRD-PARTY-NOTICES.txt, beside this file, reproduces or points to the licence
of every dependency, with the exact terms read from each package rather than
copied from memory.  It must accompany any distribution of the binaries, as
MIT, BSD, Apache-2.0, PSF and LGPL all require their licence text to travel
with the program.

Source
------

    https://github.com/silencezcp/bluebird

This program comes with ABSOLUTELY NO WARRANTY, to the extent permitted by
law.  It is free software, and you are welcome to redistribute it under the
conditions of the GNU General Public License above.
"""

text = NOTICE + gpl_text() + APPENDIX
target = os.path.join(ROOT, "LICENSE")
io.open(target, "w", encoding="utf-8", newline="\n").write(text)

print("wrote %s (%d bytes, %d lines)"
      % (target, os.path.getsize(target), text.count("\n")))
first = [line for line in text.splitlines()[:4]]
print("starts with:")
for line in first:
    print("   %s" % line)
print("is ASCII          : %s" % text.isascii())
print("has GPL-3.0 marker: %s" % ("Version 3, 29 June 2007" in text))
print("has appendix      : %s" % ("APPENDIX" in text))
