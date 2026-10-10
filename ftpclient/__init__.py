"""Nacre FTP — a modern, cream-themed FTP / FTPS / SFTP client built on PyQt5.

The package is deliberately split so the networking layer never imports Qt:

    ftpclient.config   - persisted application settings (JSON)
    ftpclient.theme    - colour palette + Qt stylesheet generation
    ftpclient.icons    - runtime-recolourable SVG icons
    ftpclient.models   - file list / transfer queue item models
    ftpclient.session  - FTP, FTPS and SFTP sessions behind one interface
    ftpclient.transfer - background transfer queue
    ftpclient.ui       - widgets and windows
"""

__version__ = "1.0.0"
__appname__ = "Nacre FTP"
__orgname__ = "Nacre"
__author__ = "silence"
__author_email__ = "2446522180@qq.com"
__copyright__ = "Copyright (c) 2026 silence"

#: shown in the About dialog and in the executable's version resource
AUTHORS = (
    ("silence", "author, design and code"),
)
