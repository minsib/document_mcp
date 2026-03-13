"""
测试意图澄清和语义冲突检测功能
"""
import sys
sys.path.append('.')

from app.nodes.intent_clarifier import IntentClarifierNode, SemanticConflictDetector, CrossReferenceResolver
from app.models.schemas import Intent, ScopeHint, Constraints
from app.db.connection import get_db
from sqlalchemy.orm import Session


def test_cross_reference_detection():
    """测试跨段落引用检测"""
    print("\n=== 测试跨段落引用检测 ===")
    
    db = next(get_db())
    clarifier = IntentClarifierNode(db)
    
    test_cases = [
        ("把第五条知识产权部分改一下，改成第四条说的对", False, "字面意思，不应该触发"),
        ("把第六条的内容改成第四条说的对", False, "字面意思，不应该触发"),
        ("参考第三章的格式来改写第二章", True, "引用，应该触发"),
        ("像第一条那样重新组织这段内容", True, "引用，应该触发"),
        ("把这段改得更简洁一些", False, "不应该触发"),
        ("改成第五条的内容", True, "引用，应该触发"),
        ("把这段改成'第四条说的对'", False, "带引号，字面意思"),
    ]
    
    for message, should_trigger, reason in test_cases:
        print(f"\n用户消息: {message}")
        print(f"预期: {'应该触发' if should_trigger else '不应该触发'} ({reason})")
        
        # 创建模拟的 intent
        intent = Intent(
            operation="replace",
            scope_hint=ScopeHint(keywords=["知识产权"]),
            constraints=Constraints(),
            risk="low"
        )
        
        state = {
            "user_message": message,
            "intent": intent
        }
        
        result = clarifier(state)
        
        if result.get("needs_clarification"):
            clarification = result["clarification"]
            print(f"✅ 检测到需要澄清")
            print(f"   类型: {clarification['type']}")
            
            if should_trigger:
                print(f"   ✓ 符合预期（应该触发）")
            else:
                print(f"   ✗ 不符合预期（不应该触发）")
        else:
            print(f"❌ 未检测到需要澄清")
            
            if not should_trigger:
                print(f"   ✓ 符合预期（不应该触发）")
            else:
                print(f"   ✗ 不符合预期（应该触发）")


def test_semantic_conflict():
    """测试语义冲突检测"""
    print("\n=== 测试语义冲突检测 ===")
    
    db = next(get_db())
    detector = SemanticConflictDetector(db)
    
    test_cases = [
        {
            "name": "主题完全不同",
            "original": "第四条 验收标准\n\n4.1 甲方应在收到乙方书面验收通知后15个工作日内组织验收",
            "new": "第四条 知识产权\n\n4.1 本项目开发成果的知识产权归甲方所有",
            "should_conflict": True
        },
        {
            "name": "格式调整（不冲突）",
            "original": "第五条 知识产权\n\n本项目开发成果的知识产权归甲方所有",
            "new": "第五条 知识产权\n\n5.1 本项目开发成果的知识产权归甲方所有\n5.2 乙方保证交付成果不侵犯任何第三方的知识产权",
            "should_conflict": False
        },
        {
            "name": "逻辑矛盾",
            "original": "甲方必须在30日内完成付款",
            "new": "甲方禁止在30日内完成付款",
            "should_conflict": True
        }
    ]
    
    for case in test_cases:
        print(f"\n测试: {case['name']}")
        print(f"原内容: {case['original'][:50]}...")
        print(f"新内容: {case['new'][:50]}...")
        
        conflict = detector.check_conflict(
            case['original'],
            case['new']
        )
        
        if conflict:
            print(f"✅ 检测到冲突")
            print(f"   类型: {conflict.get('conflict_type')}")
            print(f"   严重程度: {conflict.get('severity')}")
            print(f"   描述: {conflict.get('message')}")
            
            if case['should_conflict']:
                print(f"   ✓ 符合预期（应该冲突）")
            else:
                print(f"   ✗ 不符合预期（不应该冲突）")
        else:
            print(f"❌ 未检测到冲突")
            
            if not case['should_conflict']:
                print(f"   ✓ 符合预期（不应该冲突）")
            else:
                print(f"   ✗ 不符合预期（应该冲突）")


def test_reference_resolver():
    """测试引用解析"""
    print("\n=== 测试引用解析 ===")
    
    db = next(get_db())
    resolver = CrossReferenceResolver(db)
    
    test_messages = [
        "把第五条改成第四条那样",
        "参考第3章的格式",
        "像第十条那样重写",
        "第二条需要修改"
    ]
    
    for message in test_messages:
        print(f"\n消息: {message}")
        
        # 测试中文数字转换
        import re
        patterns = {
            r'第([一二三四五六七八九十]+)条': resolver._chinese_to_number,
            r'第(\d+)条': int,
            r'第([一二三四五六七八九十]+)章': resolver._chinese_to_number,
            r'第(\d+)章': int,
        }
        
        found = False
        for pattern, converter in patterns.items():
            match = re.search(pattern, message)
            if match:
                number = converter(match.group(1))
                print(f"✅ 找到引用: 第 {number} 条/章")
                found = True
                break
        
        if not found:
            print(f"❌ 未找到引用")


if __name__ == "__main__":
    print("开始测试意图澄清和语义冲突检测功能...")
    
    try:
        test_cross_reference_detection()
        test_semantic_conflict()
        test_reference_resolver()
        
        print("\n" + "="*50)
        print("✅ 所有测试完成")
        print("="*50)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
