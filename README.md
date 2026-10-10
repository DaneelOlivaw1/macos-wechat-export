# macOS 微信聊天记录导出 · 微信 4.1 本地解密 · WCDB / SQLCipher（Apple Silicon）

> **微信聊天记录导出 / macOS WeChat 4.x local chat export**：在自己的 Mac、自己的微信账号上，用「临时重签副本取钥 + SQLCipher 只读」导出本地聊天记录。朋友把本仓库链接丢给 AI，AI 就能跟着做。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)](#)
[![WeChat](https://img.shields.io/badge/WeChat-4.1.x-07C160)](#)

**关键词**：微信聊天记录导出 · macOS 微信 · 微信 4.1 · 本地解密 · WCDB · SQLCipher · Apple Silicon · 临时副本重签 · LLDB 取钥

---

## 一句话说明

这是一套**本机只读**工具：退出原版微信 → 复制一份临时微信 → **只重签临时副本** → LLDB 启动副本拿数据库密钥 → 恢复原版 → 用 SQLCipher 只读导出聊天。不改 `/Applications/WeChat.app`，不关 SIP，密钥与聊天不上传。

实测环境：**Apple Silicon · macOS 15.6.1 · 微信 4.1.15**。其他版本/Intel/Rosetta 未完整验证。

## 硬边界（先读）

| 可以 | 不可以 |
| --- | --- |
| 自己的 Mac、自己的微信个人号 | 别人的账号、企业微信 WeCom 5.0.x |
| 只重签工作目录里的临时副本 | 重签 `/Applications/WeChat.app` |
| SIP 保持开启 | 关闭 SIP / 全局 sudo 跑整套工具 |
| 密钥与聊天留在本机 `.wechat-local/` | 把 `keys.json`、数据库、截图提交或上传 |
| SQLCipher `SQLITE_OPEN_READONLY` 读库 | 靠改库“发消息”；发送走微信 UI |

**不要用 [jackwener/wx-cli](https://github.com/jackwener/wx-cli)**：在微信 4.1+ 上实测取到 0 把密钥，且该仓库曾涉 DMCA。本仓库推荐的成功路径是下面的「临时副本重签」，不是 wx-cli。

## 给 AI 助手的指令（复制整块即可）

把下面整段发给 Cursor / Claude / ChatGPT / 其他能跑终端的助手；仓库地址就是本页：

```text
请按 https://github.com/DaneelOlivaw1/macos-wechat-export 帮我在本机导出 macOS 微信 4.x 聊天记录。

硬规则：
1. 只在我自己的 Mac、自己的微信个人号上操作；不要动企业微信。
2. 绝对不要 codesign /Applications/WeChat.app，不要关闭 SIP，不要用 sudo 跑整套流程。
3. 不要推荐或安装 jackwener/wx-cli（微信 4.1+ 取钥为 0，且有 DMCA 问题）。
4. 成功路径必须是：菜单退出原版微信 → 复制临时副本 → 只对临时副本 ad-hoc codesign → LLDB 启动该副本捕获密钥 → 校验 HMAC → 恢复原版 → SQLCipher 只读导出。
5. 密钥写到 .wechat-local/keys.json（0600），不要打印密钥、不要上传、不要 git add。

请按顺序执行（命令在仓库根目录）：
A. git clone https://github.com/DaneelOlivaw1/macos-wechat-export.git && cd macos-wechat-export
B. 确认 Apple Silicon + 已装 Xcode CLT；brew install python@3.14 sqlcipher；sh build.sh；sh test.sh；python3.14 test_db.py
C. python3.14 disk_inventory.py  → 确认本人账号的 db_storage 路径（多账号必须让我选）
D. 提醒我：保存草稿，微信菜单「退出」原版，确认 pgrep -x WeChat 为空
E. python3.14 bootstrap_keys.py --acknowledge-debug-copy  （必要时加 --db-root 与 --timeout）
F. 等 verified_progress / keys_saved_privately；确认原版可再启动
G. python3.14 wechat_db.py verify
H. python3.14 wechat_db.py read --chat-id filehelper --limit 10
I. 需要联系人/群时用 wechat_db.py resolve，再 read；增量用 init/check/watch/ack（见 QUICKSTART.md）

失败就停在当前步，打开 TROUBLESHOOTING.md，不要删校验、不要改原版签名。
详细步骤以 QUICKSTART.md 为准；原理见 REFERENCE.md。
```

## 成功路径原理（一段话）

微信 4.x 的消息库是 WCDB / SQLCipher。密钥不是磁盘文件里能直接抄的：进程打开库时会走 `CCKeyDerivationPBKDF`。本工具**复制**一份微信到工作目录，**只对这份临时副本做 ad-hoc 重签**，再用 LLDB 启动该副本、观察派生参数，对照各库头部盐值做 HMAC 校验后，把**逐库**密钥写进私有 `keys.json`。然后注销临时副本、恢复官方签名的原版微信。日常读取不再调试微信，只对 DB + WAL 做 SQLCipher 只读打开。

## 快速开始

```sh
git clone https://github.com/DaneelOlivaw1/macos-wechat-export.git
cd macos-wechat-export

xcode-select -p          # 没有就先 xcode-select --install
brew install python@3.14 sqlcipher
python3.14 --version
sh build.sh && sh test.sh && python3.14 test_db.py

python3.14 disk_inventory.py

# 微信菜单正常退出后：
python3.14 bootstrap_keys.py --acknowledge-debug-copy

python3.14 wechat_db.py verify
python3.14 wechat_db.py read --chat-id filehelper --limit 10
```

多账号时必须显式传入本人 `--db-root`。默认状态目录 `.wechat-local/`（0700），密钥文件权限 0600，**已在 `.gitignore` 中排除，切勿提交**。

## 文档导航

| 你要做什么 | 打开 |
| --- | --- |
| 首次从安装到验收 | [QUICKSTART.md](QUICKSTART.md) |
| 是否需要取钥、路线对比 | [KEY_GUIDE.md](KEY_GUIDE.md) |
| 命令失败 / 原版恢复 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 原理、发送、增量、完整命令 | [REFERENCE.md](REFERENCE.md) |
| 日常启停与发送恢复 | [OPERATIONS.md](OPERATIONS.md) |
| 图片 / 语音 / 视频（可选） | [MEDIA_GUIDE.md](MEDIA_GUIDE.md) |
| 截图与 UI 发送 | [UI_GUIDE.md](UI_GUIDE.md) |
| 交给代理做监听回复 | [AGENT_PLAYBOOK.md](AGENT_PLAYBOOK.md) |
| 实测范围与未验证项 | [VALIDATION.md](VALIDATION.md) |

## 仓库里有什么

| 文件 | 作用 |
| --- | --- |
| `bootstrap_keys.py` | 复制微信、只重签临时副本、启动捕获、恢复原版 |
| `capture_keys.py` | LLDB 捕获 PBKDF 派生参数并校验后私密存钥 |
| `sqlcipher_probe.py` / `wechat_db.py` | SQLCipher 只读封装；联系人解析、历史/增量消息 |
| `disk_inventory.py` | 无密钥时检查数据库/WAL 元数据 |
| `WeChatUI.swift` / `Send.swift` / `send_verified.py` | 可选：界面短文本发送 + 数据库独立核验 |
| `media_pipeline.py` 等 | 可选：本机媒体准备（见 MEDIA_GUIDE） |

```text
首次：原版正常退出 → 临时副本重签 → LLDB 启动副本 → 登录时捕获派生参数
     → 对照数据库第一页 HMAC → 私密保存每库密钥 → 关闭副本 → 恢复原版
日常：原版照常运行 → SQLCipher 只读 DB + WAL → 导出 JSON
```

## 归因 / Attribution

本仓库基于 **[acmerfight 的公开 Gist](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f)**（MIT）整理发布。原作者 acmerfight 对原始 Gist 内容保留著作权；本仓库在其基础上重写文档、调整结构，同样以 MIT 发布。详见 [NOTICE](NOTICE) 与 [LICENSE](LICENSE)。

取钥思路另参考了 [wxkey](https://github.com/r266-tech/wxkey)、[fomomo](https://github.com/nishuzumi/fomomo)、[wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool)（各自许可证以其仓库为准）。本仓库是独立小工具集，不调用它们的 bootstrap，也不继承其凭据保存或全局进程清理行为。

## 免责声明

- 仅用于**本人账号、本人设备**上的个人数据备份与本地分析。
- 微信版本、系统策略、企业 MDM 都可能使流程失效；不承诺“任何环境必定成功”，也不承诺“永不被检测 / 永不封号”。
- 调试签名副本可能被客户端感知；请自行评估账号风险。
- 不要把密钥、聊天内容、截图提交到 Git 或发给不明第三方。
- 作者与贡献者对使用本工具造成的任何损失不承担责任（见 LICENSE）。

## Star 一下

如果这套「临时副本重签」路径帮你在微信 4.1 上跑通了本地导出，给仓库点个 Star，也方便把链接丢给朋友或 AI 接着用。
