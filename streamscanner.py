# -*- coding: utf-8 -*-
# StreamScanner — Copyright (c) 2026 thaarfknight-star. All rights reserved.
# Source-available, NOT open-source: viewing permitted; copying, modification,
# redistribution or reuse prohibited without written permission. See LICENSE.
"""
StreamScanner | اسکنر سرور استریم
==================================
برنامه‌ای برای پیدا کردن بهترین سرور جهت استریم روی Kick.

قابلیت‌ها:
  - تست موازی همه سرورها (پینگ + اتصال TCP به پورت RTMP) با اینترنت خود شما
  - تشخیص خودکار نام و منطقه سرور از روی لینک RTMP
  - رتبه‌بندی سرورها و پیشنهاد بهترین سرور برای استریم روی Kick
  - افزودن / ویرایش / حذف سرور
  - درون‌ریزی گروهی آدرس‌ها
  - تم تیره / روشن / سیستمی
  - بررسی خودکار آپدیت از گیت‌هاب و نصب نسخه جدید
  - ذخیره خودکار در فایل servers.json کنار برنامه

اجرا از سورس:
    pip install PySide6
    python streamscanner.py
"""

import json
import platform
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QProgressDialog, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
)

# ----------------------------------------------------------------------------
# ثابت‌ها
# ----------------------------------------------------------------------------

__version__ = "1.0.1"
GITHUB_OWNER = "thaarfknight-star"
GITHUB_REPO = "StreamScanner"
UPDATE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

APP_NAME = "StreamScanner"
APP_SUBTITLE = "بهترین سرور را برای استریم روی Kick پیدا کن"
DATA_FILE = Path(__file__).resolve().parent / "servers.json"
DEFAULT_RTMP_PORT = 1935

REGION_IRAN = "ایران"
REGION_UNKNOWN = "نامشخص"
REGIONS = ["ایران", "آلمان", "فرانسه", "هلند", "انگلیس", "ترکیه", "امارات", REGION_UNKNOWN]

# لیست سرورها خالی شروع می‌شود؛ کاربر از پنل مستراستریم وارد می‌کند.
DEFAULT_SERVERS = []


# ----------------------------------------------------------------------------
# مدل داده
# ----------------------------------------------------------------------------

@dataclass
class Server:
    name: str
    host: str = ""
    port: int = DEFAULT_RTMP_PORT
    region: str = REGION_UNKNOWN
    note: str = ""
    id: str = field(default_factory=lambda: uuid4short())


def uuid4short():
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


def server_rtmp_url(s):
    if isinstance(s, dict):
        host, port = s.get("host", ""), s.get("port", DEFAULT_RTMP_PORT)
    else:
        host, port = s.host, s.port
    if not host:
        return ""
    return f"rtmp://{host}:{port}/live"


# ----------------------------------------------------------------------------
# تشخیص خودکار نام و منطقه از روی هاست
# ----------------------------------------------------------------------------

def suggest_name(host: str) -> str:
    """نام پیشنهادی از روی هاست؛ مثلاً ir1.example.com -> IR1"""
    host = (host or "").strip().lower()
    if not host:
        return ""
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return "سرور " + host
    label = host.split(".")[0]
    label = re.sub(r"[-_]+", " ", label).strip()
    return label.upper() if label else host


_REGION_RULES = [
    (REGION_IRAN, ("ir",), ("iran", "tehran", "shiraz", "tabriz", "mashhad",
                            "isfahan", "karaj", "ahvaz", "qom")),
    ("آلمان", ("de",), ("germany", "berlin", "frankfurt", "munich", "nuremberg", "falkenstein")),
    ("فرانسه", ("fr",), ("france", "paris", "marseille", "roubaix", "gravelines")),
    ("هلند", ("nl",), ("netherlands", "amsterdam", "rotterdam")),
    ("انگلیس", ("uk",), ("england", "london", "manchester")),
    ("ترکیه", ("tr",), ("turkey", "istanbul", "ankara")),
    ("امارات", ("ae",), ("uae", "dubai", "emirates")),
]


