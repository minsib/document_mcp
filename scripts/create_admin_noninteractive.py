#!/usr/bin/env python3
"""非交互式创建管理员用户"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.db.connection import SessionLocal
from app.auth.models import User
from app.auth.security import get_password_hash
import uuid


def create_admin_user():
    """创建管理员用户"""
    # 固定的管理员信息
    username = "admin"
    email = "admin@example.com"
    full_name = "Admin User"
    password = "admin123"
    
    print(f"🔧 创建管理员用户: {username}")
    
    # 创建数据库会话
    db = SessionLocal()
    
    try:
        # 检查用户是否已存在
        existing_user = db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            print(f"⚠️  用户已存在: {existing_user.username}")
            return
        
        # 创建用户
        user = User(
            user_id=uuid.uuid4(),
            username=username,
            email=email,
            full_name=full_name,
            hashed_password=get_password_hash(password),
            is_active=True,
            is_superuser=True
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print(f"✅ 管理员用户创建成功！")
        print(f"   用户名: {username}")
        print(f"   邮箱: {email}")
        print(f"   密码: {password}")
        print(f"   超级用户: 是")
        
    except Exception as e:
        db.rollback()
        print(f"❌ 错误: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_admin_user()
