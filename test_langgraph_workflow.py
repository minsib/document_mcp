"""
LangGraph 工作流测试
测试重构后的智能体架构
"""
import pytest
from sqlalchemy.orm import Session
from app.services.langgraph_workflow import LangGraphWorkflowExecutor
from app.db.connection import get_db
import uuid


class TestLangGraphWorkflow:
    """测试 LangGraph 工作流"""
    
    @pytest.fixture
    def db(self):
        """获取数据库会话"""
        db = next(get_db())
        yield db
        db.close()
    
    @pytest.fixture
    def test_doc_id(self, db):
        """创建测试文档"""
        from app.models import database as db_models
        from app.services.splitter import BlockSplitter
        
        # 创建测试文档
        doc = db_models.Document(
            id=uuid.uuid4(),
            title="测试文档",
            user_id=uuid.uuid4()
        )
        db.add(doc)
        db.flush()
        
        # 创建初始版本
        rev = db_models.DocumentRevision(
            id=uuid.uuid4(),
            doc_id=doc.id,
            version=1,
            change_summary="初始版本"
        )
        db.add(rev)
        db.flush()
        
        # 分块并保存
        test_content = """# 项目需求文档

## 1. 项目背景

本项目旨在开发一个创新的文档编辑系统，允许用户通过自然语言对话的方式修改文档内容。

## 2. 核心功能

系统支持以下核心功能：
- 对话式编辑
- 精准定位
- 版本管理

## 3. 技术架构

系统采用 FastAPI + PostgreSQL + LangGraph 架构。
"""
        
        splitter = BlockSplitter()
        blocks = splitter.split_document(test_content)
        
        for block_data in blocks:
            block = db_models.Block(id=block_data.block_id)
            db.add(block)
            
            block_version = db_models.BlockVersion(
                id=uuid.uuid4(),
                block_id=block_data.block_id,
                rev_id=rev.id,
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
            doc_id=doc.id,
            rev_id=rev.id,
            version=1
        )
        db.add(active_rev)
        
        db.commit()
        
        return str(doc.id)
    
    def test_intent_parsing(self, db, test_doc_id):
        """测试意图解析"""
        executor = LangGraphWorkflowExecutor(db)
        
        result = executor.execute(
            doc_id=test_doc_id,
            session_id="test_session_1",
            user_id=str(uuid.uuid4()),
            user_message="把项目背景那段改得更简洁一些"
        )
        
        print("\n=== 意图解析测试 ===")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        # 应该成功解析意图
        assert result.get("status") in ["need_confirm", "need_disambiguation", "applied"]
    
    def test_retrieval_agent(self, db, test_doc_id):
        """测试检索智能体"""
        executor = LangGraphWorkflowExecutor(db)
        
        result = executor.execute(
            doc_id=test_doc_id,
            session_id="test_session_2",
            user_id=str(uuid.uuid4()),
            user_message="找到核心功能那一段"
        )
        
        print("\n=== 检索智能体测试 ===")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        # 应该找到目标
        assert result.get("status") in ["need_confirm", "need_disambiguation", "applied"]
    
    def test_clarification_flow(self, db, test_doc_id):
        """测试澄清流程"""
        executor = LangGraphWorkflowExecutor(db)
        
        result = executor.execute(
            doc_id=test_doc_id,
            session_id="test_session_3",
            user_id=str(uuid.uuid4()),
            user_message="改一下第一段"  # 模糊请求
        )
        
        print("\n=== 澄清流程测试 ===")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        # 可能需要澄清
        assert result.get("status") in ["need_clarification", "need_confirm", "need_disambiguation", "applied"]
    
    def test_full_edit_workflow(self, db, test_doc_id):
        """测试完整编辑流程"""
        executor = LangGraphWorkflowExecutor(db)
        
        result = executor.execute(
            doc_id=test_doc_id,
            session_id="test_session_4",
            user_id=str(uuid.uuid4()),
            user_message="把技术架构那段的 FastAPI 改成 Django"
        )
        
        print("\n=== 完整编辑流程测试 ===")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        if result.get("status") == "need_confirm":
            print("\n预览:")
            preview = result.get("preview", {})
            for diff in preview.get("diffs", []):
                print(f"  - 块 ID: {diff.get('block_id')}")
                print(f"    修改前: {diff.get('before_snippet')}")
                print(f"    修改后: {diff.get('after_snippet')}")
        
        # 应该生成预览或直接应用
        assert result.get("status") in ["need_confirm", "applied"]
    
    def test_disambiguation_flow(self, db, test_doc_id):
        """测试消歧流程"""
        executor = LangGraphWorkflowExecutor(db)
        
        result = executor.execute(
            doc_id=test_doc_id,
            session_id="test_session_5",
            user_id=str(uuid.uuid4()),
            user_message="修改第一段"  # 可能有多个"第一段"
        )
        
        print("\n=== 消歧流程测试 ===")
        print(f"状态: {result.get('status')}")
        print(f"消息: {result.get('message')}")
        
        if result.get("status") == "need_disambiguation":
            print("\n候选:")
            for candidate in result.get("candidates", []):
                print(f"  - {candidate.get('heading_context')}: {candidate.get('snippet')[:50]}...")
        
        # 可能需要消歧
        assert result.get("status") in ["need_disambiguation", "need_confirm", "applied"]


if __name__ == "__main__":
    """直接运行测试"""
    import sys
    sys.path.insert(0, ".")
    
    from app.db.connection import get_db
    
    db = next(get_db())
    test = TestLangGraphWorkflow()
    
    # 创建测试文档
    test_doc_id = test.test_doc_id(db)
    print(f"测试文档 ID: {test_doc_id}")
    
    # 运行测试
    try:
        test.test_intent_parsing(db, test_doc_id)
        test.test_retrieval_agent(db, test_doc_id)
        test.test_clarification_flow(db, test_doc_id)
        test.test_full_edit_workflow(db, test_doc_id)
        test.test_disambiguation_flow(db, test_doc_id)
        
        print("\n✅ 所有测试通过！")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
