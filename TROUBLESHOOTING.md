# 失败时怎样处理

任何发送失败，先区分“没按发送键”和“按过发送键但未能核验”。后者必须检查数据库和界面，不能换 ID 自动重发。

| 现象 | 含义与处理 |
| --- | --- |
| 已有密钥，微信刚重启 | 先用正确账号路径和 key-file 运行 verify；不要自动重新取钥。 |
| 只读权限探针 uid=0、errno=1 | 本机 sudo 确已生效但进程访问仍被拒绝；不是密码失败。未进入扫描，不能判断密钥不存在；无需重复运行同一探针。推荐路径及边界见 KEY_GUIDE。 |
| 权限探针 read_result=-999 | 尚未进入内存读取，是程序占位值，不是额外的系统错误码。 |
| `quit WeChat normally first` | 原版或其他副本还在运行。正常退出，不要 killall。 |
| `select_account_with_--db-root` / 多个账号 | 明确选择自己账号的 db_storage；后续命令使用相同路径。 |
| `state contains a previous bootstrap` | 避免覆盖密钥；先核对已有结果，重试用新 state-dir。 |
| `import lldb` 失败 | 捕获必须用 `/usr/bin/python3`，PYTHONPATH 来自 `/usr/bin/lldb -P`；检查 CLT，勿混用 Homebrew Python。 |
| `launch_failed` / 调试权限拒绝 | 本机安全策略不允许；保持原版签名和 SIP，停止尝试，由用户在系统界面处理适用的调试授权或换受支持环境。这里不提供关闭 SIP 的步骤。 |
| 副本只显示登录页 | 在本机点击进入微信，必要时完成手机确认；不要把验证码/二维码发给代理。 |
| 超时只有部分库获得密钥 | 未打开的库、过期库或参数变化均可能导致。运行 verify 查看覆盖范围，缺失相关库就不能可靠读取该会话；不能把部分成功写成全部成功。 |
| 捕获匹配盐为 0 | 账号/数据目录选错，或客户端不再走该 CommonCrypto 路径；不要扫描无关进程或跳过盐校验。 |
| HMAC 不通过 / SQLCipher code 26 | 错钥、参数/页面布局不匹配或库损坏等；不要把查询错误理解为“没有新消息”。 |
| 数据库只读打开失败 | 检查文件访问权限、库是否存在、SQLCipher 动态库、WAL/SHM 读取条件。不要 chmod 整个微信目录。 |
| `self_id_not_found` / 未知发送者 | 用文件传输助手中自己发出的唯一测试消息确定 sender_id；使用解析后的 sender_id 字符串，不能用数字 real_sender_id、昵称或其他人的 ID。 |
| `conversation_has_no_local_message_table` | 本机没同步该会话记录、内部 ID 不对或版本表结构不同；先在原版核对。 |
| `database_replaced_or_cursor_regressed` | 原库被替换/重建/清理。人工核对后建立新的状态文件，保留旧状态用于审计。 |
| `screen_recording_permission_missing` | 给当前终端/宿主开启屏幕录制，并按系统要求重启宿主。 |
| `screen_locked` | 解锁 Mac。数据库读取与 GUI 发送的运行条件不同。 |
| 单次截图为空白 | 本工具用应用流 → 更新窗口过滤器。检查微信隐藏共享设置、窗口是否可见、权限及版本；仍失败就停止 UI 发送。 |
| 标题不匹配 | 核对实际标题、群人数、语言、同名联系人。工具做 Unicode 兼容归一化，但不是模糊匹配或唯一联系人识别。 |
| `composer_not_empty` | 检查草稿/附件、侧栏和布局。不能自动清空；0.695 是本机标定值，需自行测量。 |
| `draft_verification_failed` | 未按 Enter；可能文字截断，也可能全文正确但 OCR 不匹配。逐字人工核对目标和草稿，只修正工具本次草稿，人工完成后用原 ID `--verify-only`；不要删除检查或重跑输入。 |
| `send_result_uncertain` | 可能已发出。优先查同一操作的数据库基线及完整正文。封装使用同一 ID + `--verify-only` 重查，不发第二次。 |
| `multiple_new_matching_messages` | 有多条相同正文，无法唯一关联；停止并人工核对。 |
| 有记录但 server_id 为 0 | 尚未取得本方案要求的服务器 ID 证据；可能排队/离线，不应判断为失败后重发。 |
| `already_sent` / `already_sent_db_verified` | 此操作已完成；不需要再发。 |
| `id_reused_with_different_payload` | 错误复用操作 ID；确认旧操作后，新业务操作才使用新 ID。 |
| `another_sender_is_running` / 文件锁被占用 | 等现有发送结束。所有发送者共用一个状态目录，不要换目录绕过锁。 |

## 媒体、登录和调度故障

