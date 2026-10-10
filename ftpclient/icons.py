"""SVG icon factory.

Every icon is defined as a tiny SVG template with ``{{token}}`` colour
placeholders.  Templates are rendered on demand with
:class:`PyQt5.QtSvg.QSvgRenderer` and cached, which means the whole icon set
recolours instantly when the user edits the palette — no external asset
files, no rebuild step.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

from .theme import Theme

# ---------------------------------------------------------------------------
# File-type icons (drawn inside a 24x24 box)
# ---------------------------------------------------------------------------

SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
            'viewBox="0 0 24 24" width="24" height="24">')
SVG_TAIL = "</svg>"

_FILE_SHEET = """
<path d="M6 3h7.5L19 8.5V20a1.4 1.4 0 0 1-1.4 1.4H6A1.4 1.4 0 0 1 4.6 20V4.4A1.4 1.4 0 0 1 6 3z"
      fill="{{tint}}" fill-opacity="0.16" stroke="{{primary}}" stroke-width="1.3"
      stroke-linejoin="round"/>
<path d="M13.4 3.2V8.4h5.2" fill="none" stroke="{{primary}}"
      stroke-width="1.3" stroke-linejoin="round"/>
"""

FILE_TEMPLATES: Dict[str, str] = {
    "folder": """
<path d="M3 7.4A1.9 1.9 0 0 1 4.9 5.5h4.2l1.9 2.2h7.1A1.9 1.9 0 0 1 20 9.6v1.1H3z"
      fill="{{folder_dark}}"/>
<path d="M2.6 10.4h18.3a1.5 1.5 0 0 1 1.5 1.8l-1.3 6.4A2 2 0 0 1 19.2 20H4.4a2 2 0 0 1-1.9-1.5L1.2 12.2a1.5 1.5 0 0 1 1.4-1.8z"
      fill="{{folder}}"/>
""",
    "folder_open": """
<path d="M3 7.4A1.9 1.9 0 0 1 4.9 5.5h4.2l1.9 2.2h7.1A1.9 1.9 0 0 1 20 9.6v1.1H3z"
      fill="{{folder_dark}}"/>
<path d="M2.6 10.4h18.3a1.5 1.5 0 0 1 1.5 1.8l-1.3 6.4A2 2 0 0 1 19.2 20H4.4a2 2 0 0 1-1.9-1.5L1.2 12.2a1.5 1.5 0 0 1 1.4-1.8z"
      fill="{{folder}}"/>
<path d="M8 14.4h6" stroke="{{text_inverse}}" stroke-width="1.4"
      stroke-linecap="round" opacity="0.85"/>
""",
    "folder_up": """
<path d="M3 7.4A1.9 1.9 0 0 1 4.9 5.5h4.2l1.9 2.2h7.1A1.9 1.9 0 0 1 20 9.6v1.1H3z"
      fill="{{folder_dark}}"/>
<path d="M2.6 10.4h18.3a1.5 1.5 0 0 1 1.5 1.8l-1.3 6.4A2 2 0 0 1 19.2 20H4.4a2 2 0 0 1-1.9-1.5L1.2 12.2a1.5 1.5 0 0 1 1.4-1.8z"
      fill="{{folder}}"/>
<path d="M12 18v-5.2M9.6 15.2 12 12.8l2.4 2.4" fill="none"
      stroke="{{text_inverse}}" stroke-width="1.5" stroke-linecap="round"
      stroke-linejoin="round"/>
""",
    "file": _FILE_SHEET,
    "text": _FILE_SHEET + """
<path d="M7 12.2h8M7 14.8h8M7 17.4h5" stroke="{{primary}}" stroke-width="1.2"
      stroke-linecap="round" opacity="0.75"/>
""",
    "code": _FILE_SHEET + """
<path d="M10.2 12.4 8 15l2.2 2.6M13.8 12.4 16 15l-2.2 2.6" fill="none"
      stroke="{{primary}}" stroke-width="1.3" stroke-linecap="round"
      stroke-linejoin="round"/>
""",
    "image": """
<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2.2"
      fill="{{tint}}" fill-opacity="0.18" stroke="{{primary}}" stroke-width="1.3"/>
<circle cx="8.6" cy="9.6" r="1.6" fill="{{primary}}"/>
<path d="M4.6 17.6 9.9 12.4l3.2 3.1 2.6-2.4 3.7 3.6" fill="none"
      stroke="{{primary}}" stroke-width="1.3" stroke-linecap="round"
      stroke-linejoin="round"/>
