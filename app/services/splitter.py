from typing import List, Optional
from dataclasses import dataclass
import uuid
from app.utils.markdown import (
    strip_markdown, hash_content, split_sentences,
    extract_heading_level, is_code_block, is_list_item, is_table_row
)
from app.config import get_settings

settings = get_settings()


@dataclass
class BlockData:
    block_id: uuid.UUID
    block_type: str
    heading_level: Optional[int]
    content_md: str
    plain_text: str
    content_hash: str
    order_index: int
    parent_heading_block_id: Optional[uuid.UUID] = None


class BlockSplitter:
    def __init__(self):
        self.min_block_size = settings.MIN_BLOCK_SIZE
        self.max_block_size = settings.MAX_BLOCK_SIZE
        self.target_block_size = settings.TARGET_BLOCK_SIZE
    
    def split_document(self, markdown: str) -> List[BlockData]:
        """将 Markdown 文档切分为块"""
        lines = markdown.split('\n')
        blocks = []
        heading_stack = []  # [(level, block_id), ...]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 处理标题
            level, heading_text = extract_heading_level(line)
            if level > 0:
                block = self._create_heading_block(line, level, heading_stack)
                blocks.append(block)
                self._update_heading_stack(heading_stack, level, block.block_id)
                i += 1
                continue
            
            # 处理代码块
            if is_code_block(line):
                code_lines, i = self._collect_code_block(lines, i)
                block = self._create_code_block(code_lines, heading_stack)
                blocks.append(block)
                continue
            
            # 处理表格
            if is_table_row(line):
                table_lines, i = self._collect_table(lines, i)
                block = self._create_table_block(table_lines, heading_stack)
                blocks.append(block)
                continue
            
            # 处理列表
            if is_list_item(line):
                list_lines, i = self._collect_list(lines, i)
                block = self._create_list_block(list_lines, heading_stack)
                blocks.append(block)
                continue
            
            # 处理段落
            if line.strip():
                para_lines, i = self._collect_paragraph(lines, i)
                para_blocks = self._split_paragraph('\n'.join(para_lines), heading_stack)
                blocks.extend(para_blocks)
            else:
                i += 1
        
        # 设置 order_index
        for idx, block in enumerate(blocks):
            block.order_index = idx * 10
        
        return blocks
    
    def _create_heading_block(self, line: str, level: int, heading_stack: List) -> BlockData:
        """创建标题块"""
        parent_id = heading_stack[-1][1] if heading_stack else None
        plain_text = strip_markdown(line)
        
        return BlockData(
            block_id=uuid.uuid4(),
            block_type="heading",
            heading_level=level,
            content_md=line,
            plain_text=plain_text,
            content_hash=hash_content(line),
            order_index=0,
            parent_heading_block_id=parent_id
        )
    
    def _create_paragraph_block(self, text: str, heading_stack: List) -> BlockData:
        """创建段落块"""
        parent_id = heading_stack[-1][1] if heading_stack else None
        plain_text = strip_markdown(text)
        
        return BlockData(
            block_id=uuid.uuid4(),
            block_type="paragraph",
            heading_level=None,
            content_md=text,
            plain_text=plain_text,
            content_hash=hash_content(text),
            order_index=0,
            parent_heading_block_id=parent_id
        )
    
    def _create_code_block(self, lines: List[str], heading_stack: List) -> BlockData:
        """创建代码块"""
        parent_id = heading_stack[-1][1] if heading_stack else None
        content = '\n'.join(lines)
        plain_text = strip_markdown(content)
        
        return BlockData(
            block_id=uuid.uuid4(),
            block_type="code",
            heading_level=None,
            content_md=content,
            plain_text=plain_text,
            content_hash=hash_content(content),
            order_index=0,
            parent_heading_block_id=parent_id
        )
    
    def _create_list_block(self, lines: List[str], heading_stack: List) -> BlockData:
        """创建列表块"""
        parent_id = heading_stack[-1][1] if heading_stack else None
        content = '\n'.join(lines)
        plain_text = strip_markdown(content)
        
        return BlockData(
            block_id=uuid.uuid4(),
            block_type="list",
            heading_level=None,
            content_md=content,
            plain_text=plain_text,
            content_hash=hash_content(content),
            order_index=0,
            parent_heading_block_id=parent_id
        )
    
    def _create_table_block(self, lines: List[str], heading_stack: List) -> BlockData:
        """创建表格块"""
        parent_id = heading_stack[-1][1] if heading_stack else None
        content = '\n'.join(lines)
        plain_text = strip_markdown(content)
        
        return BlockData(
            block_id=uuid.uuid4(),
            block_type="table",
            heading_level=None,
            content_md=content,
            plain_text=plain_text,
            content_hash=hash_content(content),
            order_index=0,
            parent_heading_block_id=parent_id
        )
    
    def _split_paragraph(self, text: str, heading_stack: List) -> List[BlockData]:
        """切分段落（如果过长）"""
        if len(text) <= self.max_block_size:
            return [self._create_paragraph_block(text, heading_stack)]
        
        # 按句子切分
        sentences = split_sentences(text)
        blocks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_len = len(sentence)
            
            if current_length + sentence_len > self.max_block_size and current_chunk:
                blocks.append(self._create_paragraph_block(''.join(current_chunk), heading_stack))
                current_chunk = [sentence]
                current_length = sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len
        
        if current_chunk:
            blocks.append(self._create_paragraph_block(''.join(current_chunk), heading_stack))
        
        return blocks
    
    def _collect_paragraph(self, lines: List[str], start: int) -> tuple[List[str], int]:
        """收集段落行"""
        para_lines = []
        i = start
        
        while i < len(lines):
            line = lines[i]
            
            # 遇到空行、标题、代码块、列表、表格则停止
            if not line.strip():
                break
            if extract_heading_level(line)[0] > 0:
                break
            if is_code_block(line):
                break
            if is_list_item(line):
                break
            if is_table_row(line):
                break
            
            para_lines.append(line)
            i += 1
        
        return para_lines, i
    
    def _collect_code_block(self, lines: List[str], start: int) -> tuple[List[str], int]:
        """收集代码块"""
        code_lines = [lines[start]]  # 包含开始的 ```
        i = start + 1
        
        while i < len(lines):
            code_lines.append(lines[i])
            if is_code_block(lines[i]):
                i += 1
                break
            i += 1
        
        return code_lines, i
    
    def _collect_list(self, lines: List[str], start: int) -> tuple[List[str], int]:
        """收集列表"""
        list_lines = []
        i = start
        
        while i < len(lines) and (is_list_item(lines[i]) or (lines[i].strip() and lines[i].startswith('  '))):
            list_lines.append(lines[i])
            i += 1
        
        return list_lines, i
    
    def _collect_table(self, lines: List[str], start: int) -> tuple[List[str], int]:
        """收集表格"""
        table_lines = []
        i = start
        
        while i < len(lines) and is_table_row(lines[i]):
            table_lines.append(lines[i])
            i += 1
        
        return table_lines, i
    
    def _update_heading_stack(self, stack: List, level: int, block_id: uuid.UUID):
        """更新标题栈"""
        # 移除同级或更低级的标题
        while stack and stack[-1][0] >= level:
            stack.pop()
        
        # 添加当前标题
        stack.append((level, block_id))
