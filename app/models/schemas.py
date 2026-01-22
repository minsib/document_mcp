from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict
from uuid import UUID
from datetime import datetime


# ============ Intent 相关 ============
class ScopeHint(BaseModel):
    heading: Optional[str] = Field(None, description="章节名称")
    nearby: Optional[str] = Field(None, description="相对位置")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    block_type: Optional[str] = Field(None, description="块类型过滤")


class Constraints(BaseModel):
    tone: Literal["formal", "neutral", "casual"] = "neutral"
    keep_length: Literal["shorter", "similar", "longer"] = "similar"
    must_include: List[str] = Field(default_factory=list)
    must_exclude: List[str] = Field(default_factory=list)


class Intent(BaseModel):
    operation: Literal["replace", "insert_after", "insert_before", "delete", "multi_replace"]
    scope_hint: ScopeHint
    constraints: Constraints
    risk: Literal["low", "medium", "high"]
    match_type: Optional[Literal["exact_term", "regex", "semantic"]] = None
    apply_scope: Optional[Literal["single", "all_matches", "within_heading"]] = None
    scope_filter: Optional[dict] = None


# ============ 定位相关 ============
class BlockCandidate(BaseModel):
    block_id: str
    snippet: str = Field(..., description="候选片段摘要")
    heading_context: str = Field(..., description="所属章节")
    order_index: int
    score: float = Field(..., description="相关性分数")
    block_type: str = "paragraph"


class EvidenceQuote(BaseModel):
    text: str = Field(..., description="证据引用文本")
    start: int = Field(..., description="起始位置")
    end: int = Field(..., description="结束位置")


class TargetBlock(BaseModel):
    block_id: str
    evidence: EvidenceQuote
    confidence: float = Field(..., ge=0.0, le=1.0)


class TargetSelection(BaseModel):
    targets: List[TargetBlock]
    need_user_disambiguation: bool = False
    candidates_for_user: List[BlockCandidate] = Field(default_factory=list)
    reasoning: str = Field(..., description="选择理由")


# ============ 编辑计划相关 ============
class EditOperation(BaseModel):
    op_type: Literal["replace", "insert_after", "insert_before", "delete"]
    target_block_id: str
    evidence: EvidenceQuote
    new_content_md: Optional[str] = None
    rationale: str = Field(..., max_length=200)


class EditPlan(BaseModel):
    doc_id: str
    rev_id: str
    operations: List[EditOperation]
    estimated_impact: Literal["low", "medium", "high"]
    requires_confirmation: bool = False


# ============ 预览相关 ============
class DiffItem(BaseModel):
    block_id: str
    op_type: str
    before_snippet: str
    after_snippet: str
    heading_context: str
    char_diff: int


class PreviewDiff(BaseModel):
    diffs: List[DiffItem]
    total_changes: int
    estimated_impact: Literal["low", "medium", "high"]
    grouped_by_heading: Optional[Dict[str, int]] = None
    total_chars_added: int = 0
    total_chars_removed: int = 0


# ============ API 请求/响应 ============
class UploadDocumentRequest(BaseModel):
    title: str
    content: Optional[str] = None


class UploadDocumentResponse(BaseModel):
    doc_id: str
    rev_id: str
    block_count: int
    title: str


class ChatEditRequest(BaseModel):
    doc_id: str
    session_id: Optional[str] = None
    message: str
    user_selection: Optional[str] = None


class CandidateResponse(BaseModel):
    block_id: str
    snippet: str
    heading_context: str
    order_index: int


class ChatEditResponse(BaseModel):
    status: Literal["need_disambiguation", "need_confirm", "applied", "failed"]
    candidates: Optional[List[CandidateResponse]] = None
    preview: Optional[PreviewDiff] = None
    confirm_token: Optional[str] = None
    preview_hash: Optional[str] = None
    new_rev_id: Optional[str] = None
    diff_summary: Optional[List[DiffItem]] = None
    export_md: Optional[str] = None
    error: Optional[dict] = None
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    doc_id: str
    confirm_token: str
    action: Literal["apply", "cancel"]
    preview_hash: str


class ConfirmResponse(BaseModel):
    status: Literal["applied", "cancelled", "failed"]
    new_rev_id: Optional[str] = None
    export_md: Optional[str] = None
    error: Optional[dict] = None
    message: str


class RevisionResponse(BaseModel):
    rev_id: str
    rev_no: int
    created_by: str
    created_at: datetime
    change_summary: Optional[str]
    is_active: bool


class ListRevisionsResponse(BaseModel):
    revisions: List[RevisionResponse]
    total: int


class RollbackRequest(BaseModel):
    target_rev_id: str
    target_rev_no: int


class RollbackResponse(BaseModel):
    new_rev_id: str
    new_rev_no: int
    message: str


# ============ 内部状态 ============
class ErrorInfo(BaseModel):
    code: str
    message: str


class ApplyResult(BaseModel):
    new_rev_id: str
    new_rev_no: int
    new_version: int
    op_ids: List[str]
