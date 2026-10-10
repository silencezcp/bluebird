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
