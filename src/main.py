"""企业知识问答命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.agent import run
from src.llm import ModelError, OpenAICompatibleModel
from src.scripted import ScriptedModel


def build_model(provider):
    if provider == "scripted":
        return ScriptedModel()
    if provider == "openai":
        return OpenAICompatibleModel.from_env()
    raise ValueError("provider must be scripted or openai")


def answer_input(path, provider):
    request = json.loads(Path(path).read_text(encoding="utf-8"))
    return run(request, build_model(provider))


def main(argv=None):
    parser = argparse.ArgumentParser(description="企业知识问答 Agent")
    parser.add_argument("--input", required=True, help="问题 JSON 文件")
    parser.add_argument("--provider", choices=("scripted", "openai"), default="scripted")
    args = parser.parse_args(argv)
    try:
        result = answer_input(args.input, args.provider)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except ModelError as exc:
        print(json.dumps({"status": "model_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
