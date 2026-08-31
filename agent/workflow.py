from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import perf_counter

from agent.generators import AnswerGenerator
from agent.query import ContextualQueryRewriter
from app.types import SearchHit
from retrieval.evidence import EvidenceDecision, EvidenceGate
from retrieval.hybrid import HybridRetriever


@dataclass(slots=True)
class AgentState:
    question: str
    tenant_id: str
    departments: list[str]
    top_k: int
    history_questions: list[str] = field(default_factory=list)
    retrieval_query: str = ""
    hits: list[SearchHit] = field(default_factory=list)
    evidence: EvidenceDecision | None = None
    answer: str = ""
    status: str = ""
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0


class RAGWorkflow:
    """Explicit retrieve -> gate -> answer/refuse state machine.

    Keeping nodes independent makes this class easy to migrate to LangGraph when
    checkpointing, human approval or multi-agent routing is added.
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        evidence_gate: EvidenceGate,
        answer_generator: AnswerGenerator,
        query_rewriter: ContextualQueryRewriter | None = None,
    ):
        self.retriever = retriever
        self.evidence_gate = evidence_gate
        self.answer_generator = answer_generator
        self.query_rewriter = query_rewriter or ContextualQueryRewriter()

    def run(self, state: AgentState) -> AgentState:
        state = self.retrieve(state)
        state = self.check_evidence(state)
        if state.evidence and state.evidence.sufficient:
            return self.answer(state)
        return self.refuse(state)

    def retrieve(self, state: AgentState) -> AgentState:
        started = perf_counter()
        state.retrieval_query = self.query_rewriter.rewrite(
            state.question,
            state.history_questions,
        )
        state.hits = self.retriever.search(
            state.retrieval_query,
            tenant_id=state.tenant_id,
            departments=state.departments,
            top_k=state.top_k,
        )
        state.retrieval_ms = (perf_counter() - started) * 1000
        return state

    def check_evidence(self, state: AgentState) -> AgentState:
        state.evidence = self.evidence_gate.evaluate(
            state.retrieval_query or state.question,
            state.hits,
        )
        return state

    def answer(self, state: AgentState) -> AgentState:
        started = perf_counter()
        state.answer = self.answer_generator.generate(
            state.retrieval_query or state.question,
            state.hits,
        )
        state.generation_ms = (perf_counter() - started) * 1000
        valid_references = {
            int(value)
            for value in re.findall(r"\[(\d+)\]", state.answer)
            if 1 <= int(value) <= len(state.hits)
        }
        if not valid_references:
            state.answer = (
                "生成结果未能提供可核验的有效引用，因此系统拒绝返回该答案。"
                "请补充更直接的资料或稍后重试。"
            )
            state.status = "insufficient_evidence"
            if state.evidence:
                state.evidence.sufficient = False
                state.evidence.reason = "生成结果缺少有效证据引用"
            return state
        state.status = "answered"
        return state

    @staticmethod
    def refuse(state: AgentState) -> AgentState:
        reason = state.evidence.reason if state.evidence else ""
        if "提示注入" in reason:
            state.answer = (
                "该请求包含试图忽略规则、绕过权限或获取系统提示词的指令。"
                "知识库不会执行此类提示注入内容。"
            )
        elif reason.startswith("安全策略拒绝"):
            state.answer = (
                "该问题请求披露敏感个人信息或认证凭据。出于隐私与安全要求，"
                "普通知识库不会检索或返回身份证号码、密码、令牌、私钥或访问密钥等具体值。"
            )
        else:
            state.answer = (
                "当前知识库没有足够证据回答这个问题。你可以补充相关制度、产品或 SOP 文档，"
                "或者提供更具体的关键词后再试。"
            )
        state.status = "insufficient_evidence"
        return state
