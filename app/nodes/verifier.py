from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.models.schemas import TargetSelection, TargetBlock, EvidenceQuote, BlockCandidate
from app.models import database as db_models
from app.services.llm_client import get_qwen_client
from app.utils.markdown import normalize_text
import json
import uuid


class VerifierNode:
    """定位验证节点"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """验证并选择目标块"""
        # 如果用户已经选择了候选，直接使用
        if state.get("user_selection"):
            selected_block = self._find_block_by_id(
                state["candidates"],
                state["user_selection"]
            )
            if selected_block:
                evidence = self._extract_evidence(selected_block)
                state["selection"] = TargetSelection(
                    targets=[TargetBlock(
                        block_id=selected_block.block_id,
                        evidence=evidence,
                        confidence=1.0
                    )],
                    need_user_disambiguation=False,
                    reasoning="用户手动选择"
                )
                return state
        
        candidates = state.get("candidates", [])
        if not candidates:
            state["error"] = {"code": "no_candidates", "message": "未找到匹配的内容"}
            return state
        
        # 如果只有一个候选且分数很高，直接选择
        if len(candidates) == 1 and candidates[0].score > 0.5:
            evidence = self._extract_evidence(candidates[0])
            state["selection"] = TargetSelection(
                targets=[TargetBlock(
                    block_id=candidates[0].block_id,
                    evidence=evidence,
                    confidence=candidates[0].score
                )],
                need_user_disambiguation=False,
                reasoning="唯一匹配且置信度高"
            )
            return state
        
        # 如果有多个候选，使用 LLM 选择
        try:
            selection = self._llm_select(state["intent"], candidates)
            
            # 验证 evidence_quote
            for target in selection.targets:
                block = self._get_block_by_id(target.block_id, state["active_rev_id"])
                if block and not self._verify_evidence(block.plain_text, target.evidence):
                    target.confidence *= 0.5
            
            state["selection"] = selection
            return state
            
        except Exception as e:
            # 降级：返回候选列表让用户选择
            state["selection"] = TargetSelection(
                targets=[],
                need_user_disambiguation=True,
                candidates_for_user=candidates[:5],
                reasoning="自动选择失败，需要用户确认"
            )
            state["error"] = {"code": "verification_failed", "message": str(e)}
            return state
    
    def _llm_select(self, intent, candidates: List[BlockCandidate]) -> TargetSelection:
        """使用 LLM 选择目标块"""
        system_prompt = """你是一个文档定位助手。

关键规则：
1. evidence_quote 必须从候选段落的 snippet 中"逐字截取"（10~50 字）
2. 必须给出 start 和 end 位置（在 snippet 中的字符索引）
3. 如果有多个候选都很相似，设置 need_user_disambiguation=true
4. confidence < 0.7 时，必须返回候选列表让用户选择

输出 JSON 格式：
{
  "targets": [
    {
      "block_id": "uuid",
      "evidence": {
        "text": "逐字截取的文本",
        "start": 0,
        "end": 20
      },
      "confidence": 0.9
    }
  ],
  "need_user_disambiguation": false,
  "reasoning": "选择理由"
}
"""
        
        candidates_text = "\n\n".join([
            f"候选 {i+1}:\nblock_id: {c.block_id}\n章节: {c.heading_context}\n内容: {c.snippet}\n分数: {c.score}"
            for i, c in enumerate(candidates[:5])
        ])
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户意图：\n{intent.model_dump_json(indent=2)}\n\n候选段落：\n{candidates_text}\n\n输出 JSON："}
        ]
        
        response = self.llm.chat_completion_json(messages, temperature=0.3)
        selection_data = json.loads(response)
        
        return TargetSelection(**selection_data)
    
    def _extract_evidence(self, candidate: BlockCandidate) -> EvidenceQuote:
        """从候选中提取证据"""
        text = candidate.snippet[:50]
        return EvidenceQuote(
            text=text,
            start=0,
            end=len(text)
        )
    
    def _verify_evidence(self, plain_text: str, evidence: EvidenceQuote) -> bool:
        """验证证据引用"""
        # 精确位置校验
        if evidence.start >= 0 and evidence.end <= len(plain_text):
            extracted = plain_text[evidence.start:evidence.end]
            if normalize_text(extracted) == normalize_text(evidence.text):
                return True
        
        # 子串匹配
        if normalize_text(evidence.text) in normalize_text(plain_text):
            return True
        
        return False
    
    def _find_block_by_id(self, candidates: List[BlockCandidate], block_id: str) -> BlockCandidate:
        """根据 ID 查找候选"""
        for c in candidates:
            if c.block_id == block_id:
                return c
        return None
    
    def _get_block_by_id(self, block_id: str, rev_id: str) -> db_models.BlockVersion:
        """根据 ID 获取块"""
        return self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == uuid.UUID(block_id),
            db_models.BlockVersion.rev_id == uuid.UUID(rev_id)
        ).first()
