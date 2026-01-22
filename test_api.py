#!/usr/bin/env python3
"""
测试 API 的简单脚本
"""
import requests
import json

BASE_URL = "http://localhost:8001"


def test_health():
    """测试健康检查"""
    print("Testing health check...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()


def test_upload():
    """测试文档上传"""
    print("Testing document upload...")
    
    # 读取测试文档
    with open("test_document.md", "r", encoding="utf-8") as f:
        content = f.read()
    
    # 上传文档
    response = requests.post(
        f"{BASE_URL}/v1/docs/upload",
        data={
            "title": "项目需求文档",
            "content": content
        }
    )
    
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
    print()
    
    return result.get("doc_id"), result.get("rev_id")


def test_export(doc_id):
    """测试文档导出"""
    print(f"Testing document export for doc_id: {doc_id}...")
    
    response = requests.get(f"{BASE_URL}/v1/docs/{doc_id}/export")
    
    print(f"Status: {response.status_code}")
    result = response.json()
    
    # 只打印前 500 个字符
    content = result.get("content", "")
    print(f"Content preview (first 500 chars):")
    print(content[:500])
    print("...")
    print()
    
    return result


def main():
    print("=" * 60)
    print("Document Edit System - API Test")
    print("=" * 60)
    print()
    
    # 测试健康检查
    test_health()
    
    # 测试上传
    doc_id, rev_id = test_upload()
    
    if doc_id:
        # 测试导出
        test_export(doc_id)
    
    print("=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