| 现象 | 处理 |
| --- | --- |
| `text: null`、类型非 1 | 基础读取没有理解媒体，不是空消息；使用可选媒体收件箱，检查阻碍/待视觉审阅引用。 |
| 语音反复出现单字、ASR 的 NaN/负时间 | 结果不可靠，不能发给回复模型当作事实；保留阻碍，重新听取或人工检查。 |
| `media_not_downloaded` / `voice_not_downloaded_or_ambiguous` | 用原版确认该条是否已下载到本机；只重试授权的这条，不扫历史。 |
| `image_format_or_key_unsupported` | 本版图片格式/密钥路径不适配；不要混用 SQLCipher 密钥，不能拿解码错误作图像内容。 |
| `thumbnail_only` / 第一帧标记 | 仅有缩略图/静态第一帧；不声称看到了全部细节和动画。 |
| 有视频外观但类型是大整数 | 可能是文件消息； `(6<<32)|49` 为本版处理的视频附件分支，见 MEDIA_GUIDE。 |
| 附件名称、摘要或大小不匹配 | 未下载、改名、同名后缀或布局变化等；停止匹配，不直接取同目录第一个文件。 |
| 音轨无可靠文字 | 视频可能无音轨、环境噪声或转写失败；仍可审阅画面，但不能编造对白。 |
| `media_processor_failed_or_timed_out` | 核对媒体 Python、依赖、模型和资源长度；240 秒批次超时不会自动 ack。 |
| “出于账号安全，请重新登录” | 暂停发送，由本人重新登录。旧 DB 可读不代表在线；原因无法仅凭提示确认。 |
| 微信在前台却点不到聊天 | 同应用网页窗/弹窗可能遮挡；人工置前主聊天窗口，重新校准和核对，见 UI_GUIDE。 |
| 群里有消息却没回复 | 依次查平台实际执行时间、进程是否运行、DB是否有新行、游标、from_self、阻碍媒体、是否确实值得回复、发送日志；不能仅看 ACTIVE 配置。 |
| 每分钟任务很久没执行 | 本次长任务期间曾观察到游标不推进，不能据此断言调度器内部原因；读平台运行记录。若要独立消费者，另行授权配置，切换时停止旧消费者，不能开两套同时发。 |

## 恢复原版微信

正常结束时 bootstrap 会恢复原版。如果终端被强制杀死、系统崩溃或出现 `manual_restore_required`，自动恢复可能未执行。

1. 正常退出临时副本；不要让原版和副本同时使用账号数据库。
2. 确认主进程的实际路径：

```sh
pgrep -x WeChat
# 将下面 PID 替换为上一步的某个数字。
ps -p PID -o pid=,comm=
```

3. 临时副本已退出后，可注销它在 LaunchServices 的注册，再把目录改名为 `.disabled`，避免 bundle ID 冲突；命令中的路径必须改成自己实际目录：

```sh
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -u "$PWD/.wechat-local/WeChat-trial.app"
mv .wechat-local/WeChat-trial.app .wechat-local/WeChat-trial.disabled
```

4. 从 Finder 打开 `/Applications/WeChat.app`，或者在终端明确运行原版路径。若打开仍误选副本，可直接执行 `/Applications/WeChat.app/Contents/MacOS/WeChat`，但应先确认没有另一个微信主进程。
5. 检查：

```sh
codesign --verify --deep --strict /Applications/WeChat.app
codesign -dvv /Applications/WeChat.app
csrutil status
```

`codesign -dvv` 应与私有目录中 `original-signature.txt` 对照。此方案不修改原版签名和 SIP；如果你此前已经修改过，它不会替你恢复那些历史改动。

## 停止和清理

- `watch` 为前台有限时长进程，Ctrl+C 即可停止，不创建 launchd 服务。
- 代理/调度器另行配置的监听，需要在对应平台暂停；终止一个 watch 不能停掉外部调度器。
- `.wechat-local` 包含密钥、游标、私有发送文本、操作记录和副本，不能公开。完成后由本人决定保留或删除。
- 从源码修改工具后，重新构建并只在文件传输助手验收；不要直接用真实群聊测试修改。

## 有输出但没有推进

| 现象 | 处理 |
| --- | --- |
| incoming_count 为 0，但 new_messages 非空 | 核对 from_self：本人手动消息与助理发送都可能为 true；用发送日志排除自我循环，不直接丢弃。 |
| 同一阻碍每轮返回 | 确认游标尚未越过该条属正常；用独立审阅账本避免重复回答/通知。不要批量转换历史媒体。 |
| 每库返回满 200 条，长期看不到更晚消息 | 可能被最早未处理内容卡住；当前 CLI 无独立扫描游标。报告积压并处理阻碍，不能跳过未读范围 ack。 |
| 已看图片仍显示 needs_visual_review | 准备器不保存人的审阅结论；消费者应另记已查看范围。第一帧/缩略图的剩余限制仍然存在。 |
| 媒体配置身份不匹配 | chat_id/self_id 必须与 state 文件完全相同；self_id 为字符串。expected_name 是数据库昵称/备注，不能带 UI 人数后缀。 |
| watch 没报告撤回或同一行变更 | 当前 watch 主要依赖新增 local_id 和批次游标，不是完整消息变更订阅。 |
