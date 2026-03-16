"""
协同编辑服务
使用 Redis + WebSocket 实现多人实时协同编辑
"""
import json
import time
from typing import Dict, Set, Optional, Any
from datetime import datetime
import redis.asyncio as redis
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


class CollaborationManager:
    """协同编辑管理器"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        # 文档 -> WebSocket 连接集合
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # WebSocket -> 用户信息
        self.connection_users: Dict[WebSocket, Dict[str, Any]] = {}
        
    async def connect(
        self,
        websocket: WebSocket,
        doc_id: str,
        user_id: str,
        username: str
    ):
        """用户连接到文档"""
        await websocket.accept()
        
        # 添加连接
        if doc_id not in self.active_connections:
            self.active_connections[doc_id] = set()
        self.active_connections[doc_id].add(websocket)
        
        # 记录用户信息
        self.connection_users[websocket] = {
            "user_id": user_id,
            "username": username,
            "doc_id": doc_id,
            "connected_at": datetime.utcnow().isoformat()
        }
        
        # 在 Redis 中记录在线用户
        await self._add_online_user(doc_id, user_id, username)
        
        # 通知其他用户有新用户加入
        await self.broadcast_to_document(
            doc_id,
            {
                "type": "user_joined",
                "user_id": user_id,
                "username": username,
                "timestamp": datetime.utcnow().isoformat()
            },
            exclude=websocket
        )
        
        # 发送当前在线用户列表给新用户
        online_users = await self.get_online_users(doc_id)
        await websocket.send_json({
            "type": "online_users",
            "users": online_users
        })
        
        logger.info(f"User {username} connected to document {doc_id}")
    
    async def disconnect(self, websocket: WebSocket):
        """用户断开连接"""
        if websocket not in self.connection_users:
            return
        
        user_info = self.connection_users[websocket]
        doc_id = user_info["doc_id"]
        user_id = user_info["user_id"]
        username = user_info["username"]
        
        # 移除连接
        if doc_id in self.active_connections:
            self.active_connections[doc_id].discard(websocket)
            if not self.active_connections[doc_id]:
                del self.active_connections[doc_id]
        
        del self.connection_users[websocket]
        
        # 从 Redis 移除在线用户
        await self._remove_online_user(doc_id, user_id)
        
        # 通知其他用户该用户离开
        await self.broadcast_to_document(
            doc_id,
            {
                "type": "user_left",
                "user_id": user_id,
                "username": username,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"User {username} disconnected from document {doc_id}")
    
    async def broadcast_to_document(
        self,
        doc_id: str,
        message: Dict[str, Any],
        exclude: Optional[WebSocket] = None
    ):
        """向文档的所有连接广播消息"""
        if doc_id not in self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections[doc_id]:
            if connection == exclude:
                continue
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to connection: {e}")
                disconnected.append(connection)
        
        # 清理断开的连接
        for connection in disconnected:
            await self.disconnect(connection)
    
    async def broadcast_edit(
        self,
        doc_id: str,
        edit_data: Dict[str, Any],
        user_id: str
    ):
        """广播编辑操作"""
        message = {
            "type": "edit",
            "user_id": user_id,
            "data": edit_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # 存储到 Redis（用于离线用户同步）
        await self._store_edit_event(doc_id, message)
        
        # 实时广播
        await self.broadcast_to_document(doc_id, message)
    
    async def broadcast_cursor(
        self,
        doc_id: str,
        user_id: str,
        cursor_position: Dict[str, Any]
    ):
        """广播光标位置"""
        message = {
            "type": "cursor",
            "user_id": user_id,
            "position": cursor_position,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.broadcast_to_document(doc_id, message)
    
    async def get_online_users(self, doc_id: str) -> list:
        """获取文档的在线用户列表"""
        key = f"doc:{doc_id}:online_users"
        users_data = await self.redis.hgetall(key)
        
        users = []
        for user_id, data in users_data.items():
            user_info = json.loads(data)
            users.append(user_info)
        
        return users
    
    async def _add_online_user(self, doc_id: str, user_id: str, username: str):
        """在 Redis 中添加在线用户"""
        key = f"doc:{doc_id}:online_users"
        user_data = json.dumps({
            "user_id": user_id,
            "username": username,
            "connected_at": datetime.utcnow().isoformat()
        })
        await self.redis.hset(key, user_id, user_data)
        await self.redis.expire(key, 86400)  # 24 小时过期
    
    async def _remove_online_user(self, doc_id: str, user_id: str):
        """从 Redis 移除在线用户"""
        key = f"doc:{doc_id}:online_users"
        await self.redis.hdel(key, user_id)
    
    async def _store_edit_event(self, doc_id: str, event: Dict[str, Any]):
        """存储编辑事件到 Redis（用于离线同步）"""
        key = f"doc:{doc_id}:edit_events"
        await self.redis.lpush(key, json.dumps(event))
        await self.redis.ltrim(key, 0, 99)  # 只保留最近 100 个事件
        await self.redis.expire(key, 3600)  # 1 小时过期
    
    async def get_recent_events(self, doc_id: str, limit: int = 50) -> list:
        """获取最近的编辑事件"""
        key = f"doc:{doc_id}:edit_events"
        events_data = await self.redis.lrange(key, 0, limit - 1)
        
        events = []
        for data in events_data:
            events.append(json.loads(data))
        
        return events
    
    async def acquire_edit_lock(
        self,
        doc_id: str,
        user_id: str,
        block_id: str,
        timeout: int = 30
    ) -> bool:
        """获取块编辑锁（防止冲突）"""
        key = f"doc:{doc_id}:block:{block_id}:lock"
        lock_acquired = await self.redis.set(
            key,
            user_id,
            nx=True,  # 只在不存在时设置
            ex=timeout  # 过期时间
        )
        return bool(lock_acquired)
    
    async def release_edit_lock(self, doc_id: str, block_id: str, user_id: str):
        """释放块编辑锁"""
        key = f"doc:{doc_id}:block:{block_id}:lock"
        # 只有锁的持有者才能释放
        current_owner = await self.redis.get(key)
        if current_owner and current_owner.decode() == user_id:
            await self.redis.delete(key)
    
    async def get_edit_lock_owner(self, doc_id: str, block_id: str) -> Optional[str]:
        """获取块编辑锁的持有者"""
        key = f"doc:{doc_id}:block:{block_id}:lock"
        owner = await self.redis.get(key)
        return owner.decode() if owner else None
