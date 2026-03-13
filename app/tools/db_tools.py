"""
数据库工具 - 封装所有数据库操作
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
from sqlalchemy.orm import Session

from app.tools.base import BaseTool
from app.models import database as db_models


# ============ Input Schemas ============

class GetDocumentInput(BaseModel):
    doc_id: str = Field(description="文档 ID (UUID)")


class GetRevisionInput(BaseModel):
    rev_id: str = Field(description="版本 ID (UUID)")


class GetBlocksInput(BaseModel):
    rev_id: str = Field(description="版本 ID (UUID)")
    block_ids: Optional[List[str]] = Field(default=None, description="块 ID 列表，为空则返回所有块")


class GetBlockContextInput(BaseModel):
    block_id: str = Field(description="块 ID (UUID)")
    rev_id: str = Field(description="版本 ID (UUID)")
    window: int = Field(default=2, description="上下文窗口大小（前后各几个块）")


class CreateRevisionInput(BaseModel):
    doc_id: str = Field(description="文档 ID (UUID)")
    parent_rev_id: str = Field(description="父版本 ID (UUID)")
    user_id: str = Field(description="用户 ID (UUID)")
    change_summary: str = Field(description="修改摘要")


class UpdateBlockInput(BaseModel):
    block_id: str = Field(description="块 ID (UUID)")
    rev_id: str = Field(description="新版本 ID (UUID)")
    content_md: str = Field(description="新的 Markdown 内容")
    plain_text: str = Field(description="新的纯文本内容")


# ============ Tools ============

class GetDocumentTool(BaseTool):
    name: str = "get_document"
    description: str = "获取文档信息，包括文档 ID、标题、创建时间等"
    args_schema: type[BaseModel] = GetDocumentInput
    
    def _run(self, doc_id: str) -> Dict[str, Any]:
        """获取文档信息"""
        doc_uuid = uuid.UUID(doc_id)
        doc = self.db.query(db_models.Document).filter(
            db_models.Document.doc_id == doc_uuid
        ).first()
        
        if not doc:
            return {"error": "Document not found", "doc_id": doc_id}
        
        return {
            "doc_id": str(doc.doc_id),
            "title": doc.title,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            "user_id": str(doc.user_id)
        }


class GetRevisionTool(BaseTool):
    name: str = "get_revision"
    description: str = "获取文档版本信息，包括版本号、创建时间、修改摘要等"
    args_schema: type[BaseModel] = GetRevisionInput
    
    def _run(self, rev_id: str) -> Dict[str, Any]:
        """获取版本信息"""
        rev_uuid = uuid.UUID(rev_id)
        rev = self.db.query(db_models.DocumentRevision).filter(
            db_models.DocumentRevision.rev_id == rev_uuid
        ).first()
        
        if not rev:
            return {"error": "Revision not found", "rev_id": rev_id}
        
        return {
            "rev_id": str(rev.rev_id),
            "doc_id": str(rev.doc_id),
            "rev_no": rev.rev_no,
            "created_at": rev.created_at.isoformat() if rev.created_at else None,
            "change_summary": rev.change_summary,
            "parent_rev_id": str(rev.parent_rev_id) if rev.parent_rev_id else None
        }


class GetBlocksTool(BaseTool):
    name: str = "get_blocks"
    description: str = "获取指定版本的块列表，可以指定块 ID 列表或获取所有块"
    args_schema: type[BaseModel] = GetBlocksInput
    
    def _run(self, rev_id: str, block_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """获取块列表"""
        rev_uuid = uuid.UUID(rev_id)
        
        query = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid
        )
        
        if block_ids:
            block_uuids = [uuid.UUID(bid) for bid in block_ids]
            query = query.filter(db_models.BlockVersion.block_id.in_(block_uuids))
        
        blocks = query.order_by(db_models.BlockVersion.order_index).all()
        
        return [
            {
                "block_id": str(block.block_id),
                "block_version_id": str(block.block_version_id),
                "block_type": block.block_type,
                "content_md": block.content_md,
                "plain_text": block.plain_text,
                "order_index": block.order_index,
                "heading_level": block.heading_level
            }
            for block in blocks
        ]


class GetBlockContextTool(BaseTool):
    name: str = "get_block_context"
    description: str = "获取块的上下文信息（前后各 N 个块）"
    args_schema: type[BaseModel] = GetBlockContextInput
    
    def _run(self, block_id: str, rev_id: str, window: int = 2) -> Dict[str, Any]:
        """获取块上下文"""
        block_uuid = uuid.UUID(block_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取目标块
        target_block = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block_uuid,
            db_models.BlockVersion.rev_id == rev_uuid
        ).first()
        
        if not target_block:
            return {"error": "Block not found"}
        
        # 获取前后的块
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid,
            db_models.BlockVersion.order_index >= target_block.order_index - (window * 10),
            db_models.BlockVersion.order_index <= target_block.order_index + (window * 10)
        ).order_by(db_models.BlockVersion.order_index).all()
        
        before_blocks = []
        after_blocks = []
        
        for block in blocks:
            if block.order_index < target_block.order_index:
                before_blocks.append({
                    "block_id": str(block.block_id),
                    "content": block.plain_text,
                    "order_index": block.order_index
                })
            elif block.order_index > target_block.order_index:
                after_blocks.append({
                    "block_id": str(block.block_id),
                    "content": block.plain_text,
                    "order_index": block.order_index
                })
        
        # 获取父级标题
        parent_heading = None
        if target_block.parent_heading_block_id:
            parent_block = self.db.query(db_models.BlockVersion).filter(
                db_models.BlockVersion.block_id == target_block.parent_heading_block_id,
                db_models.BlockVersion.rev_id == rev_uuid
            ).first()
            if parent_block:
                parent_heading = parent_block.plain_text
        
        return {
            "before": before_blocks[-window:] if before_blocks else [],
            "after": after_blocks[:window] if after_blocks else [],
            "parent_heading": parent_heading or "（无标题）"
        }


class CreateRevisionTool(BaseTool):
    name: str = "create_revision"
    description: str = "创建新的文档版本"
    args_schema: type[BaseModel] = CreateRevisionInput
    
    def _run(
        self,
        doc_id: str,
        parent_rev_id: str,
        user_id: str,
        change_summary: str
    ) -> Dict[str, Any]:
        """创建新版本"""
        doc_uuid = uuid.UUID(doc_id)
        parent_uuid = uuid.UUID(parent_rev_id)
        
        # 获取父版本号
        parent_rev = self.db.query(db_models.DocumentRevision).filter(
            db_models.DocumentRevision.rev_id == parent_uuid
        ).first()
        
        if not parent_rev:
            return {"error": "Parent revision not found"}
        
        # 创建新版本
        new_rev = db_models.DocumentRevision(
            rev_id=uuid.uuid4(),
            doc_id=doc_uuid,
            rev_no=parent_rev.rev_no + 1,
            parent_rev_id=parent_uuid,
            change_summary=change_summary,
            created_by=user_id  # 已经是字符串格式
        )
        
        self.db.add(new_rev)
        self.db.flush()
        
        return {
            "rev_id": str(new_rev.id),
            "version": new_rev.version,
            "doc_id": str(new_rev.doc_id)
        }


class UpdateBlockTool(BaseTool):
    name: str = "update_block"
    description: str = "更新块内容（创建新的块版本）"
    args_schema: type[BaseModel] = UpdateBlockInput
    
    def _run(
        self,
        block_id: str,
        rev_id: str,
        content_md: str,
        plain_text: str
    ) -> Dict[str, Any]:
        """更新块内容"""
        from app.utils.markdown import hash_content
        
        block_uuid = uuid.UUID(block_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取原块信息
        old_block = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block_uuid
        ).order_by(db_models.BlockVersion.created_at.desc()).first()
        
        if not old_block:
            return {"error": "Block not found"}
        
        # 创建新的块版本
        new_block = db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=block_uuid,
            rev_id=rev_uuid,
            block_type=old_block.block_type,
            heading_level=old_block.heading_level,
            content_md=content_md,
            plain_text=plain_text,
            content_hash=hash_content(content_md),
            order_index=old_block.order_index,
            parent_heading_block_id=old_block.parent_heading_block_id
        )
        
        self.db.add(new_block)
        self.db.flush()
        
        return {
            "block_version_id": str(new_block.block_version_id),
            "block_id": str(new_block.block_id),
            "rev_id": str(new_block.rev_id)
        }
