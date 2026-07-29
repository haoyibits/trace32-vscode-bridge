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
- macOS 或 Linux 宿主机
- VS Code
- TRACE32 PowerView 和 `t32debugadapter`
- PowerView 配置中启用 Remote API：

  ```text
  RCL=NETTCP
  PORT=20000
  ```

使用前需要把 Lauterbach RCL 安装到准备运行本工具的 Python：

```bash
python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
```

Homebrew Python 如果报告 `externally-managed-environment`，使用用户级安装：

```bash
python3.13 -m pip install --user --break-system-packages \
  'lauterbach-trace32-rcl>=1.1,<2'
```

`--user` 会把包放进当前用户目录，不会写入 Homebrew 的 Python 安装目录。

`install-vscode` 会检查当前 Python 中的 RCL，并让全部 TRACE32 任务固定使用
这个 Python；它不会创建 `.venv` 或自动修改 Python 环境。

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

`.run/` 是生成目录，只包含 PowerView 日志；可随时删除，下次启动时会自动重建。
上面的 `tests/` 只存在于源码仓库，部署时会由 `install-vscode` 删除。

## 使用指南

下面的命令都在实际项目根目录执行。不要在本工具的源码仓库中执行
`install-vscode`；它面向部署副本，安装完成后会删除副本里的 `.git/` 和
`tests/`。

### 1. 准备 TRACE32

确认已经安装 PowerView 和 `t32debugadapter`，并在 TRACE32 的 `config.t32`
中启用 Remote API：

```text
RCL=NETTCP
PORT=20000
```

如果使用其他端口，必须同时修改 `trace32.toml` 中的
`trace32.rcl_port`。

### 2. 放入工具和 Flash 脚本

把本目录复制到实际项目中，并把该项目自己的 SR6P6 Flash 脚本放在
`toolbar.cmm` 旁边：

```text
actual-project/
├── .vscode/                              # install-vscode 自动创建或合并
├── trace32-vscode-bridge/
│   ├── t32.py
│   ├── trace32.toml
│   └── trace32_bridge/
│       └── cmm/
│           ├── toolbar.cmm
│           └── flash.cmm                 # 实际项目提供
├── src/
└── build/
```

本工具不附带芯片专用的 `flash.cmm`，因为 Flash 布局和算法属于实际项目。

### 3. 配置实际项目

编辑 `trace32-vscode-bridge/trace32.toml`：

```toml
[project]
root = ".."
program = "my_app"
elf = "build/my_app.elf"

[target]
cpu = "SR6P6"
cores = "1."
mem_access = "AXI"
jtag_clock = "10MHz"
dual_port = "ON"

[rtos]
config = "~~/demo/arm/kernel/freertos/freertos.t32"
menu = "~~/demo/arm/kernel/freertos/freertos.men"
show_tasks = true

[flash]
script = "trace32_bridge/cmm/flash.cmm"
args = ["DUALPORT=1", "JTAG_CLOCK=10MHz"]
```

路径规则：

- `project.root` 相对工具目录；工具放在项目内时通常使用 `..`
- `project.elf` 相对 `project.root`
- 普通 `flash.script` 路径相对工具目录
- 以 `~~` 开头的路径由 TRACE32 解析
- 将 `[rtos]` 的 `config` 和 `menu` 留空即可关闭 RTOS awareness

### 4. 安装 RCL 和 VS Code 配置

使用任意 Python 3.11 或更高版本执行。下面以 Python 3.13 为例：

```bash
python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
python3.13 -c "import lauterbach.trace32.rcl; print('RCL OK')"
python3.13 trace32-vscode-bridge/t32.py install-vscode
```

Homebrew Python 如果拒绝第一条安装命令，按“要求”一节改用带
`--user --break-system-packages` 的命令。

最后一条命令会：

1. 确认当前 Python 可以导入 `lauterbach.trace32.rcl`
2. 备份并合并 `.vscode/tasks.json` 和 `.vscode/launch.json`
3. 让所有 TRACE32 任务固定使用当前 Python
4. 删除部署副本中的开发文件和中间产物

已有的非 TRACE32 任务和调试配置会保留。备份文件位于实际项目的
`.vscode/`，名称格式为 `tasks.json.bak.<时间戳>`。

清理仅限 `trace32-vscode-bridge/`：包括 `test/`、`tests/`、工具副本自己的
`.git/`、`.github/`、`build/`、`dist/`、`*.egg-info` 和 Python 缓存。
旧版本遗留的工具内 `.venv/` 也会删除。外层实际项目的 `.git/`、工具的
`.run/`、配置、文档和运行源码不会被删除。

安装 RCL 时需要能够访问 Python 包源。复制到另一台电脑后，需要先在那台电脑
的 Python 中安装 RCL，再执行 `install-vscode`。

