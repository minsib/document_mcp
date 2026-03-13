"""
意图澄清节点 - 检测模糊意图并请求用户确认
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from app.models.schemas import Intent
from app.models import database as db_models
from app.services.llm_client import get_qwen_client
import uuid
import json
import re


class IntentClarifierNode:
    """意图澄清节点"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """检查意图是否需要澄清"""
        intent = state.get("intent")
        if not intent:
            return state
        
        user_message = state.get("user_message", "")
        
        # 1. 检测引用其他段落的情况
        reference_check = self._check_cross_reference(user_message, intent)
        if reference_check:
            state["needs_clarification"] = True
            state["clarification"] = reference_check
            return state
        
        # 2. 检测模糊表达
        ambiguity_check = self._check_ambiguity(user_message, intent)
        if ambiguity_check:
            state["needs_clarification"] = True
            state["clarification"] = ambiguity_check
            return state
        
        # 3. 检测大范围修改
        scope_check = self._check_large_scope(intent)
        if scope_check:
            state["needs_clarification"] = True
            state["clarification"] = scope_check
            return state
        
        return state
    
    def _check_cross_reference(self, user_message: str, intent: Intent) -> Optional[Dict]:
        """检测是否引用了其他段落"""
        
        # 先检查是否是字面意思（不是引用）
        # 如果用户说"改成XXX说的对"、"改成XXX的内容"，这通常是字面意思
        literal_patterns = [
            r'改成["""].*["""]',  # 带引号的内容
            r'改成.*说的对$',      # "改成XXX说的对"（结尾）
            r'改成.*的对$',        # "改成XXX的对"（结尾）
        ]
        
        for pattern in literal_patterns:
            if re.search(pattern, user_message):
                # 这是字面意思，不是引用，不需要澄清
                return None
        
        # 检测引用模式：如"参考第X章"、"像第X段那样"
        # 注意：排除"改成第X条说的对"这种字面表达
        reference_patterns = [
            (r'参考第[一二三四五六七八九十\d]+[条章节段]', True),
            (r'像第[一二三四五六七八九十\d]+[条章节段]', True),
            (r'按照第[一二三四五六七八九十\d]+[条章节段]', True),
            (r'和第[一二三四五六七八九十\d]+[条章节段].*一样', True),
            (r'改成第[一二三四五六七八九十\d]+条(?!说的对)', True),  # "改成第X条"但不是"说的对"
        ]
        
        has_reference = False
        for pattern, _ in reference_patterns:
            if re.search(pattern, user_message):
                has_reference = True
                break
        
        if not has_reference:
            return None
        
        # 检查是否明确表达了"完全替换"的意图
        explicit_replace_patterns = [
            r'把.*替换成',
            r'把.*换成',
            r'把.*的内容改成.*的内容',
        ]
        
        for pattern in explicit_replace_patterns:
            if re.search(pattern, user_message):
                # 用户意图明确：完全替换，不需要澄清
                return None
        
        # 如果只是"参考"、"像"等模糊表达，才需要澄清
        return {
            "type": "cross_reference",
            "message": "检测到您引用了其他段落",
            "question": "您是想：\n1. 完全替换为被引用段落的内容？\n2. 参考被引用段落的格式/结构来改写？\n3. 参考被引用段落的表述方式？",
            "options": [
                {"id": "replace_content", "label": "完全替换内容"},
                {"id": "reference_format", "label": "参考格式结构"},
                {"id": "reference_style", "label": "参考表述方式"}
            ],
            "severity": "high"
        }
    
    def _check_ambiguity(self, user_message: str, intent: Intent) -> Optional[Dict]:
        """检测模糊表达"""
        
        # 先检查是否是明确的字面表达
        # 如果用户说"改成XXX说的对"，这通常是明确的字面意思
        clear_literal_patterns = [
            r'改成.*说的对$',
            r'改成.*的对$',
            r'改成["""].*["""]',
            r'改为["""].*["""]',
        ]
        
        for pattern in clear_literal_patterns:
            if re.search(pattern, user_message):
                # 这是明确的字面表达，不模糊
                return None
        
        # 使用 LLM 检测意图是否明确
        system_prompt = """你是一个意图分析专家。判断用户的编辑请求是否明确。

模糊请求的特征：
1. 使用"改一下"、"优化一下"等笼统表达，且没有说明具体改成什么
2. 没有明确说明要改成什么样
3. 使用"更好"、"更合适"等主观词汇但没有具体标准
4. 引用其他内容但没说清楚如何引用

明确请求的特征：
1. 明确说明要改成什么内容（如"改成XXX"）
2. 提供了具体的修改标准或示例
3. 即使包含"第X条"等词，但如果是"改成第X条说的对"这种，是明确的字面意思

输出 JSON：
{
  "is_ambiguous": true/false,
  "reason": "模糊的原因或明确的原因",
  "suggestions": ["建议1", "建议2"]  // 仅在模糊时提供
}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户请求：{user_message}\n\n判断是否模糊："}
        ]
        
        try:
            response = self.llm.chat_completion_json(messages, temperature=0.3)
            result = json.loads(response)
            
            if result.get("is_ambiguous"):
                return {
                    "type": "ambiguous",
                    "message": "您的请求可能不够明确",
                    "reason": result.get("reason", ""),
                    "question": "为了更好地帮您修改，请明确：\n" + "\n".join(f"- {s}" for s in result.get("suggestions", [])),
                    "severity": "medium"
                }
        except Exception as e:
            print(f"模糊检测失败: {e}")
        
        return None
    
    def _check_large_scope(self, intent) -> Optional[Dict]:
        """检测大范围修改"""
        # 兼容dict和Intent对象
        if isinstance(intent, dict):
            operation = intent.get("operation")
        else:
            operation = getattr(intent, "operation", None)
        
        # 检测是否是批量操作
        if operation == "multi_replace":
            return {
                "type": "large_scope",
                "message": "这是一个批量修改操作",
                "question": "此操作可能影响多个段落，确认继续？",
                "severity": "medium"
            }
        
        # 检测是否是删除操作
        if operation == "delete":
            return {
                "type": "delete_operation",
                "message": "这是一个删除操作",
                "question": "删除后无法恢复（除非回滚版本），确认删除？",
                "severity": "high"
            }
        
        return None


