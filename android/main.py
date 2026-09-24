# -*- coding: utf-8 -*-
# StreamScanner — Android (Kivy) edition
# Copyright (c) 2026 thaarfknight-star. All rights reserved.
# Source-available, NOT open-source: viewing permitted; copying, modification,
# redistribution or reuse prohibited without written permission. See LICENSE.
"""
نسخه اندروید StreamScanner با Kivy و رابط موبایل‌محور:
نوار بالای برنامه، دکمه بزرگ اسکن، کارت بهترین سرور، لیست کارتی سرورها،
نوار پایین اکشن‌ها، تست موازی سرورها (TCP-محور)، تشخیص خودکار نام/منطقه،
افزودن/ویرایش/حذف، درون‌ریزی گروهی، ۹ تم با اعمال لحظه‌ای، دوزبانه فارسی/انگلیسی،
دابل‌تاپ=کپی آدرس، و آپدیت درون‌برنامه‌ای (دانلود APK و پیشنهاد نصب).
"""
import json
import os
import re
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
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


def ping_color(ping_ms, pal):
    """رنگ وضعیت بر اساس پینگ: خوب=سبز تم، متوسط=کهربایی، بد/قطع=قرمز."""
    if ping_ms is None:
        return pal["subtext"]
    if ping_ms < 200:
        return pal["accent"]
    if ping_ms < 600:
        return "#ffb300"
    return pal["danger"]


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
    def __init__(self, bg=(0, 0, 0, 1), radius=0, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._color = Color(*bg)
            if radius:
                self._rect = RoundedRectangle(pos=self.pos, size=self.size,
                                              radius=[radius])
            else:
                self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_bg(self, bg):
        self._color.rgba = bg


class Chip(Label):
    """برچسب کوچک گردگوشه (منطقه، نشان بهترین). عرض خودکار از روی متن."""

    def __init__(self, bg=(1, 1, 1, 0.08), fg=(1, 1, 1, 1), **kw):
        kw.setdefault("size_hint", (None, None))
        kw.setdefault("height", dp(26))
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(**kw)
        self._pad = dp(12)
        self._hidden = False
        with self.canvas.before:
            self._c = Color(*bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size,
                                       radius=[dp(13)])
        self.bind(pos=self._u, size=self._u, texture_size=self._fit)
        self.bind(size=lambda i, s: setattr(i, "text_size", s))
        self._c.rgba = bg
        self.color = fg

    def _u(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size

    def _fit(self, *a):
        if self._hidden:
            self.width = 0
        else:
            self.width = self.texture_size[0] + self._pad * 2

    def set_colors(self, bg, fg=None):
        self._c.rgba = bg
        if fg is not None:
            self.color = fg

    def set_hidden(self, h):
        self._hidden = h
        self.opacity = 0 if h else 1
        if h:
            self.width = 0
        else:
            self._fit()


class PillButton(ButtonBehavior, BGBox):
    """دکمه گردگوشه موبایلی با رنگ‌بندی تم."""

    def __init__(self, app, text="", kind="primary", font_sp=16, **kw):
        self.app = app
        self._kind = kind
        self._disabled_flag = False
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(56))
        super().__init__(bg=(0, 0, 0, 0), radius=dp(14), **kw)
        self.label = Label(text=text, font_name=FONT, font_size=sp(font_sp),
                           halign="center", valign="middle")
        self.label.bold = True
        self.label.bind(size=lambda i, s: setattr(i, "text_size", s))
        self.add_widget(self.label)
        self.repaint()

    @property
    def text(self):
        return self.label.text

    @text.setter
    def text(self, v):
        self.label.text = v

    def repaint(self):
        pal = self.app.pal
        k = self._kind
        if k == "primary":
            self.set_bg(kx(pal["accent_deep"]))
            self.label.color = (1, 1, 1, 1)
        elif k == "danger":
            self.set_bg(kx(pal["danger"]))
            self.label.color = (1, 1, 1, 1)
        elif k == "ghost":
            self.set_bg(kx(pal["ghost_bg"]))
            self.label.color = kx(pal["ghost_text"])
        elif k == "white":
            self.set_bg((1, 1, 1, 1))
            self.label.color = kx(pal["accent_deep"])
        if self._disabled_flag:
            self.set_bg(kx(pal["disabled_bg"]))
            self.label.color = kx(pal["disabled_text"])

    def set_disabled(self, d):
        self._disabled_flag = d
        self.repaint()


class ServerRow(ButtonBehavior, BGBox):
    """یک ردیف کارتی سرور: نام + برچسب منطقه + خط وضعیت."""

    def __init__(self, app, server, **kw):
        self.app = app
        self.server_id = server.id
        super().__init__(orientation="vertical", bg=(0, 0, 0, 0),
                         radius=dp(14),
                         padding=[dp(14), dp(10), dp(14), dp(10)],
                         spacing=dp(2), size_hint_y=None, height=dp(94),
                         **kw)
        # حاشیه انتخاب
        with self.canvas.after:
            self._bcolor = Color(0, 0, 0, 0)
            self._border = Line(rounded_rectangle=(0, 0, 0, 0, dp(14)),
                                width=dp(1.5))
        self.bind(pos=self._ub, size=self._ub)

        top = BoxLayout(orientation="horizontal", size_hint_y=None,
                        height=dp(32), spacing=dp(8))
        self.region_chip = Chip(font_name=FONT, font_size=sp(12))
        self.best_chip = Chip(font_name=FONT, font_size=sp(12),
                              text=fa(T("best_badge")))
        self.name_lb = Label(font_name=FONT, font_size=sp(17),
                             halign="right", valign="middle", size_hint_x=1)
        self.name_lb.bold = True
        self.name_lb.bind(size=lambda i, s: setattr(i, "text_size",
                                                    (s[0], s[1])))
        # ترتیب چیدمان برای RTL: برچسب‌ها سمت چپ، نام سمت راست
        top.add_widget(self.region_chip)
        top.add_widget(self.best_chip)
        top.add_widget(self.name_lb)
        self.add_widget(top)

        self.status_lb = Label(font_name=FONT, font_size=sp(13),
                               halign="right", valign="middle",
                               size_hint_y=None, height=dp(26))
        self.status_lb.bind(size=lambda i, s: setattr(i, "text_size",
                                                      (s[0], s[1])))
        self.add_widget(self.status_lb)

        self.bind(on_press=self._on_press)
        self.refresh_content()
        self.set_selected(False)

    def _ub(self, *a):
        self._border.rounded_rectangle = (self.x, self.y, self.width,
                                          self.height, dp(14))

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and getattr(
                touch, "is_double_tap", False):
            self.app.copy_server(self.server_id)
            return True
        return super().on_touch_down(touch)

    def _on_press(self, *a):
        self.app.select_server(self.server_id)

    def set_selected(self, on):
        pal = self.app.pal
        if on:
            r, g, b, _a = kx(pal["accent"])
            self._color.rgba = (r, g, b, 0.22)
            self._bcolor.rgba = kx(pal["accent"])
        else:
            self._color.rgba = kx(pal["surface"])
            self._bcolor.rgba = (0, 0, 0, 0)

    def apply_theme(self):
        pal = self.app.pal
        self.name_lb.color = kx(pal["text"])
        self.region_chip.set_colors(kx(pal["ghost_bg"]), kx(pal["subtext"]))
        self.best_chip.set_colors(kx(pal["accent"]), kx(pal["on_accent"]))
        self.refresh_content()

    def refresh_content(self):
        app = self.app
        pal = app.pal
        s = next((x for x in app.servers if x.id == self.server_id), None)
        if s is None:
            return
        self.name_lb.text = fa(s.name)
        self.region_chip.text = fa(region_name(s.region))
        best = bool(app._best and app._best.get("id") == s.id)
        self.best_chip.set_hidden(not best)
        r = app.last_results.get(s.id)
        if r:
            if r.get("ok"):
                pm, tm = r.get("ping_ms"), r.get("tcp_ms")
                ptxt = "%dms" % pm if pm is not None else "—"
                ttxt = "%dms" % tm if tm is not None else "—"
                self.status_lb.text = fa("پینگ %s • tcp %s • وصل"
                                         % (ptxt, ttxt))
                self.status_lb.color = kx(ping_color(pm, pal))
            else:
                self.status_lb.text = fa("پاسخی دریافت نشد • قطع")
                self.status_lb.color = kx(pal["danger"])
        else:
            self.status_lb.text = ui("not_scanned")
            self.status_lb.color = kx(pal["subtext"])


# ----------------------------------------------------------------------------
# صفحه اصلی
# ----------------------------------------------------------------------------

class MainScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="main", **kw)
        self.app = app
        self.rows = {}
        root = BGBox(orientation="vertical", padding=0, spacing=0)
        self.root = root

        # ـــ نوار بالای برنامه ـــ
        bar = BGBox(orientation="horizontal", size_hint_y=None, height=dp(64),
                    padding=[dp(16), dp(10), dp(16), dp(10)], spacing=dp(8))
        self.bar = bar
        self.count_lb = app.L("", size=13, align="left",
                              size_hint_x=None, width=dp(110))
        title_box = BoxLayout(orientation="vertical", size_hint_x=None,
                              width=dp(230))
        self.title = app.L(APP_NAME, size=20, bold=True, align="right")
        self.subtitle = app.L(ui("subtitle"), size=12, align="right")
        title_box.add_widget(self.title)
        title_box.add_widget(self.subtitle)
        # ترتیب چیدمان برای RTL: شمارنده سمت چپ، عنوان سمت راست
        bar.add_widget(self.count_lb)
        bar.add_widget(BoxLayout(size_hint_x=1))
        bar.add_widget(title_box)
        root.add_widget(bar)

        self.progress = ProgressBar(max=100, size_hint_y=None, height=dp(6),
                                    opacity=0)
        root.add_widget(self.progress)

        # ـــ دکمه بزرگ اسکن ـــ
        scan_wrap = BGBox(padding=[dp(16), dp(12), dp(16), dp(6)],
                          size_hint_y=None, height=dp(80))
        self.scan_btn = app.PB(ui("scan_all"), kind="primary", font_sp=17,
                               size_hint_y=None, height=dp(58))
        self.scan_btn.bind(on_press=lambda *a: self.run_scan())
        scan_wrap.add_widget(self.scan_btn)
        root.add_widget(scan_wrap)

        # ـــ کارت بهترین سرور (مخفی در ابتدا) ـــ
        self.best_wrap = BGBox(padding=[dp(16), dp(6), dp(16), dp(6)],
                               size_hint_y=None, height=0, opacity=0)
        self.best_card = BGBox(orientation="vertical", radius=dp(16),
                               padding=dp(16), spacing=dp(6))
        self.best_title = app.L(ui("best_server_lbl"), size=13, align="right")
        self.best_name = app.L("", size=20, bold=True, align="right")
        self.best_info = app.L("", size=14, align="right")
        self.best_copy = app.PB(ui("copy_rtmp"), kind="white", font_sp=15,
                                size_hint_y=None, height=dp(48))
        self.best_copy.bind(on_press=lambda *a: app.copy_best())
        for w in (self.best_title, self.best_name, self.best_info,
                  self.best_copy):
            self.best_card.add_widget(w)
        self.best_wrap.add_widget(self.best_card)
        root.add_widget(self.best_wrap)

        self.hint = app.L(ui("tap_select_hint"), size=12, align="center",
                          size_hint_y=None, height=dp(28))
        root.add_widget(self.hint)

        scroll = ScrollView(size_hint_y=1)
        self.rows_box = BoxLayout(orientation="vertical", spacing=dp(10),
                                  size_hint_y=None,
                                  padding=[dp(16), dp(4), dp(16), dp(16)])
        self.rows_box.bind(minimum_height=self.rows_box.setter("height"))
        scroll.add_widget(self.rows_box)
        root.add_widget(scroll)

        self.status = app.L("", size=13, align="center",
                            size_hint_y=None, height=dp(32))
        root.add_widget(self.status)

        self.divider = BGBox(size_hint_y=None, height=dp(1))
        root.add_widget(self.divider)

        # ـــ نوار پایین ـــ
        bottom = BGBox(orientation="horizontal", size_hint_y=None,
                       height=dp(68),
                       padding=[dp(6), dp(10), dp(6), dp(10)], spacing=dp(2))
        self.bottom = bottom
        self.settings_btn = app.B(ui("settings"), "bar", size=13)
        self.settings_btn.bind(on_press=lambda *a: app.go("settings"))
        self.import_btn = app.B(ui("import"), "bar", size=13)
        self.import_btn.bind(on_press=lambda *a: app.go("import"))
        self.del_btn = app.B(ui("delete"), "bar_danger", size=14)
        self.del_btn.bind(on_press=lambda *a: app.delete_selected())
        self.edit_btn = app.B(ui("edit"), "bar", size=14)
        self.edit_btn.bind(on_press=lambda *a: app.edit_selected())
        self.add_btn = app.B(ui("add"), "bar", size=14)
        self.add_btn.bind(on_press=lambda *a: app.open_form(None))
        # ترتیب برای RTL: اولین اکشن سمت راست
        for b in (self.settings_btn, self.import_btn, self.del_btn,
                  self.edit_btn, self.add_btn):
            bottom.add_widget(b)
        self.bar_btns = [self.settings_btn, self.import_btn, self.del_btn,
                         self.edit_btn, self.add_btn]
        root.add_widget(bottom)

        self.add_widget(root)
        self.refresh_rows()

    # -- تم --
    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.root.set_bg(kx(pal["bg"]))
        self.bar.set_bg(kx(pal["accent_deep"]))
        self.title.color = (1, 1, 1, 1)
        self.subtitle.color = (1, 1, 1, 0.75)
        self.count_lb.color = (1, 1, 1, 0.85)
        self.best_card.set_bg(kx(pal["accent_deep"]))
        self.best_title.color = (1, 1, 1, 0.85)
        self.best_name.color = (1, 1, 1, 1)
        self.best_info.color = (1, 1, 1, 0.9)
        self.hint.color = kx(pal["subtext"])
        self.status.color = kx(pal["subtext"])
        self.divider.set_bg(kx(pal["input_border"]))
        self.bottom.set_bg(kx(pal["surface"]))
        self.scan_btn.repaint()
        self.best_copy.repaint()
        for b in self.bar_btns:
            app.paint_btn(b, "bar_danger" if b is self.del_btn else "bar")
        for row in self.rows.values():
            row.set_selected(row.server_id == app.selected_id)
            row.apply_theme()
        self._update_count()
        if app._best:
            srv = next((s for s in app.servers
                        if s.id == app._best.get("id")), None)
            self.show_best(app._best, srv)
        else:
            self.hide_best()

    # -- لیست --
    def _update_count(self):
        self.count_lb.text = fa("%d %s" % (len(self.app.servers),
                                           T("server_word")))

    def refresh_selection(self):
        for sid, row in self.rows.items():
            row.set_selected(sid == self.app.selected_id)

    def refresh_rows(self):
        app = self.app
        self.rows_box.clear_widgets()
        self.rows = {}
        if not app.servers:
            box = BoxLayout(orientation="vertical", size_hint_y=None,
                            height=dp(320), spacing=dp(8),
                            padding=[0, dp(70), 0, 0])
            t1 = app.L(ui("no_servers"), size=18, bold=True, align="center")
            t2 = app.L(ui("no_servers_hint"), size=14, align="center")
            box.add_widget(t1)
            box.add_widget(t2)
            self.rows_box.add_widget(box)
            self.hint.opacity = 0
        else:
            self.hint.opacity = 1
            for s in app.servers:
                row = ServerRow(app, s)
                row.set_selected(s.id == app.selected_id)
                self.rows_box.add_widget(row)
                self.rows[s.id] = row
        self._update_count()

    def refresh_results(self):
        for row in self.rows.values():
            row.refresh_content()

    def show_status(self, msg, secs=3):
        self.status.text = fa(msg)
        Clock.unschedule(self._clear_status)
        Clock.schedule_once(self._clear_status, secs)

    def _clear_status(self, dt):
        self.status.text = ""

    # -- کارت بهترین سرور --
    def show_best(self, best, srv):
        name = srv.name if srv else best.get("name", "")
        region = srv.region if srv else best.get("region", "")
        pm, tm = best.get("ping_ms"), best.get("tcp_ms")
        ptxt = "%dms" % pm if pm is not None else "—"
        ttxt = "%dms" % tm if tm is not None else "—"
        self.best_name.text = fa(name)
        self.best_info.text = fa("%s • پینگ %s • tcp %s"
                                 % (region_name(region), ptxt, ttxt))
        self.best_wrap.height = dp(196)
        self.best_wrap.opacity = 1

    def hide_best(self):
        self.best_wrap.height = 0
        self.best_wrap.opacity = 0

    # -- اسکن --
    def run_scan(self):
        app = self.app
        if app.scanning:
            return
        if not app.servers:
            self.show_status(T("add_first"))
            return
        app.scanning = True
        self.scan_btn.set_disabled(True)
        self.hide_best()
        self.progress.opacity = 1
        self.progress.value = 0
        self.progress.max = len(app.servers)
        self.show_status(T("scanning"), secs=60)
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
        self.scan_btn.set_disabled(False)
        self.progress.opacity = 0
        for r in results:
            if r and r.get("id"):
                app.last_results[r["id"]] = r
        self.refresh_results()
        ok_results = [r for r in results if r and r.get("ok")]
        if not ok_results:
            self.show_status(T("no_server"), secs=5)
            return
        best = min(ok_results, key=lambda r: r["score"])
        srv = next((s for s in app.servers if s.id == best["id"]), None)
        app._best = best
        self.show_best(best, srv)
        self.refresh_results()
        self.show_status(T("scan"), secs=2)


