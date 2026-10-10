# 本地语音、图片、视频：安装、读取与审阅

这是可选模块，不改变“数据库只读、发送走界面”的边界。`media_pipeline.py` 准备媒体；`check_inbox.py` 将它接入增量收件箱。两者都不发送、不自动确认游标、不创建后台任务、不调用远程模型。基础文本工具仍可单独使用。

## 1. 安装隔离运行时

基础数据库 CLI 使用 Python 3.14；媒体依赖在 Apple Silicon / Python 3.12 的单独环境中验证。不要把 MLX 装进 LLDB 所用的 Apple Python。需要 FFmpeg/ffprobe 和 SQLCipher：

```sh
brew install python@3.14 python@3.12 sqlcipher ffmpeg
python3.12 -m venv .venv-media
.venv-media/bin/python -m pip install -r requirements-media.txt
.venv-media/bin/python test_media.py
```

如果 Python 的 `venv/ensurepip` 安装不完整，可以使用官方安装的 uv：`uv venv --python python3.12 .venv-media`，然后 `uv pip install --python .venv-media/bin/python -r requirements-media.txt`。不需要同时执行两种安装方式。使用的是 **pilk**，不是 `pysilk`：本次尝试的 PyPI `pysilk` 包未提供可导入解码模块。

版本文件固定了实测的直接依赖，不是完整传递依赖锁文件。测试使用人工媒体，不读取你的微信。下载依赖及模型需要网络，后面的媒体推理只在本机运行。

## 2. 准备本地 ASR 模型

本次实测 `mlx-community/whisper-large-v3-turbo`。已有完整本地模型目录时直接使用，不必再下载；否则明确下载到私有目录：

```sh
mkdir -p .wechat-local/models
chmod 700 .wechat-local
.venv-media/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('mlx-community/whisper-large-v3-turbo',
                  local_dir='.wechat-local/models/whisper-large-v3-turbo')
PY
```

这里只下载模型，不上传音频。运行转写时将 `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`，配置必须指向本地模型目录。首次加载、模型大小、音频长度和硬件都会影响耗时；不承诺秒级端到端回复。没有模型时已有微信转写仍可读，其他语音标记阻碍；视频可保留画面并标记音轨转写不可用。

MLX Whisper 的实现和模型用法见 [官方 mlx-examples/whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)。

## 3. 配置一次，固定身份

先完成 QUICKSTART / REFERENCE.md 中的密钥、联系人唯一匹配、自己 sender_id 和文件传输助手验收。随后：

```sh
umask 077
cp media-config.example.json .wechat-local/media-config.json
chmod 600 .wechat-local/media-config.json
```

手动编辑复制后的配置，不能直接运行占位符：

| 字段 | 含义 |
| --- | --- |
| `db_root` | 本人选定账号的实际 db_storage 绝对路径 |
| `key_file` | 本人的逐库密钥文件，通常相对配置文件的 `keys.json` |
| `chat_id` / `self_id` | 会话 username / 本人 sender_id 字符串；不能填昵称或数字 real_sender_id |
| `expected_name` | 当前联系人/群的昵称或备注；改名会停止检查，需人工核对 |
| `state_file` | 用下面 init 创建的持久化游标文件 |
| `media_python` | 媒体环境中的 Python，通常 `../.venv-media/bin/python` |
| `cache_dir` | 私有解码文件、音频、抽帧和审阅素材目录 |
| `asr_model` | 完整本地 MLX Whisper 模型目录 |
| `app_data`（可选） | 微信 app_data；默认当前用户的标准容器路径，只用来尝试图片密钥派生 |

配置里的路径统一相对于**配置文件所在目录**解析，绝对路径也可。不要把填好后的配置上传到公开仓库。

建立基线只运行一次，会跳过创建前的历史消息。全局参数位于子命令前：

```sh
python3.14 wechat_db.py --db-root '/自己的实际路径/db_storage' \
  --key-file .wechat-local/keys.json init \
  --chat-id '确认后的会话 username' --self-id '本人 sender_id' \
  --state .wechat-local/group-state.json

python3.14 check_inbox.py --config .wechat-local/media-config.json \
  > .wechat-local/inbox.json
```

