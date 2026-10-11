"""Which DLLs in the bundle are actually imported by other binaries?

The trim removed Qt5Positioning.dll because nothing in the Python code mentions
"Positioning", but Qt5WebEngineCore.dll imports it, so the in-app manual stopped
working.  This walks the real PE import tables instead of guessing from names.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist", "BlueBird")
DUMPBIN = (r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Professional"
           r"\VC\Tools\MSVC\14.29.30133\bin\Hostx64\x64\dumpbin.exe")

if not os.path.isfile(DUMPBIN):
    sys.exit("dumpbin not found at %s" % DUMPBIN)

# the DLLs the trim rules propose removing
CANDIDATES = [
    "Qt5XmlPatterns.dll", "Qt5Sql.dll", "Qt5Test.dll", "Qt5Designer.dll",
    "Qt5Bluetooth.dll", "Qt5Nfc.dll", "Qt5Positioning.dll", "Qt5Sensors.dll",
    "Qt5SerialPort.dll", "Qt5Multimedia.dll", "Qt5MultimediaWidgets.dll",
    "Qt5WebSockets.dll", "Qt5Location.dll", "d3dcompiler_47.dll",
    "opengl32sw.dll",
]

binaries = []
for base, _dirs, files in os.walk(DIST):
    for name in files:
        if name.lower().endswith((".dll", ".pyd", ".exe")):
            binaries.append(os.path.join(base, name))

print("  scanning %d binaries for imports of the trim candidates" % len(binaries))
print()

# who imports each candidate
imported_by = {name: [] for name in CANDIDATES}
for path in binaries:
    result = subprocess.run([DUMPBIN, "/DEPENDENTS", path],
                            capture_output=True, text=True, errors="replace")
    text = (result.stdout or "").lower()
    if not text:
        continue
    for candidate in CANDIDATES:
        if candidate.lower() in text:
            imported_by[candidate].append(os.path.relpath(path, DIST))

print("  %-28s %-6s %s" % ("candidate", "safe?", "imported by"))
print("  " + "-" * 88)
for candidate in CANDIDATES:
    users = imported_by[candidate]
    # a candidate is only safe when nothing else in the bundle imports it
    safe = "YES" if not users else "NO"
    shown = ", ".join(sorted(set(os.path.basename(u) for u in users))[:3])
    if len(set(users)) > 3:
        shown += " (+%d)" % (len(set(users)) - 3)
    print("  %-28s %-6s %s" % (candidate, safe, shown or "-"))

print()
print("  A candidate listed as NO must stay: removing it is what broke the")
print("  manual, and the failure only shows up as a DLL-load error at runtime.")
