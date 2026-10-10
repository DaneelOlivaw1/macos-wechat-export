# macOS 微信 4.x：修复空白截图，读取与验证发送

一个无需 Python、Node、远程模型或第三方运行时的 Swift CLI。全部图像处理和 OCR 在本机完成。

提供三个命令：

- `read`：核对当前聊天标题，读取可见聊天正文的 OCR 文本行。
- `watch`：保持 ScreenCaptureKit 流，画面有变化才做 OCR，输出候选新增行。
- `send`：核对联系人、检查输入框、输入指定文字、核对草稿、发送并检查右侧绿色消息气泡。

本文件只介绍 Swift UI 部分：它不读取数据库或提取密钥。完整的密钥与数据库流程见 REFERENCE.md。请先手动打开目标聊天；实测支持短文本发送，群聊长气泡的视觉确认可能失败，应使用 send_verified.py 独立查询数据库确认。这个 Swift CLI 不分析媒体或语音，也不支持转账；可选的数据库媒体模块见 MEDIA_GUIDE.md。

## 1. 空白截图的修复

在 macOS 15.6.1 / 微信 4.1.15 的实测中：

- AX 能读菜单，但没有聊天正文。
- 单次窗口截图为空白，单窗口 SCStream 启动后也可能没有有效画面。
- 即使微信在前台，显示器截图也可能略过它，捕获到后面的应用。
- 微信“演示屏幕时不显示微信主窗口”已关闭，重启微信仍不能解决。

可复现的有效顺序：

```swift
// 先按应用创建流，仍只包含微信。
let initial = SCContentFilter(display: display,
                              including: [wechatApplication],
                              exceptingWindows: [])
let stream = SCStream(filter: initial, configuration: configuration, delegate: receiver)
try stream.addStreamOutput(receiver, type: .screen, sampleHandlerQueue: queue)
try await stream.startCapture()
try await Task.sleep(for: .milliseconds(250))
// 关键：在已运行的流上更新为目标窗口过滤器。
try await stream.updateContentFilter(SCContentFilter(display: display,
                                                    including: [mainWindow]))
```

单纯在每轮重新调用 `SCScreenshotManager.captureImage` 并不能替代这一步。完整实现包含等待帧、窗口检查、错误处理和结束捕获。

