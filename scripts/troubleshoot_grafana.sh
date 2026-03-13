#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "Grafana 故障排查脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
    fi
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 1. 检查容器状态
echo ""
echo "1. 检查容器状态"
echo "----------------------------------------"
if docker ps | grep -q document_edit_grafana; then
    print_status 0 "Grafana 容器正在运行"
else
    print_status 1 "Grafana 容器未运行"
    echo "   请运行: docker-compose up -d grafana"
    exit 1
fi

if docker ps | grep -q document_edit_prometheus; then
    print_status 0 "Prometheus 容器正在运行"
else
    print_status 1 "Prometheus 容器未运行"
    exit 1
fi

# 2. 检查 Grafana 健康状态
echo ""
echo "2. 检查 Grafana 健康状态"
echo "----------------------------------------"
if curl -s http://localhost:3000/api/health | grep -q "ok"; then
    print_status 0 "Grafana 健康检查通过"
else
    print_status 1 "Grafana 健康检查失败"
fi

# 3. 检查 Prometheus 健康状态
echo ""
echo "3. 检查 Prometheus 健康状态"
echo "----------------------------------------"
if curl -s http://localhost:9090/-/healthy | grep -q "Prometheus"; then
    print_status 0 "Prometheus 健康检查通过"
else
    print_status 1 "Prometheus 健康检查失败"
fi

# 4. 检查 Prometheus 目标
echo ""
echo "4. 检查 Prometheus 目标"
echo "----------------------------------------"
targets=$(curl -s http://localhost:9090/api/v1/targets | python3 -c "
import sys, json
data = json.load(sys.stdin)
for target in data['data']['activeTargets']:
    job = target['labels']['job']
    health = target['health']
    print(f'{job}: {health}')
")
echo "$targets"

if echo "$targets" | grep -q "document-edit-system: up"; then
    print_status 0 "API 目标状态正常"
else
    print_status 1 "API 目标状态异常"
fi

# 5. 检查是否有数据
echo ""
echo "5. 检查 Prometheus 数据"
echo "----------------------------------------"
result=$(curl -s 'http://localhost:9090/api/v1/query?query=up' | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(len(data['data']['result']))
")

if [ "$result" -gt 0 ]; then
    print_status 0 "Prometheus 有 $result 个指标"
else
    print_status 1 "Prometheus 没有数据"
fi

# 6. 检查业务指标
echo ""
echo "6. 检查业务指标"
echo "----------------------------------------"
metrics=(
    "documents_uploaded_total"
    "edits_requested_total"
    "workflow_runs_total"
)

for metric in "${metrics[@]}"; do
    result=$(curl -s "http://localhost:9090/api/v1/query?query=$metric" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    count = len(data['data']['result'])
    if count > 0:
        print('found')
    else:
        print('empty')
except:
    print('error')
")
    
    if [ "$result" = "found" ]; then
        print_status 0 "$metric 有数据"
    elif [ "$result" = "empty" ]; then
        print_warning "$metric 没有数据（可能还没有操作）"
    else
        print_status 1 "$metric 查询失败"
    fi
done

# 7. 检查 Grafana 数据源
echo ""
echo "7. 检查 Grafana 数据源配置"
echo "----------------------------------------"
docker exec document_edit_grafana ls -la /etc/grafana/provisioning/datasources/ 2>/dev/null
if [ $? -eq 0 ]; then
    print_status 0 "数据源配置文件存在"
else
    print_status 1 "数据源配置文件不存在"
fi

# 8. 检查 Grafana 日志
echo ""
echo "8. 检查 Grafana 日志（最后 20 行）"
echo "----------------------------------------"
docker logs document_edit_grafana --tail 20 2>&1 | grep -i "error\|warn" || echo "没有错误或警告"

# 9. 测试从 Grafana 容器访问 Prometheus
echo ""
echo "9. 测试 Grafana → Prometheus 连接"
echo "----------------------------------------"
if docker exec document_edit_grafana wget -q -O- http://prometheus:9090/api/v1/query?query=up 2>/dev/null | grep -q "success"; then
    print_status 0 "Grafana 可以访问 Prometheus"
else
    print_status 1 "Grafana 无法访问 Prometheus"
    print_warning "检查 Docker 网络配置"
fi

# 10. 生成测试数据
echo ""
echo "10. 生成测试数据"
echo "----------------------------------------"
echo "正在生成测试流量..."

docker exec -i document_edit_api python3 << 'PYTHON_SCRIPT'
import requests
import time
import uuid

BASE_URL = 'http://localhost:8000'

try:
    # 注册用户
    username = f'test_{int(time.time())}'
    resp = requests.post(
        f'{BASE_URL}/v1/auth/register',
        json={'username': username, 'email': f'{username}@test.com', 'password': 'Test123456!'}
    )
    
    # 登录
    resp = requests.post(
        f'{BASE_URL}/v1/auth/login',
        json={'username': username, 'password': 'Test123456!'}
    )
    token = resp.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    
    # 上传文档
    resp = requests.post(
        f'{BASE_URL}/v1/docs/upload',
        headers=headers,
        data={'title': 'Test', 'content': '# Test\n\n## Section\nContent here.'}
    )
    doc_id = resp.json()['doc_id']
    
    # 编辑请求
    for i in range(3):
        session_id = f'sess_{uuid.uuid4().hex[:8]}'
        requests.post(
            f'{BASE_URL}/v1/chat/edit',
            headers=headers,
            json={'doc_id': doc_id, 'session_id': session_id, 'message': f'把Content改成NewContent{i}'}
        )
        time.sleep(0.2)
    
    print("✅ 成功生成 3 次编辑请求")
except Exception as e:
    print(f"❌ 生成测试数据失败: {e}")
PYTHON_SCRIPT

# 11. 再次检查指标
echo ""
echo "11. 再次检查指标（等待 15 秒让 Prometheus 抓取）"
echo "----------------------------------------"
sleep 15

result=$(curl -s 'http://localhost:9090/api/v1/query?query=edits_requested_total' | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    results = data['data']['result']
    if results:
        total = sum(float(r['value'][1]) for r in results)
        print(f'{int(total)}')
    else:
        print('0')
except:
    print('error')
")

if [ "$result" != "0" ] && [ "$result" != "error" ]; then
    print_status 0 "检测到 $result 次编辑请求"
else
    print_warning "还没有检测到编辑请求"
fi

# 总结
echo ""
echo "=========================================="
echo "故障排查完成"
echo "=========================================="
echo ""
echo "📊 访问 Grafana:"
echo "   URL: http://localhost:3000"
echo "   用户名: admin"
echo "   密码: admin"
echo ""
echo "🔍 如果 Dashboard 还是没有数据，请检查:"
echo "   1. Dashboard 的时间范围（右上角）- 建议选择 'Last 15 minutes'"
echo "   2. Dashboard 的数据源是否选择了 'Prometheus'"
echo "   3. 查询语句是否正确"
echo ""
echo "💡 推荐的查询语句:"
echo "   - up"
echo "   - rate(edits_requested_total[5m])"
echo "   - sum(rate(edits_requested_total[5m])) by (operation_type)"
echo ""
