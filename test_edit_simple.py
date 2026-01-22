#!/usr/bin/env python3
"""
简单的编辑测试
"""
import requests
import json

BASE_URL = "http://localhost:8001"


def test_simple_edit():
    """测试简单的编辑操作"""
    print("=" * 60)
    print("测试简单编辑")
    print("=" * 60)
    
    # 1. 上传文档
    print("\n1. 上传文档...")
    content = """# 测试文档

## 项目背景

这是一个测试项目，用于验证文档编辑功能。

## 核心功能

系统支持以下功能：
- 文档上传
- 内容编辑
- 版本管理

## 技术架构

采用 FastAPI + PostgreSQL 架构。
"""
    
    response = requests.post(
        f"{BASE_URL}/v1/docs/upload",
        data={
            "title": "测试文档",
            "content": content
        }
    )
    
    result = response.json()
    doc_id = result["doc_id"]
    print(f"✓ 文档已上传: {doc_id}")
    print(f"  块数量: {result['block_count']}")
    
    # 2. 测试编辑 - 查找项目背景
    print("\n2. 测试编辑 - 查找'项目背景'...")
    response = requests.post(
        f"{BASE_URL}/v1/chat/edit",
        json={
            "doc_id": doc_id,
            "message": "找到项目背景那一段"
        }
    )
    
    result = response.json()
    print(f"状态: {result['status']}")
    print(f"消息: {result['message']}")
    
    if result['status'] == 'need_disambiguation':
        print(f"候选数量: {len(result.get('candidates', []))}")
        for i, candidate in enumerate(result.get('candidates', [])[:3]):
            print(f"\n候选 {i+1}:")
            print(f"  章节: {candidate['heading_context']}")
            print(f"  内容: {candidate['snippet'][:100]}...")
    
    # 3. 测试编辑 - 修改内容
    print("\n3. 测试编辑 - 修改'项目背景'...")
    response = requests.post(
        f"{BASE_URL}/v1/chat/edit",
        json={
            "doc_id": doc_id,
            "message": "把项目背景改成：这是一个创新的文档编辑系统"
        }
    )
    
    result = response.json()
    print(f"状态: {result['status']}")
    print(f"消息: {result['message']}")
    
    if result['status'] == 'need_confirm':
        print(f"\n预览:")
        for diff in result['preview']['diffs']:
            print(f"  操作: {diff['op_type']}")
            print(f"  章节: {diff['heading_context']}")
            print(f"  修改前: {diff['before_snippet'][:80]}...")
            print(f"  修改后: {diff['after_snippet'][:80]}...")
    
    elif result['status'] == 'applied':
        print(f"✓ 修改已应用")
        print(f"  新版本: {result['new_rev_id']}")
    
    elif result['status'] == 'failed':
        print(f"✗ 修改失败")
        if result.get('error'):
            print(f"  错误: {result['error']}")
    
    # 4. 导出文档
    print("\n4. 导出文档...")
    response = requests.get(f"{BASE_URL}/v1/docs/{doc_id}/export")
    result = response.json()
    
    print(f"导出内容:")
    print("-" * 60)
    print(result['content'])
    print("-" * 60)
    
    print("\n✅ 测试完成！")


if __name__ == "__main__":
    test_simple_edit()
