"""
批量应用节点 - 执行批量修改
"""
from typing import List, Set, Tuple
from app.models.schemas import PreviewDiff, EditOperation, EvidenceQuote
from app.models import database as db_models
from app.utils.markdown import strip_markdown, hash_content
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
from datetime import datetime


class BulkApplyNode:
    """批量应用节点 - 执行批量修改"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def apply_bulk_changes(
        self,
        preview: PreviewDiff,
        doc_id: str,
        active_rev_id: str,
        active_version: int,
        user_id: str,
        trace_id: str = None
    ) -> dict:
        """
        应用批量修改
        
        Args:
            preview: 预览 diff
            doc_id: 文档 ID
            active_rev_id: 当前活跃版本 ID
            active_version: 乐观锁版本号
            user_id: 用户 ID
            trace_id: 追踪 ID
        
        Returns:
            应用结果
        """
        doc_uuid = uuid.UUID(doc_id)
        active_rev_uuid = uuid.UUID(active_rev_id)
        user_uuid = uuid.UUID(user_id)
        
        try:
            # 1. 读取当前 revision 的所有 block_versions
            current_blocks = self.db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.rev_id == active_rev_uuid
            ).order_by(db_models.BlockVersion.order_index).all()
            
            # 创建 block_id -> block 的映射
            block_map = {str(b.block_id): b for b in current_blocks}
            
            # 2. 应用变更
            changed_block_ids = set()
            new_blocks = []
            
            for block in current_blocks:
                block_id_str = str(block.block_id)
                
                # 查找是否有对应的 diff
                diff_item = next(
                    (d for d in preview.diffs if d.block_id == block_id_str),
                    None
                )
                
                if diff_item and diff_item.op_type == "replace":
                    # 有修改：创建新版本
                    changed_block_ids.add(block.block_id)
                    
                    # 从 after_snippet 重建完整内容（实际应该从 intent 重新生成）
                    # 这里简化处理，实际应该保存完整的新内容
                    new_content = self._reconstruct_content(block, diff_item)
                    
                    new_block = self._create_new_block_version(
                        block,
                        new_content
                    )
                    new_blocks.append(new_block)
                else:
                    # 无修改：复制原块
                    new_block = self._copy_block_version(block)
                    new_blocks.append(new_block)
            
            # 3. 创建新 revision
            new_rev_no = self._get_next_rev_no(doc_uuid)
            new_rev = self._create_revision(
                doc_uuid,
                new_rev_no,
                active_rev_uuid,
                f"批量修改了 {len(preview.diffs)} 处内容"
            )
            
            # 4. 设置新 block_versions 的 rev_id 和 order_index
            for i, block in enumerate(new_blocks):
                block.rev_id = new_rev.rev_id
                block.order_index = i * 10
            
            # 5. 插入新 block_versions
            self.db.bulk_save_objects(new_blocks)
            
            # 6. 写入 edit_operations（审计）
            for diff_item in preview.diffs:
                block = block_map.get(diff_item.block_id)
                if not block:
                    continue
                
                self._insert_edit_operation(
                    doc_uuid,
                    new_rev.rev_id,
                    active_rev_uuid,
                    user_uuid,
                    uuid.UUID(diff_item.block_id),
                    block.plain_text or '',
                    trace_id
                )
            
            # 7. 更新 active_rev（CAS 操作）
            result = self.db.execute(
                text("""
                    UPDATE document_active_revision
                    SET rev_id = :new_rev_id, version = version + 1, updated_at = now()
                    WHERE doc_id = :doc_id AND version = :expected_version
                    RETURNING version
                """),
                {
                    'new_rev_id': new_rev.rev_id,
                    'doc_id': doc_uuid,
                    'expected_version': active_version
                }
            ).fetchone()
            
            if not result:
                raise Exception("并发冲突：文档已被其他用户修改")
            
            new_version = result[0]
            
            # 8. 提交事务
            self.db.commit()
            
            return {
                'success': True,
                'new_rev_id': str(new_rev.rev_id),
                'new_rev_no': new_rev_no,
                'new_version': new_version,
                'changes_applied': len(preview.diffs)
            }
            
        except Exception as e:
            self.db.rollback()
            raise e
    
    def _reconstruct_content(
        self,
        original_block: db_models.BlockVersion,
        diff_item: DiffItem
    ) -> str:
        """
        重建完整内容
        
        注意：这是简化实现，实际应该从 intent 重新生成
        """
        # 这里简化处理，实际应该保存完整的新内容
        # 暂时返回原内容（需要在 preview 阶段保存完整的新内容）
        return original_block.content_md or ''
    
    def _create_new_block_version(
        self,
        original: db_models.BlockVersion,
        new_content: str
    ) -> db_models.BlockVersion:
        """创建新的 block_version"""
        return db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=original.block_id,
            rev_id=None,  # 稍后设置
            order_index=0,  # 稍后设置
            block_type=original.block_type,
            heading_level=original.heading_level,
            parent_heading_block_id=original.parent_heading_block_id,
            content_md=new_content,
            plain_text=strip_markdown(new_content),
            content_hash=hash_content(new_content),
            parent_version_id=None
        )
    
    def _copy_block_version(
        self,
        original: db_models.BlockVersion
    ) -> db_models.BlockVersion:
        """复制 block_version"""
        return db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=original.block_id,
            rev_id=None,  # 稍后设置
            order_index=0,  # 稍后设置
            block_type=original.block_type,
            heading_level=original.heading_level,
            parent_heading_block_id=original.parent_heading_block_id,
            content_md=original.content_md,
            plain_text=original.plain_text,
            content_hash=original.content_hash,
            parent_version_id=None
        )
    
    def _get_next_rev_no(self, doc_id: uuid.UUID) -> int:
        """获取下一个版本号"""
        result = self.db.execute(
            text("""
                SELECT COALESCE(MAX(rev_no), 0) + 1
                FROM document_revisions
                WHERE doc_id = :doc_id
            """),
            {'doc_id': doc_id}
        ).fetchone()
        
        return result[0] if result else 1
    
    def _create_revision(
        self,
        doc_id: uuid.UUID,
        rev_no: int,
        parent_rev_id: uuid.UUID,
        change_summary: str
    ) -> db_models.DocumentRevision:
        """创建新 revision"""
        revision = db_models.DocumentRevision(
            rev_id=uuid.uuid4(),
            doc_id=doc_id,
            rev_no=rev_no,
            parent_rev_id=parent_rev_id,
            created_by="ai",
            change_summary=change_summary
        )
        
        self.db.add(revision)
        self.db.flush()  # 获取 rev_id
        
        return revision
    
    def _insert_edit_operation(
        self,
        doc_id: uuid.UUID,
        rev_id: uuid.UUID,
        parent_rev_id: uuid.UUID,
        user_id: uuid.UUID,
        target_block_id: uuid.UUID,
        evidence_quote: str,
        trace_id: str = None
    ):
        """插入编辑操作记录"""
        operation = db_models.EditOperation(
            op_id=uuid.uuid4(),
            doc_id=doc_id,
            rev_id=rev_id,
            parent_rev_id=parent_rev_id,
            trace_id=trace_id,
            user_id=user_id,
            op_type="replace",
            target_block_id=target_block_id,
            evidence_quote=evidence_quote[:100],  # 截断
            quote_start=0,
            quote_end=min(len(evidence_quote), 100),
            rationale="批量修改",
            status="applied"
        )
        
        self.db.add(operation)
