# 需求理解

| 项目 | 定义 |
|---|---|
| 用户 | 需要查制度或产品规定的员工 |
| 目标 | 给出能回溯到原文的答案；资料不足或互相冲突时明确停下来，不编造事实 |
| 输入 | 当前问题，可选对话历史；可注入工具失败（`fail_tool`）或步数上限（`max_steps`） |
| 材料 | `data/documents.json` 与 `data/*.md` 合成制度（D01–D05）；`data/rules.md` 规定引用与冲突处理 |
| 输出 | 回答、引用（`doc_id` + 原文片段）、资料缺口、需确认问题、任务状态、主循环与检索轨迹 |
| 范围 | 本地 CLI。检索为向量 + BM25 + RRF（可选重排）。切片可入 Postgres/pgvector，并保留本地切片 |
| 不包含 | 真实发布、权限系统、界面、线上部署、生产级 Runtime |

## 成功标准

- 只有一份资料支持、且已读原文无冲突时，状态为 `completed`，回答与引用片段一致。
- 两份资料对同一事项给出不同事实且没有优先级时，状态为 `needs_confirmation`，并列引用并请求确认，不选定其中一个。
- 资料库没有依据时，状态为 `insufficient_evidence`，说明缺口，引用为空，不补写事实。
- 换一种说法提问时，第一次用原句检索；未命中后可以根据空结果改写检索词再查。
- 追问使用对话历史理解指代，按当前问题检索，不把上一题答案套到新问题上。
- 工具失败返回 `tool_error`，不把失败写成已经查到。
- 达到 `max_steps` 时返回 `incomplete`。

## 验收场景映射

| 考核点 | 输入 | 期望状态 |
|---|---|---|
| 明确答案 | `examples/clear.input.json` | `completed`，引用 D05「36 个月」 |
| 文档冲突 | `examples/conflict.input.json` | `needs_confirmation`，并列 D01 30 天与 D02 15 天 |
| 资料外 | `examples/insufficient.input.json` | `insufficient_evidence`，引用为空 |
| 换说法 / 改写检索 | `examples/paraphrase.input.json` | 原句「PTO」未命中后改写「年假」；年假两版冲突则 `needs_confirmation` |
| 上下文追问 | `examples/followup.input.json` | 按病假检索并引用原文 |
| 工具失败 | `examples/tool-failure.input.json` | `tool_error` |
| 步数上限 | `examples/step-limit.input.json` | `incomplete`（`max_steps=1`） |

## 参考冲突

- **报销期限：** D01《财务报销制度及报销流程》写「报销期限为 30 天」，D02《费用报销管理办法》写「报销期限为 15 天」，两处都没有适用范围和优先级。问「报销期限多久」必须并列引用并请求确认，不能回答成 15 天或 30 天。
- **年假天数：** 两版《假期管理制度》（D03 / D04）对不满 10 年的年假分别写 5 个工作日和 10 个工作日，同样不能选定其中一个。
- **可完成回答：** 只有一份资料支持且已读无冲突时，可以依据该份回答，例如 D05 的设备更换周期 36 个月。

高分观察点在检索改进与冲突处理；无证据或错误引用视为关键缺陷。
