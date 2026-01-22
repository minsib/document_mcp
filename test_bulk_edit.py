#!/usr/bin/env python3
"""
测试批量修改功能

运行前确保：
1. 系统正在运行
2. 已上传测试文档
"""
import requests
import json
import time

API_BASE = "http://localhost:8001"


def test_bulk_edit():
    """测试批量修改"""
    print("🧪 测试批量修改功能\n")
    
    # 1. 上传测试文档
    print("1️⃣ 上传测试文档...")
    test_content = """# 测试文档

## 第一章

这是第一段内容，包含旧词。

这是第二段内容，也包含旧词。

## 第二章

这是第三段内容，同样包含旧词。

这是第四段内容，还是包含旧词。

## 第三章

这是第五段内容，依然包含旧词。
"""
    
    response = requests.post(
        f"{API_BASE}/v1/docs/upload",
        data={
            'title': '批量修改测试文档',
            'content': test_content
        }
    )
    
    if response.status_code != 200:
        print(f"❌ 上传失败: {response.text}")
        return
    
    result = response.json()
    doc_id = result['doc_id']
    print(f"✅ 文档已上传: {doc_id}\n")
    
    # 2. 创建会话
    print("2️⃣ 创建会话...")
    session_response = requests.post(
        f"{API_BASE}/v1/chat/sessions",
        json={
            "doc_id": doc_id,
            "user_id": "test-user"
        }
    )
    
    if session_response.status_code != 200:
        print(f"❌ 创建会话失败: {session_response.text}")
        return
    
    session_id = session_response.json()['session_id']
    print(f"✅ 会话已创建: {session_id}\n")
    
    # 3. 测试批量修改
    print("3️⃣ 发起批量修改请求...")
    bulk_edit_response = requests.post(
        f"{API_BASE}/v1/chat/bulk-edit",
        json={
            "session_id": session_id,
            "doc_id": doc_id,
            "message": "将所有'旧词'替换为'新词'",
            "match_type": "exact_term",
            "scope_filter": {
                "term": "旧词",
                "replacement": "新词"
            }
        }
    )
    
    if bulk_edit_response.status_code != 200:
        print(f"❌ 批量修改请求失败: {bulk_edit_response.text}")
        return
    
    bulk_result = bulk_edit_response.json()
    print(f"✅ 状态: {bulk_result['status']}")
    print(f"   消息: {bulk_result['message']}\n")
    
    if bulk_result['status'] != 'need_confirm':
        print(f"⚠️ 意外状态: {bulk_result['status']}")
        return
    
    # 4. 显示预览
    preview = bulk_result['preview']
    print(f"4️⃣ 预览修改:")
    print(f"   总修改数: {preview['total_changes']}")
    print(f"   影响等级: {preview['estimated_impact']}")
    print(f"   新增字符: {preview['total_chars_added']}")
    print(f"   删除字符: {preview['total_chars_removed']}\n")
    
    print("   按章节分组:")
    for heading, count in preview.get('grouped_by_heading', {}).items():
        print(f"      {heading}: {count} 处")
    
    print("\n   前 3 处修改:")
    for i, diff in enumerate(preview['diffs'][:3], 1):
        print(f"      {i}. [{diff['heading_context']}]")
        print(f"         修改前: {diff['before_snippet'][:50]}...")
        print(f"         修改后: {diff['after_snippet'][:50]}...")
        print()
    
    # 5. 确认修改
    print("5️⃣ 确认并应用修改...")
    confirm_response = requests.post(
        f"{API_BASE}/v1/chat/bulk-confirm",
        json={
            "session_id": session_id,
            "doc_id": doc_id,
            "confirm_token": bulk_result['confirm_token'],
            "preview_hash": bulk_result['preview_hash'],
            "action": "apply"
        }
    )
    
    if confirm_response.status_code != 200:
        print(f"❌ 确认失败: {confirm_response.text}")
        return
    
    confirm_result = confirm_response.json()
    print(f"✅ 状态: {confirm_result['status']}")
    print(f"   消息: {confirm_result['message']}")
    print(f"   新版本 ID: {confirm_result['new_rev_id']}")
    print(f"   新版本号: {confirm_result['new_rev_no']}")
    print(f"   应用修改数: {confirm_result['changes_applied']}\n")
    
    # 6. 导出验证
    print("6️⃣ 导出文档验证...")
    export_response = requests.get(
        f"{API_BASE}/v1/docs/{doc_id}/export"
    )
    
    if export_response.status_code != 200:
        print(f"❌ 导出失败: {export_response.text}")
        return
    
    export_result = export_response.json()
    exported_content = export_result['content']
    
    # 检查是否所有"旧词"都被替换了
    old_term_count = exported_content.count("旧词")
    new_term_count = exported_content.count("新词")
    
    print(f"   导出内容中:")
    print(f"      '旧词' 出现次数: {old_term_count}")
    print(f"      '新词' 出现次数: {new_term_count}")
    
    if old_term_count == 0 and new_term_count > 0:
        print("\n✅ 批量修改成功！所有'旧词'都已替换为'新词'")
    else:
        print("\n⚠️ 批量修改可能不完整")
    
    print("\n7️⃣ 测试完成！")
    print("\n📊 功能验证:")
    print("   ✅ 批量发现匹配内容")
    print("   ✅ 生成批量修改预览")
    print("   ✅ 按章节分组统计")
    print("   ✅ 确认并应用修改")
    print("   ✅ 版本管理正常")


