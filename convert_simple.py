#!/usr/bin/env python3
"""
简单的Markdown转HTML工具
生成的HTML可以在浏览器中打开并打印为PDF
"""

import sys
import os

def convert_md_to_html(md_file, html_file=None):
    """转换Markdown到HTML"""
    
    if html_file is None:
        html_file = md_file.replace('.md', '.html')
    
    # 读取Markdown文件
    with open(md_file, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    try:
        import markdown
        # 使用markdown库转换
        html_body = markdown.markdown(
            md_content,
            extensions=['tables', 'fenced_code', 'codehilite']
        )
    except ImportError:
        # 如果没有markdown库，做简单的转换
        print("提示: 安装markdown库可获得更好的效果: pip install markdown")
        html_body = md_content.replace('\n\n', '</p><p>').replace('\n', '<br>')
        html_body = f'<p>{html_body}</p>'
    
    # 完整的HTML
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>海外博士AI客服方案</title>
    <style>
        @media print {{
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-size: 10pt;
            }}
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #fff;
        }}
        
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-top: 40px;
            margin-bottom: 20px;
            font-size: 28px;
        }}
        
        h2 {{
            color: #34495e;
            border-bottom: 2px solid #95a5a6;
            padding-bottom: 8px;
            margin-top: 30px;
            margin-bottom: 15px;
            font-size: 22px;
        }}
        
        h3 {{
            color: #555;
            margin-top: 25px;
            margin-bottom: 12px;
            font-size: 18px;
        }}
        
        h4 {{
            color: #666;
            margin-top: 20px;
            margin-bottom: 10px;
            font-size: 16px;
        }}
        
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "Courier New", "Monaco", "Menlo", monospace;
            font-size: 0.9em;
            color: #e74c3c;
        }}
        
        pre {{
            background-color: #f8f8f8;
            border: 1px solid #ddd;
            border-left: 4px solid #3498db;
            border-radius: 5px;
            padding: 15px;
            overflow-x: auto;
            margin: 15px 0;
        }}
        
        pre code {{
            background-color: transparent;
            padding: 0;
            color: #333;
            font-size: 13px;
            line-height: 1.5;
        }}
        
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        table th {{
            background-color: #3498db;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border: 1px solid #2980b9;
        }}
        
        table td {{
            padding: 10px 12px;
            border: 1px solid #ddd;
        }}
        
        table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        
        table tr:hover {{
            background-color: #f5f5f5;
        }}
        
        ul, ol {{
            margin: 15px 0;
            padding-left: 30px;
        }}
        
        li {{
            margin: 8px 0;
        }}
        
        blockquote {{
            border-left: 4px solid #3498db;
            padding-left: 20px;
            margin: 20px 0;
            color: #555;
            font-style: italic;
            background-color: #f9f9f9;
            padding: 15px 20px;
        }}
        
        strong {{
            color: #2c3e50;
            font-weight: 600;
        }}
        
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        
        a:hover {{
            text-decoration: underline;
        }}
        
        hr {{
            border: none;
            border-top: 2px solid #ecf0f1;
            margin: 30px 0;
        }}
        
        .print-button {{
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 24px;
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 1000;
        }}
        
        .print-button:hover {{
            background-color: #2980b9;
        }}
        
        @media print {{
            .print-button {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <button class="print-button" onclick="window.print()">打印/保存为PDF</button>
    {html_body}
    
    <script>
        // 添加打印快捷键
        document.addEventListener('keydown', function(e) {{
            if ((e.ctrlKey || e.metaKey) && e.key === 'p') {{
                e.preventDefault();
                window.print();
            }}
        }});
    </script>
</body>
</html>"""
    
    # 写入HTML文件
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"✓ 已生成HTML文件: {html_file}")
    print(f"\n使用方法:")
    print(f"1. 在浏览器中打开: {html_file}")
    print(f"2. 点击右上角的'打印/保存为PDF'按钮")
    print(f"3. 或使用快捷键 Ctrl+P (Windows) / Cmd+P (Mac)")
    print(f"4. 在打印对话框中选择'保存为PDF'")
    
    return html_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python convert_simple.py <markdown文件>")
        print("示例: python convert_simple.py 海外博士AI客服方案.md")
        sys.exit(1)
    
    md_file = sys.argv[1]
    
    if not os.path.exists(md_file):
        print(f"错误: 文件不存在 {md_file}")
        sys.exit(1)
    
    html_file = convert_md_to_html(md_file)
    
    # 尝试在浏览器中打开
    import webbrowser
    import pathlib
    file_path = pathlib.Path(html_file).absolute()
    webbrowser.open(f'file://{file_path}')
    print(f"\n已在浏览器中打开文件")
