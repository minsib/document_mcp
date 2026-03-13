"""
LLM 工具 - 封装所有 LLM 调用
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import json

from app.tools.base import BaseTool
from app.services.llm_client import get_qwen_client
from app.models.schemas import Intent


# ============ Input Schemas ============

class ParseIntentInput(BaseModel):
    user_message: str = Field(description="用户的编辑请求")
    context: Optional[str] = Field(default=None, description="上下文信息")


class VerifyTargetInput(BaseModel):
    intent_description: str = Field(description="用户意图描述")
    candidate_content: str = Field(description="候选块的内容")
    operation: str = Field(description="操作类型")


class GenerateContentInput(BaseModel):
    instruction: str = Field(description="生成指令")
    original_content: str = Field(description="原始内容")
    context: Optional[str] = Field(default=None, description="上下文信息")


class CheckSemanticConflictInput(BaseModel):
    original_content: str = Field(description="原始内容")
    new_content: str = Field(description="新内容")
    context: Optional[str] = Field(default=None, description="上下文信息")


# ============ Tools ============

class ParseIntentTool(BaseTool):
    name: str = "parse_intent"
    description: str = """解析用户的编辑意图。
    从用户的自然语言请求中提取：
    - 操作类型（replace/insert_after/insert_before/delete）
    - 目标描述（要修改哪里）
    - 新内容（改成什么）
    - 范围提示（在哪个章节）"""
    args_schema: type[BaseModel] = ParseIntentInput
    
    def _run(self, user_message: str, context: Optional[str] = None) -> Dict[str, Any]:
        """解析意图"""
        llm = get_qwen_client()
        
        system_prompt = """你是一个文档编辑意图分析专家。

你的任务是从用户的自然语言请求中提取编辑意图。

输出 JSON 格式：
{
  "operation": "replace/insert_after/insert_before/delete/multi_replace",
  "target_description": "要修改的目标描述",
  "new_content": "新内容（如果是删除则为空）",
  "scope_hint": "范围提示（如章节名称）",
  "confidence": 0.0-1.0
}

操作类型说明：
- replace: 替换指定段落
- insert_after: 在指定段落后插入
- insert_before: 在指定段落前插入
- delete: 删除指定段落
- multi_replace: 批量替换（全文统一修改）
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户请求：{user_message}\n\n上下文：{context or '无'}\n\n解析意图："}
        ]
        
        try:
            response = llm.chat_completion_json(messages, temperature=0.3)
            result = json.loads(response)
            return result
        except Exception as e:
            return {"error": str(e)}


class VerifyTargetTool(BaseTool):
    name: str = "verify_target"
    description: str = """验证候选块是否匹配用户意图。
    使用 LLM 判断检索到的候选块是否真的是用户想要修改的目标。
    返回匹配置信度和原因。"""
    args_schema: type[BaseModel] = VerifyTargetInput
    
    def _run(
        self,
        intent_description: str,
        candidate_content: str,
        operation: str
    ) -> Dict[str, Any]:
        """验证目标"""
        llm = get_qwen_client()
        
        system_prompt = """你是一个文档定位验证专家。

判断候选内容是否匹配用户的编辑意图。

输出 JSON 格式：
{
  "is_match": true/false,
  "confidence": 0.0-1.0,
  "reason": "匹配/不匹配的原因"
}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""用户意图：{intent_description}
操作类型：{operation}

候选内容：
{candidate_content}

判断是否匹配："""}
        ]
        
        try:
            response = llm.chat_completion_json(messages, temperature=0.3)
            result = json.loads(response)
            return result
        except Exception as e:
            return {"error": str(e), "is_match": False, "confidence": 0.0}


class GenerateContentTool(BaseTool):
    name: str = "generate_content"
    description: str = """根据指令生成新内容。
    基于用户的修改要求和原始内容，生成修改后的新内容。"""
    args_schema: type[BaseModel] = GenerateContentInput
    
    def _run(
        self,
        instruction: str,
        original_content: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """生成内容"""
        llm = get_qwen_client()
        
        system_prompt = """你是一个文档编辑专家。

根据用户的修改要求，生成修改后的内容。

要求：
1. 保持原文的格式和风格
2. 只修改需要修改的部分
3. 确保修改后的内容通顺、准确
4. 保留 Markdown 格式

直接输出修改后的内容，不要添加任何解释。
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""修改要求：{instruction}

原始内容：
{original_content}

上下文：
{context or '无'}

生成修改后的内容："""}
        ]
        
        try:
            response = llm.chat_completion(messages, temperature=0.7)
            return {"content": response.strip()}
        except Exception as e:
            return {"error": str(e)}


class CheckSemanticConflictTool(BaseTool):
    name: str = "check_semantic_conflict"
    description: str = """检测修改前后的语义冲突。
    判断修改是否会导致：
    - 主题不符
    - 逻辑矛盾
    - 关键信息丢失
    - 上下文不连贯"""
    args_schema: type[BaseModel] = CheckSemanticConflictInput
    
    def _run(
        self,
        original_content: str,
        new_content: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """检测语义冲突"""
        llm = get_qwen_client()
        
        system_prompt = """你是一个文档语义分析专家。

比较修改前后的内容，检测是否存在语义冲突。

语义冲突的情况：
1. 主题完全不同（如：技术规范 → 付款条款）
2. 逻辑矛盾（如：必须 → 禁止）
3. 关键信息丢失（如：删除了重要的约束条件）
4. 上下文不连贯（如：修改后与前后段落脱节）

输出 JSON 格式：
{
  "has_conflict": true/false,
  "conflict_type": "主题不符/逻辑矛盾/信息丢失/上下文不连贯",
  "severity": "high/medium/low",
  "description": "冲突描述",
  "suggestion": "建议"
}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""原内容：
{original_content}

新内容：
{new_content}

上下文：
{context or '无'}

检测语义冲突："""}
        ]
        
        try:
            response = llm.chat_completion_json(messages, temperature=0.3)
            result = json.loads(response)
            return result
        except Exception as e:
            return {"error": str(e), "has_conflict": False}
