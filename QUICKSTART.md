# 首次使用：从下载到一次完整验收

本页是顺序操作路线。所有命令在克隆下来的仓库根目录执行，适用于 macOS 的 zsh/bash；不要跨目录、跨终端照抄未设置的变量。命令失败就停在该步，查 TROUBLESHOOTING.md。示例不包含真实账号，标为“替换”的值必须自己填写。

完成本页可以验证本机读取、增量确认和单条发送。它不会创建自动回复服务。媒体是可选模块，代理和调度器需另行接入。

## 1. 下载、安装、编译

已验证环境：Apple Silicon、macOS 15.6.1、微信 4.1.15。UI 代码最低目标 macOS 14；其他版本未做完整实机验收。需要已登录过的本人微信、本地聊天数据、Homebrew、Xcode Command Line Tools。Intel/Rosetta 的取钥流程未验证。

```sh
xcode-select -p
# 若缺少 CLT，先运行 xcode-select --install，安装完成后继续。
brew install python@3.14 sqlcipher gh
# gh 尚未登录时，在本机完成 gh auth login。
git clone https://github.com/DaneelOlivaw1/macos-wechat-export.git
cd macos-wechat-export
python3.14 --version
sh build.sh
sh test.sh
python3.14 test_db.py
```

也可以在 GitHub 仓库页面点 Code → Download ZIP 下载，解压并进入包含 README.md 的目录，不必安装 gh。`build.sh` 生成 wechat-ui；测试使用人工图像/数据库，不向微信发消息。可选 `python3.14 test_db.py --lldb` 只调试人工 C 子进程。

成功标准：构建和测试退出码为 0、测试输出无失败。若 SQLCipher 无法加载，检查 Homebrew 安装位置或设置 SQLCIPHER_LIBRARY；系统 SQLite 不能替代 SQLCipher。

## 2. 选择账号并准备密钥

先查看本机数据库目录元数据：

```sh
python3.14 disk_inventory.py
```

从输出选择本人账号的 db_storage 绝对路径。多账号不能猜第一个。设置以下变量，之后命令共用它们：

```sh
WX_DB='/替换为本人账号的实际绝对路径/db_storage'
WX_KEYS="$PWD/.wechat-local/keys.json"
```

已有有效密钥：把 WX_KEYS 改为已有文件的绝对路径，直接到第 3 步。不要为日常读取重复初始化。

没有密钥：先阅读 REFERENCE.md 第 3 节和 KEY_GUIDE，保存草稿，通过微信菜单正常退出原版。然后运行：

```sh
python3.14 bootstrap_keys.py --db-root "$WX_DB" --acknowledge-debug-copy
```

此操作复制微信、仅重签临时副本，由 LLDB 启动该副本取钥，完成后恢复原版；不改 SIP。副本仍访问原账号数据，可能要求本人手机确认或扫码，不是隔离账号沙箱。不要在副本中继续聊天。真实逐步流程已成功，整合 bootstrap 封装的验证范围见 VALIDATION。

成功标准：私有 keys.json 已保存、原版恢复且能正常使用；`original_launch_requested` 只表示请求启动，不代表已登录。脚本拒绝覆盖旧副本/密钥；如有旧状态，先查 KEY_GUIDE，不能删除后盲重跑。异常恢复见 TROUBLESHOOTING。

## 3. 只读验证与确认本人身份

```sh
umask 077
mkdir -p .wechat-local
chmod 700 .wechat-local
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" verify
```

成功标准：验证列表中的库均 verified，退出码 0。库数量依账号而异，不要求正好 26；有失败先排查，不把失败当作无消息。

在微信里手动给文件传输助手发送一条独特的普通文字，例如 `本人身份验收-当天自选编号`，然后读回：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  read --chat-id filehelper --limit 10
```

找到刚才全文匹配的行，复制其 **sender_id 字符串**：

```sh
WX_SELF='替换为刚才本人消息的sender_id字符串'
```

不要复制数字 `real_sender_id`，不要填昵称；公开 CLI 将数字行号通过 Name2Id 解析为 sender_id。没有指定 `--self-id` 的 read 返回 `from_self: null` 是未进行本人比较，不代表消息不是本人所发。

## 4. 只在文件传输助手验收一次工具发送

在系统设置中给运行终端/代理宿主开启屏幕录制和辅助功能；按系统要求重新打开宿主后，重新设置本页变量。保持 Mac 解锁。

```sh
./wechat-ui doctor
```

人工打开文件传输助手，关闭遮挡窗口/侧栏，确认没有草稿或附件。将 WX_TITLE 填成界面实际标题。测量编辑区上边界距窗口顶部的比例，填写 WX_COMPOSER；0.695 只是曾实测的例子。

```sh
WX_TITLE='替换为实际标题，例如文件传输助手'
WX_COMPOSER='替换为测量比例，例如0.695'
./wechat-ui read --chat "$WX_TITLE" --snapshot .wechat-local/layout.png
```

在本机打开截图核对标题和编辑区，截图包含私人信息。详见 UI_GUIDE。聊天标题与数据库 ID 是两种东西，不能互换。

选择新的唯一测试正文和操作 ID；以下示例在同一安装目录只用一次：

```sh
printf '%s' '本地发送验收-demo-001' > .wechat-local/message.txt
python3.14 send_verified.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  --state-dir .wechat-local/send-state --chat-id filehelper --self-id "$WX_SELF" \
  --title "$WX_TITLE" --text-file .wechat-local/message.txt --id demo-001 \
  --composer-top "$WX_COMPOSER" --dry-run