def detect_region(host: str) -> str:
    """حدس منطقه از روی هاست (کد کشور، TLD یا نام شهر)."""
    h = (host or "").strip().lower()
    if not h:
        return REGION_UNKNOWN
    tokens = [t for t in re.split(r"[.\-_]", h) if t]
    tld = tokens[-1] if tokens else ""
    for region, tlds, words in _REGION_RULES:
        if tld in tlds:
            return region
        for tok in tokens:
            if tok in words:
                return region
            m = re.fullmatch(r"(ir|de|fr|nl|uk|tr|ae)(\d+)?", tok)
            if m:
                code = m.group(1)
                for r2, tlds2, _w2 in _REGION_RULES:
                    if code in tlds2:
                        return r2
    return REGION_UNKNOWN


def parse_rtmp(text):
    """برگرداندن (host, port) از یک RTMP URL یا host تنها."""
    text = (text or "").strip()
    if not text:
        return "", DEFAULT_RTMP_PORT
    if "://" not in text:
        text = "rtmp://" + text
    try:
        u = urlparse(text)
        host = u.hostname or ""
        port = u.port or DEFAULT_RTMP_PORT
        return host, port
    except Exception:
        return "", DEFAULT_RTMP_PORT


# ----------------------------------------------------------------------------
# تست شبکه — بدون باز شدن پنجره CMD، همه سرورها موازی
# ----------------------------------------------------------------------------

def _popen_kwargs():
    """روی ویندوز پنجره کنسول باز نشود."""
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def ping_host(host, count=2, timeout_ms=1500):
    """میانگین پینگ (ms) و درصد packet loss. بدون نمایش پنجره."""
    if not host:
        return None, 100.0
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=count * (timeout_ms / 1000) + 5,
                              **_popen_kwargs())
        out = proc.stdout or ""
        times = [float(x) for x in re.findall(r"time[=<](\d+(?:\.\d+)?)\s*ms", out)]
        loss_m = re.search(r"(\d+)%\s*(?:packet\s*)?loss", out, re.IGNORECASE)
        if not loss_m:
            loss_m = re.search(r"Lost\s*=\s*\d+\s*\((\d+)%", out)
        loss = float(loss_m.group(1)) if loss_m else (0.0 if times else 100.0)
        avg = sum(times) / len(times) if times else None
        return avg, loss
    except Exception:
        return None, 100.0


def tcp_probe(host, port, timeout=3.0):
    """زمان برقراری اتصال TCP به پورت RTMP (ms) یا None."""
    if not host:
        return None
    try:
        t0 = time.perf_counter()
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
        return (time.perf_counter() - t0) * 1000.0
    except Exception:
        return None


def probe_server(server):
    """تست کامل یک سرور؛ نتیجه دیکشنری."""
    s = dict(server)
    ping_ms, loss = ping_host(s.get("host", ""))
    tcp_ms = tcp_probe(s.get("host", ""), s.get("port", DEFAULT_RTMP_PORT))
    ok = tcp_ms is not None
    if not ok:
        score = 1_000_000.0
    else:
        base = tcp_ms if tcp_ms is not None else 9999.0
        score = base + (ping_ms or 500.0) * 0.3 + loss * 20.0
    return {
        "id": s.get("id"), "name": s.get("name"), "region": s.get("region"),
        "host": s.get("host"), "port": s.get("port"),
        "ping_ms": ping_ms, "loss": loss, "tcp_ms": tcp_ms,
        "ok": ok, "score": score,
    }


class ScanThread(QThread):
    """اسکن موازی همه سرورها؛ نتیجه هر سرور جدا emit می‌شود."""
    one_done = Signal(int, dict)   # index, result
    all_done = Signal(list)

    def __init__(self, servers, parent=None):
        super().__init__(parent)
        self.servers = servers

    def run(self):
        results = [None] * len(self.servers)
        if not self.servers:
            self.all_done.emit([])
            return
        with ThreadPoolExecutor(max_workers=min(32, len(self.servers))) as ex:
            futs = {ex.submit(probe_server, s): i for i, s in enumerate(self.servers)}
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    res = fut.result()
                except Exception:
                    res = {"id": self.servers[i].get("id"), "ok": False,
                           "ping_ms": None, "loss": 100.0, "tcp_ms": None,
                           "score": 1_000_000.0, "name": self.servers[i].get("name"),
                           "region": self.servers[i].get("region"),
                           "host": self.servers[i].get("host"),
                           "port": self.servers[i].get("port")}
                results[i] = res
                self.one_done.emit(i, res)
        self.all_done.emit(results)


# ----------------------------------------------------------------------------
# تم‌ها
# ----------------------------------------------------------------------------

