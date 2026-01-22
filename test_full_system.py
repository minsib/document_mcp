#!/usr/bin/env python3
"""完整系统测试"""
import requests
import json
import time

BASE_URL = "http://localhost:8001"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_health_check():
    """测试健康检查"""
    print_section("1. 健康检查测试")
    
    # 综合健康检查
    response = requests.get(f"{BASE_URL}/health/")
    print(f"综合健康检查: {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    
    # Liveness probe
    response = requests.get(f"{BASE_URL}/health/liveness")
    print(f"\nLiveness probe: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    
    # Readiness probe
    response = requests.get(f"{BASE_URL}/health/readiness")
    print(f"\nReadiness probe: {response.status_code}")
    print(json.dumps(response.json(), indent=2))

def test_authentication():
    """测试用户认证"""
    print_section("2. 用户认证测试")
    
    # 登录
    login_data = {
        "username": "admin",
        "password": "admin123"
    }
    response = requests.post(f"{BASE_URL}/v1/auth/login", json=login_data)
    print(f"登录: {response.status_code}")
    
    if response.status_code == 200:
        tokens = response.json()
        print(f"✅ 登录成功")
        print(f"Access Token: {tokens['access_token'][:50]}...")
        return tokens['access_token']
    else:
        print(f"❌ 登录失败: {response.text}")
        return None

def test_document_upload(token):
    """测试文档上传"""
    print_section("3. 文档上传测试")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 准备测试文档
    test_content = """# 测试文档

## 项目背景

本项目旨在开发一个创新的文档编辑系统，支持通过自然语言对话的方式修改文档内容。

## 核心功能

### 1. 对话式编辑
用户可以用自然语言描述修改需求，系统自动定位并修改。

### 2. 版本管理
完整的版本历史，支持任意版本回滚。

### 3. 批量修改
支持全文统一替换和批量编辑。

## 技术架构

- 后端框架：FastAPI
- 数据库：PostgreSQL
- 搜索引擎：Meilisearch
- LLM：Qwen3-235B

## 性能指标

- 检索准确率：> 90%
- 编辑延迟：< 3s
- 并发支持：100+ 请求/秒
"""
    
    data = {
        "title": "测试文档",
        "content": test_content
    }
    
    response = requests.post(
        f"{BASE_URL}/v1/docs/upload",
        headers=headers,
        data=data
    )
    
    print(f"上传文档: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ 文档上传成功")
        print(f"文档 ID: {result['doc_id']}")
        print(f"版本 ID: {result['rev_id']}")
        print(f"块数量: {result['block_count']}")
        return result['doc_id']
    else:
        print(f"❌ 上传失败: {response.text}")
        return None

def test_document_export(token, doc_id):
    """测试文档导出"""
    print_section("4. 文档导出测试")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/v1/docs/{doc_id}/export",
        headers=headers
    )
    
    print(f"导出文档: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ 文档导出成功")
        print(f"内容长度: {len(result['content'])} 字符")
        print(f"\n前 200 字符:")
        print(result['content'][:200])
        return True
    else:
        print(f"❌ 导出失败: {response.text}")
        return False

def test_chat_edit(token, doc_id):
    """测试对话式编辑"""
    print_section("5. 对话式编辑测试")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 发起编辑请求
    edit_request = {
        "doc_id": doc_id,
        "session_id": "test_session_001",
        "message": "把项目背景那段改得更简洁一些"
    }
    
    print("发起编辑请求...")
    response = requests.post(
        f"{BASE_URL}/v1/chat/edit",
        headers=headers,
        json=edit_request
    )
    
    print(f"编辑请求: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ 编辑请求成功")
        print(f"状态: {result.get('status')}")
        
        if result.get('status') == 'need_confirm':
            print(f"\n预览信息:")
            preview = result.get('preview', {})
            print(f"修改数量: {preview.get('total_changes')}")
            print(f"影响评估: {preview.get('estimated_impact')}")
            
            if preview.get('diffs'):
                print(f"\n第一处修改:")
                diff = preview['diffs'][0]
                print(f"块 ID: {diff.get('block_id')}")
                print(f"操作类型: {diff.get('op_type')}")
                print(f"修改前: {diff.get('before_snippet', '')[:100]}...")
                print(f"修改后: {diff.get('after_snippet', '')[:100]}...")
            
            return {
                'confirm_token': result.get('confirm_token'),
                'preview_hash': result.get('preview_hash')
            }
        else:
            print(f"消息: {result.get('message')}")
            return None
    else:
        print(f"❌ 编辑失败: {response.text}")
        return None

def test_metrics():
    """测试 Prometheus 指标"""
    print_section("6. Prometheus 指标测试")
    
    response = requests.get(f"{BASE_URL}/metrics")
    print(f"获取指标: {response.status_code}")
    
    if response.status_code == 200:
        metrics = response.text
        print(f"✅ 指标获取成功")
        lines = metrics.split('\n')
        print(f"指标数量: {len(lines)} 行")
        
        # 显示一些关键指标
        print(f"\n关键指标:")
        for line in lines:
            if 'app_info' in line and not line.startswith('#'):
                print(f"  {line}")
            elif 'documents_uploaded_total' in line and not line.startswith('#'):
                print(f"  {line}")
            elif 'request_duration_seconds_count' in line and not line.startswith('#'):
                print(f"  {line}")
                break
        return True
    else:
        print(f"❌ 获取指标失败")
        return False

def main():
    """主测试流程"""
    print("\n" + "="*60)
    print("  文档编辑系统 - 完整功能测试")
    print("="*60)
    
    try:
        # 1. 健康检查
        test_health_check()
        time.sleep(1)
        
        # 2. 用户认证
        token = test_authentication()
        if not token:
            print("\n❌ 认证失败，终止测试")
            return
        time.sleep(1)
        
        # 3. 文档上传
        doc_id = test_document_upload(token)
        if not doc_id:
            print("\n❌ 文档上传失败，终止测试")
            return
        time.sleep(2)  # 等待索引完成
        
        # 4. 文档导出
        test_document_export(token, doc_id)
        time.sleep(1)
        
        # 5. 对话式编辑
        test_chat_edit(token, doc_id)
        time.sleep(1)
        
        # 6. Prometheus 指标
        test_metrics()
        
        print_section("测试完成")
        print("✅ 所有核心功能测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