`check_inbox` 只为新收到的支持类型准备媒体，自己发出的消息仍在 new_messages 中，但本收件箱不会为它们自动准备媒体；不能因此忽略本人手动文字提问。本人手动媒体需另行审阅或保留阻碍。近期上下文也不会批量解码历史媒体。它使用基础 Reader 的账号绑定、数据库盐值及游标倒退检查，另外验证配置与状态的会话/本人 ID 一致。输出 JSON 含私人正文和素材路径，不能上传。

不需要媒体时继续用 `wechat_db.py check`。若明确要重查某一条消息，可手动运行以下命令；它可能读取历史媒体，不能放进“只处理新消息”的循环：

```sh
.venv-media/bin/python media_pipeline.py --config .wechat-local/media-config.json \
  --database message_0.db --ids 123
```

上例库名和 ID 必须换成实际返回值，不是可照抄的测试消息。

## 4. 各类型具体怎样读取

### 语音（local_type 34）

先读取消息行 `packed_info_data` 的 protobuf 字段 5 内的字段 2，尝试取得微信已保存的文字转写。没有时按会话内部 ID 和 server_id，在 `media_*.db` 的 `VoiceInfo`/`Name2Id` 中匹配唯一语音数据。

SILK → `pilk.decode` → 24 kHz PCM → WAV → 本机 MLX Whisper。数据库里没有唯一完整语音时停止，不把另一会话的同号数据拼过来。微信文字和 Whisper 文字都可能识别错，均标记为机器转写。

质量检查会拒绝明显跨段重复、无效时间戳、NaN、过低置信度等结果。此检查是启发式的，既可能漏掉错误，也可能拒绝正常重复发言，**不是准确率认证**。被拒绝的 segments 仅保留供私下排障，不能当作真实对话送进自动回复。

### 图片（local_type 3）

消息 XML 中的 MD5 不一定就是磁盘文件名。代码按会话和 server_id 查询 `MessageResourceInfo`/`MessageResourceDetail`，从 packed_info 提取候选资源名，再在对应会话、月份的 `msg/attach/.../Img` 中按资源大小匹配。

支持的本地路径：常见明文图片、旧单字节 XOR DAT、实测 V1/V2 DAT。V2 的尝试密钥来自当前账号与本机 `app_data/{net,ilink}/kvcomm/key_*_*.statistic` 文件名中的数值，通过本地派生候选后解码；这是逆向获得的兼容逻辑，不是微信官方接口，也不等于数据库 SQLCipher 密钥。密钥不打印、不写入配置、不上传。

V2 布局按本次格式读取 AES 头部、明文中部及 XOR 尾部，使用图像解码验证结果。静态 WXGF 内容定位 HEVC VPS 起始码，交给 FFmpeg 导出第一帧。本次两张实际图片均恢复到完整分辨率；所有 WXGF、透明通道和动画兼容性未证明。普通动画图片也只输出第一帧。

结果是 `needs_visual_review`，需要代理/人实际打开 `image` 检查；`thumbnail_only` 或 `wxgf_first_frame_only` 必须保留在判断中。PNG 生成成功不代表理解了图片。未下载原图时可能只得到缩略图，不能拿模糊字作事实。