DARK_QSS = """
QMainWindow, QWidget { background-color: #0f1419; color: #e8f5e9; }
QLabel#title { font-size: 22px; font-weight: bold; color: #00e676; }
QLabel#subtitle { font-size: 12px; color: #9e9e9e; }
QLabel#banner { font-size: 14px; font-weight: bold; color: #0f1419;
    background-color: #00e676; border-radius: 8px; padding: 8px; }
QPushButton { background-color: #1b5e20; color: #ffffff; border: none;
    border-radius: 8px; padding: 9px 14px; font-size: 13px; font-weight: bold; }
QPushButton:hover { background-color: #2e7d32; }
QPushButton:disabled { background-color: #37474f; color: #90a4ae; }
QPushButton#danger { background-color: #b71c1c; }
QPushButton#danger:hover { background-color: #d32f2f; }
QPushButton#ghost { background-color: #263238; }
QPushButton#ghost:hover { background-color: #37474f; }
QLineEdit, QTextEdit, QComboBox { background-color: #1c262c; color: #e8f5e9;
    border: 1px solid #37474f; border-radius: 6px; padding: 7px; font-size: 13px; }
QTableWidget { background-color: #131a20; gridline-color: #263238;
    border: 1px solid #263238; border-radius: 8px; font-size: 13px; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background-color: #1b5e20; color: white;
    padding: 8px; font-weight: bold; border: none; }
QProgressBar { border: 1px solid #37474f; border-radius: 6px; background: #1c262c;
    text-align: center; color: #e8f5e9; height: 18px; }
QProgressBar::chunk { background-color: #00e676; border-radius: 5px; }
QDialog { background-color: #0f1419; }
QCheckBox { font-size: 13px; }
"""

LIGHT_QSS = """
QMainWindow, QWidget { background-color: #f4f6f4; color: #1b2b1e; }
QLabel#title { font-size: 22px; font-weight: bold; color: #1b7a2e; }
QLabel#subtitle { font-size: 12px; color: #6b7a6e; }
QLabel#banner { font-size: 14px; font-weight: bold; color: #ffffff;
    background-color: #1b7a2e; border-radius: 8px; padding: 8px; }
QPushButton { background-color: #1b7a2e; color: #ffffff; border: none;
    border-radius: 8px; padding: 9px 14px; font-size: 13px; font-weight: bold; }
QPushButton:hover { background-color: #239a3a; }
QPushButton:disabled { background-color: #b9c6bb; color: #6b7a6e; }
QPushButton#danger { background-color: #c62828; }
QPushButton#danger:hover { background-color: #e53935; }
QPushButton#ghost { background-color: #dde5de; color: #1b2b1e; }
QPushButton#ghost:hover { background-color: #cdd8ce; }
QLineEdit, QTextEdit, QComboBox { background-color: #ffffff; color: #1b2b1e;
    border: 1px solid #b9c6bb; border-radius: 6px; padding: 7px; font-size: 13px; }
QTableWidget { background-color: #ffffff; gridline-color: #dde5de;
    border: 1px solid #cdd8ce; border-radius: 8px; font-size: 13px; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background-color: #1b7a2e; color: white;
    padding: 8px; font-weight: bold; border: none; }
QProgressBar { border: 1px solid #b9c6bb; border-radius: 6px; background: #e7ede7;
    text-align: center; color: #1b2b1e; height: 18px; }
QProgressBar::chunk { background-color: #1b7a2e; border-radius: 5px; }
QDialog { background-color: #f4f6f4; }
QCheckBox { font-size: 13px; }
"""

THEMES = {"dark": "تیره", "light": "روشن", "system": "سیستمی"}


def resolve_theme(theme):
    if theme == "system":
        try:
            from PySide6.QtCore import QOperatingSystemVersion  # noqa
            hints = QApplication.instance().styleHints()
            scheme = hints.colorScheme()
            from PySide6.QtCore import Qt as _Qt
            return "dark" if scheme == _Qt.ColorScheme.Dark else "light"
        except Exception:
            return "light"
    return theme if theme in ("dark", "light") else "dark"


def apply_theme(theme):
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(DARK_QSS if resolve_theme(theme) == "dark" else LIGHT_QSS)


# ----------------------------------------------------------------------------
# بررسی آپدیت از گیت‌هاب
# ----------------------------------------------------------------------------