""",
    "media": """
<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2.2"
      fill="{{tint}}" fill-opacity="0.18" stroke="{{primary}}" stroke-width="1.3"/>
<path d="M10.2 9.1 15 12l-4.8 2.9z" fill="{{primary}}"/>
""",
    "archive": """
<rect x="4.2" y="3.4" width="15.6" height="17.2" rx="2.2"
      fill="{{tint}}" fill-opacity="0.18" stroke="{{primary}}" stroke-width="1.3"/>
<path d="M12 3.4v9.2" stroke="{{primary}}" stroke-width="1.3"/>
<path d="M10.2 5.2h3.6M10.2 7.4h3.6M10.2 9.6h3.6" stroke="{{primary}}"
      stroke-width="1.1" opacity="0.8"/>
<rect x="10" y="13" width="4" height="3.4" rx="0.9" fill="{{primary}}"/>
""",
    "doc": _FILE_SHEET + """
<path d="M7.4 12.4h7M7.4 15h7M7.4 17.6h4" stroke="{{primary}}"
      stroke-width="1.2" stroke-linecap="round" opacity="0.75"/>
<path d="M15.6 17.8v-3.6" stroke="{{primary}}" stroke-width="1.4"
      stroke-linecap="round"/>
""",
    "exec": """
<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2.4"
      fill="{{tint}}" fill-opacity="0.18" stroke="{{primary}}" stroke-width="1.3"/>
<path d="M7 9.4 9.8 12 7 14.6" fill="none" stroke="{{primary}}"
      stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M11.6 15.2h5.4" stroke="{{primary}}" stroke-width="1.5"
      stroke-linecap="round"/>
""",
    "link": """
<path d="M6 3h7.5L19 8.5V20a1.4 1.4 0 0 1-1.4 1.4H6A1.4 1.4 0 0 1 4.6 20V4.4A1.4 1.4 0 0 1 6 3z"
      fill="{{tint}}" fill-opacity="0.16" stroke="{{primary}}" stroke-width="1.3"
      stroke-linejoin="round"/>
<path d="M13.4 3.2V8.4h5.2" fill="none" stroke="{{primary}}"
      stroke-width="1.3" stroke-linejoin="round"/>
<path d="M9.4 15.6a2.3 2.3 0 0 0 3.2 0l1.7-1.7M14.6 14.2a2.3 2.3 0 0 0-3.2 0l-1.7 1.7"
      fill="none" stroke="{{primary}}" stroke-width="1.3" stroke-linecap="round"/>
""",
    "drive": """
<rect x="3.2" y="8.4" width="17.6" height="7.2" rx="2"
      fill="{{tint}}" fill-opacity="0.18" stroke="{{primary}}" stroke-width="1.3"/>
<circle cx="7.2" cy="12" r="1.1" fill="{{primary}}"/>
<path d="M16.4 12h2.2" stroke="{{primary}}" stroke-width="1.4"
      stroke-linecap="round"/>
""",
}

# ---------------------------------------------------------------------------
# Toolbar / action icons (stroke based, 24x24)
# ---------------------------------------------------------------------------

_ACTION_SHEET = """
<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"
      stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}"/>
"""

ACTION_TEMPLATES: Dict[str, str] = {
    "connect": """
<path d="M10.6 13.4a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.4 1.4" fill="none"
      stroke="{{primary}}" stroke-width="1.7" stroke-linecap="round"/>
<path d="M13.4 10.6a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.4-1.4" fill="none"
      stroke="{{primary}}" stroke-width="1.7" stroke-linecap="round"/>
""",
    "disconnect": """
<path d="M4 4l16 16" stroke="{{danger}}" stroke-width="1.9" stroke-linecap="round"/>
<path d="M10.6 13.4a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.4 1.4" fill="none"
      stroke="{{danger}}" stroke-width="1.7" stroke-linecap="round"/>
<path d="M13.4 10.6a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.4-1.4" fill="none"
      stroke="{{danger}}" stroke-width="1.7" stroke-linecap="round"/>
""",
    "refresh": """
