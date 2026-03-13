#!/usr/bin/env python3
"""
测试工作流调试
"""
import sys
sys.path.insert(0, '/app')

from app.db.connection import get_db
from app.services.langgraph_workflow import LangGraphWorkflowExecutor

# 获取数据库会话
db = next(get_db())

# 创建工作流执行器
executor = LangGraphWorkflowExecutor(db)

# 执行工作流
result = executor.execute(
    doc_id="324003c6-3fbf-4727-963a-1192c8a5fece",
    session_id="test-session",
    user_id="test-user",
    user_message="将第一章的标题改为'系统概述'"
)

print("结果:")
print(result)
