# 架构说明

AgentBridge 是为梨花（NipaPlay / NipaPlay-Reload）社区设计的聊天原生 Agent 桥接层。它不是一个传统 bot 框架，也不是 Agent 的长期记忆系统。它的职责是接入 QQ/NapCat 事件、保存上下文、随机唤醒 Hermes Agent，并执行经过控制的真实副作用。

## 系统边界

```text
QQ 群 / 私聊
  ↓ webhook/events
NapCat / OneBot 11
  ↓
AgentBridge
  ├─ 硬逻辑层
  ├─ 状态与归档层
  ├─ handoff 层
  └─ Skill API 层
        ↑
        ↓
Hermes Agent
  ↓
NipaPlay 仓库 / 知识库 / GitHub API
```

当前实现支持：

- NapCat 作为 OneBot 11 兼容适配器。
- Hermes/OpenClaw 风格的 Agent skill。
- OpenAI-compatible chat completions API。
- GitHub REST API，用于 PR、Issue、Workflow 状态查询和 workflow dispatch。
- NipaPlay 项目仓库和知识库通过 Hermes 文件/代码工具读取。

## 分层设计

### 1. 硬逻辑层

硬逻辑层处理不应该依赖模型判断的操作：

- 管理员命令解析。
- 管理员 QQ 号鉴权。
- GitHub release/deploy workflow dispatch。
- 公开状态查询命令。
- 群自主互动配置。
- 健康检查。

这一层不会调用 Hermes。它适合执行确定、可审计、失败模式清楚的动作。

### 2. Handoff 层

handoff 层决定何时调用 Hermes，以及如何构造上下文包。

立即触发：

- 私聊。
- @bot。
- 回复 bot 之前的消息。
- 命中配置关键词。

群级注意力窗口：

- @bot 或回复 bot 负责立即唤醒 Hermes，并会打断当前群已有的注意力窗口。
- 注意力窗口不会因为 Agent 发消息自动打开；只有 Agent 显式调用 `qq.extend_group_attention` 后，Bridge 才会为当前群打开短时注意力窗口。
- 窗口内的普通群消息不会逐条调用 Hermes，而是先进入 active group attention buffer。
- `GROUP_ATTENTION_BATCH_INTERVAL_SECONDS` 是固定收集窗口；普通群消息只入队，不刷新倒计时。
- 倒计时结束后，Bridge 把这一批消息交给 Hermes。
- 如果窗口内再次出现 @bot 或回复 bot，旧窗口会被清空；新的 mention handoff 自带最近上下文和归档路径，不再保留旧 buffer 等待二次投喂。
- 如果 Hermes 不发言但想继续等补充，可以调用 `qq.extend_group_attention` 延长观察。
- 窗口受 `GROUP_ATTENTION_TTL_SECONDS`、`GROUP_ATTENTION_MAX_BATCHES` 和 buffer 上限约束，避免无限续命。
- prompt 会明确告诉 Hermes：这是它主动保持注意力后的群聊续场，不是 ambient 随机看群。

ambient 触发：

- 普通群聊先进入 unread buffer。
- 后台调度器从指数分布采样下一次检查时间。
- 长期期望由 `AMBIENT_INTERVAL_SECONDS` 控制，默认 3600 秒。
- 没有未读、群未开启自主互动、或群回复冷却中时直接跳过。

Bridge 不判断讨论是否重要，也不做复杂语义理解。它只把当前聊天切片交给 Hermes，由 Hermes 判断是否要参与。

### 3. 状态与归档层

Bridge 持久化这些内容：

- 私聊和即时对话的短历史。
- 群最近消息窗口。
- 群级注意力窗口和待投喂批次。
- ambient 未读 buffer。
- bot 最近发出的 message_id，用于识别“回复 bot”。
- 群配置覆盖：自主互动开关、cooldown、关键词。
- 短期 agent run。
- SQLite 消息索引。
- JSONL 消息归档。

JSONL 是长上下文的主要来源：

```text
data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl
data/message_archive/private/<user_id>/YYYY-MM-DD.jsonl
```

每次 handoff 会把当前上下文和相关归档路径传给 Hermes。Hermes 需要更长历史时，应该自己用文件工具读取这些归档。

Bridge 有意不提供上下文搜索 skill。上下文检索、总结、长期记忆和项目理解属于 Hermes Agent。

