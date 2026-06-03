import os
import re

# 1. Read original file
with open('jsl/git_web_server.py', 'r', encoding='utf-8') as f:
    orig_content = f.read()

# 2. Read current file
with open('jsl/00_web_server.py', 'r', encoding='utf-8-sig') as f:
    curr_content = f.read()

# 3. Extract the templates from original
match = re.search(r'HTML_TEMPLATE = ""\"(.*?)""\"\n\nHISTORY_TEMPLATE = ""\"(.*?)""\"\n\n@app.route', orig_content, flags=re.DOTALL)
if not match:
    # Try another pattern
    match = re.search(r'HTML_TEMPLATE = """(.*?)"""\s*HISTORY_TEMPLATE = """(.*?)"""\s*@app.route', orig_content, flags=re.DOTALL)

if not match:
    print("Could not find templates in git_web_server.py")
    exit(1)

orig_html_template = match.group(1)
orig_history_template = match.group(2)

# 4. Modify the HTML_TEMPLATE to remove the data source block
# The block looks like this: <div style="margin-top: 20px; padding: 15px; background: #fff; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 12px; color: #666;">...</div>
# We can just remove it using regex.
orig_html_template = re.sub(r'<div style="margin-top: 20px; padding: 15px; background: #fff; border-radius: 4px; box-shadow: 0 1px 3px rgba\(0,0,0,0\.1\); font-size: 12px; color: #666;">.*?</div>', '', orig_html_template, flags=re.DOTALL)


# 5. Apply the aesthetic styles to HTML_TEMPLATE
new_html_styles = """    <style>
        /* 1) 字体优化：中英文/数字分离 */
        :root {
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
            --font-num: "Consolas", "Monaco", "Courier New", monospace;
        }
        
        body { 
            font-family: var(--font-sans); 
            background-color: #f7f8fa; 
            margin: 20px; 
            font-size: 13px;
        }

        /* 页头 */
        .header-bar { 
            display: flex; align-items: center; justify-content: center; gap: 30px; 
            width: 100%; margin-bottom: 20px; padding: 12px 15px; 
            background: #fff; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        }
        .header-title { font-size: 20px; font-weight: bold; color: #333;}
        .clock { font-size: 14px; color: #888; font-family: var(--font-num);}
        .refresh-btn { 
            padding: 6px 14px; background: #e0f2fe; color: #0284c7; 
            border: 1px solid #bae6fd; border-radius: 4px; cursor: pointer; 
            font-size: 13px; font-weight: bold; transition: all 0.2s;
        }
        .refresh-btn:hover { background: #bae6fd; }

        /* TAB 样式 */
        .tabs { display: flex; border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; gap: 2px;}
        .tab { 
            padding: 10px 24px; background: #f8fafc; border: 1px solid #e2e8f0; 
            border-bottom: none; cursor: pointer; font-size: 14px; font-weight: 500; 
            border-radius: 6px 6px 0 0; color: #64748b; transition: all 0.2s;
        }
        .tab.active { 
            background: #fff; color: #0ea5e9; border-color: #e2e8f0; 
            border-top: 3px solid #0ea5e9; position: relative; bottom: -2px;
            font-weight: bold;
        }
        .tab:hover:not(.active) { background: #f1f5f9; }
        .tab-content { display: none;}
        .tab-content.active { display: block;}

        /* 表格样式 */
        .jsl-table { 
            width: 100%; border-collapse: separate; border-spacing: 0; 
            background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border-radius: 6px; overflow: hidden;
        }
        /* 表头底色与字体颜色 */
        .jsl-table th { 
            background: #f1f5f9; 
            color: #334155;      
            font-weight: 600; 
            padding: 10px 6px; 
            border-bottom: 1px solid #e2e8f0; 
            text-align: right; 
            white-space: nowrap; 
            font-size: 13px; 
        }
        .jsl-table th:hover { background: #e2e8f0; }
        
        .jsl-table td { 
            padding: 8px 6px; 
            border-bottom: 1px solid #f1f5f9; 
            text-align: right; 
            font-size: 13px;
        }
        
        .jsl-table th:nth-child(1), .jsl-table th:nth-child(2), .jsl-table th:nth-child(3),
        .jsl-table td:nth-child(1), .jsl-table td:nth-child(2), .jsl-table td:nth-child(3) { 
            text-align: left; 
        }
        .jsl-table tr:hover td { background-color: #f8fafc; }
        
        /* 字体类 */
        .num-font { font-family: var(--font-num); }
        .code-text { color: #0ea5e9; text-decoration: none; font-weight: bold; font-family: var(--font-num);}
        .code-text:hover { text-decoration: underline; }
        .val-dash { color: #cbd5e1; }
        
        /* 涨跌幅颜色 */
        .red-text { color: #ef4444; font-weight: bold; font-family: var(--font-num);}
        .green-text { color: #22c55e; font-weight: bold; font-family: var(--font-num);}
        
        /* 状态标识 */
        .status-open { color: #059669; }
        .status-close { color: #ef4444; }
        .status-limited { color: #d97706; }
    </style>"""

