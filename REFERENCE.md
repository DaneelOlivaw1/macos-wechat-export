# 完整参考：原理、命令与边界（macOS 微信 4.x 本地取钥、读取、增量、发送）

这是一套可下载、编译和运行的本地工具，覆盖本次从空白截图排障到真实数据库读写核验的全过程。**读取使用 SQLCipher 数据库，发送使用微信界面；不通过修改数据库发送消息。** 不需要把截图、密钥或聊天上传给远程模型。

实测：Apple Silicon、macOS 15.6.1、微信 4.1.15。取得 26 个数据库的有效密钥，逐库成功查询表结构；读出了既有测试消息，也在恢复原版后读到了新发送的消息。源码、安装步骤、测试与失败处理均在本仓库中。

**这是明确限定环境的复现方案，不是“任何系统、任何微信版本必定成功”的保证。** 密钥捕获仅实现原生 arm64；Intel、Rosetta、其他微信版本及企业安全策略未验证。改动后的通用封装与此前人工执行步骤的验证区别见 `VALIDATION.md`。

## 从哪里开始

首次使用请按 **[QUICKSTART.md](QUICKSTART.md)** 从下载、安装、确认账号，一直做到文件传输助手发送和增量确认验收。本页后续章节保留原理和命令参考，不必与快速开始重复执行。

| 你要做什么 | 阅读入口 |
| --- | --- |
| 首次安装并完整验收 | [QUICKSTART.md](QUICKSTART.md) |
| 判断是否需要取钥、比较初始化路线 | [KEY_GUIDE.md](KEY_GUIDE.md) |
| 日常开始、审阅、发送恢复、停止 | [OPERATIONS.md](OPERATIONS.md) |
| 安装媒体依赖、理解图片/语音/视频结果 | [MEDIA_GUIDE.md](MEDIA_GUIDE.md) |
| 接入自己的代理、记录审阅进度、避免重复回复 | [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) |
| 截图、权限、标题、布局标定 | [UI_GUIDE.md](UI_GUIDE.md) |
| 命令失败或结果不确定 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 查看实测证据与尚未验证范围 | [VALIDATION.md](VALIDATION.md) |

## 能做什么，以及需要自己补什么

| 能力 | 已有实现与边界 |
| --- | --- |
| 磁盘读取 | SQLCipher 只读 DB + WAL；需要本人账号的逐库密钥 |
| 文本发送 | UI 单行短文本，最长 200 字；数据库核验唯一全文及非零服务器 ID；不代表对方已读 |
| 增量消息 | init/check/watch/ack；每库每批最多 200 条，调用方审阅后确认 |
| 语音 | 微信已有转写或本机 SILK 解码 + MLX Whisper；质量过滤不保证文字准确 |
| 图片 | DAT/WXGF 静态路径；可能只有缩略图或第一帧，需实际查看 |
| 普通视频/文件视频 | 本地容器探测、最多 24 个抽样帧和音轨；不等于连续动作分析 |
| 视频号/引用/其他类型 | 没有通用自动理解实现；需授权的界面审阅或保留阻碍 |
| 自动回复 | 自行接入代理和调度器，并单独授权；下载本仓库不会启动监听 |
| 审阅账本、阻碍退避、完整变化检测 | 消费者设计要求/改进建议，发布 CLI 尚未自动实现 |

读取不修改消息数据库，发送走界面。工具本身不上传正文或音频；如果把输出交给云端代理，内容会进入该代理服务。本地解密/ASR 不代表整个回复链路都在本机。

命令中的 `self_id` 是公开 Reader 返回的 `sender_id`（用户名字符串），不是数字 `real_sender_id`。`chat_id` 是会话 username；群显示名、带人数的 UI 标题、数据库昵称/备注各有用途，详见 QUICKSTART。

## 1. 文件与整体流程