### 4. Skill API 层

Hermes 通过安装的 `agentbridge` skill 调用 Bridge。Bridge 再调用 OneBot/NapCat 或 GitHub。

当前 skill API 分组：

- `onebot.call`：泛用 OneBot action 调用，受分级 allowlist 控制。
- `qq.*`：常用 QQ helper，包括发消息、私聊、回复、表情、群信息、群管。
- `github.*`：只读的 PR、Issue、Workflow 状态查询。

release/deploy 等项目写操作仍保留在硬逻辑命令层。

## Agent Run 模型

每次 handoff 都创建一个短期 `agent_run`：

```text
run_id
mode: immediate / ambient / private
group_id
user_id
trigger_message_id
allowed_tools
allowed_repos
expires_at
max_tool_calls
tool_calls
```

每个 skill 请求都必须带 `run_id`。Bridge 会检查：

- run 是否存在且未过期。
- 请求工具是否在 `allowed_tools` 内。
- 目标群或 repo 是否和 run 匹配。
- tool call 次数是否超过限制。
- 泛用 OneBot 调用是否符合 `SKILL_ONEBOT_LEVEL`。

这不是完整沙箱，而是一个实用的防误触边界。默认假设 Hermes 是可信的 NipaPlay maintainer agent。

## OneBot 分级

`SKILL_ONEBOT_LEVEL` 控制 `onebot.call` 能调用哪些 OneBot action：

```text
chat        send_msg / send_group_msg
group_read  chat + 群信息/群成员读取
group_admin group_read + 撤回/改名片/禁言/踢人/管理员/全员禁言/头衔
full        不做 OneBot action allowlist
```

常用动作有独立 helper，因为这对 Agent 更好用；少见动作走 `onebot.call`。

## 消息流程

### @bot / 回复 bot

```text
群消息触发 bot
  ↓
保存消息到 SQLite + JSONL
  ↓
创建 agent_run
  ↓
构造上下文包
  ↓
调用 Hermes
  ↓
Hermes 调用 qq.reply_message 或 onebot.call
  ↓
AgentBridge 校验 run 和目标
  ↓
NapCat send_msg
```

### 被叫住后的群聊续场

```text
@bot / 回复 bot
  ↓
立即 handoff
  ↓
Hermes 回复；如果希望看到群友反应，调用 qq.extend_group_attention
  ↓
AgentBridge 打开群级注意力窗口
  ↓
窗口内普通群消息
  ↓
只入队，不刷新倒计时，不逐条调用 Hermes
  ↓
倒计时结束后打包新消息
  ↓
创建 active_dialogue agent_run
  ↓
Hermes 判断回复、SKIP，或调用 qq.extend_group_attention 继续观察
```

### Ambient 随机看群

```text
普通群消息
  ↓
写入 unread buffer 和 JSONL 归档
  ↓
泊松式调度器随机唤醒
  ↓
无未读 / 未开启 / cooldown 中则跳过
  ↓
创建 ambient agent_run
  ↓
把未读批次和归档路径交给 Hermes
  ↓
Hermes 决定 skip 或通过 skill 发言
  ↓
Bridge 清空该批 unread buffer
```

## 外部接口

NapCat -> AgentBridge：

```text
POST /onebot
```

AgentBridge -> NapCat：

```text
POST <NAPCAT_BASE_URL>/<onebot_action>
```

AgentBridge -> Hermes：

```text
POST <HERMES_BASE_URL>/v1/chat/completions
GET  <HERMES_BASE_URL>/health
```

Hermes skill -> AgentBridge：

```text
POST /skills/*
```

AgentBridge -> GitHub：

```text
GET  /repos/{owner}/{repo}/pulls
GET  /repos/{owner}/{repo}/pulls/{number}
GET  /repos/{owner}/{repo}/issues/{number}
GET  /repos/{owner}/{repo}/actions/runs
GET  /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs
POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
```

## 设计原则

- Bridge 保持机械：接入、存储、鉴权、转发、执行。
- Hermes 负责理解：项目知识、长期上下文、是否参与、如何回应。
- 原始上下文先落盘，再让 Agent 读取。
- 长上下文优先使用文件，不把 Bridge 做成搜索引擎。
- release/deploy 等高风险项目写操作保留确定性命令。
- 对可信 Agent 开放有用工具，但保留 run 过期、目标限制和 OneBot 分级。
