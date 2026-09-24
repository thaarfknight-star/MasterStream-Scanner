# -*- coding: utf-8 -*-
# StreamScanner — Android (Kivy) edition
# Copyright (c) 2026 thaarfknight-star. All rights reserved.
# Source-available, NOT open-source: viewing permitted; copying, modification,
# redistribution or reuse prohibited without written permission. See LICENSE.
"""
نسخه اندروید StreamScanner با Kivy؛ همان قابلیت‌های نسخه ویندوز:
تست موازی سرورها (TCP-محور)، تشخیص خودکار نام/منطقه، پیشنهاد بهترین سرور،
افزودن/ویرایش/حذف، درون‌ریزی گروهی، ۹ تم با اعمال لحظه‌ای، دوزبانه فارسی/انگلیسی،
دابل‌تاپ=کپی آدرس، و آپدیت درون‌برنامه‌ای (دانلود APK و پیشنهاد نصب).
"""
import os
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

import core
from core import (
    APP_NAME, DEFAULT_RTMP_PORT, REGIONS, REGION_UNKNOWN, THEME_PALETTES,
    THEMES, _REGION_FA2KEY, __version__, T, region_name, Server,
    server_rtmp_url, suggest_name, detect_region, parse_rtmp, probe_server,
    resolve_theme, fetch_latest_android_release, find_apk_asset, _ver_tuple,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(BASE_DIR, "assets", "fonts", "Vazirmatn-Regular.ttf")
if not os.path.exists(FONT):
    FONT = None

# ----------------------------------------------------------------------------
# متن فارسی: شکل‌دهی حروف + حذف ایموجی (فونت ایموجی ندارد)
# ----------------------------------------------------------------------------

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _SHAPE = True
except Exception:
    _SHAPE = False

_AR_RE = re.compile("[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_STRIP_CHARS = "⚡📥🗑✎＋🏆✅❌📋✓\ufe0f\u200d"


def clean(t):
    return "".join(c for c in str(t) if c not in _STRIP_CHARS).strip()


def fa(text):
    t = clean(text)
    if _SHAPE and _AR_RE.search(t):
        try:
            return get_display(arabic_reshaper.reshape(t))
        except Exception:
            return t
    return t


def ui(key):
    """متن نمایشی دوزبانه، شکل‌یافته و بدون ایموجی."""
    return fa(T(key))


def kx(hexcolor):
    h = hexcolor.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0, 1.0)


# ----------------------------------------------------------------------------
# کمک‌های اندروید (کلیپ‌بورد، دانلود، نصب APK)
# ----------------------------------------------------------------------------

def copy_text(text):
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        cm = act.getSystemService(act.CLIPBOARD_SERVICE)
        cd = autoclass("android.content.ClipData")
        cm.setPrimaryClip(cd.newPlainText("rtmp", text))
        return True
    except Exception:
        pass
    try:
        from plyer import clipboard
        clipboard.copy(text)
        return True
    except Exception:
        return False


def downloads_dir():
    try:
        from jnius import autoclass
        env = autoclass("android.os.Environment")
        return env.getExternalStoragePublicDirectory(
            env.DIRECTORY_DOWNLOADS).getAbsolutePath()
    except Exception:
        return os.path.expanduser("~/Download")


def is_system_dark():
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        cfg = act.getResources().getConfiguration()
        c = autoclass("android.content.res.Configuration")
        return (cfg.uiMode & c.UI_MODE_NIGHT_MASK) == c.UI_MODE_NIGHT_YES
    except Exception:
        return True


def install_apk(apk_path):
    """نصب APK از طریق PackageInstaller (بدون نیاز به FileProvider)."""
    from jnius import autoclass
    py_act = autoclass("org.kivy.android.PythonActivity")
    activity = py_act.mActivity
    installer = activity.getPackageManager().getPackageInstaller()
    params_cls = autoclass("android.content.pm.PackageInstaller$SessionParams")
    params = params_cls(params_cls.MODE_FULL_INSTALL)
    session_id = installer.createSession(params)
    session = installer.openSession(session_id)
    out = session.openWrite("package", 0, -1)
    with open(apk_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            out.write(chunk)
    session.fsync(out)
    out.close()
    intent = autoclass("android.content.Intent")(activity, py_act)
    pi_cls = autoclass("android.app.PendingIntent")
    flags = pi_cls.FLAG_UPDATE_CURRENT
    try:
        flags |= pi_cls.FLAG_MUTABLE
    except Exception:
        pass
    pi = pi_cls.getActivity(activity, session_id, intent, flags)
    session.commit(pi.getIntentSender())


# ----------------------------------------------------------------------------
# ویجت‌ها
# ----------------------------------------------------------------------------

class BGBox(BoxLayout):
    def __init__(self, bg=(0, 0, 0, 1), **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._color = Color(*bg)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_bg(self, bg):
        self._color.rgba = bg


class MainScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="main", **kw)
        self.app = app
        root = BGBox(orientation="vertical", padding=12, spacing=8)
        self.root = root

        self.title = app.L(APP_NAME, size=26, bold=True, align="center")
        self.subtitle = app.L(ui("subtitle"), size=13, align="center")
        root.add_widget(self.title)
        root.add_widget(self.subtitle)

        self.banner_box = BGBox(orientation="vertical", size_hint_y=None,
                                height=0, opacity=0)
        self.banner = app.L("", size=14, bold=True, align="center")
        self.banner_box.add_widget(self.banner)
        root.add_widget(self.banner_box)

        grid = GridLayout(cols=2, spacing=8, size_hint_y=None, height=184)
        self.scan_btn = app.B(ui("scan_all"), "primary")
        self.scan_btn.bind(on_press=lambda *a: self.run_scan())
        self.add_btn = app.B(ui("add"), "ghost")
        self.add_btn.bind(on_press=lambda *a: app.open_form(None))
        self.edit_btn = app.B(ui("edit"), "ghost")
        self.edit_btn.bind(on_press=lambda *a: app.edit_selected())
        self.del_btn = app.B(ui("delete"), "danger")
        self.del_btn.bind(on_press=lambda *a: app.delete_selected())
        self.import_btn = app.B(ui("bulk_import"), "ghost")
        self.import_btn.bind(on_press=lambda *a: app.go("import"))
        self.settings_btn = app.B(ui("settings"), "ghost")
        self.settings_btn.bind(on_press=lambda *a: app.go("settings"))
        for b in (self.scan_btn, self.add_btn, self.edit_btn,
                  self.del_btn, self.import_btn, self.settings_btn):
            grid.add_widget(b)
        root.add_widget(grid)

        self.progress = ProgressBar(max=100, size_hint_y=None, height=14,
                                    opacity=0)
        root.add_widget(self.progress)
        self.hint = app.L(ui("tap_select_hint"), size=11, align="center")
        root.add_widget(self.hint)

        scroll = ScrollView()
        self.rows_box = BoxLayout(orientation="vertical", spacing=6,
                                  size_hint_y=None)
        self.rows_box.bind(minimum_height=self.rows_box.setter("height"))
        scroll.add_widget(self.rows_box)
        root.add_widget(scroll)

        self.copy_btn = app.B(ui("copy_best"), "primary",
                              size_hint_y=None, height=52)
        self.copy_btn.bind(on_press=lambda *a: app.copy_best())
        self.copy_btn.disabled = True
        root.add_widget(self.copy_btn)

        self.status = app.L("", size=12, align="center")
        root.add_widget(self.status)

        self.row_btns = {}
        self.add_widget(root)
        self.refresh_rows()

    # -- تم --
    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        self.title.color = kx(pal["accent"])
        self.subtitle.color = kx(pal["subtext"])
        self.hint.color = kx(pal["subtext"])
        self.status.color = kx(pal["subtext"])
        self.banner_box.set_bg(kx(pal["accent"]))
        self.banner.color = kx(pal["on_accent"])
        app.paint_btn(self.scan_btn, "primary")
        app.paint_btn(self.copy_btn, "primary")
        app.paint_btn(self.add_btn, "ghost")
        app.paint_btn(self.edit_btn, "ghost")
        app.paint_btn(self.import_btn, "ghost")
        app.paint_btn(self.settings_btn, "ghost")
        app.paint_btn(self.del_btn, "danger")
        self.refresh_rows()

    # -- لیست --
    def row_text(self, s):
        app = self.app
        r = app.last_results.get(s.id)
        line1 = "%s (%s)" % (s.name, region_name(s.region))
        if r:
            ping = "%d ms" % r["ping_ms"] if r["ping_ms"] is not None else T("failed")
            tcp = "%d ms" % r["tcp_ms"] if r["tcp_ms"] is not None else T("down")
            st = T("up") if r["ok"] else T("down_emoji")
            line2 = "ping: %s | tcp: %s | %s" % (ping, tcp, st)
        else:
            line2 = "—"
        return fa(line1 + "\n" + clean(line2))

    def refresh_rows(self):
        app = self.app
        self.rows_box.clear_widgets()
        self.row_btns = {}
        for s in app.servers:
            b = app.B("", "ghost", size=14)
            b.size_hint_y = None
            b.height = 76
            b.halign = "right" if core.LANG == "fa" else "left"
            b.text = self.row_text(s)
            b.bind(size=self._fit_text)
            b._server_id = s.id
            b.bind(on_touch_down=self._row_touch)
            if s.id == app.selected_id:
                b.background_color = kx(app.pal["accent_deep"])
                b.color = kx(app.pal["btn_text"])
            self.rows_box.add_widget(b)
            self.row_btns[s.id] = b

    def _fit_text(self, inst, sz):
        inst.text_size = (sz[0] - 16, None)

    def _row_touch(self, btn, touch):
        if not btn.collide_point(*touch.pos):
            return False
        if touch.is_double_tap:
            self.app.copy_server(btn._server_id)
            return True
        self.app.selected_id = btn._server_id
        self.refresh_rows()
        return False

    def show_status(self, msg, secs=3):
        self.status.text = fa(msg)
        Clock.unschedule(self._clear_status)
        Clock.schedule_once(self._clear_status, secs)

    def _clear_status(self, dt):
        self.status.text = ""

    # -- بنر --
    def show_banner(self, text):
        self.banner.text = fa(text)
        self.banner_box.height = 64
        self.banner_box.opacity = 1

    def hide_banner(self):
        self.banner_box.height = 0
        self.banner_box.opacity = 0

    # -- اسکن --
    def run_scan(self):
        app = self.app
        if app.scanning:
            return
        if not app.servers:
            self.show_status(T("add_first"))
            return
        app.scanning = True
        self.scan_btn.disabled = True
        self.copy_btn.disabled = True
        self.hide_banner()
        self.progress.opacity = 1
        self.progress.value = 0
        self.progress.max = len(app.servers)
        self.show_status(T("scanning"), secs=30)
        snapshot = [asdict(s) for s in app.servers]
        threading.Thread(target=self._scan_worker, args=(snapshot,),
                         daemon=True).start()

    def _fail_result(self, s):
        return {"id": s.get("id"), "name": s.get("name"),
                "region": s.get("region"), "host": s.get("host"),
                "port": s.get("port"), "ping_ms": None, "loss": 100.0,
                "tcp_ms": None, "ok": False, "score": 1_000_000.0}

    def _scan_worker(self, snapshot):
        results = [None] * len(snapshot)
        with ThreadPoolExecutor(max_workers=min(16, len(snapshot))) as ex:
            futs = {ex.submit(probe_server, s): i
                    for i, s in enumerate(snapshot)}
            done = 0
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    results[i] = fut.result()
                except Exception:
                    results[i] = self._fail_result(snapshot[i])
                done += 1
                d = done
                Clock.schedule_once(
                    lambda dt, d=d: setattr(self.progress, "value", d), 0)
        Clock.schedule_once(lambda dt: self._scan_done(results), 0)

    def _scan_done(self, results):
        app = self.app
        app.scanning = False
        self.scan_btn.disabled = False
        self.progress.opacity = 0
        for r in results:
            if r and r.get("id"):
                app.last_results[r["id"]] = r
        self.refresh_rows()
        ok_results = [r for r in results if r and r.get("ok")]
        if not ok_results:
            self.show_status(T("no_server"), secs=5)
            return
        best = min(ok_results, key=lambda r: r["score"])
        srv = next((s for s in app.servers if s.id == best["id"]), None)
        name = srv.name if srv else best["name"]
        region = srv.region if srv else best.get("region", "")
        ping = "%d" % best["ping_ms"] if best["ping_ms"] is not None else "?"
        tcp = "%d" % best["tcp_ms"]
        self.show_banner("🏆 %s: %s (%s) — ping %sms، tcp %sms"
                         % (T("best_server_lbl"), name, region_name(region),
                            ping, tcp))
        app._best = best
        self.copy_btn.disabled = False
        self.show_status(T("scan") + " ✓", secs=2)


class ServerFormScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="server_form", **kw)
        self.app = app
        self.editing = None
        self._name_touched = False
        root = BGBox(orientation="vertical", padding=14, spacing=10)
        self.root = root
        self.title = app.L("", size=20, bold=True, align="center")
        root.add_widget(self.title)
        self.name_lb = app.L(ui("server_name"), size=14)
        self.name_ti = app.TI(hint=T("ex_name"))
        self.name_ti.bind(text=self._on_name)
        self.url_lb = app.L(ui("rtmp_addr"), size=14)
        self.url_ti = app.TI(hint="rtmp://host:1935/live", ltr=True)
        self.url_ti.bind(text=self._on_url)
        self.region_lb = app.L(ui("region"), size=14)
        self.region_sp = app.SP([], "", size=14)
        self.note_lb = app.L(ui("note"), size=14)
        self.note_ti = app.TI(hint=T("optional_note"))
        self.hint = app.L(ui("auto_hint"), size=12)
        for w in (self.name_lb, self.name_ti, self.url_lb, self.url_ti,
                  self.region_lb, self.region_sp, self.note_lb, self.note_ti,
                  self.hint):
            root.add_widget(w)
        row = BoxLayout(spacing=8, size_hint_y=None, height=52)
        self.save_btn = app.B(ui("save"), "primary")
        self.save_btn.bind(on_press=lambda *a: self.save())
        self.cancel_btn = app.B(ui("cancel"), "ghost")
        self.cancel_btn.bind(on_press=lambda *a: app.go("main"))
        row.add_widget(self.save_btn)
        row.add_widget(self.cancel_btn)
        root.add_widget(row)
        self.add_widget(root)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        for lb in (self.title, self.name_lb, self.url_lb, self.region_lb,
                   self.note_lb):
            lb.color = kx(pal["text"])
        self.title.color = kx(pal["accent"])
        self.hint.color = kx(pal["subtext"])
        for ti in (self.name_ti, self.url_ti, self.note_ti):
            app.paint_input(ti)
        app.paint_spinner(self.region_sp)
        app.paint_btn(self.save_btn, "primary")
        app.paint_btn(self.cancel_btn, "ghost")

    def open(self, server):
        self.editing = server
        self._name_touched = server is not None
        self.title.text = ui("edit_server") if server else ui("add_server")
        self.name_ti.text = server.name if server else ""
        self.url_ti.text = server_rtmp_url(server) if server else ""
        self.note_ti.text = server.note if server else ""
        vals = [fa(region_name(k)) for k in REGIONS]
        self.region_sp.values = vals
        key = (server.region if server and server.region in REGIONS
               else _REGION_FA2KEY.get(server.region if server else "",
                                       REGION_UNKNOWN))
        self.region_sp.text = fa(region_name(key))
        self.app.go("server_form")

    def _on_name(self, inst, val):
        self._name_touched = True

    def _on_url(self, inst, text):
        host, _p = parse_rtmp(text)
        if not host:
            return
        if not self._name_touched:
            self.name_ti.text = suggest_name(host)
            self._name_touched = False
        region = detect_region(host)
        if region != REGION_UNKNOWN:
            self.region_sp.text = fa(region_name(region))

    def _region_key(self):
        for k in REGIONS:
            if self.region_sp.text == fa(region_name(k)):
                return k
        return REGION_UNKNOWN

    def save(self):
        host, port = parse_rtmp(self.url_ti.text)
        name = self.name_ti.text.strip() or suggest_name(host) or T("server_word")
        region = self._region_key()
        note = self.note_ti.text.strip()
        if self.editing:
            self.editing.name, self.editing.host = name, host
            self.editing.port, self.editing.region = port, region
            self.editing.note = note
        else:
            self.app.servers.append(
                Server(name=name, host=host, port=port, region=region, note=note))
        self.app.save_settings()
        self.app.main_screen.refresh_rows()
        self.app.go("main")


class ImportScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="import", **kw)
        self.app = app
        root = BGBox(orientation="vertical", padding=14, spacing=10)
        self.root = root
        self.title = app.L(ui("import_title"), size=20, bold=True, align="center")
        self.hint = app.L(ui("import_hint"), size=13)
        self.text_ti = app.TI(hint="IR1 | rtmp://ir1.example.com:1935/live",
                              multiline=True, ltr=True)
        self.text_ti.size_hint_y = 1
        root.add_widget(self.title)
        root.add_widget(self.hint)
        root.add_widget(self.text_ti)
        row = BoxLayout(spacing=8, size_hint_y=None, height=52)
        self.do_btn = app.B(ui("do_import"), "primary")
        self.do_btn.bind(on_press=lambda *a: self.do_import())
        self.cancel_btn = app.B(ui("cancel"), "ghost")
        self.cancel_btn.bind(on_press=lambda *a: (setattr(self.text_ti, "text", ""), app.go("main")))
        row.add_widget(self.do_btn)
        row.add_widget(self.cancel_btn)
        root.add_widget(row)
        self.status = app.L("", size=12, align="center")
        root.add_widget(self.status)
        self.add_widget(root)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        self.title.color = kx(pal["accent"])
        self.hint.color = kx(pal["subtext"])
        self.status.color = kx(pal["subtext"])
        app.paint_input(self.text_ti)
        app.paint_btn(self.do_btn, "primary")
        app.paint_btn(self.cancel_btn, "ghost")

    def do_import(self):
        app = self.app
        new = []
        for line in self.text_ti.text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            name, url = [p.strip() for p in line.split("|", 1)]
            host, port = parse_rtmp(url)
            if not host:
                continue
            new.append(Server(name=name or suggest_name(host), host=host,
                              port=port, region=detect_region(host)))
        if new:
            app.servers.extend(new)
            app.save_settings()
            app.main_screen.refresh_rows()
            self.status.text = fa("%d %s" % (len(new), T("import_n")))
        else:
            self.status.text = ui("import_none")
        Clock.schedule_once(lambda dt: (setattr(self, "_done", True),
                                        self._finish()), 1.2)

    def _finish(self):
        self.text_ti.text = ""
        self.status.text = ""
        self.app.go("main")


class SettingsScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="settings", **kw)
        self.app = app
        self.orig_theme = app.theme
        root = BGBox(orientation="vertical", padding=14, spacing=10)
        self.root = root
        self.title = app.L(ui("settings"), size=20, bold=True, align="center")
        root.add_widget(self.title)

        self.theme_lb = app.L(ui("theme_label"), size=14)
        self.theme_sp = app.SP([], "", size=14)
        self.theme_sp.bind(text=self._on_theme_text)
        self.lang_lb = app.L(ui("lang_label"), size=14)
        self.lang_sp = app.SP(["فارسی", "English"], "فارسی", size=14)
        self.auto_lb = app.L(ui("autocheck"), size=14)
        self.auto_cb = CheckBox(size_hint=(None, None), size=(48, 48))
        auto_row = BoxLayout(size_hint_y=None, height=52)
        auto_row.add_widget(self.auto_lb)
        auto_row.add_widget(self.auto_cb)
        self.ver_lb = app.L("", size=13)
        self.check_btn = app.B(ui("check_update"), "ghost", size_hint_y=None, height=52)
        self.check_btn.bind(on_press=lambda *a: self._check_update())
        self.upd_status = app.L("", size=12)
        for w in (self.theme_lb, self.theme_sp, self.lang_lb, self.lang_sp):
            root.add_widget(w)
        root.add_widget(auto_row)
        root.add_widget(self.ver_lb)
        root.add_widget(self.check_btn)
        root.add_widget(self.upd_status)
        spacer = BoxLayout(size_hint_y=1)
        root.add_widget(spacer)
        row = BoxLayout(spacing=8, size_hint_y=None, height=52)
        self.save_btn = app.B(ui("save"), "primary")
        self.save_btn.bind(on_press=lambda *a: self.save())
        self.cancel_btn = app.B(ui("cancel"), "ghost")
        self.cancel_btn.bind(on_press=lambda *a: self.cancel())
        row.add_widget(self.save_btn)
        row.add_widget(self.cancel_btn)
        root.add_widget(row)
        self.add_widget(root)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        self.title.color = kx(pal["accent"])
        for lb in (self.theme_lb, self.lang_lb, self.auto_lb, self.ver_lb):
            lb.color = kx(pal["text"])
        self.upd_status.color = kx(pal["subtext"])
        app.paint_spinner(self.theme_sp)
        app.paint_spinner(self.lang_sp)
        app.paint_btn(self.check_btn, "ghost")
        app.paint_btn(self.save_btn, "primary")
        app.paint_btn(self.cancel_btn, "ghost")

    def on_pre_enter(self):
        app = self.app
        self.orig_theme = app.theme
        vals = [fa(T(THEMES[k])) for k in THEMES]
        self._theme_map = {fa(T(THEMES[k])): k for k in THEMES}
        self.theme_sp.values = vals
        self.theme_sp.text = fa(T(THEMES.get(app.theme, "dark")))
        self.theme_sp.unbind(text=self._on_theme_text)
        self.theme_sp.bind(text=self._on_theme_text)
        self.lang_sp.text = "فارسی" if app.lang == "fa" else "English"
        self.auto_cb.active = app.auto_check
        self.ver_lb.text = fa("%s %s" % (T("current_version"), __version__))
        self.upd_status.text = ""

    def _on_theme_text(self, inst, text):
        key = self._theme_map.get(text)
        if key:
            self.app.set_theme(key)

    def _check_update(self):
        self.upd_status.text = ui("checking")
        self.app.check_for_updates(manual=True, status_cb=self._upd_status_cb)

    def _upd_status_cb(self, msg):
        self.upd_status.text = fa(msg)

    def save(self):
        app = self.app
        app.theme = self._theme_map.get(self.theme_sp.text, app.theme)
        app.auto_check = self.auto_cb.active
        new_lang = "fa" if self.lang_sp.text == "فارسی" else "en"
        app.save_settings()
        if new_lang != app.lang:
            app.lang = new_lang
            app.save_settings()
            self.upd_status.text = ui("lang_restart")
            Clock.schedule_once(lambda dt: app.go("main"), 2.5)
        else:
            app.go("main")

    def cancel(self):
        self.app.set_theme(self.orig_theme)
        self.app.go("main")


class UpdateScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="update", **kw)
        self.app = app
        self.release = None
        root = BGBox(orientation="vertical", padding=14, spacing=10)
        self.root = root
        self.title = app.L(ui("new_version_title"), size=20, bold=True,
                           align="center")
        self.info = app.L("", size=14, align="center")
        self.changes_lb = app.L(ui("changes"), size=14)
        scroll = ScrollView(size_hint_y=1)
        self.body = app.L("", size=13)
        scroll.add_widget(self.body)
        self.dl_btn = app.B(ui("dl_install_apk"), "primary",
                            size_hint_y=None, height=56)
        self.dl_btn.bind(on_press=lambda *a: self.download_and_install())
        self.later_btn = app.B(ui("later"), "ghost",
                               size_hint_y=None, height=52)
        self.later_btn.bind(on_press=lambda *a: app.go("main"))
        self.status = app.L("", size=12, align="center")
        for w in (self.title, self.info, self.changes_lb, scroll,
                  self.dl_btn, self.later_btn, self.status):
            root.add_widget(w)
        self.add_widget(root)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        self.title.color = kx(pal["accent"])
        for lb in (self.info, self.changes_lb, self.body):
            lb.color = kx(pal["text"])
        self.status.color = kx(pal["subtext"])
        app.paint_btn(self.dl_btn, "primary")
        app.paint_btn(self.later_btn, "ghost")

    def show(self, release):
        self.release = release
        tag = release.get("tag_name", "")
        self.info.text = fa("%s %s %s (%s %s)" % (
            T("new_version"), tag, T("version_released"),
            T("your_version"), __version__))
        self.body.text = fa(release.get("body") or "—")
        self.status.text = ""
        self.dl_btn.disabled = False
        self.app.go("update")

    def download_and_install(self):
        asset = find_apk_asset(self.release)
        if not asset:
            self.status.text = ui("file_not_found")
            return
        self.dl_btn.disabled = True
        self.status.text = ui("downloading")
        threading.Thread(target=self._worker,
                         args=(asset,), daemon=True).start()

    def _worker(self, asset):
        url = asset.get("browser_download_url", "")
        tag = self.release.get("tag_name", "")
        dest = os.path.join(downloads_dir(),
                            "StreamScanner-%s.apk" % tag)
        try:
            req = urllib.request.Request(url,
                                         headers={"User-Agent": "StreamScanner-Android"})
            with urllib.request.urlopen(req, timeout=120) as r, \
                    open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length", 0) or 0)
                done = 0
                while True:
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        Clock.schedule_once(
                            lambda dt, p=pct: setattr(
                                self.status, "text",
                                fa("%s %d%%" % (T("downloading"), p))), 0)
        except Exception as e:
            Clock.schedule_once(
                lambda dt: self._fail("%s\n%s" % (T("download_failed"), e)), 0)
            return
        Clock.schedule_once(lambda dt: self._install(dest), 0)

    def _fail(self, msg):
        self.status.text = fa(msg)
        self.dl_btn.disabled = False

    def _install(self, dest):
        self.status.text = ui("installing")
        try:
            install_apk(dest)
            self.status.text = fa("%s\n%s" % (T("portable_saved"), dest))
        except Exception as e:
            self.status.text = fa("%s\n%s\n%s\n%s" % (
                T("install_failed"), T("allow_unknown"), T("install_manual"),
                dest))


