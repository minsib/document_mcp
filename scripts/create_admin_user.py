#!/usr/bin/env python3
"""
创建管理员用户

用法:
    python scripts/create_admin_user.py
"""
import sys
import os
import getpass

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import get_db
from app.auth.models import User
from app.auth.security import get_password_hash
import uuid


def create_admin_user():
    """创建管理员用户"""
    db = next(get_db())
    
    try:
        print("🔧 创建管理员用户\n")
        
        # 输入用户信息
        username = input("用户名: ").strip()
        if not username:
            print("❌ 用户名不能为空")
            return
        
        # 检查用户名是否已存在
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"❌ 用户名 '{username}' 已存在")
            return
        
        email = input("邮箱: ").strip()
        if not email:
            print("❌ 邮箱不能为空")
            return
        
        # 检查邮箱是否已存在
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"❌ 邮箱 '{email}' 已被注册")
            return
        
        full_name = input("全名（可选）: ").strip() or None
        
        # 输入密码
        password = getpass.getpass("密码: ")
        if len(password) < 6:
            print("❌ 密码长度至少为 6 个字符")
            return
        
        password_confirm = getpass.getpass("确认密码: ")
        if password != password_confirm:
            print("❌ 两次输入的密码不一致")
            return
        
        # 创建用户
        user = User(
            user_id=uuid.uuid4(),
            username=username,
            email=email,
            full_name=full_name,
            hashed_password=get_password_hash(password),
            is_active=True,
            is_superuser=True  # 管理员用户
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        print(f"\n✅ 管理员用户创建成功！")
        print(f"   用户 ID: {user.user_id}")
        print(f"   用户名: {user.username}")
        print(f"   邮箱: {user.email}")
        print(f"   是否为超级用户: {user.is_superuser}")
        
        print(f"\n💡 提示:")
        print(f"   1. 使用用户名和密码登录: POST /v1/auth/login")
        print(f"   2. 或创建 API Key: POST /v1/auth/api-keys")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_admin_user()