def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def fetch_latest_release():
    req = urllib.request.Request(
        UPDATE_API,
        headers={"User-Agent": "StreamScanner",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def find_setup_asset(release):
    for a in release.get("assets", []):
        name = (a.get("name") or "").lower()
        if name.endswith("setup.exe"):
            return a
    return None


# ----------------------------------------------------------------------------
# دیالوگ افزودن / ویرایش سرور
# ----------------------------------------------------------------------------

class ServerDialog(QDialog):
    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.setWindowTitle("افزودن سرور" if server is None else "ویرایش سرور")
        self.setMinimumWidth(430)
        self._name_touched = server is not None

        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.name_edit = QLineEdit(server.name if server else "")
        self.name_edit.setPlaceholderText("مثلاً IR1")
        self.name_edit.textEdited.connect(lambda _t: setattr(self, "_name_touched", True))

        self.url_edit = QLineEdit()
        if server:
            self.url_edit.setText(server_rtmp_url(server))
        self.url_edit.setPlaceholderText("rtmp://host:1935/live")
        self.url_edit.setLayoutDirection(Qt.LeftToRight)
        self.url_edit.textChanged.connect(self.on_url_changed)

        self.region_combo = QComboBox()
        self.region_combo.addItems(REGIONS)
        if server:
            idx = self.region_combo.findText(server.region)
            self.region_combo.setCurrentIndex(idx if idx >= 0 else REGIONS.index(REGION_UNKNOWN))

        self.note_edit = QLineEdit(server.note if server else "")
        self.note_edit.setPlaceholderText("توضیح اختیاری")

        hint = QLabel("نام و منطقه به‌صورت خودکار از روی لینک حدس زده می‌شوند؛\nمی‌توانید دستی هم تغییرشان دهید.")
        hint.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        hint.setWordWrap(True)

        layout.addRow("نام سرور:", self.name_edit)
        layout.addRow("آدرس RTMP:", self.url_edit)
        layout.addRow("منطقه:", self.region_combo)
        layout.addRow("توضیح:", self.note_edit)
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تأیید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def on_url_changed(self, text):
        host, _port = parse_rtmp(text)
        if not host:
            return
        if not self._name_touched:
            self.name_edit.setText(suggest_name(host))
        region = detect_region(host)
        idx = self.region_combo.findText(region)
        if idx >= 0:
            self.region_combo.setCurrentIndex(idx)

    def get_server(self, existing=None):
        host, port = parse_rtmp(self.url_edit.text())
        name = self.name_edit.text().strip() or suggest_name(host) or "سرور"
        region = self.region_combo.currentText()
        note = self.note_edit.text().strip()
        if existing:
            existing.name, existing.host, existing.port = name, host, port
            existing.region, existing.note = region, note
            return existing
        return Server(name=name, host=host, port=port, region=region, note=note)


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("درون‌ریزی گروهی")
        self.setMinimumSize(480, 320)
        layout = QVBoxLayout(self)
        hint = QLabel("هر خط یک سرور، با قالب:\nنام سرور | rtmp://host:1935/live")
        hint.setStyleSheet("color: #9e9e9e; font-size: 12px;")
        hint.setWordWrap(True)
        self.text = QTextEdit()
        self.text.setPlaceholderText("IR1 | rtmp://ir1.example.com:1935/live\nDE1 | rtmp://de1.example.com:1935/live")
        self.text.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(hint)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("وارد کردن")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_servers(self):
        out = []
        for line in self.text.toPlainText().splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            name, url = [p.strip() for p in line.split("|", 1)]
            host, port = parse_rtmp(url)
            if not host:
                continue
            region = detect_region(host)
            out.append(Server(name=name or suggest_name(host), host=host,
                              port=port, region=region))
        return out


# ----------------------------------------------------------------------------
# دیالوگ تنظیمات
# ----------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, parent, theme, auto_check):
        super().__init__(parent)
        self.setWindowTitle("تنظیمات")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("تیره", "dark")
        self.theme_combo.addItem("روشن", "light")
        self.theme_combo.addItem("سیستمی", "system")
        idx = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("تم برنامه:", self.theme_combo)

        self.auto_check_box = QCheckBox("بررسی خودکار آپدیت هنگام اجرای برنامه")
        self.auto_check_box.setChecked(auto_check)
        form.addRow(self.auto_check_box)
        layout.addLayout(form)

        upd_box = QVBoxLayout()
        ver_label = QLabel(f"نسخه فعلی برنامه: <b>{__version__}</b>")
        self.upd_status = QLabel("")
        self.upd_status.setWordWrap(True)
        self.upd_status.setStyleSheet("font-size: 12px; color: #9e9e9e;")
        check_btn = QPushButton("بررسی آپدیت")
        check_btn.setObjectName("ghost")
        check_btn.clicked.connect(self.on_check_update)
        upd_box.addWidget(ver_label)
        upd_box.addWidget(check_btn)
        upd_box.addWidget(self.upd_status)
        layout.addLayout(upd_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("ذخیره")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def on_check_update(self):
        self.upd_status.setText("در حال بررسی…")
        parent = self.parent()
        if parent and hasattr(parent, "check_for_updates"):
            parent.check_for_updates(manual=True, status_label=self.upd_status)

    def values(self):
        return self.theme_combo.currentData(), self.auto_check_box.isChecked()


# ----------------------------------------------------------------------------
# دیالوگ آپدیت جدید
# ----------------------------------------------------------------------------

class UpdateDialog(QDialog):
    def __init__(self, parent, release):
        super().__init__(parent)
        tag = release.get("tag_name", "")
        self.setWindowTitle("نسخه جدید موجود است")
        self.setMinimumSize(460, 340)
        layout = QVBoxLayout(self)
        title = QLabel(f"نسخه <b>{tag}</b> منتشر شده است (نسخه شما: {__version__})")
        title.setWordWrap(True)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(release.get("body") or "—")
        layout.addWidget(title)
        layout.addWidget(QLabel("تغییرات:"))
        layout.addWidget(body)
        row = QHBoxLayout()
        dl_btn = QPushButton("دانلود و نصب")
        later_btn = QPushButton("بعداً")
        later_btn.setObjectName("ghost")
        dl_btn.clicked.connect(self.accept)
        later_btn.clicked.connect(self.reject)
        row.addWidget(dl_btn)
        row.addWidget(later_btn)
        layout.addLayout(row)
        self.release = release


# ----------------------------------------------------------------------------
# پنجره اصلی
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    update_found = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(880, 620)
        self.servers = []
        self.theme = "dark"
        self.auto_check_update = True
        self.scan_thread = None
        self.last_results = {}
        self.update_found.connect(self.on_update_found)
        self.load_settings()
        apply_theme(self.theme)
        self.build_ui()
        self.refresh_table()
        if self.auto_check_update:
            QTimer.singleShot(2500, lambda: self.check_for_updates(manual=False))

    # -- ذخیره‌سازی ---------------------------------------------------------
    def load_settings(self):
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            items = data.get("servers", []) if isinstance(data, dict) else data
            self.servers = [Server(**{k: v for k, v in s.items()
                                      if k in Server.__dataclass_fields__})
                            for s in items]
            if isinstance(data, dict):
                self.theme = data.get("theme", "dark")
                self.auto_check_update = data.get("auto_check_update", True)
        except Exception:
            self.servers = [Server(**s) for s in DEFAULT_SERVERS]

    def save_settings(self):
        try:
            DATA_FILE.write_text(json.dumps(
                {"servers": [asdict(s) for s in self.servers],
                 "theme": self.theme,
                 "auto_check_update": self.auto_check_update},
                ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # -- رابط ---------------------------------------------------------------
    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel(APP_SUBTITLE)
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("⚡ اسکن همه سرورها")
        self.scan_btn.clicked.connect(self.run_scan)
        add_btn = QPushButton("＋ افزودن")
        add_btn.setObjectName("ghost")
        add_btn.clicked.connect(self.add_server)
        edit_btn = QPushButton("✎ ویرایش")
        edit_btn.setObjectName("ghost")
        edit_btn.clicked.connect(self.edit_server)
        del_btn = QPushButton("🗑 حذف")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self.delete_server)
        import_btn = QPushButton("📥 درون‌ریزی گروهی")
        import_btn.setObjectName("ghost")
        import_btn.clicked.connect(self.import_servers)
        settings_btn = QPushButton("⚙ تنظیمات")
        settings_btn.setObjectName("ghost")
        settings_btn.clicked.connect(self.open_settings)
        for b in (self.scan_btn, add_btn, edit_btn, del_btn, import_btn, settings_btn):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["سرور", "منطقه", "پینگ", "Packet Loss", "اتصال TCP", "وضعیت"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setLayoutDirection(Qt.RightToLeft)
        layout.addWidget(self.table)

        bottom = QHBoxLayout()
        self.copy_btn = QPushButton("📋 کپی آدرس RTMP سرور پیشنهادی")
        self.copy_btn.clicked.connect(self.copy_best)
        self.copy_btn.setEnabled(False)
        bottom.addWidget(self.copy_btn)
        layout.addLayout(bottom)

    # -- جدول ----------------------------------------------------------------
    def refresh_table(self):
        self.table.setRowCount(len(self.servers))
        for i, s in enumerate(self.servers):
            self.table.setItem(i, 0, QTableWidgetItem(s.name))
            self.table.setItem(i, 1, QTableWidgetItem(s.region))
            r = self.last_results.get(s.id)
            if r:
                self.fill_result_row(i, r)
            else:
                for c in range(2, 6):
                    self.table.setItem(i, c, QTableWidgetItem("—"))

    def fill_result_row(self, i, r):
        ping_txt = f"{r['ping_ms']:.0f} ms" if r["ping_ms"] is not None else "ناموفق"
        tcp_txt = f"{r['tcp_ms']:.0f} ms" if r["tcp_ms"] is not None else "قطع"
        ok_txt = "✅ وصل" if r["ok"] else "❌ قطع"
        self.table.setItem(i, 2, QTableWidgetItem(ping_txt))
        self.table.setItem(i, 3, QTableWidgetItem(f"{r['loss']:.0f}%"))
        self.table.setItem(i, 4, QTableWidgetItem(tcp_txt))
        item = QTableWidgetItem(ok_txt)
        item.setForeground(QColor("#00e676") if r["ok"] else QColor("#ff5252"))
        self.table.setItem(i, 5, item)

    # -- اسکن -----------------------------------------------------------------
    def run_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        if not self.servers:
            QMessageBox.information(self, "اسکن", "اول چند سرور اضافه کنید.")
            return
        self.scan_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.banner.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.servers))
        self.progress.setValue(0)
        self._done_count = 0
        snapshot = [asdict(s) for s in self.servers]
        self.scan_thread = ScanThread(snapshot, self)
        self.scan_thread.one_done.connect(self.on_one_done)
        self.scan_thread.all_done.connect(self.on_all_done)
        self.scan_thread.start()

    @Slot(int, dict)
    def on_one_done(self, index, result):
        srv = next((s for s in self.servers if s.id == result.get("id")), None)
        if srv is None or index >= len(self.servers):
            return
        self.last_results[srv.id] = result
        self.table.setItem(index, 0, QTableWidgetItem(srv.name))
        self.table.setItem(index, 1, QTableWidgetItem(srv.region))
        self.fill_result_row(index, result)
        self._done_count += 1
        self.progress.setValue(self._done_count)

    @Slot(list)
    def on_all_done(self, results):
        self.scan_thread = None
        self.scan_btn.setEnabled(True)
        self.progress.setVisible(False)
        ok_results = [r for r in results if r.get("ok")]
        if not ok_results:
            QMessageBox.warning(self, "اسکن",
                                "هیچ سروری وصل نشد. اینترنت یا آدرس‌ها را بررسی کنید.")
            return
        best = min(ok_results, key=lambda r: r["score"])
        srv = next((s for s in self.servers if s.id == best["id"]), None)
        name = srv.name if srv else best["name"]
        region = srv.region if srv else best.get("region", "")
        self.banner.setText(
            f"🏆 بهترین سرور: {name} ({region}) — "
            f"پینگ {best['ping_ms']:.0f}ms، اتصال {best['tcp_ms']:.0f}ms")
        self.banner.setVisible(True)
        self.copy_btn.setEnabled(True)
        self._best = best

    def copy_best(self):
        best = getattr(self, "_best", None)
        if not best:
            return
        url = f"rtmp://{best['host']}:{best['port']}/live"
        QApplication.clipboard().setText(url)
        QMessageBox.information(self, "کپی شد",
                                f"آدرس RTMP کپی شد:\n{url}\n\n"
                                "در Meld/OBS وارد کنید.")

    # -- مدیریت سرورها ----------------------------------------------------------
    def selected_server(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "انتخاب", "اول یک سرور را انتخاب کنید.")
            return None
        return self.servers[rows[0].row()]

    def add_server(self):
        dlg = ServerDialog(self)
        if dlg.exec():
            self.servers.append(dlg.get_server())
            self.save_settings()
            self.refresh_table()

    def edit_server(self):
        srv = self.selected_server()
        if not srv:
            return
        dlg = ServerDialog(self, srv)
        if dlg.exec():
            dlg.get_server(srv)
            self.save_settings()
            self.refresh_table()

    def delete_server(self):
        srv = self.selected_server()
        if not srv:
            return
        if QMessageBox.question(self, "حذف", f"«{srv.name}» حذف شود؟") \
                == QMessageBox.Yes:
            self.servers.remove(srv)
            self.last_results.pop(srv.id, None)
            self.save_settings()
            self.refresh_table()

    def import_servers(self):
        dlg = ImportDialog(self)
        if dlg.exec():
            new = dlg.get_servers()
            if new:
                self.servers.extend(new)
                self.save_settings()
                self.refresh_table()
                QMessageBox.information(self, "درون‌ریزی", f"{len(new)} سرور اضافه شد.")
            else:
                QMessageBox.information(self, "درون‌ریزی", "سرور معتبری پیدا نشد.")

    # -- تنظیمات -----------------------------------------------------------------
    def open_settings(self):
        dlg = SettingsDialog(self, self.theme, self.auto_check_update)
        if dlg.exec():
            theme, auto = dlg.values()
            self.theme = theme
            self.auto_check_update = auto
            apply_theme(theme)
            self.save_settings()

    # -- آپدیت -------------------------------------------------------------------
    def check_for_updates(self, manual=False, status_label=None):
        def worker():
            try:
                rel = fetch_latest_release()
                newer = _ver_tuple(rel.get("tag_name", "0")) > _ver_tuple(__version__)
            except Exception as e:
                if manual:
                    msg = f"خطا در بررسی آپدیت: {e}"
                    if status_label:
                        QTimer.singleShot(0, lambda: status_label.setText(msg))
                    else:
                        QTimer.singleShot(0, lambda: QMessageBox.warning(
                            self, "آپدیت", msg))
                return
            if newer:
                QTimer.singleShot(0, lambda: self.update_found.emit(rel))
                if manual and status_label:
                    tag = rel.get("tag_name", "")
                    QTimer.singleShot(0, lambda: status_label.setText(
                        f"نسخه جدید {tag} موجود است."))
            elif manual:
                msg = "شما از آخرین نسخه استفاده می‌کنید. ✅"
                if status_label:
                    QTimer.singleShot(0, lambda: status_label.setText(msg))
                else:
                    QTimer.singleShot(0, lambda: QMessageBox.information(
                        self, "آپدیت", msg))
        threading.Thread(target=worker, daemon=True).start()

    @Slot(dict)
    def on_update_found(self, release):
        tag = release.get("tag_name", "")
        dlg = UpdateDialog(self, release)
        if dlg.exec():
            asset = find_setup_asset(release)
            if not asset:
                QMessageBox.warning(self, "آپدیت",
                                    "فایل نصب در این نسخه پیدا نشد.")
                return
            self.download_and_install(asset, tag)

    def download_and_install(self, asset, tag):
        url = asset.get("browser_download_url", "")
        name = asset.get("name", "StreamScanner-Setup.exe")
        dest = str(Path(tempfile.gettempdir()) / name)
        prog = QProgressDialog("در حال دانلود نسخه جدید…", "انصراف", 0, 0, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.show()

        def worker():
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "StreamScanner"})
                with urllib.request.urlopen(req, timeout=60) as r, \
                        open(dest, "wb") as f:
                    while True:
                        chunk = r.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)
            except Exception as e:
                QTimer.singleShot(0, lambda: (prog.close(), QMessageBox.warning(
                    self, "آپدیت", f"دانلود ناموفق بود:\n{e}")))
                return
            def done():
                prog.close()
                if QMessageBox.question(
                        self, "آپدیت",
                        f"نسخه {tag} دانلود شد. نصب شود؟\n(برنامه بسته می‌شود)") \
                        == QMessageBox.Yes:
                    try:
                        if sys.platform == "win32":
                            import os as _os
                            _os.startfile(dest)  # noqa
                        else:
                            QMessageBox.information(
                                self, "آپدیت", f"فایل نصب:\n{dest}")
                    finally:
                        QApplication.quit()
            QTimer.singleShot(0, done)
        threading.Thread(target=worker, daemon=True).start()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("StreamScanner")
    font = QFont("Vazirmatn", 10)
    if "Vazirmatn" not in QFont().families():
        font = QFont()
        font.setPointSize(10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
