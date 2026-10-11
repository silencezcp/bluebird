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

__version__ = "1.36.1"
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
