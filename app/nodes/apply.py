from typing import Dict, Any, List, Set, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.schemas import ApplyResult, ErrorInfo
from app.models import database as db_models
from app.utils.markdown import hash_content, strip_markdown
import uuid
from datetime import datetime


class ApplyEditsNode:
    """应用编辑节点"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """应用编辑"""
        edit_plan = state.get("edit_plan")
        if not edit_plan:
            state["error"] = ErrorInfo(code="no_edit_plan", message="没有编辑计划")
            return state
        
        doc_id = uuid.UUID(state["doc_id"])
        active_rev_id = uuid.UUID(state["active_rev_id"])
        active_version = state["active_version"]
        
        try:
            # 1. 读取当前 revision 的所有 block_versions
            current_blocks = self.db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.rev_id == active_rev_id
            ).order_by(db_models.BlockVersion.order_index).all()
            
            # 2. 校验所有 operations
            for op in edit_plan.operations:
                self._validate_operation(current_blocks, op)
            
            # 3. 执行变更
            new_blocks, changed_block_ids = self._apply_operations(
                current_blocks,
                edit_plan.operations,
                doc_id
            )
            
            # 4. 创建新 revision
            new_rev_no = self._get_next_rev_no(doc_id)
            new_rev = db_models.DocumentRevision(
                rev_id=uuid.uuid4(),
                doc_id=doc_id,
                rev_no=new_rev_no,
                parent_rev_id=active_rev_id,
                created_by="ai",
                change_summary=self._generate_summary(edit_plan.operations)
            )
            self.db.add(new_rev)
            self.db.flush()
            
            # 5. 插入新 block_versions
            for block in new_blocks:
                block.rev_id = new_rev.rev_id
                self.db.add(block)
            
            # 6. 写入 edit_operations（审计）
            for op in edit_plan.operations:
                edit_op = db_models.EditOperation(
                    op_id=uuid.uuid4(),
                    doc_id=doc_id,
                    rev_id=new_rev.rev_id,
                    parent_rev_id=active_rev_id,
                    user_id=uuid.UUID(state["user_id"]),
                    op_type=op.op_type,
                    target_block_id=uuid.UUID(op.target_block_id),
                    evidence_quote=op.evidence.text,
                    quote_start=op.evidence.start,
                    quote_end=op.evidence.end,
                    rationale=op.rationale,
                    status="applied"
                )
                self.db.add(edit_op)
            
            # 7. 更新 active_rev（CAS 操作）
            from sqlalchemy import text
            result = self.db.execute(
                text("""
                UPDATE document_active_revision
                SET rev_id = :new_rev_id, version = version + 1, updated_at = now()
                WHERE doc_id = :doc_id AND version = :expected_version
                RETURNING version
                """),
                {
                    "new_rev_id": new_rev.rev_id,
                    "doc_id": doc_id,
                    "expected_version": active_version
                }
            )
            
            updated = result.fetchone()
            if not updated:
                raise IntegrityError("version_mismatch", None, None)
            
            new_version = updated[0]
            
            self.db.commit()
            
            state["apply_result"] = ApplyResult(
                new_rev_id=str(new_rev.rev_id),
                new_rev_no=new_rev_no,
                new_version=new_version,
                op_ids=[]  # 简化：不返回 op_ids
            )
            
            return state
            
        except IntegrityError as e:
            self.db.rollback()
            state["error"] = ErrorInfo(code="concurrent_edit", message="文档已被他人修改")
            state["retry_count"] = state.get("retry_count", 0) + 1
            return state
            
        except Exception as e:
            self.db.rollback()
            state["error"] = ErrorInfo(code="apply_failed", message=str(e))
            return state
    
    def _validate_operation(self, blocks: List[db_models.BlockVersion], op):
        """验证操作"""
        # 查找目标块
        target_block = None
        for block in blocks:
            if str(block.block_id) == op.target_block_id:
                target_block = block
                break
        
        if not target_block:
            raise ValueError(f"target_block_not_found: {op.target_block_id}")
        
        # 验证 evidence_quote（简化版）
        if op.evidence.text not in target_block.plain_text:
            raise ValueError(f"evidence_quote_not_matched: {op.evidence.text}")
    
    def _apply_operations(
        self,
        current_blocks: List[db_models.BlockVersion],
        operations,
        doc_id: uuid.UUID
    ) -> Tuple[List[db_models.BlockVersion], Set[uuid.UUID]]:
        """应用操作"""
        new_blocks = []
        changed_block_ids = set()
        op_map = {op.target_block_id: op for op in operations}
        
        for block in current_blocks:
            op = op_map.get(str(block.block_id))
            
            if op:
                changed_block_ids.add(block.block_id)
                
                if op.op_type == "replace":
                    new_block = db_models.BlockVersion(
                        block_version_id=uuid.uuid4(),
                        block_id=block.block_id,
                        rev_id=None,  # 稍后设置
                        order_index=0,  # 临时值
                        block_type=block.block_type,
                        heading_level=block.heading_level,
                        parent_heading_block_id=block.parent_heading_block_id,
                        content_md=op.new_content_md,
                        plain_text=strip_markdown(op.new_content_md),
                        content_hash=hash_content(op.new_content_md),
                        parent_version_id=None
                    )
                    new_blocks.append(new_block)
                
                elif op.op_type == "delete":
                    # 标记软删除
                    from sqlalchemy import text
                    self.db.execute(
                        text("""
                        UPDATE blocks
                        SET deleted_at = now()
                        WHERE block_id = :block_id
                        """),
                        {"block_id": block.block_id}
                    )
                    # 不添加到 new_blocks
                    continue
                
                elif op.op_type == "insert_after":
                    # 先添加原块
                    new_blocks.append(self._copy_block(block))
                    # 创建新块
                    new_block = self._create_new_block(op, doc_id, block)
                    new_blocks.append(new_block)
                    changed_block_ids.add(new_block.block_id)
                
                elif op.op_type == "insert_before":
                    # 先添加新块
                    new_block = self._create_new_block(op, doc_id, block)
                    new_blocks.append(new_block)
                    changed_block_ids.add(new_block.block_id)
                    # 再添加原块
                    new_blocks.append(self._copy_block(block))
            else:
                # 无操作：复制
                new_blocks.append(self._copy_block(block))
        
        # 重排 order_index
        for i, block in enumerate(new_blocks):
            block.order_index = i * 10
        
        return new_blocks, changed_block_ids
    
    def _copy_block(self, block: db_models.BlockVersion) -> db_models.BlockVersion:
        """复制块"""
        return db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=block.block_id,
            rev_id=None,
            order_index=0,
            block_type=block.block_type,
            heading_level=block.heading_level,
            parent_heading_block_id=block.parent_heading_block_id,
            content_md=block.content_md,
            plain_text=block.plain_text,
            content_hash=block.content_hash,
            parent_version_id=None
        )
    
    def _create_new_block(self, op, doc_id: uuid.UUID, context_block: db_models.BlockVersion) -> db_models.BlockVersion:
        """创建新块"""
        new_block_id = uuid.uuid4()
        
        # 创建 blocks 记录
        block = db_models.Block(
            block_id=new_block_id,
            doc_id=doc_id,
            first_rev_id=None  # 稍后设置
        )
        self.db.add(block)
        self.db.flush()
        
        return db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=new_block_id,
            rev_id=None,
            order_index=0,
            block_type="paragraph",
            heading_level=None,
            parent_heading_block_id=context_block.parent_heading_block_id,
            content_md=op.new_content_md,
            plain_text=strip_markdown(op.new_content_md),
            content_hash=hash_content(op.new_content_md),
            parent_version_id=None
        )
    
    def _get_next_rev_no(self, doc_id: uuid.UUID) -> int:
        """获取下一个版本号"""
        result = self.db.query(db_models.DocumentRevision).filter(
            db_models.DocumentRevision.doc_id == doc_id
        ).order_by(db_models.DocumentRevision.rev_no.desc()).first()
        
        return (result.rev_no + 1) if result else 1
    
    def _generate_summary(self, operations) -> str:
        """生成变更摘要"""
        op_counts = {}
        for op in operations:
            op_counts[op.op_type] = op_counts.get(op.op_type, 0) + 1
        
        parts = []
        if op_counts.get("replace"):
            parts.append(f"修改了 {op_counts['replace']} 处")
        if op_counts.get("delete"):
            parts.append(f"删除了 {op_counts['delete']} 处")
        if op_counts.get("insert_after") or op_counts.get("insert_before"):
            total = op_counts.get("insert_after", 0) + op_counts.get("insert_before", 0)
            parts.append(f"插入了 {total} 处")
        
        return "、".join(parts) if parts else "修改了内容"