| 文件 | 作用 |
| --- | --- |
| `QUICKSTART.md` | 从安装到发送/增量确认的顺序验收路线 |
| `KEY_GUIDE.md` | 最新取钥决策：已有密钥复用、首次初始化、root EPERM 实测、第三方方案与未验证方向 |
| `readonly_port_probe.c` / `probe_readonly_port.sh` | 可选的最小只读权限诊断，不取钥、不修改微信或系统设置 |
| `bootstrap_keys.py` | 检查前提、复制微信、只重签副本、启动捕获、恢复原版 |
| `capture_keys.py` | LLDB 启动一个指定子进程，捕获匹配数据库盐值的派生参数，校验后私密保存密钥 |
| `sqlcipher_probe.py` | SQLCipher C API 的只读封装、密钥验证及人工 WAL 测试 |
| `wechat_db.py` | 联系人解析、历史消息、增量消息、持久化游标与确认 |
| `WeChatUI.swift` / `Send.swift` | ScreenCaptureKit 截图修复、OCR、受控鼠标键盘发送与去重日志 |
| `send_verified.py` | 界面发送后独立查询数据库；不确定结果不自动重发 |
| `media_pipeline.py` / `check_inbox.py` | 可选的本地媒体准备、仅新消息的收件箱，均不发送或自动 ack |
| `media-config.example.json` / `requirements-media.txt` | 不含真实账号的配置模板、实测媒体依赖 |
| `MEDIA_GUIDE.md` / `OPERATIONS.md` / `test_media.py` | 媒体原理、完整日常流程、人工媒体回归 |
| `disk_inventory.py` | 无密钥时检查数据库/WAL 元数据 |
| `test_db.py` / `Tests.swift` | 人工数据库、密钥捕获、OCR 和操作日志测试 |
| `UI_GUIDE.md` | UI 工具详细说明、布局校准及截图故障处理 |
| `AGENT_PLAYBOOK.md` | 交给代理执行的监听与适时回复流程 |
| `VALIDATION.md` / `TROUBLESHOOTING.md` | 验证范围、限制与恢复步骤 |

```text
首次：原版正常退出 → 临时副本重签 → LLDB 启动副本 → 登录时捕获派生参数
     → 对照数据库第一页 HMAC → 私密保存每库密钥 → 关闭副本 → 恢复原版
日常：原版照常运行 → SQLCipher 只读 DB + WAL → 新消息/历史消息 JSON
发送：人工选定聊天 → 核对标题和空草稿 → 输入并核对 → 回车
     → 独立查询同一会话新增消息 → 核对发送者、全文、唯一性和服务器 ID
```

## 2. 安装与前置条件

需要 macOS 14+、Apple Silicon、微信已登录过且本地有聊天记录、Xcode Command Line Tools、Homebrew。完整数据库工具使用 **Python 3.14+**（标准库 `compression.zstd`）；LLDB 捕获部分单独使用 Apple 自带 `/usr/bin/python3`，不可混用 Homebrew Python 的 LLDB ABI。

克隆本仓库（或在仓库页面 Download ZIP）：

```sh
git clone https://github.com/DaneelOlivaw1/macos-wechat-export.git
cd macos-wechat-export
xcode-select -p
# 上一步提示不存在时，先运行 xcode-select --install，完成系统安装后再继续。
brew install python@3.14 sqlcipher
python3.14 --version
sh build.sh
sh test.sh
python3.14 test_db.py
```

基础文本/密钥/UI工具不需要 pip 包。可选媒体模块另外使用 Python 3.12 隔离环境及 pip 依赖，见 `MEDIA_GUIDE.md`。`SQLCIPHER_LIBRARY` 可指向自定义的 SQLCipher 动态库；默认查找 Apple Silicon/Intel Homebrew 路径。不要指向系统的普通 SQLite。

执行 UI 读取/发送前，在系统设置中给运行命令的 Terminal/iTerm/代理宿主开启**屏幕录制**和**辅助功能**，然后运行：

```sh
./wechat-ui doctor
```

数据库日常读取不需要截图权限，但需要当前进程能访问微信数据目录。若 macOS 拒绝目录访问，由用户在系统界面处理所需权限；工具不自行修改权限。

## 3. 首次获取密钥

**已有密钥时跳过本节，先运行 `python3.14 wechat_db.py verify`。** 使用非默认目录时，在 `verify` 前传入正确的 `--key-file` 和必要的 `--db-root`。微信普通重启不等于密钥失效；只有核实密钥缺失/失效，才重新初始化。见 `KEY_GUIDE.md`。

### 先了解会发生什么

此步骤会中断当前微信进程。先结束发送、保存草稿，然后在微信菜单正常退出。脚本不会退出账号，但副本启动后可能要求点击 Enter Weixin、手机确认或重新扫码。

只重签工作目录里的临时副本，原版 `/Applications/WeChat.app` 不改，SIP 不改，不索取或保存管理员密码。本机无需 sudo 即可成功；其他机器如果调试权限被拒绝，停止并参考故障表，**不要随手关闭 SIP 或用 sudo 启动整套工具**。