# ----------------------------------------------------------------------------
# فرم سرور
# ----------------------------------------------------------------------------

class ServerFormScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="server_form", **kw)
        self.app = app
        self.editing = None
        self._name_touched = False
        outer = BGBox(orientation="vertical", padding=0, spacing=0)
        self.outer = outer

        bar = BGBox(orientation="horizontal", size_hint_y=None, height=dp(56),
                    padding=[dp(16), dp(8), dp(16), dp(8)])
        self.bar = bar
        self.back_btn = app.B(ui("back"), "bar", size=14,
                              size_hint=(None, None), width=dp(90),
                              height=dp(40))
        self.back_btn.bind(on_press=lambda *a: app.go("main"))
        self.title = app.L("", size=19, bold=True, align="right")
        bar.add_widget(self.back_btn)
        bar.add_widget(BoxLayout(size_hint_x=1))
        bar.add_widget(self.title)
        outer.add_widget(bar)

        scroll = ScrollView(size_hint_y=1)
        root = BGBox(orientation="vertical", padding=dp(16), spacing=dp(10),
                     size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))
        self.root = root
        self.name_lb = app.L(ui("server_name"), size=14,
                             size_hint_y=None, height=dp(28))
        self.name_ti = app.TI(hint=T("ex_name"))
        self.name_ti.bind(text=self._on_name)
        self.url_lb = app.L(ui("rtmp_addr"), size=14,
                            size_hint_y=None, height=dp(28))
        self.url_ti = app.TI(hint="rtmp://host:1935/live", ltr=True)
        self.url_ti.bind(text=self._on_url)
        self.region_lb = app.L(ui("region"), size=14,
                               size_hint_y=None, height=dp(28))
        self.region_sp = app.SP([], "")
        self.note_lb = app.L(ui("note"), size=14,
                             size_hint_y=None, height=dp(28))
        self.note_ti = app.TI(hint=T("optional_note"))
        self.hint = app.L(ui("auto_hint"), size=12,
                          size_hint_y=None, height=dp(60))
        for w in (self.name_lb, self.name_ti, self.url_lb, self.url_ti,
                  self.region_lb, self.region_sp, self.note_lb, self.note_ti,
                  self.hint):
            root.add_widget(w)
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(56))
        self.save_btn = app.PB(ui("save"), kind="primary", font_sp=16)
        self.save_btn.bind(on_press=lambda *a: self.save())
        self.cancel_btn = app.PB(ui("cancel"), kind="ghost", font_sp=16)
        self.cancel_btn.bind(on_press=lambda *a: app.go("main"))
        row.add_widget(self.cancel_btn)
        row.add_widget(self.save_btn)
        root.add_widget(row)
        scroll.add_widget(root)
        outer.add_widget(scroll)
        self.add_widget(outer)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.outer.set_bg(kx(pal["bg"]))
        self.bar.set_bg(kx(pal["accent_deep"]))
        self.title.color = (1, 1, 1, 1)
        app.paint_btn(self.back_btn, "bar")
        self.back_btn.color = (1, 1, 1, 1)
        for lb in (self.name_lb, self.url_lb, self.region_lb, self.note_lb):
            lb.color = kx(pal["text"])
        self.hint.color = kx(pal["subtext"])
        for ti in (self.name_ti, self.url_ti, self.note_ti):
            app.paint_input(ti)
        app.paint_spinner(self.region_sp)
        self.save_btn.repaint()
        self.cancel_btn.repaint()

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


