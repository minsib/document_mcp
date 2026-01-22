import re
import hashlib
from typing import List, Tuple


def strip_markdown(text: str) -> str:
    """移除 Markdown 格式，返回纯文本"""
    # 移除代码块
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    
    # 移除标题标记
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # 移除粗体和斜体
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    
    # 移除链接
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # 移除图片
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    
    # 移除列表标记
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # 移除引用标记
    text = re.sub(r'^\s*>\s+', '', text, flags=re.MULTILINE)
    
    # 移除多余空白
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text


def hash_content(content: str) -> str:
    """计算内容的 SHA256 哈希"""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def normalize_text(text: str) -> str:
    """标准化文本（用于比较）"""
    # 转小写
    text = text.lower()
    # 移除多余空白
    text = re.sub(r'\s+', ' ', text)
    # 移除标点符号
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def split_sentences(text: str) -> List[str]:
    """按句子切分文本"""
    # 按中文句号、英文句号、分号、换行切分
    sentences = re.split(r'([。.;；\n])', text)
    
    # 重新组合（保留分隔符）
    result = []
    for i in range(0, len(sentences) - 1, 2):
        if i + 1 < len(sentences):
            result.append(sentences[i] + sentences[i + 1])
        else:
            result.append(sentences[i])
    
    return [s for s in result if s.strip()]


def extract_heading_level(line: str) -> Tuple[int, str]:
    """提取标题级别和文本"""
    match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
    if match:
        level = len(match.group(1))
        text = match.group(2).strip()
        return level, text
    return 0, line


def is_code_block(line: str) -> bool:
    """判断是否是代码块标记"""
    return line.strip().startswith('```')


def is_list_item(line: str) -> bool:
    """判断是否是列表项"""
    return bool(re.match(r'^\s*[-*+]\s+', line) or re.match(r'^\s*\d+\.\s+', line))


def is_table_row(line: str) -> bool:
    """判断是否是表格行"""
    return '|' in line and line.strip().startswith('|')
