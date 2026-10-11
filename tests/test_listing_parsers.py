"""Check the listing parsers against the lines a real IIS server sends.

The DOS samples were captured from Microsoft FTP service on 192.168.31.216.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ftpclient.session import FTPSession  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  [ok]   %s" % name)
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


#: verbatim from 192.168.31.216
DOS = [
    ("10-11-26  01:17PM              1661239 7z2603-x64.exe",
     "7z2603-x64.exe", False, 1661239),
    ("10-11-26  01:16PM       <DIR>          backup",
     "backup", True, 0),
    ("10-11-26  01:17PM           3775004672 "
     "cn_office_professional_plus_2019_x86_x64_dvd_5e5be643.iso",
     "cn_office_professional_plus_2019_x86_x64_dvd_5e5be643.iso", False,
     3775004672),
    ("10-11-26  01:53PM       <DIR>          fa to oa",
     "fa to oa", True, 0),
    ("10-11-26  01:37AM       <DIR>          oa to fa",
     "oa to fa", True, 0),
    ("10-11-26  01:05AM             30774112 python-3.14.6-amd64.exe",
     "python-3.14.6-amd64.exe", False, 30774112),
    ("10-11-26  12:05AM                   42 midnight.txt",
     "midnight.txt", False, 42),
    ("10-11-26  12:05PM                   42 noon.txt",
     "noon.txt", False, 42),
]

UNIX = [
    ("-rw-r--r--   1 user group     1234 Jan  2 03:04 notes.txt",
     "notes.txt", False),
    ("drwxr-xr-x   2 user group     4096 Jan  2  2026 docs", "docs", True),
    ("lrwxrwxrwx   1 user group        7 Jan  2 03:04 link -> target",
     "link", False),
]

print("=== DOS listings (Microsoft FTP service) ===")
for line, name, is_dir, size in DOS:
    entry = FTPSession._parse_list_line(line)
    check("parsed: %s" % name, entry is not None, "returned None")
    if entry is None:
        continue
    check("  name is %s" % name, entry.name == name, repr(entry.name))
    check("  %s is %s" % (name, "a folder" if is_dir else "a file"),
          entry.is_dir == is_dir, str(entry.is_dir))
    if not is_dir:
        check("  size is %s" % size, entry.size == size, str(entry.size))
    check("  %s has a timestamp" % name, entry.mtime is not None,
          str(entry.mtime))

print()
print("=== the timestamp is decoded, not guessed ===")
noon = FTPSession._parse_list_line(
    "10-11-26  12:05PM                   42 noon.txt")
check("12:05PM is 12:05", noon is not None and
      __import__("time").localtime(noon.mtime).tm_hour == 12,
      str(noon and __import__("time").localtime(noon.mtime).tm_hour))
midnight = FTPSession._parse_list_line(
    "10-11-26  12:05AM                   42 midnight.txt")
check("12:05AM is 00:05", midnight is not None and
      __import__("time").localtime(midnight.mtime).tm_hour == 0,
      str(midnight and __import__("time").localtime(midnight.mtime).tm_hour))
afternoon = FTPSession._parse_list_line(
    "10-11-26  01:37PM       <DIR>          fa to oa")
check("01:37PM is 13:37", afternoon is not None and
      __import__("time").localtime(afternoon.mtime).tm_hour == 13,
      str(afternoon and __import__("time").localtime(afternoon.mtime).tm_hour))

print()
print("=== Unix listings still work ===")
for line, name, is_dir in UNIX:
    entry = FTPSession._parse_list_line(line)
    check("Unix: %s" % name,
          entry is not None and entry.name == name and entry.is_dir == is_dir,
          repr(entry and entry.name))

print()
print("=== junk is rejected ===")
for junk in ("", "   ", "total 12", "226 Transfer complete",
             "not a listing at all"):
    check("rejected: %r" % junk[:22],
          FTPSession._parse_list_line(junk) is None)

print()
print("=== a wide file is not mis-sliced ===")
# this is the case fixed columns got wrong: 10 digits instead of 7
wide = FTPSession._parse_list_line(
    "10-11-26  01:17PM           3775004672 wide.iso")
check("a 10 digit size keeps the right name",
      wide is not None and wide.name == "wide.iso",
      repr(wide and wide.name))
check("a 10 digit size is read in full",
      wide is not None and wide.size == 3775004672,
      str(wide and wide.size))

print()
print("passed: %d   failed: %d" % (len(PASSED), len(FAILED)))
for name, detail in FAILED:
    print("  FAILED: %s  %s" % (name, detail))
sys.exit(1 if FAILED else 0)
