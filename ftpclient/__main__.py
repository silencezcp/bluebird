"""Run the client with ``python -m ftpclient``."""

import sys

if __name__ == "__main__" and not __package__:
    # Started directly: right-clicking this file in an IDE, or running
    # `python ftpclient/__main__.py`.  Every module in this package uses relative
    # imports, which cannot work that way, and the resulting "attempted
    # relative import with no known parent package" says nothing useful.
    # Re-run the file as the module it is, from the project root.
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    sys.stderr.write("Starting __main__.py directly; running it as "
                     "'python -m ftpclient.__main__' instead.\n")
    runpy.run_module("ftpclient.__main__", run_name="__main__", alter_sys=True)
    # A library module has no main block, so nothing above ran.  Say so rather
    # than exiting silently.  Start the application with run.py.
    sys.stderr.write("  (ftpclient.__main__ has no main entry point; "
                     "start the client with run.py)\n")
    raise SystemExit(0)
from .app import run

if __name__ == "__main__":
    sys.exit(run())