[Apple 开发者论坛](https://developer.apple.com/forums/thread/808016)有相似报告：带有 `NSWindowSharingNone` 的窗口初始不出现在捕获流中，切换过滤配置后才出现。Apple 工程师要求提交 bug report，编号 FB21115847。本工具的修复来自本机对照测试，并不是 Apple 对所有微信版本作出的兼容性保证。

## 2. 安装

要求 macOS 14+、Xcode Command Line Tools。实际验证环境见 `VALIDATION.md`；其他系统、微信版本和主题需要自行验证。

1. 克隆本仓库（`git clone https://github.com/DaneelOlivaw1/macos-wechat-export.git`）或在仓库页面 Download ZIP。
2. 如果没有编译器，执行 `xcode-select --install`，按系统提示完成安装。
3. 在终端运行：

```sh
sh build.sh
sh test.sh
./wechat-ui doctor
```

`build.sh` 只调用系统 Swift 编译器，不下载依赖。`test.sh` 使用人工生成的图片测试联系人标题、草稿、绿色气泡以及操作 ID 日志，不访问实际微信账号。

在系统设置 → 隐私与安全性中，给运行工具的宿主（如 Terminal/iTerm）开启：

- **屏幕录制**：读取和截图需要。
- **辅助功能**：发送所需的鼠标、键盘事件需要。

工具不会自动修改权限。授权后如仍显示权限缺失，重新打开终端再检查 `doctor`。请保持 Mac 解锁；锁屏时返回 `screen_locked`。

微信设置 → 通用中的“Hide Weixin main window during demonstration”应关闭。关闭会使微信可能出现在录屏/共享中，请按自身需要选择；本工具不会替你切换该设置。

## 3. 读取

先手动打开一个一对一聊天，使用标题栏里显示的**完整、精确名称**：

```sh
./wechat-ui read --chat '联系人名称'
./wechat-ui read --chat '联系人名称' --snapshot ./debug.png
./wechat-ui watch --chat '联系人名称' --seconds 60 --interval 0.5
```

微信英文界面的文件传输助手标题通常是 `File Transfer`；中文界面请填写实际标题，不能盲用翻译后的名称。

输出为 JSONL。`baseline` 表示首次建立基线，不是新收到的消息；`candidate_added_lines` 只是候选追加 OCR 行；`context_reset` 表示上下文无法对齐。文本位置信息相对于裁切后的聊天区域归一化，坐标从左上方开始。

初始聊天边界由标题栏位置推算，针对微信 4.x 的左对齐标题布局。聊天正文底部默认采用 `--composer-top 0.70`，即窗口高度的 70%；如你的输入区域高度不同，必须按下面方法校准。默认不把输入框当作消息来源。

`watch` 是有限时长前台进程，默认 30 秒。Ctrl+C 可停止，不创建开机启动项、定时任务或后台服务。静态画面不会反复调用 OCR，但仍会检查窗口状态和图像变化。

## 4. 校准与发送

**先使用文件传输助手测试。** 保持窗口完整位于一个显示器中，不要最小化。发送期间不要操作微信、切换聊天或切换前台应用。

使用 `read --snapshot ./debug.png` 检查布局。找到聊天正文与编辑输入区之间的横线：

```text
composer-top = 横线距窗口顶部的像素数 / 截图总高度
```

例如窗口高 924 像素，横线大约位于 642 像素，则填 `0.695`。发送命令强制要求显式给出这个参数，不能照搬示例而跳过校准。先确认区域内没有草稿、图片或附件。

```sh
# 预检：只检查，不点击、不输入、不发送。
./wechat-ui send --chat 'File Transfer' \
  --text '本地读写测试 001' --id 'demo-001' \
  --composer-top 0.695 --dry-run

# 实际发送（同一组参数去掉 --dry-run）。
./wechat-ui send --chat 'File Transfer' \
  --text '本地读写测试 001' --id 'demo-001' \
  --composer-top 0.695

# 再读取，核对正文。
./wechat-ui read --chat 'File Transfer' --composer-top 0.695
```

默认按 Enter 发送。如果微信使用 Command+Enter，显式加 `--send-key cmd-enter`。错误快捷键可能只产生换行；工具不会尝试第二种快捷键补发，而是报告结果不确定。

仅支持不含控制字符的单行文本，最多 200 个字符。长文本、emoji、特殊字体和 OCR 无法精确识别的标点可能导致草稿核验失败，此时不按发送键，保留草稿供人工检查。实测也发生过 Unicode 输入实际截断；务必逐字核对。若由人工/获授权交互代理补全并发送，只改本次工具草稿，然后用原 ID 的 send_verified.py --verify-only 核验；不能换 ID 重跑。键盘输入使用 Unicode 事件，不覆盖剪贴板。

成功时输出 `sent_ui_verified`，含义为**输入框已清空且聊天正文出现匹配的右侧绿色气泡**。这不是微信服务器的送达回执，也不表示对方已读。颜色判断针对标准绿色发送气泡；自定义主题、界面变化、折行识别错误等会影响验证。

## 5. 防止重复与误发

- 联系人标题不匹配、窗口不明确、输入框不空、失去焦点或窗口移动：停止。
- 打字后先用 OCR 核对输入框全文；不匹配时不按 Enter。
- `--id` 是调用方提供的操作 ID。同一次业务操作请始终复用它。
- 状态默认保存在当前目录 `.wechat-ui-state`，也可用 `--state-dir` 指定固定目录；文件仅含内容哈希、状态和时间。
- 相同 ID 已成功：返回 `already_sent`，不再次操作微信。
- 相同 ID 状态为 `prepared` / `dispatching`：拒绝重试，必须先人工核对微信。
- 同一 ID 搭配不同联系人/文本：拒绝。
- 使用同一状态目录的发送进程互斥。不要用不同目录同时控制同一个微信。
- 一旦按过发送键，即使后续 OCR 失败，也不能据此断定没发出。不要换新 ID 盲目重发。

标题核对是 OCR 检查，不是微信内部唯一联系人 ID：同名联系人、恶意改名和操作时人为切换聊天仍有风险，因此本工具要求先人工选择准确的一对一聊天。它不是可无人值守处理重要事务的可靠消息 API。

## 6. 常见错误与排查

| 错误 | 处理 |
|---|---|
| `screen_locked` | 解锁 Mac，重新打开微信主窗口 |
| `screen_recording_permission_missing` | 检查宿主的屏幕录制权限 |
| `main_window_unavailable` / `expected_one_visible_main_window` | 主窗口必须可见；退出登录、最小化或多个候选窗口会被拒绝 |
| `window_must_fit_one_display` | 将窗口完整移到同一个屏幕内 |
| `no_frame_after_filter_refresh` / `blank_capture` | 检查微信隐藏开关、权限、显示器状态；不要当作没有新消息 |
| `chat_title_not_verified` | 核对顶部标题是否完整匹配，避免群聊、弹窗、搜索页和截断标题 |
| `composer_not_empty_or_wrong_composer_top` | 校准输入区边界，检查是否有文本、图片、附件 |
| `draft_verification_failed` | 未按发送键；检查草稿、输入焦点和 OCR；不要直接重发 |
| `send_result_uncertain` | 可能已发出；人工看气泡和错误图标，不要盲目重试 |

输出和显式截图可能包含私人聊天内容，请自行保管。代码不联网，但将 stdout 重定向到文件会保存文本。发布仓库、日志或截图时要单独脱敏。

## 7. 限制与参考

读取结果是可见 OCR 文本行，不是完整聊天数据库。不能区分所有消息方向，也不能可靠处理图片中的文字、引用、多行消息、滚动历史和撤回。因此阅读事件标记 `safe_to_autoreply: false`，不应直接接入无人值守自动回复。没有真实新消息到达延迟的 P95 承诺。

没有测试长期睡眠唤醒、所有微信版本、暗色/自定义主题和所有多显示器配置。显示器、布局或微信版本变化后，请重新校准并用文件传输助手验证。

- [Apple：SCStream](https://developer.apple.com/documentation/screencapturekit/scstream)
- [Apple：updateContentFilter](https://developer.apple.com/documentation/screencapturekit/scstream/updatecontentfilter(_:completionhandler:))
- [Apple：Vision 文本识别](https://developer.apple.com/documentation/vision/recognizing-text-in-images)
- [相似问题与 Apple 回复](https://developer.apple.com/forums/thread/808016)

MIT License。所有公开测试图片由代码生成；本仓库不包含私人聊天截图、实际联系人信息、账号凭据或运行日志。


## 8. 实际窗口故障补充

微信主聊天窗和内置网页窗属于同一应用。应用在前台不等于目标聊天窗口在前台；背景窗口截图可读也不等于鼠标将点到该窗口。发送前先人工关闭/移开遮挡、选择目标聊天，复核截图标题和空输入区。代码会检查应用焦点和主窗口几何，但未保证同进程其他窗口不会遮挡。

本次交互流程曾用 macOS AX 的 Raise、AXMain=true、AXFocused=true 恢复主窗。只激活应用或只 Raise 并非每次都足够。该方法需要先通过真实 AX 窗口列表/位置大小确定目标，不能照抄窗口 ID 和屏幕坐标；当前发布 CLI 不自动导航聊天或整理所有窗口。无法确定时交回人工，不在背景里盲输入。

仅以 bundle ID 选择应用时，保留的临时副本可能让自动化工具报告歧义。使用 `/Applications/WeChat.app` 的确切路径，核对实际运行进程；副本 `.disabled` 后仍可能被某些工具的应用清单列出，不代表它在运行。

数据库可继续读出旧记录，但 UI 可能已经要求重新登录。遇到提示时先停发送，由本人处理登录；不要在登录窗输入聊天正文，也不要自动重签名、再次获取密钥或反复登录。
