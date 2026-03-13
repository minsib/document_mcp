#!/usr/bin/env python3
"""
快速测试脚本 - 测试 LangGraph 重构后的系统
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.connection import get_db
from app.services.langgraph_workflow import LangGraphWorkflowExecutor
from app.models import database as db_models
from app.auth.models import User
from app.services.splitter import BlockSplitter
import uuid


def create_test_document(db):
    """创建测试文档"""
    print("📝 创建测试文档...")
    
    # 尝试获取已存在的测试用户，如果不存在则创建
    import random
    username = f"test_user_{random.randint(1000, 9999)}"
    
    user = User(
        user_id=uuid.uuid4(),
        username=username,
        email=f"{username}@example.com",
        hashed_password="test"
    )
    db.add(user)
    db.flush()
    
    # 创建文档
    doc = db_models.Document(
        doc_id=uuid.uuid4(),
        title="测试文档 - LangGraph 架构",
        user_id=user.user_id
    )
    db.add(doc)
    db.flush()
    
    # 创建初始版本
    rev = db_models.DocumentRevision(
        rev_id=uuid.uuid4(),
        doc_id=doc.doc_id,
        rev_no=1,
        change_summary="初始版本",
        created_by=str(user.user_id)
    )
    db.add(rev)
    db.flush()
    
    # 测试内容
    test_content = """# 项目需求文档

## 1. 项目背景

本项目旨在开发一个创新的文档编辑系统，允许用户通过自然语言对话的方式修改文档内容。系统采用 LangGraph + 智能体架构，提供更好的可维护性和扩展性。

## 2. 核心功能

系统支持以下核心功能：

### 2.1 对话式编辑
用户可以使用自然语言描述修改需求，系统自动理解并执行。

### 2.2 精准定位
通过混合检索（BM25 + 向量检索）精确定位目标内容。

### 2.3 版本管理
完整的版本历史，支持任意版本回滚。

## 3. 技术架构

系统采用以下技术栈：
- 后端：FastAPI + Python 3.11
- 数据库：PostgreSQL + pgvector
- 搜索：Meilisearch
- 工作流：LangGraph
- LLM：Qwen3-235B

## 4. 智能体设计

系统包含 5 个核心智能体：

### 4.1 Intent Agent
负责理解用户意图，提取操作类型和目标描述。

### 4.2 Router Agent
负责路由决策，判断是否需要澄清。

### 4.3 Clarify Agent
负责处理模糊意图，生成澄清问题。

### 4.4 Retrieval Agent
负责检索和定位目标块。

### 4.5 Edit Agent
负责执行编辑操作，更新数据库和索引。
"""
    
    # 分块
    splitter = BlockSplitter()
    blocks = splitter.split_document(test_content)
    
    for block_data in blocks:
        block = db_models.Block(block_id=block_data.block_id, doc_id=doc.doc_id, first_rev_id=rev.rev_id)
        db.add(block)
        
        block_version = db_models.BlockVersion(
            block_version_id=uuid.uuid4(),
            block_id=block_data.block_id,
            rev_id=rev.rev_id,
            block_type=block_data.block_type,
            heading_level=block_data.heading_level,
            content_md=block_data.content_md,
            plain_text=block_data.plain_text,
            content_hash=block_data.content_hash,
            order_index=block_data.order_index,
            parent_heading_block_id=block_data.parent_heading_block_id
        )
        db.add(block_version)
    
    # 设置活跃版本
    active_rev = db_models.DocumentActiveRevision(
        doc_id=doc.doc_id,
        rev_id=rev.rev_id,
        version=1
    )
    db.add(active_rev)
    
    db.commit()
    
    print(f"✅ 文档创建成功！")
    print(f"   文档 ID: {doc.doc_id}")
    print(f"   用户 ID: {user.user_id}")
    print(f"   块数量: {len(blocks)}")
    
    return str(doc.doc_id), str(user.user_id)


def test_workflow(db, doc_id, user_id, test_message):
    """测试工作流"""
    print(f"\n🧪 测试: {test_message}")
    print("=" * 60)
    
    executor = LangGraphWorkflowExecutor(db)
    
    result = executor.execute(
        doc_id=doc_id,
        session_id=f"test_session_{uuid.uuid4().hex[:8]}",
        user_id=user_id,
        user_message=test_message
    )
    
    print(f"\n📊 结果:")
    print(f"   状态: {result.get('status')}")
    print(f"   消息: {result.get('message')}")
    
    if result.get("status") == "need_clarification":
        clarification = result.get("clarification", {})
        print(f"\n❓ 需要澄清:")
        print(f"   类型: {clarification.get('type')}")
        print(f"   问题: {clarification.get('question')}")
        if clarification.get("options"):
            print(f"   选项:")
            for opt in clarification["options"]:
                print(f"     - {opt.get('label')}")
    
    elif result.get("status") == "need_disambiguation":
        print(f"\n🔍 需要消歧:")
        candidates = result.get("candidates", [])
        print(f"   找到 {len(candidates)} 个候选:")
        for i, cand in enumerate(candidates, 1):
            print(f"     {i}. {cand.get('heading_context')}: {cand.get('snippet')[:50]}...")
    
    elif result.get("status") == "need_confirm":
        print(f"\n✅ 需要确认:")
        preview = result.get("preview", {})
        diffs = preview.get("diffs", [])
        print(f"   修改数量: {len(diffs)}")
        for diff in diffs:
            print(f"     - {diff.get('op_type')}: {diff.get('heading_context')}")
            print(f"       修改前: {diff.get('before_snippet')[:50]}...")
            print(f"       修改后: {diff.get('after_snippet')[:50]}...")
    
    elif result.get("status") == "applied":
        print(f"\n🎉 修改成功!")
        print(f"   新版本 ID: {result.get('new_rev_id')}")
    
    elif result.get("status") == "failed":
        print(f"\n❌ 失败:")
        error = result.get("error", {})
        print(f"   错误类型: {error.get('code')}")
        print(f"   错误信息: {error.get('message')}")
    
    print("\n" + "=" * 60)
    
    return result


def main():
    """主函数"""
    print("🚀 LangGraph 架构快速测试")
    print("=" * 60)
    
    # 获取数据库连接
    db = next(get_db())
    
    try:
        # 1. 创建测试文档
        doc_id, user_id = create_test_document(db)
        
        # 2. 测试用例
        test_cases = [
            "把项目背景那段改得更简洁一些",
            "找到核心功能那一段",
            "把技术架构中的 FastAPI 改成 Django",
            "删除智能体设计这一章",
            "在第二章后面添加一段关于安全性的说明",
        ]
        
        print(f"\n📋 准备运行 {len(test_cases)} 个测试用例...")
        
        for i, test_message in enumerate(test_cases, 1):
            print(f"\n{'='*60}")
            print(f"测试 {i}/{len(test_cases)}")
            test_workflow(db, doc_id, user_id, test_message)
            
            if i < len(test_cases):
                input("\n按 Enter 继续下一个测试...")
        
        print(f"\n{'='*60}")
        print("✅ 所有测试完成！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        db.close()


if __name__ == "__main__":
    main()
