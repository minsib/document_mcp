from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import uuid
from typing import Optional

from app.config import get_settings
from app.db.connection import get_db, engine
from app.models.database import Base
from app.models.schemas import (
    UploadDocumentResponse, ChatEditRequest, ChatEditResponse,
    ConfirmRequest, ConfirmResponse
)
from app.services.splitter import BlockSplitter
from app.models import database as db_models

settings = get_settings()

# 创建数据库表
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AI-powered document editing system"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/v1/docs/upload", response_model=UploadDocumentResponse)
async def upload_document(
    title: str = Form(...),
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """上传文档"""
    # 模拟用户 ID（实际应该从认证中获取）
    user_id = uuid.uuid4()
    
    # 获取文档内容
    if file:
        markdown = (await file.read()).decode('utf-8')
        source_filename = file.filename
        source_format = file.filename.split('.')[-1] if '.' in file.filename else 'txt'
    elif content:
        markdown = content
        source_filename = f"{title}.md"
        source_format = "md"
    else:
        raise HTTPException(400, "Either file or content must be provided")
    
    # 分块
    splitter = BlockSplitter()
    blocks = splitter.split_document(markdown)
    
    # 创建文档
    doc = db_models.Document(
        doc_id=uuid.uuid4(),
        user_id=user_id,
        title=title,
        source_filename=source_filename,
        source_format=source_format,
        total_blocks=len(blocks),
        total_chars=sum(len(b.content_md) for b in blocks)
    )
    db.add(doc)
    db.flush()  # 确保 doc_id 可用
    
    # 创建首个 revision
    rev = db_models.DocumentRevision(
        rev_id=uuid.uuid4(),
        doc_id=doc.doc_id,
        rev_no=1,
        created_by="user"
    )
    db.add(rev)
    db.flush()  # 确保 rev_id 可用
    
    # 创建 blocks 和 block_versions
    for block_data in blocks:
        block = db_models.Block(
            block_id=block_data.block_id,
            doc_id=doc.doc_id,
            first_rev_id=rev.rev_id
        )
        db.add(block)
        
        block_version = db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=block_data.block_id,
            rev_id=rev.rev_id,
            order_index=block_data.order_index,
            block_type=block_data.block_type,
            heading_level=block_data.heading_level,
            parent_heading_block_id=block_data.parent_heading_block_id,
            content_md=block_data.content_md,
            plain_text=block_data.plain_text,
            content_hash=block_data.content_hash
        )
        db.add(block_version)
    
    # 设置 active_revision
    active_rev = db_models.DocumentActiveRevision(
        doc_id=doc.doc_id,
        rev_id=rev.rev_id,
        version=1
    )
    db.add(active_rev)
    
    db.commit()
    
    return UploadDocumentResponse(
        doc_id=str(doc.doc_id),
        rev_id=str(rev.rev_id),
        block_count=len(blocks),
        title=title
    )


@app.get("/v1/docs/{doc_id}/export")
async def export_document(
    doc_id: str,
    rev_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """导出文档"""
    doc_uuid = uuid.UUID(doc_id)
    
    # 获取 revision
    if not rev_id:
        active_rev = db.query(db_models.DocumentActiveRevision).filter(
            db_models.DocumentActiveRevision.doc_id == doc_uuid
        ).first()
        if not active_rev:
            raise HTTPException(404, "Document not found")
        rev_uuid = active_rev.rev_id
    else:
        rev_uuid = uuid.UUID(rev_id)
    
    # 获取所有 blocks
    blocks = db.query(db_models.BlockVersion).filter(
        db_models.BlockVersion.rev_id == rev_uuid
    ).order_by(db_models.BlockVersion.order_index).all()
    
    if not blocks:
        raise HTTPException(404, "No blocks found")
    
    # 拼接 Markdown
    markdown_parts = [block.content_md for block in blocks]
    markdown = '\n\n'.join(markdown_parts)
    
    return {
        "doc_id": doc_id,
        "rev_id": str(rev_uuid),
        "content": markdown
    }


@app.post("/v1/chat/edit", response_model=ChatEditResponse)
async def chat_edit(
    request: ChatEditRequest,
    db: Session = Depends(get_db)
):
    """对话式编辑（简化版 MVP）"""
    return ChatEditResponse(
        status="failed",
        message="Chat edit功能正在开发中，请使用简单的文本替换功能"
    )


@app.post("/v1/chat/confirm", response_model=ConfirmResponse)
async def confirm_edit(
    request: ConfirmRequest,
    db: Session = Depends(get_db)
):
    """确认编辑"""
    return ConfirmResponse(
        status="failed",
        message="Confirm功能正在开发中"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
