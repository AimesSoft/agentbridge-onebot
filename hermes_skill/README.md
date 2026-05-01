# agentbridge-skill

这是 Hermes/OpenClaw 侧的 `agentbridge` skill，用于让 Hermes 通过 AgentBridge 参与 NipaPlay / 梨花 QQ 社区。

它只负责把 Agent 的 QQ、OneBot、群管和 GitHub 状态请求转发给 AgentBridge。真实 QQ 操作由 AgentBridge 再调用 NapCat / OneBot 执行。

## 安装

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

## 环境变量

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<与 AgentBridge 一致>
```

## 约定

- 每次调用都必须带 AgentBridge handoff 上下文里的 `run_id`。
- 上下文由 handoff 文本和 JSONL 归档文件提供，skill 不提供上下文搜索接口。
- release、deploy、merge 保留在 AgentBridge 硬命令层。
- OneBot/NapCat 协议参考见 `SKILL.md`。
- 常见动作有专用 helper，不常见动作走 `onebot-call`。

## 示例

```bash
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py reply-message --run-id <run_id> --message-id <message_id> --text "我看一下。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-private-message --run-id <run_id> --user-id <user_id> --text "私聊回复。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py onebot-call --run-id <run_id> --action get_group_info --params-json '{"group_id":123}'
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py workflow-status --run-id <run_id> --repo default
```
