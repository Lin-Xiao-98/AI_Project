# 小林的个人 AI 助手 V1.0

这是一个运行在 `D:\Workspace\AI_Project` 的本地个人助手。它保留原有 Persona 和长期记忆，并加入会话、任务、提醒、资料库、安全工具、语音和企业微信入口。

## 最快上手

双击 `启动AI助手.bat`，输入普通文字即可聊天。输入 `/help` 可查看全部命令。

如需自行验收，双击 `验收AI助手.bat`。验收过程不会联网、不会录音、不会播放声音，也不会改动亮度和音量。

## 已完成功能

- Persona 对话与最近会话自动恢复
- 分类长期记忆：新增、全局去重、更新、删除
- 程序层敏感信息拦截，拒绝保存密钥、密码、验证码、令牌和身份证号
- 私人记忆、会话、任务、提醒、资料均只保存在已被 Git 忽略的 `data/`
- 本地任务清单、一次性提醒、失败后重试的企业微信提醒
- 本地资料库：按项目导入、检索、去重和删除 UTF-8 的 `.md` / `.txt`
- 受控读取项目文本；敏感目录和越界路径永久禁止
- 文件创建先进入待审批区，必须在本机使用 `/approve` 确认，且永不覆盖已有文件
- fast / balanced / deep 三档模型与故障回退
- 智能记忆筛选、历史与回复长度上限、稳定提示前缀缓存优化
- 麦克风录音转写、现有音频转写、文字生成 MP3；所有语音功能均需显式命令，绝不自动播放
- 企业微信群 Webhook 单向提醒
- 企业微信官方智能机器人 WebSocket 双向文字与语音转文字对话
- 个人微信官方 ClawBot（iLink）扫码绑定、私聊文字与语音转文字对话
- SQLite 一致性备份、工具审计、消息排重和单一所有者白名单
- 离线自动化测试与一键验收

## 常用命令

```text
/help                         命令帮助
/status                       运行状态
/mode                         查看模型档位
/mode fast|balanced|deep      切换并保存模型档位
/memory                       查看长期记忆
/forget <完整记忆>             删除长期记忆
/history                      最近会话
/new                          新会话（长期记忆保留）
/todo add <任务>               新增任务
/todo list|all                查看任务
/todo done|delete <编号>       完成或删除任务
/remind add <时间> | <内容>    新增提醒，时间格式 YYYY-MM-DD HH:MM
/remind list|all              查看提醒
/remind done|delete <编号>     完成或删除提醒
/knowledge add <路径> | <项目> 导入资料
/knowledge list               查看资料
/knowledge search <关键词>     检索资料
/knowledge delete <编号>       删除资料
/pending                      查看待审批文件动作
/approve <编号>                在本机批准动作
/reject <编号>                 拒绝动作
/listen <1-60秒>              录音、转写并作为一条聊天消息
/transcribe <音频路径>         转写已有音频
/speak <文字>                 生成 MP3，不自动播放
/wechat status                查看企业微信通知状态
/wechat test                  显式发送测试通知
/weixin                      个人微信通道说明（实际连接使用单独启动脚本）
/backup                       创建不含密钥的一致性备份
/exit                         退出
```

任务和提醒的写入只接受上面的明确命令；普通聊天中的文件创建仍需要 `/approve`，这是为了防止文档里的恶意文字诱导助手修改数据。

## 配置

真实配置保存在 `.env`，该文件已被 Git 忽略。模板见 `.env.example`。

```text
OPENAI_API_KEY=...
ASSISTANT_MODE=fast
OPENAI_MEMORY_MODEL=gpt-6-luna
OPENAI_FALLBACK_MODEL=gpt-6-luna
MEMORY_ANALYSIS_MODE=smart
MAX_HISTORY_MESSAGES=24
MAX_COMPLETION_TOKENS=1600
```

ChatGPT Plus 与 OpenAI API 是两套独立计费系统；本项目调用 API，需要 API 账户具有可用额度。

## 额度节省策略

- 默认 `fast` 使用 Luna，适合高频任务；需要更强能力时才手动切换 `balanced` 或 `deep`。
- `MEMORY_ANALYSIS_MODE=smart` 会用本地规则跳过普通闲聊的第二次模型调用；明确说“记住”、个人长期偏好或目标时仍会处理记忆。
- 默认只带最近 24 条历史，并把单次回复限制为 1600 tokens；可在 `.env` 调整。
- Persona 和工具说明放在稳定提示前缀，利用 OpenAI 自动提示缓存；动态记忆放在后面。
- `/status`、`/todo`、`/memory`、`/knowledge` 等本地命令不消耗聊天模型额度。

