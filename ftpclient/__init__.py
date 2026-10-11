"""BlueBird (青鸟) — a modern, cream-themed FTP / FTPS / SFTP client on PyQt5.

The name is the blue bird of Chinese legend that carried letters between
people; the icon is that messenger with a sealed letter in its beak.

The package is deliberately split so the networking layer never imports Qt:

    ftpclient.core     - plain data types, no Qt (used by the CLI too)
    ftpclient.config   - persisted application settings (JSON) and connections
    ftpclient.theme    - colour palette + Qt stylesheet generation
    ftpclient.icons    - runtime-recolourable SVG icons
    ftpclient.appicon  - the drawn application icon
    ftpclient.models   - file list / transfer queue item models
    ftpclient.session  - FTP, FTPS and SFTP sessions behind one interface
    ftpclient.transfer - background transfer queue
    ftpclient.app      - GUI entry point
"""

__version__ = "1.36.2"
__appname__ = "BlueBird"
#: The Chinese name, shown alongside the English one in the interface.  It is
#: not translated: 青鸟 is the product name, not a description.
__appname_cn__ = "\u9752\u9e1f"
__orgname__ = "BlueBird"
__author__ = "silence"
__author_email__ = "2446522180@qq.com"
__copyright__ = "Copyright (c) 2026 silence"


def display_name(language: str = "") -> str:
    """The product name to show: 青鸟 BlueBird in Chinese, BlueBird in English."""
    from . import i18n
    code = language or i18n.current_language()
    if code == "zh":
        return "%s %s" % (__appname_cn__, __appname__)
    return __appname__


#: shown in the About dialog and in the executable's version resource
AUTHORS = (
    ("silence", "author, design and code"),
)


def boot_if_main(name: str) -> None:
    """Run *name* correctly when someone starts a package file directly.

    Every module here uses relative imports (``from . import config``), so
    running one on its own - which is what right-clicking a file in an IDE and
    choosing Run does - fails with::

        ImportError: attempted relative import with no known parent package

    That message says nothing about the actual fix.  Calling this at the top of a
    module detects the situation and re-runs the file as the module it is,
    ``python -m ftpclient.<name>``, which is what the caller meant.  Nothing
    happens on a normal import, so the cost when running the application
    properly is one comparison.
    """
    if __name__ != "__main__" or __package__:
        return
    import os
    import runpy
    import sys

    # this file is <project>/ftpclient/__init__.py, so the project is two up
    project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project not in sys.path:
        sys.path.insert(0, project)
    target = "ftpclient.%s" % name
    sys.stderr.write(
        "%s.py was started directly; re-running it as '%s -m %s' instead.\n"
        "To start the application, use run.py or '%s -m ftpclient'.\n"
        % (name, os.path.basename(sys.executable), target,
           os.path.basename(sys.executable)))
    raise SystemExit(runpy.run_module(target, run_name="__main__", alter_sys=True))

