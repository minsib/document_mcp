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
    
    # 索引到 Meilisearch
    try:
        from app.services.search_indexer import get_indexer
        indexer = get_indexer()
        indexer.index_document_blocks(str(doc.doc_id), str(rev.rev_id), db)
    except Exception as e:
        print(f"索引失败（不影响上传）: {e}")
    
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
    """对话式编辑"""
    from app.services.workflow import EditWorkflow
    
    # 模拟用户 ID（实际应该从认证中获取）
    user_id = str(uuid.uuid4())
    
    # 创建或获取 session
    session_id = request.session_id or str(uuid.uuid4())
    
    # 执行工作流
    workflow = EditWorkflow(db)
    result = workflow.execute(
        doc_id=request.doc_id,
        session_id=session_id,
        user_id=user_id,
        user_message=request.message,
        user_selection=request.user_selection
    )
    
    return result


@app.post("/v1/chat/confirm", response_model=ConfirmResponse)
async def confirm_edit(
    request: ConfirmRequest,
    db: Session = Depends(get_db)
):
    """确认编辑"""
    import hashlib
    from app.models.schemas import EditPlan
    from app.nodes.apply import ApplyEditsNode
    from app.services.cache import get_cache_manager
    
    # 模拟用户 ID
    user_id = str(uuid.uuid4())
    
    # 获取 cache manager
    cache = get_cache_manager()
    
    # 1. 获取 token payload
    payload = cache.get_confirm_token(request.session_id, request.confirm_token)
    
    if not payload:
        return ConfirmResponse(
            status="failed",
            message="Token 无效或已过期",
            error={"code": "invalid_token", "message": "Token 无效或已过期"}
        )
    
    # 2. 基础校验
    if payload["doc_id"] != request.doc_id:
        return ConfirmResponse(
            status="failed",
            message="Token doc_id 不匹配",
            error={"code": "token_mismatch", "message": "Token doc_id 不匹配"}
        )
    
    if payload["session_id"] != request.session_id:
        return ConfirmResponse(
            status="failed",
            message="Token session_id 不匹配",
            error={"code": "token_mismatch", "message": "Token session_id 不匹配"}
        )
    
    # 3. 过期校验
    import time
    if time.time() > payload["expires_at"]:
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="Token 已过期",
            error={"code": "token_expired", "message": "Token 已过期"}
        )
    
    # 4. 获取当前 active_revision
    doc_uuid = uuid.UUID(request.doc_id)
    active_rev = db.query(db_models.DocumentActiveRevision).filter(
        db_models.DocumentActiveRevision.doc_id == doc_uuid
    ).first()
    
    if not active_rev:
        return ConfirmResponse(
            status="failed",
            message="文档不存在",
            error={"code": "doc_not_found", "message": "文档不存在"}
        )
    
    # 5. 版本校验
    if payload["active_rev_id"] != str(active_rev.rev_id):
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="文档已被他人修改，预览已失效",
            error={
                "code": "document_modified",
                "message": "文档已被他人修改，预览已失效",
                "current_rev_id": str(active_rev.rev_id),
                "token_rev_id": payload["active_rev_id"]
            }
        )
    
    if payload["active_version"] != active_rev.version:
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="文档版本已变更，预览已失效",
            error={
                "code": "version_mismatch",
                "message": "文档版本已变更，预览已失效",
                "current_version": active_rev.version,
                "token_version": payload["active_version"]
            }
        )
    
    # 6. 取消操作
    if request.action == "cancel":
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="cancelled",
            message="已取消修改"
        )
    
    # 7. preview_hash 校验
    if not request.preview_hash:
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="缺少 preview_hash",
            error={"code": "missing_preview_hash", "message": "缺少 preview_hash"}
        )
    
    if request.preview_hash != payload.get("preview_hash"):
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="预览内容已变更，请重新确认",
            error={"code": "preview_hash_mismatch", "message": "预览内容已变更"}
        )
    
    # 8. plan_hash 校验
    edit_plan = EditPlan(**payload["edit_plan"])
    plan_json = json.dumps(edit_plan.model_dump(), sort_keys=True)
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()
    
    if plan_hash != payload.get("plan_hash"):
        cache.delete_confirm_token(request.session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            message="编辑计划已被篡改",
            error={"code": "plan_hash_mismatch", "message": "编辑计划已被篡改"}
        )
    
    # 9. 执行修改
    state = {
        "doc_id": request.doc_id,
        "session_id": request.session_id,
        "user_id": user_id,
        "active_rev_id": str(active_rev.rev_id),
        "active_version": active_rev.version,
        "edit_plan": edit_plan,
        "retry_count": 0,
        "max_retries": 2
    }
    
    apply_node = ApplyEditsNode(db)
    result = apply_node(state)
    
    # 10. 删除 token（一次性使用）
    cache.delete_confirm_token(request.session_id, request.confirm_token)
    
    if result.get("apply_result"):
        # 导出文档
        from app.services.workflow import EditWorkflow
        workflow = EditWorkflow(db, cache)
        export_md = workflow._export_document(result["apply_result"].new_rev_id)
        
        return ConfirmResponse(
            status="applied",
            new_rev_id=result["apply_result"].new_rev_id,
            export_md=export_md,
            message="修改已应用"
        )
    else:
        error = result.get("error", {})
        if hasattr(error, 'model_dump'):
            error = error.model_dump()
        
        return ConfirmResponse(
            status="failed",
            message=error.get("message", "应用修改失败"),
            error=error
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.get("/v1/docs/{doc_id}/revisions")
async def list_revisions(
    doc_id: str,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """列出文档版本"""
    from app.models.schemas import RevisionResponse, ListRevisionsResponse
    
    doc_uuid = uuid.UUID(doc_id)
    
    # 获取 active_revision
    active_rev = db.query(db_models.DocumentActiveRevision).filter(
        db_models.DocumentActiveRevision.doc_id == doc_uuid
    ).first()
    
    # 获取版本列表
    revisions = db.query(db_models.DocumentRevision).filter(
        db_models.DocumentRevision.doc_id == doc_uuid
    ).order_by(
        db_models.DocumentRevision.rev_no.desc()
    ).limit(limit).offset(offset).all()
    
    # 统计总数
    total = db.query(db_models.DocumentRevision).filter(
        db_models.DocumentRevision.doc_id == doc_uuid
    ).count()
    
    return ListRevisionsResponse(
        revisions=[
            RevisionResponse(
                rev_id=str(rev.rev_id),
                rev_no=rev.rev_no,
                created_by=rev.created_by,
                created_at=rev.created_at,
                change_summary=rev.change_summary,
                is_active=(active_rev and rev.rev_id == active_rev.rev_id)
            )
            for rev in revisions
        ],
        total=total
    )


@app.post("/v1/docs/{doc_id}/rollback")
async def rollback_revision(
    doc_id: str,
    request: dict,
    db: Session = Depends(get_db)
):
    """回滚到指定版本"""
    from app.models.schemas import RollbackResponse
    
    doc_uuid = uuid.UUID(doc_id)
    target_rev_id = uuid.UUID(request["target_rev_id"])
    
    # 获取目标 revision 的所有 blocks
    target_blocks = db.query(db_models.BlockVersion).filter(
        db_models.BlockVersion.rev_id == target_rev_id
    ).order_by(db_models.BlockVersion.order_index).all()
    
    if not target_blocks:
        raise HTTPException(404, "目标版本不存在")
    
    # 获取当前最大版本号
    current_rev = db.query(db_models.DocumentRevision).filter(
        db_models.DocumentRevision.doc_id == doc_uuid
    ).order_by(db_models.DocumentRevision.rev_no.desc()).first()
    
    new_rev_no = current_rev.rev_no + 1 if current_rev else 1
    
    # 创建新 revision
    new_rev = db_models.DocumentRevision(
        rev_id=uuid.uuid4(),
        doc_id=doc_uuid,
        rev_no=new_rev_no,
        parent_rev_id=target_rev_id,
        created_by="system",
        change_summary=f"回滚到版本 {request.get('target_rev_no', '?')}"
    )
    db.add(new_rev)
    db.flush()
    
    # 复制 blocks
    for block in target_blocks:
        new_block_version = db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=block.block_id,
            rev_id=new_rev.rev_id,
            order_index=block.order_index,
            block_type=block.block_type,
            heading_level=block.heading_level,
            parent_heading_block_id=block.parent_heading_block_id,
            content_md=block.content_md,
            plain_text=block.plain_text,
            content_hash=block.content_hash,
            parent_version_id=None
        )
        db.add(new_block_version)
    
    # 更新 active_rev
    from sqlalchemy import text
    db.execute(
        text("""
        UPDATE document_active_revision
        SET rev_id = :new_rev_id, version = version + 1, updated_at = now()
        WHERE doc_id = :doc_id
        """),
        {"new_rev_id": new_rev.rev_id, "doc_id": doc_uuid}
    )
    
    db.commit()
    
    return RollbackResponse(
        new_rev_id=str(new_rev.rev_id),
        new_rev_no=new_rev_no,
        message=f"已回滚到版本 {request.get('target_rev_no', '?')}"
    )