## 企业微信接入

### 官方智能机器人（推荐，双向）

该方案使用企业微信官方 Python SDK 和 WebSocket 长连接，不需要公网 IP。先在企业微信管理后台创建“智能机器人 → API 模式 → 长连接”，再把以下配置写入 `.env`：

```text
WECOM_ENABLED=true
WECOM_BOT_ID=你的BotID
WECOM_BOT_SECRET=你的Secret
WECOM_ALLOWED_USER_IDS=唯一所有者的企业微信userid
```

然后双击 `启动企业微信助手.bat`。默认关闭；必须且只能配置一个所有者，并且只接受该所有者的单聊，群聊会拒绝读取私人资料。重复消息不会重复处理，进程崩溃后超时消息可重新领取，远程斜杠管理命令和文件审批被禁止。长连接进程也会检查并主动发送到期提醒。

官方资料：

- https://developer.work.weixin.qq.com/document/path/101463
- https://github.com/WecomTeam/wecom-aibot-python-sdk

### 企业微信群 Webhook（仅通知）

把官方群机器人的完整地址填入 `WECOM_WEBHOOK_URL`。仅接受 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...`，用于到期提醒和显式 `/wechat test`。

本项目不使用个人微信外挂、Hook、模拟登录或桌面点击脚本，避免封号、泄密和夜间误操作。

## 个人微信接入（官方 ClawBot）

当前版本也支持腾讯官方微信 ClawBot 通道。它与“个人微信好友聊天”的目标一致，
不读取桌面微信数据库、不注入微信进程、不需要微信密码或 Cookie。首次使用前，
在 `.env` 增加：

```text
WEIXIN_ENABLED=true
```

然后双击 `启动个人微信助手.bat`。程序会从腾讯 iLink 服务取得官方二维码并尝试在浏览器打开，
用手机微信扫码确认。登录凭证和同步游标只保存在已被 Git 忽略的 `data/weixin_account.json`。
成功绑定后，你可以在个人微信的 ClawBot 会话中像和好友聊天一样给助手发消息；消息会交给本项目
现有 Persona、长期记忆、任务、提醒和安全工具处理。该通道只接受首次扫码绑定的所有者单聊，
群聊和其他账号会被忽略。

这是腾讯维护的官方 `openclaw-weixin` iLink 通道协议，要求微信客户端提供 ClawBot 入口；
如果手机微信设置中没有 ClawBot，说明账号或版本尚未开放，程序无法通过第三方方式绕过。

## 数据与安全

- `data/memory.json`：私人长期记忆
- `data/assistant.db`：会话、任务、提醒、资料索引、审批状态
- `data/tool_audit.jsonl`：本地工具审计
- `data/audio/`：显式录制或生成的音频
- `backups/`：本地 ZIP 备份
- `workspace/`：经批准新建的文件

以上目录均不会提交到 Git。旧版仓库中的 `memory.json` 已迁移到 `data/memory.json`，内容保留但从版本控制删除。

“本地保存”不等于“从不发送”：当你要求助手读取项目文件、检索资料、转写音频或生成语音时，相关文本或音频会按功能需要发送到 OpenAI API。不要导入或上传密码、密钥、验证码、身份证件等敏感内容。

项目文本读取禁止 `.env*`、`memory.json`、`data/`、`.git/`、`venv/`、项目外路径和超过 100 KB 的文件。备份使用 SQLite 官方快照机制并做完整性检查，不包含 `.env`。

## 开发与测试

```powershell
cd D:\Workspace\AI_Project
.\venv\Scripts\python.exe -m unittest discover -v
.\venv\Scripts\python.exe .\health_check.py
```

主要模块：

```text
main.py                  本地终端入口
assistant_service.py     外部通道共用助手核心
wecom_bot.py             企业微信官方长连接入口
memory_manager.py        长期记忆
conversation_manager.py  会话与通道排重
task_manager.py          任务
reminder_manager.py      提醒与远程重试
knowledge_manager.py     本地资料库
tool_manager.py          模型工具与审计
action_manager.py        待审批文件动作
voice_manager.py         录音、转写、语音生成
channel_manager.py       企业微信群 Webhook
backup_manager.py        一致性备份
```