图片格式研究参考 [wxkey 的实现](https://github.com/r266-tech/wxkey)与 [WXAM 原作者的格式分析](https://sarv.blog/posts/wxam/)。本模块是独立实现，不包含真实账号密钥；V1 路径使用了该格式已公开的固定常量，它不是个人凭据。

### 视频（local_type 43）

同样经资源表定位本地 MP4。FFprobe 读取真实容器和音视频流，FFmpeg 按时间均匀提取至多 24 帧，单帧宽 960；有音轨则提取整条音轨后本地转写，没有音轨明确返回 `no_audio_stream`。

返回 `needs_visual_review`、时间戳、帧路径和 `sampling_only=true`。必须实际看帧，不能把抽帧等同于连续完整观看；乒乓触球、拍面变化等快速细节通常需要对应短片段的更密集帧或人工慢放。本工具没有动作跟踪、旋转测量或击球自动评分功能。

超过 10 分钟的素材暂标记需要选段，**当前 CLI 没有自动分段参数**。请使用者选定短片段，再由独立工具查看；不要宣称长视频已处理。视频噪声曾让 ASR 输出重复字和无效时间，质量过滤后不能拿这些内容作发言依据。

### 以“文件”发送的视频（local_type = (6 << 32) | 49）

实测遇到无扩展名的 `share_video_tmp_...` 文件。该条本机已验证：XML 声明大小与文件大小一致，MD5 一致，FFprobe 检出 H.264 视频且没有音轨。**停止监听前只完成了定位和探测，没有完成内容分析。**

新增发布代码在 `msg/file/<月份>/<标题>` 进行严格匹配：禁止目录穿越、符号链接、超 200 MiB 附件，必须大小及 MD5 均相符，再探测视频流；不会按扩展名猜测或执行附件。无扩展名的视频可进入同一视频流程。文件被改名、去重后缀、缺少 MD5、尚未下载、非视频文档都会显式停止；当前没有自动搜索所有目录或联网下载的回退。

此分支已通过人工文件/视频测试，**尚未用发布封装重新读取实际附件**，不要把真实元数据探测写成完整实机分析成功。普通 PDF、Office、引用/XML 消息、撤回、表情等仍不自动理解。

### 视频号分享卡片与界面审阅

视频号分享卡片不是普通 `local_type 43` 视频，也不能仅凭链接或下载文件大小判定已取得可播放内容。实测曾取得非可直接播放 MP4 的响应；不能把下载成功写成视频解析成功。发布版没有通用的视频号下载、解密和评论采集实现。分享卡片内的完整 XML、签名 URL 或凭据只留本机，不输出到公开日志。

用户已授权查看时，可通过微信界面打开目标视频。分别记录：实际观看的连续片段及时间范围、抽样画面、可核对的字幕、音频是否可靠、评论阅读范围。暂停视频有助于阅读评论，但不等于观看完整动作；读到评论区底部也不保证展开了全部回复，不能据此宣称读完所有评论或给出未经计数的精确覆盖率。

评论是他人的观点，需与画面观察分开；多数评论赞同或反对都不能替代动作证据。技术结论仍需要相关连续片段，不能用评论补齐未观察到的击球时序、旋转或效果。界面操作需重新核对窗口：同属微信进程的视频号窗和主聊天窗不是同一目标。快捷键或翻页可能切换视频，操作后应确认仍是原素材。

## 5. 审阅、确认和缓存

`blocked_media_refs` 和 `needs_visual_review_refs` 使用 `(database, local_id)`，不能只用一个分库内 ID。先处理未解析媒体和视觉审阅，再决定是否回复；处理后显式 ack：

```sh
python3.14 wechat_db.py --db-root '/自己的实际路径/db_storage' \
  --key-file .wechat-local/keys.json ack --state .wechat-local/group-state.json \
  --cursor '{"message_0.db": 123}'
```

只确认实际审阅完成的游标；某条阻碍未解决，不能把该库游标跨过它。新到消息不随旧批次一起确认。`needs_visual_review` 不会因为文件被某个程序打开就自动变为 ready；调用方应记录自己已查看的范围及结论。

缓存以会话、数据库、local_id 和 server_id 派生文件夹名。成功准备的素材复用；阻碍可重试。缓存不只含文本，还包括原始 SILK、PCM/WAV、图片和帧；命令设置 umask 077，新目录 0700、结果 0600。既有目录应由本人核对权限。需要重处理时，仅在暂停消费者后清理自己确认可删除的对应缓存；不要删除整个账号数据目录。

一批媒体子进程最多等待 240 秒，超时或失败会标记阻碍，不自动确认。首次模型加载或长素材可能超时，需人工处理，不能把超时解释为没有新消息。

## 6. 依赖及许可

本仓库及上游 Gist 原创代码使用 MIT。第三方库不因此改成 MIT：例如 [pilk](https://github.com/foyoux/pilk) 采用其自己的许可证（GPL-3.0）；MLX Whisper、模型、Pillow、cryptography、FFmpeg 及其构建选项也须各自核对许可。本仓库不再分发依赖源码、二进制或模型权重。打包、修改、商用分发时不能只引用本仓库的 MIT 许可证。
