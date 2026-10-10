# 现在最方便的取钥方法：先复用，首次才初始化

结论更新：2026-09-23。实测环境为 Apple Silicon、macOS 15.6.1、腾讯官方微信 4.1.15。这里的“推荐”限定于这套环境及本仓库的实测，不代表所有平台的最优方案。

## 直接选择

| 当前情况 | 推荐做法 | 是否中断微信 |
| --- | --- | --- |
| 已有本账号的有效逐库密钥 | 先 verify，通过后直接只读 DB + WAL | 不需要 |
| 首次没有密钥 | 正常退出原版 → 临时副本重签 → LLDB 启动副本取钥 → 恢复原版 | 一次初始化会中断 |
| 已有密钥但验证失败 | 先检查账号、路径、SQLCipher、文件权限和数据库是否变化；明确失效/缺失后才重新初始化 | 排障本身不需要 |
| 要求保持官方签名和系统保护不变、首次取钥也完全免重启 | 本机普通用户与管理员只读端口测试均失败；没有已验证的可用实现 | 本仓库不承诺实现 |
| Windows / Linux / Intel Mac / 其他微信版本 | 按平台和具体版本单独验证，不能套用本机结论 | 未在本项目实测 |

**对已有密钥的使用者，最方便的方法是不再取钥。对首次安装者，本项目推荐一次性临时副本初始化，之后反复复用密钥。** “一次性”指密钥仍有效的正常使用周期，不是保证永不失效。

## A. 已有密钥：最短路径

先按 QUICKSTART 安装 Python 3.14、SQLCipher 等依赖，再在下载目录执行：

```sh
python3.14 wechat_db.py --key-file .wechat-local/keys.json verify
# 核对目标消息库验证通过后，再读取本人指定会话。
python3.14 wechat_db.py --key-file .wechat-local/keys.json read --chat-id filehelper --limit 10
```

`verify` 实际以 SQLCipher 只读打开并查询表结构，不获取新密钥、不读取正文。非默认密钥目录要替换 `--key-file`；多账号要在子命令前加 `--db-root '/本人账号/db_storage'`。不得把别人的账号或不同副本数据目录混在一起。

本机复验：26/26 数据库结构查询通过，26/26 为 query_only，一次测量约 186.3 ms。这个时间不是首次取钥耗时，也不是消息发现或回复延迟。微信普通重启不应自动触发 bootstrap；先验证已有密钥。账号迁移、库重建、密钥轮换或新分库缺少密钥时，需重新核对覆盖范围。

## B. 首次取钥：推荐的完整路径

首次操作按 QUICKSTART 第 1–3 节；影响说明和原理见 REFERENCE.md 第 2、3 节。保存草稿并通过微信菜单正常退出原版后，执行：

```sh
python3.14 disk_inventory.py
python3.14 bootstrap_keys.py --acknowledge-debug-copy
# 临时窗口中进入本人账号；如要求手机确认/扫码，在本机完成。
# 捕获完成、原版恢复后：
python3.14 wechat_db.py verify
```

实际流程：

```text
原版正常退出
  → 复制到私有工作目录，只重签副本
  → LLDB 启动自己的副本子进程
  → 观察 CommonCrypto 的 CCKeyDerivationPBKDF 参数
  → 与所选数据库盐值匹配，派生/识别候选 raw key
  → 数据库首页 HMAC 验证，逐库保存密钥
  → 结束临时进程、禁用副本入口、恢复原版
  → SQLCipher 只读打开验证，日常复用
```

本机这条流程没有使用 sudo，没有改原版签名，没有关闭 SIP。默认密钥文件为 `.wechat-local/keys.json`，权限 0600，目录 0700。临时副本仍使用原账号数据，并不是隔离的测试账号；可能需要重新登录。不能保证不被客户端感知或不存在账号风险，详见 REFERENCE.md 和 VALIDATION。

**验证层级：**逐步执行这条流程已在真实微信成功取得并验证 26 个库；`bootstrap_keys.py` 是对此过程的通用封装，捕获核心另经人工程序测试。没有为了发布文档再次中断真实微信验证整个封装，不能将二者混称为整套封装已多次实机通过。

脚本拒绝覆盖现有密钥或已有副本。重新初始化时保留旧结果，明确选择新的 `--state-dir`，之后读取使用新目录中的 `--key-file`。不要因单个查询失败就删除密钥，也不要把整个 bootstrap 用 sudo 运行。

## C. 为什么暂不推荐“sudo + 直接扫描”

在本机官方微信 4.1.15、Hardened Runtime 开启、未开放 get-task-allow、SIP 开启的状态下：

| 测试 | 结果 |
| --- | --- |
| 普通探针申请控制端口 | task_for_pid 返回 5 |
| 普通探针申请只读端口 | task_read_for_pid 返回 -1，errno=1 (EPERM) |
| 给自建探针增加 debugger entitlement | 访问微信仍失败 |
| 用户在本机 Terminal 手动 sudo 执行只读探针 | uid=0，仍为 EPERM，没有读取目标内存 |
| 探针自身正对照 | 成功申请只读端口并读取自身 16 字节 Mach-O 头 |

