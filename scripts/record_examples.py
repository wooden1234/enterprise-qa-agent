"""用真实模型重放 examples/*.input.json，并覆盖对应输出。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import run
from src.llm import OpenAICompatibleModel

CASES = (
    "clear",
    "conflict",
    "insufficient",
    "paraphrase",
    "followup",
    "tool-failure",
    "step-limit",
    "chat",
    "chat-thanks",
)


def main():
    model = OpenAICompatibleModel.from_env()
    lines = ["provider=openai", "model=%s" % model.model_name]
    for name in CASES:
        request = json.loads((ROOT / "examples" / ("%s.input.json" % name)).read_text(encoding="utf-8"))
        model.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        result = run(request, model)
        target = ROOT / "examples" / ("%s.output.json" % name)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines.append(
            "%s status=%s steps=%d mode=%s"
            % (name, result["status"], len(result["trace"]), result["mode"])
        )
        print(lines[-1])
    (ROOT / "examples" / "test-results.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