# ----------------------------------------------------------------------------
# درون‌ریزی گروهی
# ----------------------------------------------------------------------------

class ImportScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="import", **kw)
        self.app = app
        outer = BGBox(orientation="vertical", padding=0, spacing=0)
        self.outer = outer

        bar = BGBox(orientation="horizontal", size_hint_y=None, height=dp(56),
                    padding=[dp(16), dp(8), dp(16), dp(8)])
        self.bar = bar
        self.back_btn = app.B(ui("back"), "bar", size=14,
                              size_hint=(None, None), width=dp(90),
                              height=dp(40))
        self.back_btn.bind(on_press=lambda *a: (setattr(self.text_ti, "text", ""),
                                                app.go("main")))
        self.title = app.L(ui("import_title"), size=19, bold=True, align="right")
        bar.add_widget(self.back_btn)
        bar.add_widget(BoxLayout(size_hint_x=1))
        bar.add_widget(self.title)
        outer.add_widget(bar)

        root = BGBox(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.root = root
        self.hint = app.L(ui("import_hint"), size=13,
                          size_hint_y=None, height=dp(64))
        self.text_ti = app.TI(hint="IR1 | rtmp://ir1.example.com:1935/live",
                              multiline=True, ltr=True)
        self.text_ti.size_hint_y = 1
        root.add_widget(self.hint)
        root.add_widget(self.text_ti)
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(56))
        self.do_btn = app.PB(ui("do_import"), kind="primary", font_sp=16)
        self.do_btn.bind(on_press=lambda *a: self.do_import())
        self.cancel_btn = app.PB(ui("cancel"), kind="ghost", font_sp=16)
        self.cancel_btn.bind(on_press=lambda *a: (setattr(self.text_ti, "text", ""),
                                                 app.go("main")))
        row.add_widget(self.cancel_btn)
        row.add_widget(self.do_btn)
        root.add_widget(row)
        self.status = app.L("", size=12, align="center",
                            size_hint_y=None, height=dp(28))
        root.add_widget(self.status)
        outer.add_widget(root)
        self.add_widget(outer)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.outer.set_bg(kx(pal["bg"]))
        self.bar.set_bg(kx(pal["accent_deep"]))
        self.title.color = (1, 1, 1, 1)
        app.paint_btn(self.back_btn, "bar")
        self.back_btn.color = (1, 1, 1, 1)
        self.hint.color = kx(pal["subtext"])
        self.status.color = kx(pal["subtext"])
        app.paint_input(self.text_ti)
        self.do_btn.repaint()
        self.cancel_btn.repaint()

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
        Clock.schedule_once(lambda dt: self._finish(), 1.2)

    def _finish(self):
        self.text_ti.text = ""
        self.status.text = ""
        self.app.go("main")