orig_html_template = re.sub(r'<style>.*?</style>', new_html_styles, orig_html_template, flags=re.DOTALL)

# 6. Apply aesthetic styles to HISTORY_TEMPLATE
new_history_styles = """    <style>
        :root {
            --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
            --font-num: "Consolas", "Monaco", "Courier New", monospace;
        }
        body { font-family: var(--font-sans); background:#f7f8fa; margin:20px; font-size:13px; }
        .crumb { margin-bottom:12px; color:#64748b; font-size: 13px;}
        .title { font-size:20px; font-weight:700; margin:0 0 16px 0; color:#334155; }
        
        .jsl-table { width:100%; border-collapse:separate; border-spacing: 0; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.08); border-radius: 6px; overflow: hidden;}
        .jsl-table th { background:#f1f5f9; color:#334155; font-weight:600; padding:10px 6px; border-bottom:1px solid #e2e8f0; text-align:right; white-space:nowrap; font-size:13px; }
        .jsl-table td { padding:8px 6px; border-bottom:1px solid #f1f5f9; text-align:right; font-family: var(--font-num); font-size: 13px;}
        .jsl-table th:nth-child(1), .jsl-table td:nth-child(1) { text-align:center; }
        .jsl-table tr:hover td { background-color: #f8fafc; }
        
        .red-text { color:#ef4444; font-weight:bold; font-family: var(--font-num); }
        .green-text { color:#22c55e; font-weight:bold; font-family: var(--font-num); }
        .orange { color:#d97706; font-weight:bold; font-family: var(--font-num); }
        
        .pagination { margin-top:20px; text-align:center; font-family: var(--font-num);}
        .pagination a { display:inline-block; padding:6px 12px; margin:0 3px; background:#f1f5f9; color:#334155; text-decoration:none; border-radius:4px; border: 1px solid #e2e8f0;}
        .pagination a:hover { background:#e2e8f0; }
        .pagination span { padding:6px 12px; margin:0 3px; }
        .pagination .current { background:#0ea5e9; color:#fff; border-radius: 4px;}
        .pagination .disabled { background:#f8fafc; color:#cbd5e1; cursor:not-allowed; border-radius: 4px; border: 1px solid #e2e8f0;}
        .page-info { text-align:center; color:#94a3b8; margin-top:10px; font-size: 12px; }
    </style>"""
orig_history_template = re.sub(r'<style>.*?</style>', new_history_styles, orig_history_template, flags=re.DOTALL)

