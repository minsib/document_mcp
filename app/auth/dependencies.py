"""
认证依赖项
"""
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.orm import Session
from typing import Optional
import uuid

from app.db.connection import get_db
from app.auth.models import User, APIKey
from app.auth.security import decode_token, hash_api_key
from datetime import datetime

# JWT Bearer 认证
security = HTTPBearer(auto_error=False)

# API Key 认证
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """从 JWT Token 获取当前用户"""
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if not payload:
        return None
    
    # 检查 token 类型
    if payload.get("type") != "access":
        return None
    
    user_id = payload.get("sub")
    if not user_id:
        return None
    
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None
    
    user = db.query(User).filter(User.user_id == user_uuid).first()
    
    if not user or not user.is_active:
        return None
    
    return user


async def get_current_user_from_api_key(
    api_key: Optional[str] = Security(api_key_header),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """从 API Key 获取当前用户"""
    if not api_key:
        return None
    
    # 哈希 API Key
    key_hash = hash_api_key(api_key)
    
    # 查找 API Key
    api_key_obj = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.is_active == True
    ).first()
    
    if not api_key_obj:
        return None
    
    # 检查是否过期
    if api_key_obj.expires_at and api_key_obj.expires_at < datetime.utcnow():
        return None
    
    # 更新最后使用时间
    api_key_obj.last_used_at = datetime.utcnow()
    db.commit()
    
    # 获取用户
    user = db.query(User).filter(User.user_id == api_key_obj.user_id).first()
    
    if not user or not user.is_active:
        return None
    
    return user


async def get_current_user(
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
    user_from_api_key: Optional[User] = Depends(get_current_user_from_api_key)
) -> User:
    """
    获取当前用户（支持 JWT Token 和 API Key）
    
    优先级：JWT Token > API Key
    """
    user = user_from_token or user_from_api_key
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证或认证已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """获取当前活跃用户"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """获取当前超级用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足"
        )
    return current_user


# 可选认证（不强制要求认证）
async def get_optional_user(
    user_from_token: Optional[User] = Depends(get_current_user_from_token),
    user_from_api_key: Optional[User] = Depends(get_current_user_from_api_key)
) -> Optional[User]:
    """获取当前用户（可选，不强制要求认证）"""
    return user_from_token or user_from_api_key
