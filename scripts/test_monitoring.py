#!/usr/bin/env python3
"""
监控数据生成测试脚本
用于生成各种 API 请求，让 Grafana 面板显示数据
"""
import requests
import time
import random
import json
from typing import Dict, Any

# API 基础 URL
BASE_URL = "http://localhost:8001"

# 测试用户凭证
TEST_USER = {
    "username": "test_monitor_user",
    "email": "monitor@test.com",
    "password": "test123456"
}


def print_step(step: str):
    """打印步骤信息"""
    print(f"\n{'='*60}")
    print(f"📊 {step}")
    print(f"{'='*60}")


def check_health():
    """检查健康状态"""
    print_step("检查系统健康状态")
    try:
        response = requests.get(f"{BASE_URL}/health/")
        print(f"✅ 健康检查: {response.status_code}")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
        return False


def check_metrics():
    """检查 metrics 端点"""
    print_step("检查 Prometheus Metrics")
    try:
        response = requests.get(f"{BASE_URL}/metrics")
        print(f"✅ Metrics 端点: {response.status_code}")
        lines = response.text.split('\n')
        print(f"📈 指标数量: {len([l for l in lines if l and not l.startswith('#')])}")
        
        # 显示一些关键指标
        print("\n关键指标示例:")
        for line in lines[:30]:
            if line and not line.startswith('#'):
                print(f"  {line}")
        return True
    except Exception as e:
        print(f"❌ Metrics 检查失败: {e}")
        return False


