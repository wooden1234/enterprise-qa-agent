"""本地 BM25。中文分词与 fin-harness 一样使用 jieba，并保留制度里的专有词。"""

from __future__ import annotations

import math

_DOMAIN_WORDS = (
    "年假",
    "年休假",
    "带薪年假",
    "带薪休假",
    "病假",
    "事假",
    "婚假",
    "丧假",
    "产假",
    "工伤假",
    "法定节假日",
    "补休假",
    "办公设备",
    "更换周期",
    "报销",
)
_STOPWORDS = {
    "我们",
    "公司",
    "可以",
    "进行",
    "以及",
    "或者",
    "如果",
    "因为",
    "所以",
    "这个",
    "那个",
    "什么",
    "怎么",
    "如何",
    "是否",
    "多少",
    "几天",
    "员工",
    "一个",
    "没有",
    "不是",
    "就是",
    "已经",
    "工作",
    "制度",
}
_READY = False


class BM25Okapi:
    def __init__(self, corpus_tokens, k1=1.5, b=0.75, epsilon=0.25):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus_tokens)
        self.doc_len = [len(doc) for doc in corpus_tokens]
        total = sum(self.doc_len)
        self.avgdl = (total / self.corpus_size) if self.corpus_size else 0.0
        self.df = {}
        self.tf = []
        for doc in corpus_tokens:
            freqs = {}
            for token in doc:
                freqs[token] = freqs.get(token, 0) + 1
            self.tf.append(freqs)
            for token in freqs:
                self.df[token] = self.df.get(token, 0) + 1
        self.idf = {}
        idf_sum = 0.0
        for token, freq in self.df.items():
            value = math.log(self.corpus_size - freq + 0.5) - math.log(freq + 0.5)
            self.idf[token] = value
            idf_sum += value
        average = (idf_sum / len(self.idf)) if self.idf else 0.0
        for token, value in list(self.idf.items()):
            if value < 0:
                self.idf[token] = epsilon * average

    def scores(self, query_tokens):
        scores = [0.0] * self.corpus_size
        if not query_tokens:
            return scores
        anchor = max(query_tokens, key=lambda token: self.idf.get(token, float("inf")))
        if anchor not in self.df:
            return scores
        rare = [token for token in query_tokens if 0 < self.df.get(token, 0) <= max(self.corpus_size * 0.3, 1)]
        if not rare:
            return scores
        for token in query_tokens:
            weight = self.idf.get(token)
            if weight is None:
                continue
            for index, freqs in enumerate(self.tf):
                freq = freqs.get(token) or 0
                if freq <= 0 or not any(item in freqs for item in rare):
                    continue
                length_norm = 1 - self.b + self.b * self.doc_len[index] / self.avgdl
                scores[index] += weight * freq * (self.k1 + 1) / (freq + self.k1 * length_norm)
        return scores


def tokenize(text):
    _ensure_tokenizer()
    import jieba

    tokens = []
    for token in jieba.cut(str(text or ""), cut_all=False):
        token = token.strip().lower()
        if len(token) < 2 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _ensure_tokenizer():
    global _READY
    if _READY:
        return
    import jieba

    for word in _DOMAIN_WORDS:
        jieba.add_word(word, freq=2_000_000)
    _READY = True