### 5. 安装后检查

这一步不连接板卡，只检查解析后的工程、ELF 和 TRACE32 路径：

```bash
python3.13 trace32-vscode-bridge/t32.py config
```

先处理输出中的 `MISSING`，再执行 Flash 或 Load。

### 6. 日常使用

1. 先用实际项目自己的构建系统生成 `project.elf` 指向的 ELF。
2. 在 VS Code 中执行 **Tasks: Run Task → T32: Flash**。它会启动或复用
   PowerView、运行项目的 `flash.cmm`、烧写 ELF、加载符号并运行。
3. 打开 **Run and Debug**，选择 `TRACE32: Attach` 后按 F5。隐藏的
   `T32: Start Debug Adapter` 任务会自动启动，无需手动执行。
4. 已经烧写过代码、只想刷新符号时，执行 `T32: Load ELF`；该任务不会改写
   Flash。
5. 固件初始化 SEGGER RTT 后，执行 `T32: RTT Viewer`。在终端中按
   `Ctrl-C` 退出。

如果只想启动 PowerView，可从命令行执行 `open`。由本工具新启动 PowerView
时，还会安装 `Flash` 和 `Load ELF` 两个 toolbar 按钮。

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
T32SYS=/opt/t32 python3.13 trace32-vscode-bridge/t32.py load
```

优先级为：

```text
环境变量 > trace32.toml > 平台默认值
```

## 命令行

以下命令格式仍以实际项目根目录为当前目录：

```bash
python3.13 trace32-vscode-bridge/t32.py <command>
```

| 命令 | 功能 |
|---|---|
| `flash` | 烧写 ELF、加载符号并运行 |
| `load` | 不烧写，只加载符号并运行 |
| `open` | 启动或复用 PowerView |
| `rtt` | 启动双向 RTT 终端 |
| `config` | 显示解析后的关键路径，不连接板卡 |
| `install-vscode` | 检查 RCL 并安装或更新 VS Code 配置 |
| `adapter` | 启动 DAP 代理，通常由 `TRACE32: Attach` 自动调用 |

RTT 可以绕过符号解析：

```bash
python3.13 trace32-vscode-bridge/t32.py rtt --cb 0x20000000
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
       └─ install-vscode ──> Python VS Code installer

PowerView toolbar ──> toolbar.cmm ──> 异步 Python CLI ──> RCL
```

Python 负责配置、路径、进程、网络、DAP、target setup、flash/load、Reset、
错误处理和安装。工具自身唯一的 CMM 只定义 PowerView toolbar；它使用的是没有
实用 Python 表达形式的块状 GUI DSL。工具启动新的 PowerView 并确认 RCL 端口
就绪后安装 toolbar；所有操作直接通过 Python Remote API 返回结果。

## 构建

本工具不构建项目，只消费现有 ELF。需要烧写前构建时，在实际项目的
`.vscode/tasks.json` 中给 `T32: Flash` 加入：

```jsonc
"dependsOn": ["your build task"],
"dependsOrder": "sequence"
```

## 源码开发测试

这一节只适用于工具的源码仓库；部署副本中的测试会被删除。不要为了运行测试而
执行 `install-vscode`，应单独创建开发虚拟环境：

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -v
```

测试覆盖 TOML 配置、路径解析、烧写失败清理、PowerView 启动、JSONC 合并、
DAP framing 和 session 清理。最终硬件验证还应覆盖 Flash、Load、RTT、
Pause、Restart 和断点。

## 排错

**PowerView 没有打开 RCL 端口**

检查 `config.t32` 中的 `RCL=NETTCP`、端口配置和 `.run/powerview.log`。

**显示 ELF 或 TRACE32 路径为 `MISSING`**

先构建 ELF；如果 TRACE32 不在默认的 `~/t32`，设置 `[trace32]` 路径或对应的
环境变量，然后重新执行 `t32.py config`。

**找不到 `flash.cmm`**

普通路径相对 `trace32-vscode-bridge/`。默认位置应为
`trace32_bridge/cmm/flash.cmm`。

**VS Code 报告缺少 RCL**

确认 RCL 安装在执行 `install-vscode` 的同一个 Python 中，然后重新执行：

```bash
python3.13 -m pip install 'lauterbach-trace32-rcl>=1.1,<2'
python3.13 trace32-vscode-bridge/t32.py install-vscode
```

**TRACE32 操作超时**

查看 PowerView AREA 窗口。超时由 `trace32.operation_timeout` 控制。

**RTT 运行时内存访问失败**

确认目标已 attach，并且 `target.dual_port = "ON"` 对当前架构有效。

**Locals 为空**

DAP 代理会屏蔽已知会导致部分 `t32debugadapter` 版本退出的 Locals 请求。
Watch、寄存器、调用栈、断点和单步仍正常转发。
