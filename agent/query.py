from __future__ import annotations

import re


_CONTEXT_MARKERS = re.compile(
    r"(?:它|这个|该|上述|前面|刚才|其中|那么|那如果|这种情况|这项|这条|此时)"
)
_IMPLICIT_FOLLOW_UP = re.compile(
    r"^(?:还|那么|那)?(?:需要|要|应|应该|可以|能|多久|多少|谁|如何|怎么|何时|什么时候)"
)


class ContextualQueryRewriter:
    """Small deterministic follow-up rewriter that works without an LLM.

    It only adds the last question when the new turn contains a clear contextual
    marker. Standalone questions are left untouched, avoiding unnecessary query
    drift. An external LLM can later replace this component behind the same API.
    """

    def rewrite(self, question: str, history_questions: list[str]) -> str:
        cleaned = question.strip()
        is_short_implicit_follow_up = (
            len(cleaned) <= 24 and bool(_IMPLICIT_FOLLOW_UP.search(cleaned))
        )
        if not history_questions or not (
            _CONTEXT_MARKERS.search(cleaned) or is_short_implicit_follow_up
        ):
            return cleaned
        previous = history_questions[-1].strip()
        if not previous:
            return cleaned
        return f"上下文问题：{previous}\n当前追问：{cleaned}"
