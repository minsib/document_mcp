"""
Intent Agent - 意图理解智能体
负责解析用户的自然语言请求，提取编辑意图
"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.tools.llm_tools import ParseIntentTool
from app.tools.db_tools import GetDocumentTool, GetRevisionTool
from app.models.schemas import Intent, ScopeHint, Constraints
from app.utils.intent_helper import get_intent_attr


def create_intent_agent(db: Session):
    """创建意图理解智能体"""
    return IntentAgent(db)


class IntentAgent:
    """意图理解智能体
    
    职责：
    1. 解析用户的自然语言请求
    2. 提取操作类型、范围提示、约束条件等关键信息
    3. 评估意图的明确性和置信度
    4. 处理边界情况和异常输入
    """
    
    def __init__(self, db: Session):
        self.db = db
        
        # 初始化工具
        self.parse_intent_tool = ParseIntentTool(db=db)
        self.get_document_tool = GetDocumentTool(db=db)
        self.get_revision_tool = GetRevisionTool(db=db)
    
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行意图解析
        
        Args:
            state: 工作流状态
            
        Returns:
            更新后的状态，包含解析的意图
        """
        user_message = state.get("user_message", "").strip()
        doc_id = state.get("doc_id")
        
        # 1. 输入验证
        if not user_message:
            state["errors"] = state.get("errors", []) + [{
                "type": "empty_message",
                "message": "用户消息不能为空"
            }]
            state["next_action"] = "end"
            return state
        
        if len(user_message) > 2000:
            state["errors"] = state.get("errors", []) + [{
                "type": "message_too_long",
                "message": "用户消息过长（最多 2000 字符）"
            }]
            state["next_action"] = "end"
            return state
        
        # 2. 获取文档上下文
        context = self._get_document_context(doc_id, state.get("active_rev_id"))
        
        # 3. 解析意图
        try:
            # 推断操作类型
            operation = self._infer_operation(user_message)
            
            # 提取范围提示
            scope_hint = self._extract_scope_hint(user_message)
            
            # 推断约束条件
            constraints = self._infer_constraints(user_message, operation)
            
            # 评估风险等级
            risk = self._assess_risk(operation, user_message)
            
            # 4. 创建 Intent 对象
            intent = Intent(
                operation=operation,
                scope_hint=scope_hint,
                constraints=constraints,
                risk=risk,
                user_message=user_message
            )
            
            # 5. 评估意图置信度
            confidence = self._evaluate_confidence(intent, user_message)
            
            # 6. 更新状态
            state["intent"] = intent.model_dump()  # 转换为字典
            state["intent_confidence"] = confidence
            state["next_action"] = "router"
            
            # 7. 添加调试信息（可选）
            if state.get("debug_mode"):
                state["debug_info"] = state.get("debug_info", {})
                state["debug_info"]["intent_agent"] = {
                    "parsed_intent": intent.model_dump(),
                    "confidence": confidence,
                    "context_used": bool(context)
                }
            
            return state
            
        except Exception as e:
            print(f"意图智能体执行失败: {e}")
            import traceback
            traceback.print_exc()
            
            state["errors"] = state.get("errors", []) + [{
                "type": "intent_agent_error",
                "message": f"意图智能体执行失败: {str(e)}"
            }]
            state["next_action"] = "end"
            return state
    
    def _get_document_context(self, doc_id: str, rev_id: Optional[str]) -> str:
        """获取文档上下文信息
        
        Args:
            doc_id: 文档 ID
            rev_id: 版本 ID
            
        Returns:
            文档上下文描述
        """
        try:
            # 获取文档信息
            doc_info = self.get_document_tool._run(doc_id=doc_id)
            
            if "error" in doc_info:
                return ""
            
            context_parts = [f"文档标题: {doc_info.get('title', '未知')}"]
            
            # 获取版本信息
            if rev_id:
                rev_info = self.get_revision_tool._run(rev_id=rev_id)
                if "error" not in rev_info:
                    context_parts.append(f"当前版本: {rev_info.get('rev_no', 1)}")
            
            return "\n".join(context_parts)
            
        except Exception as e:
            print(f"获取文档上下文失败: {e}")
            return ""
    
    def _infer_operation(self, user_message: str) -> str:
        """从用户消息推断操作类型
        
        Args:
            user_message: 用户消息
            
        Returns:
            操作类型
        """
        message_lower = user_message.lower()
        
        # 删除操作
        if any(keyword in message_lower for keyword in ["删除", "删掉", "去掉", "移除"]):
            return "delete"
        
        # 插入操作
        if any(keyword in message_lower for keyword in ["插入", "添加", "加上", "增加"]):
            if "后面" in message_lower or "之后" in message_lower:
                return "insert_after"
            elif "前面" in message_lower or "之前" in message_lower:
                return "insert_before"
            return "insert_after"  # 默认后插入
        
        # 批量替换
        if any(keyword in message_lower for keyword in ["全部", "所有", "统一", "批量"]):
            return "multi_replace"
        
        # 默认为替换
        return "replace"
    
    def _extract_scope_hint(self, user_message: str) -> ScopeHint:
        """从用户消息提取范围提示
        
        Args:
            user_message: 用户消息
            
        Returns:
            ScopeHint 对象
        """
        import re
        
        heading = None
        nearby = None
        keywords = []
        block_type = None
        
        # 1. 提取章节名称
        # 匹配"第X章"、"第X节"、"XX部分"等
        heading_patterns = [
            r'第[一二三四五六七八九十\d]+章',
            r'第[一二三四五六七八九十\d]+节',
            r'第[一二三四五六七八九十\d]+部分',
            r'([^，。！？\n]+)那段',
            r'([^，。！？\n]+)这段',
            r'([^，。！？\n]+)章节',
        ]
        
        for pattern in heading_patterns:
            match = re.search(pattern, user_message)
            if match:
                heading = match.group(0).replace("那段", "").replace("这段", "").replace("章节", "").strip()
                break
        
        # 2. 提取相对位置
        if "第一" in user_message or "开头" in user_message:
            nearby = "first"
        elif "最后" in user_message or "结尾" in user_message:
            nearby = "last"
        
        # 3. 提取关键词（简单实现：提取引号中的内容）
        quote_patterns = [r'"([^"]+)"', r'"([^"]+)"', r'「([^」]+)」']
        for pattern in quote_patterns:
            matches = re.findall(pattern, user_message)
            keywords.extend(matches)
        
        # 4. 推断块类型
        if "标题" in user_message or "章节" in user_message:
            block_type = "heading"
        elif "段落" in user_message:
            block_type = "paragraph"
        elif "列表" in user_message:
            block_type = "list"
        elif "代码" in user_message:
            block_type = "code"
        
        return ScopeHint(
            heading=heading,
            nearby=nearby,
            keywords=keywords,
            block_type=block_type
        )
    
    def _infer_constraints(self, user_message: str, operation: str) -> Constraints:
        """推断约束条件
        
        Args:
            user_message: 用户消息
            operation: 操作类型
            
        Returns:
            Constraints 对象
        """
        tone = "neutral"
        keep_length = "similar"
        must_include = []
        must_exclude = []
        
        # 1. 推断语气
        if any(kw in user_message for kw in ["正式", "严肃", "专业"]):
            tone = "formal"
        elif any(kw in user_message for kw in ["随意", "轻松", "口语"]):
            tone = "casual"
        
        # 2. 推断长度要求
        if any(kw in user_message for kw in ["简洁", "简短", "精简", "缩短"]):
            keep_length = "shorter"
        elif any(kw in user_message for kw in ["详细", "扩展", "展开", "加长"]):
            keep_length = "longer"
        
        # 3. 提取必须包含的内容
        import re
        include_patterns = [r'必须包含["""]([^"""]+)["""]', r'要有["""]([^"""]+)["""]']
        for pattern in include_patterns:
            matches = re.findall(pattern, user_message)
            must_include.extend(matches)
        
        # 4. 提取必须排除的内容
        exclude_patterns = [r'不要["""]([^"""]+)["""]', r'去掉["""]([^"""]+)["""]']
        for pattern in exclude_patterns:
            matches = re.findall(pattern, user_message)
            must_exclude.extend(matches)
        
        return Constraints(
            tone=tone,
            keep_length=keep_length,
            must_include=must_include,
            must_exclude=must_exclude
        )
    
    def _assess_risk(self, operation: str, user_message: str) -> str:
        """评估操作风险等级
        
        Args:
            operation: 操作类型
            user_message: 用户消息
            
        Returns:
            风险等级: low, medium, high
        """
        # 1. 基于操作类型的基础风险
        base_risk = {
            "replace": "low",
            "insert_after": "low",
            "insert_before": "low",
            "delete": "medium",
            "multi_replace": "high"
        }
        
        risk = base_risk.get(operation, "medium")
        
        # 2. 基于范围的风险调整
        if any(kw in user_message for kw in ["全部", "所有", "整个", "全文"]):
            if risk == "low":
                risk = "medium"
            elif risk == "medium":
                risk = "high"
        
        # 3. 基于模糊性的风险调整
        if len(user_message) < 10:
            # 消息太短，可能不够明确
            if risk == "low":
                risk = "medium"
        
        return risk
    
    def _evaluate_confidence(self, intent: Intent, user_message: str) -> float:
        """评估意图置信度
        
        Args:
            intent: 解析的意图
            user_message: 用户消息
            
        Returns:
            置信度 (0.0-1.0)
        """
        confidence = 0.5  # 基础置信度
        
        # 1. 操作类型明确性
        operation_keywords = {
            "replace": ["改", "换", "修改", "变"],
            "delete": ["删", "去掉", "移除"],
            "insert_after": ["插入", "添加", "加上", "后面"],
            "insert_before": ["前面加", "之前加"],
            "multi_replace": ["全部", "所有", "统一"]
        }
        
        if intent.operation in operation_keywords:
            keywords = operation_keywords[intent.operation]
            if any(kw in user_message for kw in keywords):
                confidence += 0.2
        
        # 2. 范围提示明确性
        scope_hint = get_intent_attr(intent, "scope_hint", None)
        if scope_hint:
            heading = None
            keywords_list = []
            block_type = None
            
            if isinstance(scope_hint, dict):
                heading = scope_hint.get("heading")
                keywords_list = scope_hint.get("keywords", [])
                block_type = scope_hint.get("block_type")
            else:
                heading = getattr(scope_hint, "heading", None)
                keywords_list = getattr(scope_hint, "keywords", [])
                block_type = getattr(scope_hint, "block_type", None)
            
            if heading:
                confidence += 0.15
            if keywords_list:
                confidence += 0.1
            if block_type:
                confidence += 0.05
        
        # 3. 消息长度合理性
        if 10 <= len(user_message) <= 200:
            confidence += 0.1
        elif len(user_message) < 5:
            confidence -= 0.2
        
        # 确保在 0-1 范围内
        return max(0.0, min(1.0, confidence))