# Update class names in HTML_TEMPLATE
orig_html_template = orig_html_template.replace('style="{{ get_color_style(fund.change_pct) }}"', 'class="num-font {{ get_color_style(fund.change_pct) }}"')
orig_html_template = orig_html_template.replace('style="{{ get_color_style(fund.added_shares) }}"', 'class="num-font {{ get_color_style(fund.added_shares) }}"')
orig_html_template = orig_html_template.replace('style="{{ get_premium_color(fund.rt_premium) }}"', 'class="num-font {{ get_color_style(fund.rt_premium) }}"')
orig_html_template = orig_html_template.replace('style="{{ get_premium_color(fund.premium) }}"', 'class="num-font {{ get_color_style(fund.premium) }}"')
orig_html_template = orig_html_template.replace('style="{{ get_color_style(fund.idx_change_pct) }}"', 'class="num-font {{ get_color_style(fund.idx_change_pct) }}"')
orig_html_template = orig_html_template.replace('<td>{{ "%.2f"|format(fund.turnover_amt)', '<td class="num-font">{{ "%.2f"|format(fund.turnover_amt)')
orig_html_template = orig_html_template.replace('<td>{{ "%.2f"|format(fund.shares_10k)', '<td class="num-font">{{ "%.2f"|format(fund.shares_10k)')
orig_html_template = orig_html_template.replace('<td>{{ "%.2f"|format(fund.turnover_rate)', '<td class="num-font">{{ "%.2f"|format(fund.turnover_rate)')
orig_html_template = orig_html_template.replace('<td>{{ "%.4f"|format(fund.est_price)', '<td class="num-font">{{ "%.4f"|format(fund.est_price)')
orig_html_template = orig_html_template.replace('<td>{{ "%.4f"|format(fund.nav)', '<td class="num-font">{{ "%.4f"|format(fund.nav)')
orig_html_template = orig_html_template.replace('<td style="color:#666; font-size:11px;">{{ fund.nav_date', '<td class="num-font" style="color:#94a3b8; font-size:12px;">{{ fund.nav_date')

# Update class names in HISTORY_TEMPLATE
orig_history_template = orig_history_template.replace("'red'", "'red-text'").replace("'green'", "'green-text'")

# 7. Reconstruct the file safely. We replace everything from HTML_TEMPLATE to the end of the file.
# But first, we need to extract the Python code from the current file BEFORE the templates.
# The current file's templates got mashed together, so we split at HTML_TEMPLATE.
split_parts = curr_content.split('HTML_TEMPLATE = """')
python_code = split_parts[0]

# And the rest of the python code that comes after HISTORY_TEMPLATE
# Wait, in the original, @app.route is right after HISTORY_TEMPLATE
# Let's extract the route part from the original git_web_server.py since it hasn't changed.
route_part_match = re.search(r'(@app\.route.*)', orig_content, flags=re.DOTALL)
if route_part_match:
    route_part = route_part_match.group(1)
    # Ensure get_color_style uses the new names
    route_part = route_part.replace("""def get_color_style(value):
    if not isinstance(value, (int, float)) or pd.isna(value): return ""
    if value > 0: return "color: #d32f2f; font-weight: bold;"
    if value < 0: return "color: #1b5e20; font-weight: bold;"
    return "color: #333;"

def get_premium_color(value):
    if not isinstance(value, (int, float)) or pd.isna(value): return "color:#000;"
    if value >= 5: return "color: #FF0000; font-weight: bold;"
    if value >= 1: return "color: #FF4500; font-weight: bold;"
    if value > -1: return "color: #2E8B57; font-weight: bold;"
    return "color: #006400; font-weight: bold;\"""", """def get_color_style(value):
    if not isinstance(value, (int, float)) or pd.isna(value): return ""
    if value > 0: return "red-text"
    if value < 0: return "green-text"
    return ""

def get_premium_color(value):
    if not isinstance(value, (int, float)) or pd.isna(value): return ""
    if value > 0: return "red-text"
    if value < 0: return "green-text"
    return "" """)

    # Also, we need to make sure the fix to the port is applied
    route_part = route_part.replace("port = 5003", "port = 5004")
    route_part = route_part.replace("http://127.0.0.1:5003", "http://127.0.0.1:5004")

    # Combine everything
    final_content = python_code + 'HTML_TEMPLATE = """\n' + orig_html_template + '\n"""\n\nHISTORY_TEMPLATE = """\n' + orig_history_template + '\n"""\n\n' + route_part

    with open('jsl/00_web_server.py', 'w', encoding='utf-8-sig') as f:
        f.write(final_content)
    
    print("SUCCESS: Templates recovered, cleaned, and properly separated.")
else:
    print("Failed to extract routes")
