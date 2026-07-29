# trace32-vscode-bridge

TRACE32 PowerView 与 VS Code 的通用调试工装。宿主侧全部使用 Python；芯片相关
flash CMM 由实际项目提供。

*English: [README.md](README.md)*

提供三个可见任务和一个调试配置：

| VS Code | 功能 |
|---|---|
| `T32: Flash` | 烧写现有 ELF、加载符号并运行；不负责构建 |
| `T32: Load ELF` | 不烧写，只加载 ELF 符号并运行 |
| `T32: RTT Viewer` | 双向 SEGGER RTT 终端 |
| `TRACE32: Attach` | 启动 DAP 兼容代理并 attach |

## 要求

- Python 3.11 或更高版本
- TRACE32 PowerView 和 `t32debugadapter`
- PowerView 配置中启用 Remote API：

  ```text
  RCL=NETTCP
  PORT=20000
  ```

安装 Python 依赖：

```bash
python3 -m pip install -e ./trace32-vscode-bridge
```

不再需要 Bash 或 Node.js。

## 目录结构

```text
trace32-vscode-bridge/
├── pyproject.toml
├── trace32.toml                  # 项目和 TRACE32 配置
├── t32.py                         # 直接运行入口
├── trace32_bridge/
│   ├── cmm/                       # PowerView 内执行
│   │   └── toolbar.cmm
│   ├── cli.py
│   ├── config.py
│   ├── powerview.py
│   ├── remote.py
│   ├── target.py
│   ├── rtt.py
│   ├── dap/
│   │   ├── protocol.py
│   │   └── proxy.py
│   └── vscode/
│       ├── installer.py
│       └── jsonc.py
├── vscode/
│   ├── tasks.json
│   └── launch.json
└── tests/
```

`.run/` 是生成目录，包含 PowerView 日志。

## 接入实际项目

1. 把本目录放进实际项目，例如：

   ```text
   actual-project/
   ├── trace32-vscode-bridge/
   ├── src/
   └── build/
   ```

2. 编辑 `trace32-vscode-bridge/trace32.toml`：

   ```toml
   [project]
   root = ".."
   program = "my_app"
   elf = "build/my_app.elf"

   [target]
   cpu = "STM32F407ZG"
   cores = "1."
   mem_access = "AXI"
   jtag_clock = "10MHz"
   dual_port = "ON"

   [rtos]
   config = "~~/demo/arm/kernel/freertos/freertos.t32"
   menu = "~~/demo/arm/kernel/freertos/freertos.men"
   show_tasks = true

   [flash]
   script = "~~/demo/arm/flash/stm32f4xx.cmm"
   args = ["CPU=STM32F407ZG", "DUALPORT=1"]
   ```

   `project.elf` 相对 `project.root`；普通 flash 路径相对工具目录。以 `~~`
   开头的路径交给 TRACE32 解析。

3. 安装或更新 VS Code 配置：

   ```bash
   python3 trace32-vscode-bridge/t32.py install-vscode
   ```

   已有的 `.vscode/tasks.json` 和 `.vscode/launch.json` 会先备份再合并。
   非 TRACE32 项目保持不变。生成的任务会记录执行安装命令时使用的 Python
   解释器，确保 VS Code 和 PowerView toolbar 使用已经安装依赖的同一环境。

4. 运行 `T32: Flash` 或 `T32: Load ELF`，然后按 F5 选择
   `TRACE32: Attach`。

## 配置

完整配置位于 `trace32.toml`，分成：

- `[project]`：工程根目录、程序名、ELF
- `[target]`：CPU、核、内存访问、JTAG 时钟、dual-port
- `[rtos]`：可选的 RTOS awareness 配置、菜单和任务窗口
- `[flash]`：实际项目提供的 flash CMM 及参数
- `[trace32]`：安装路径、程序名、端口和超时
- `[rtt]`：RTT 符号、地址覆盖和轮询周期

TRACE32 安装目录默认是 `~/t32`。标准安装下，PowerView、配置文件和 debug
adapter 都会自动推导。临时覆盖支持：

```bash
T32SYS=/opt/t32 python3 trace32-vscode-bridge/t32.py load
```

优先级为：

```text
环境变量 > trace32.toml > 平台默认值
```

## 命令行

```bash
python3 t32.py flash
python3 t32.py load
python3 t32.py open
python3 t32.py rtt
python3 t32.py adapter
python3 t32.py config
python3 t32.py install-vscode
```

RTT 可以绕过符号解析：

```bash
python3 t32.py rtt --cb 0x20000000
```

## Flash 扩展点

本工具不提供具体芯片的 flash CMM。实际项目配置的脚本需要遵循 Lauterbach
`PREPAREONLY` 约定：

1. 连接并配置目标。
2. 声明 flash 区域。
3. 收到 `PREPAREONLY` 时停止，不执行烧写。

之后 Python 通过 RCL 统一执行：

```text
FLASH.ReProgram ALL /Erase
Data.LOAD.Elf <ELF>
FLASH.ReProgram OFF
SYStem.Down
SYStem.Up
```

## 工作原理

```text
VS Code/CLI
    └─ Python CLI
       ├─ flash/load ──> Python RCL ──> 项目 flash.cmm PREPAREONLY
       ├─ open ────────> PowerView + Python 安装 toolbar
       ├─ rtt ─────────> Python RCL
       ├─ adapter ─────> Python DAP proxy ──> t32debugadapter
       └─ install ─────> Python VS Code installer

PowerView toolbar ──> toolbar.cmm ──> 异步 Python CLI ──> RCL
```

Python 负责配置、路径、进程、网络、DAP、target setup、flash/load、Reset、
错误处理和安装。工具自身唯一的 CMM 只定义 PowerView toolbar；它使用的是没有
实用 Python 表达形式的块状 GUI DSL。Python 在 RCL 端口就绪后安装 toolbar，
所有操作直接通过 Python Remote API 返回结果。

## 构建

本工具不构建项目，只消费现有 ELF。需要烧写前构建时，在实际项目的
`.vscode/tasks.json` 中给 `T32: Flash` 加入：

```jsonc
"dependsOn": ["your build task"],
"dependsOrder": "sequence"
```

## 测试

不连接硬件即可运行宿主侧测试：

```bash
python3 -m unittest discover -v
```

测试覆盖 TOML 配置、路径解析、烧写失败清理、PowerView 启动、JSONC 合并、
DAP framing 和 session 清理。最终硬件验证还应覆盖 Flash、Load、RTT、
Pause、Restart 和断点。

## 排错

**PowerView 没有打开 RCL 端口**

检查 `config.t32` 中的 `RCL=NETTCP`、端口配置和 `.run/powerview.log`。

**TRACE32 操作超时**

查看 PowerView AREA 窗口。超时由 `trace32.operation_timeout` 控制。

**RTT 运行时内存访问失败**

确认目标已 attach，并且 `target.dual_port = "ON"` 对当前架构有效。

**Locals 为空**

DAP 代理会屏蔽已知会导致部分 `t32debugadapter` 版本退出的 Locals 请求。
Watch、寄存器、调用栈、断点和单步仍正常转发。