临时副本仍访问原账号的数据，**不是独立账号沙箱**；微信自身可能更新缓存、数据库或登录状态。调试与副本签名可能被应用感知，不能承诺不被检测或没有账号风险。捕获结束时，提取器会终止它自己启动的调试子进程，所以不要在副本中编辑草稿或继续聊天。

### 推荐执行

```sh
# 只读检查：不获取密钥，不读取正文。
python3.14 disk_inventory.py

# 可选：只对人工 C 程序和人工数据库测试 LLDB，不接触微信。
python3.14 test_db.py --lldb

# 确认微信已从菜单正常退出后执行。
python3.14 bootstrap_keys.py --acknowledge-debug-copy
```

默认使用 `.wechat-local/`，目录权限 0700，密钥 `.wechat-local/keys.json` 权限 0600。**不要提交或上传这个目录。** 输出只包含进度、进程 ID 和验证数量，密钥不写到标准输出，也不放进命令行参数。

出现临时微信窗口后，在本机进入自己的账号；等待 `verified_progress` 和 `keys_saved_privately`。默认最多 180 秒；手机登录较慢时可用 `--timeout 300`。若发现多个账号，必须明确选择自己要读取的账号：

```sh
python3.14 bootstrap_keys.py --acknowledge-debug-copy \
  --db-root '/你的微信账号目录/db_storage' \
  --state-dir './private-bootstrap-2'
```

不要照抄示例路径。正常路径形如：

```text
~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<账号目录>/db_storage
```

脚本拒绝覆盖已有密钥或已有副本。重试请用新的 `--state-dir`；后续读取同时传入相应 `--key-file`，多账号时还要传相同的 `--db-root`。无有效数据库时先使用原版登录并同步记录。

成功后，脚本检查原版签名输出仍一致，注销临时副本的 LaunchServices 注册，将副本改名为 `WeChat-trial.disabled`，通过**原版可执行文件的确切路径**启动原版，避免同 bundle ID 的两个应用被混淆。请在界面确认原版可正常使用；`original_launch_requested` 只是启动请求，不是登录成功证明。

### 密钥到底怎样取得

不是从磁盘文件中暴力破解，也不是网络拦截。微信启动并打开数据库时，会进行密钥派生；提取器在自己启动的调试子进程内观察 `CCKeyDerivationPBKDF`。

arm64 的参数包含口令/输入指针与长度、盐值与长度、PRF、迭代次数。只接受 SHA-512（CommonCrypto 的 PRF 枚举值 **5**）、16 字节盐和已知的迭代组合，并与目标数据库头部盐值匹配：

- 256000 轮路径：从匹配输入派生 32 字节数据库密钥。
- 2 轮路径：识别由数据库盐 XOR `0x3a` 得到的 HMAC 派生盐，其 32 字节输入是候选数据库密钥。
- 对候选值验证数据库第一页的 HMAC；不通过的候选不保存。保存的是逐数据库的密钥映射，不能假设所有库共用一把钥匙。

本实现只覆盖实测的 4096 字节 SQLCipher 4 页面格式。布局或加密参数变化会导致验证失败，不能删除校验“强行兼容”。提取器不扫描整个进程内存，不附加任意现有进程，不执行 `killall`，只清理自己创建的进程。

