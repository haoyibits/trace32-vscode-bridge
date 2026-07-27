# trace32_auto

TRACE32 PowerView + VS Code 的通用调试工装。换新工程时**只改 `config.env`**。

*English: [README.md](README.md)*

提供三条流程：

| VS Code | 做什么 |
|---|---|
| 任务 `T32: Flash + Debug` / 调试配置 `1. Flash + Debug` | 烧写 → 加载符号 → 运行 → 拉起 DAP adapter |
| 任务 `T32: Load + Debug` / 调试配置 `2. Load + Debug` | 不烧写，attach 已在跑的目标并加载符号 |
| 任务 `T32: RTT Viewer` | 双向 SEGGER RTT 终端（printf 输出 + CLI 输入） |

按 F5 选调试配置会自动跑对应的 task，然后 attach，直接在 VS Code 里下断点、单步。

**构建不归这套工装管。** 它不关心你的工程是 Rust 还是 C，只消费一个已经编好的
ELF。要在烧写前重新构建，见[串上你的构建](#串上你的构建)。

---

## 目录结构

```text
trace32_auto/
├── config.env                 ← 换工程时唯一要改的文件
├── install.sh                 ← 把 vscode/ 模板装进工程的 .vscode/
├── vscode/
│   ├── tasks.json
│   └── launch.json
└── scripts/
    ├── t32.sh                 ← 唯一入口，被 VS Code task 调用
    ├── startup.cmm            ← PowerView 启动脚本
    ├── load_config.cmm        ← 加载生成的 .run/config.cmm
    ├── target.cmm             ← flash / load 两个动作
    ├── toolbar.cmm            ← PowerView 上的两个按钮
    ├── flash/                 ← 本地 flash 脚本（通常是空的）
    └── rtt_viewer.py          ← RTT 终端
```

`.run/` 是生成目录（PowerView 日志、握手标记、由 `config.env` 生成的
`config.cmm`），已被 `.gitignore` 忽略。

### 路径

除了 TRACE32 安装位置，这里没有任何东西绑死在某台机器上 —— 而 TRACE32
按定义就装在工程之外：

| 谁 | 怎么解析 |
|---|---|
| 脚本自身 | 靠 `${BASH_SOURCE[0]}` / TRACE32 的 `~~~~` 前缀，放哪都能找到自己 |
| `PROJECT_ROOT`、`ELF` | 分别相对 `trace32_auto/` 和 `PROJECT_ROOT` |
| 自带 flash 脚本 | `~~/demo/...`，`~~` 是 TRACE32 自己的安装前缀 |
| VS Code task | `${workspaceFolder}/trace32_auto/scripts/t32.sh` |
| **TRACE32 工具链** | **`T32_SYS`，绝对路径** —— 默认 `$HOME/t32` |

`T32_BIN`、`T32_REM`、`T32_CONFIG`、`T32_DEBUG_ADAPTER` 全部由 `T32_SYS`
加自动探测的 host 目录推导出来，所以标准安装一个绝对路径都不用写。只有安装
布局不标准时才需要单独指定某一项。临时换一套安装、不想改文件：

```bash
T32SYS=/opt/t32 ./trace32_auto/scripts/t32.sh load
```

`./trace32_auto/scripts/t32.sh config` 会把所有解析后的路径打出来，
并标出不存在的那些。

---

## 接入一个新工程

1. 把整个 `trace32_auto/` 目录拷进工程根目录：

   ```bash
   cp -r /path/to/trace32_auto <your-project>/
   ```

2. 编辑 `<your-project>/trace32_auto/config.env`。通常只需要改这几项：

   ```sh
   PROGRAM_NAME="my_app"                 # 必须等于 ELF 文件名（不含扩展名）
   ELF="build/.../my_app.elf"            # 相对 PROJECT_ROOT
   T32_CPU="STM32F407ZG"
   T32_FLASH_SCRIPT="~~/demo/arm/flash/stm32f4xx.cmm"   # 留空 = 不烧写
   ```

3. 安装 VS Code 配置：

   ```bash
   ./trace32_auto/install.sh
   ```

4. 确认 `~/t32/config.t32` 里有 Remote API：

   ```text
   RCL=NETTCP
   PORT=20000
   ```

5. 装一次 Python 依赖（RTT 用）：

   ```bash
   python3 -m pip install lauterbach-trace32-rcl
   ```

### 串上你的构建

工装自己不构建任何东西。要在烧写前重新构建，在 `.vscode/tasks.json` 里让
flash task 依赖工程已有的构建 task：

```jsonc
{
    "label": "T32: Flash + Debug",
    "command": "${workspaceFolder}/trace32_auto/scripts/t32.sh",
    "args": ["flash"],
    "dependsOn": ["cargo build"],     // 或 "make"、"CMake: build" ……
    "dependsOrder": "sequence"
}
```

这一行在随附的 `tasks.json` 里已经写好，只是注释掉了。被依赖的 task 可以定义在
同一个文件里，也可以来自插件（rust-analyzer、CMake Tools 等）。
`"dependsOrder": "sequence"` 是让 VS Code 等构建跑完再烧写的关键，
否则两个会并发。

如果构建产物换了位置，改 `config.env` 里的 `ELF=` 一行即可，工装其它部分
不关心。

### 换芯片

`T32_FLASH_SCRIPT` 可以直接指向 Lauterbach 自带的 flash 脚本，所以换芯片
通常就是改一行：

```sh
T32_FLASH_SCRIPT="~~/demo/arm/flash/stm32f4xx.cmm"
T32_FLASH_ARGS="CPU=STM32F407ZG DUALPORT=1"
T32_CPU="STM32F407ZG"
```

`~~` 是 TRACE32 安装目录。`target.cmm` 按 Lauterbach 的 `PREPAREONLY` 约定
调用脚本 —— "连上、配好目标、声明 flash，但什么都不烧" —— 然后自己执行烧写
序列，这段对所有芯片都一样：

```text
FLASH.ReProgram ALL /Erase
Data.LOAD.Elf <ELF>
FLASH.ReProgram OFF
SYStem.Down / SYStem.Up
```

`PREPAREONLY` 在自带脚本里基本是通用的（`~~/demo/arm/flash` 下 839 个里约 770
个支持，PowerPC / TriCore / RISC-V 比例类似），所以大多数芯片根本不用新写脚本。
选定脚本后看它头部注释支持哪些参数，填进 `T32_FLASH_ARGS`。

### 换架构

仍然只改 `config.env`，但不止一行 —— `T32_EXE` 决定用哪个 PowerView 可执行文件。
以 Infineon AURIX 为例：

```sh
T32_EXE="t32mtc-qt"
T32_CPU="TC387QP"
T32_MEMACCESS=""                                      # TriCore 没有这条命令
T32_FLASH_SCRIPT="~~/demo/tricore/flash/tc38x.cmm"
T32_FLASH_ARGS="CPU=TC387QP DUALPORT=1"
```

`T32_CPU`、`T32_CORES`、`T32_MEMACCESS`、`T32_DUALPORT` 留空就跳过对应命令，
就是为了让缺少某条命令的架构也能跑。`SYStem.Option.DUALPORT` 和 `CORE.ASSIGN`
在 TriCore 上是有的，所以 RTT 和选核都能沿用；`SYStem.MemAccess` 没有，
所以上面留空。

### 改 `config.env` 解决不了的

- 自带脚本**不支持 `PREPAREONLY`**、或者需要打补丁的芯片 —— 比如少了关看门狗
  这一步导致擦除中途芯片自己复位、flash 算法需要换一块 RAM 窗口、要绕某条
  勘误。做法是把厂商脚本拷进 `scripts/flash/` 打上补丁，确保声明结束后有
  `IF &param_prepareonly / ENDDO PREPAREDONE`，然后让 `T32_FLASH_SCRIPT`
  指向你这份拷贝。细节见
  [scripts/flash/README.md](scripts/flash/README.md)。
- **RTT** 需要固件里编进 SEGGER RTT，以及架构支持运行时内存访问。两者缺一，
  就只用 flash 和 load 两条流程，跳过 RTT task。

---

## 命令行用法

`scripts/t32.sh` 也可以直接用：

```bash
./trace32_auto/scripts/t32.sh flash     # 烧写 + 符号 + 运行 + adapter
./trace32_auto/scripts/t32.sh load      # 符号 + 运行 + adapter
./trace32_auto/scripts/t32.sh rtt       # RTT 终端
./trace32_auto/scripts/t32.sh open      # 只开 PowerView
./trace32_auto/scripts/t32.sh config    # 打印解析后的配置
./trace32_auto/scripts/t32.sh stop      # 停掉本脚本启动的 DAP adapter
```

PowerView **只会被启动一次**：之后每次调用都通过 RCL 复用已在运行的实例，
不会再弹一个新窗口。

---

## 工作原理

```text
VS Code ──dependsOn──> 你自己的构建 task           (cargo / make / cmake ...)
        └───task─────> t32.sh ──┬─> PowerView  -s startup.cmm         (首次启动)
                                ├─> t32rem --RCL 20000--> target.cmm  (烧写/符号)
                                └─> t32debugadapter --port 58870      (DAP)

VS Code ──DAP 58870──> t32debugadapter ──RCL 20000──> PowerView
rtt_viewer.py ─────────────────────────RCL 20000──> PowerView
```

几个设计点：

- **配置只有一份。** `t32.sh` 读 `config.env`，翻译成 `.run/config.cmm`
  里的 `&CFG_*` 全局宏。CMM 侧不做字符串解析（PRACTICE 的宏展开是纯文本的，
  值里带引号会直接把表达式弄坏）。
- **`t32rem` 是异步的**：命令排进队列就返回。所以 `target.cmm` 结束时会写
  `.run/done`（内容 `OK` 或 `FAIL: ...`），`t32.sh` 阻塞等这个文件，从而做到
  "烧完了才 attach"。`startup.cmm` 同理写 `.run/ready`。
- **符号只加载不覆盖**：`Data.LOAD.Elf /NoCODE`，绝不动正在跑的目标内存。
- **`SYStem.Option.DUALPORT ON`** 是 RTT 的前提，RTT viewer 靠运行时 AXI
  访问读写 ring buffer，CPU 不会被停下来。

---

## RTT

当前 PowerView 没有原生 `TERM.METHOD RTT`，`rtt_viewer.py` 自己实现了标准
RTT host 逻辑：

1. 从 ELF 符号解析 `_SEGGER_RTT`（`PROGRAM_NAME` 用于定位符号表）。
2. 用 `E:` 运行时内存访问读 channel 0 的 `WrOff/RdOff`。
3. 读完上行 ring buffer 后更新 `RdOff`。
4. 键盘输入写进下行 ring buffer，最后才更新 `WrOff`。

一个 RTT 通道只能有一个 host 消费者，所以不要同时开两个 viewer。

字节流原样透传，viewer 不做任何着色或改写 —— 目标想输出什么 ANSI 转义序列
是目标自己的事。

符号还没加载时可以跳过解析，直接给地址：

```bash
./trace32_auto/scripts/t32.sh rtt --cb 0x20000000
```

---

## 排错

**"PowerView did not open RCL port 20000"**
`config.t32` 里没有 `RCL=NETTCP` / `PORT=20000`，或者端口被别的进程占了。

**"TRACE32 script did not finish within 600s"**
`t32rem` 把命令发出去了但 `target.cmm` 没写完成标记 —— 多半是烧写报错停在了
PowerView 的 AREA 窗口里，去那边看具体错误。`T32_TIMEOUT` 可在 `config.env` 调。

**"path must not contain spaces"**
TRACE32 用空格分隔 CMM 参数，工程路径/ELF 路径里不能有空格。

**RTT 报 run-time memory access failed**
确认目标已 attach 且 `SYStem.Option.DUALPORT ON` 已生效（`load` 动作会自动设）。

**Variables 面板报 `Invalid letter code`**
`t32debugadapter` 在某些 FreeRTOS 中断栈帧上读局部变量会出这个错并退出。
把 Run and Debug 里的 `Variables` 区域折叠起来，断点/单步/调用栈不受影响，
变量临时到 PowerView 里看。
