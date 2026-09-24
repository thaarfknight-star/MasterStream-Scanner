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
  - تم تیره / روشن / سیستمی + ۶ تم جدید (اعمال لحظه‌ای)
  - دوزبانه کامل فارسی (راست‌به‌چپ) / انگلیسی
  - بررسی خودکار آپدیت از گیت‌هاب؛ انتخاب بین فایل آپدیت (قابل‌حمل) و فایل نصبی
  - ذخیره خودکار در فایل servers.json کنار برنامه

اجرا از سورس:
    pip install PySide6
    python streamscanner.py
"""

import base64
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
from string import Template
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QProgressDialog, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView, QAbstractItemView,
)

# ----------------------------------------------------------------------------
# ثابت‌ها
# ----------------------------------------------------------------------------

__version__ = "1.0.2"
GITHUB_OWNER = "thaarfknight-star"
GITHUB_REPO = "StreamScanner"
UPDATE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

APP_NAME = "StreamScanner"
DATA_FILE = Path(__file__).resolve().parent / "servers.json"
DEFAULT_RTMP_PORT = 1935

REGION_IRAN = "ir"
REGION_UNKNOWN = "unknown"
REGIONS = ["ir", "de", "fr", "nl", "uk", "tr", "ae", REGION_UNKNOWN]
# نگاشت نام‌های فارسی قدیم (servers.json نسخه‌های قبل) به کلید جدید
_REGION_FA2KEY = {"ایران": "ir", "آلمان": "de", "فرانسه": "fr", "هلند": "nl",
                  "انگلیس": "uk", "ترکیه": "tr", "امارات": "ae", "نامشخص": "unknown"}

# لیست سرورها خالی شروع می‌شود؛ کاربر از پنل مستراستریم وارد می‌کند.
DEFAULT_SERVERS = []


# ----------------------------------------------------------------------------
# دوزبانگی فارسی / انگلیسی
# ----------------------------------------------------------------------------

STRINGS = {
    "subtitle": ("بهترین سرور را برای استریم روی Kick پیدا کن",
                 "Find the best server for streaming on Kick"),
    "settings": ("تنظیمات", "Settings"),
    "theme_label": ("تم برنامه:", "App theme:"),
    "theme_dark": ("تیره", "Dark"),
    "theme_light": ("روشن", "Light"),
    "theme_system": ("سیستمی", "System"),
    "theme_midnight": ("نیمه‌شب", "Midnight"),
    "theme_emerald": ("زمردی", "Emerald"),
    "theme_sunset": ("غروب", "Sunset"),
    "theme_amethyst": ("یاسی", "Lilac"),
    "theme_ocean": ("اقیانوسی", "Ocean"),
    "theme_rose": ("رز", "Rose"),
    "lang_label": ("زبان:", "Language:"),
    "autocheck": ("بررسی خودکار آپدیت هنگام اجرای برنامه",
                  "Check for updates automatically on startup"),
    "current_version": ("نسخه فعلی برنامه:", "Current version:"),
    "version": ("نسخه", "Version"),
    "downloaded": ("دانلود شد.", "downloaded."),
    "check_update": ("بررسی آپدیت", "Check for updates"),
    "checking": ("در حال بررسی…", "Checking…"),
    "save": ("ذخیره", "Save"),
    "cancel": ("انصراف", "Cancel"),
    "ok": ("تأیید", "OK"),
    "do_import": ("وارد کردن", "Import"),
    "later": ("بعداً", "Later"),
    "new_version": ("نسخه جدید", "New version"),
    "new_version_title": ("نسخه جدید موجود است", "New version available"),
    "version_released": ("منتشر شده است", "has been released"),
    "your_version": ("نسخه شما:", "Your version:"),
    "changes": ("تغییرات:", "Changes:"),
    "dl_update_file": ("📥 دانلود فایل آپدیت", "📥 Download update file"),
    "dl_installer": ("📥 دانلود فایل نصبی", "📥 Download installer"),
    "add_server": ("افزودن سرور", "Add server"),
    "edit_server": ("ویرایش سرور", "Edit server"),
    "server_name": ("نام سرور:", "Server name:"),
    "rtmp_addr": ("آدرس RTMP:", "RTMP address:"),
    "region": ("منطقه:", "Region:"),
    "note": ("توضیح:", "Note:"),
    "optional_note": ("توضیح اختیاری", "Optional note"),
    "auto_hint": ("نام و منطقه به‌صورت خودکار از روی لینک حدس زده می‌شوند؛\nمی‌توانید دستی هم تغییرشان دهید.",
                  "Name and region are auto-detected from the link;\nyou can also edit them manually."),
    "ex_name": ("مثلاً IR1", "e.g. IR1"),
    "import_title": ("درون‌ریزی گروهی", "Bulk import"),
    "import_hint": ("هر خط یک سرور، با قالب:\nنام سرور | rtmp://host:1935/live",
                    "One server per line, format:\nname | rtmp://host:1935/live"),
    "scan_all": ("⚡ اسکن همه سرورها", "⚡ Scan all servers"),
    "add": ("＋ افزودن", "＋ Add"),
    "edit": ("✎ ویرایش", "✎ Edit"),
    "delete": ("🗑 حذف", "🗑 Delete"),
    "bulk_import": ("📥 درون‌ریزی گروهی", "📥 Bulk import"),
    "col_server": ("سرور", "Server"),
    "col_region": ("منطقه", "Region"),
    "col_ping": ("پینگ", "Ping"),
    "col_tcp": ("اتصال TCP", "TCP connect"),
    "col_status": ("وضعیت", "Status"),
    "copy_best": ("📋 کپی آدرس RTMP سرور پیشنهادی",
                  "📋 Copy recommended server's RTMP address"),
    "best_server_lbl": ("بهترین سرور", "Best server"),
    "add_first": ("اول چند سرور اضافه کنید.", "Add some servers first."),
    "scan": ("اسکن", "Scan"),
    "no_server": ("هیچ سروری وصل نشد. اینترنت یا آدرس‌ها را بررسی کنید.",
                  "No server is reachable. Check your internet connection or addresses."),
    "copied": ("کپی شد", "Copied"),
    "rtmp_copied": ("آدرس RTMP کپی شد:", "RTMP address copied:"),
    "copied_msg": ("در Meld/OBS وارد کنید.", "Paste it into Meld/OBS."),
    "select_first": ("اول یک سرور را انتخاب کنید.", "Please select a server first."),
    "select": ("انتخاب", "Selection"),
    "delete_title": ("حذف", "Delete"),
    "delete_q": ("حذف شود؟", "Delete?"),
    "import_n": ("سرور اضافه شد.", "servers added."),
    "import_none": ("سرور معتبری پیدا نشد.", "No valid servers found."),
    "import": ("درون‌ریزی", "Import"),
    "failed": ("ناموفق", "Failed"),
    "down": ("قطع", "Down"),
    "up": ("✅ وصل", "✅ Up"),
    "down_emoji": ("❌ قطع", "❌ Down"),
    "update": ("آپدیت", "Update"),
    "update_err": ("خطا در بررسی آپدیت:", "Update check failed:"),
    "update_avail": ("موجود است.", "is available."),
    "update_latest": ("شما از آخرین نسخه استفاده می‌کنید. ✅",
                      "You are on the latest version. ✅"),
    "file_not_found": ("فایل موردنظر در این نسخه پیدا نشد.",
                       "The requested file was not found in this release."),
    "downloading": ("در حال دانلود نسخه جدید…", "Downloading new version…"),
    "download_failed": ("دانلود ناموفق بود:", "Download failed:"),
    "install_q": ("نصب شود؟\n(برنامه بسته می‌شود)", "Install now?\n(The app will close)"),
    "installer_file": ("فایل نصب:", "Installer file:"),
    "portable_saved": ("فایل آپدیت ذخیره شد در:", "Update file saved to:"),
    "dblclick_copied": ("آدرس RTMP سرور کپی شد", "Server RTMP address copied"),
    "lang_restart": ("برای اعمال زبان جدید، برنامه را ببندید و دوباره باز کنید.",
                     "Please restart the app to apply the new language."),
    "server_word": ("سرور", "Server"),
    "region_ir": ("ایران", "Iran"),
    "region_de": ("آلمان", "Germany"),
    "region_fr": ("فرانسه", "France"),
    "region_nl": ("هلند", "Netherlands"),
    "region_uk": ("انگلیس", "UK"),
    "region_tr": ("ترکیه", "Turkey"),
    "region_ae": ("امارات", "UAE"),
    "region_unknown": ("نامشخص", "Unknown"),
}

LANG = "fa"


def T(key):
    fa, en = STRINGS.get(key, (key, key))
    return en if LANG == "en" else fa


def region_name(key):
    return T("region_" + str(key))


# ----------------------------------------------------------------------------
# آیکون برنامه (PNG داخل کد، برای آیکون پنجره و تسک‌بار)
# ----------------------------------------------------------------------------

APP_ICON_B64 = "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"


def app_icon():
    pm = QPixmap()
    pm.loadFromData(base64.b64decode(APP_ICON_B64))
    return QIcon(pm)


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
        return T("server_word") + " " + host
    label = host.split(".")[0]
    label = re.sub(r"[-_]+", " ", label).strip()
    return label.upper() if label else host


_REGION_RULES = [
    ("ir", ("ir",), ("iran", "tehran", "shiraz", "tabriz", "mashhad",
                      "isfahan", "karaj", "ahvaz", "qom", "ika", "thr")),
    ("de", ("de",), ("germany", "berlin", "frankfurt", "munich", "nuremberg",
                      "falkenstein", "fra")),
    ("fr", ("fr",), ("france", "paris", "marseille", "roubaix", "gravelines",
                      "par", "cdg")),
    ("nl", ("nl",), ("netherlands", "amsterdam", "rotterdam", "ams")),
    ("uk", ("uk",), ("england", "london", "manchester", "lhr", "lon")),
    ("tr", ("tr",), ("turkey", "istanbul", "ankara", "ist")),
    ("ae", ("ae",), ("uae", "dubai", "emirates", "dxb")),
]


def detect_region(host: str) -> str:
    """حدس منطقه از روی هاست (کد کشور، TLD، نام شهر یا کد فرودگاهی)."""
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
            if m and m.group(1) in tlds:
                return region
            for w in words:
                if len(w) >= 3 and re.fullmatch(w + r"\d*", tok):
                    return region
        for w in words:
            if len(w) >= 3 and w in h:
                return region
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
# تم‌ها — پالت رنگی + قالب QSS
# ----------------------------------------------------------------------------

QSS_TEMPLATE = Template("""
QMainWindow, QWidget { background-color: $bg; color: $text; }
QLabel#title { font-size: 22px; font-weight: bold; color: $accent; }
QLabel#subtitle { font-size: 12px; color: $subtext; }
QLabel#banner { font-size: 14px; font-weight: bold; color: $on_accent;
    background-color: $accent; border-radius: 8px; padding: 8px; }
