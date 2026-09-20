#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 余额悬浮窗（桌面小组件）

功能:
  * 悬浮在桌面 / 其他窗口最上层
  * 每 30 秒自动刷新余额（右键菜单 → 刷新间隔，可改可自定义并记住）
  * 实时显示当前计价时段（高峰 / 空闲半价）及下次切换时间
  * 左键按住拖拽移动位置
  * 双击立即刷新；右键菜单: 立即刷新 / 刷新间隔 / 更换 Key / 置顶 / 不透明度 / 退出

用法:
    方式一（推荐，无命令行窗口）: 双击 deepseek_balance_widget.pyw
    方式二: pythonw deepseek_balance_widget.py
    方式三: python deepseek_balance_widget.py   # 双击 .py 时黑窗会自动隐藏

    python deepseek_balance_widget.py --api-key sk-xxxxx --interval 30
    python deepseek_balance_widget.py --opacity 0.9 --no-topmost
    python deepseek_balance_widget.py --reset-key      # 清除本地保存的 Key

API Key 获取顺序: --api-key 参数 > 本地保存文件 (~/.deepseek/api_key) > 环境变量。
首次运行（三者都没有）会弹出输入框，勾选"记住 Key"即可保存到本地文件，无需系统环境变量。

接口文档: https://api-docs.deepseek.com/zh-cn/api/get-user-balance/
依赖: 仅 Python 标准库 (tkinter)，要求 Python 3.6+，无需 pip install。
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import tkinter as tk

import pricing  # 同目录模块: 峰谷时段 + 中国法定节假日判定

API_BASE = "https://api.deepseek.com"
BALANCE_ENDPOINT = "/user/balance"
DEFAULT_INTERVAL = 30
DEFAULT_TIMEOUT = 15

CURRENCY_SYMBOLS = {"CNY": "\u00a5", "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "JPY": "\u00a5"}

HTTP_ERROR_MESSAGES = {
    400: "请求参数错误",
    401: "API Key 无效或未授权",
    402: "余额不足或账户被冻结",
    403: "禁止访问",
    404: "接口不存在",
    429: "请求过于频繁，请稍后重试",
}

# ------- API Key 本地存储（无需系统环境变量） -------
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".deepseek")
KEY_FILE = os.path.join(CONFIG_DIR, "api_key")


def load_saved_key():
    """读取本地保存的 API Key，没有则返回 None。"""
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
        return key or None
    except OSError:
        return None


def save_key(key):
    """保存 API Key 到本地文件，成功返回 True。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key.strip() + "\n")
        return True
    except OSError:
        return False


def clear_saved_key():
    """删除本地保存的 API Key 文件，成功返回 True。"""
    try:
        os.remove(KEY_FILE)
        return True
    except OSError:
        return False


# ------- 设置持久化（刷新间隔等） -------
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    """读取本地设置，失败返回空字典。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    """合并写入本地设置，成功返回 True。"""
    try:
        merged = load_config()
        merged.update(cfg)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False

# ------- 主题配色 -------
BG = "#0f141a"        # 窗口最外层背景
PANEL = "#161d26"     # 面板背景
BORDER = "#2a3542"    # 边框 / 分隔线
TEXT = "#e8edf2"      # 正文
DIM = "#7d8b9e"       # 次要文字
ACCENT = "#5b8cff"    # 强调（总余额）
OK = "#3fb950"        # 状态正常
BAD = "#ff6b6b"       # 状态异常
WARN = "#f5a623"      # 查询中

FONT_TITLE = ("Microsoft YaHei UI", 10, "bold")
FONT_BODY = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_NUM = ("Consolas", 11, "bold")


class BalanceError(Exception):
    """余额查询失败。"""


def query_balance(api_key, base_url, timeout):
    """调用 GET {base_url}/user/balance。成功返回 JSON 字典，失败抛出 BalanceError。"""
    url = base_url.rstrip("/") + BALANCE_ENDPOINT
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        msg = HTTP_ERROR_MESSAGES.get(e.code, "请求失败")
        raise BalanceError("HTTP %d %s%s" % (e.code, msg, (": " + body) if body else ""))
    except urllib.error.URLError as e:
        raise BalanceError("网络错误: %s" % e.reason)
    except ValueError as e:
        raise BalanceError("响应解析失败: %s" % e)


def fmt_money(symbol, value):
    """把 "110.00" 之类的金额格式化为 "¥110.00"。"""
    try:
        return "%s%.2f" % (symbol, float(value))
    except (TypeError, ValueError):
        return "%s%s" % (symbol, value)