# ----------------------------------------------------------------------------
# اپ
# ----------------------------------------------------------------------------

class StreamScannerApp(App):
    title = "StreamScanner"

    # -- کارخانه ویجت‌ها --
    def L(self, text="", size=15, bold=False, align=None, color=None):
        lb = Label(text=text if isinstance(text, str) else str(text),
                   font_name=FONT, font_size=size,
                   color=kx(color or self.pal.get("text", "#e9f2ec")))
        if bold:
            lb.bold = True
        lb.halign = align or ("right" if core.LANG == "fa" else "left")
        lb.valign = "middle"
        lb.bind(size=lambda inst, sz: setattr(inst, "text_size", (sz[0], None)))
        return lb

    def B(self, text="", kind="primary", size=15, **kw):
        b = Button(text=text, font_name=FONT, font_size=size,
                   background_normal="", background_down="", **kw)
        b.bold = True
        self.paint_btn(b, kind)
        return b

    def paint_btn(self, b, kind):
        pal = self.pal
        if kind == "primary":
            b.background_color = kx(pal["accent_deep"])
            b.color = kx(pal["btn_text"])
        elif kind == "danger":
            b.background_color = kx(pal["danger"])
            b.color = (1, 1, 1, 1)
        else:
            b.background_color = kx(pal["ghost_bg"])
            b.color = kx(pal["ghost_text"])
        b.disabled_color = kx(pal["disabled_text"])

    def TI(self, text="", hint="", multiline=False, size=15, ltr=False):
        ti = TextInput(text=text, hint_text=hint, multiline=multiline,
                       font_name=FONT, font_size=size)
        if ltr:
            ti.halign = "left"
        self.paint_input(ti)
        return ti

    def paint_input(self, ti):
        pal = self.pal
        ti.background_color = kx(pal["input_bg"])
        ti.foreground_color = kx(pal["text"])
        ti.hint_text_color = kx(pal["subtext"])
        ti.cursor_color = kx(pal["accent"])

    def SP(self, values, text, size=15):
        sp = Spinner(text=text, values=values, font_name=FONT, font_size=size,
                     background_normal="", background_down="")
        self.paint_spinner(sp)
        return sp

    def paint_spinner(self, sp):
        pal = self.pal
        sp.background_color = kx(pal["input_bg"])
        sp.color = kx(pal["text"])

    # -- چرخه --
    def build(self):
        self.pal = THEME_PALETTES["dark"]
        self.servers = []
        self.last_results = {}
        self.theme = "dark"
        self.lang = "fa"
        self.auto_check = True
        self.selected_id = None
        self.scanning = False
        self._best = None
        self.load_settings()
        self.sm = ScreenManager()
        self.main_screen = MainScreen(self)
        self.form_screen = ServerFormScreen(self)
        self.import_screen = ImportScreen(self)
        self.settings_screen = SettingsScreen(self)
        self.update_screen = UpdateScreen(self)
        for s in (self.main_screen, self.form_screen, self.import_screen,
                  self.settings_screen, self.update_screen):
            self.sm.add_widget(s)
        self.set_theme(self.theme)
        if self.auto_check:
            Clock.schedule_once(lambda dt: self.check_for_updates(), 2.5)
        return self.sm

    def go(self, name):
        self.sm.current = name

    # -- تم --
    def set_theme(self, theme):
        self.theme = theme
        resolved = resolve_theme(theme, system_dark=is_system_dark())
        self.pal = THEME_PALETTES[resolved]
        Window.clearcolor = kx(self.pal["bg"])
        for s in (self.main_screen, self.form_screen, self.import_screen,
                  self.settings_screen, self.update_screen):
            s.apply_theme()

    # -- ذخیره‌سازی --
    def data_file(self):
        return os.path.join(self.user_data_dir, "servers.json")

    def load_settings(self):
        try:
            with open(self.data_file(), encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("servers", []) if isinstance(data, dict) else data
            self.servers = [Server(**{k: v for k, v in s.items()
                                      if k in Server.__dataclass_fields__})
                            for s in items]
            if isinstance(data, dict):
                self.theme = data.get("theme", "dark")
                self.auto_check = data.get("auto_check_update", True)
                lang = data.get("lang", "fa")
                self.lang = lang if lang in ("fa", "en") else "fa"
            for sv in self.servers:
                if sv.region in _REGION_FA2KEY:
                    sv.region = _REGION_FA2KEY[sv.region]
                elif sv.region not in REGIONS:
                    sv.region = REGION_UNKNOWN
        except Exception:
            self.servers = []
        core.LANG = self.lang

    def save_settings(self):
        try:
            with open(self.data_file(), "w", encoding="utf-8") as f:
                json.dump({"servers": [asdict(s) for s in self.servers],
                           "theme": self.theme,
                           "auto_check_update": self.auto_check,
                           "lang": self.lang},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # -- عملیات سرور --
    def selected_server(self):
        for s in self.servers:
            if s.id == self.selected_id:
                return s
        return None

    def open_form(self, server):
        self.form_screen.open(server)

    def edit_selected(self):
        srv = self.selected_server()
        if not srv:
            self.main_screen.show_status(T("select_first"))
            return
        self.form_screen.open(srv)

    def delete_selected(self):
        srv = self.selected_server()
        if not srv:
            self.main_screen.show_status(T("select_first"))
            return
        self.servers.remove(srv)
        self.last_results.pop(srv.id, None)
        if self.selected_id == srv.id:
            self.selected_id = None
        self._best = None
        self.main_screen.copy_btn.disabled = True
        self.main_screen.hide_banner()
        self.save_settings()
        self.main_screen.refresh_rows()

    def copy_server(self, server_id):
        srv = next((s for s in self.servers if s.id == server_id), None)
        if not srv:
            return
        url = server_rtmp_url(srv)
        if url and copy_text(url):
            self.main_screen.show_status(T("dblclick_copied"))

    def copy_best(self):
        best = self._best
        if not best:
            return
        url = "rtmp://%s:%s/live" % (best["host"], best["port"])
        if copy_text(url):
            self.main_screen.show_status(
                "%s\n%s" % (T("rtmp_copied"), url), secs=4)

    # -- آپدیت --
    def check_for_updates(self, manual=False, status_cb=None):
        def worker():
            try:
                rel = fetch_latest_android_release()
            except Exception as e:
                if manual:
                    msg = "%s %s" % (T("update_err"), e)
                    Clock.schedule_once(
                        lambda dt: status_cb(msg) if status_cb else None, 0)
                return
            if rel and _ver_tuple(rel.get("tag_name", "")) > _ver_tuple(__version__):
                Clock.schedule_once(lambda dt: self.update_screen.show(rel), 0)
                if manual and status_cb:
                    tag = rel.get("tag_name", "")
                    Clock.schedule_once(
                        lambda dt: status_cb("%s %s %s" % (
                            T("new_version"), tag, T("update_avail"))), 0)
            elif manual and status_cb:
                Clock.schedule_once(
                    lambda dt: status_cb(T("update_latest")), 0)
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    StreamScannerApp().run()
