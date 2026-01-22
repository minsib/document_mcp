"""
认证相关的 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List
import uuid

from app.db.connection import get_db
from app.auth import schemas
from app.auth.models import User, APIKey
from app.auth.security import (
    verify_password, get_password_hash,
    create_access_token, create_refresh_token, decode_token,
    generate_api_key
)
from app.auth.dependencies import (
    get_current_active_user, get_current_superuser
)

router = APIRouter(prefix="/v1/auth", tags=["认证"])


@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: schemas.UserCreate,
    db: Session = Depends(get_db)
):
    """注册新用户"""
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    # 创建用户
    user = User(
        user_id=uuid.uuid4(),
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=get_password_hash(user_data.password),
        is_active=True,
        is_superuser=False
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@router.post("/login", response_model=schemas.Token)
async def login(
    login_data: schemas.LoginRequest,
    db: Session = Depends(get_db)
):
    """用户登录"""
    # 查找用户
    user = db.query(User).filter(User.username == login_data.username).first()
    
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )
    
    # 更新最后登录时间
    user.last_login_at = datetime.utcnow()
    db.commit()
    
    # 创建令牌
    access_token = create_access_token(data={"sub": str(user.user_id)})
    refresh_token = create_refresh_token(data={"sub": str(user.user_id)})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=schemas.Token)
async def refresh_token(
    refresh_data: schemas.RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """刷新访问令牌"""
    payload = decode_token(refresh_data.refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的刷新令牌"
        )
    
    user = db.query(User).filter(User.user_id == user_uuid).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用"
        )
    
    # 创建新令牌
    access_token = create_access_token(data={"sub": str(user.user_id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.user_id)})
    
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=schemas.UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """获取当前用户信息"""
    return current_user


@router.put("/me", response_model=schemas.UserResponse)
async def update_current_user(
    user_update: schemas.UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """更新当前用户信息"""
    if user_update.email:
        # 检查邮箱是否已被其他用户使用
        existing = db.query(User).filter(
            User.email == user_update.email,
            User.user_id != current_user.user_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用"
            )
        current_user.email = user_update.email
    
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    
    if user_update.password:
        current_user.hashed_password = get_password_hash(user_update.password)
    
    db.commit()
    db.refresh(current_user)
    
    return current_user


# ============ API Key 管理 ============

@router.post("/api-keys", response_model=schemas.APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: schemas.APIKeyCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """创建 API Key"""
    # 生成 API Key
    api_key, key_hash, key_prefix = generate_api_key()
    
    # 计算过期时间
    expires_at = None
    if key_data.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=key_data.expires_days)
    
    # 创建记录
    api_key_obj = APIKey(
        key_id=uuid.uuid4(),
        user_id=current_user.user_id,
        key_name=key_data.key_name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_active=True,
        expires_at=expires_at
    )
    
    db.add(api_key_obj)
    db.commit()
    db.refresh(api_key_obj)
    
    # 返回完整的 API Key（只在创建时返回一次）
    return schemas.APIKeyCreateResponse(
        key_id=api_key_obj.key_id,
        key_name=api_key_obj.key_name,
        key_prefix=api_key_obj.key_prefix,
        is_active=api_key_obj.is_active,
        expires_at=api_key_obj.expires_at,
        last_used_at=api_key_obj.last_used_at,
        created_at=api_key_obj.created_at,
        api_key=api_key  # 完整的 key
    )


@router.get("/api-keys", response_model=List[schemas.APIKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """列出当前用户的所有 API Keys"""
    api_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.user_id
    ).order_by(APIKey.created_at.desc()).all()
    
    return api_keys


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """删除 API Key"""
    api_key = db.query(APIKey).filter(
        APIKey.key_id == key_id,
        APIKey.user_id == current_user.user_id
    ).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key 不存在"
        )
    
    db.delete(api_key)
    db.commit()
    
    return None


@router.patch("/api-keys/{key_id}/toggle", response_model=schemas.APIKeyResponse)
async def toggle_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """启用/禁用 API Key"""
    api_key = db.query(APIKey).filter(
        APIKey.key_id == key_id,
        APIKey.user_id == current_user.user_id
    ).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key 不存在"
        )
    
    api_key.is_active = not api_key.is_active
    db.commit()
    db.refresh(api_key)
    
    return api_key
