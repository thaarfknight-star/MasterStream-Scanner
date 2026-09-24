# -*- coding: utf-8 -*-
# StreamScanner Android — core.py
# Copyright (c) 2026 thaarfknight-star. All rights reserved.
# Source-available, NOT open-source: viewing permitted; copying, modification,
# redistribution or reuse prohibited without written permission. See LICENSE.
"""
منطق خالص StreamScanner برای نسخه اندروید (بدون هیچ وابستگی به UI).

بازاستفاده‌شده از نسخه ویندوز (streamscanner.py) با این تفاوت‌ها:
  - امتیازدهی سرورها TCP-محور است: روی اندروید پینگ ICMP معمولاً بدون روت
    کار نمی‌کند؛ اگر پینگ جواب نداد نادیده گرفته می‌شود و سرور «قطع» حساب
    نمی‌شود (ملاک وصل بودن فقط TCP به پورت RTMP است).
  - بررسی آپدیت فقط ریلیزهایی با تگ «android-v*» را در نظر می‌گیرد تا با
    ریلیزهای ویندوز قاطی نشود؛ فایل موردنظر APK است.
"""

import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

__version__ = "1.0.2"
GITHUB_OWNER = "thaarfknight-star"
GITHUB_REPO = "StreamScanner"
ANDROID_TAG_PREFIX = "android-v"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

APP_NAME = "StreamScanner"
DEFAULT_RTMP_PORT = 1935

REGION_IRAN = "ir"
REGION_UNKNOWN = "unknown"
REGIONS = ["ir", "de", "fr", "nl", "uk", "tr", "ae", REGION_UNKNOWN]
# نگاشت نام‌های فارسی قدیم (servers.json نسخه‌های قبل) به کلید جدید
_REGION_FA2KEY = {"ایران": "ir", "آلمان": "de", "فرانسه": "fr", "هلند": "nl",
                  "انگلیس": "uk", "ترکیه": "tr", "امارات": "ae", "نامشخص": "unknown"}

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
    "back": ("بازگشت", "Back"),
    "new_version": ("نسخه جدید", "New version"),
    "new_version_title": ("نسخه جدید موجود است", "New version available"),
    "version_released": ("منتشر شده است", "has been released"),
    "your_version": ("نسخه شما:", "Your version:"),
    "changes": ("تغییرات:", "Changes:"),
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
    "col_ping": ("پینگ", "Ping"),
    "col_tcp": ("اتصال TCP", "TCP connect"),
    "copy_best": ("📋 کپی آدرس RTMP سرور پیشنهادی",
                  "📋 Copy recommended server's RTMP address"),
    "best_server_lbl": ("بهترین سرور", "Best server"),
    "add_first": ("اول چند سرور اضافه کنید.", "Add some servers first."),
    "scan": ("اسکن", "Scan"),
    "scanning": ("در حال اسکن…", "Scanning…"),
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
    "portable_saved": ("فایل آپدیت ذخیره شد در:", "Update file saved to:"),
    "dblclick_copied": ("آدرس RTMP سرور کپی شد", "Server RTMP address copied"),
    "lang_restart": ("برای اعمال زبان جدید، برنامه را ببندید و دوباره باز کنید.",
                     "Please restart the app to apply the new language."),
    "server_word": ("سرور", "Server"),
    "tap_select_hint": ("یک‌بار لمس: انتخاب — دو‌بار لمس: کپی آدرس",
                        "Single tap: select — Double tap: copy address"),
    "dl_install_apk": ("📥 دانلود و نصب نسخه اندروید", "📥 Download & install Android update"),
    "installing": ("در حال آماده‌سازی نصب…", "Preparing installation…"),
    "install_failed": ("نصب خودکار ناموفق بود.", "Automatic installation failed."),
    "install_manual": ("فایل APK را از پوشه دانلودها باز و نصب کنید.",
                       "Open the APK from the Downloads folder and install it."),
    "allow_unknown": ("اگر نصب شروع نشد، «نصب برنامه‌های ناشناس» را برای StreamScanner فعال کنید.",
                      "If installation doesn't start, enable “Install unknown apps” for StreamScanner."),
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
# تست شبکه — TCP-محور (روی اندروید پینگ ICMP معمولاً در دسترس نیست)
# ----------------------------------------------------------------------------

