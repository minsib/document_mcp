from fastapi import FastAPI, Depends, HTTPException, status, Security, Form, File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from prometheus_client import make_asgi_app
import uuid
from typing import Any, Dict, Optional
import logging
import json

from app.config import get_settings
from app.db.connection import get_db, engine
from app.db.schema_sync import ensure_memory_schema
from app.models.database import Base
from app.auth.models import User as AuthUser, APIKey
from app.models.schemas import (
    UploadDocumentResponse, ChatEditRequest, ChatEditResponse,
    ConfirmRequest, ConfirmResponse, ChatSessionDetailResponse,
    ChatMessageResponse, UserPreferenceResponse, UserPreferenceUpsertRequest,
    UserMemoryItemResponse
)
from app.services.splitter import BlockSplitter
from app.models import database as db_models
from app.auth.dependencies import get_current_active_user, get_optional_user
from app.auth.router import router as auth_router
from app.monitoring.health import router as health_router
from app.monitoring.middleware import MetricsMiddleware, LoggingMiddleware
from app.monitoring.metrics import app_info
from app.services.chat_sessions import (
    append_chat_message,
    ensure_chat_session,
    normalize_session_id,
)
from app.services.memory import MemoryService
from app.services.memory_scheduler import MemoryMaintenanceScheduler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()

# 创建数据库表
Base.metadata.create_all(bind=engine)
ensure_memory_schema(engine)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AI-powered document editing system with authentication and monitoring"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加监控中间件
app.add_middleware(MetricsMiddleware)
app.add_middleware(LoggingMiddleware)

# 注册路由
app.include_router(auth_router)
app.include_router(health_router)

# 导入并注册协同编辑路由
from app.api.collaboration import router as collab_router
app.include_router(collab_router, tags=["collaboration"])

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# 设置应用信息
app_info.info({
    'version': '1.0.0',
    'environment': settings.APP_ENV
})

memory_scheduler = MemoryMaintenanceScheduler()


@app.on_event("startup")
async def startup_memory_scheduler() -> None:
    memory_scheduler.start()


@app.on_event("shutdown")
async def shutdown_memory_scheduler() -> None:
    await memory_scheduler.stop()


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


def _get_owned_document_or_404(db: Session, doc_id: str, user_id: uuid.UUID) -> db_models.Document:
    """Ensure the current user owns the target document."""
    try:
        doc_uuid = uuid.UUID(doc_id)
    except ValueError as exc:
        raise HTTPException(400, "无效的 doc_id") from exc

    document = db.query(db_models.Document).filter(
        db_models.Document.doc_id == doc_uuid,
        db_models.Document.user_id == user_id,
    ).first()
    if not document:
        raise HTTPException(404, "文档不存在或无权限访问")
    return document


def _session_status_from_response(status_value: str) -> str:
    """Map API response statuses to persisted chat session statuses."""
    return {
        "applied": "completed",
        "need_confirm": "awaiting_confirmation",
        "need_disambiguation": "awaiting_disambiguation",
        "need_clarification": "awaiting_clarification",
        "cancelled": "cancelled",
        "failed": "failed",
    }.get(status_value, "active")


def _persist_chat_turn(
    db: Session,
    *,
    session_id: str,
    user_content: str,
    user_meta: Dict[str, Any],
    assistant_content: str,
    assistant_meta: Dict[str, Any],
) -> tuple[db_models.ChatMessage, db_models.ChatMessage]:
    """Persist a single user/assistant turn."""
    user_message = append_chat_message(
        db,
        session_id=session_id,
        role="user",
        content=user_content,
        meta=user_meta,
    )
    assistant_message = append_chat_message(
        db,
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        meta=assistant_meta,
    )
    return user_message, assistant_message


def _ensure_session_or_409(
    db: Session,
    *,
    session_id: str,
    user_id: str,
    doc_id: str,
    status: str,
) -> None:
    """Create or update a chat session, surfacing ownership conflicts as HTTP errors."""
    try:
        ensure_chat_session(
            db,
            session_id=session_id,
            user_id=user_id,
            doc_id=doc_id,
            status=status,
        )
    except ValueError as exc:
        raise HTTPException(409, "session_id 与当前用户或文档不匹配") from exc


