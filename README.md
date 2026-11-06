# 企业知识问答 Agent

员工用自然语言问制度问题。系统只根据已读原文回答，冲突时并列引用并请求确认，资料不足或工具失败时明确停住，不编造事实。交付物是本地 CLI 和可核对的运行记录，不含界面、权限和线上部署。

## 做什么

| 场景 | 期望行为 |
|---|---|
| 只有一份依据 | `completed`，回答与引用片段一致 |
| 两份制度冲突且无优先级 | `needs_confirmation`，并列引用，不选定一边 |
| 语料外问题 | `insufficient_evidence`，说明缺口，引用为空 |
| 换说法提问 | 可用空检索改写检索词后再查 |
| 带历史追问 | 按当前问题检索，不套用上一题答案 |
| 工具失败 | `tool_error`，不把失败写成已经查到 |
| 达到步数上限 | `incomplete` |

参考冲突：D01《财务报销制度及报销流程》写报销期限 30 天，D02《费用报销管理办法》写 15 天。问「报销期限多久」必须并列引用并请求确认。

## 怎么做

两层 ReAct 循环，每步由模型选一个动作，工具结果写回对话后再决定下一步。

```text
主代理（默认最多 8 步）
  consult_retrieval → 检索子代理
  submit_answer     → 引用与冲突检查后结束

检索子代理（LangGraph：decide → search | read | submit_findings）
  search_documents  → 向量 + BM25 + RRF（可选重排），只返回命中摘要
  read_document     → 按 section_id 读章节原文
  submit_findings   → 把 findings / gaps / confirmation 交回主代理
```

提交前检查：引用必须来自已读原文；已读内容出现冲突天数且无优先级时，拒绝 `completed`。长期偏好（语言、详略、引用偏好）存在 Postgres `enterprise_qa`，写入主代理系统提示。

没有密钥时用 `--provider scripted`。该模式按固定策略选动作，`mode` 为 `scripted_mock`，只能验证流程，不能证明模型会改下一步。仓库里六项验收输出是真实模型 `deepseek-v4-flash` 的一次运行，`mode` 为 `live_model`。

## 环境

- Python 3.11（`requirements.txt` 写 3.8+）
- 依赖：`jieba`、`psycopg2-binary`、`langgraph`、`langsmith`
- 模型：OpenAI 兼容接口（默认 DeepSeek）
- 可选：Postgres + pgvector（切片与长期记忆）；DashScope 嵌入 / 重排

```sh
python3 -m pip install -r requirements.txt
cp .env.example .env   # 填入密钥，勿提交 .env
```

常用环境变量见 `.env.example`：`OPENAI_*` / `DEEPSEEK_*`、`EMBEDDING_*`、`PGVECTOR_DATABASE_URL`、`LANGSMITH_*`。也可设 `ENV_FILE` 指向本机环境文件。

### 知识库

语料在 `data/*.md`，目录在 `data/documents.json`（D01–D05）。构建与入库：

```sh
python3 -m src.retrieval.build     # 写出 data/kb/chunks.jsonl 与 vectors.json
python3 -m src.retrieval.pgstore   # 写入 enterprise_qa.documents / policy_chunks
```

配置了数据库时向量检索走 Postgres；未配置时用本地切片文件。

## 运行

在仓库根目录：

```sh
# 无密钥：脚本模式跑通验收输入
python3 -m src.main --provider scripted --input examples/clear.input.json
python3 -m src.main --provider scripted --input examples/conflict.input.json
python3 -m src.main --provider scripted --input examples/insufficient.input.json
python3 -m src.main --provider scripted --input examples/paraphrase.input.json
python3 -m src.main --provider scripted --input examples/followup.input.json
python3 -m src.main --provider scripted --input examples/tool-failure.input.json
python3 -m src.main --provider scripted --input examples/step-limit.input.json

# 有密钥：真实模型
python3 -m src.main --provider openai --input examples/conflict.input.json

# 重录六项验收输出（会覆盖 examples/*.output.json）
python3 scripts/record_examples.py

# 测试（含换文核对：临时把 D05「36 个月」换成「24 个月」）
python3 -m unittest discover -s tests -v
```

输入 JSON 至少含 `question`；可选 `history`、`max_steps`（1–12，默认 8）、`fail_tool` 等。业务结果以 JSON 打到 stdout，退出码 0。解析失败或模型错误时 stderr 打印 `invalid_input` / `model_error`，退出码 2。

闲聊样例：`examples/chat.input.json`、`examples/chat-thanks.input.json`。步数上限：`examples/step-limit.input.json` 将 `max_steps` 设为 1，命中后返回 `incomplete`（无单独 live 输出）。

## 验收样例

| 用例 | 输出 | 状态要点 |
|---|---|---|
| 明确答案 | [clear.output.json](examples/clear.output.json) | 引用 D05「设备更换周期为 36 个月。」 |
| 文档冲突 | [conflict.output.json](examples/conflict.output.json) | 并列 D01 30 天与 D02 15 天 |
| 资料不足 | [insufficient.output.json](examples/insufficient.output.json) | 引用为空，不编造 |
| 换说法 | [paraphrase.output.json](examples/paraphrase.output.json) | 「PTO」未命中 → 改写「年假」 |
| 上下文追问 | [followup.output.json](examples/followup.output.json) | 按病假检索并引用原文 |
| 工具失败 | [tool-failure.output.json](examples/tool-failure.output.json) | `tool_error`，无编造天数 |

## 目录

```text
data/                 合成制度 Markdown 与 documents.json
data/kb/              切片与本地向量
docs/                 需求、方案、评估、AI 使用、复盘
examples/             输入、真实模型输出、dataset.json
scripts/              record_examples.py
src/main.py           CLI
src/harness/          主循环、工具调度、提交审核、会话
src/retrieval/        检索子代理、LangGraph、向量/BM25/RRF/重排、入库
src/memory/           长期偏好（Postgres）
tests/                样例回放、换文、检索与记忆测试
```

## 评审入口

| 检查项 | 入口 |
|---|---|
| 用户、范围、成功标准 | [docs/01-requirements.md](docs/01-requirements.md) |
| 循环、工具和取舍 | [docs/02-solution.md](docs/02-solution.md) |
| 用例、真实结果、限制 | [docs/03-evaluation.md](docs/03-evaluation.md) |
| AI 辅助和验证 | [docs/04-ai-usage.md](docs/04-ai-usage.md) |
| 未完成部分和下一步 | [docs/05-retrospective.md](docs/05-retrospective.md) |

## 已知限制

- 相近说法可能被向量检索直接命中；PTO 样例依赖原词不在语料且低于相似度阈值。
- `scripted` 不能代替 `live_model` 证明动态决策。
- 再次调用措辞可能变化；以当时输出的状态、引用和检索轨迹为准。
- 界面、权限与线上部署未做；详见 [docs/05-retrospective.md](docs/05-retrospective.md)。

仓库：https://github.com/wooden1234/enterprise-qa-agent  
提交 SHA：以 `git rev-parse HEAD` / GitHub 最新 commit 为准（当前推送基线 `2e4c2be237503199055da8680d97448ef17ed296`）。
