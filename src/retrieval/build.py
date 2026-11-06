"""构建制度知识库：先写切片，再按环境变量调用嵌入接口。"""

from __future__ import annotations

import sys

from src.retrieval.embeddings import EmbeddingError
from src.retrieval.settings import CHUNKS_PATH
from src.retrieval.store import build_vector_index, write_chunks


def main():
    path = write_chunks()
    print("chunks %s" % path)
    try:
        summary = build_vector_index()
    except EmbeddingError as exc:
        print("vectors_skipped %s" % exc, file=sys.stderr)
        print("chunks_ready %s" % CHUNKS_PATH)
        return 0
    print("vectors chunks=%s dim=%s path=%s" % (summary["chunks"], summary["dim"], summary["path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