<path d="M20 12a8 8 0 1 1-2.6-5.9" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round"/>
<path d="M20 4.4v4.2h-4.2" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "up": """
<path d="M12 4.6v14.8M5.6 11 12 4.6 18.4 11" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "arrow_left": """
<path d="M20 12H4M10 5.6 3.6 12 10 18.4" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "arrow_right": """
<path d="M4 12h16M14 5.6 20.4 12 14 18.4" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "home": """
<path d="M4 10.6 12 4l8 6.6" fill="none" stroke="{{primary}}" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round"/>
<path d="M6.2 9.6V19a1 1 0 0 0 1 1h9.6a1 1 0 0 0 1-1V9.6" fill="none"
      stroke="{{primary}}" stroke-width="1.8" stroke-linecap="round"
      stroke-linejoin="round"/>
""",
    "parent": """
<path d="M4 12h11" stroke="{{primary}}" stroke-width="2" stroke-linecap="round"/>
<path d="M11 6.6 4.6 12 11 17.4" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M17.6 5.4v13.2" stroke="{{primary}}" stroke-width="2"
      stroke-linecap="round"/>
""",
    "new_folder": """
<path d="M3 7.4A1.9 1.9 0 0 1 4.9 5.5h4.2l1.9 2.2h7.1A1.9 1.9 0 0 1 20 9.6v1.1H3z"
      fill="{{folder_dark}}"/>
<path d="M2.6 10.4h18.3a1.5 1.5 0 0 1 1.5 1.8l-1.3 6.4A2 2 0 0 1 19.2 20H4.4a2 2 0 0 1-1.9-1.5L1.2 12.2a1.5 1.5 0 0 1 1.4-1.8z"
      fill="{{folder}}"/>
<path d="M12 13.2v4M10 15.2h4" stroke="{{text_inverse}}" stroke-width="1.5"
      stroke-linecap="round"/>
""",
    "new_file": """
<path d="M6 3h7.5L19 8.5V20a1.4 1.4 0 0 1-1.4 1.4H6A1.4 1.4 0 0 1 4.6 20V4.4A1.4 1.4 0 0 1 6 3z"
      fill="{{primary}}" fill-opacity="0.14" stroke="{{primary}}" stroke-width="1.5"
      stroke-linejoin="round"/>
<path d="M13.4 3.2V8.4h5.2" fill="none" stroke="{{primary}}" stroke-width="1.5"
      stroke-linejoin="round"/>
<path d="M12 12v5M9.5 14.5h5" stroke="{{primary}}" stroke-width="1.6"
      stroke-linecap="round"/>
""",
    "rename": """
<path d="M4 20h4.2L19 9.2a2.1 2.1 0 0 0 0-3l-1.2-1.2a2.1 2.1 0 0 0-3 0L4 15.8z"
      fill="{{primary}}" fill-opacity="0.14" stroke="{{primary}}"
      stroke-width="1.6" stroke-linejoin="round"/>
<path d="M14.2 5.6 18.4 9.8" stroke="{{primary}}" stroke-width="1.6"/>
""",
    "delete": """
<path d="M5 7h14" stroke="{{danger}}" stroke-width="1.8" stroke-linecap="round"/>
<path d="M9.6 7V5.2A1.2 1.2 0 0 1 10.8 4h2.4a1.2 1.2 0 0 1 1.2 1.2V7"
      fill="none" stroke="{{danger}}" stroke-width="1.6" stroke-linecap="round"/>
<path d="M6.6 7l.9 12a1.4 1.4 0 0 0 1.4 1.3h6.2A1.4 1.4 0 0 0 16.5 19l.9-12"
      fill="none" stroke="{{danger}}" stroke-width="1.6" stroke-linejoin="round"/>
<path d="M10.4 10.6v6M13.6 10.6v6" stroke="{{danger}}" stroke-width="1.5"
      stroke-linecap="round"/>
""",
    "download": """
<path d="M12 3.6v10.8" stroke="{{primary}}" stroke-width="2" stroke-linecap="round"/>
<path d="M7.4 10.4 12 15l4.6-4.6" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M4.4 18.6h15.2" stroke="{{primary}}" stroke-width="2"
      stroke-linecap="round"/>
""",
    "upload": """
<path d="M12 15.2V4.4" stroke="{{primary}}" stroke-width="2" stroke-linecap="round"/>
<path d="M7.4 9 12 4.4 16.6 9" fill="none" stroke="{{primary}}"
      stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M4.4 18.6h15.2" stroke="{{primary}}" stroke-width="2"
      stroke-linecap="round"/>