class SemanticConflictDetector:
    """语义冲突检测器"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
    
    def check_conflict(
        self,
        original_content: str,
        new_content: str,
        context: Optional[str] = None
    ) -> Optional[Dict]:
        """检测修改前后的语义冲突"""
        
        system_prompt = """你是一个文档语义分析专家。比较修改前后的内容，检测是否存在语义冲突。

语义冲突的情况：
1. 主题完全不同（如：技术规范 → 付款条款）
2. 逻辑矛盾（如：必须 → 禁止）
3. 关键信息丢失（如：删除了重要的约束条件）
4. 上下文不连贯（如：修改后与前后段落脱节）

输出 JSON：
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
            response = self.llm.chat_completion_json(messages, temperature=0.3)
            result = json.loads(response)
            
            if result.get("has_conflict"):
                return {
                    "type": "semantic_conflict",
                    "conflict_type": result.get("conflict_type"),
                    "severity": result.get("severity", "medium"),
                    "message": result.get("description", "检测到语义冲突"),
                    "suggestion": result.get("suggestion", ""),
                    "question": "检测到修改前后内容存在较大差异，是否继续？"
                }
        except Exception as e:
            print(f"语义冲突检测失败: {e}")
        
        return None
    
    def get_context(self, block_id: str, rev_id: str, window: int = 2) -> str:
        """获取块的上下文（前后各 window 个块）"""
        block_uuid = uuid.UUID(block_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 获取目标块
        target_block = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.block_id == block_uuid,
            db_models.BlockVersion.rev_id == rev_uuid
        ).first()
        
        if not target_block:
            return ""
        
        # 获取前后的块
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid,
            db_models.BlockVersion.order_index >= target_block.order_index - window,
            db_models.BlockVersion.order_index <= target_block.order_index + window
        ).order_by(db_models.BlockVersion.order_index).all()
        
        context_parts = []
        for block in blocks:
            if block.block_id == block_uuid:
                context_parts.append(f"【目标块】\n{block.plain_text}")
            else:
                context_parts.append(block.plain_text)
        
        return "\n\n".join(context_parts)


class CrossReferenceResolver:
    """跨段落引用解析器"""
    
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_qwen_client()
    
    def resolve_reference(
        self,
        user_message: str,
        doc_id: str,
        rev_id: str
    ) -> Optional[Dict]:
        """解析用户消息中的引用"""
        
        # 提取引用的段落编号
        patterns = {
            r'第([一二三四五六七八九十]+)条': self._chinese_to_number,
            r'第(\d+)条': int,
            r'第([一二三四五六七八九十]+)章': self._chinese_to_number,
            r'第(\d+)章': int,
        }
        
        for pattern, converter in patterns.items():
            match = re.search(pattern, user_message)
            if match:
                number = converter(match.group(1))
                # 查找对应的块
                referenced_block = self._find_block_by_number(doc_id, rev_id, number)
                if referenced_block:
                    return {
                        "number": number,
                        "block_id": str(referenced_block.block_id),
                        "content": referenced_block.content_md,
                        "plain_text": referenced_block.plain_text
                    }
        
        return None
    
    def _chinese_to_number(self, chinese: str) -> int:
        """中文数字转阿拉伯数字"""
        chinese_map = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10
        }
        
        if chinese in chinese_map:
            return chinese_map[chinese]
        
        # 处理"十一"、"十二"等
        if chinese.startswith('十'):
            if len(chinese) == 1:
                return 10
            return 10 + chinese_map.get(chinese[1], 0)
        
        return 0
    
    def _find_block_by_number(
        self,
        doc_id: str,
        rev_id: str,
        number: int
    ) -> Optional[db_models.BlockVersion]:
        """根据编号查找块"""
        doc_uuid = uuid.UUID(doc_id)
        rev_uuid = uuid.UUID(rev_id)
        
        # 查找标题块，匹配"第X条"、"第X章"等
        blocks = self.db.query(db_models.BlockVersion).filter(
            db_models.BlockVersion.rev_id == rev_uuid,
            db_models.BlockVersion.block_type == 'heading'
        ).order_by(db_models.BlockVersion.order_index).all()
        
        for block in blocks:
            # 检查标题中是否包含对应的编号
            if block.plain_text:
                patterns = [
                    rf'第{number}条',
                    rf'第{self._number_to_chinese(number)}条',
                    rf'{number}\.',
                    rf'{number}\s',
                ]
                for pattern in patterns:
                    if re.search(pattern, block.plain_text):
                        return block
        
        return None
    
    def _number_to_chinese(self, num: int) -> str:
        """阿拉伯数字转中文"""
        chinese_map = {
            1: '一', 2: '二', 3: '三', 4: '四', 5: '五',
            6: '六', 7: '七', 8: '八', 9: '九', 10: '十'
        }
        return chinese_map.get(num, str(num))
