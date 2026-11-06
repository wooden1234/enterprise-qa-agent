# 测试与评估

真实模型记录在 `examples/*.output.json`。模型是 `deepseek-v4-flash`，温度 0，`mode` 为 `live_model`。脚本重放由 `tests/test_examples.py` 检查，不代替这些记录。

| 用例 | 文件 | 实测 |
|---|---|---|
| 明确答案 | [clear.output.json](../examples/clear.output.json) | `completed`。先用原句检索，再读 D05「更换周期」，引用「设备更换周期为 36 个月。」 |
| 文档冲突 | [conflict.output.json](../examples/conflict.output.json) | `needs_confirmation`。读取 D01 的 30 天和 D02 的 15 天，并列引用，没有写成「期限是 15 天」或「期限是 30 天」 |
| 资料外问题 | [insufficient.output.json](../examples/insufficient.output.json) | `insufficient_evidence`。原句没有命中，改写成「班车」后读到的是交通费条款，引用为空，没有编造发车时间 |
| 换说法 | [paraphrase.output.json](../examples/paraphrase.output.json) | 原句「每年的 PTO 份额是几天？」没有命中，下一步检索词改为「年假」，再读 D03 和 D04，因天数冲突停在 `needs_confirmation` |
| 上下文追问 | [followup.output.json](../examples/followup.output.json) | 上文是年假，当前检索「病假有多少天？」，读取病假章节后 `completed`，引用的是医疗期原文 |
| 工具失败 | [tool-failure.output.json](../examples/tool-failure.output.json) | 检索失败后主代理用相同问题再试一次，仍失败，`tool_error`，引用为空，回答里没有年假天数 |

## 换掉原文后的核对

`tests/test_examples.py` 的 `ContentSwapTests` 不修改仓库里的制度文件。它在读取 D05 时把「36 个月」临时换成「24 个月」，再问更换周期。引用里的月数变成 24，不再出现 36；动作仍然是先检索，再阅读。

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

## 限制

- `--provider scripted` 只说明没有密钥时流程能走通，不能证明模型会改下一步。
- 第一次检索被要求使用用户原句。向量检索仍可能让相近说法直接命中；PTO 这条例外，是因为原词不在语料里且相似度低于阈值。
- 检查器退回没有原文支持的引用，以及已读原文冲突却提交 `completed` 的回答。最终状态仍由模型提交。
- 再次执行时措辞可能变化。状态、引用和是否改写检索词应以当时的输出为准。
