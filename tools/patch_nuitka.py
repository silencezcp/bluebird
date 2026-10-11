"""Fix the one Nuitka source line that MSVC rejects.

Nuitka 4.3 generates a translation unit containing this pair::

    static char const *_kw_list_get_data[];          # ResourceReader.c:17
    static char const *_kw_list_get_data[] = {...};  # ...ResourceReaderFiles.c

C allows the first as a tentative definition that the second completes.  MSVC
does not: it reads ``[]`` without an initialiser as an incomplete type and
refuses it outright, even under ``/std:c11``::

    error C2133: '_kw_list_get_data': unknown size

Because the initialised definition lives in a file that
``MetaPathBasedLoaderResourceReader.c`` includes, and the array is only used
*after* that include, the repair is to drop the incomplete declaration: the
definition from the included file is then the only one MSVC sees.  Merely moving
the include above the declaration is not enough - MSVC then reports the
remaining declaration as a redefinition (C2086) instead.

GCC does not need any of this, which is why Nuitka's MinGW path builds the same
source unchanged.

The patch is idempotent: run it as often as you like.  ``--check`` reports
without touching anything, ``--revert`` puts the backup back.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sys

#: the file and the two lines that matter
TARGET = os.path.join("nuitka", "build", "static_src",
                      "MetaPathBasedLoaderResourceReader.c")

DECLARATION = "static char const *_kw_list_get_data[];"
INCLUDE = '#include "MetaPathBasedLoaderResourceReaderFiles.c"'

#: the array name as MSVC spells it in the error, for the diagnostic
LOOKING_FOR = "_kw_list_get_data"


def static_src_dir() -> str:
    """Where Nuitka keeps its C sources, or "" when it cannot be found."""
    try:
        import nuitka
    except ImportError:
        return ""
    return os.path.join(os.path.dirname(os.path.abspath(nuitka.__file__)),
                        "build", "static_src")


def target_path(explicit: str = "") -> str:
    if explicit:
        return explicit
    root = static_src_dir()
    if not root:
        return ""
    return os.path.join(root, "MetaPathBasedLoaderResourceReader.c")


def analyse(path: str) -> dict:
    """What state the file is in, without changing it."""
    if not path or not os.path.isfile(path):
        return {"exists": False, "patched": False, "needs": False,
                "decl_line": 0, "inc_line": 0}
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    decl = next((index for index, line in enumerate(lines)
                 if line.strip() == DECLARATION), -1)
    include = next((index for index, line in enumerate(lines)
                    if line.strip() == INCLUDE), -1)
    # patched means the incomplete declaration is gone, or the include already
    # precedes it (a newer Nuitka may have reordered it itself)
    patched = decl < 0 or (include >= 0 and include < decl)
    return {"exists": True, "patched": patched, "needs": not patched,
            "decl_line": decl + 1, "inc_line": include + 1}


def apply(path: str, quiet: bool = False) -> bool:
    """Remove the incomplete declaration.  True when it changed something."""
    state = analyse(path)
    if not state["exists"]:
        raise SystemExit("Nuitka source not found: %s" % (path or "<none>"))
    if state["patched"]:
        if not quiet:
            print("  already patched, nothing to do")
        return False
    if state["inc_line"] <= 0:
        raise SystemExit(
            "the include of MetaPathBasedLoaderResourceReaderFiles.c is not in\n"
            "  %s\n"
            "so this patch does not apply; Nuitka has changed, please report it"
            % path)

    lines = io.open(path, encoding="utf-8").read().splitlines(True)
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)

    decl_index = state["decl_line"] - 1
    removed = lines.pop(decl_index)
    io.open(path, "w", encoding="utf-8", newline="").write("".join(lines))

    if not quiet:
        print("  patched: removed  %s" % removed.strip())
        print("  the definition comes from the included file, which is the only")
        print("  declaration MSVC accepts; the array is not used before it")
        print("  backup : %s" % backup)
    return True


def revert(path: str, quiet: bool = False) -> bool:
    backup = path + ".orig"
    if not os.path.isfile(backup):
        if not quiet:
            print("  no backup to restore")
        return False
    shutil.copy2(backup, path)
    os.remove(backup)
    if not quiet:
        print("  restored from %s" % backup)
    return True


def verify(path: str) -> int:
    """Check the arrangement is the one MSVC needs."""
    state = analyse(path)
    if not state["exists"]:
        print("  file not found: %s" % path)
        return 1
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    decl = state["decl_line"]
    include = state["inc_line"]
    print("  file    : %s" % path)
    if decl:
        print("  decl    : line %d" % decl)
    else:
        print("  decl    : absent (newer Nuitka)")
    if include:
        print("  include : line %d" % include)
    if state["patched"]:
        print("  state   : OK for MSVC")
        return 0
    print("  state   : MSVC will fail with C2133; run this tool to patch")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make Nuitka 4.3's loader source acceptable to MSVC.")
    parser.add_argument("--check", action="store_true",
                       help="report the state and change nothing")
    parser.add_argument("--revert", action="store_true",
                       help="restore the original file from the backup")
    parser.add_argument("--file", default="",
                       help="patch this file instead of the installed Nuitka")
    args = parser.parse_args()

    path = target_path(args.file)
    if not path:
        print("Nuitka is not installed in this interpreter")
        return 2

    if args.revert:
        print("reverting")
        revert(path)
        return 0
    if args.check:
        return verify(path)

    print("patching Nuitka for MSVC")
    changed = apply(path)
    return 0 if (changed or analyse(path)["patched"]) else 1


if __name__ == "__main__":
    sys.exit(main())
