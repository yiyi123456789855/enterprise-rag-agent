from __future__ import annotations

import re
from dataclasses import dataclass

from app.types import SearchHit
from retrieval.tokenizer import tokenize


@dataclass(slots=True)
class EvidenceDecision:
    sufficient: bool
    reason: str
    top_score: float
    query_coverage: float
    anchor_coverage: float = 0.0


class EvidenceGate:
    def __init__(
        self,
        min_coverage: float = 0.20,
        min_top_score: float = 0.42,
        min_anchor_coverage: float = 0.20,
    ):
        self.min_coverage = min_coverage
        self.min_top_score = min_top_score
        self.min_anchor_coverage = min_anchor_coverage

    def evaluate(self, query: str, hits: list[SearchHit]) -> EvidenceDecision:
        if _looks_like_prompt_injection(query):
            return EvidenceDecision(
                False,
                "安全策略拒绝执行提示注入或越权指令",
                hits[0].score if hits else 0.0,
                0.0,
            )
        if _requests_sensitive_value(query):
            return EvidenceDecision(
                False,
                "安全策略拒绝披露敏感个人标识、认证凭据或访问密钥",
                hits[0].score if hits else 0.0,
                0.0,
            )
        if not hits:
            return EvidenceDecision(False, "知识库中没有当前用户可访问的候选资料", 0.0, 0.0)
        query_tokens = set(tokenize(query, remove_stopwords=True))
        evidence_tokens: set[str] = set()
        # Exact identifiers may occur in a lower-ranked Top-K citation even
        # when the top policy chunk contains the general rule. Check all
        # accessible candidates so a query such as "two 800-yuan orders" can
        # use the general aggregation rule without weakening ACL isolation.
        evidence_text = "\n".join(hit.chunk.content for hit in hits).lower()
        for hit in hits[:3]:
            evidence_tokens.update(tokenize(hit.chunk.content, remove_stopwords=True))
        coverage = len(query_tokens & evidence_tokens) / max(1, len(query_tokens))
        query_anchors = _anchor_tokens(query_tokens)
        evidence_anchors = _anchor_tokens(evidence_tokens)
        anchor_coverage = len(query_anchors & evidence_anchors) / max(1, len(query_anchors))
        top_score = hits[0].score
        anchors_sufficient = not query_anchors or anchor_coverage >= self.min_anchor_coverage
        required_exact_anchors = _required_exact_anchors(query)
        missing_exact_anchors = [
            anchor for anchor in required_exact_anchors if anchor not in evidence_text
        ]
        exact_anchors_sufficient = not missing_exact_anchors
        sufficient = (
            coverage >= self.min_coverage
            and anchors_sufficient
            and exact_anchors_sufficient
            and top_score >= self.min_top_score
        )
        if sufficient:
            reason = "候选片段同时满足相关性与问题词覆盖阈值"
        elif not exact_anchors_sufficient:
            reason = "候选资料未覆盖问题中的精确编号、金额或模型指标"
        elif not anchors_sufficient:
            reason = "候选资料未覆盖问题中的关键实体、时间或专有名词"
        elif coverage < self.min_coverage:
            reason = "候选资料对问题关键信息覆盖不足"
        else:
            reason = "最高相关性分数低于回答阈值"
        return EvidenceDecision(sufficient, reason, top_score, coverage, anchor_coverage)


_SENSITIVE_VALUE_TERMS = re.compile(
    r"(?:身份证(?:号|号码)?|护照(?:号|号码)?|银行卡(?:号|号码)?|"
    r"密码|口令|验证码|私钥|密钥|访问令牌|刷新令牌|"
    r"access\s*token|refresh\s*token|api[\s_-]*key|secret)",
    re.IGNORECASE,
)
_DISCLOSURE_INTENT = re.compile(
    r"(?:是多少|是什么|告诉我|提供|给我|发我|查询|查看|显示|列出|输出|导出|完整内容|具体值)",
    re.IGNORECASE,
)
_PROMPT_INJECTION = re.compile(
    r"(?:忽略|无视|绕过|覆盖).{0,12}(?:之前|以上|系统|安全|权限|指令|规则)|"
    r"(?:输出|显示|泄露|告诉我).{0,12}(?:系统提示词|开发者消息|隐藏指令)|"
    r"(?:假装|切换|进入).{0,8}(?:管理员|开发者|无安全限制)",
    re.IGNORECASE,
)
_GENERIC_ANCHORS = {
    "多少", "什么", "如何", "怎么", "是否", "能否", "需要", "问题", "这个",
    "这家", "公司", "员工", "规定", "要求", "情况", "一个", "哪些", "可以",
}


def _requests_sensitive_value(query: str) -> bool:
    """Reject requests for secret values without blocking security-policy questions.

    Questions such as “密码泄露后如何处理” remain answerable, while requests
    such as “管理员密码是什么” or “CEO 身份证号码是多少” are denied before
    any retrieved passage can be mistaken for an answer.
    """

    normalized = " ".join(query.strip().split())
    return bool(
        _SENSITIVE_VALUE_TERMS.search(normalized)
        and _DISCLOSURE_INTENT.search(normalized)
    )


def _looks_like_prompt_injection(query: str) -> bool:
    return bool(_PROMPT_INJECTION.search(" ".join(query.strip().split())))


def _anchor_tokens(tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if len(token) >= 2 and token not in _GENERIC_ANCHORS
    }


def _required_exact_anchors(query: str) -> set[str]:
    """Return identifiers that must occur verbatim in accessible evidence.

    Short values such as "7天" may legitimately match a policy range, so they
    are not required verbatim. Longer numbers and letter-number identifiers
    identify a specific project, amount, year or metric and prevent an ACL or
    deleted-document query from being answered using generic public material.
    """

    normalized = " ".join(query.lower().split())
    identifiers = set(
        re.findall(r"(?<![a-z0-9])[a-z]+\d+[a-z0-9_-]*(?![a-z0-9])", normalized)
    )
    years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", normalized))
    chinese_project_codes = set(
        re.findall(
            r"[\u3400-\u9fff]{1,8}\d{2,}(?=项目|工程|计划|产品|型号|版本|批次)",
            normalized,
        )
    )
    return identifiers | years | chinese_project_codes
