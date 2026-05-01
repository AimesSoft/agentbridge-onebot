# agentbridge-skill

Hermes/OpenClaw 侧的 `agentbridge` skill。它只负责把 agent 的 QQ/OneBot/GitHub 状态请求转发给 AgentBridge。

安装：

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

环境变量：

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<same token as AgentBridge>
```

注意：

- 上下文由 AgentBridge handoff 文本和 JSONL 归档文件提供，skill 不提供上下文搜索接口。
- 每次调用都必须带 `run_id`。
- release/deploy/merge 仍然走 AgentBridge 硬命令层。
- OneBot/NapCat 协议参考见 `SKILL.md`，常见动作有专用 helper，不常见动作走 `onebot-call`。

示例：

```bash
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py reply-message --run-id <run_id> --message-id <message_id> --text "我看一下。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py onebot-call --run-id <run_id> --action get_group_info --params-json '{"group_id":123}'
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py workflow-status --run-id <run_id> --repo default
```