```

预检通过后，立即确认界面仍为该会话，再执行一次：

```sh
python3.14 send_verified.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  --state-dir .wechat-local/send-state --chat-id filehelper --self-id "$WX_SELF" \
  --title "$WX_TITLE" --text-file .wechat-local/message.txt --id demo-001 \
  --composer-top "$WX_COMPOSER"
```

成功标准：`sent_db_verified`，并在微信看见完整正文。它表示同会话新增本人消息、全文一致、唯一匹配、server_id 非零，不表示对方已读。可以用原命令加 `--verify-only` 复核；原 ID、文件、参数不变。再次运行原操作也不应触发重复发送。

`send_result_uncertain` 不等于没发送；先核验，不能换 ID 重发。`draft_verification_failed` 表示未按 Enter，先查看是截断还是 OCR 错读，只修正本次工具自己的草稿；人工核对全文后完成发送，再对原操作 verify-only。完整分支见 OPERATIONS 第 4 节。

## 5. 验收增量和确认，再选真实目标

先在文件传输助手测试游标，避免用真实群摸索：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  init --chat-id filehelper --self-id "$WX_SELF" --state .wechat-local/test-state.json
```

现在手动发一条新的测试文字，然后检查：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  check --state .wechat-local/test-state.json > .wechat-local/test-batch.json
cat .wechat-local/test-batch.json
```

应在 new_messages 中看到新文字，from_self 为 true；incoming_count 为 0 是正常的。init 之前的消息不应被列为新增。未确认前再次 check 可以重复返回同一批。

审阅全部返回消息后，复制该批 ack_cursor 的 JSON，替换下面的占位文本；不要复制文档中的固定消息编号：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  ack --state .wechat-local/test-state.json --cursor '替换为实际审阅批次的ack_cursor JSON'
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  check --state .wechat-local/test-state.json
```

成功标准：返回 acknowledged；若期间没有再来消息，下次 new_messages 为空。ack 命令只校验数值范围，不知道人是否真正审阅过，调用方必须保证这一点。

选择真实目标前取得本人授权。按准确名称解析并人工核对唯一结果：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" resolve '替换为准确群名或联系人名'
WX_CHAT='替换为唯一结果的username'
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  init --chat-id "$WX_CHAT" --self-id "$WX_SELF" --state .wechat-local/group-state.json
```

init 仅首次使用：它把当前最大位置设为基线，不处理此前历史。恢复监听不能再次 init。真实目标的发送还需重新核对标题、空草稿和布局，不能沿用文件传输助手标题。

## 6. 选择日常运行方式

- **仅文字、人工审阅**：对 group-state.json 运行 check，读输出，完成后 ack 实际审阅范围。无需模型或调度器。
- **需要媒体**：按 MEDIA_GUIDE 安装 Python 3.12 隔离环境、FFmpeg、本地 ASR 模型，填写 media-config.example.json 的私有副本，运行 check_inbox.py。db_root、key_file、chat_id、self_id、state_file 必须与本页一致。expected_name 是联系人数据库中的昵称/备注，不是带人数的 UI 标题。
- **需要自动适时回复**：按 AGENT_PLAYBOOK 接入自己的消费者/代理和一个调度器。公开工具不自带模型、审阅账本、调度任务或默认回复。

本地有限时长 watch 示例：

```sh
python3.14 wechat_db.py --db-root "$WX_DB" --key-file "$WX_KEYS" \
  watch --state .wechat-local/group-state.json --seconds 3600 --interval 1
```

watch 只输出批次，不发送、不 ack；Ctrl+C 停止。单次 check/check_inbox 运行完就退出。平台定时唤醒代理是另一种运行方式，不能把上述 1 秒本地轮询等同于 1 秒模型回复。

## 7. 停止、恢复和验收清单

停止时暂停外部调度器、结束自己启动的 watch/消费者，保留游标和发送状态。收到停止指令后，已排队任务也不得继续发言。恢复需本人明确要求，沿用旧进度；未决发送先核验，历史媒体不自动补做。详见 OPERATIONS 第 5 节。

完成复现应能确认以下结果：

- 构建、人工测试通过；自己的密钥 verify 通过。
- 手动测试消息读回，sender_id 已确认。
- 文件传输助手工具发送仅一条，全文及非零 server_id 核验成功；原 ID 不重复发送。
- init 后新增消息可见，审阅后 ack，下次不再返回该批。
- 如安装媒体模块，人工 test_media.py 通过；在本人授权的测试会话中分别审阅实际素材，不能把人工测试当作所有真实格式已兼容。
- 停止后调度器暂停，相关消费者已结束；未公开私有目录、截图或输出。

保留本机验收结果即可，不必把聊天正文交给作者。失败报告可提供工具版本、系统/微信版本和脱敏错误码，不附密钥、完整 XML 或签名 URL。