# ----------------------------------------------------------------------------
# تنظیمات
# ----------------------------------------------------------------------------

class SettingsScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="settings", **kw)
        self.app = app
        self.orig_theme = app.theme
        outer = BGBox(orientation="vertical", padding=0, spacing=0)
        self.outer = outer

        bar = BGBox(orientation="horizontal", size_hint_y=None, height=dp(56),
                    padding=[dp(16), dp(8), dp(16), dp(8)])
        self.bar = bar
        self.back_btn = app.B(ui("back"), "bar", size=14,
                              size_hint=(None, None), width=dp(90),
                              height=dp(40))
        self.back_btn.bind(on_press=lambda *a: self.cancel())
        self.title = app.L(ui("settings"), size=19, bold=True, align="right")
        bar.add_widget(self.back_btn)
        bar.add_widget(BoxLayout(size_hint_x=1))
        bar.add_widget(self.title)
        outer.add_widget(bar)

        scroll = ScrollView(size_hint_y=1)
        root = BGBox(orientation="vertical", padding=dp(16), spacing=dp(12),
                     size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))
        self.root = root
        self.theme_lb = app.L(ui("theme_label"), size=14,
                              size_hint_y=None, height=dp(28))
        self.theme_sp = app.SP([], "", size=14)
        self.theme_sp.bind(text=self._on_theme_text)
        self.lang_lb = app.L(ui("lang_label"), size=14,
                             size_hint_y=None, height=dp(28))
        self.lang_sp = app.SP(["فارسی", "English"], "فارسی", size=14)
        self.auto_lb = app.L(ui("autocheck"), size=14)
        self.auto_cb = CheckBox(size_hint=(None, None),
                                size=(dp(48), dp(48)))
        auto_row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        auto_row.add_widget(self.auto_cb)
        auto_row.add_widget(self.auto_lb)
        self.ver_lb = app.L("", size=13, size_hint_y=None, height=dp(28))
        self.check_btn = app.PB(ui("check_update"), kind="ghost", font_sp=15,
                                size_hint_y=None, height=dp(54))
        self.check_btn.bind(on_press=lambda *a: self._check_update())
        self.upd_status = app.L("", size=12, align="center",
                                size_hint_y=None, height=dp(28))
        for w in (self.theme_lb, self.theme_sp, self.lang_lb, self.lang_sp):
            root.add_widget(w)
        root.add_widget(auto_row)
        root.add_widget(self.ver_lb)
        root.add_widget(self.check_btn)
        root.add_widget(self.upd_status)
        row = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(56))
        self.save_btn = app.PB(ui("save"), kind="primary", font_sp=16)
        self.save_btn.bind(on_press=lambda *a: self.save())
        self.cancel_btn = app.PB(ui("cancel"), kind="ghost", font_sp=16)
        self.cancel_btn.bind(on_press=lambda *a: self.cancel())
        row.add_widget(self.cancel_btn)
        row.add_widget(self.save_btn)
        root.add_widget(row)
        scroll.add_widget(root)
        outer.add_widget(scroll)
        self.add_widget(outer)

    def apply_theme(self):
        app, pal = self.app, self.app.pal
        self.outer.set_bg(kx(pal["bg"]))
        self.bar.set_bg(kx(pal["accent_deep"]))
        self.title.color = (1, 1, 1, 1)
        app.paint_btn(self.back_btn, "bar")
        self.back_btn.color = (1, 1, 1, 1)
        for lb in (self.theme_lb, self.lang_lb, self.auto_lb, self.ver_lb):
            lb.color = kx(pal["text"])
        self.upd_status.color = kx(pal["subtext"])
        app.paint_spinner(self.theme_sp)
        app.paint_spinner(self.lang_sp)
        self.check_btn.repaint()
        self.save_btn.repaint()
        self.cancel_btn.repaint()

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


