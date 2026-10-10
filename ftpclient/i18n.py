"""Bilingual interface strings (English / \u4e2d\u6587) with live switching.

The catalogue is keyed by the **English** wording, which makes the source code
readable and means a missing entry silently falls back to English instead of
showing a placeholder.

Switching language at runtime emits :attr:`i18n.changed`; every view connects
its own ``retranslate`` method to it, so no restart is needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

LANGUAGE_EN = "en"
LANGUAGE_ZH = "zh"
DEFAULT_LANGUAGE = LANGUAGE_ZH

LANGUAGE_NAMES = [
    ("zh", "\u4e2d\u6587 (Chinese)"),
    ("en", "English"),
]


class _I18n(QObject):
    """Holds the active language and notifies the interface on change."""

    changed = pyqtSignal()

    def __init__(self) -> None:
        super(_I18n, self).__init__()
        self._language = DEFAULT_LANGUAGE

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str, notify: bool = True) -> bool:
        language = (language or "").lower()
        if language not in (LANGUAGE_EN, LANGUAGE_ZH):
            language = DEFAULT_LANGUAGE
        if language == self._language:
            return False
        self._language = language
        if notify:
            self.changed.emit()
        return True

    @property
    def is_chinese(self) -> bool:
        return self._language == LANGUAGE_ZH


i18n = _I18n()


def set_language(language: str, notify: bool = True) -> bool:
    return i18n.set_language(language, notify=notify)


def current_language() -> str:
    return i18n.language


def is_chinese() -> bool:
    return i18n.is_chinese


def T(text: str) -> str:
    """Translate ``text`` (an English key) into the active language."""
    if not text:
        return text
    if i18n.language == LANGUAGE_EN:
        return text
    return ZH.get(text, text)


# ``_`` is the conventional alias used at the call sites.
_ = T


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

ZH: Dict[str, str] = {
    # -- menus ----------------------------------------------------------
    "&File": "文件(&F)",
    "&Server": "服务器(&S)",
    "&Transfer": "传输(&T)",
    "&View": "视图(&V)",
    "&Tools": "工具(&O)",
    "&Help": "帮助(&H)",
    "&User manual": "用户手册(&U)",
    "Open the manual as &PDF": "以 PDF 打开手册(&P)",
    "Open the &documentation folder": "打开文档文件夹(&D)",
    "User manual": "用户手册",
    "Manual": "手册",
    "Manual not found": "未找到手册",
    "The manual file is missing from this installation.":
        "此安装中缺少手册文件。",
    "The manual file was not found in this installation.":
        "此安装中未找到手册文件。",
    "No manual file could be opened.": "无法打开手册文件。",
    "Could not open %s": "无法打开 %s",
    "Documentation": "文档",
    "Zoom in": "放大",
    "Zoom out": "缩小",
    "Save as PDF…": "另存为 PDF…",
    "Rendering the PDF…": "正在生成 PDF…",
    "Could not write the PDF": "无法写入 PDF",
    "Open in the browser": "用浏览器打开",
    "Back": "后退",
    "Forward": "前进",
    "&Site manager…": "站点管理(&S)…",
    "Manage saved connections": "管理已保存的连接",
    "&Connect…": "连接(&C)…",
    "Recent connections": "最近连接",
    "Saved connections (config.ini)": "已保存的连接（config.ini）",
    "Recently used": "最近使用",
    "(nothing yet)": "（暂无）",
    "Save &log…": "保存日志(&L)…",
    "E&xit": "退出(&X)",
    "&Disconnect": "断开(&D)",
    "&Refresh": "刷新(&R)",
    "Create &directory…": "新建目录(&D)…",
    "&Rename…": "重命名(&R)…",
    "&Delete": "删除(&D)",
    "&Upload →": "上传 →(&U)",
    "← &Download": "← 下载(&D)",
    "&Pause queue": "暂停队列(&P)",
    "Re&try failed": "重试失败项(&T)",
    "Clear &finished": "清除已完成(&F)",
    "Show the &queue": "显示队列(&Q)",
    "Show &hidden files": "显示隐藏文件(&H)",
    "Auto-fit the &name column": "名称列自适应内容(&N)",
    "Show &permissions": "显示权限列(&P)",
    "Show file &owner": "显示属主列(&O)",
    "Fetch missing file si&zes": "补取缺失的文件大小(&Z)",
    "Refresh &local pane": "刷新本地面板(&L)",
    "Refresh &remote pane": "刷新远程面板(&R)",
    "&Preferences…": "偏好设置(&P)…",
    "&Swap panes": "交换左右面板(&S)",
    "&Edit remote file…": "编辑远程文件(&E)…",
    "Copy the remote &path": "复制远程路径(&P)",
    "Clear the &log": "清空日志(&L)",
    "&Keyboard shortcuts": "键盘快捷键(&K)",
    "&About": "关于(&A)",
    "Main": "主工具栏",

    # -- toolbar / connection bar ---------------------------------------
    "Connect": "连接",
    "Disconnect": "断开",
    "Refresh": "刷新",
    "Upload": "上传",
    "Download": "下载",
    "Pause queue": "暂停队列",
    "Preferences": "偏好设置",
    "Server": "服务器",
    "Connection name": "连接名",
    "Name this connection is saved under (config.ini)":
        "该连接保存到 config.ini 时使用的名字",
    "Host — e.g. ftp.example.com": "主机 — 例如 ftp.example.com",
    "User": "用户",
    "Password": "密码",
    "Site manager": "站点管理",

    # -- panes ----------------------------------------------------------
    "Local site": "本地站点",
    "Remote site": "远程站点",
    "This computer": "本机",
    "Not connected": "未连接",
    "Filter…": "筛选…",
    "Back": "后退",
    "Forward": "前进",
    "Parent directory (Alt+Up)": "上级目录（Alt+↑）",
    "Home directory": "主目录",
    "Switch drive / browse for a folder": "切换盘符 / 浏览文件夹",
    "Recent locations": "最近位置",
    "Refresh (F5)": "刷新（F5）",
    "Path": "路径",
    "Show hidden files": "显示隐藏文件",
    "Hide hidden files": "隐藏隐藏文件",
    "Every file size is already known": "所有文件大小都已获取",
    "Reading file sizes…": "正在读取文件大小…",
    "%d items": "%d 项",
    "%d files": "%d 个文件",
    "%d selected (%s)": "已选 %d 项（%s）",
    "%d size(s) pending": "%d 项大小待获取",

    # -- column headers --------------------------------------------------
    "Name": "名称",
    "Size": "大小",
    "Type": "类型",
    "Modified": "修改时间",
    "Permissions": "权限",
    "Owner": "属主",
    "FTP": "FTP",
    "FTPS": "FTPS",
    "SFTP": "SFTP",
    "Permissions: %s": "权限：%s",
    "Owner: %s": "属主：%s",
    "“%s” — ": "“%s” — ",
    "“%s” is %s. Opening it in the editor may be slow.\n\nContinue?":
        "“%s” 大小为 %s。用编辑器打开可能较慢。\n\n是否继续？",
    "File": "文件",
    "Direction": "方向",
    "Progress": "进度",
    "Speed": "速度",
    "Status": "状态",

    # -- file types ------------------------------------------------------
    "Folder": "文件夹",
    "File type": "文件",
    "Parent directory": "上级目录",
    "Symbolic link": "符号链接",
    "file": "文件",

    # -- context menus ---------------------------------------------------
    "Upload to the server": "上传到服务器",
    "Create folder…": "新建文件夹…",
    "Download to the local folder": "下载到本地文件夹",
    "Create directory…": "新建目录…",
    "Create empty file…": "新建空文件…",
    "Edit": "编辑",
    "Calculate folder size": "统计文件夹大小",
    "Permissions…": "权限…",
    "Properties": "属性",
    "Retry": "重试",
    "Pause/Resume the queue": "暂停/继续队列",
    "Remove from list": "从列表移除",
    "Clear finished": "清除已完成",
    "Browse for a folder…": "浏览文件夹…",

    # -- transfer queue --------------------------------------------------
    "Queue is empty": "队列为空",
    "Pause the queue": "暂停队列",
    "Resume the queue": "继续队列",
    "Retry failed transfers": "重试失败的传输",
    "Remove the selected items": "移除选中项",
    "Remove finished transfers": "移除已完成的传输",
    "Transferring": "传输中",
    "Queued": "排队中",
    "Completed": "已完成",
    "Failed": "失败",
    "Skipped": "已跳过",
    "Cancelled": "已取消",
    "Upload →": "上传 →",
    "← Download": "← 下载",
    "Show the queue": "显示队列",

    # -- status bar ------------------------------------------------------
    "Connected to %s%s": "已连接到 %s%s",
    "Connecting to %s…": "正在连接到 %s…",
    "Name column: %s": "名称列：%s",
    "auto-fit to contents": "自适应内容",
    "fixed width": "固定宽度",
    "Panes swapped": "已交换左右面板",
    "Remote path copied": "已复制远程路径",
    "Log saved to %s": "日志已保存到 %s",
    "Disconnected": "已断开连接",

    # -- connect dialog ---------------------------------------------------
    "Connect to server": "连接到服务器",
    "Connect to a server": "连接到服务器",
    "Protocol": "协议",
    "Host": "主机",
    "Port": "端口",
    "Private key": "私钥",
    "Optional OpenSSH private key": "可选的 OpenSSH 私钥文件",
    "Options": "选项",
    "Log in anonymously": "匿名登录",
    "Save this connection to config.ini": "把该连接保存到 config.ini",
    "Connections are stored in the local config.ini so you can reconnect "
    "with one click": "连接信息保存在本地 config.ini，方便一键重连",
    "Restore the suggested name (user@host)": "恢复建议名（用户名@主机）",
    "Show password": "显示密码",
    "Hide password": "隐藏密码",
    "Select private key": "选择私钥文件",
    "Please give this connection a name — it is how the connection is "
    "stored and listed.": "请给这个连接起个名字——它用于保存和显示该连接。",
    "Please enter a host name.": "请输入主机名。",
    "FTP - File Transfer Protocol": "FTP — 文件传输协议",
    "FTPS - FTP over explicit TLS": "FTPS — 显式 TLS 加密的 FTP",
    "SFTP - SSH File Transfer Protocol": "SFTP — SSH 文件传输协议",

    # -- site manager ------------------------------------------------------
    "Site manager — saved connections": "站点管理 — 已保存的连接",
    "Saved to %s": "保存位置：%s",
    "Saved connections": "已保存的连接",
    "Stored in %s": "保存在 %s",
    "Rename…": "重命名…",
    "Close": "关闭",
    "Rename connection": "重命名连接",
    "Select a saved connection first.": "请先选择一个已保存的连接。",
    "Delete connection": "删除连接",
    "Remove “%s” from config.ini?": "从 config.ini 中删除“%s”？",
    "Could not rename “%s”.": "无法重命名“%s”。",
    "Protocol: %s": "协议：%s",
    "Host: %s": "主机：%s",
    "Port: %s": "端口：%s",
    "User: %s": "用户：%s",
    "Password: %s": "密码：%s",
    "Name: %s": "名称：%s",
    "saved": "已保存",
    "not saved": "未保存",

    # -- preferences --------------------------------------------------------
    "Preferences": "偏好设置",
    "General": "常规",
    "Appearance": "外观",
    "Colours": "颜色",
    "Colors": "颜色",
    "Transfers": "传输",
    "Connection": "连接",
    "Language": "语言",
    "Interface language": "界面语言",
    "Takes effect immediately, no restart needed.": "立即生效，无需重启。",
    "Behaviour": "行为",
    "Startup": "启动",
    "Double click": "双击",
    "Open the folder / transfer the file": "打开文件夹 / 传输文件",
    "Always transfer": "总是传输",
    "Ask before deleting files": "删除文件前询问",
    "Ask before overwriting files": "覆盖文件前询问",
    "Reopen the last used directories": "重新打开上次使用的目录",
    "Local folder": "本地文件夹",
    "Log lines kept": "保留日志行数",
    "Browse…": "浏览…",
    "Theme preset": "主题预设",
    "Apply preset": "应用预设",
    "Presets replace the whole palette; tweak individual colours on the "
    "Colours page.": "预设会替换整套配色；单项颜色请在「颜色」页调整。",
    "Fonts and sizes": "字体与尺寸",
    "Interface font": "界面字体",
    "Font size": "字号",
    "Row height": "行高",
    "Icon size": "图标大小",
    "Alternating row colours": "隔行变色",
    "Show grid lines": "显示网格线",
    "Search colours…": "搜索颜色…",
    "Reset all": "全部重置",
    "Selected colour": "选中的颜色",
    "Pick…": "取色…",
    "Reset": "重置",
    "Folders default to blue and files keep the normal text colour. "
    "Pick any values you like — but keep them clearly different so the two "
    "are easy to tell apart at a glance.":
        "文件夹默认蓝色，文件默认跟随正文颜色。你可以随意修改，但请保持两者"
        "明显不同，方便一眼区分。",
    "Folder and file colours are very close — folders will be hard to pick out.":
        "⚠ 文件夹色与文件色非常接近——文件夹会不易辨认。",
    "File colour has too little contrast against the panel background.":
        "⚠ 文件色与面板底色对比度不足。",
    "Folder colour has too little contrast against the panel background.":
        "⚠ 文件夹色与面板底色对比度不足。",
    "Folder and symbolic-link colours look alike.":
        "⚠ 文件夹色与符号链接色过于相似。",
    "Queue": "队列",
    "Notification": "提示",
    "Show a popup when a transfer finishes": "传输完成后弹出提示窗口",
    "Refresh the pane when a transfer finishes": "传输完成后刷新对应面板",
    "Transfer complete": "传输完成",
    "Transfer finished with errors": "传输完成，但有失败项",
    "Transfer cancelled": "传输已取消",
    "Download complete": "下载完成",
    "Upload complete": "上传完成",
    "Download finished with errors": "下载完成，但有失败项",
    "Upload finished with errors": "上传完成，但有失败项",
    "Everything went through.": "全部传输成功。",
    "Succeeded: %d": "成功：%d 项",
    "Failed: %d": "失败：%d 项",
    "Cancelled: %d": "已取消：%d 项",
    "Destination folder:": "目标目录：",
    "Details:": "详细信息：",
    "... and %d more": "… 以及另外 %d 项",
    "Simultaneous transfers": "并发传输数",
    "Automatic retries": "自动重试次数",
    "Keep the original modification time": "保留原始修改时间",
    "Transfer mode": "传输模式",
    "Extensions always sent as text (ASCII) or always sent byte-for-byte "
    "(binary). Space separated.":
        "始终按文本（ASCII）或始终按字节（二进制）传输的扩展名，空格分隔。",
    "ASCII extensions": "ASCII 扩展名",
    "Binary extensions": "二进制扩展名",
    "Network": "网络",
    "Connection timeout": "连接超时",
    "Keep-alive interval": "心跳间隔",
    "off": "关闭",
    "Use passive mode (FTP/FTPS)": "使用被动模式（FTP/FTPS）",
    "Strictly verify SSH host keys (SFTP)": "严格校验 SSH 主机密钥（SFTP）",
    "Strict host-key verification refuses unknown servers. Leave it off for "
    "the first connection, then enable it once the key is known.":
        "严格校验会拒绝未知服务器。首次连接建议关闭，确认主机密钥后再开启。",
    "FTP encoding": "FTP 编码",
    "OK": "确定",
    "Folder name:": "文件夹名：",
    "Directory name:": "目录名：",
    "File name:": "文件名：",
    "New name:": "新名称：",
    "File name": "文件名",
    "unknown": "未知",
    "Name: %s": "名称：%s",
    "Path: %s": "路径：%s",
    "Type: %s": "类型：%s",
    "Size: %s": "大小：%s",
    "Modified: %s": "修改时间：%s",
    "Link target: %s": "链接目标：%s",
    "%s contains %d file(s), %s in total.": "%s 包含 %d 个文件，合计 %s。",
    "Set mode %s on %s": "已把 %s 的权限设为 %s",
    "%d ok / %d failed": "成功 %d / 失败 %d",
    "%d ok / %d failed / %d cancelled": "成功 %d / 失败 %d / 取消 %d",
    "and %d more": "以及另外 %d 项",
    "Transfers finished — %d failed": "传输结束 — %d 项失败",
    "All transfers completed (%d)": "全部传输完成（%d 项）",
    "All transfers completed": "全部传输完成",
    "Transfers finished — %d failed": "传输结束 — %d 项失败",
    "Reading %d missing file size(s)…": "正在读取 %d 个缺失的文件大小…",
    "Deleted %d local item(s)": "已删除 %d 个本地项目",
    "Deleted %d remote item(s)": "已删除 %d 个远程项目",
    "Retrying failed transfers": "正在重试失败的传输",
    "A cream-themed FTP / FTPS / SFTP client built with PyQt5, "
    "PyQtWebEngine and paramiko.":
        "使用 PyQt5、PyQtWebEngine 与 paramiko 构建的奶白色 FTP / FTPS / SFTP 客户端。",
    "Every colour is yours to change: open "
    "View — Preferences — Colours.":
        "所有颜色都可以自定义：打开 视图 — 偏好设置 — 颜色。",
    "Connect to a server": "连接到服务器",
    "Close the connection": "断开连接",
    "Refresh both panes": "刷新左右面板",
    "Show or hide hidden files": "显示或隐藏隐藏文件",
    "Upload the local selection": "上传本地选中的项目",
    "Download the remote selection": "下载远程选中的项目",
    "Pause or resume the transfer queue": "暂停或继续传输队列",
    "Open the preferences": "打开偏好设置",
    "Rename the selected item": "重命名选中项",
    "Create a directory": "新建目录",
    "Delete the selection": "删除选中项",
    "Show or hide hidden files": "显示或隐藏隐藏文件",
    "Show the transfer queue": "显示传输队列",
    "Show or hide hidden files": "显示或隐藏隐藏文件",
    "Swap the two panes": "交换左右面板",
    "Go to the parent directory": "上级目录",
    "Go back in the path history": "路径后退",
    "Quit": "退出",
    "Show Details…": "显示详细信息(&D)…",
    "Hide Details…": "隐藏详细信息(&D)…",
    "&Yes": "是(&Y)", "&No": "否(&N)",
    "Yes to &All": "全是(&A)", "N&o to All": "全否(&O)",
    "Discard": "放弃", "Reset": "重置", "Help": "帮助",
    "Abort": "中止", "Retry": "重试", "Ignore": "忽略",
    "Cancel": "取消",
    "Apply": "应用",
    "Delete": "删除",
    "Save": "保存",
    "All": "全部",

    # -- file type labels ---------------------------------------------------
    "%s file": "%s 文件",

    # -- log / misc ------------------------------------------------
    "Preferences saved": "偏好设置已保存",
    "Connection saved to config.ini as “%s”": "连接已保存到 config.ini，名称：“%s”",
    "Could not save the connection: %s": "无法保存连接：%s",
    "Do you want to delete the selected item(s)?":
        "确定要删除选中的项目吗？",
    # -- dialog titles ------------------------------------------------------
    "Connection failed": "连接失败",
    "Overwrite?": "是否覆盖？",
    "Create folder": "新建文件夹",
    "Create directory": "新建目录",
    "Create file": "新建文件",
    "Rename": "重命名",
    "Delete": "删除",
    "Folder size": "文件夹大小",
    "Edit": "编辑",
    "Save": "保存",
    "Save log": "保存日志",
    "Properties": "属性",
    "Keyboard shortcuts": "键盘快捷键",
    "Upload": "上传",
    "Download": "下载",
    "Site manager": "站点管理",
    "Connection": "连接",
    "Transfer failed": "传输失败",
    "%s — unexpected error": "%s — 意外错误",
    "Something went wrong:": "发生了错误：",
    "Could not connect to %s.": "无法连接到 %s。",
    "Not connected": "未连接",
    "Connect to a server before uploading.": "请先连接服务器再上传。",
    "Connect to a server before downloading.": "请先连接服务器再下载。",
    "Connect to a server first.": "请先连接服务器。",
    "Select something to upload first": "请先选择要上传的内容",
    "Select something to download first": "请先选择要下载的内容",
    "“%s” already exists on the server.": "服务器上已存在“%s”。",
    "Overwrite it?": "是否覆盖？",
    "“%s” already exists locally.": "本地已存在“%s”。",
    "Overwriting without asking for the rest of this batch":
        "本批次剩余文件将直接覆盖，不再询问",
    "Time": "时间",
    "About %s": "关于 %s",
    "Author: %s": "作者：%s",
    "Configuration files": "配置文件",
    "Open the configuration folder": "打开配置文件夹",
    "Edit the saved connections (config.ini)": "编辑已保存的连接（config.ini）",
    "Connections are stored in config.ini inside this folder. Passwords are "
    "kept in clear text, so treat the file like a password list.":
        "连接信息保存在此文件夹下的 config.ini 中。密码为明文存储，"
        "请把该文件当作密码清单妥善保管。",
    "Delete %d item(s) from this computer?": "要从本机删除 %d 项吗？",
    "Delete %d item(s) on the server?": "要在服务器上删除 %d 项吗？",
    "Octal mode for “%s”:": "“%s”的八进制权限：",
    "Enter an octal mode, for example 644 or 755.": "请输入八进制权限，例如 644 或 755。",
    "“%s” is %s.": "“%s”大小为 %s。",
    "Opening it in the editor may be slow.": "用编辑器打开可能较慢。",
    "Continue?": "是否继续？",
    "Reading file sizes…": "正在读取文件大小…",
    "Reading %d missing file size(s)…": "正在读取 %d 个缺失的文件大小…",
    "%d transfer(s) are still pending.": "还有 %d 个传输未完成。",
    "Quit anyway?": "仍要退出吗？",
    "(platform default)": "（跟随系统）",
    "Element": "项目",
    "Colour": "颜色",
    "Required — e.g. Production web server": "必填 — 例如 生产环境 Web 服务器",
    "Connection name:": "连接名：",
    "Key: %s": "私钥：%s",
    "Language": "语言",
    "Interface language": "界面语言",
    "Takes effect immediately, no restart needed.": "立即生效，无需重启。",
    "no shortcut": "无快捷键",
    "connected": "已连接",
    "Transfers tab": "传输",
    "Log": "日志",
    "%d queued / %d active / %d done / %d failed":
        "%d 排队 / %d 传输中 / %d 完成 / %d 失败",
    "Notice": "提示",
    "Warning": "警告",
    "Error": "错误",
    "Question": "询问",
}


def has_translation(text: str) -> bool:
    return text in ZH


def missing_keys(strings: List[str]) -> List[str]:
    """Keys with no Chinese entry (used by the tests)."""
    return [s for s in strings if s not in ZH]


# ---------------------------------------------------------------------------
# QMessageBox helper
# ---------------------------------------------------------------------------

#: caches the original static methods so they are wrapped only once
_WRAPPED = {"done": False, "original": {}}

#: standard button -> English source text.  PyQt5-Qt5 does not ship Qt's own
#: translations, so the labels are set from this table instead.
BUTTON_TEXTS = [
    ("Ok", "OK"), ("Cancel", "Cancel"), ("Yes", "&Yes"), ("No", "&No"),
    ("YesToAll", "Yes to &All"), ("NoToAll", "N&o to All"),
    ("Close", "Close"), ("Apply", "Apply"), ("Discard", "Discard"),
    ("Reset", "Reset"), ("Save", "Save"), ("Help", "Help"),
    ("Abort", "Abort"), ("Retry", "Retry"), ("Ignore", "Ignore"),
]

#: the same idea for QDialogButtonBox, using its own enum names
DIALOG_BUTTON_TEXTS = [
    ("Ok", "OK"), ("Cancel", "Cancel"), ("Apply", "Apply"),
    ("Close", "Close"), ("Save", "Save"), ("Discard", "Discard"),
    ("Reset", "Reset"), ("Help", "Help"), ("Yes", "&Yes"), ("No", "&No"),
    ("YesToAll", "Yes to &All"), ("NoToAll", "N&o to All"),
    ("Retry", "Retry"), ("Abort", "Abort"), ("Ignore", "Ignore"),
    ("Open", "Open"),
]


def localise_box(box: Any) -> None:
    """Translate a QMessageBox's standard buttons and its details toggle.

    Also handles a ``QDialogButtonBox``: Qt fills those with its own English
    strings, so without this the OK / Cancel / Apply buttons of the
    preferences and connect dialogs stay English while everything around them
    is translated.
    """
    try:
        from PyQt5.QtWidgets import QDialogButtonBox, QMessageBox
    except ImportError:      # pragma: no cover
        return
    try:
        if isinstance(box, QDialogButtonBox):
            for name, english in DIALOG_BUTTON_TEXTS:
                flag = getattr(QDialogButtonBox, name, None)
                if flag is None:
                    continue
                button = box.button(flag)
                if button is not None:
                    # always rewrite: T() returns the English text when English
                    # is active, which is what makes switching back work
                    button.setText(T(english))
            return
        for name, english in BUTTON_TEXTS:
            flag = getattr(QMessageBox, name, None)
            if flag is None:
                continue
            button = box.button(flag)
            if button is not None:
                button.setText(T(english))
        # Qt's own "Show Details…" toggle is not a standard button
        for button in box.buttons():
            text = button.text().replace("&", "").strip()
            if text.startswith("Show Details"):
                button.setText(T("Show Details…"))
            elif text.startswith("Hide Details"):
                button.setText(T("Hide Details…"))
    except (RuntimeError, TypeError):
        return


def install_message_box_translation() -> None:
    """Route the title of every ``QMessageBox`` through the translator.

    Wrapping the static helpers keeps ~40 call sites in the codebase free of
    translation noise, and any title without an entry simply stays English.
    """
    if _WRAPPED["done"]:
        return
    try:
        from PyQt5.QtWidgets import QMessageBox
    except ImportError:      # pragma: no cover - Qt is required anyway
        return

    for name in ("information", "warning", "critical", "question", "about"):
        method = getattr(QMessageBox, name, None)
        if method is None:
            continue
        _WRAPPED["original"][name] = method
        setattr(QMessageBox, name, _make_wrapper(name, method))
    _WRAPPED["done"] = True


def _make_wrapper(name: str, method: Any) -> Any:
    def wrapper(parent: Any = None, title: str = "", text: str = "",
                *args: Any, **kwargs: Any) -> Any:
        return method(parent, T(title), text, *args, **kwargs)

    wrapper.__name__ = name
    wrapper.__doc__ = getattr(method, "__doc__", None)
    return wrapper


def apply_locale() -> None:
    """Tell Qt which language to use for date formats and its own strings."""
    try:
        from PyQt5.QtCore import QLocale
    except ImportError:      # pragma: no cover
        return
    locale = QLocale(QLocale.Chinese, QLocale.China) if i18n.is_chinese \
        else QLocale(QLocale.English, QLocale.UnitedStates)
    QLocale.setDefault(locale)


__all__ = [
    "i18n", "T", "_", "set_language", "current_language", "is_chinese",
    "LANGUAGE_EN", "LANGUAGE_ZH", "DEFAULT_LANGUAGE", "LANGUAGE_NAMES", "ZH",
    "has_translation", "missing_keys", "install_message_box_translation",
    "apply_locale",
]
