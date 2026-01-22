#!/usr/bin/env python3
"""
测试向量检索功能

运行前确保：
1. 已运行 scripts/add_vector_support.py
2. 已上传测试文档
3. 已生成 embeddings
"""
import sys
import requests
import json

API_BASE = "http://localhost:8001"


def test_vector_search():
    """测试向量检索"""
    print("🧪 测试向量检索功能\n")
    
    # 1. 上传测试文档
    print("1️⃣ 上传测试文档...")
    with open("test_document.md", "r", encoding="utf-8") as f:
        content = f.read()
    
    files = {
        'file': ('test.md', content.encode('utf-8'), 'text/markdown')
    }
    data = {
        'title': '向量检索测试文档'
    }
    
    response = requests.post(f"{API_BASE}/v1/docs/upload", files=files, data=data)
    
    if response.status_code != 200:
        print(f"❌ 上传失败: {response.text}")
        return
    
    result = response.json()
    doc_id = result['doc_id']
    print(f"✅ 文档已上传: {doc_id}\n")
    
    # 2. 等待 embeddings 生成
    print("2️⃣ 等待 embeddings 生成（约 5-10 秒）...")
    import time
    time.sleep(10)
    print("✅ 完成\n")
    
    # 3. 测试语义搜索
    print("3️⃣ 测试语义搜索...")
    
    test_queries = [
        {
            "query": "关于项目背景的内容",
            "expected": "应该找到项目背景相关段落"
        },
        {
            "query": "技术架构是什么",
            "expected": "应该找到技术架构相关段落"
        },
        {
            "query": "如何部署",
            "expected": "应该找到部署相关段落"
        }
    ]
    
    for i, test in enumerate(test_queries, 1):
        print(f"\n   测试 {i}: {test['query']}")
        print(f"   期望: {test['expected']}")
        
        # 创建会话
        session_response = requests.post(
            f"{API_BASE}/v1/chat/sessions",
            json={
                "doc_id": doc_id,
                "user_id": "test-user"
            }
        )
        
        if session_response.status_code != 200:
            print(f"   ❌ 创建会话失败: {session_response.text}")
            continue
        
        session_id = session_response.json()['session_id']
        
        # 发送查询
        edit_response = requests.post(
            f"{API_BASE}/v1/chat/edit",
            json={
                "session_id": session_id,
                "doc_id": doc_id,
                "message": f"找到{test['query']}"
            }
        )
        
        if edit_response.status_code != 200:
            print(f"   ❌ 查询失败: {edit_response.text}")
            continue
        
        result = edit_response.json()
        
        if result.get('status') == 'need_disambiguation':
            candidates = result.get('candidates', [])
            print(f"   ✅ 找到 {len(candidates)} 个候选:")
            for j, candidate in enumerate(candidates[:3], 1):
                print(f"      {j}. [{candidate['heading_context']}] {candidate['snippet'][:50]}...")
        else:
            print(f"   ⚠️ 状态: {result.get('status')}")
    
    print("\n4️⃣ 测试完成！")
    print("\n📊 检查向量检索是否生效:")
    print("   - 如果能找到语义相关的段落（即使关键词不完全匹配），说明向量检索工作正常")
    print("   - 如果只能找到关键词完全匹配的段落，说明可能降级到了 BM25 搜索")
    print("\n💡 提示:")
    print("   - 查看 API 日志中是否有 '混合检索' 或 '向量检索' 相关信息")
    print("   - 运行 'psql -c \"SELECT COUNT(*) FROM block_versions WHERE embedding IS NOT NULL;\"' 检查 embeddings")


if __name__ == "__main__":
    try:
        test_vector_search()
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