管理员结果不是“密码没输入成功”，也不证明密钥不存在。它证明当前环境下这条只读端口入口未打通。对应版本 XNU 的 root 路径仍经过 MAC 策略检查；不能由 EPERM 指定某个闭源策略模块，也不能断言所有可能方式均已穷尽。[Apple 对应内核源码](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/bsd/kern/kern_proc.c#L5845)

可选诊断文件 `readonly_port_probe.c` 与 `probe_readonly_port.sh` 仅用于复现实验，不是日常安装的必需步骤，也不是密钥提取器：

```sh
bash probe_readonly_port.sh
# 只有需要验证本机管理员分支时才由本人运行：
bash probe_readonly_port.sh --admin
```

它只允许探针自身或实际执行路径为 `/Applications/WeChat.app/Contents/MacOS/WeChat` 的目标，申请专用只读端口，成功后最多读取目标可执行区域的 16 字节。只输出状态，不输出字节内容、地址或密钥，不暂停或写入微信。无权限时非零退出属于诊断结果；`read_result=-999` 只是尚未尝试读取的内部占位值。sudo 密码仅在本机输入，不交给代理或写入脚本。

## D. 与调研项目的关系

以下是截至更新日的源码/文档核对，未在本机安装这些项目做兼容性验收。

- **TANGandXUE/wcdb-key-tool（macOS）**：核心也是 LLDB 观察 CommonCrypto/PBKDF2，再校验数据库密钥，因此原理同类。它的公开使用步骤对原版重签名并使用 sudo；本仓库采用只签临时副本、调试自身子进程、保存逐库 raw key 的流程。不能因为它是单文件工具就认为省掉了签名和进程权限前提。[macOS 源码](https://github.com/TANGandXUE/wcdb-key-tool/blob/main/wcdb_key_tool_macos.py)
- **同项目 Windows 路径**：源码包含针对 4.1.11 的运行期 Config.Cipher 对象只读扫描、候选解码及 HMAC 验证；该平台的设计不依赖先重新登录命中断点。本机未验证 Windows，也不能把 Windows 内存权限和对象布局直接搬到 Mac。[Windows 源码](https://github.com/TANGandXUE/wcdb-key-tool/blob/main/wcdb_key_tool_windows.py)
- **leeguooooo/wechat-use**：核对到的当前安装脚本为独立微信 4.1.9 副本增加调试权限并重签名，项目另有激活和版本约束。它简化了操作流程，不代表不需要签名调整；没有证据表明换到它会比已跑通的 4.1.15 方案更省事。[项目](https://github.com/leeguooooo/wechat-use)、[安装器](https://github.com/leeguooooo/wechat-use/blob/main/install.sh)
- **jackwener/wx-cli**：在微信 4.1+ 上实测取到 0 把密钥，且该仓库曾涉 DMCA。**本仓库明确不推荐、不依赖这条路径。** 成功路径仍是上文 B 节的临时副本重签 + LLDB。
- **CosmosShadow/UseChat**：通过界面、OCR 和视觉模型读写，可以省去数据库取钥，但仍依赖窗口及识别条件；适合愿意采用界面读取的人，不是磁盘解密方案。[项目](https://github.com/CosmosShadow/usechat)

第三方项目中“永不封号”“新版不可能留 raw key”等宽泛说法不作为本项目保证。判断候选密钥是否正确，仍要以实际数据库 HMAC 和只读查询为准。

## E. 新发现属于研究方向，不能冒充成功方案

已对本机实际 ARM64 二进制定位 PBKDF2 和 AES 包装调用，确认 AES 调用接收 32 字节 key；其行为与 SQLCipher 的 CommonCrypto provider 相符。腾讯 WCDB 开源 `CipherConfig` 也会缓存 raw key 并优先复用，但尚未证明本机私有构建有同样的对象布局。[SQLCipher 源码](https://github.com/sqlcipher/sqlcipher/blob/master/src/crypto_cc.c)、[WCDB 源码](https://github.com/Tencent/wcdb/blob/master/src/common/core/config/CipherConfig.cpp)

因此存在两个候选方向：取得适当读取权限后定位常驻密钥对象；或取得调试权限后，在正常数据库页加解密时观察 AES 输入，而不只等启动阶段。两者均未在保持当前官方进程不变的条件下完成取钥。静态地址会受版本和 ASLR 影响，不是可直接运行的通用配方。

“从磁盘持久化材料恢复初始密钥”也尚未验证。能从 DB/WAL 读取消息，前提是已经有有效密钥；数据库头部盐值本身不能推算出密钥。本次没有发现可公开复现的磁盘直接取钥方法。
