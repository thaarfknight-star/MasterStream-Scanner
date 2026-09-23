# -*- coding: utf-8 -*-
"""
اسکنر سرور مستراستریم | MasterStream Server Scanner
====================================================
برنامه‌ای برای پیدا کردن بهترین سرور مستراستریم جهت استریم روی Kick.

قابلیت‌ها:
  - لیست پیش‌فرض همه سرورهای مستراستریم (۶ سرور ایران، ۳ سرور آلمان، ۲ سرور خروجی)
  - دکمه «اسکن»: تست پینگ و اتصال TCP به پورت RTMP با اینترنت خود شما
  - رتبه‌بندی سرورها و پیشنهاد بهترین سرور ایران برای استریم روی Kick
  - افزودن / ویرایش / حذف سرور (حتی سرورهای پیش‌فرض)
  - درون‌ریزی گروهی آدرس‌ها از پنل مستراستریم
  - ذخیره خودکار در فایل servers.json کنار برنامه

اجرا:
    pip install PySide6
    python masterstream_scanner.py

نکته: آدرس دقیق سرورها (هاست RTMP) عمومی نیست و فقط داخل پنل کاربری
مستراستریم نمایش داده می‌شود؛ یک‌بار از پنل کپی کنید و در برنامه وارد کنید.
"""

import json
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget, QHeaderView, QAbstractItemView,
)

# ----------------------------------------------------------------------------
# ثابت‌ها
# ----------------------------------------------------------------------------

APP_NAME = "اسکنر سرور مستراستریم"
APP_SUBTITLE = "بهترین سرور را برای استریم روی Kick پیدا کن"
DATA_FILE = Path(__file__).resolve().parent / "servers.json"
DEFAULT_RTMP_PORT = 1935

REGION_IRAN = "ایران"
REGION_EU = "اروپا"
REGION_OUT = "خروجی"

# سرورهای پیش‌فرض — از مخزن رسمی مانیتورینگ مستراستریم
# (github.com/masterking32/masterstream_uptime)
# هاست‌ها خالی‌اند چون عمومی نیستند؛ از پنل کاربری کپی کنید.
DEFAULT_SERVERS = [
    ("ایران ۱ — نور", REGION_IRAN, "Noor"),
    ("ایران ۲ — آسیاتک", REGION_IRAN, "AsiaTech"),
    ("ایران ۳ — مبین", REGION_IRAN, "Mobin IDC"),
    ("ایران ۴ — شیراز", REGION_IRAN, "ITC Shiraz"),
    ("ایران ۵ — سیستک", REGION_IRAN, "Systec"),
    ("ایران ۶ — فناپ", REGION_IRAN, "Fanap"),
    ("آلمان ۱", REGION_EU, "Germany"),
    ("آلمان ۲", REGION_EU, "Germany"),
    ("آلمان ۳", REGION_EU, "Germany"),
    ("خروجی آلمان ۱", REGION_OUT, "Forward"),
    ("خروجی فرانسه ۱", REGION_OUT, "Forward"),
]


# ----------------------------------------------------------------------------
# مدل داده
# ----------------------------------------------------------------------------

@dataclass
class Server:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    region: str = REGION_IRAN
    host: str = ""
    port: int = DEFAULT_RTMP_PORT
    rtmp_url: str = ""
    note: str = ""


def default_server_list():
    return [
        Server(name=name, region=region, host="", port=DEFAULT_RTMP_PORT,
               rtmp_url="", note=provider)
        for name, region, provider in DEFAULT_SERVERS
    ]


def load_servers():
    """خواندن لیست سرورها از فایل؛ اگر نبود، پیش‌فرض‌ها ساخته می‌شود."""
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            return [Server(**s) for s in data.get("servers", [])]
        except Exception:
            pass
    servers = default_server_list()
    save_servers(servers)
    return servers