""",
    "sync": """
<path d="M4.6 10.4A7.6 7.6 0 0 1 17 6.6l2.4 2.4" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M19.4 13.6A7.6 7.6 0 0 1 7 17.4l-2.4-2.4" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M19.4 4.6v4.4H15M4.6 19.4V15H9" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "settings": """
<circle cx="12" cy="12" r="3.1" fill="none" stroke="{{primary}}" stroke-width="1.7"/>
<path d="M12 3.4v2.2M12 18.4v2.2M3.4 12h2.2M18.4 12h2.2M6 6l1.6 1.6M16.4 16.4 18 18M18 6l-1.6 1.6M7.6 16.4 6 18"
      stroke="{{primary}}" stroke-width="1.7" stroke-linecap="round"/>
""",
    "palette": """
<path d="M12 3.6c-4.7 0-8.4 3.6-8.4 8.1 0 3.8 2.9 6.4 6.2 6.4 1.6 0 2.4-.9 2.4-1.9 0-.9-.6-1.3-.6-2.1 0-1 .8-1.7 2-1.7h1.7c2.6 0 4.7-1.9 4.7-4.4 0-2.6-3.2-4.4-8-4.4z"
      fill="{{primary}}" fill-opacity="0.14" stroke="{{primary}}" stroke-width="1.6"
      stroke-linejoin="round"/>
<circle cx="7.8" cy="10.4" r="1.2" fill="{{primary}}"/>
<circle cx="11.6" cy="7.6" r="1.2" fill="{{primary}}"/>
<circle cx="16" cy="9.2" r="1.2" fill="{{primary}}"/>
""",
    "sites": """
<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2.4" fill="{{primary}}"
      fill-opacity="0.12" stroke="{{primary}}" stroke-width="1.6"/>
<path d="M3.4 9.2h17.2" stroke="{{primary}}" stroke-width="1.6"/>
<circle cx="6.4" cy="6.9" r="0.9" fill="{{primary}}"/>
<circle cx="9.2" cy="6.9" r="0.9" fill="{{primary}}"/>
<path d="M9.6 13.4h6.4M9.6 16.2h4" stroke="{{primary}}" stroke-width="1.5"
      stroke-linecap="round"/>
""",
    "queue": """
<path d="M4 6.4h16M4 12h11M4 17.6h7" stroke="{{primary}}" stroke-width="1.9"
      stroke-linecap="round"/>
<path d="M18.4 14.6v5.6M16 17.4l2.4 2.4 2.4-2.4" fill="none" stroke="{{accent}}"
      stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "log": """
<rect x="4" y="3.6" width="16" height="16.8" rx="2.4" fill="{{primary}}"
      fill-opacity="0.10" stroke="{{primary}}" stroke-width="1.6"/>
<path d="M7.4 8.4h9.2M7.4 12h9.2M7.4 15.6h5.6" stroke="{{primary}}"
      stroke-width="1.5" stroke-linecap="round"/>
""",
    "transfer": """