class _RowSlot:
    """一行可复用的显示控件：包含分隔线 / 左标签 / 右标签，避免刷新时销毁重建导致闪烁。"""

    __slots__ = ("frame", "sep", "left", "right", "spec")

    def __init__(self, body):
        self.frame = tk.Frame(body, bg=PANEL)
        self.sep = tk.Frame(self.frame, bg=BORDER, height=1)
        self.left = tk.Label(self.frame, bg=PANEL, fg=TEXT, font=FONT_BODY, anchor="w")
        self.right = tk.Label(self.frame, bg=PANEL, fg=TEXT, font=FONT_BODY, anchor="e")
        self.spec = None  # 当前显示的内容（用于跳过无变化的刷新）


class KeyPromptDialog:
    """模态输入框：输入 API Key，可选勾选"记住 Key"保存到本地文件。"""

    def __init__(self, parent):
        self.result_key = None
        self.remember = True

        win = tk.Toplevel(parent)
        win.title("DeepSeek API Key")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.transient(parent)
        win.grab_set()

        tk.Label(win, text="请输入 DeepSeek API Key", bg=PANEL, fg=TEXT,
                 font=FONT_TITLE).pack(padx=16, pady=(14, 2), anchor="w")
        tk.Label(win, text="（Key 在平台获取: https://platform.deepseek.com/api_keys）",
                 bg=PANEL, fg=DIM, font=FONT_SMALL).pack(padx=16, anchor="w")

        self.entry = tk.Entry(win, show="*", width=44, bg="#0d1218", fg=TEXT,
                              insertbackground=TEXT, relief="flat", font=FONT_BODY)
        self.entry.pack(padx=16, pady=(10, 6), fill="x")

        self.remember_var = tk.BooleanVar(value=True)
        tk.Checkbutton(win, text="记住 Key（保存到本地文件 %s）" % KEY_FILE,
                       variable=self.remember_var, bg=PANEL, fg=DIM,
                       selectcolor="#0d1218", activebackground=PANEL,
                       activeforeground=TEXT, font=FONT_SMALL).pack(padx=16, anchor="w")

        btns = tk.Frame(win, bg=PANEL)
        btns.pack(padx=16, pady=(8, 14))
        tk.Button(btns, text="确定", width=8, command=self._ok, bg=ACCENT, fg="#ffffff",
                  activebackground="#3f6fe0", activeforeground="#ffffff", relief="flat",
                  font=FONT_BODY).pack(side="left", padx=(0, 8))
        tk.Button(btns, text="取消", width=8, command=self._cancel, bg="#232d3a", fg=TEXT,
                  activebackground="#2f3b4c", activeforeground=TEXT, relief="flat",
                  font=FONT_BODY).pack(side="left")

        win.bind("<Return>", lambda e: self._ok())
        win.bind("<Escape>", lambda e: self._cancel())
        self.entry.focus_set()
        parent.wait_window(win)  # 模态：等待对话框关闭

    def _ok(self):
        self.result_key = self.entry.get().strip()
        self.remember = bool(self.remember_var.get())
        self.entry.master.destroy()

    def _cancel(self):
        self.entry.master.destroy()


class IntervalDialog:
    """模态输入框：设置自动刷新间隔（秒）。"""

    def __init__(self, parent, current):
        self.result = None

        win = tk.Toplevel(parent)
        win.title("设置刷新间隔")
        win.configure(bg=PANEL)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.transient(parent)
        win.grab_set()

        tk.Label(win, text="自动刷新间隔（秒）", bg=PANEL, fg=TEXT,
                 font=FONT_TITLE).pack(padx=16, pady=(14, 2), anchor="w")
        tk.Label(win, text="范围 5 ~ 86400 秒（1 天），改后立即生效并记住",
                 bg=PANEL, fg=DIM, font=FONT_SMALL).pack(padx=16, anchor="w")

        self.spin = tk.Spinbox(win, from_=5, to=86400, increment=5, width=10,
                               bg="#0d1218", fg=TEXT, insertbackground=TEXT,
                               buttonbackground="#232d3a", relief="flat",
                               font=FONT_BODY, justify="center")
        self.spin.delete(0, "end")
        self.spin.insert(0, str(int(current)))
        self.spin.pack(padx=16, pady=(10, 6), anchor="w")

        btns = tk.Frame(win, bg=PANEL)
        btns.pack(padx=16, pady=(8, 14))
        tk.Button(btns, text="确定", width=8, command=self._ok, bg=ACCENT, fg="#ffffff",
                  activebackground="#3f6fe0", activeforeground="#ffffff", relief="flat",
                  font=FONT_BODY).pack(side="left", padx=(0, 8))
        tk.Button(btns, text="取消", width=8, command=self._cancel, bg="#232d3a", fg=TEXT,
                  activebackground="#2f3b4c", activeforeground=TEXT, relief="flat",
                  font=FONT_BODY).pack(side="left")

        win.bind("<Return>", lambda e: self._ok())
        win.bind("<Escape>", lambda e: self._cancel())
        self.spin.focus_set()
        parent.wait_window(win)  # 模态：等待对话框关闭

    def _ok(self):
        try:
            self.result = max(5, int(self.spin.get()))
        except ValueError:
            self.result = None
        self.spin.master.destroy()

    def _cancel(self):
        self.spin.master.destroy()


