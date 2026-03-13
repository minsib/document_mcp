#!/usr/bin/env python3
"""
将Markdown文件转换为PDF
需要安装: pip install markdown weasyprint
"""

import sys
import os

def check_dependencies():
    """检查依赖是否安装"""
    try:
        import markdown
        print("✓ markdown 已安装")
    except ImportError:
        print("✗ 需要安装 markdown: pip install markdown")
        return False
    
    try:
        import weasyprint
        print("✓ weasyprint 已安装")
    except ImportError:
        print("✗ 需要安装 weasyprint: pip install weasyprint")
        return False
    
    return True

def convert_md_to_pdf(md_file, pdf_file=None):
    """转换Markdown到PDF"""
    import markdown
    from weasyprint import HTML, CSS
    
    if pdf_file is None:
        pdf_file = md_file.replace('.md', '.pdf')
    
    # 读取Markdown文件
    with open(md_file, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 转换为HTML
    html_content = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'codehilite']
    )
    
    # 添加CSS样式
    html_with_style = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: "PingFang SC", "Microsoft YaHei", "SimHei", sans-serif;
                line-height: 1.6;
                color: #333;
                font-size: 11pt;
            }}
            h1 {{
                color: #2c3e50;
                border-bottom: 3px solid #3498db;
                padding-bottom: 10px;
                margin-top: 30px;
                font-size: 24pt;
            }}
            h2 {{
                color: #34495e;
                border-bottom: 2px solid #95a5a6;
                padding-bottom: 8px;
                margin-top: 25px;
                font-size: 18pt;
            }}
            h3 {{
                color: #555;
                margin-top: 20px;
                font-size: 14pt;
            }}
            h4 {{
                color: #666;
                margin-top: 15px;
                font-size: 12pt;
            }}
            code {{
                background-color: #f4f4f4;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: "Courier New", monospace;
                font-size: 10pt;
            }}
            pre {{
                background-color: #f8f8f8;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 15px;
                overflow-x: auto;
                font-size: 9pt;
                line-height: 1.4;
            }}
            pre code {{
                background-color: transparent;
                padding: 0;
            }}
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 15px 0;
                font-size: 10pt;
            }}
            table th {{
                background-color: #3498db;
                color: white;
                padding: 10px;
                text-align: left;
                border: 1px solid #2980b9;
            }}
            table td {{
                padding: 8px;
                border: 1px solid #ddd;
            }}
            table tr:nth-child(even) {{
                background-color: #f9f9f9;
            }}
            ul, ol {{
                margin: 10px 0;
                padding-left: 30px;
            }}
            li {{
                margin: 5px 0;
            }}
            blockquote {{
                border-left: 4px solid #3498db;
                padding-left: 15px;
                margin: 15px 0;
                color: #555;
                font-style: italic;
            }}
            strong {{
                color: #2c3e50;
            }}
            a {{
                color: #3498db;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    # 转换为PDF
    print(f"正在转换 {md_file} -> {pdf_file}")
    HTML(string=html_with_style).write_pdf(pdf_file)
    print(f"✓ 转换完成: {pdf_file}")
    
    return pdf_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python convert_to_pdf.py <markdown文件> [输出pdf文件]")
        print("示例: python convert_to_pdf.py 海外博士AI客服方案.md")
        sys.exit(1)
    
    if not check_dependencies():
        print("\n请先安装依赖:")
        print("pip install markdown weasyprint")
        sys.exit(1)
    
    md_file = sys.argv[1]
    pdf_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(md_file):
        print(f"错误: 文件不存在 {md_file}")
        sys.exit(1)
    
    convert_md_to_pdf(md_file, pdf_file)