<path d="M4 8.4h13.4M14 4.8 17.6 8.4 14 12" fill="none" stroke="{{primary}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M20 15.6H6.6M10 12l-3.6 3.6L10 19.2" fill="none" stroke="{{accent}}"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "filter": """
<path d="M4 5.6h16l-6.2 7.4v5.4l-3.6 2v-7.4z" fill="{{primary}}"
      fill-opacity="0.16" stroke="{{primary}}" stroke-width="1.6"
      stroke-linejoin="round"/>
""",
    "search": """
<circle cx="10.6" cy="10.6" r="6" fill="none" stroke="{{primary}}"
        stroke-width="1.8"/>
<path d="M15.2 15.2 20 20" stroke="{{primary}}" stroke-width="1.8"
      stroke-linecap="round"/>
""",
    "edit": """
<path d="M4 20h4.2L19 9.2a2.1 2.1 0 0 0 0-3l-1.2-1.2a2.1 2.1 0 0 0-3 0L4 15.8z"
      fill="{{primary}}" fill-opacity="0.14" stroke="{{primary}}"
      stroke-width="1.6" stroke-linejoin="round"/>
<path d="M14.2 5.6 18.4 9.8" stroke="{{primary}}" stroke-width="1.6"/>
""",
    "properties": """
<circle cx="12" cy="12" r="8.4" fill="{{primary}}" fill-opacity="0.12"
        stroke="{{primary}}" stroke-width="1.6"/>
<path d="M12 10.8v5.4" stroke="{{primary}}" stroke-width="1.8"
      stroke-linecap="round"/>
<circle cx="12" cy="7.9" r="1.1" fill="{{primary}}"/>
""",
    "eye": """
<path d="M2.6 12S6 6.4 12 6.4 21.4 12 21.4 12 18 17.6 12 17.6 2.6 12 2.6 12z"
      fill="{{primary}}" fill-opacity="0.12" stroke="{{primary}}" stroke-width="1.6"/>
<circle cx="12" cy="12" r="2.8" fill="none" stroke="{{primary}}" stroke-width="1.6"/>
""",
    "eye_off": """
<path d="M2.6 12S6 6.4 12 6.4c1.6 0 3 .4 4.2 1" fill="none" stroke="{{primary}}"
      stroke-width="1.6" stroke-linecap="round"/>
<path d="M19.6 9.4c1.1 1.4 1.8 2.6 1.8 2.6S18 17.6 12 17.6c-1.4 0-2.6-.3-3.7-.8"
      fill="none" stroke="{{primary}}" stroke-width="1.6" stroke-linecap="round"/>
<path d="M4 4l16 16" stroke="{{danger}}" stroke-width="1.8" stroke-linecap="round"/>
""",
    "save": """
<path d="M5 4.6h10.4L20 9.2V19a1.4 1.4 0 0 1-1.4 1.4H5A1.4 1.4 0 0 1 3.6 19V6A1.4 1.4 0 0 1 5 4.6z"
      fill="{{primary}}" fill-opacity="0.13" stroke="{{primary}}" stroke-width="1.6"
      stroke-linejoin="round"/>
<path d="M7.6 4.6v4.8h7.2V4.6" fill="none" stroke="{{primary}}" stroke-width="1.5"/>
<rect x="7.4" y="13.4" width="9.2" height="7" rx="1.2" fill="{{primary}}"
      fill-opacity="0.2" stroke="{{primary}}" stroke-width="1.4"/>
""",
    "star": """
<path d="M12 3.8l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 17.1l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"
      fill="{{warning}}" fill-opacity="0.25" stroke="{{warning}}" stroke-width="1.5"
      stroke-linejoin="round"/>
""",
    "close": """
<path d="M6 6l12 12M18 6 6 18" stroke="{{primary}}" stroke-width="1.9"
      stroke-linecap="round"/>
""",
    "check": """
<path d="M4.8 12.6 9.6 17.4 19.2 6.6" fill="none" stroke="{{success}}"
      stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
""",
    "pause": """
<rect x="7" y="5" width="3.6" height="14" rx="1.2" fill="{{primary}}"/>
<rect x="13.4" y="5" width="3.6" height="14" rx="1.2" fill="{{primary}}"/>
""",
    "play": """
<path d="M7.4 5.2 18.6 12 7.4 18.8z" fill="{{primary}}"/>
""",
    "clear": """
<path d="M4.4 6.6h15.2M9.4 6.6V4.9h5.2v1.7" fill="none" stroke="{{primary}}"
      stroke-width="1.7" stroke-linecap="round"/>
<path d="M6.4 6.6 7.6 19a1.4 1.4 0 0 0 1.4 1.3h6a1.4 1.4 0 0 0 1.4-1.3l1.2-12.4"
      fill="none" stroke="{{primary}}" stroke-width="1.7" stroke-linejoin="round"/>
""",
    "info": """
<circle cx="12" cy="12" r="8.4" fill="{{info}}" fill-opacity="0.14"
        stroke="{{info}}" stroke-width="1.6"/>
<path d="M12 11v5.4" stroke="{{info}}" stroke-width="1.9" stroke-linecap="round"/>
<circle cx="12" cy="8" r="1.1" fill="{{info}}"/>
""",
    "warning": """
<path d="M12 4.2 21 19.4H3z" fill="{{warning}}" fill-opacity="0.18"
      stroke="{{warning}}" stroke-width="1.6" stroke-linejoin="round"/>
<path d="M12 9.6v4.6" stroke="{{warning}}" stroke-width="1.9"
      stroke-linecap="round"/>
<circle cx="12" cy="16.8" r="1.1" fill="{{warning}}"/>
""",
    "bookmark": """
<path d="M6.4 4.4h11.2v15.2L12 15.6l-5.6 4z" fill="{{accent}}"
      fill-opacity="0.18" stroke="{{accent}}" stroke-width="1.6"
      stroke-linejoin="round"/>
""",
    "bookmark_off": """
<path d="M6.4 4.4h11.2v15.2L12 15.6l-5.6 4z" fill="none" stroke="{{text_muted}}"
      stroke-width="1.6" stroke-linejoin="round"/>
""",
}

