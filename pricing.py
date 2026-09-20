#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 峰谷计价时段判定（含中国法定节假日）

计价规则（DeepSeek API 峰谷时间说明）:
  * 高峰时段: 北京时间 周一~周五（不含中国法定节假日）09:00-12:00、14:00-18:00
  * 空闲时段: 其余全部时间 —— 周末、中国法定节假日全天、以及工作日的高峰时段之外
  * 空闲时段价格为高峰时段价格的一半
  * 调休上班的周末、中国法定节假日全天均按空闲时段计费

为什么只需要"放假日"、不需要"调休补班日":
  调休补班日必定落在周六或周日，而周末本就全天空闲，
  所以补班日自动就是空闲时段，无需单独标记。
  只有落在周一~周五的法定假日需要从"高峰"里排除掉。

节假日数据来源:
  国务院办公厅《关于 XXXX 年部分节假日安排的通知》，
  发布于 https://www.gov.cn/zhengce/zhengceku/ （每年 11 月前后公布次年安排）。
  更新方法: 在 HOLIDAY_RANGES 里按同样格式补上新的一年即可（闭区间，含首尾两天）。

依赖: 仅 Python 标准库（要求 Python 3.6+）。
"""

from datetime import date, datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))

# 高峰时段，用"当天第几分钟"表示: 09:00-12:00、14:00-18:00
PEAK_RANGES = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))

# 查找"下次切换时刻"时向后搜索的自然日数。
# 最长的连续空闲区间出现在春节（2026 年连休 9 天）叠加前后周末，约 11 天，30 天足够覆盖。
BOUNDARY_SEARCH_DAYS = 30

# 年份 -> ((节日名, 起始日, 结束日), ...)，日期为北京时间自然日，闭区间
HOLIDAY_RANGES = {
    2025: (
        ("元旦", "2025-01-01", "2025-01-01"),
        ("春节", "2025-01-28", "2025-02-04"),
        ("清明节", "2025-04-04", "2025-04-06"),
        ("劳动节", "2025-05-01", "2025-05-05"),
        ("端午节", "2025-05-31", "2025-06-02"),
        ("国庆节·中秋节", "2025-10-01", "2025-10-08"),
    ),
    2026: (
        ("元旦", "2026-01-01", "2026-01-03"),
        ("春节", "2026-02-15", "2026-02-23"),
        ("清明节", "2026-04-04", "2026-04-06"),
        ("劳动节", "2026-05-01", "2026-05-05"),
        ("端午节", "2026-06-19", "2026-06-21"),
        ("中秋节", "2026-09-25", "2026-09-27"),
        ("国庆节", "2026-10-01", "2026-10-07"),
    ),
}

WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _parse_day(text):
    """把 "2026-09-25" 解析成 date（不用 date.fromisoformat，以兼容 Python 3.6）。"""
    year, month, day = text.split("-")
    return date(int(year), int(month), int(day))


def _build_holiday_index():
    """把 HOLIDAY_RANGES 展开成 {date: 节日名}。"""
    index = {}
    for ranges in HOLIDAY_RANGES.values():
        for name, start, end in ranges:
            day = _parse_day(start)
            last = _parse_day(end)
            while day <= last:
                index[day] = name
                day += timedelta(days=1)
    return index


HOLIDAY_INDEX = _build_holiday_index()


def beijing_now():
    """当前北京时间（与本机时区无关；中国不实行夏令时）。"""
    return datetime.now(BEIJING_TZ)


def holiday_name(day):
    """返回该自然日对应的法定节假日名称；不是放假日则返回 None。"""
    return HOLIDAY_INDEX.get(day)


def is_holiday(day):
    """该自然日是否为中国法定节假日（放假日）。"""
    return day in HOLIDAY_INDEX


def covered_years():
    """已收录节假日安排的年份（升序）。"""
    return tuple(sorted(HOLIDAY_RANGES))


def has_holiday_data(year):
    """该年份的法定节假日安排是否已收录。

    未收录时只能按"周一~周五"粗略判定，节假日的调休会出现偏差，
    界面上会提示"假期表待更新"。
    """
    return year in HOLIDAY_RANGES


def get_period(now=None):
    """返回当前时段: "peak" 高峰 / "offpeak" 空闲（默认取当前北京时间）。

    空闲时段价格为高峰时段价格的一半。
    """
    now = now or beijing_now()
    if is_holiday(now.date()):
        return "offpeak"        # 法定节假日全天按空闲计费
    if now.weekday() >= 5:
        return "offpeak"        # 周六、周日全天空闲（含调休补班的周末）
    minute_of_day = now.hour * 60 + now.minute
    for start, end in PEAK_RANGES:
        if start <= minute_of_day < end:
            return "peak"
    return "offpeak"


def period_reason(now=None):
    """返回 (时段, 原因说明)。

    原因说明用于界面展示，让人一眼看出为什么是空闲:
    法定假日名（如 "中秋节"）/ "周末" / None（工作日高峰时段之内或之外）。
    """
    now = now or beijing_now()
    period = get_period(now)
    name = holiday_name(now.date())
    if name:
        return period, name
    if now.weekday() >= 5:
        return period, "周末"
    return period, None


def next_boundary(now=None):
    """返回 (下次时段切换的北京时间, 切换后的时段)。

    时段只会在"非节假日的工作日"的 09:00 / 12:00 / 14:00 / 18:00 发生变化
    （午夜前后都是空闲，不构成切换），所以只需在这些候选时刻里找第一个与当前不同的。
    切换点可能跨越整个春节/国庆假期（10 天以上），故搜索窗口取 BOUNDARY_SEARCH_DAYS 天；
    窗口内没有切换则返回 (None, 当前时段)。
    """
    now = now or beijing_now()
    current = get_period(now)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(BOUNDARY_SEARCH_DAYS):
        day = midnight + timedelta(days=offset)
        if day.weekday() >= 5 or is_holiday(day.date()):
            continue
        for hour in (9, 12, 14, 18):
            candidate = day.replace(hour=hour)
            if candidate > now and get_period(candidate) != current:
                return candidate, get_period(candidate)
    return None, current


def format_boundary(boundary, now=None):
    """把切换时刻格式化成界面用的短文本。

    当天 -> "15:00"；次日 -> "明天 09:00"；
    更远 -> "10-08 周四 09:00"（假期结束后才切换时会用到，带日期避免"周四"歧义）。
    """
    if boundary is None:
        return None
    now = now or beijing_now()
    days = (boundary.date() - now.date()).days
    clock = boundary.strftime("%H:%M")
    if days <= 0:
        return clock
    if days == 1:
        return "明天 " + clock
    return "%s %s %s" % (boundary.strftime("%m-%d"), WEEKDAY_CN[boundary.weekday()], clock)


def period_text(now=None, with_boundary=True):
    """生成一行人类可读的时段说明，供 CLI 与悬浮窗共用。

    例: "高峰时段 · 12:00 转空闲"
        "空闲时段（价格半价）· 中秋节 · 10-08 周四 09:00 转高峰"
        "空闲时段（价格半价）· 周末 · 明天 09:00 转高峰"
    """
    now = now or beijing_now()
    period, reason = period_reason(now)
    if period == "peak":
        text = "高峰时段"
    else:
        text = "空闲时段（价格半价）"
    if reason:
        text += " · %s" % reason
    if with_boundary:
        boundary, boundary_period = next_boundary(now)
        when = format_boundary(boundary, now)
        if when:
            text += " · %s 转%s" % (when, "高峰" if boundary_period == "peak" else "空闲")
    if not has_holiday_data(now.year):
        text += " · %d 年假期表待更新" % now.year
    return text
