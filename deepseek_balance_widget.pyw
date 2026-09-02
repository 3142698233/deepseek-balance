#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 余额悬浮窗 - 无命令行窗口启动器

双击本文件即可启动悬浮窗，不会出现黑色命令行窗口（系统会用 pythonw.exe 运行）。
真正的程序代码在 deepseek_balance_widget.py 中，本文件只是一个薄启动层，
修改代码时只需改 deepseek_balance_widget.py。

也可以直接运行: pythonw deepseek_balance_widget.py
"""
import sys

import deepseek_balance_widget as app

if __name__ == "__main__":
    sys.exit(app.main())
