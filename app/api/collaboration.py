"""
协同编辑 WebSocket API
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.orm import Session
import logging
import json

from app.db.connection import get_db
from app.services.collaboration import CollaborationManager
from app.services.cache import get_cache_manager
from app.auth.dependencies import get_current_user_ws
from app.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

# 全局协同管理器实例
collaboration_manager: CollaborationManager = None


def get_collaboration_manager() -> CollaborationManager:
    """获取协同管理器实例"""
    global collaboration_manager
    if collaboration_manager is None:
        # 从缓存管理器获取 Redis 客户端
        cache_manager = get_cache_manager()
        if cache_manager.redis_available:
            # 创建异步 Redis 客户端
            import redis.asyncio as redis
            redis_client = redis.from_url(cache_manager.redis_url)
            collaboration_manager = CollaborationManager(redis_client)
        else:
            raise RuntimeError("Redis not available for collaboration")
    return collaboration_manager


@router.websocket("/ws/collab/{doc_id}")
async def websocket_collaboration(
    websocket: WebSocket,
    doc_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    协同编辑 WebSocket 端点
    
    客户端需要通过 query 参数传递 token
    """
    manager = get_collaboration_manager()
    
    # 验证用户身份
    try:
        user = await get_current_user_ws(token, db)
    except Exception as e:
        await websocket.close(code=1008, reason="Authentication failed")
        return
    
    # 连接用户
    await manager.connect(websocket, doc_id, str(user.user_id), user.username)
    
    try:
        # 消息处理循环
        while True:
            # 接收客户端消息
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "edit":
                # 编辑操作
                edit_data = data.get("data", {})
                block_id = edit_data.get("block_id")
                
                # 尝试获取编辑锁
                if block_id:
                    lock_acquired = await manager.acquire_edit_lock(
                        doc_id, str(user.user_id), block_id
                    )
                    if not lock_acquired:
                        # 锁被其他用户持有
                        lock_owner = await manager.get_edit_lock_owner(doc_id, block_id)
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Block is being edited by another user",
                            "lock_owner": lock_owner
                        })
                        continue
                
                # 广播编辑操作
                await manager.broadcast_edit(doc_id, edit_data, str(user.user_id))
                
                # 释放锁
                if block_id:
                    await manager.release_edit_lock(doc_id, block_id, str(user.user_id))
            
            elif message_type == "cursor":
                # 光标位置更新
                cursor_position = data.get("position", {})
                await manager.broadcast_cursor(doc_id, str(user.user_id), cursor_position)
            
            elif message_type == "ping":
                # 心跳
                await websocket.send_json({"type": "pong"})
            
            elif message_type == "get_recent_events":
                # 获取最近的编辑事件（用于同步）
                limit = data.get("limit", 50)
                events = await manager.get_recent_events(doc_id, limit)
                await websocket.send_json({
                    "type": "recent_events",
                    "events": events
                })
            
            else:
                logger.warning(f"Unknown message type: {message_type}")
    
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)