QPushButton { background-color: $accent_deep; color: $btn_text; border: none;
    border-radius: 8px; padding: 9px 14px; font-size: 13px; font-weight: bold; }
QPushButton:hover { background-color: $accent_hover; }
QPushButton:disabled { background-color: $disabled_bg; color: $disabled_text; }
QPushButton#danger { background-color: $danger; color: #ffffff; }
QPushButton#danger:hover { background-color: $danger_hover; }
QPushButton#ghost { background-color: $ghost_bg; color: $ghost_text; }
QPushButton#ghost:hover { background-color: $ghost_hover; }
QLineEdit, QTextEdit, QComboBox { background-color: $input_bg; color: $text;
    border: 1px solid $input_border; border-radius: 6px; padding: 7px; font-size: 13px; }
QTableWidget { background-color: $surface; gridline-color: $table_grid;
    border: 1px solid $table_border; border-radius: 8px; font-size: 13px; }
QTableWidget::item { padding: 6px; }
QHeaderView::section { background-color: $accent_deep; color: $btn_text;
    padding: 8px; font-weight: bold; border: none; }
QProgressBar { border: 1px solid $input_border; border-radius: 6px; background: $progress_bg;
    text-align: center; color: $text; height: 18px; }
QProgressBar::chunk { background-color: $accent; border-radius: 5px; }
QDialog { background-color: $bg; }
QCheckBox { font-size: 13px; }
""")

THEME_PALETTES = {
    "dark": dict(
        bg="#0d1218", surface="#131a22", text="#e9f2ec", subtext="#9aa7ad",
        accent="#00e676", accent_deep="#1b5e20", accent_hover="#2e9e44",
        on_accent="#0d1218", btn_text="#ffffff",
        disabled_bg="#37474f", disabled_text="#8fa0a8",
        danger="#c62828", danger_hover="#e53935",
        ghost_bg="#1c2830", ghost_hover="#2a3842", ghost_text="#e9f2ec",
        input_bg="#161e26", input_border="#2f3d47",
        table_grid="#222e38", table_border="#222e38", progress_bg="#161e26"),
    "light": dict(
        bg="#f4f6f4", surface="#ffffff", text="#1b2b1e", subtext="#6b7a6e",
        accent="#1b7a2e", accent_deep="#1b7a2e", accent_hover="#239a3a",
        on_accent="#ffffff", btn_text="#ffffff",
        disabled_bg="#b9c6bb", disabled_text="#6b7a6e",
        danger="#c62828", danger_hover="#e53935",
        ghost_bg="#dde5de", ghost_hover="#cdd8ce", ghost_text="#1b2b1e",
        input_bg="#ffffff", input_border="#b9c6bb",
        table_grid="#dde5de", table_border="#cdd8ce", progress_bg="#e7ede7"),
    "midnight": dict(
        bg="#0a0f1e", surface="#101a30", text="#e3ecff", subtext="#8b9bb8",
        accent="#38bdf8", accent_deep="#0369a1", accent_hover="#0ea5e9",
        on_accent="#04121f", btn_text="#ffffff",
        disabled_bg="#1c2742", disabled_text="#5b6b8c",
        danger="#b91c1c", danger_hover="#dc2626",
        ghost_bg="#16213a", ghost_hover="#1e2c4d", ghost_text="#e3ecff",
        input_bg="#0e1628", input_border="#24345a",
        table_grid="#1e2c4d", table_border="#1e2c4d", progress_bg="#0e1628"),
    "emerald": dict(
        bg="#0b1512", surface="#10201a", text="#e6f4ec", subtext="#93a89d",
        accent="#34d399", accent_deep="#047857", accent_hover="#10b981",
        on_accent="#06281c", btn_text="#ffffff",
        disabled_bg="#1a2b23", disabled_text="#5f7a6d",
        danger="#b91c1c", danger_hover="#dc2626",
        ghost_bg="#14271f", ghost_hover="#1d352b", ghost_text="#e6f4ec",
        input_bg="#0e1c15", input_border="#234034",
        table_grid="#1d352b", table_border="#1d352b", progress_bg="#0e1c15"),
    "sunset": dict(
        bg="#171008", surface="#221709", text="#f7ead9", subtext="#a89880",
        accent="#fb923c", accent_deep="#c2410c", accent_hover="#f97316",
        on_accent="#241102", btn_text="#ffffff",
        disabled_bg="#2a2013", disabled_text="#7a6a52",
        danger="#b91c1c", danger_hover="#dc2626",
        ghost_bg="#2a1e10", ghost_hover="#3a2a15", ghost_text="#f7ead9",
        input_bg="#1e1509", input_border="#453419",
        table_grid="#3a2a15", table_border="#3a2a15", progress_bg="#1e1509"),
    "amethyst": dict(
        bg="#120e1c", surface="#1a1428", text="#ece5f7", subtext="#9a8fb5",
        accent="#c084fc", accent_deep="#7e22ce", accent_hover="#a855f7",
        on_accent="#1e0a33", btn_text="#ffffff",
        disabled_bg="#221b36", disabled_text="#6f6390",
        danger="#b91c1c", danger_hover="#dc2626",
        ghost_bg="#1f1832", ghost_hover="#2c2342", ghost_text="#ece5f7",
        input_bg="#161129", input_border="#352a52",
        table_grid="#2c2342", table_border="#2c2342", progress_bg="#161129"),
    "ocean": dict(
        bg="#e9f3f9", surface="#ffffff", text="#0c2b3e", subtext="#5b7a90",
        accent="#0284c7", accent_deep="#0369a1", accent_hover="#0ea5e9",
        on_accent="#ffffff", btn_text="#ffffff",
        disabled_bg="#c3d5e0", disabled_text="#6b8a9c",
        danger="#c62828", danger_hover="#e53935",
        ghost_bg="#d5e8f2", ghost_hover="#bfdcee", ghost_text="#0c2b3e",
        input_bg="#ffffff", input_border="#aecadd",
        table_grid="#d5e8f2", table_border="#bfd9e8", progress_bg="#d9eaf4"),
    "rose": dict(
        bg="#fbf0f4", surface="#ffffff", text="#3d1220", subtext="#96707e",
        accent="#db2777", accent_deep="#be185d", accent_hover="#ec4899",
        on_accent="#ffffff", btn_text="#ffffff",
        disabled_bg="#e8ccd5", disabled_text="#9c7585",
        danger="#c62828", danger_hover="#e53935",
        ghost_bg="#f5dde6", ghost_hover="#eec9d8", ghost_text="#3d1220",
        input_bg="#ffffff", input_border="#e5b9cb",
        table_grid="#f5dde6", table_border="#e8c3d2", progress_bg="#f7e0e9"),
}

# کلید تم -> کلید رشته نمایشی (دوزبانه)
THEMES = {"dark": "theme_dark", "light": "theme_light",
          "midnight": "theme_midnight", "emerald": "theme_emerald",
          "sunset": "theme_sunset", "amethyst": "theme_amethyst",
          "ocean": "theme_ocean", "rose": "theme_rose",
          "system": "theme_system"}


def resolve_theme(theme):
    if theme == "system":
        try:
            hints = QApplication.instance().styleHints()
            scheme = hints.colorScheme()
            from PySide6.QtCore import Qt as _Qt
            return "dark" if scheme == _Qt.ColorScheme.Dark else "light"
        except Exception:
            return "light"
    return theme if theme in THEME_PALETTES else "dark"


def apply_theme(theme):
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(QSS_TEMPLATE.substitute(THEME_PALETTES[resolve_theme(theme)]))




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


def find_portable_asset(release):
    for a in release.get("assets", []):
        name = (a.get("name") or "").lower()
        if "portable" in name and name.endswith(".exe"):
            return a
    return None


# ----------------------------------------------------------------------------
# دیالوگ افزودن / ویرایش سرور
# ----------------------------------------------------------------------------

class ServerDialog(QDialog):
    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.setWindowTitle(T("add_server") if server is None else T("edit_server"))
        self.setMinimumWidth(430)
        self._name_touched = server is not None

        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.name_edit = QLineEdit(server.name if server else "")
        self.name_edit.setPlaceholderText(T("ex_name"))
        self.name_edit.textEdited.connect(lambda _t: setattr(self, "_name_touched", True))

        self.url_edit = QLineEdit()
        if server:
            self.url_edit.setText(server_rtmp_url(server))
        self.url_edit.setPlaceholderText("rtmp://host:1935/live")
        self.url_edit.setLayoutDirection(Qt.LeftToRight)
        self.url_edit.textChanged.connect(self.on_url_changed)

        self.region_combo = QComboBox()
        for _rk in REGIONS:
            self.region_combo.addItem(region_name(_rk), _rk)
        if server:
            _skey = server.region if server.region in REGIONS \
                else _REGION_FA2KEY.get(server.region, REGION_UNKNOWN)
            idx = self.region_combo.findData(_skey)
            self.region_combo.setCurrentIndex(idx if idx >= 0 else REGIONS.index(REGION_UNKNOWN))

        self.note_edit = QLineEdit(server.note if server else "")
        self.note_edit.setPlaceholderText(T("optional_note"))

        hint = QLabel(T("auto_hint"))
        hint.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        hint.setWordWrap(True)

        layout.addRow(T("server_name"), self.name_edit)
        layout.addRow(T("rtmp_addr"), self.url_edit)
        layout.addRow(T("region"), self.region_combo)
        layout.addRow(T("note"), self.note_edit)
        layout.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(T("ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(T("cancel"))
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
        if region != REGION_UNKNOWN:
            idx = self.region_combo.findData(region)
            if idx >= 0:
                self.region_combo.setCurrentIndex(idx)

    def get_server(self, existing=None):
        host, port = parse_rtmp(self.url_edit.text())
        name = self.name_edit.text().strip() or suggest_name(host) or T("server_word")
        region = self.region_combo.currentData()
        note = self.note_edit.text().strip()
        if existing:
            existing.name, existing.host, existing.port = name, host, port
            existing.region, existing.note = region, note
            return existing
        return Server(name=name, host=host, port=port, region=region, note=note)


class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("import_title"))
        self.setMinimumSize(480, 320)
        layout = QVBoxLayout(self)
        hint = QLabel(T("import_hint"))
        hint.setStyleSheet("color: #9e9e9e; font-size: 12px;")
        hint.setWordWrap(True)
        self.text = QTextEdit()
        self.text.setPlaceholderText("IR1 | rtmp://ir1.example.com:1935/live\nDE1 | rtmp://de1.example.com:1935/live")
        self.text.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(hint)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(T("do_import"))
        buttons.button(QDialogButtonBox.Cancel).setText(T("cancel"))
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
    def __init__(self, parent, theme, auto_check, lang):
        super().__init__(parent)
        self.setWindowTitle(T("settings"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self.theme_combo = QComboBox()
        for _tk, _sk in THEMES.items():
            self.theme_combo.addItem(T(_sk), _tk)
        idx = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        # پیش‌نمایش لحظه‌ای تم
        self.theme_combo.currentIndexChanged.connect(self._preview_theme)
        form.addRow(T("theme_label"), self.theme_combo)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("فارسی", "fa")
        self.lang_combo.addItem("English", "en")
        idx = self.lang_combo.findData(lang)
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(T("lang_label"), self.lang_combo)

        self.auto_check_box = QCheckBox(T("autocheck"))
        self.auto_check_box.setChecked(auto_check)
        form.addRow(self.auto_check_box)
        layout.addLayout(form)

        upd_box = QVBoxLayout()
        ver_label = QLabel(f"{T('current_version')} <b>{__version__}</b>")
        self.upd_status = QLabel("")
        self.upd_status.setWordWrap(True)
        self.upd_status.setStyleSheet("font-size: 12px; color: #9e9e9e;")
        check_btn = QPushButton(T("check_update"))
        check_btn.setObjectName("ghost")
        check_btn.clicked.connect(self.on_check_update)
        upd_box.addWidget(ver_label)
        upd_box.addWidget(check_btn)
        upd_box.addWidget(self.upd_status)
        layout.addLayout(upd_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(T("save"))
        buttons.button(QDialogButtonBox.Cancel).setText(T("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview_theme(self):
        parent = self.parent()
        if parent and hasattr(parent, "preview_theme"):
            parent.preview_theme(self.theme_combo.currentData())

    def on_check_update(self):
        self.upd_status.setText(T("checking"))
        parent = self.parent()
        if parent and hasattr(parent, "check_for_updates"):
            parent.check_for_updates(manual=True, status_label=self.upd_status)

    def values(self):
        return (self.theme_combo.currentData(),
                self.auto_check_box.isChecked(),
                self.lang_combo.currentData())


# ----------------------------------------------------------------------------
# دیالوگ آپدیت جدید
# ----------------------------------------------------------------------------

class UpdateDialog(QDialog):
    """دیالوگ نسخه جدید: انتخاب بین فایل آپدیت (قابل‌حمل) و فایل نصبی."""
    def __init__(self, parent, release):
        super().__init__(parent)
        tag = release.get("tag_name", "")
        self.choice = None
        self.setWindowTitle(T("new_version_title"))
        self.setMinimumSize(460, 360)
        layout = QVBoxLayout(self)
        title = QLabel(f"{T('new_version')} <b>{tag}</b> {T('version_released')} "
                       f"({T('your_version')} {__version__})")
        title.setWordWrap(True)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(release.get("body") or "—")
        layout.addWidget(title)
        layout.addWidget(QLabel(T("changes")))
        layout.addWidget(body)
        row = QHBoxLayout()
        upd_btn = QPushButton(T("dl_update_file"))
        inst_btn = QPushButton(T("dl_installer"))
        later_btn = QPushButton(T("later"))
        later_btn.setObjectName("ghost")
        upd_btn.clicked.connect(lambda: self._done("portable"))
        inst_btn.clicked.connect(lambda: self._done("setup"))
        later_btn.clicked.connect(self.reject)
        row.addWidget(upd_btn)
        row.addWidget(inst_btn)
        row.addWidget(later_btn)
        layout.addLayout(row)
        self.release = release

    def _done(self, choice):
        self.choice = choice
        self.accept()


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
        self.lang = "fa"
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
                _lang = data.get("lang", "fa")
                self.lang = _lang if _lang in ("fa", "en") else "fa"
            # مهاجرت نام‌های فارسی قدیم منطقه به کلید جدید
            for _sv in self.servers:
                if _sv.region in _REGION_FA2KEY:
                    _sv.region = _REGION_FA2KEY[_sv.region]
                elif _sv.region not in REGIONS:
                    _sv.region = REGION_UNKNOWN
        except Exception:
            self.servers = [Server(**s) for s in DEFAULT_SERVERS]
        global LANG
        LANG = self.lang

    def save_settings(self):
        try:
            DATA_FILE.write_text(json.dumps(
                {"servers": [asdict(s) for s in self.servers],
                 "theme": self.theme,
                 "auto_check_update": self.auto_check_update,
                 "lang": self.lang},
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
        subtitle = QLabel(T("subtitle"))
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
        self.scan_btn = QPushButton(T("scan_all"))
        self.scan_btn.clicked.connect(self.run_scan)
        add_btn = QPushButton(T("add"))
        add_btn.setObjectName("ghost")
        add_btn.clicked.connect(self.add_server)
        edit_btn = QPushButton(T("edit"))
        edit_btn.setObjectName("ghost")
        edit_btn.clicked.connect(self.edit_server)
        del_btn = QPushButton(T("delete"))
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self.delete_server)
        import_btn = QPushButton(T("bulk_import"))
        import_btn.setObjectName("ghost")
        import_btn.clicked.connect(self.import_servers)
        settings_btn = QPushButton(T("settings"))
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
            [T("col_server"), T("col_region"), T("col_ping"), "Packet Loss",
             T("col_tcp"), T("col_status")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.copy_row_server)
        layout.addWidget(self.table)

        bottom = QHBoxLayout()
        self.copy_btn = QPushButton(T("copy_best"))
        self.copy_btn.clicked.connect(self.copy_best)
        self.copy_btn.setEnabled(False)
        bottom.addWidget(self.copy_btn)
        layout.addLayout(bottom)

    # -- جدول ----------------------------------------------------------------
    def refresh_table(self):
        self.table.setRowCount(len(self.servers))
        for i, s in enumerate(self.servers):
            self.table.setItem(i, 0, QTableWidgetItem(s.name))
            self.table.setItem(i, 1, QTableWidgetItem(region_name(s.region)))
            r = self.last_results.get(s.id)
            if r:
                self.fill_result_row(i, r)
            else:
                for c in range(2, 6):
                    self.table.setItem(i, c, QTableWidgetItem("—"))

    def fill_result_row(self, i, r):
        ping_txt = f"{r['ping_ms']:.0f} ms" if r["ping_ms"] is not None else T("failed")
        tcp_txt = f"{r['tcp_ms']:.0f} ms" if r["tcp_ms"] is not None else T("down")
        ok_txt = T("up") if r["ok"] else T("down_emoji")
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
            QMessageBox.information(self, T("scan"), T("add_first"))
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
        self.table.setItem(index, 1, QTableWidgetItem(region_name(srv.region)))
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
            QMessageBox.warning(self, T("scan"), T("no_server"))
            return
        best = min(ok_results, key=lambda r: r["score"])
        srv = next((s for s in self.servers if s.id == best["id"]), None)
        name = srv.name if srv else best["name"]
        region = srv.region if srv else best.get("region", "")
        self.banner.setText(
            f"🏆 {T('best_server_lbl')}: {name} ({region_name(region)}) — "
            f"{T('col_ping')} {best['ping_ms']:.0f}ms، {T('col_tcp')} {best['tcp_ms']:.0f}ms")
        self.banner.setVisible(True)
        self.copy_btn.setEnabled(True)
        self._best = best

    def copy_best(self):
        best = getattr(self, "_best", None)
        if not best:
            return
        url = f"rtmp://{best['host']}:{best['port']}/live"
        QApplication.clipboard().setText(url)
        QMessageBox.information(self, T("copied"),
                                f"{T('rtmp_copied')}\n{url}\n\n"
                                f"{T('copied_msg')}")

    def copy_row_server(self, item):
        """دابل‌کلیک روی هر ردیف = کپی آدرس RTMP همان سرور."""
        row = item.row()
        if 0 <= row < len(self.servers):
            url = server_rtmp_url(self.servers[row])
            if url:
                QApplication.clipboard().setText(url)
                self.statusBar().showMessage(T("dblclick_copied"), 2500)

    # -- مدیریت سرورها ----------------------------------------------------------
    def selected_server(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, T("select"), T("select_first"))
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
        if QMessageBox.question(self, T("delete_title"), f"«{srv.name}» {T('delete_q')}") \
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
                QMessageBox.information(self, T("import"), f"{len(new)} {T('import_n')}")
            else:
                QMessageBox.information(self, T("import"), T("import_none"))

    # -- تنظیمات -----------------------------------------------------------------
    def preview_theme(self, theme):
        """پیش‌نمایش لحظه‌ای تم از داخل دیالوگ تنظیمات."""
        apply_theme(theme)

    def open_settings(self):
        dlg = SettingsDialog(self, self.theme, self.auto_check_update, self.lang)
        orig_theme = self.theme
        if dlg.exec():
            theme, auto, lang = dlg.values()
            self.theme = theme
            self.auto_check_update = auto
            apply_theme(theme)
            self.save_settings()
            if lang != self.lang:
                self.lang = lang
                self.save_settings()
                QMessageBox.information(self, T("settings"), T("lang_restart"))
        else:
            apply_theme(orig_theme)

    # -- آپدیت -------------------------------------------------------------------
    def check_for_updates(self, manual=False, status_label=None):
        def worker():
            try:
                rel = fetch_latest_release()
                newer = _ver_tuple(rel.get("tag_name", "0")) > _ver_tuple(__version__)
            except Exception as e:
                if manual:
                    msg = f"{T('update_err')} {e}"
                    if status_label:
                        QTimer.singleShot(0, lambda: status_label.setText(msg))
                    else:
                        QTimer.singleShot(0, lambda: QMessageBox.warning(
                            self, T("update"), msg))
                return
            if newer:
                QTimer.singleShot(0, lambda: self.update_found.emit(rel))
                if manual and status_label:
                    tag = rel.get("tag_name", "")
                    QTimer.singleShot(0, lambda: status_label.setText(
                        f"{T('new_version')} {tag} {T('update_avail')}"))
            elif manual:
                msg = T("update_latest")
                if status_label:
                    QTimer.singleShot(0, lambda: status_label.setText(msg))
                else:
                    QTimer.singleShot(0, lambda: QMessageBox.information(
                        self, T("update"), msg))
        threading.Thread(target=worker, daemon=True).start()

    @Slot(dict)
    def on_update_found(self, release):
        tag = release.get("tag_name", "")
        dlg = UpdateDialog(self, release)
        if dlg.exec() and dlg.choice:
            if dlg.choice == "setup":
                asset = find_setup_asset(release)
                kind = "setup"
            else:
                asset = find_portable_asset(release)
                kind = "portable"
            if not asset:
                QMessageBox.warning(self, T("update"), T("file_not_found"))
                return
            self.download_and_install(asset, tag, kind)

    def download_and_install(self, asset, tag, kind="setup"):
        url = asset.get("browser_download_url", "")
        name = asset.get("name", "StreamScanner-Setup.exe")
        if kind == "portable":
            dest = str(Path.home() / "Downloads" / f"StreamScanner-{tag}-Portable.exe")
        else:
            dest = str(Path(tempfile.gettempdir()) / name)
        prog = QProgressDialog(T("downloading"), T("cancel"), 0, 0, self)
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
                    self, T("update"), f"{T('download_failed')}\n{e}")))
                return
            def done():
                prog.close()
                if kind == "portable":
                    QMessageBox.information(
                        self, T("update"), f"{T('portable_saved')}\n{dest}")
                    return
                if QMessageBox.question(
                        self, T("update"),
                        f"{T('version')} {tag} {T('downloaded')} {T('install_q')}") \
                        == QMessageBox.Yes:
                    try:
                        if sys.platform == "win32":
                            import os as _os
                            _os.startfile(dest)  # noqa
                        else:
                            QMessageBox.information(
                                self, T("update"), f"{T('installer_file')}\n{dest}")
                    finally:
                        QApplication.quit()
            QTimer.singleShot(0, done)
        threading.Thread(target=worker, daemon=True).start()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("StreamScanner")
    app.setWindowIcon(app_icon())
    try:
        _d = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        _lang = _d.get("lang", "fa") if isinstance(_d, dict) else "fa"
    except Exception:
        _lang = "fa"
    global LANG
    LANG = _lang if _lang in ("fa", "en") else "fa"
    app.setLayoutDirection(Qt.RightToLeft if LANG == "fa" else Qt.LeftToRight)
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
