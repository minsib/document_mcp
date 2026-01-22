from typing import Dict, Any
from app.models.schemas import Intent, ScopeHint, Constraints
from app.services.llm_client import get_qwen_client
import json


class IntentParserNode:
    """意图解析节点"""
    
    def __init__(self):
        self.llm = get_qwen_client()
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """解析用户意图"""
        user_message = state["user_message"]
        
        # 构建提示词
        system_prompt = """你是一个文档编辑意图解析助手。

你的任务是解析用户的修改需求，输出结构化的意图信息。

规则：
1. 不要直接生成修改后的内容，只解析意图
2. 必须给出 scope_hint（heading/keywords/nearby）以辅助检索
3. 评估风险等级：
   - delete 操作 → high
   - multi_replace（全文统一替换）→ medium
   - 单段 replace → low
4. 如果用户提到"所有"、"全部"、"统一"，设置 operation = "multi_replace"

输出 JSON 格式，包含以下字段：
{
  "operation": "replace|insert_after|insert_before|delete|multi_replace",
  "scope_hint": {
    "heading": "章节名称（可选）",
    "nearby": "相对位置（可选）",
    "keywords": ["关键词1", "关键词2"],
    "block_type": "paragraph|heading|list|code|table（可选）"
  },
  "constraints": {
    "tone": "formal|neutral|casual",
    "keep_length": "shorter|similar|longer",
    "must_include": [],
    "must_exclude": []
  },
  "risk": "low|medium|high"
}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户消息：{user_message}\n\n输出 JSON："}
        ]
        
        # 获取 trace_id
        trace_id = state.get("trace_id")
        
        try:
            response = self.llm.chat_completion_json(
                messages, 
                temperature=0.3,
                trace_id=trace_id,
                span_name="intent_parser"
            )
            intent_data = json.loads(response)
            
            # 构建 Intent 对象
            intent = Intent(
                operation=intent_data.get("operation", "replace"),
                scope_hint=ScopeHint(**intent_data.get("scope_hint", {})),
                constraints=Constraints(**intent_data.get("constraints", {})),
                risk=intent_data.get("risk", "low")
            )
            
            state["intent"] = intent
            return state
            
        except Exception as e:
            # 降级：使用简单的规则解析
            intent = self._fallback_parse(user_message)
            state["intent"] = intent
            state["error"] = {"code": "intent_parse_failed", "message": str(e)}
            return state
    
    def _fallback_parse(self, message: str) -> Intent:
        """降级解析（基于规则）"""
        message_lower = message.lower()
        
        # 判断操作类型
        if "删除" in message or "去掉" in message:
            operation = "delete"
            risk = "high"
        elif "增加" in message or "添加" in message or "插入" in message:
            operation = "insert_after"
            risk = "low"
        else:
            operation = "replace"
            risk = "low"
        
        # 提取关键词
        keywords = []
        for word in message.split():
            if len(word) > 1 and word not in ["把", "将", "的", "了", "在", "和"]:
                keywords.append(word)
        
        return Intent(
            operation=operation,
            scope_hint=ScopeHint(keywords=keywords[:5]),
            constraints=Constraints(),
            risk=risk
        )
