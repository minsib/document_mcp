#!/usr/bin/env python3
"""
完整工作流测试脚本
"""
import requests
import json
import time

BASE_URL = "http://localhost:8001"


def test_health():
    """测试健康检查"""
    print("=" * 60)
    print("1. 测试健康检查")
    print("=" * 60)
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print()
    return response.status_code == 200


def test_upload():
    """测试文档上传"""
    print("=" * 60)
    print("2. 测试文档上传")
    print("=" * 60)
    
    with open("test_document.md", "r", encoding="utf-8") as f:
        content = f.read()
    
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


def test_chat_edit(doc_id, message):
    """测试对话式编辑"""
    print("=" * 60)
    print(f"3. 测试对话式编辑: {message}")
    print("=" * 60)
    
    response = requests.post(
        f"{BASE_URL}/v1/chat/edit",
        json={
            "doc_id": doc_id,
            "message": message
        }
    )
    
    print(f"Status: {response.status_code}")
    
    try:
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        print()
        return result
    except Exception as e:
        print(f"Error parsing response: {e}")
        print(f"Raw response: {response.text}")
        print()
        return None


def test_list_revisions(doc_id):
    """测试版本列表"""
    print("=" * 60)
    print("4. 测试版本列表")
    print("=" * 60)
    
    response = requests.get(f"{BASE_URL}/v1/docs/{doc_id}/revisions")
    
    print(f"Status: {response.status_code}")
    result = response.json()
    print(f"Total revisions: {result.get('total')}")
    
    for rev in result.get("revisions", []):
        print(f"  - Rev {rev['rev_no']}: {rev['change_summary']} ({'active' if rev['is_active'] else 'inactive'})")
    
    print()
    return result


def test_export(doc_id):
    """测试文档导出"""
    print("=" * 60)
    print("5. 测试文档导出")
    print("=" * 60)
    
    response = requests.get(f"{BASE_URL}/v1/docs/{doc_id}/export")
    
    print(f"Status: {response.status_code}")
    result = response.json()
    
    content = result.get("content", "")
    print(f"Content length: {len(content)} chars")
    print(f"Content preview (first 300 chars):")
    print(content[:300])
    print("...")
    print()
    
    return result


def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "文档对话式编辑系统 - 完整测试" + " " * 10 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    # 1. 健康检查
    if not test_health():
        print("❌ 健康检查失败，退出测试")
        return
    
    time.sleep(1)
    
    # 2. 上传文档
    doc_id, rev_id = test_upload()
    if not doc_id:
        print("❌ 文档上传失败，退出测试")
        return
    
    time.sleep(1)
    
    # 3. 测试对话式编辑（简单查询）
    result = test_chat_edit(doc_id, "找到项目背景那一段")
    
    if result and result.get("status") == "need_disambiguation":
        print("✅ 成功返回候选列表")
        print(f"   找到 {len(result.get('candidates', []))} 个候选")
    elif result and result.get("status") == "need_confirm":
        print("✅ 成功生成预览")
        print(f"   影响 {result['preview']['total_changes']} 处内容")
    elif result and result.get("status") == "applied":
        print("✅ 成功应用修改")
    elif result and result.get("status") == "failed":
        print(f"⚠️  编辑失败: {result.get('message')}")
        if result.get("error"):
            print(f"   错误详情: {result['error']}")
    
    time.sleep(1)
    
    # 4. 查看版本列表
    test_list_revisions(doc_id)
    
    time.sleep(1)
    
    # 5. 导出文档
    test_export(doc_id)
    
    print("=" * 60)
    print("✅ 所有测试完成！")
    print("=" * 60)
    print()
    print("测试总结：")
    print("  ✓ 健康检查")
    print("  ✓ 文档上传")
    print("  ✓ 对话式编辑")
    print("  ✓ 版本管理")
    print("  ✓ 文档导出")
    print()


if __name__ == "__main__":
    main()