这条路线参考了 [wxkey 的对应版本实现](https://github.com/r266-tech/wxkey/tree/01e96fa58ce3ff061dce83e4c36f62104ebc6b16)和 [fomomo 的副本流程](https://github.com/nishuzumi/fomomo/blob/c0ea14f419f62a498a14bd89581de124b3e462dd/scripts/setup-keys.sh)。本仓库是为本次流程编写的独立小工具，不调用它们的 bootstrap，也不继承其凭据保存或全局进程清理行为。

## 4. 验证密钥、从硬盘读取消息

```sh
python3.14 wechat_db.py verify
python3.14 wechat_db.py read --chat-id filehelper --limit 10
```

`verify` 会实际打开各库并查询表结构，不只是检查密钥格式。数据库读取通过 SQLCipher 的 `SQLITE_OPEN_READONLY` 和 `query_only` 进行；正文读取前已验证解密可用。参见 [SQLCipher API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)。

读取文件包括主 DB 和 SQLite 自动处理的 WAL。不能只拷贝 `.db` 而漏掉 `-wal`，也不能仅盯主库修改时间。读取不会主动写消息或执行 checkpoint；WAL 读者可能涉及 SHM 协调，因此不是“不触碰任何辅助文件”。参见 [SQLite WAL 文档](https://www.sqlite.org/wal.html)。

返回内容包括库名、local_id、server_id、时间、发送者内部 ID、文本。压缩文本用本地 Zstandard 解压；群消息的发送者前缀会剥离。基础 `wechat_db.py` 对媒体、语音、引用/XML 消息只返回类型和省略标记，不输出 XML 内的附件密钥或下载凭据。可选 `check_inbox.py` / `media_pipeline.py` 在本机另行准备支持的媒体，见 `MEDIA_GUIDE.md`；不能把基础读取返回的 `text: null` 当作空消息。

消息表通过 `Msg_ + MD5(会话内部 ID)` 定位，遍历消息分库。显示名不是唯一 ID；先解析，再确认唯一匹配：

```sh
python3.14 wechat_db.py resolve '目标联系人或群的准确名称'
python3.14 wechat_db.py read --chat-id '解析结果中的 username' --limit 20
```

同名匹配多于一个时命令返回非零，不能直接取第一个。`--db-root` 和 `--key-file` 是全局参数，必须放在 `read/resolve/verify/check` **前面**。

正常读取不再需要重启或调试微信。账号迁移、重建数据库、轮换密钥或客户端改版后，重新验证再使用。

## 5. 发送：先做文件传输助手验收

发送一直经由微信 UI，**没有直接 INSERT 数据库，也没有微信私有发送协议实现**。

1. 在原版微信中人工打开文件传输助手，确认没有未发送草稿/附件，关闭群详情侧栏等附加面板，窗口完整处于同一显示器。
2. 运行 UI 读取并保存本地截图，确认当前标题和编辑区分界线。
3. 给出真实的 `composer-top = 编辑区分界线距窗口顶部 / 窗口高度`。实测示例为 0.695，不适用于所有布局。

```sh
./wechat-ui read --chat 'File Transfer' --snapshot ./private-layout.png
# 中文界面请改用实际标题，例如“文件传输助手”，不要猜。
```

`private-layout.png` 包含微信窗口，勿上传。底层修复顺序是先启动按应用过滤的 ScreenCaptureKit 流，再将运行中的流更新为主窗口过滤器。本机单次截图和直接窗口流均曾返回空白，这个顺序成功。它不是保证所有版本有效的通用补丁；详见 `UI_GUIDE.md` 和 [Apple 的相关讨论](https://developer.apple.com/forums/thread/808016)。

先只发送到自己的文件传输助手。写一条唯一测试文本，不带结尾换行：

```sh
umask 077
printf '%s' '本地读写验收 demo-001' > .wechat-local/message.txt
./wechat-ui send --chat 'File Transfer' \
  --text-file .wechat-local/message.txt --id demo-001 \
  --composer-top 0.695 --state-dir .wechat-local/send-state --dry-run

# 预检通过后，去掉 --dry-run 执行一次。
./wechat-ui send --chat 'File Transfer' \
  --text-file .wechat-local/message.txt --id demo-001 \
  --composer-top 0.695 --state-dir .wechat-local/send-state

python3.14 wechat_db.py read --chat-id filehelper --limit 5
```

确认该测试消息完整、仅出现一次。**该行的 sender_id 字符串就是下一步所需的 self_id，不能填数字 real_sender_id**；不要填昵称，不要选别人的发送者 ID。若 UI 返回 `send_result_uncertain`，先查数据库，不能换新 ID 再发一次。

### 独立数据库核验的发送封装

拿到自己内部 ID 后，换一个新的测试内容和操作 ID：

```sh
printf '%s' '数据库独立核验 demo-002' > .wechat-local/message.txt
python3.14 send_verified.py \
  --chat-id filehelper --self-id '上一步自己消息的 sender_id' \
  --title 'File Transfer' --text-file .wechat-local/message.txt \
  --id demo-002 --composer-top 0.695 --dry-run

# 移除 --dry-run 执行；其余参数完全相同。
python3.14 send_verified.py \
  --chat-id filehelper --self-id '上一步自己消息的 sender_id' \
  --title 'File Transfer' --text-file .wechat-local/message.txt \
  --id demo-002 --composer-top 0.695
```

封装会保存发送前游标、运行 UI 预检和发送，再查指定会话的新行：必须是自己发送、正文完全一致、唯一匹配，且 `server_id` 非零，才返回 `sent_db_verified`。这不是对方已读证明，也不是官方消息送达 API。

同一个操作 ID 再运行，只核验/返回已发送，不再触发 UI 发送；出现不确定结果时可带 `--verify-only` 查询原尝试。**不要修改文本文件或更换 ID 盲重试**；参数与原操作不一致会被拒绝。只有核验完全明确后才创建下一条独立操作。

实测存在两种不同失败：文字实际截断，以及全文已输入但 OCR 没匹配。均不得直接重跑输入。人工或已获授权的交互代理应查看目标群及完整草稿，仅修正本次工具自己的草稿；逐字确认后手动发送，再对原 ID 使用 `--verify-only`。详见 `OPERATIONS.md`。

给真实联系人或群发送时，先人工选择实际会话，确认其与 `--chat-id` 对应，`--title` 使用当前标题（群人数可能变化）。OCR 标题不能区别同名会话，数据库的事后核验也无法撤回错发，因此不要无人值守地盲选会话。群聊的长气泡视觉验证实测出现过不确定结果，数据库核验提供了独立证据。

## 6. 增量监听与适时回复

先建立基线；历史消息不会自动当作新消息：

```sh
python3.14 wechat_db.py init \
  --chat-id '目标会话内部 ID' --self-id '自己的内部 ID' \
  --state .wechat-local/group-state.json
python3.14 wechat_db.py check --state .wechat-local/group-state.json
python3.14 wechat_db.py watch --state .wechat-local/group-state.json --seconds 3600 --interval 1
```

`check` 返回新行、是否自己发送、`incoming_count` 和 `ack_cursor`。`watch` 是本地有限时长进程，只有发现新批次才输出 JSON；不调用模型、不发送消息、不创建后台服务。Ctrl+C 结束。重新启动不清空已确认游标。

需要语音/图片/视频时，先按 `MEDIA_GUIDE.md` 安装配置，消费者改调用 `python3.14 check_inbox.py --config .wechat-local/media-config.json`。它是单次检查，**不是常驻监听**；基础 `watch` 仍只提供新消息元数据，可用它唤醒消费者再做媒体准备。

处理完一批（包括决定不回复）后，才确认其游标：

```sh
# 将下方 JSON 替换成刚才实际审阅过的 ack_cursor，不能照抄示例数字。
python3.14 wechat_db.py ack --state .wechat-local/group-state.json \
  --cursor '{"message_0.db": 123}'
```

不确认则保留待处理批次；这提供可重放性，不保证消费者恰好处理一次。用 `(数据库名, local_id)` 去重，并给每次发送绑定稳定操作 ID。只允许一个消费者使用同一游标文件；不要并行启动多个自动回复进程。多分库以每库游标跟踪，每批每库最多 200 条，积压时逐批处理和确认。数据库替换或游标倒退会停止，不能静默重置。

自动聊天还需要决策者。可把 `AGENT_PLAYBOOK.md` 的流程交给已有代理：检查新消息 → 判断是否值得回复 → 执行上述发送封装 → 核验 → 确认游标。这里不附远程模型密钥、平台专用定时任务或默认向群里发消息的后台服务。代理平台每分钟唤醒与本地一秒轮询是两回事；本次真实使用的是前者，不能据此宣传秒级模型回复。

## 7. 复现验收与公开内容

建议依次通过：

- `sh test.sh`：人工图像、OCR、草稿、操作日志测试。
- `python3.14 test_db.py --lldb`：人工数据库/捕获测试（数量以输出为准）。
- `.venv-media/bin/python test_media.py`：可选媒体人工样本测试，不读取真实微信。
- `wechat_db.py verify`：自己的真实库逐项 verified。
- 文件传输助手发送唯一测试文本并读回一次。
- 新消息触发增量 check，确认后不再重复出现。
- 使用同一个发送 ID 再运行，不重复发送。
- 原版微信恢复，原版签名未改，SIP 仍开。

本仓库只发布源码、说明和人工测试。**不包含真实密钥、数据库、截图、私人联系人 ID、聊天内容、登录状态或本机任务配置。** 默认生成的 `.wechat-local/`、截图、日志与编译产物均留在本机。不要把运行目录整个再次公开上传。

无法通过某一步时，按 `TROUBLESHOOTING.md` 停在该步，不要删除校验或忽略错误。MIT 许可证见 `LICENSE`。
