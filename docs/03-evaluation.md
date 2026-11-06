# 测试与评估

真实模型记录在 `examples/*.output.json`。模型是 `deepseek-v4-flash`，温度 0，`mode` 为 `live_model`。脚本重放由 `tests/` 检查，不代替这些记录。

## 如何复现

```sh
python3 -m pip install -r requirements.txt
# 无密钥：流程回放
python3 -m src.main --provider scripted --input examples/conflict.input.json
python3 -m unittest discover -s tests -v
# 有密钥：真实模型（会覆盖输出时用 scripts/record_examples.py）
python3 -m src.main --provider openai --input examples/conflict.input.json
```

## 真实模型用例

| 用例 | 文件 | 实测 |
|---|---|---|
| 明确答案 | [clear.output.json](../examples/clear.output.json) | `completed`。先用原句检索，再读 D05「更换周期」，引用「设备更换周期为 36 个月。」 |
| 文档冲突 | [conflict.output.json](../examples/conflict.output.json) | `needs_confirmation`。读取 D01 的 30 天和 D02 的 15 天，并列引用，没有写成「期限是 15 天」或「期限是 30 天」 |
| 资料外问题 | [insufficient.output.json](../examples/insufficient.output.json) | `insufficient_evidence`。原句没有命中，改写成「班车」后读到的是交通费条款，引用为空，没有编造发车时间 |
| 换说法 | [paraphrase.output.json](../examples/paraphrase.output.json) | 原句「每年的 PTO 份额是几天？」没有命中，下一步检索词改为「年假」，再读 D03 和 D04，因天数冲突停在 `needs_confirmation` |
| 上下文追问 | [followup.output.json](../examples/followup.output.json) | 上文是年假，当前检索「病假有多少天？」，读取病假章节后 `completed`，引用的是医疗期原文 |
| 工具失败 | [tool-failure.output.json](../examples/tool-failure.output.json) | 检索失败后主代理用相同问题再试一次，仍失败，`tool_error`，引用为空，回答里没有年假天数 |

考核要求「至少两条路径体现根据工具结果调整动作」：冲突样例在读到两边期限后改为请求确认；改写样例在空检索后更换检索词。轨迹字段含步骤、工具参数、返回摘要、后续动作与 `decision_basis`。

## 其他输入（无单独 live 输出）

| 用例 | 文件 | 说明 |
|---|---|---|
| 步数上限 | [step-limit.input.json](../examples/step-limit.input.json) | `max_steps=1`，返回 `incomplete` |
| 闲聊 | [chat.input.json](../examples/chat.input.json) / [chat-thanks.input.json](../examples/chat-thanks.input.json) | 不调检索，直接 `completed` 闲聊回复 |

## 自动化测试

| 测试 | 覆盖 |
|---|---|
| `tests/test_examples.py` | 六项输入的脚本模式状态与关键断言 |
| `ContentSwapTests` | 读取 D05 时临时把「36 个月」换成「24 个月」；引用月数变为 24，不再出现 36 |
| `tests/test_agent.py` / `test_tools.py` / `test_retrieval.py` / `test_memory.py` | 循环、工具、检索与记忆单元行为 |

换文测试不修改仓库里的制度文件。

## 单次调用量

| 用例 | 主循环步数 | 耗时（秒） | prompt tokens | completion tokens |
|---|---:|---:|---:|---:|
| clear | 2 | 7.758 | 4796 | 553 |
| conflict | 2 | 10.095 | 8623 | 1052 |
| insufficient | 2 | 8.702 | 5148 | 809 |
| paraphrase | 2 | 11.686 | 11133 | 1385 |
| followup | 2 | 10.216 | 11896 | 1296 |
| tool-failure | 3 | 8.961 | 4535 | 560 |

主循环的一步可以包含检索子代理内部的多次检索和阅读。子代理轨迹在对应输出的 `retrieval_trace` 里。

## 曾出现的失败与修正

| 现象 | 处理 | 验证 |
|---|---|---|
| 模型把 `citations` 写成字符串数组 | 提示词要求对象形如 `{"doc_id","quote"}`；表面层剥掉 findings 全文噪声 | 重录后的冲突 / 改写输出第一次提交即过审 |
| 脚本冲突策略只读到一边 | 扩展报销冲突检测与脚本选读 | `conflict` 脚本用例并列两段 |
| 相近说法被向量直接命中，看不到改写 | 选用语料外原词「PTO」作为改写样例 | `paraphrase.output.json` 可见空检索后再查「年假」 |

## 限制

- `--provider scripted` 只说明没有密钥时流程能走通，不能证明模型会改下一步。
- 第一次检索被要求使用用户原句。向量检索仍可能让相近说法直接命中；PTO 这条例外，是因为原词不在语料里且相似度低于阈值。
- 检查器退回没有原文支持的引用，以及已读原文冲突却提交 `completed` 的回答。最终状态仍由模型提交。
- 再次执行时措辞可能变化。状态、引用和是否改写检索词应以当时的输出为准。