def register_user() -> Dict[str, Any]:
    """注册测试用户"""
    print_step("注册测试用户")
    try:
        response = requests.post(
            f"{BASE_URL}/v1/auth/register",
            json=TEST_USER
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 用户注册成功: {data.get('user_id')}")
            return data
        elif response.status_code == 400 and "already exists" in response.text:
            print(f"ℹ️  用户已存在，尝试登录")
            return login_user()
        else:
            print(f"❌ 注册失败: {response.status_code} - {response.text}")
            return {}
    except Exception as e:
        print(f"❌ 注册异常: {e}")
        return {}


def login_user() -> Dict[str, Any]:
    """登录用户"""
    print_step("用户登录")
    try:
        response = requests.post(
            f"{BASE_URL}/v1/auth/login",
            data={
                "username": TEST_USER["username"],
                "password": TEST_USER["password"]
            }
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 登录成功")
            print(f"   Token: {data.get('access_token')[:50]}...")
            return data
        else:
            print(f"❌ 登录失败: {response.status_code} - {response.text}")
            return {}
    except Exception as e:
        print(f"❌ 登录异常: {e}")
        return {}


def upload_document(token: str) -> str:
    """上传测试文档"""
    print_step("上传测试文档")
    
    test_content = """# 测试文档

## 第一章：产品介绍

我们的产品具有高性能、易用性和可扩展性三大特点。

## 第二章：技术架构

系统采用微服务架构，使用 Python 和 FastAPI 开发。

## 第三章：价格方案

基础版每月 99 元，专业版每月 299 元。

## 第四章：联系方式

如有问题，请联系我们的客服团队。
"""
    
    try:
        response = requests.post(
            f"{BASE_URL}/v1/docs/upload",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "title": f"监控测试文档_{int(time.time())}",
                "content": test_content
            }
        )
        if response.status_code == 200:
            data = response.json()
            doc_id = data.get('doc_id')
            print(f"✅ 文档上传成功")
            print(f"   文档 ID: {doc_id}")
            print(f"   块数量: {data.get('block_count')}")
            return doc_id
        else:
            print(f"❌ 上传失败: {response.status_code} - {response.text}")
            return ""
    except Exception as e:
        print(f"❌ 上传异常: {e}")
        return ""


def perform_edit(token: str, doc_id: str, message: str) -> bool:
    """执行编辑操作"""
    print(f"\n📝 执行编辑: {message}")
    try:
        response = requests.post(
            f"{BASE_URL}/v1/docs/{doc_id}/edit",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": message}
        )
        if response.status_code == 200:
            data = response.json()
            status = data.get('status')
            print(f"   ✅ 编辑状态: {status}")
            return True
        else:
            print(f"   ❌ 编辑失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ 编辑异常: {e}")
        return False


def generate_traffic(token: str, doc_id: str, count: int = 10):
    """生成测试流量"""
    print_step(f"生成 {count} 次测试请求")
    
    edit_messages = [
        "把'高性能'改成'超高性能'",
        "把'易用性'改成'简单易用'",
        "把'可扩展性'改成'灵活扩展'",
        "把'微服务架构'改成'分布式架构'",
        "把'Python'改成'Python 3.11'",
        "把'FastAPI'改成'FastAPI 框架'",
        "把'99 元'改成'199 元'",
        "把'299 元'改成'399 元'",
        "把'客服团队'改成'技术支持团队'",
        "把'联系方式'改成'联系我们'",
    ]
    
    success_count = 0
    fail_count = 0
    
    for i in range(count):
        message = random.choice(edit_messages)
        print(f"\n[{i+1}/{count}] ", end="")
        
        if perform_edit(token, doc_id, message):
            success_count += 1
        else:
            fail_count += 1
        
        # 随机延迟，模拟真实使用
        time.sleep(random.uniform(0.5, 2.0))
    
    print(f"\n\n📊 测试结果:")
    print(f"   ✅ 成功: {success_count}")
    print(f"   ❌ 失败: {fail_count}")
    print(f"   📈 成功率: {success_count/count*100:.1f}%")


def export_document(token: str, doc_id: str):
    """导出文档"""
    print_step("导出文档")
    try:
        response = requests.get(
            f"{BASE_URL}/v1/docs/{doc_id}/export",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 文档导出成功")
            print(f"   内容长度: {len(data.get('content', ''))} 字符")
            return True
        else:
            print(f"❌ 导出失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 导出异常: {e}")
        return False


def list_documents(token: str):
    """列出文档"""
    print_step("列出文档")
    try:
        response = requests.get(
            f"{BASE_URL}/v1/docs/",
            headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            docs = data.get('documents', [])
            print(f"✅ 文档列表获取成功")
            print(f"   文档数量: {len(docs)}")
            return True
        else:
            print(f"❌ 获取失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 获取异常: {e}")
        return False


def main():
    """主函数"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║          📊 监控数据生成测试脚本                              ║
║                                                              ║
║  此脚本会生成各种 API 请求，让 Grafana 面板显示数据           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # 1. 检查系统健康
    if not check_health():
        print("\n❌ 系统未就绪，请先启动服务")
        print("   运行: docker-compose up -d")
        return
    
    # 2. 检查 metrics 端点
    if not check_metrics():
        print("\n❌ Metrics 端点不可用")
        return
    
    # 3. 注册/登录用户
    auth_data = register_user()
    if not auth_data:
        auth_data = login_user()
    
    if not auth_data or 'access_token' not in auth_data:
        print("\n❌ 无法获取访问令牌")
        return
    
    token = auth_data['access_token']
    
    # 4. 上传文档
    doc_id = upload_document(token)
    if not doc_id:
        print("\n❌ 无法上传文档")
        return
    
    # 5. 生成测试流量
    generate_traffic(token, doc_id, count=20)
    
    # 6. 导出文档
    export_document(token, doc_id)
    
    # 7. 列出文档
    list_documents(token)
    
    # 8. 再次检查 metrics
    print_step("查看最新 Metrics")
    check_metrics()
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║  ✅ 测试完成！                                                ║
║                                                              ║
║  现在可以在 Grafana 中查看数据了：                            ║
║  http://localhost:3000                                       ║
║                                                              ║
║  建议的查询：                                                 ║
║  - rate(request_duration_seconds_count[5m])                  ║
║  - rate(edits_requested_total[5m])                           ║
║  - histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m])) ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
