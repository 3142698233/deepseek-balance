#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 账户余额查询工具

基于 DeepSeek API 文档:
    https://api-docs.deepseek.com/zh-cn/api/get-user-balance/

接口:   GET https://api.deepseek.com/user/balance
鉴权:   请求头 Authorization: Bearer <API_KEY>

用法示例:
    # 方式一（推荐）: 用悬浮窗版首次运行保存 Key 到本地 (~/.deepseek/api_key)，
    # 本脚本会自动读取同一个文件，无需任何环境变量:
    python deepseek_balance.py

    # 方式二: 直接传 Key（不保存）
    python deepseek_balance.py --api-key sk-xxxxx

    # 方式三: 环境变量（可选）
    set DEEPSEEK_API_KEY=sk-xxxxx                # Windows CMD
    $env:DEEPSEEK_API_KEY = "sk-xxxxx"           # PowerShell

    # 其他:
    python deepseek_balance.py --json            # 输出原始 JSON（适合脚本解析）
    python deepseek_balance.py --reset-key       # 清除本地保存的 Key

依赖: 仅 Python 标准库，无需 pip install 任何包（要求 Python 3.6+）。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_BASE = "https://api.deepseek.com"
BALANCE_ENDPOINT = "/user/balance"
DEFAULT_TIMEOUT = 15

# 计价时段: 高峰 = 北京时间周一~周五 9:00-12:00、14:00-18:00；其余空闲（价格半价）
BEIJING_TZ = timezone(timedelta(hours=8))
PEAK_RANGES = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))


def get_period(now=None):
    """返回当前时段: "peak" 高峰 / "offpeak" 空闲（默认按北京时间）。"""
    now = now or datetime.now(BEIJING_TZ)
    if now.weekday() >= 5:
        return "offpeak"
    hm = now.hour * 60 + now.minute
    for start, end in PEAK_RANGES:
        if start <= hm < end:
            return "peak"
    return "offpeak"


def next_boundary(now=None):
    """返回 (下次时段切换时间, 切换后的时段)。"""
    now = now or datetime.now(BEIJING_TZ)
    cur = get_period(now)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(8):
        dt = day + timedelta(days=d)
        if dt.weekday() >= 5:
            continue
        for hh in (9, 12, 14, 18):
            cand = dt.replace(hour=hh, minute=0, second=0, microsecond=0)
            if cand > now and get_period(cand) != cur:
                return cand, get_period(cand)
    return None, cur

# HTTP 错误码 -> 中文说明
HTTP_ERROR_MESSAGES = {
    400: "请求参数错误",
    401: "API Key 无效或未授权",
    402: "余额不足或账户被冻结",
    403: "禁止访问",
    404: "接口不存在",
    429: "请求过于频繁，请稍后重试",
}

# ------- API Key 本地存储（与悬浮窗版共用同一文件） -------
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


def clear_saved_key():
    """删除本地保存的 API Key 文件，成功返回 True。"""
    try:
        os.remove(KEY_FILE)
        return True
    except OSError:
        return False


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="查询 DeepSeek 账户余额",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-k", "--api-key",
        metavar="KEY",
        help="DeepSeek API Key（优先级最高，不保存）；未指定时读取本地文件，最后才读环境变量",
    )
    parser.add_argument(
        "--reset-key",
        action="store_true",
        help="清除本地保存的 API Key（%s）后退出" % KEY_FILE,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出接口原始结果（便于脚本解析）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="请求超时秒数（默认 %(default)s）",
    )
    parser.add_argument(
        "-b", "--base-url",
        default=API_BASE,
        help="API 地址（默认 %(default)s，一般无需修改）",
    )
    return parser


def resolve_api_key(args):
    """确定 API Key：--api-key > 本地保存文件 > 环境变量。"""
    key = (args.api_key or "").strip()
    if key:
        return key
    key = load_saved_key()
    if key:
        return key
    key = (os.environ.get("DEEPSEEK_API_KEY", "") or "").strip()
    if key:
        return key
    sys.stderr.write(
        "错误: 未提供 API Key。\n"
        "推荐: 先运行 python deepseek_balance_widget.py，在弹窗中输入 Key 并勾选"
        "\"记住 Key\"，之后本命令即可直接使用（保存位置: %s）。\n"
        "临时: 也可以用 --api-key 参数直接传入。\n" % KEY_FILE
    )
    sys.exit(2)
    return key


def fetch_balance(api_key, base_url, timeout):
    """调用 GET {base_url}/user/balance，返回解析后的 JSON 字典。"""
    url = base_url.rstrip("/") + BALANCE_ENDPOINT
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json",
        },
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
        sys.stderr.write("HTTP %d %s\n" % (e.code, msg))
        if body:
            sys.stderr.write("响应内容: %s\n" % body)
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.stderr.write("网络错误: %s\n" % e.reason)
        sys.exit(1)


def format_human(data):
    """把接口返回的 JSON 格式化成易读的多行文本。"""
    lines = ["DeepSeek 账户余额", "-" * 36]
    lines.append("账户状态: %s" % ("可用" if data.get("is_available") else "不可用"))
    period = get_period()
    nxt, nxt_period = next_boundary()
    ptext = "高峰时段" if period == "peak" else "空闲时段（价格半价）"
    if nxt is not None:
        ptext += " \u00b7 %s 转%s" % (nxt.strftime("%H:%M"),
                                      "高峰" if nxt_period == "peak" else "空闲")
    lines.append("当前时段: %s" % ptext)
    infos = data.get("balance_infos") or []
    if not infos:
        lines.append("未查询到余额信息")
        return "\n".join(lines)
    for i, info in enumerate(infos, 1):
        currency = info.get("currency", "?")
        total = info.get("total_balance", "-")
        granted = info.get("granted_balance", "-")
        topped = info.get("topped_up_balance", "-")
        prefix = "[%d] " % i if len(infos) > 1 else ""
        lines.append("%s币种: %s" % (prefix, currency))
        lines.append("总余额: %s" % total)
        lines.append("  ├─ 赠送余额: %s" % granted)
        lines.append("  └─ 充值余额: %s" % topped)
        if i < len(infos):
            lines.append("")
    return "\n".join(lines)


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.reset_key:
        if clear_saved_key():
            print("已清除本地保存的 API Key: %s" % KEY_FILE)
        else:
            print("未找到需要清除的 Key 文件（%s）" % KEY_FILE)
        return 0
    api_key = resolve_api_key(args)
    data = fetch_balance(api_key, args.base_url, args.timeout)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_human(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