def save_servers(servers):
    DATA_FILE.write_text(
        json.dumps({"servers": [asdict(s) for s in servers]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_rtmp_url(url):
    """از آدرس کامل RTMP، هاست و پورت را جدا می‌کند."""
    url = (url or "").strip()
    if not url:
        return "", DEFAULT_RTMP_PORT
    if "://" not in url:
        url = "rtmp://" + url
    try:
        p = urlparse(url)
        host = p.hostname or ""
        port = p.port or DEFAULT_RTMP_PORT
        return host, port
    except Exception:
        return "", DEFAULT_RTMP_PORT


# ----------------------------------------------------------------------------
# تست شبکه
# ----------------------------------------------------------------------------

def ping_host(host, count=3, timeout=1):
    """پینگ با دستور سیستمی؛ خروجی: (میانگین میلی‌ثانیه، درصد افت)"""
    system = platform.system()
    if system == "Windows":
        cmd = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=count * (timeout + 1) + 10)
        out = proc.stdout or ""
    except Exception:
        return None, None

    loss = None
    m = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    if m:
        loss = float(m.group(1))
    else:
        m = re.search(r"Lost = \d+ \((\d+)% loss\)", out)
        if m:
            loss = float(m.group(1))

    avg = None
    m = re.search(r"Average = (\d+)ms", out)
    if m:
        avg = float(m.group(1))
    else:
        m = re.search(r"rtt [^=]*=\s*[\d.]+/([\d.]+)/", out)
        if m:
            avg = float(m.group(1))
    return avg, loss


def tcp_probe(host, port, attempts=3, timeout=3):
    """میانگین زمان برقراری اتصال TCP به پورت؛ None یعنی unreachable."""
    times = []
    for _ in range(attempts):
        t0 = time.perf_counter()
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            times.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            pass
    if not times:
        return None
    return sum(times) / len(times)


def score_server(ping_avg, loss, tcp_avg):
    """امتیاز کمتر = بهتر. None یعنی سرور در دسترس نیست."""
    if tcp_avg is None:
        return None
    base = tcp_avg * 0.7 + (ping_avg if ping_avg is not None else tcp_avg) * 0.3
    if loss:
        base += loss * 2.0
    return base


# ----------------------------------------------------------------------------
# ورکر اسکن (در ترد جدا)
# ----------------------------------------------------------------------------

class ScanWorker(QObject):
    progress = Signal(int, str)      # درصد، پیام
    server_done = Signal(str, dict)  # id سرور، نتیجه
    finished = Signal()

    def __init__(self, servers):
        super().__init__()
        self.servers = servers
        self._stop = False

    @Slot()
    def run(self):
        total = len(self.servers)
        for i, srv in enumerate(self.servers):
            if self._stop:
                break
            self.progress.emit(int(i / max(total, 1) * 100), f"در حال تست: {srv.name}")
            result = {"ping": None, "loss": None, "tcp": None, "score": None,
                      "ok": False}
            if srv.host.strip():
                try:
                    ping_avg, loss = ping_host(srv.host.strip())
                    tcp_avg = tcp_probe(srv.host.strip(), srv.port)
                    result.update(ping=ping_avg, loss=loss, tcp=tcp_avg,
                                  score=score_server(ping_avg, loss, tcp_avg),
                                  ok=tcp_avg is not None)
                except Exception:
                    pass
            self.server_done.emit(srv.id, result)
        self.progress.emit(100, "تمام شد")
        self.finished.emit()

    def stop(self):
        self._stop = True


# ----------------------------------------------------------------------------
# استایل تیره گیمینگ
# ----------------------------------------------------------------------------

DARK_QSS = """
* { font-family: "Vazirmatn", "Segoe UI", "Tahoma"; font-size: 13px; }
QMainWindow, QWidget#central { background: #0f1115; }
QLabel { color: #e8eaed; }
QLabel#title { font-size: 22px; font-weight: bold; color: #ffffff; }
QLabel#subtitle { font-size: 12px; color: #9aa0a6; }
QLabel#banner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0d3b26, stop:1 #0f2f22);
    border: 1px solid #00e676; border-radius: 10px;
    padding: 12px; font-size: 14px; font-weight: bold; color: #d7ffe9;
}
QPushButton {
    background: #1c2028; color: #e8eaed;
    border: 1px solid #2c313b; border-radius: 8px; padding: 9px 16px;
}
QPushButton:hover { background: #242a35; border-color: #3a424f; }
QPushButton:disabled { color: #6b7280; background: #16191f; }
QPushButton#scanBtn {
    background: #00c853; color: #ffffff; font-weight: bold; font-size: 14px;
    border: none; padding: 11px 26px;
}
QPushButton#scanBtn:hover { background: #00e676; }
QPushButton#scanBtn:disabled { background: #1d3a2a; color: #6b7280; }
QPushButton#dangerBtn { border-color: #5a2b2b; color: #ff8a80; }
QPushButton#dangerBtn:hover { background: #3a1d1d; }
QTableWidget {
    background: #14171d; color: #e8eaed; gridline-color: #232833;
    border: 1px solid #232833; border-radius: 10px;
    selection-background-color: #1f3a2c;
}
QTableWidget::item { padding: 6px; }
QHeaderView::section {
    background: #1c2028; color: #9aa0a6; border: none;
    padding: 8px; font-weight: bold;
}
QProgressBar {
    background: #1c2028; border: 1px solid #2c313b; border-radius: 8px;
    text-align: center; color: #e8eaed; height: 18px;
}
QProgressBar::chunk { background: #00e676; border-radius: 6px; }
QLineEdit, QTextEdit, QComboBox {
    background: #14171d; color: #e8eaed;
    border: 1px solid #2c313b; border-radius: 8px; padding: 8px;
}
QComboBox QAbstractItemView { background: #1c2028; color: #e8eaed; }
QDialog { background: #0f1115; }
QLabel#hint { color: #9aa0a6; font-size: 11px; }
"""


# ----------------------------------------------------------------------------
# دیالوگ افزودن / ویرایش سرور
# ----------------------------------------------------------------------------

class ServerDialog(QDialog):
    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.setWindowTitle("ویرایش سرور" if server else "افزودن سرور")
        self.setMinimumWidth(420)
        self.setStyleSheet(DARK_QSS)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "💡 آدرس RTMP را از پنل مستراستریم کپی کنید؛ هاست و پورت خودکار جدا می‌شود.\n"
            "مثال: rtmp://ir3.masterstream.ir:1935/live"
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.region_combo = QComboBox()
        self.region_combo.addItems([REGION_IRAN, REGION_EU, REGION_OUT])
        self.rtmp_edit = QLineEdit()
        self.rtmp_edit.setPlaceholderText("rtmp://host:1935/live")
        self.rtmp_edit.setAlignment(Qt.AlignLeft)
        self.host_edit = QLineEdit()
        self.host_edit.setAlignment(Qt.AlignLeft)
        self.port_edit = QLineEdit()
        self.port_edit.setAlignment(Qt.AlignLeft)
        self.note_edit = QLineEdit()

        # با تایپ آدرس کامل، هاست/پورت خودکار پر شود
        self.rtmp_edit.textChanged.connect(self._autofill)

        form.addRow("نام سرور:", self.name_edit)
        form.addRow("منطقه:", self.region_combo)
        form.addRow("آدرس کامل RTMP:", self.rtmp_edit)
        form.addRow("هاست:", self.host_edit)
        form.addRow("پورت:", self.port_edit)
        form.addRow("توضیح:", self.note_edit)
        layout.addLayout(form)

        if server:
            self.name_edit.setText(server.name)
            self.region_combo.setCurrentText(server.region)
            self.rtmp_edit.setText(server.rtmp_url)
            self.host_edit.setText(server.host)
            self.port_edit.setText(str(server.port))
            self.note_edit.setText(server.note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تأیید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _autofill(self, text):
        host, port = parse_rtmp_url(text)
        if host:
            self.host_edit.setText(host)
            self.port_edit.setText(str(port))

    def get_server(self, server=None):
        srv = server or Server()
        srv.name = self.name_edit.text().strip() or "سرور جدید"
        srv.region = self.region_combo.currentText()
        srv.rtmp_url = self.rtmp_edit.text().strip()
        srv.host = self.host_edit.text().strip()
        try:
            srv.port = int(self.port_edit.text().strip() or DEFAULT_RTMP_PORT)
        except ValueError:
            srv.port = DEFAULT_RTMP_PORT
        srv.note = self.note_edit.text().strip()
        return srv


# ----------------------------------------------------------------------------
# دیالوگ درون‌ریزی گروهی
# ----------------------------------------------------------------------------

class ImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("درون‌ریزی گروهی سرورها")
        self.setMinimumSize(480, 360)
        self.setStyleSheet(DARK_QSS)
        layout = QVBoxLayout(self)

        hint = QLabel(
            "هر خط یک سرور، با این قالب:\n"
            "نام سرور | rtmp://host:1935/live\n\n"
            "مثال:\nایران ۳ — مبین | rtmp://ir3.example.ir:1935/live"
        )
        hint.setObjectName("hint")
        layout.addWidget(hint)

        self.text = QTextEdit()
        self.text.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("افزودن همه")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_servers(self):
        servers = []
        for line in self.text.toPlainText().splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            name, url = [p.strip() for p in line.split("|", 1)]
            host, port = parse_rtmp_url(url)
            region = REGION_IRAN if re.search(r"ایران|iran|ir\d", name + url,
                                             re.IGNORECASE) else REGION_EU
            servers.append(Server(name=name or host, region=region,
                                  host=host, port=port, rtmp_url=url))
        return servers


# ----------------------------------------------------------------------------
# پنجره اصلی
# ----------------------------------------------------------------------------

COLS = ["وضعیت", "نام سرور", "منطقه", "هاست", "پینگ", "افت بسته", "اتصال TCP", "امتیاز"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — انتخاب بهترین سرور برای Kick")
        self.resize(920, 620)
        self.setStyleSheet(DARK_QSS)

        self.servers = load_servers()
        self.results = {}          # id -> result dict
        self.scan_thread = None
        self.scan_worker = None

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # تیتر
        title = QLabel("⚡ " + APP_NAME)
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(APP_SUBTITLE + " — روی «اسکن» بزن تا با اینترنت خودت بهترین سرور مشخص شود")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # بنر پیشنهاد
        self.banner = QLabel("")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        root.addWidget(self.banner)

        # جدول
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        # پیشرفت
        prog_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label = QLabel("آماده")
        self.status_label.setObjectName("subtitle")
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.status_label)
        root.addLayout(prog_row)

        # دکمه‌ها
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 اسکن همه سرورها")
        self.scan_btn.setObjectName("scanBtn")
        self.scan_btn.clicked.connect(self.start_scan)
        btn_row.addWidget(self.scan_btn)

        add_btn = QPushButton("➕ افزودن")
        add_btn.clicked.connect(self.add_server)
        btn_row.addWidget(add_btn)

        edit_btn = QPushButton("✏️ ویرایش")
        edit_btn.clicked.connect(self.edit_server)
        btn_row.addWidget(edit_btn)

        del_btn = QPushButton("🗑 حذف")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(self.delete_server)
        btn_row.addWidget(del_btn)

        copy_btn = QPushButton("📋 کپی آدرس RTMP")
        copy_btn.clicked.connect(self.copy_rtmp)
        btn_row.addWidget(copy_btn)

        import_btn = QPushButton("📥 درون‌ریزی گروهی")
        import_btn.clicked.connect(self.import_servers)
        btn_row.addWidget(import_btn)

        reset_btn = QPushButton("↺ بازنشانی")
        reset_btn.clicked.connect(self.reset_defaults)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        hint = QLabel("💡 فقط سرورهای «ایران» برای اتصال شما مناسب‌اند؛ سرورهای اروپا/خروجی را خود مستراستریم مدیریت می‌کند.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.refresh_table()

    # -- جدول -------------------------------------------------------------
    def refresh_table(self, order=None):
        servers = list(self.servers)
        if order == "score":
            servers.sort(key=lambda s: (
                self.results.get(s.id, {}).get("score") is None,
                self.results.get(s.id, {}).get("score") or 1e9,
            ))
        self.table.setRowCount(len(servers))
        for row, srv in enumerate(servers):
            res = self.results.get(srv.id, {})
            status, color = self._status_cell(srv, res)
            cells = [
                (status, color),
                (srv.name, None),
                (srv.region, None),
                (srv.host or "—", None),
                (f"{res['ping']:.0f} ms" if res.get("ping") is not None else "—", None),
                (f"{res['loss']:.0f}٪" if res.get("loss") is not None else "—", None),
                (f"{res['tcp']:.0f} ms" if res.get("tcp") is not None else "—", None),
                (f"{res['score']:.0f}" if res.get("score") is not None else "—", None),
            ]
            for col, (text, fg) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, srv.id)
                if fg:
                    item.setForeground(QColor(fg))
                if col == 0:
                    font = QFont()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(row, col, item)

    def _status_cell(self, srv, res):
        if not srv.host.strip():
            return ("⚪ بدون آدرس", "#9aa0a6")
        if not res:
            return ("⚪ تست نشده", "#9aa0a6")
        if res.get("ok"):
            return ("🟢 سالم", "#00e676")
        return ("🔴 قطع", "#ff5252")

    def selected_server(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        srv_id = self.table.item(row, 0).data(Qt.UserRole)
        return next((s for s in self.servers if s.id == srv_id), None)

    # -- اسکن --------------------------------------------------------------
    def start_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        testable = [s for s in self.servers if s.host.strip()]
        if not testable:
            QMessageBox.information(self, "اسکن", "هیچ سروری آدرس ندارد! اول آدرس RTMP را از پنل مستراستریم وارد کنید.")
            return
        self.banner.hide()
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("⏳ در حال اسکن...")
        self.results = {}

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(self.servers)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self._on_progress)
        self.scan_worker.server_done.connect(self._on_server_done)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_thread.start()

    @Slot(int, str)
    def _on_progress(self, pct, msg):
        self.progress.setValue(pct)
        self.status_label.setText(msg)

    @Slot(str, dict)
    def _on_server_done(self, srv_id, result):
        self.results[srv_id] = result
        self.refresh_table()

    @Slot()
    def _on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("🔍 اسکن همه سرورها")
        self.status_label.setText("تمام شد")
        self.refresh_table(order="score")
        self._show_recommendation()

    def _show_recommendation(self):
        iran = [s for s in self.servers if s.region == REGION_IRAN]
        ranked = [(s, self.results.get(s.id, {}).get("score"))
                  for s in iran]
        ranked = [(s, sc) for s, sc in ranked if sc is not None]
        if not ranked:
            self.banner.setText("⚠️ هیچ سرور ایرانی در دسترسی نبود — آدرس‌ها و اینترنت را بررسی کنید.")
            self.banner.show()
            return
        ranked.sort(key=lambda x: x[1])
        best, score = ranked[0]
        res = self.results[best.id]
        self.banner.setText(
            f"🏆 پیشنهاد برای استریم روی Kick: {best.name}\n"
            f"پینگ {res['ping']:.0f} میلی‌ثانیه • اتصال TCP: {res['tcp']:.0f} میلی‌ثانیه"
            + (f" • افت بسته: {res['loss']:.0f}٪" if res.get("loss") else "")
            + "\nاین آدرس را در Meld/OBS به‌عنوان سرور RTMP وارد کنید."
        )
        self.banner.show()

    # -- مدیریت سرورها -------------------------------------------------------
    def add_server(self):
        dlg = ServerDialog(self)
        if dlg.exec():
            self.servers.append(dlg.get_server())
            save_servers(self.servers)
            self.refresh_table()

    def edit_server(self):
        srv = self.selected_server()
        if not srv:
            QMessageBox.information(self, "ویرایش", "اول یک سرور را از جدول انتخاب کنید.")
            return
        dlg = ServerDialog(self, srv)
        if dlg.exec():
            dlg.get_server(srv)
            save_servers(self.servers)
            self.refresh_table()

    def delete_server(self):
        srv = self.selected_server()
        if not srv:
            QMessageBox.information(self, "حذف", "اول یک سرور را از جدول انتخاب کنید.")
            return
        ans = QMessageBox.question(self, "حذف", f"«{srv.name}» حذف شود؟",
                                   QMessageBox.Yes | QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.servers = [s for s in self.servers if s.id != srv.id]
            self.results.pop(srv.id, None)
            save_servers(self.servers)
            self.refresh_table()

    def import_servers(self):
        dlg = ImportDialog(self)
        if dlg.exec():
            new = dlg.get_servers()
            if new:
                self.servers.extend(new)
                save_servers(self.servers)
                self.refresh_table()
                QMessageBox.information(self, "درون‌ریزی", f"{len(new)} سرور اضافه شد.")
            else:
                QMessageBox.warning(self, "درون‌ریزی", "خط معتبری پیدا نشد.")

    def reset_defaults(self):
        ans = QMessageBox.question(
            self, "بازنشانی",
            "لیست به حالت پیش‌فرض برگردد؟ (تغییرات شما پاک می‌شود)",
            QMessageBox.Yes | QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.servers = default_server_list()
            self.results = {}
            self.banner.hide()
            save_servers(self.servers)
            self.refresh_table()

    def copy_rtmp(self):
        srv = self.selected_server()
        if not srv:
            QMessageBox.information(self, "کپی", "اول یک سرور را انتخاب کنید.")
            return
        text = srv.rtmp_url or (f"rtmp://{srv.host}:{srv.port}/live" if srv.host else "")
        if not text:
            QMessageBox.information(self, "کپی", "این سرور آدرسی ندارد.")
            return
        QApplication.clipboard().setText(text)
        self.status_label.setText("✅ آدرس در حافظه کپی شد")


# ----------------------------------------------------------------------------
# اجرا
# ----------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
