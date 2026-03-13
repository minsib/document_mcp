#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8001}"
REQUESTS="${2:-20}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1"
    exit 1
  fi
}

json_get() {
  local key="$1"
  python3 - "$key" <<'PY'
import json
import sys

key = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

val = data
for p in key.split('.'):
    if isinstance(val, dict):
        val = val.get(p)
    else:
        val = None
        break

if val is None:
    sys.exit(1)

if isinstance(val, (dict, list)):
    print(json.dumps(val, ensure_ascii=False))
else:
    print(val)
PY
}

require_cmd curl
require_cmd python3

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "[1/7] 检查服务健康: $BASE_URL/health"
if ! curl -fsS "$BASE_URL/health" >/dev/null; then
  echo "API 不可用，请先启动: docker compose up -d"
  exit 1
fi

suffix="$(date +%s)_$RANDOM"
username="monitor_${suffix}"
email="${username}@example.com"
password="Passw0rd!"

echo "[2/7] 注册测试用户: $username"
register_code=$(curl -sS -o "$workdir/register.json" -w "%{http_code}" \
  -X POST "$BASE_URL/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$username\",\"email\":\"$email\",\"password\":\"$password\"}")

if [[ "$register_code" != "201" ]]; then
  echo "注册返回 $register_code，继续尝试登录（可能用户名重复）"
fi

echo "[3/7] 登录获取 token"
login_code=$(curl -sS -o "$workdir/login.json" -w "%{http_code}" \
  -X POST "$BASE_URL/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$username\",\"password\":\"$password\"}")

if [[ "$login_code" != "200" ]]; then
  echo "登录失败，状态码: $login_code"
  cat "$workdir/login.json"
  exit 1
fi

TOKEN=$(cat "$workdir/login.json" | json_get "access_token")
if [[ -z "${TOKEN:-}" ]]; then
  echo "无法解析 access_token"
  cat "$workdir/login.json"
  exit 1
fi

echo "[4/7] 上传测试文档"
DOC_CONTENT=$(cat <<'MD'
# 项目目标
我们要构建一个文档编辑系统，支持多用户并发编辑和审计能力。

## 检索策略
系统使用 BM25 + 向量检索 + 融合排序，提升定位准确率。

## 实施计划
第一阶段完成核心编辑能力，第二阶段补齐监控告警与可观测性。

## 回滚策略
所有变更支持版本回滚和差异对比。
MD
)

upload_code=$(curl -sS -o "$workdir/upload.json" -w "%{http_code}" \
  -X POST "$BASE_URL/v1/docs/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "title=监控压测文档" \
  -F "content=$DOC_CONTENT")

if [[ "$upload_code" != "200" ]]; then
  echo "上传失败，状态码: $upload_code"
  cat "$workdir/upload.json"
  exit 1
fi

DOC_ID=$(cat "$workdir/upload.json" | json_get "doc_id")
if [[ -z "${DOC_ID:-}" ]]; then
  echo "无法解析 doc_id"
  cat "$workdir/upload.json"
  exit 1
fi

echo "文档已创建: $DOC_ID"

echo "[5/7] 发送 $REQUESTS 次编辑请求（含确认/取消）"

need_confirm_count=0
applied_count=0
failed_count=0
other_count=0

for i in $(seq 1 "$REQUESTS"); do
  case $((i % 4)) in
    0) msg="把项目目标这段改得更简洁" ;;
    1) msg="在实施计划后面补充一段风险说明" ;;
    2) msg="把回滚策略改成灰度发布与快速回滚策略" ;;
    3) msg="把不存在章节abcdefg中的段落删除" ;;
  esac

  session_id="sess_${suffix}_$i"
  body="{\"doc_id\":\"$DOC_ID\",\"session_id\":\"$session_id\",\"message\":\"$msg\"}"

  edit_code=$(curl -sS -o "$workdir/edit_$i.json" -w "%{http_code}" \
    -X POST "$BASE_URL/v1/chat/edit" \
    -H "Content-Type: application/json" \
    -d "$body")

  if [[ "$edit_code" != "200" ]]; then
    failed_count=$((failed_count + 1))
    continue
  fi

  status=$(cat "$workdir/edit_$i.json" | json_get "status" || true)

  if [[ "$status" == "need_confirm" ]]; then
    need_confirm_count=$((need_confirm_count + 1))
    confirm_token=$(cat "$workdir/edit_$i.json" | json_get "confirm_token" || true)
    preview_hash=$(cat "$workdir/edit_$i.json" | json_get "preview_hash" || true)

    if [[ -n "$confirm_token" && -n "$preview_hash" ]]; then
      action="apply"
      if (( i % 6 == 0 )); then
        action="cancel"
      fi

      confirm_body="{\"session_id\":\"$session_id\",\"doc_id\":\"$DOC_ID\",\"confirm_token\":\"$confirm_token\",\"action\":\"$action\",\"preview_hash\":\"$preview_hash\"}"
      confirm_code=$(curl -sS -o "$workdir/confirm_$i.json" -w "%{http_code}" \
        -X POST "$BASE_URL/v1/chat/confirm" \
        -H "Content-Type: application/json" \
        -d "$confirm_body")

      if [[ "$confirm_code" == "200" ]]; then
        cstatus=$(cat "$workdir/confirm_$i.json" | json_get "status" || true)
        if [[ "$cstatus" == "applied" ]]; then
          applied_count=$((applied_count + 1))
        fi
      fi
    fi
  elif [[ "$status" == "applied" ]]; then
    applied_count=$((applied_count + 1))
  elif [[ "$status" == "failed" ]]; then
    failed_count=$((failed_count + 1))
  else
    other_count=$((other_count + 1))
  fi

done

echo "[6/7] 发送 6 次非法 doc_id 请求，制造错误样本"
for i in $(seq 1 6); do
  bad_body="{\"doc_id\":\"00000000-0000-0000-0000-000000000000\",\"session_id\":\"bad_${suffix}_$i\",\"message\":\"测试错误链路\"}"
  curl -sS -o /dev/null \
    -X POST "$BASE_URL/v1/chat/edit" \
    -H "Content-Type: application/json" \
    -d "$bad_body" || true

done

echo "[7/7] 指标快照（关键字段）"
metrics_file="$workdir/metrics.txt"
curl -fsS "$BASE_URL/metrics" > "$metrics_file"

echo "----------------------------------------"
echo "请求统计:"
echo "need_confirm=$need_confirm_count, applied=$applied_count, failed=$failed_count, other=$other_count"
echo ""
echo "关键指标样本:"
if command -v rg >/dev/null 2>&1; then
  rg -n "edits_requested_total|edits_applied_total|edits_failed_total|edit_request_duration_seconds_count|llm_calls_total|llm_tokens_used_total|retrieval_duration_seconds_count|retrieval_requests_total|workflow_duration_seconds_count|workflow_runs_total" "$metrics_file" || true
else
  grep -nE "edits_requested_total|edits_applied_total|edits_failed_total|edit_request_duration_seconds_count|llm_calls_total|llm_tokens_used_total|retrieval_duration_seconds_count|retrieval_requests_total|workflow_duration_seconds_count|workflow_runs_total" "$metrics_file" || true
fi
echo "----------------------------------------"

echo "完成。请到 Grafana 看板查看（建议时间范围 Last 15 minutes）。"