def ping_host(host, count=2, timeout_ms=1500):
    """میانگین پینگ (ms) و درصد packet loss؛ در صورت عدم دسترسی (None, 100)."""
    if not host:
        return None, 100.0
    cmd = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=count * (timeout_ms / 1000) + 5)
        out = proc.stdout or ""
        times = [float(x) for x in re.findall(r"time[=<](\d+(?:\.\d+)?)\s*ms", out)]
        loss_m = re.search(r"(\d+)%\s*(?:packet\s*)?loss", out, re.IGNORECASE)
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
    """تست کامل یک سرور؛ نتیجه دیکشنری.

    نسخه اندروید TCP-محور است: ملاک «وصل بودن» فقط TCP است. اگر پینگ جواب
    ندهد (روی اندروید رایج است) نادیده گرفته می‌شود و در امتیاز اثری ندارد.
    """
    s = dict(server)
    host, port = s.get("host", ""), s.get("port", DEFAULT_RTMP_PORT)
    tcp_ms = tcp_probe(host, port)
    ok = tcp_ms is not None
    ping_ms, loss = ping_host(host)
    if not ok:
        score = 1_000_000.0
    else:
        score = tcp_ms
        if ping_ms is not None:
            score += ping_ms * 0.3 + loss * 20.0
    return {
        "id": s.get("id"), "name": s.get("name"), "region": s.get("region"),
        "host": host, "port": port,
        "ping_ms": ping_ms, "loss": loss, "tcp_ms": tcp_ms,
        "ok": ok, "score": score,
    }


def scan_servers(servers, max_workers=16):
    """اسکن موازی همه سرورها؛ لیست نتیجه‌ها به ترتیب ورودی."""
    results = [None] * len(servers)
    if not servers:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(servers))) as ex:
        futs = {ex.submit(probe_server, s): i for i, s in enumerate(servers)}
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception:
                s = servers[i]
                results[i] = {"id": s.get("id"), "name": s.get("name"),
                              "region": s.get("region"), "host": s.get("host"),
                              "port": s.get("port"), "ping_ms": None,
                              "loss": 100.0, "tcp_ms": None, "ok": False,
                              "score": 1_000_000.0}
    return results


# ----------------------------------------------------------------------------
# تم‌ها — پالت‌های رنگی (مشترک با نسخه ویندوز)
# ----------------------------------------------------------------------------

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


def resolve_theme(theme, system_dark=None):
    """کلید تم نهایی؛ برای system از وضعیت سیستم (system_dark) استفاده می‌شود."""
    if theme == "system":
        return "dark" if system_dark else "light"
    return theme if theme in THEME_PALETTES else "dark"


# ----------------------------------------------------------------------------
# بررسی آپدیت از گیت‌هاب — فقط ریلیزهای اندروید (تگ android-v*)
# ----------------------------------------------------------------------------

def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def fetch_latest_android_release():
    """جدیدترین ریلیز اندروید (تگ android-v*) یا None."""
    req = urllib.request.Request(
        RELEASES_API + "?per_page=20",
        headers={"User-Agent": "StreamScanner-Android",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        releases = json.load(r)
    for rel in releases:
        tag = rel.get("tag_name", "")
        if tag.startswith(ANDROID_TAG_PREFIX):
            return rel
    return None


def find_apk_asset(release):
    for a in (release or {}).get("assets", []):
        name = (a.get("name") or "").lower()
        if name.endswith(".apk"):
            return a
    return None
