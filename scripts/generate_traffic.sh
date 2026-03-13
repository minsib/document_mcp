#!/bin/bash

# 监控流量生成脚本
# 快速生成 API 请求来填充 Grafana 面板

BASE_URL="http://localhost:8001"
TOKEN=""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          📊 快速生成监控流量                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# 1. 检查健康状态
echo "1️⃣  检查系统健康..."
curl -s "$BASE_URL/health/" | jq '.' || echo "❌ 健康检查失败"
echo ""

# 2. 检查 metrics
echo "2️⃣  检查 Metrics 端点..."
METRICS_COUNT=$(curl -s "$BASE_URL/metrics" | grep -v "^#" | wc -l)
echo "✅ 发现 $METRICS_COUNT 个指标"
echo ""

# 3. 注册用户
echo "3️⃣  注册测试用户..."
REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "traffic_test_user",
    "email": "traffic@test.com",
    "password": "test123456"
  }')

echo "$REGISTER_RESPONSE" | jq '.' 2>/dev/null || echo "用户可能已存在"
echo ""

# 4. 登录获取 token
echo "4️⃣  登录获取 Token..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=traffic_test_user&password=test123456")

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "❌ 无法获取 Token"
    echo "$LOGIN_RESPONSE"
    exit 1
fi

echo "✅ Token 获取成功: ${TOKEN:0:50}..."
echo ""

# 5. 上传文档
echo "5️⃣  上传测试文档..."
DOC_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/docs/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "流量测试文档",
    "content": "# 测试文档\n\n## 第一章\n\n这是测试内容。\n\n## 第二章\n\n更多测试内容。"
  }')

DOC_ID=$(echo "$DOC_RESPONSE" | jq -r '.doc_id' 2>/dev/null)

if [ -z "$DOC_ID" ] || [ "$DOC_ID" = "null" ]; then
    echo "❌ 文档上传失败"
    echo "$DOC_RESPONSE"
    exit 1
fi

echo "✅ 文档上传成功: $DOC_ID"
echo ""

# 6. 生成编辑请求
echo "6️⃣  生成 30 次编辑请求..."
for i in {1..30}; do
    echo -n "  [$i/30] "
    
    EDIT_RESPONSE=$(curl -s -X POST "$BASE_URL/v1/docs/$DOC_ID/edit" \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"message\": \"测试编辑 $i\"}")
    
    STATUS=$(echo "$EDIT_RESPONSE" | jq -r '.status' 2>/dev/null)
    
    if [ "$STATUS" != "null" ] && [ -n "$STATUS" ]; then
        echo "✅ $STATUS"
    else
        echo "❌ 失败"
    fi
    
    # 随机延迟
    sleep $(awk -v min=0.2 -v max=1.0 'BEGIN{srand(); print min+rand()*(max-min)}')
done
echo ""

# 7. 导出文档
echo "7️⃣  导出文档..."
curl -s -X GET "$BASE_URL/v1/docs/$DOC_ID/export" \
  -H "Authorization: Bearer $TOKEN" | jq '.content' | head -c 100
echo "..."
echo ""

# 8. 列出文档
echo "8️⃣  列出文档..."
DOCS_COUNT=$(curl -s -X GET "$BASE_URL/v1/docs/" \
  -H "Authorization: Bearer $TOKEN" | jq '.documents | length' 2>/dev/null)
echo "✅ 找到 $DOCS_COUNT 个文档"
echo ""

# 9. 健康检查（多次）
echo "9️⃣  执行 10 次健康检查..."
for i in {1..10}; do
    echo -n "  [$i/10] "
    STATUS=$(curl -s "$BASE_URL/health/" | jq -r '.status' 2>/dev/null)
    echo "✅ $STATUS"
    sleep 0.5
done
echo ""

# 10. 显示最新 metrics
echo "🔟 查看最新 Metrics..."
echo ""
echo "关键指标："
curl -s "$BASE_URL/metrics" | grep -E "^(request_duration|edits_|documents_|errors_)" | head -20
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ 流量生成完成！                                            ║"
echo "║                                                              ║"
echo "║  现在可以在 Grafana 查看数据：                                ║"
echo "║  http://localhost:3000                                       ║"
echo "║                                                              ║"
echo "║  Prometheus 查询示例：                                        ║"
echo "║  - rate(request_duration_seconds_count[5m])                  ║"
echo "║  - rate(edits_requested_total[5m])                           ║"
echo "║  - histogram_quantile(0.95, rate(request_duration_seconds_bucket[5m])) ║"
echo "╚══════════════════════════════════════════════════════════════╝"
