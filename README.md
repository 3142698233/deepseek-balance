# DeepSeek Balance Widget / 余额悬浮窗

一个轻量级的 [DeepSeek](https://platform.deepseek.com/) 账户余额查询工具，支持**桌面悬浮窗**和**命令行**两种模式。

> 纯 Python 标准库实现，无需安装任何第三方依赖（Python 3.6+）。提供 exe 单文件版本，双击即用。

![DeepSeek 余额悬浮窗](screenshot.png)

## 功能亮点

- 🔍 实时查询 DeepSeek 账户余额（总余额 / 赠送余额 / 充值余额）
- 🖥️ **桌面悬浮窗**：置顶显示、左键拖拽、双击刷新、右键菜单
- ⏱️ **自动刷新**：可调间隔（10/30/60/120/300 秒或自定义），设置自动记忆
- 💰 **计价时段显示**：实时显示当前是高峰时段还是空闲时段（半价），标明原因（周末 / 法定假日名）与下次切换时间
- 📋 **命令行工具**：一行命令查看余额，支持 JSON 输出（便于脚本解析）
- 🔐 **本地保存 Key**：首次运行弹窗输入，可勾选"记住"，无需系统环境变量
- 🎨 **深色主题**：护眼深色界面，控件复用无刷新闪烁

## 快速开始

### 方式一：下载 exe（推荐，无需 Python）

1. 前往 [Releases](https://github.com/3142698233/deepseek-balance/releases) 下载 `DeepSeekBalance.exe`
2. 双击运行，首次会弹窗让你输入 API Key，勾选"记住 Key"即可
3. 悬浮窗自动出现在桌面右上角，每 30 秒刷新一次

### 方式二：从源码运行

```bash
git clone https://github.com/3142698233/deepseek-balance.git
cd deepseek-balance

# 悬浮窗（推荐 .pyw 无命令行窗口）
python deepseek_balance_widget.py
pythonw deepseek_balance_widget.py   # 更好的方式

# 命令行版
python deepseek_balance.py
```

### 命令行参数

```bash
# 悬浮窗
python deepseek_balance_widget.py --api-key sk-xxx --interval 60 --opacity 0.9

# 命令行版
python deepseek_balance.py --api-key sk-xxx --json
python deepseek_balance.py --reset-key   # 清除本地保存的 Key
```

## 自行打包 exe

```bash
pip install pyinstaller
cd deepseek-balance
python -m PyInstaller DeepSeekBalance.spec
# 生成文件：dist/DeepSeekBalance.exe
```

## 计价时段规则

| 时段 | 时间（北京时间） | 说明 |
|------|-----------------|------|
| 高峰时段 | 周一~周五（**不含中国法定节假日**）9:00-12:00、14:00-18:00 | 全价 |
| 空闲时段 | 其余全部时间：周末、中国法定节假日全天、午休、夜间 | **价格为高峰时段的一半** |

几点说明：

- **调休上班的周末仍按空闲时段计费**（如 2026-09-20 周日、2026-10-10 周六补班）。
  调休补班日必定落在周六或周日，而周末本就全天空闲，因此不需要特殊处理。
- 节假日安排数据在 [`pricing.py`](pricing.py) 的 `HOLIDAY_RANGES` 里，来源是国务院办公厅
  《关于 XXXX 年部分节假日安排的通知》，目前收录 **2025、2026** 两年。
- 每年 11 月前后国务院公布次年安排后，按同样格式补一行即可；**未收录的年份**界面会提示
  「XXXX 年假期表待更新」，此时只能按「周一~周五」粗略判定。
- 时段判定与节假日数据由 `pricing.py` 统一提供，悬浮窗和命令行版共用，不会出现两边不一致。

## 文件结构

```
deepseek-balance/
├── deepseek_balance_widget.py   # 悬浮窗主程序（tkinter GUI）
├── deepseek_balance_widget.pyw  # 无控制台启动器（双击无黑窗）
├── deepseek_balance.py          # 命令行版（纯文本输出）
├── pricing.py                   # 峰谷时段 + 中国法定节假日判定（两版共用）
├── DeepSeekBalance.ico          # 应用图标
├── DeepSeekBalance.spec         # PyInstaller 打包配置
└── README.md
```

## API Key 获取

1. 登录 [DeepSeek 平台](https://platform.deepseek.com/api_keys)
2. 创建 API Key
3. 首次运行时在弹窗中输入即可

## License

MIT