# ----------------------------------------------------------------------------
# صفحه آپدیت
# ----------------------------------------------------------------------------

class UpdateScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="update", **kw)
        self.app = app
        self.release = None
        root = BGBox(orientation="vertical", padding=dp(16), spacing=dp(10))
        self.root = root
        self.title = app.L(ui("new_version_title"), size=20, bold=True,
                           align="center", size_hint_y=None, height=dp(36))
        self.info = app.L("", size=14, align="center",
                          size_hint_y=None, height=dp(56))
        self.changes_lb = app.L(ui("changes"), size=14,
                                size_hint_y=None, height=dp(28))
        scroll = ScrollView(size_hint_y=1)
        self.body = app.L("", size=13)
        scroll.add_widget(self.body)
        self.dl_btn = app.PB(ui("dl_install_apk"), kind="primary", font_sp=16,
                             size_hint_y=None, height=dp(58))
        self.dl_btn.bind(on_press=lambda *a: self.download_and_install())
        self.later_btn = app.PB(ui("later"), kind="ghost", font_sp=15,
                                size_hint_y=None, height=dp(52))
        self.later_btn.bind(on_press=lambda *a: app.go("main"))
        self.status = app.L("", size=12, align="center",
                            size_hint_y=None, height=dp(40))
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
        self.dl_btn.repaint()
        self.later_btn.repaint()

    def show(self, release):
        self.release = release
        tag = release.get("tag_name", "")
        self.info.text = fa("%s %s %s (%s %s)" % (
            T("new_version"), tag, T("version_released"),
            T("your_version"), __version__))
        self.body.text = fa(release.get("body") or "—")
        self.status.text = ""
        self.dl_btn.set_disabled(False)
        self.app.go("update")

    def download_and_install(self):
        asset = find_apk_asset(self.release)
        if not asset:
            self.status.text = ui("file_not_found")
            return
        self.dl_btn.set_disabled(True)
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
        self.dl_btn.set_disabled(False)

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
    def L(self, text="", size=15, bold=False, align=None, color=None, **kw):
        lb = Label(text=text if isinstance(text, str) else str(text),
                   font_name=FONT, font_size=sp(size),
                   color=kx(color or self.pal.get("text", "#e9f2ec")), **kw)
        if bold:
            lb.bold = True
        lb.halign = align or ("right" if core.LANG == "fa" else "left")
        lb.valign = "middle"
        lb.bind(size=lambda inst, sz: setattr(inst, "text_size", (sz[0], None)))
        return lb

    def B(self, text="", kind="primary", size=15, **kw):
        b = Button(text=text, font_name=FONT, font_size=sp(size),
                   background_normal="", background_down="", **kw)
        b.bold = True
        self.paint_btn(b, kind)
        return b

    def PB(self, text="", kind="primary", font_sp=16, **kw):
        return PillButton(self, text=text, kind=kind, font_sp=font_sp, **kw)

    def paint_btn(self, b, kind):
        pal = self.pal
        if kind == "primary":
            b.background_color = kx(pal["accent_deep"])
            b.color = (1, 1, 1, 1)
        elif kind == "danger":
            b.background_color = kx(pal["danger"])
            b.color = (1, 1, 1, 1)
        elif kind == "bar":
            b.background_color = (0, 0, 0, 0)
            b.color = kx(pal["text"])
        elif kind == "bar_danger":
            b.background_color = (0, 0, 0, 0)
            b.color = kx(pal["danger"])
        else:
            b.background_color = kx(pal["ghost_bg"])
            b.color = kx(pal["ghost_text"])
        b.disabled_color = kx(pal["disabled_text"])

    def TI(self, text="", hint="", multiline=False, size=16, ltr=False,
           height=54):
        ti = TextInput(text=text, hint_text=fa(hint) if hint else "",
                       multiline=multiline, font_name=FONT,
                       font_size=sp(size), size_hint_y=None,
                       height=dp(height))
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

    def SP(self, values, text, size=15, height=54):
        sp_ = Spinner(text=text, values=values, font_name=FONT,
                      font_size=sp(size), background_normal="",
                      background_down="", size_hint_y=None,
                      height=dp(height))
        self.paint_spinner(sp_)
        return sp_

    def paint_spinner(self, sp_):
        pal = self.pal
        sp_.background_color = kx(pal["input_bg"])
        sp_.color = kx(pal["text"])

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

    def select_server(self, server_id):
        self.selected_id = server_id
        self.main_screen.refresh_selection()

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
        if self._best and self._best.get("id") == srv.id:
            self._best = None
            self.main_screen.hide_best()
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
