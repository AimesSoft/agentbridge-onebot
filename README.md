# AgentBridge for OneBot

让梨花（NipaPlay）的 Agent 住进 QQ 群。

AgentBridge 是为梨花（NipaPlay / NipaPlay-Reload）社区维护场景开发的 QQ/OneBot 11 Agent 接入后端。下层对接 NapCat 等 OneBot 11 兼容适配器，上层对接 Hermes、OpenClaw 或任何 OpenAI-compatible 的 Agent。

它不是传统命令机器人。Agent 可以被 @ 后正常继续对话，也可以像真实群成员一样偶尔看一眼未读消息，自己决定要不要说话。

## 关键能力

- 私聊、@bot、回复 bot、关键词会立即转交 Agent。
- Agent 在群里实际发言后会打开群级注意力窗口，窗口内群聊会在安静一小段时间后打包交给 Agent 继续判断。
- 普通群聊可以进入 ambient 未读 buffer，由泊松式随机调度模拟“随机看手机”。
- 群消息保存为 SQLite 索引和 JSONL 归档，Agent 需要长上下文时自己读文件。
- release/deploy 等高风险 GitHub 操作走管理员硬命令，不交给 LLM 自由触发。
- 提供 Hermes/OpenClaw skill，用于 QQ 消息、私聊、群管、OneBot 调用和 GitHub 状态查询。

## 兼容性

**下层（OneBot 11 适配器）**
- NapCat
- LLOneBot
- 任何 OneBot 11 兼容实现

**上层（Agent）**
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)，附带开箱即用的 agentbridge skill
- [OpenClaw](https://github.com/openclaw/openclaw)
- 任何支持 OpenAI-compatible chat completions 的 Agent

## 快速开始

```bash
git clone https://github.com/AimesSoft/agentbridge-onebot.git
cd agentbridge-onebot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
agentbridge
```

NapCat HTTP Client 指向 `http://127.0.0.1:8787/onebot`。

完整配置和部署文档见 [docs/](docs/)。

## 许可证

MIT
