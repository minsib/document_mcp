#!/usr/bin/env python3
"""
完整流程测试 - 测试从意图解析到编辑完成的完整流程
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.connection import get_db
from app.services.langgraph_workflow import LangGraphWorkflowExecutor
from app.models import database as db_models
from app.auth.models import User
from app.services.splitter import BlockSplitter
import uuid


def create_simple_test_document(db):
    """创建简单的测试文档"""
    print("📝 创建测试文档...")
    
    # 创建用户
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
        title="简单测试文档",
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
    
    # 简单的测试内容
    test_content = """# 产品介绍

## 产品特点

我们的产品具有高性能、易用性和可扩展性三大特点。

## 技术架构

系统采用微服务架构，使用 Python 和 FastAPI 开发。

## 价格方案

基础版每月 99 元，专业版每月 299 元。
"""
    
    # 分块
    splitter = BlockSplitter()
    blocks = splitter.split_document(test_content)
    
    # 获取 embedding 和索引服务
    from app.services.embedding import get_embedding_service
    from app.services.search_indexer import get_indexer
    
    try:
        embedding_service = get_embedding_service()
        print("✅ Embedding 服务已加载")
    except Exception as e:
        print(f"⚠️  Embedding 服务加载失败: {e}")
        embedding_service = None
    
    try:
        indexer = get_indexer()
        print("✅ Meilisearch 索引服务已加载")
    except Exception as e:
        print(f"⚠️  Meilisearch 索引服务加载失败: {e}")
        indexer = None
    
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
            block_type=block_data.block_type,
            heading_level=block_data.heading_level,
            content_md=block_data.content_md,
            plain_text=block_data.plain_text,
            content_hash=block_data.content_hash,
            order_index=block_data.order_index,
            parent_heading_block_id=block_data.parent_heading_block_id
        )
        
        # 生成 embedding
        if embedding_service and block_data.plain_text:
            try:
                embedding = embedding_service.generate_embedding(block_data.plain_text)
                block_version.embedding = embedding
            except Exception as e:
                print(f"⚠️  生成 embedding 失败 (block {block_data.block_id}): {e}")
        
        db.add(block_version)
    
    # 设置活跃版本
    active_rev = db_models.DocumentActiveRevision(
        doc_id=doc.doc_id,
        rev_id=rev.rev_id,
        version=1
    )
    db.add(active_rev)
    
    db.commit()
    
    # 创建 Meilisearch 索引
    if indexer:
        print("📊 正在创建 Meilisearch 索引...")
        try:
            for block_data in blocks:
                # 获取父级标题
                parent_heading = None
                if block_data.parent_heading_block_id:
                    parent_block = next((b for b in blocks if b.block_id == block_data.parent_heading_block_id), None)
                    if parent_block:
                        parent_heading = parent_block.plain_text
                
                indexer.index_block(
                    block_id=str(block_data.block_id),
                    doc_id=str(doc.doc_id),
                    rev_id=str(rev.rev_id),
                    content=block_data.plain_text,
                    block_type=block_data.block_type,
                    order_index=block_data.order_index,
                    parent_heading=parent_heading
                )
            print("✅ Meilisearch 索引创建成功")
        except Exception as e:
            print(f"⚠️  创建 Meilisearch 索引失败: {e}")
    
    print(f"✅ 文档创建成功！")
    print(f"   文档 ID: {doc.doc_id}")
    print(f"   用户 ID: {user.user_id}")
    print(f"   块数量: {len(blocks)}")
    print(f"\n📄 文档内容:")
    for i, block in enumerate(blocks, 1):
        print(f"   {i}. [{block.block_type}] {block.plain_text[:50]}...")
    
    return str(doc.doc_id), str(user.user_id)


def test_complete_workflow(db, doc_id, user_id):
    """测试完整的编辑流程"""
    
    test_cases = [
        {
            "name": "测试1: 替换具体内容",
            "message": "把'高性能、易用性和可扩展性'改成'快速、简单、灵活'",
            "expected_status": ["need_confirm", "applied"]
        },
        {
            "name": "测试2: 修改价格",
            "message": "把基础版价格改成 79 元",
            "expected_status": ["need_confirm", "applied"]
        },
        {
            "name": "测试3: 添加新内容",
            "message": "在技术架构后面添加一段：支持 Docker 容器化部署",
            "expected_status": ["need_confirm", "applied"]
        }
    ]
    
    executor = LangGraphWorkflowExecutor(db)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"🧪 {test_case['name']}")
        print(f"{'='*70}")
        print(f"📝 用户消息: {test_case['message']}")
        
        try:
            result = executor.execute(
                doc_id=doc_id,
                session_id=f"test_session_{i}",
                user_id=user_id,
                user_message=test_case['message']
            )
            
            status = result.get('status')
            print(f"\n📊 状态: {status}")
            
            if status == "need_clarification":
                print(f"❓ 需要澄清:")
                clarification = result.get('clarification', {})
                print(f"   问题: {clarification.get('question', '')}")
                print(f"   ⚠️  测试未通过 - 需要更明确的指令")
                
            elif status == "need_disambiguation":
                print(f"🔍 需要消歧:")
                candidates = result.get('candidates', [])
                print(f"   找到 {len(candidates)} 个候选位置")
                for j, cand in enumerate(candidates[:3], 1):
                    print(f"   {j}. {cand.get('heading_context')}: {cand.get('snippet')[:50]}...")
                print(f"   ⚠️  测试未通过 - 需要选择具体位置")
                
            elif status == "need_confirm":
                print(f"✅ 生成预览成功!")
                preview = result.get('preview', {})
                diffs = preview.get('diffs', [])
                print(f"   修改数量: {len(diffs)}")
                for diff in diffs:
                    print(f"\n   📝 修改详情:")
                    print(f"      位置: {diff.get('heading_context')}")
                    print(f"      操作: {diff.get('op_type')}")
                    print(f"      修改前: {diff.get('before_snippet', '')[:60]}...")
                    print(f"      修改后: {diff.get('after_snippet', '')[:60]}...")
                print(f"\n   ✅ 测试通过 - 预览生成成功")
                
            elif status == "applied":
                print(f"🎉 修改已应用!")
                print(f"   新版本 ID: {result.get('new_rev_id')}")
                print(f"   ✅ 测试通过 - 修改成功")
                
            elif status == "failed":
                print(f"❌ 失败:")
                error = result.get('error', {})
                print(f"   错误: {error.get('message', '未知错误')}")
                print(f"   ⚠️  测试未通过")
            
            else:
                print(f"❓ 未知状态: {status}")
                print(f"   ⚠️  测试未通过")
            
            # 检查是否符合预期
            if status in test_case['expected_status']:
                print(f"\n✅ 符合预期状态")
            else:
                print(f"\n⚠️  状态不符合预期，期望: {test_case['expected_status']}")
                
        except Exception as e:
            print(f"\n❌ 测试异常: {e}")
            import traceback
            traceback.print_exc()
        
        if i < len(test_cases):
            print(f"\n{'─'*70}")
            # 支持非交互模式
            import os
            if os.environ.get('NON_INTERACTIVE') != '1':
                input("按 Enter 继续下一个测试...")
            else:
                print("自动继续下一个测试...")


def main():
    """主函数"""
    print("🚀 完整流程测试")
    print("="*70)
    
    db = next(get_db())
    
    try:
        # 1. 创建测试文档
        doc_id, user_id = create_simple_test_document(db)
        
        # 2. 运行完整流程测试
        print(f"\n{'='*70}")
        print("开始完整流程测试")
        print(f"{'='*70}")
        
        test_complete_workflow(db, doc_id, user_id)
        
        print(f"\n{'='*70}")
        print("✅ 所有测试完成！")
        print(f"{'='*70}")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        db.close()


if __name__ == "__main__":
    main()