#: default colour tokens for every icon
_ICON_DEFAULTS: Dict[str, Dict[str, str]] = {}


def _spec(template: str) -> Dict[str, str]:
    """Default colour tokens used by the file-type templates."""
    return {
        "primary": "file",
        "tint": "file",
        "folder": "folder",
        "folder_dark": "folder_dark",
        "text_inverse": "text_inverse",
        "accent": "accent",
        "danger": "danger",
        "warning": "warning",
        "success": "success",
        "info": "info",
        "text_muted": "text_muted",
    }


class IconFactory(object):
    """Renders and caches recolourable SVG icons."""

    def __init__(self, theme: Theme) -> None:
        self._theme = theme
        self._cache: Dict[Any, QIcon] = {}
        theme.changed.connect(self.clear)

    # -- cache ---------------------------------------------------------
    def clear(self) -> None:
        self._cache.clear()

    def _key(self, name: str, color: str, size: int, kind: str) -> Any:
        return (name, color, size, kind)

    # -- public API ----------------------------------------------------
    def file_icon(self, name: str, color: str, kind: str = "file",
                  size: Optional[int] = None) -> QIcon:
        size = size or self._theme.row_icon_size()
        key = self._key(name, color, size, kind)
        icon = self._cache.get(key)
        if icon is None:
            icon = self._render(self._file_template(name), color, size, kind)
            self._cache[key] = icon
        return icon

    def action_icon(self, name: str, color: Optional[str] = None,
                    size: int = 22) -> QIcon:
        color = color or self._theme.color("text")
        key = self._key("action:" + name, color, size, "")
        icon = self._cache.get(key)
        if icon is None:
            template = ACTION_TEMPLATES.get(name)
            if template is None:
                template = FILE_TEMPLATES.get(name, FILE_TEMPLATES["file"])
            icon = self._render(template, color, size, "")
            self._cache[key] = icon
        return icon

    def pixmap(self, name: str, color: str, size: int = 24,
               kind: str = "file") -> QPixmap:
        return self._render(self._file_template(name), color, size, kind).pixmap(size, size)

    # -- internals -----------------------------------------------------
    def _file_template(self, name: str) -> str:
        if name in FILE_TEMPLATES:
            return FILE_TEMPLATES[name]
        if name in ACTION_TEMPLATES:
            return ACTION_TEMPLATES[name]
        return FILE_TEMPLATES["file"]

    def _resolve(self, template: str, primary_color: str) -> str:
        """Substitute ``{{token}}`` placeholders with palette colours."""
        theme = self._theme
        values = _spec(template)
        rendered = template
        for token in ("primary", "tint", "folder", "folder_dark", "text_inverse",
                      "accent", "danger", "warning", "success", "info",
                      "text_muted"):
            if token == "primary" or token == "tint":
                value = primary_color
            else:
                value = theme.color(values.get(token, token))
            rendered = rendered.replace("{{%s}}" % token, value)
        return rendered

    def _render(self, template: str, color: str, size: int, kind: str) -> QIcon:
        svg = SVG_HEAD + self._resolve(template, color) + SVG_TAIL
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        icon = QIcon()
        for scale in (1, 2):
            px = int(round(size * scale))
            pixmap = QPixmap(px, px)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            renderer.render(painter, QRectF(0, 0, px, px))
            painter.end()
            pixmap.setDevicePixelRatio(float(scale))
            icon.addPixmap(pixmap)
        return icon

    def svg_for(self, template: str, color: str) -> str:
        """Expose the resolved SVG (used by tests and by ``--dump-icons``)."""
        return SVG_HEAD + self._resolve(template, color) + SVG_TAIL

    def _device_pixel_ratio(self) -> float:
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                return float(app.devicePixelRatio())
        except Exception:
            pass
        return 1.0
