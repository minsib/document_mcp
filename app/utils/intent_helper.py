"""
Intent Helper - 统一处理 Intent 对象和字典的属性访问
"""
from typing import Any, Optional


def get_intent_attr(intent: Any, attr_name: str, default: Any = None) -> Any:
    """
    安全地获取 intent 的属性值，兼容对象和字典两种形式
    
    Args:
        intent: Intent 对象或字典
        attr_name: 属性名称
        default: 默认值
        
    Returns:
        属性值，如果不存在则返回默认值
    """
    if intent is None:
        return default
    
    if isinstance(intent, dict):
        return intent.get(attr_name, default)
    else:
        return getattr(intent, attr_name, default)


def is_intent_dict(intent: Any) -> bool:
    """
    判断 intent 是否为字典形式
    
    Args:
        intent: Intent 对象或字典
        
    Returns:
        是否为字典
    """
    return isinstance(intent, dict)