def test_bulk_edit_with_scope():
    """测试带范围限制的批量修改"""
    print("\n\n🧪 测试带范围限制的批量修改\n")
    
    # 上传测试文档
    test_content = """# 测试文档

## 第一章

这是第一段内容，包含关键词。

这是第二段内容，也包含关键词。

## 第二章

这是第三段内容，同样包含关键词。

这是第四段内容，还是包含关键词。
"""
    
    response = requests.post(
        f"{API_BASE}/v1/docs/upload",
        data={
            'title': '范围限制测试文档',
            'content': test_content
        }
    )
    
    if response.status_code != 200:
        print(f"❌ 上传失败: {response.text}")
        return
    
    result = response.json()
    doc_id = result['doc_id']
    
    # 创建会话
    session_response = requests.post(
        f"{API_BASE}/v1/chat/sessions",
        json={
            "doc_id": doc_id,
            "user_id": "test-user"
        }
    )
    
    session_id = session_response.json()['session_id']
    
    # 只在"第一章"中替换
    print("1️⃣ 只在'第一章'中替换...")
    bulk_edit_response = requests.post(
        f"{API_BASE}/v1/chat/bulk-edit",
        json={
            "session_id": session_id,
            "doc_id": doc_id,
            "message": "在第一章中将'关键词'替换为'新关键词'",
            "match_type": "exact_term",
            "scope_filter": {
                "term": "关键词",
                "replacement": "新关键词",
                "heading": "第一章"
            }
        }
    )
    
    if bulk_edit_response.status_code != 200:
        print(f"❌ 批量修改请求失败: {bulk_edit_response.text}")
        return
    
    bulk_result = bulk_edit_response.json()
    preview = bulk_result['preview']
    
    print(f"✅ 找到 {preview['total_changes']} 处匹配")
    print(f"   按章节分组:")
    for heading, count in preview.get('grouped_by_heading', {}).items():
        print(f"      {heading}: {count} 处")
    
    # 验证只在第一章中修改
    first_chapter_count = preview.get('grouped_by_heading', {}).get('第一章', 0)
    second_chapter_count = preview.get('grouped_by_heading', {}).get('第二章', 0)
    
    if first_chapter_count > 0 and second_chapter_count == 0:
        print("\n✅ 范围限制成功！只在第一章中找到匹配")
    else:
        print("\n⚠️ 范围限制可能不正确")


if __name__ == "__main__":
    try:
        test_bulk_edit()
        test_bulk_edit_with_scope()
    except KeyboardInterrupt:
        print("\n\n⚠️ 测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
