from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]+|[a-zA-Z0-9_]+")
STOPWORDS = {
    "的", "了", "和", "是", "在", "请", "问", "有", "什么", "如何", "能否", "是否",
    "a", "an", "the", "is", "are", "of", "to", "and", "or", "for", "in",
}


def tokenize(text: str, *, remove_stopwords: bool = False) -> list[str]:
    tokens: list[str] = []
    for segment in TOKEN_PATTERN.findall(text):
        normalized = segment.lower()
        if re.fullmatch(r"[\u3400-\u9fff]+", normalized):
            characters = list(normalized)
            tokens.extend(characters)
            tokens.extend(
                normalized[index : index + 2]
                for index in range(max(0, len(normalized) - 1))
            )
        else:
            tokens.append(normalized)
    if remove_stopwords:
        return [token for token in tokens if token not in STOPWORDS]
    return tokens


def approximate_token_count(text: str) -> int:
    return len(tokenize(text))