class BalanceWidget:
    def __init__(self, root, api_key, args):
        self.root = root
        self.api_key = api_key
        self.base_url = args.base_url
        if args.interval is not None:
            self.interval = max(5, args.interval)
        else:
            self.interval = max(5, int(load_config().get("refresh_interval", DEFAULT_INTERVAL)))
        self.interval_var = tk.IntVar(value=self.interval)
        self.timeout = args.timeout

        self.queue = queue.Queue()      # 工作线程 -> 主线程 通信
        self.refreshing = False
        self.countdown = self.interval
        self.last_ok = None             # 最近一次成功的数据
        self.error_text = None
        self.last_update_text = "--:--:--"
        self._period_text = None        # 时段行当前文案（未变则跳过重排）
        self._pinned_right = None       # 贴右上角时锁定的右边缘 x 坐标
        self._last_reqwidth = 0

        root.title("DeepSeek 余额")
        root.overrideredirect(True)
        root.attributes("-topmost", args.topmost)
        root.attributes("-alpha", max(0.3, min(1.0, args.opacity)))
        root.configure(bg=BG)

        self._build_ui()
        self._bind_events(args)
        self._place_window(args)
        self._update_period()

        self.refresh_now()
        self.root.after(200, self._poll_queue)   # 轮询工作线程结果
        self.root.after(1000, self._tick)        # 倒计时 + 定时刷新

    # ---------- UI ----------
    def _build_ui(self):
        self.frame = tk.Frame(self.root, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        self.frame.pack(fill="both", expand=True)

        head = tk.Frame(self.frame, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(head, text="DeepSeek 余额", bg=PANEL, fg=ACCENT, font=FONT_TITLE).pack(side="left")
        self.status_label = tk.Label(head, text="查询中\u2026", bg=PANEL, fg=WARN, font=FONT_SMALL)
        self.status_label.pack(side="right")
        tk.Frame(self.frame, bg=BORDER, height=1).pack(fill="x", padx=8)

        period_row = tk.Frame(self.frame, bg=PANEL)
        period_row.pack(fill="x", padx=12, pady=(3, 0))
        self.period_label = tk.Label(period_row, text="", bg=PANEL, font=FONT_SMALL)
        self.period_label.pack(side="left")

        self.body = tk.Frame(self.frame, bg=PANEL)
        self.body.pack(fill="x", padx=12, pady=6)
        self.body.grid_columnconfigure(0, weight=1)
        self._row_pool = []  # 可复用行控件池
        tk.Frame(self.frame, bg=BORDER, height=1).pack(fill="x", padx=8)

        foot = tk.Frame(self.frame, bg=PANEL)
        foot.pack(fill="x", padx=12, pady=(4, 8))
        self.footer_label = tk.Label(foot, text="", bg=PANEL, fg=DIM, font=FONT_SMALL)
        self.footer_label.pack(side="left")

    def _place_window(self, args):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        if args.x is not None and args.y is not None:
            x, y = args.x, args.y
        else:
            sw = self.root.winfo_screenwidth()
            x, y = sw - w - 24, 48          # 默认右上角
            # 记住右边缘: 时段文案（周末/节假日/跨假期）长度会变，
            # 窗口随之变宽，锁定右边缘才不会向右溢出屏幕。
            self._pinned_right = x + w
        self.root.geometry("+%d+%d" % (x, y))

    def _reanchor_right(self):
        """保持默认右上角位置时的右边缘不动（窗口变宽就向左长，不会溢出屏幕）。"""
        if self._pinned_right is None:
            return
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        if width == self._last_reqwidth:
            return
        self._last_reqwidth = width
        x = max(0, self._pinned_right - width)
        if x != self.root.winfo_x():
            self.root.geometry("+%d+%d" % (x, self.root.winfo_y()))

    # ---------- 事件 ----------
    def _bind_events(self, args):
        self.root.bind("<Button-1>", self._drag_start)
        self.root.bind("<B1-Motion>", self._drag_move)
        self.root.bind("<Double-Button-1>", lambda e: self.refresh_now())
        self.root.bind("<Button-3>", self._show_menu)
        self.root.bind("<Button-2>", self._show_menu)
        self.root.bind("<F5>", lambda e: self.refresh_now())
        self.root.bind("<Escape>", lambda e: self._quit())

        self.menu = tk.Menu(self.root, tearoff=0, bg="#1c242f", fg=TEXT,
                            activebackground=ACCENT, activeforeground="#ffffff")
        self.menu.add_command(label="立即刷新 (F5)", command=self.refresh_now)
        self.menu.add_separator()
        int_menu = tk.Menu(self.menu, tearoff=0, bg="#1c242f", fg=TEXT,
                           activebackground=ACCENT, activeforeground="#ffffff")
        for sec in (10, 30, 60, 120, 300):
            int_menu.add_radiobutton(label="%d 秒" % sec, value=sec,
                                     variable=self.interval_var, command=self._apply_interval_preset)
        int_menu.add_separator()
        int_menu.add_command(label="自定义…", command=self._custom_interval)
        self.menu.add_cascade(label="刷新间隔", menu=int_menu)
        self.menu.add_separator()
        self.menu.add_command(label="更换 API Key…", command=self._change_key)
        self.menu.add_command(label="清除已保存的 Key", command=self._clear_saved_key)
        self.menu.add_separator()
        self.topmost_var = tk.BooleanVar(value=args.topmost)
        self.menu.add_checkbutton(label="保持置顶", variable=self.topmost_var, command=self._toggle_topmost)
        self.opacity_var = tk.DoubleVar(value=args.opacity)
        op_menu = tk.Menu(self.menu, tearoff=0, bg="#1c242f", fg=TEXT,
                          activebackground=ACCENT, activeforeground="#ffffff")
        for val in (1.0, 0.9, 0.8, 0.65, 0.5):
            op_menu.add_radiobutton(label="%d%%" % int(val * 100), value=val,
                                    variable=self.opacity_var, command=self._apply_opacity)
        self.menu.add_cascade(label="不透明度", menu=op_menu)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self._quit)

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry("+%d+%d" % (x, y))
        # 拖回右上角附近就重新锁定右边缘；拖到别处则不再自动调整位置
        right = x + self.root.winfo_reqwidth()
        if abs(right - (self.root.winfo_screenwidth() - 24)) <= 8:
            self._pinned_right = right
        else:
            self._pinned_right = None

    def _show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _apply_opacity(self):
        self.root.attributes("-alpha", self.opacity_var.get())

    def _apply_interval_preset(self):
        self._set_interval(self.interval_var.get())

    def _custom_interval(self):
        dlg = IntervalDialog(self.root, self.interval)
        if dlg.result is not None:
            self._set_interval(dlg.result)

    def _set_interval(self, seconds):
        seconds = max(5, int(seconds))
        self.interval = seconds
        self.interval_var.set(seconds)
        self.countdown = seconds
        save_config({"refresh_interval": seconds})
        self._update_footer()
        self.refresh_now()

    def _change_key(self):
        dlg = KeyPromptDialog(self.root)
        if not dlg.result_key:
            return
        if dlg.remember:
            save_key(dlg.result_key)
        self.api_key = dlg.result_key
        self.refresh_now()

    def _clear_saved_key(self):
        if clear_saved_key():
            self._set_status("已清除本地 Key", DIM)
        else:
            self._set_status("没有已保存的 Key", WARN)

    def _quit(self):
        self.root.destroy()

    # ---------- 刷新逻辑 ----------
    def refresh_now(self):
        if self.refreshing:
            return
        if not self.api_key:
            self.error_text = "右键菜单 \u2192 更换 API Key\u2026 输入 Key 即可"
            self._set_status("未配置 Key", BAD)
            self._render_error()
            return
        self.refreshing = True
        if self.last_ok is None:
            self._set_status("查询中\u2026", WARN)  # 已有数据时保持原状态，避免每次刷新闪变
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            data = query_balance(self.api_key, self.base_url, self.timeout)
            self.queue.put(("ok", data))
        except BalanceError as e:
            self.queue.put(("err", str(e)))
        except Exception as e:  # 兜底，避免线程静默死亡
            self.queue.put(("err", repr(e)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self.refreshing = False
                self.countdown = self.interval
                if kind == "ok":
                    self.last_ok = payload
                    self.error_text = None
                    self._render(payload)
                else:
                    self.error_text = payload
                    self._set_status("获取失败", BAD)
                    if self.last_ok is None:
                        self._render_error()
                    # 有旧数据则保留旧数据，仅在状态栏体现失败
                    self._update_footer()
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _render(self, data):
        ok = bool(data.get("is_available"))
        self._set_status("\u25cf 可用" if ok else "\u25cf 不可用", OK if ok else BAD)
        infos = data.get("balance_infos") or []
        rows = []
        if not infos:
            rows.append(("msg", "未查询到余额信息", DIM))
        for i, info in enumerate(infos):
            if i > 0:
                rows.append(("sep",))
            cur = info.get("currency", "")
            sym = CURRENCY_SYMBOLS.get(cur, cur + " ")
            rows.append(("row", "总余额 " + cur, fmt_money(sym, info.get("total_balance")), True))
            rows.append(("row", "赠送余额", fmt_money(sym, info.get("granted_balance")), False))
            rows.append(("row", "充值余额", fmt_money(sym, info.get("topped_up_balance")), False))
        self._show_rows(rows)
        self.last_update_text = time.strftime("%H:%M:%S")
        self._update_footer()

    def _render_error(self):
        rows = [("err", "\u26a0 查询失败")]
        if self.error_text:
            rows.append(("msg", self.error_text, TEXT))
        self._show_rows(rows)
        self._update_footer()

    def _show_rows(self, rows):
        """用控件池按需复用/新建行，无变化的行完全不动，避免刷新闪烁。"""
        pool = self._row_pool
        for i, spec in enumerate(rows):
            if i < len(pool):
                slot = pool[i]
            else:
                slot = _RowSlot(self.body)
                pool.append(slot)
            self._apply_slot(slot, spec)
            slot.frame.grid(row=i, column=0, sticky="ew")
        for extra in pool[len(rows):]:
            extra.frame.grid_remove()

    def _apply_slot(self, slot, spec):
        """更新一行内容；spec 与当前一致时直接跳过（无任何重绘）。"""
        if slot.spec == spec:
            return
        # 结构变化时先全部收起再按需展开，避免 pack 顺序错乱
        slot.sep.pack_forget()
        slot.left.pack_forget()
        slot.right.pack_forget()
        kind = spec[0]
        if kind == "sep":
            slot.sep.pack(fill="x", pady=4)
        elif kind == "row":
            _, label, value, bold = spec
            slot.left.config(text=label, fg=TEXT if bold else DIM,
                             font=FONT_TITLE if bold else FONT_BODY)
            slot.right.config(text=value, fg=ACCENT if bold else TEXT,
                              font=FONT_NUM if bold else FONT_BODY)
            slot.left.pack(side="left")
            slot.right.pack(side="right")
        elif kind == "err":
            slot.left.config(text=spec[1], fg=BAD, font=FONT_TITLE)
            slot.left.pack(side="left")
        elif kind == "msg":
            _, text, color = spec
            slot.left.config(text=text, fg=color, font=FONT_SMALL,
                             justify="left", wraplength=260, anchor="w")
            slot.left.pack(side="left", fill="x", expand=True)
        slot.spec = spec

    def _set_status(self, text, color):
        self.status_label.config(text=text, fg=color)

    def _update_footer(self):
        text = "更新于 %s \u00b7 %ds 后刷新" % (self.last_update_text, max(self.countdown, 0))
        if self.error_text and self.last_ok is not None:
            text += "（上次刷新失败）"
        self.footer_label.config(text=text)

    def _update_period(self):
        """更新当前时段指示（高峰/空闲半价），附下次切换时间，到点自动切换。"""
        now = pricing.beijing_now()
        period, reason = pricing.period_reason(now)
        if period == "peak":
            text, color = "\u25c6 高峰时段", WARN
        else:
            text, color = "\u25c6 空闲时段 \u00b7 半价", OK
            if reason:  # 周末 / 法定假日名，让用户知道为什么是空闲
                text += " \u00b7 " + reason
        nxt, nxt_period = pricing.next_boundary(now)
        when = pricing.format_boundary(nxt, now)
        if when:
            text += " \u00b7 %s 转%s" % (when,
                                         "高峰" if nxt_period == "peak" else "空闲")
        if not pricing.has_holiday_data(now.year):
            text += " \u00b7 %d 年假期表待更新" % now.year
        if text != self._period_text:   # 文案没变就不动，避免每秒触发重排
            self._period_text = text
            self.period_label.config(text=text, fg=color)
            self._reanchor_right()

    def _tick(self):
        self.countdown -= 1
        if self.countdown <= 0 and not self.refreshing:
            self.countdown = self.interval
            self.refresh_now()
        self._update_period()
        self._update_footer()
        self.root.after(1000, self._tick)


# ---------- 启动 ----------
def build_arg_parser():
    p = argparse.ArgumentParser(
        description="DeepSeek 余额悬浮窗 - 置顶显示，每 N 秒自动刷新",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-k", "--api-key", metavar="KEY", help="DeepSeek API Key（优先级最高，不保存到本地）")
    p.add_argument("--reset-key", action="store_true", help="清除本地保存的 API Key 后退出")
    p.add_argument("--interval", type=int, default=None, metavar="SECONDS",
                   help="自动刷新间隔秒数（不传则用上次记忆的值，默认 30；右键菜单可随时改）")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SECONDS",
                   help="请求超时秒数（默认 %(default)s）")
    p.add_argument("--opacity", type=float, default=0.95, metavar="0.3-1.0",
                   help="窗口不透明度（默认 %(default)s）")
    p.add_argument("--no-topmost", dest="topmost", action="store_false", default=True,
                   help="启动时不置顶（默认置顶）")
    p.add_argument("--x", type=int, default=None, help="窗口初始 X 坐标（默认屏幕右上角）")
    p.add_argument("--y", type=int, default=None, help="窗口初始 Y 坐标")
    p.add_argument("-b", "--base-url", default=API_BASE, help="API 地址（默认 %(default)s，一般无需修改）")
    return p


def resolve_key(args):
    """API Key 获取顺序: --api-key > 本地保存文件 > 环境变量。都没有则返回 None。"""
    key = (args.api_key or "").strip()
    if key:
        return key
    key = load_saved_key()
    if key:
        return key
    key = (os.environ.get("DEEPSEEK_API_KEY", "") or "").strip()
    if key:
        return key
    return None


def _hide_console_if_dedicated():
    """双击启动 .py 时隐藏独立控制台黑窗；从已有终端启动时不动（避免误藏用户终端）。

    判断方法: GetConsoleProcessList 返回附加到当前控制台的进程数。
    只有 1 个进程 = 双击生成的独立控制台，可以安全隐藏；
    >=2 个进程 = 从 cmd/PowerShell 等终端里启动的共享控制台，不隐藏。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        procs = (wintypes.DWORD * 4)()
        n = kernel32.GetConsoleProcessList(procs, 4)
        if n <= 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _set_dpi_aware():
    """让高分屏 (125%/150% 缩放) 下文字清晰。失败则忽略。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _notify(msg):
    """向用户反馈信息。

    有控制台（.py 直接运行）时写 stderr；打包成 --noconsole 的 exe 后
    sys.stderr 为 None，改走 GUI 弹窗提示，避免 AttributeError 崩溃。
    """
    if sys.stderr:
        try:
            sys.stderr.write(msg + "\n")
            return
        except Exception:
            pass
    try:
        import tkinter.messagebox as tkmb
        root = tk.Tk()
        root.withdraw()
        tkmb.showinfo("DeepSeek 余额", msg)
        root.destroy()
    except Exception:
        pass


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.reset_key:
        if clear_saved_key():
            _notify("已清除本地保存的 API Key: %s" % KEY_FILE)
        else:
            _notify("未找到需要清除的 Key 文件（%s）" % KEY_FILE)
        return 0
    _hide_console_if_dedicated()
    _set_dpi_aware()
    root = tk.Tk()
    api_key = resolve_key(args)
    if not api_key:
        if sys.stderr:
            sys.stderr.write("提示: 未找到 API Key，请在弹出的输入框中填写。\n")
        dlg = KeyPromptDialog(root)
        api_key = dlg.result_key
        if api_key and dlg.remember:
            save_key(api_key)
    BalanceWidget(root, api_key, args)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