@app.post("/v1/docs/upload", response_model=UploadDocumentResponse)
async def upload_document(
    title: str = Form(...),
    file: Optional[UploadFile] = File(None),
    content: Optional[str] = Form(None),
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """上传文档（需要认证）"""
    # 使用当前用户的 ID
    user_id = current_user.user_id
    
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
    
    # 记录指标
    from app.monitoring.metrics import documents_uploaded
    documents_uploaded.labels(user_id=str(user_id)).inc()
    
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
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """对话式编辑"""
    from app.services.workflow import EditWorkflow

    _get_owned_document_or_404(db, request.doc_id, current_user.user_id)
    user_id = str(current_user.user_id)
    session_id = normalize_session_id(
        request.session_id,
        user_id=user_id,
        doc_id=request.doc_id,
    )
    _ensure_session_or_409(
        db,
        session_id=session_id,
        user_id=user_id,
        doc_id=request.doc_id,
        status="active",
    )

    workflow = EditWorkflow(db)
    result = workflow.execute(
        doc_id=request.doc_id,
        session_id=session_id,
        user_id=user_id,
        user_message=request.message,
        user_selection=request.user_selection
    )

    _ensure_session_or_409(
        db,
        session_id=session_id,
        user_id=user_id,
        doc_id=request.doc_id,
        status=_session_status_from_response(result.status),
    )
    user_turn, assistant_turn = _persist_chat_turn(
        db,
        session_id=session_id,
        user_content=request.message,
        user_meta={
            "request_type": "edit",
            "doc_id": request.doc_id,
            "user_selection": request.user_selection,
        },
        assistant_content=result.message,
        assistant_meta={
            "request_type": "edit",
            "doc_id": request.doc_id,
            "status": result.status,
            "operation_type": workflow.last_operation_type,
            "confirm_token": result.confirm_token,
            "preview_hash": result.preview_hash,
            "new_rev_id": result.new_rev_id,
            "clarification": result.clarification,
            "preview": result.preview.model_dump() if result.preview else None,
            "diff_summary": [item.model_dump() for item in result.diff_summary] if result.diff_summary else None,
            "trace": workflow.last_trace,
        },
    )
    db.flush()
    try:
        MemoryService(db).record_turn(
            user_id=user_id,
            doc_id=request.doc_id,
            session_id=session_id,
            user_content=request.message,
            user_meta=user_turn.meta or {},
            assistant_content=result.message,
            assistant_meta=assistant_turn.meta or {},
            source_message_ids=[str(user_turn.msg_id), str(assistant_turn.msg_id)],
        )
    except Exception:
        logger.exception("Failed to record memory for chat_edit")
    db.commit()

    return result


@app.post("/v1/chat/confirm", response_model=ConfirmResponse)
async def confirm_edit(
    request: ConfirmRequest,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """确认编辑"""
    import hashlib
    from app.models.schemas import EditPlan
    from app.nodes.apply import ApplyEditsNode
    from app.services.cache import get_cache_manager
    from app.monitoring.metrics import edits_applied, edits_failed
    
    _get_owned_document_or_404(db, request.doc_id, current_user.user_id)
    user_id = str(current_user.user_id)
    session_id = normalize_session_id(
        request.session_id,
        user_id=user_id,
        doc_id=request.doc_id,
    )
    _ensure_session_or_409(
        db,
        session_id=session_id,
        user_id=user_id,
        doc_id=request.doc_id,
        status="active",
    )
    
    # 获取 cache manager
    cache = get_cache_manager()
    
    # 1. 获取 token payload
    payload = cache.get_confirm_token(session_id, request.confirm_token)
    
    if not payload:
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="Token 无效或已过期",
            error={"code": "invalid_token", "message": "Token 无效或已过期"}
        )
    
    # 2. 基础校验
    if payload["doc_id"] != request.doc_id:
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="Token doc_id 不匹配",
            error={"code": "token_mismatch", "message": "Token doc_id 不匹配"}
        )
    
    if payload["session_id"] != session_id:
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="Token session_id 不匹配",
            error={"code": "token_mismatch", "message": "Token session_id 不匹配"}
        )

    if payload.get("user_id") != user_id:
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="Token user_id 不匹配",
            error={"code": "token_mismatch", "message": "Token user_id 不匹配"},
        )
    
    # 3. 过期校验
    import time
    if time.time() > payload["expires_at"]:
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
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
            session_id=session_id,
            message="文档不存在",
            error={"code": "doc_not_found", "message": "文档不存在"}
        )
    
    # 5. 版本校验
    if payload["active_rev_id"] != str(active_rev.rev_id):
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="文档已被他人修改，预览已失效",
            error={
                "code": "document_modified",
                "message": "文档已被他人修改，预览已失效",
                "current_rev_id": str(active_rev.rev_id),
                "token_rev_id": payload["active_rev_id"]
            }
        )
    
    if payload["active_version"] != active_rev.version:
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
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
        cache.delete_confirm_token(session_id, request.confirm_token)
        response = ConfirmResponse(
            status="cancelled",
            session_id=session_id,
            message="已取消修改"
        )
        _ensure_session_or_409(
            db,
            session_id=session_id,
            user_id=user_id,
            doc_id=request.doc_id,
            status=_session_status_from_response(response.status),
        )
        user_turn, assistant_turn = _persist_chat_turn(
            db,
            session_id=session_id,
            user_content="取消本次修改",
            user_meta={
                "request_type": "confirm",
                "action": request.action,
                "doc_id": request.doc_id,
                "confirm_token": request.confirm_token,
                "preview_hash": request.preview_hash,
            },
            assistant_content=response.message,
            assistant_meta={
                "request_type": "confirm",
                "status": response.status,
                "doc_id": request.doc_id,
                "confirm_token": request.confirm_token,
            },
        )
        db.flush()
        try:
            MemoryService(db).record_turn(
                user_id=user_id,
                doc_id=request.doc_id,
                session_id=session_id,
                user_content="取消本次修改",
                user_meta=user_turn.meta or {},
                assistant_content=response.message,
                assistant_meta=assistant_turn.meta or {},
                source_message_ids=[str(user_turn.msg_id), str(assistant_turn.msg_id)],
            )
        except Exception:
            logger.exception("Failed to record memory for confirm cancel")
        db.commit()
        return response
    
    # 7. preview_hash 校验
    if not request.preview_hash:
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="缺少 preview_hash",
            error={"code": "missing_preview_hash", "message": "缺少 preview_hash"}
        )
    
    if request.preview_hash != payload.get("preview_hash"):
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="预览内容已变更，请重新确认",
            error={"code": "preview_hash_mismatch", "message": "预览内容已变更"}
        )
    
    # 8. plan_hash 校验
    edit_plan = EditPlan(**payload["edit_plan"])
    operation_type = edit_plan.operations[0].op_type if edit_plan.operations else "unknown"
    plan_json = json.dumps(edit_plan.model_dump(), sort_keys=True)
    plan_hash = hashlib.sha256(plan_json.encode()).hexdigest()
    
    if plan_hash != payload.get("plan_hash"):
        cache.delete_confirm_token(session_id, request.confirm_token)
        return ConfirmResponse(
            status="failed",
            session_id=session_id,
            message="编辑计划已被篡改",
            error={"code": "plan_hash_mismatch", "message": "编辑计划已被篡改"}
        )
    
    # 9. 执行修改
    state = {
        "doc_id": request.doc_id,
        "session_id": session_id,
        "user_id": user_id,
        "active_rev_id": str(active_rev.rev_id),
        "active_version": active_rev.version,
        "edit_plan": edit_plan,
        "retry_count": 0,
        "max_retries": 2,
        "_workflow_trace": payload.get("workflow_trace", {}),
    }
    
    apply_node = ApplyEditsNode(db)
    result = apply_node(state)
    
    # 10. 删除 token（一次性使用）
    cache.delete_confirm_token(session_id, request.confirm_token)
    
    if result.get("apply_result"):
        edits_applied.labels(operation_type=operation_type).inc()
        # 导出文档
        from app.services.workflow import EditWorkflow
        workflow = EditWorkflow(db, cache)
        export_md = workflow._export_document(result["apply_result"].new_rev_id)
        response = ConfirmResponse(
            status="applied",
            session_id=session_id,
            new_rev_id=result["apply_result"].new_rev_id,
            export_md=export_md,
            message="修改已应用"
        )
        _ensure_session_or_409(
            db,
            session_id=session_id,
            user_id=user_id,
            doc_id=request.doc_id,
            status=_session_status_from_response(response.status),
        )
        user_turn, assistant_turn = _persist_chat_turn(
            db,
            session_id=session_id,
            user_content="确认应用修改",
            user_meta={
                "request_type": "confirm",
                "action": request.action,
                "doc_id": request.doc_id,
                "confirm_token": request.confirm_token,
                "preview_hash": request.preview_hash,
            },
            assistant_content=response.message,
            assistant_meta={
                "request_type": "confirm",
                "status": response.status,
                "doc_id": request.doc_id,
                "operation_type": operation_type,
                "confirm_token": request.confirm_token,
                "new_rev_id": response.new_rev_id,
                "trace": payload.get("workflow_trace", {}),
            },
        )
        db.flush()
        try:
            MemoryService(db).record_turn(
                user_id=user_id,
                doc_id=request.doc_id,
                session_id=session_id,
                user_content="确认应用修改",
                user_meta=user_turn.meta or {},
                assistant_content=response.message,
                assistant_meta=assistant_turn.meta or {},
                source_message_ids=[str(user_turn.msg_id), str(assistant_turn.msg_id)],
            )
        except Exception:
            logger.exception("Failed to record memory for confirm apply")
        db.commit()
        return response
    else:
        error = result.get("error", {})
        if hasattr(error, 'model_dump'):
            error = error.model_dump()
        edits_failed.labels(
            operation_type=operation_type,
            error_type=error.get("code", "apply_failed")
        ).inc()

        response = ConfirmResponse(
            status="failed",
            session_id=session_id,
            message=error.get("message", "应用修改失败"),
            error=error
        )
        _ensure_session_or_409(
            db,
            session_id=session_id,
            user_id=user_id,
            doc_id=request.doc_id,
            status=_session_status_from_response(response.status),
        )
        user_turn, assistant_turn = _persist_chat_turn(
            db,
            session_id=session_id,
            user_content="确认应用修改",
            user_meta={
                "request_type": "confirm",
                "action": request.action,
                "doc_id": request.doc_id,
                "confirm_token": request.confirm_token,
                "preview_hash": request.preview_hash,
            },
            assistant_content=response.message,
            assistant_meta={
                "request_type": "confirm",
                "status": response.status,
                "doc_id": request.doc_id,
                "operation_type": operation_type,
                "confirm_token": request.confirm_token,
                "error": error,
                "trace": payload.get("workflow_trace", {}),
            },
        )
        db.flush()
        try:
            MemoryService(db).record_turn(
                user_id=user_id,
                doc_id=request.doc_id,
                session_id=session_id,
                user_content="确认应用修改",
                user_meta=user_turn.meta or {},
                assistant_content=response.message,
                assistant_meta=assistant_turn.meta or {},
                source_message_ids=[str(user_turn.msg_id), str(assistant_turn.msg_id)],
            )
        except Exception:
            logger.exception("Failed to record memory for confirm failure")
        db.commit()
        return response


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


