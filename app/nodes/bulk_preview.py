"""
批量预览节点 - 生成批量修改的预览
"""
from typing import List, Dict
from app.models.schemas import Intent, BlockCandidate, PreviewDiff, DiffItem
from app.models import database as db_models
from app.utils.markdown import strip_markdown
from sqlalchemy.orm import Session
import uuid


class BulkPreviewNode:
    """批量预览节点 - 生成批量修改的预览"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def generate_preview(
        self,
        intent: Intent,
        candidates: List[BlockCandidate],
        rev_id: str
    ) -> PreviewDiff:
        """
        生成批量修改预览
        
        Args:
            intent: 用户意图
            candidates: 候选块列表
            rev_id: 版本 ID
        
        Returns:
            预览 diff
        """
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取所有候选块的完整内容
        block_ids = [uuid.UUID(c.block_id) for c in candidates]
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id.in_(block_ids),
            db_models.BlockVersion.rev_id == rev_uuid
        ).all()
        
        # 创建 block_id -> block 的映射
        block_map = {str(b.block_id): b for b in blocks}
        
        # 生成每个块的 diff
        diffs = []
        grouped_by_heading = {}
        total_chars_added = 0
        total_chars_removed = 0
        
        for candidate in candidates:
            block = block_map.get(candidate.block_id)
            if not block:
                continue
            
            # 生成替换后的内容
            new_content = self._generate_replacement(block, intent)
            
            if new_content == block.content_md:
                # 内容没有变化，跳过
                continue
            
            # 计算字符变化
            char_diff = len(new_content) - len(block.content_md or '')
            if char_diff > 0:
                total_chars_added += char_diff
            else:
                total_chars_removed += abs(char_diff)
            
            # 创建 diff item
            before_snippet = block.plain_text[:200] if block.plain_text else ''
            after_snippet = strip_markdown(new_content)[:200]
            
            diffs.append(DiffItem(
                block_id=str(block.block_id),
                op_type="replace",
                before_snippet=before_snippet,
                after_snippet=after_snippet,
                heading_context=candidate.heading_context,
                char_diff=char_diff
            ))
            
            # 按章节分组统计
            heading = candidate.heading_context
            grouped_by_heading[heading] = grouped_by_heading.get(heading, 0) + 1
        
        # 评估影响等级
        estimated_impact = self._estimate_impact(len(diffs))
        
        return PreviewDiff(
            diffs=diffs,
            total_changes=len(diffs),
            estimated_impact=estimated_impact,
            grouped_by_heading=grouped_by_heading,
            total_chars_added=total_chars_added,
            total_chars_removed=total_chars_removed
        )
    
    def _generate_replacement(
        self,
        block: db_models.BlockVersion,
        intent: Intent
    ) -> str:
        """
        生成替换后的内容
        
        Args:
            block: 原始块
            intent: 用户意图
        
        Returns:
            替换后的内容
        """
        content = block.content_md or ''
        
        if intent.match_type == "exact_term":
            # 精确词替换
            term = intent.scope_filter.get("term", "")
            replacement = intent.scope_filter.get("replacement", "")
            
            if term and replacement:
                return content.replace(term, replacement)
        
        elif intent.match_type == "regex":
            # 正则表达式替换
            import re
            pattern_str = intent.scope_filter.get("pattern", "")
            replacement = intent.scope_filter.get("replacement", "")
            
            if pattern_str and replacement:
                try:
                    pattern = re.compile(pattern_str)
                    return pattern.sub(replacement, content)
                except re.error as e:
                    print(f"正则表达式错误: {e}")
                    return content
        
        # 其他类型需要调用 LLM 生成（暂不实现）
        return content
    
    def _estimate_impact(self, change_count: int) -> str:
        """评估影响等级"""
        if change_count > 20:
            return "high"
        elif change_count > 10:
            return "medium"
        else:
            return "low"