@app.post("/v1/chat/bulk-edit")
async def bulk_edit(
    request: dict,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    批量修改接口
    
    请求格式:
    {
        "session_id": "uuid",
        "doc_id": "uuid",
        "message": "将所有'旧词'替换为'新词'",
        "match_type": "exact_term",  // exact_term | regex | semantic
        "scope_filter": {
            "term": "旧词",
            "replacement": "新词",
            "heading": "可选：限制在某个章节"
        }
    }
    """
    from app.nodes.bulk_discover import BulkDiscoverNode
    from app.nodes.bulk_preview import BulkPreviewNode
    from app.models.schemas import Intent, ScopeHint
    
    # 解析请求
    session_id = request.get("session_id")
    doc_id = request.get("doc_id")
    message = request.get("message")
    match_type = request.get("match_type", "exact_term")
    scope_filter = request.get("scope_filter", {})
    
    if not all([doc_id, message]):
        raise HTTPException(400, "缺少必需参数")

    _get_owned_document_or_404(db, doc_id, current_user.user_id)
    session_id = normalize_session_id(
        session_id,
        user_id=str(current_user.user_id),
        doc_id=doc_id,
    )
    
    # 获取当前活跃版本
    doc_uuid = uuid.UUID(doc_id)
    active_rev = db.query(db_models.DocumentActiveRevision).filter(
        db_models.DocumentActiveRevision.doc_id == doc_uuid
    ).first()
    
    if not active_rev:
        raise HTTPException(404, "文档不存在")
    
    # 构建 Intent
    intent = Intent(
        operation="multi_replace",
        scope_hint=ScopeHint(
            heading=scope_filter.get("heading"),
            keywords=[scope_filter.get("term", "")],
            block_type=scope_filter.get("block_type")
        ),
        constraints={},
        risk="medium",
        match_type=match_type,
        apply_scope="all_matches",
        scope_filter=scope_filter
    )
    
    try:
        # 1. 批量发现
        discover_node = BulkDiscoverNode(db)
        candidates = discover_node.discover(
            intent,
            doc_id,
            str(active_rev.rev_id),
            max_changes=100
        )
        
        if not candidates:
            return {
                "status": "no_matches",
                "message": "未找到匹配的内容",
                "candidates": []
            }
        
        # 2. 生成预览
        preview_node = BulkPreviewNode(db)
        preview = preview_node.generate_preview(
            intent,
            candidates,
            str(active_rev.rev_id)
        )
        
        if not preview.diffs:
            return {
                "status": "no_changes",
                "message": "没有需要修改的内容",
                "preview": preview.model_dump()
            }
        
        # 3. 生成 confirm_token
        from app.services.cache import get_cache_manager
        import hashlib
        import json
        import time
        
        cache = get_cache_manager()
        token_id = str(uuid.uuid4())
        
        # 计算 preview_hash
        preview_json = json.dumps(preview.model_dump(), sort_keys=True)
        preview_hash = hashlib.sha256(preview_json.encode()).hexdigest()
        
        payload = {
            "token_id": token_id,
            "session_id": session_id,
            "user_id": str(current_user.user_id),
            "doc_id": doc_id,
            "active_rev_id": str(active_rev.rev_id),
            "active_version": active_rev.version,
            "preview_hash": preview_hash,
            "preview": preview.model_dump(),
            "intent": intent.model_dump(),
            "created_at": time.time(),
            "expires_at": time.time() + 900  # 15 分钟
        }
        
        cache.store_confirm_token(session_id, token_id, payload, ttl=900)
        
        return {
            "status": "need_confirm",
            "message": f"将修改 {preview.total_changes} 处内容，请确认",
            "session_id": session_id,
            "preview": preview.model_dump(),
            "confirm_token": token_id,
            "preview_hash": preview_hash,
            "grouped_by_heading": preview.grouped_by_heading
        }
        
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"批量修改失败: {str(e)}")


@app.post("/v1/chat/bulk-confirm")
async def bulk_confirm(
    request: dict,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    确认批量修改
    
    请求格式:
    {
        "session_id": "uuid",
        "doc_id": "uuid",
        "confirm_token": "uuid",
        "preview_hash": "hash",
        "action": "apply" | "cancel"
    }
    """
    from app.nodes.bulk_apply import BulkApplyNode
    from app.services.cache import get_cache_manager
    from app.models.schemas import PreviewDiff
    import hashlib
    import json
    
    session_id = request.get("session_id")
    doc_id = request.get("doc_id")
    confirm_token = request.get("confirm_token")
    preview_hash = request.get("preview_hash")
    action = request.get("action", "apply")
    
    if not all([session_id, doc_id, confirm_token, preview_hash]):
        raise HTTPException(400, "缺少必需参数")

    _get_owned_document_or_404(db, doc_id, current_user.user_id)
    session_id = normalize_session_id(
        session_id,
        user_id=str(current_user.user_id),
        doc_id=doc_id,
    )
    
    # 获取 token payload
    cache = get_cache_manager()
    payload = cache.get_confirm_token(session_id, confirm_token)
    
    if not payload:
        raise HTTPException(400, "确认令牌无效或已过期")

    if payload.get("user_id") != str(current_user.user_id):
        cache.delete_confirm_token(session_id, confirm_token)
        raise HTTPException(403, "确认令牌不属于当前用户")
    
    # 验证 preview_hash
    if preview_hash != payload.get("preview_hash"):
        cache.delete_confirm_token(session_id, confirm_token)
        raise HTTPException(400, "预览内容已变更，请重新确认")
    
    # 取消操作
    if action == "cancel":
        cache.delete_confirm_token(session_id, confirm_token)
        return {
            "status": "cancelled",
            "message": "已取消批量修改"
        }
    
    # 获取当前活跃版本
    doc_uuid = uuid.UUID(doc_id)
    active_rev = db.query(db_models.DocumentActiveRevision).filter(
        db_models.DocumentActiveRevision.doc_id == doc_uuid
    ).first()
    
    if not active_rev:
        raise HTTPException(404, "文档不存在")
    
    # 验证版本号
    if active_rev.version != payload.get("active_version"):
        cache.delete_confirm_token(session_id, confirm_token)
        raise HTTPException(409, "文档版本已变更，预览已失效")
    
    try:
        # 应用批量修改
        apply_node = BulkApplyNode(db)
        preview = PreviewDiff(**payload["preview"])
        
        result = apply_node.apply_bulk_changes(
            preview,
            doc_id,
            str(active_rev.rev_id),
            active_rev.version,
            user_id=str(current_user.user_id),
            trace_id=None
        )
        
        # 删除 token
        cache.delete_confirm_token(session_id, confirm_token)
        
        # 重新索引（如果启用了 Meilisearch）
        try:
            from app.services.search_indexer import get_indexer
            indexer = get_indexer()
            indexer.index_document_blocks(doc_id, result['new_rev_id'], db)
        except Exception as e:
            print(f"重新索引失败（不影响主流程）: {e}")
        
        return {
            "status": "applied",
            "message": f"已成功修改 {result['changes_applied']} 处内容",
            "new_rev_id": result['new_rev_id'],
            "new_rev_no": result['new_rev_no'],
            "new_version": result['new_version'],
            "changes_applied": result['changes_applied']
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"应用批量修改失败: {str(e)}")


@app.get("/v1/chat/sessions/{session_id}", response_model=ChatSessionDetailResponse)
async def get_chat_session(
    session_id: str,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """查看当前用户的会话历史"""
    try:
        session, messages = MemoryService(db).get_session_history(
            user_id=str(current_user.user_id),
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(404, "会话不存在") from exc

    return ChatSessionDetailResponse(
        session_id=str(session.session_id),
        doc_id=str(session.doc_id),
        status=session.status,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            ChatMessageResponse(
                msg_id=str(message.msg_id),
                role=message.role,
                content=message.content,
                meta=message.meta,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@app.get("/v1/users/me/preferences", response_model=list[UserPreferenceResponse])
async def list_my_preferences(
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """查看当前用户的长期偏好"""
    items = MemoryService(db).list_user_preferences(str(current_user.user_id))
    return [
        UserPreferenceResponse(
            preference_key=item.preference_key,
            preference_value=item.preference_value,
            source_type=item.source_type,
            source=item.source,
            confidence=item.confidence,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@app.put("/v1/users/me/preferences/{preference_key}", response_model=UserPreferenceResponse)
async def upsert_my_preference(
    preference_key: str,
    request: UserPreferenceUpsertRequest,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """显式更新当前用户偏好"""
    item = MemoryService(db).upsert_user_preference(
        user_id=str(current_user.user_id),
        preference_key=preference_key,
        preference_value=request.preference_value,
        source=request.source,
        source_type="explicit" if request.source == "user_explicit" else "inferred",
        confidence=1.0 if request.source == "user_explicit" else 0.9,
        details={"updated_via": "api"},
    )
    db.commit()
    db.refresh(item)
    return UserPreferenceResponse(
        preference_key=item.preference_key,
        preference_value=item.preference_value,
        source_type=item.source_type,
        source=item.source,
        confidence=item.confidence,
        updated_at=item.updated_at,
    )


@app.delete("/v1/users/me/preferences/{preference_key}")
async def delete_my_preference(
    preference_key: str,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """删除当前用户偏好"""
    deleted = MemoryService(db).delete_user_preference(
        user_id=str(current_user.user_id),
        preference_key=preference_key,
    )
    if not deleted:
        raise HTTPException(404, "偏好不存在")
    db.commit()
    return {"status": "deleted", "preference_key": preference_key}


@app.get("/v1/users/me/memory", response_model=list[UserMemoryItemResponse])
async def list_my_memory(
    memory_type: Optional[str] = None,
    scope: Optional[str] = None,
    doc_id: Optional[str] = None,
    active_only: bool = True,
    limit: int = 50,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """查看当前用户的情景记忆"""
    items = MemoryService(db).list_memory_items(
        user_id=str(current_user.user_id),
        memory_type=memory_type,
        scope=scope,
        doc_id=doc_id,
        active_only=active_only,
        limit=min(limit, 100),
    )
    return [
        UserMemoryItemResponse(
            memory_id=str(item.memory_id),
            memory_layer=item.memory_layer,
            memory_type=item.memory_type,
            memory_subtype=item.memory_subtype,
            scope=item.scope,
            title=item.title,
            content=item.content,
            summary=item.summary,
            confidence=item.confidence,
            importance=item.importance,
            memory_strength=item.memory_strength,
            stability=item.stability,
            retention_score=item.retention_score,
            review_count=item.review_count,
            recall_count=item.recall_count,
            doc_id=str(item.doc_id) if item.doc_id else None,
            session_id=str(item.session_id) if item.session_id else None,
            created_at=item.created_at,
            last_recalled_at=item.last_recalled_at,
            archived_at=item.archived_at,
        )
        for item in items
    ]


@app.get("/v1/docs/{doc_id}/preferences", response_model=list[UserPreferenceResponse])
async def list_document_preferences(
    doc_id: str,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """查看某篇文档的结构化偏好"""
    _get_owned_document_or_404(db, doc_id, current_user.user_id)
    items = MemoryService(db).list_document_preferences(str(current_user.user_id), doc_id)
    return [
        UserPreferenceResponse(
            preference_key=item.preference_key,
            preference_value=item.preference_value,
            source_type=item.source_type,
            source=item.source,
            confidence=item.confidence,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@app.put("/v1/docs/{doc_id}/preferences/{preference_key}", response_model=UserPreferenceResponse)
async def upsert_document_preference(
    doc_id: str,
    preference_key: str,
    request: UserPreferenceUpsertRequest,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """显式更新某篇文档的结构化偏好"""
    _get_owned_document_or_404(db, doc_id, current_user.user_id)
    item = MemoryService(db).upsert_document_preference(
        user_id=str(current_user.user_id),
        doc_id=doc_id,
        preference_key=preference_key,
        preference_value=request.preference_value,
        scope_type="document",
        scope_key=doc_id,
        source=request.source,
        source_type="explicit" if request.source == "user_explicit" else "inferred",
        confidence=1.0 if request.source == "user_explicit" else 0.9,
    )
    db.commit()
    db.refresh(item)
    return UserPreferenceResponse(
        preference_key=item.preference_key,
        preference_value=item.preference_value,
        source_type=item.source_type,
        source=item.source,
        confidence=item.confidence,
        updated_at=item.updated_at,
    )


@app.delete("/v1/users/me/memory/{memory_id}")
async def delete_my_memory(
    memory_id: str,
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """删除当前用户的某条情景记忆"""
    deleted = MemoryService(db).delete_memory_item(
        user_id=str(current_user.user_id),
        memory_id=memory_id,
    )
    if not deleted:
        raise HTTPException(404, "记忆不存在")
    db.commit()
    return {"status": "deleted", "memory_id": memory_id}


@app.post("/v1/users/me/memory/maintenance")
async def run_my_memory_maintenance(
    current_user: AuthUser = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """手动执行一次当前用户记忆热度衰减和归档"""
    result = MemoryService(db).run_maintenance(user_id=str(current_user.user_id))
    db.commit()
    return {"status": "ok", **result}
