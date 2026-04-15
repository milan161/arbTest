# LOF基金信息输入工具
# 版本: 1.0.0
# 最后修改时间: 2026-02-22

from flask import Flask, render_template_string, request, redirect, url_for, flash
import yaml
import os
from datetime import datetime
import socket

app = Flask(__name__)
app.secret_key = "lof_config_manager"

# 配置文件路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "lof_config.yaml")

# 市场配置
MARKETS = {
    "US": {"label": "美国 (US)", "curr": "USD", "exch": "SMART"},
    "CHF": {"label": "瑞士 (Swiss)", "curr": "CHF", "exch": "SMART"},
    "JPY": {"label": "日本 (JP)", "curr": "JPY", "exch": "TSEJ"},
    "HKD": {"label": "香港 (HK)", "curr": "HKD", "exch": "SEHK"},
    "EU": {"label": "欧洲 (EU)", "curr": "USD", "exch": "LSE"}
}

# 锚点配置
ANCHORS = {"US": "美股收盘 (US)", "EU": "欧洲收盘时刻 (EU)", "JP": "日本收盘时刻 (JP)", "HK": "香港收盘时刻 (HK)"}

# 加载配置
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"funds": []}, None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {"funds": []}
            
            # 🚨 自动热迁移逻辑：兼容旧版 hedging_portfolio，并智能推断 trade_etf
            for fund in cfg.get('funds', []):
                if 'hedging_portfolio' in fund:
                    fund['valuation_portfolio'] = fund.pop('hedging_portfolio')
                if 'trade_etf' not in fund:
                    cat = fund.get('category', '')
                    code = str(fund.get('code', ''))
                    if cat == '黄金': fund['trade_etf'] = 'GLD'
                    elif cat == '原油' and code != '162411': fund['trade_etf'] = 'USO'
                    elif code == '162411': fund['trade_etf'] = 'XOP'
                    elif code == '161130': fund['trade_etf'] = 'QQQ'
                    elif code == '161125': fund['trade_etf'] = 'SPY'
                    else: fund['trade_etf'] = ''
                if 'trade_future' not in fund:
                    f_list = fund.get('future_hedging', [])
                    if f_list: fund['trade_future'] = f_list[0].get('symbol', '')
                    else:
                        cat = fund.get('category', '')
                        code = str(fund.get('code', ''))
                        if cat == '黄金': fund['trade_future'] = 'MGC'
                        elif cat == '原油' and code != '162411': fund['trade_future'] = 'MCL'
                        elif code == '161130': fund['trade_future'] = 'MNQ'
                        elif code == '161125': fund['trade_future'] = 'MES'
                        else: fund['trade_future'] = ''
            return cfg, None
    except Exception as e:
        return {"funds": []}, f"配置文件读取失败: {e}"

# 保存配置
def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)

# CSS样式
CSS_STYLES = """
<style>
    :root { 
        --sidebar-bg: #eef5ff; 
        --sidebar-text: #34495e;
        --accent: #3498db; 
        --bg: #f4f7fa; 
        --card-shadow: 0 4px 15px rgba(0,0,0,0.05); 
    }
    body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; background: var(--bg); margin: 0; display: flex; height: 100vh; }
    
    /* 🎨 侧边栏：浅蓝色调优化 */
    .sidebar { width: 320px; background: var(--sidebar-bg); color: var(--sidebar-text); flex-shrink: 0; display: flex; flex-direction: column; border-right: 1px solid #d0e0f0; }
    .sidebar-header { padding: 25px; border-bottom: 1px solid #d0e0f0; background: #fff; }
    .fund-link { padding: 15px 25px; color: var(--sidebar-text); text-decoration: none; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e1ebf5; transition: 0.2s; }
    .fund-link:hover { background: #fff; color: var(--accent); }
    .fund-link.active { background: #fff; color: var(--accent); font-weight: bold; box-shadow: inset 4px 0 0 var(--accent); }
    
    .badge-cat { font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; margin-right: 8px; }
    .badge-gold { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    .badge-oil { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    .badge-other { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
    .badge-index { background: #e8eaf6; color: #3f51b5; border: 1px solid #c5cae9; }
    
    .main-content { flex: 1; padding: 40px; overflow-y: auto; }
    .card { background: white; border-radius: 12px; box-shadow: var(--card-shadow); padding: 30px; margin-bottom: 25px; }
    .form-control { border: 1px solid #dee2e6; border-radius: 6px; padding: 10px; width: 100%; box-sizing: border-box; }
    
    /* TAB 系统 */
    .nav-tabs { display: flex; border-bottom: 2px solid #eee; margin-bottom: 20px; gap: 15px; font-size: 14px; }
    .nav-tab { padding: 12px 5px; cursor: pointer; color: #999; font-weight: bold; font-size: 14px; border-bottom: 3px solid transparent; transition: 0.3s; }
    .nav-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    
    .table-pro { width: 100%; border-collapse: collapse; }
    .table-pro th { background: #f8faff; padding: 12px; font-size: 12px; color: #1565c0; border-bottom: 2px solid #e3f2fd; text-align: left; }
    .table-pro td { padding: 10px; border-bottom: 1px solid #f0f0f0; }
    .btn-save { background: var(--accent); color: white; padding: 15px; border: none; border-radius: 8px; width: 100%; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.3s; }
    .btn-save:hover { background: #2980b9; }
    .btn-add { background: #fff; color: var(--accent); border: 1px dashed var(--accent); padding: 6px 15px; border-radius: 6px; cursor: pointer; font-size: 13px; }
    
    /* 表单布局 */
    .form-row { display: flex; gap: 20px; margin-bottom: 20px; }
    .form-group { flex: 1; }
    .form-group label { display: block; font-size: 13px; font-weight: bold; color: #666; margin-bottom: 5px; }
    
    /* 成功消息 */
    .success-message { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; border-radius: 4px; padding: 15px; margin-bottom: 20px; }
    .error-message { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; border-radius: 4px; padding: 15px; margin-bottom: 20px; }
    
    /* 拖拽排序相关样式 */
    .fund-link.dragging { opacity: 0.6; background: #e3f2fd; border: 1px dashed #3498db; }
    .drag-handle { cursor: grab; margin-right: 12px; color: #bdc3c7; font-size: 18px; user-select: none; }
    .drag-handle:active { cursor: grabbing; }
</style>
"""

# HTML模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>⚓ LOF 配置中心 | TRAE编码</title>
    {{ CSS_STYLES | safe }}
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h3 style="margin:0; color:#2c3e50;">⚓ LOF 配置中心</h3>
            <small style="color:#7f8c8d;">版本: V1.0 | {{ current_date }}</small>
        </div>
        <div style="flex:1; overflow-y:auto;">
            <div id="fund-list">
                {% for f in config.funds %}
                <div class="fund-link {% if active_code == f.code %}active{% endif %}" draggable="true" data-code="{{ f.code }}">
                    <span class="drag-handle" title="按住拖动以排序">☰</span>
                <a href="/edit/{{ f.code }}" style="text-decoration: none; color: inherit; flex: 1;">
                    <span>
                        <span class="badge-cat {% if f.category=='黄金' %}badge-gold{% elif f.category=='原油' %}badge-oil{% elif f.category=='指数' %}badge-index{% else %}badge-other{% endif %}">{{ f.category }}</span>
                        {{ f.name }}
                    </span>
                    <small style="opacity:0.6; font-family:monospace;">{{ f.code }}</small>
                </a>
                <form action="/delete/{{ f.code }}" method="POST" style="margin-left: 10px; display:inline;">
                    <button type="submit" onclick="return confirm('确定要删除该基金吗？此操作不可撤销。');" style="border:none; background:none; color:#e74c3c; font-size:18px; cursor:pointer;">&times;</button>
                </form>
            </div>
                {% endfor %}
            </div>
            <a href="/new" class="fund-link" style="color:#3498db; font-weight:bold; background:#fff;">+ 添加新基金档案</a>
        </div>
    </div>

    <div class="main-content">
        {% if error_message %}
        <div class="error-message">
            {{ error_message }}
        </div>
        {% endif %}

        {% if success_message %}
        <div class="success-message">
            {{ success_message }}
        </div>
        {% endif %}

        {% if fund %}
        <form action="/save" method="POST">
            <input type="hidden" name="val_tab_type" id="val_tab_type" value="{{ active_val_tab }}">
            <div class="card">
                <h3 style="margin-top:0; color:#2c3e50;">📂 基础档案: {{ fund.name }}</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label for="code">代码</label>
                        <input type="text" name="code" class="form-control" value="{{ fund.code }}" required>
                    </div>
                    <div class="form-group">
                        <label for="name">基金全称</label>
                        <input type="text" name="name" class="form-control" value="{{ fund.name }}" required>
                    </div>
                    <div class="form-group">
                        <label for="category">资产类别</label>
                        <input type="text" name="category" list="category-list" class="form-control" value="{{ fund.category }}">
                        <datalist id="category-list">
                            <option value="黄金">
                            <option value="原油">
                            <option value="指数">
                            <option value="其他">
                        </datalist>
                    </div>
                    <div class="form-group">
                        <label for="equity">基础仓位 % <span style="color:#999; font-weight:normal;">(现金比例自动按 100 - 仓位 计算)</span></label>
                        <input type="number" step="0.1" name="equity" class="form-control" value="{{ fund.holdings.equity_ratio }}">
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="nav-tabs">
                    <div class="nav-tab {% if active_val_tab=='multi' %}active{% endif %}" onclick="switchTab(event, 'tab-multi')">🌍 黄金原油商品类</div>
                    <div class="nav-tab {% if active_val_tab=='sector' %}active{% endif %}" onclick="switchTab(event, 'tab-sector')">🎯 纯ETF对冲</div>
                    <div class="nav-tab {% if active_val_tab=='index' %}active{% endif %}" onclick="switchTab(event, 'tab-index')">📊 跟踪指数</div>
                    <div class="nav-tab" onclick="switchTab(event, 'tab-future')">📈 用期货来估值</div>
                    <div class="nav-tab" onclick="switchTab(event, 'tab-holdings')">🗄️ 季报底仓归档</div>
                </div>

                <div id="tab-multi" class="tab-content {% if active_val_tab=='multi' %}active{% endif %}">
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px; align-items:center;">
                        <span style="color:#7f8c8d; font-size:13px;">🌍 <b>多区组合模型</b>：适用于黄金、原油等。因底层包含欧美多国资产，需拼接 GLD + GLD-EU 等。</span>
                        <button type="button" class="btn-add" onclick="addRow('multi-table')">+ 增加估值分量</button>
                    </div>
                    <table class="table-pro" id="multi-table">
                        <thead><tr><th>资产代码</th><th>权重 %</th><th>估值锚点</th><th>备注</th><th>操作</th></tr></thead>
                        <tbody>
                            {% for v in multi_port %}
                            <tr>
                                <td><input type="text" name="v_multi_sym[]" class="form-control" value="{{ v.symbol }}" style="font-family:monospace;"></td>
                                <td><input type="number" step="0.01" name="v_multi_w[]" class="form-control" value="{{ v.weight }}"></td>
                                <td><select name="v_multi_a[]" class="form-control">
                                    {% for k,val in anchors.items() %}
                                    <option value="{{k}}" {% if v.anchor==k %}selected{% endif %}>{{val}}</option>
                                    {% endfor %}
                                </select></td>
                                <td><input type="text" name="v_multi_n[]" class="form-control" value="{{ v.name or '' }}"></td>
                                <td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div id="tab-sector" class="tab-content {% if active_val_tab=='sector' %}active{% endif %}">
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px; align-items:center;">
                        <span style="color:#7f8c8d; font-size:13px;">🎯 <b>单一替身模型</b>：适用于油气(162411)、生科(161127)等。底层基本等效单一美股ETF（如XOP、XBI）。</span>
                        <button type="button" class="btn-add" onclick="addRow('sector-table')">+ 增加估值分量</button>
                    </div>
                    <table class="table-pro" id="sector-table">
                        <thead><tr><th>资产代码</th><th>权重 %</th><th>估值锚点</th><th>备注</th><th>操作</th></tr></thead>
                        <tbody>
                            {% for v in sec_port %}
                            <tr>
                                <td><input type="text" name="v_sec_sym[]" class="form-control" value="{{ v.symbol }}" style="font-family:monospace; color:#e67e22; font-weight:bold;"></td>
                                <td><input type="number" step="0.01" name="v_sec_w[]" class="form-control" value="{{ v.weight }}"></td>
                                <td><select name="v_sec_a[]" class="form-control">
                                    {% for k,val in anchors.items() %}
                                    <option value="{{k}}" {% if v.anchor==k %}selected{% endif %}>{{val}}</option>
                                    {% endfor %}
                                </select></td>
                                <td><input type="text" name="v_sec_n[]" class="form-control" value="{{ v.name or '' }}"></td>
                                <td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div id="tab-index" class="tab-content {% if active_val_tab=='index' %}active{% endif %}">
                    <div style="display:flex; justify-content:space-between; margin-bottom:10px; align-items:center;">
                        <span style="color:#7f8c8d; font-size:13px;">📊 <b>指数双轨模型</b>：适用于标普、纳指等宽基。盘中采用 ETF(SPY/QQQ) 替身，同时预留原版指数抓取口。</span>
                        <button type="button" class="btn-add" onclick="addRow('index-table')">+ 增加替身分量</button>
                    </div>
                    <div class="form-group" style="margin-bottom: 15px; background: #f8faff; padding: 10px; border-radius: 6px; border: 1px solid #e3f2fd;">
                        <label style="color:#1565c0; font-size:12px; margin-bottom:5px; display:block;">🔗 纯指数抓取源 URL (新浪数据接口，选填。仅作后续对账备用)</label>
                        <input type="text" name="sina_index_url" class="form-control" value="{{ fund.sina_index_url or '' }}" placeholder="例如: https://hq.sinajs.cn/list=gb_ndx" style="font-family:monospace; color:#0d47a1; font-size:13px; background:#fff;">
                    </div>
                    <table class="table-pro" id="index-table">
                        <thead><tr><th>替身资产 (如 SPY)</th><th>权重 %</th><th>估值锚点</th><th>备注</th><th>操作</th></tr></thead>
                        <tbody>
                            {% for v in idx_port %}
                            <tr>
                                <td><input type="text" name="v_idx_sym[]" class="form-control" value="{{ v.symbol }}" style="font-family:monospace; color:#2ecc71; font-weight:bold;"></td>
                                <td><input type="number" step="0.01" name="v_idx_w[]" class="form-control" value="{{ v.weight }}"></td>
                                <td><select name="v_idx_a[]" class="form-control">
                                    {% for k,val in anchors.items() %}
                                    <option value="{{k}}" {% if v.anchor==k %}selected{% endif %}>{{val}}</option>
                                    {% endfor %}
                                </select></td>
                                <td><input type="text" name="v_idx_n[]" class="form-control" value="{{ v.name or '' }}"></td>
                                <td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div id="tab-future" class="tab-content">
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px; align-items:center;">
                        <span style="color:#7f8c8d; font-size:13px;">📈 <b>期货原生映射</b>：基于CME(如GC, CL, NQ)或国内期货(如沪银)连续报价，提供无视夜盘滑点波动的实时估值锚点。</span>
                        <button type="button" class="btn-add" onclick="addFutureRow('future-table', '{{ fund.category }}')">+ 增加期货参数</button>
                    </div>
                    <table class="table-pro" id="future-table">
                        <thead><tr><th>资产代码</th><th>交割月份</th><th>权重 %</th><th>备注</th><th>操作</th></tr></thead>
                        <tbody>
                            {% for f in fund.future_hedging %}
                            <tr>
                                <td><input type="text" name="f_sym[]" class="form-control" value="{{ f.symbol }}" style="font-family:monospace;"></td>
                                <td><input type="text" name="f_month[]" class="form-control" value="{{ f.delivery_month }}"></td>
                                <td><input type="number" step="0.01" name="f_w[]" class="form-control" value="{{ f.weight }}"></td>
                                <td><input type="text" name="f_n[]" class="form-control" value="{{ f.name or '' }}"></td>
                                <td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <div id="tab-holdings" class="tab-content">
                    <div style="display:flex; justify-content:space-between; margin-bottom:15px; align-items:center;">
                        <span style="color:#7f8c8d; font-size:13px;">🗄️ <b>真实底仓归档</b>：记录基金季报披露的真实底层资产明细。盘中不调用，仅作深度校准的“压舱石”。</span>
                        <button type="button" class="btn-add" onclick="addRow('hold-table')">+ 增加原始持仓</button>
                    </div>
                    <table class="table-pro" id="hold-table">
                        <thead><tr><th>资产代码</th><th>权重 %</th><th>所属市场</th><th>备注</th><th>操作</th></tr></thead>
                        <tbody>
                            {% for p in fund.holdings_portfolio %}
                            <tr>
                                <td><input type="text" name="p_sym[]" class="form-control" value="{{ p.symbol }}" style="font-family:monospace;"></td>
                                <td><input type="number" step="0.01" name="p_w[]" class="form-control" value="{{ p.weight }}"></td>
                                <td><select name="p_m[]" class="form-control">
                                    {% for k,v in markets.items() %}
                                    <option value="{{k}}" {% if p.currency==v.curr %}selected{% endif %}>{{v.label}}</option>
                                    {% endfor %}
                                </select></td>
                                <td><input type="text" name="p_n[]" class="form-control" value="{{ p.name or '' }}"></td>
                                <td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="card">
                <h3 style="margin-top:0; color:#c0392b;">⚔️ 实盘交易载体 (用于沙盘一键打单)</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label for="trade_etf">实盘交易 ETF <span style="color:#999; font-weight:normal;">(如 GLD, XOP)</span></label>
                        <input type="text" name="trade_etf" list="trade-etf-list" class="form-control" value="{{ fund.trade_etf }}" style="font-family:monospace; font-weight:bold; color:#1565c0;">
                        <datalist id="trade-etf-list">
                            <option value="GLD">黄金</option> <option value="USO">原油</option> <option value="XOP">油气</option>
                            <option value="SPY">标普500</option> <option value="QQQ">纳指100</option> <option value="XBI">标普生物</option> <option value="SLV">白银</option>
                        </datalist>
                    </div>
                    <div class="form-group">
                        <label for="trade_future">实盘交易 期货 <span style="color:#999; font-weight:normal;">(如 MGC, MCL)</span></label>
                        <input type="text" name="trade_future" list="trade-future-list" class="form-control" value="{{ fund.trade_future }}" style="font-family:monospace; font-weight:bold; color:#e65100;">
                        <datalist id="trade-future-list">
                            <option value="MGC">微型黄金</option> <option value="MCL">微型原油</option> <option value="MES">微型标普</option>
                            <option value="MNQ">微型纳指</option> <option value="GC">黄金主连</option> <option value="CL">原油主连</option> <option value="沪银Ag">国内沪银</option>
                        </datalist>
                    </div>
                </div>
            </div>
            <button type="submit" class="btn-save">💾 保存双轨配置并更新 YAML 数据库</button>
        </form>
        {% else %}
        <div style="text-align:center; padding-top:150px; color:#bdc3c7;">
            <h2 style="font-weight:300;">⬅️ 请从侧边栏选择基金进行编辑</h2>
        </div>
        {% endif %}
    </div>

    <script>
        function switchTab(e, id) {
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            e.target.classList.add('active');
            document.getElementById(id).classList.add('active');
            
            let tabType = 'multi';
            if (id === 'tab-sector') tabType = 'sector';
            else if (id === 'tab-index') tabType = 'index';
            const tabInput = document.getElementById('val_tab_type');
            if (tabInput) tabInput.value = tabType;
        }
        function addRow(tid) {
            const tb = document.querySelector('#'+tid+' tbody');
            const r = tb.insertRow();
            if(tid==='multi-table') {
                r.innerHTML = `<td><input type="text" name="v_multi_sym[]" class="form-control" style="font-family:monospace;"></td><td><input type="number" step="0.01" name="v_multi_w[]" class="form-control"></td><td><select name="v_multi_a[]" class="form-control">{% for k,val in anchors.items() %}<option value="{{k}}">{{val}}</option>{% endfor %}</select></td><td><input type="text" name="v_multi_n[]" class="form-control"></td><td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>`;
            } else if(tid==='sector-table') {
                r.innerHTML = `<td><input type="text" name="v_sec_sym[]" class="form-control" style="font-family:monospace; color:#e67e22; font-weight:bold;"></td><td><input type="number" step="0.01" name="v_sec_w[]" class="form-control" value="100.0"></td><td><select name="v_sec_a[]" class="form-control">{% for k,val in anchors.items() %}<option value="{{k}}">{{val}}</option>{% endfor %}</select></td><td><input type="text" name="v_sec_n[]" class="form-control"></td><td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>`;
            } else if(tid==='index-table') {
                r.innerHTML = `<td><input type="text" name="v_idx_sym[]" class="form-control" style="font-family:monospace; color:#2ecc71; font-weight:bold;"></td><td><input type="number" step="0.01" name="v_idx_w[]" class="form-control" value="100.0"></td><td><select name="v_idx_a[]" class="form-control">{% for k,val in anchors.items() %}<option value="{{k}}">{{val}}</option>{% endfor %}</select></td><td><input type="text" name="v_idx_n[]" class="form-control"></td><td style="text-align:center;"><button type="button" onclick="this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>`;
            } else {
                r.innerHTML = `<td><input type="text" name="p_sym[]" class="form-control"></td><td><input type="number" step="0.01" name="p_w[]" class="form-control"></td><td><select name="p_m[]" class="form-control">{% for k,v in markets.items() %}<option value="{{k}}">{{v.label}}</option>{% endfor %}</select></td><td><input type="text" name="p_n[]" class="form-control"></td><td style="text-align:center;"><button type="button" onclick="if(confirm('确定要删除该原始持仓吗？')) this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>`;
            }
        }

        function addFutureRow(tid, category) {
            const tb = document.querySelector('#'+tid+' tbody');
            const r = tb.insertRow();
            let symbolOptions = '';
            
            if(category === '黄金') {
                symbolOptions = '<input type="text" name="f_sym[]" class="form-control" value="GC" style="font-family:monospace;">';
            } else if(category === '原油') {
                symbolOptions = `<select name="f_sym[]" class="form-control">
                    <option value="CL">CL</option>
                    <option value="QM">QM</option>
                </select>`;
            } else if(category === '指数') {
                symbolOptions = `<select name="f_sym[]" class="form-control">
                    <option value="NQ">纳指 (NQ)</option>
                    <option value="ES">标普 (ES)</option>
                </select>`;
            } else if(category === '其他') {
                symbolOptions = '<input type="text" name="f_sym[]" class="form-control" value="沪银Ag" style="font-family:monospace;">';
            } else {
                symbolOptions = '<input type="text" name="f_sym[]" class="form-control" placeholder="期货代码" style="font-family:monospace;">';
            }
            
            r.innerHTML = `
                <td>${symbolOptions}</td>
                <td><input type="text" name="f_month[]" class="form-control" placeholder="如: 2604"></td>
                <td><input type="number" step="0.01" name="f_w[]" class="form-control" value="100.00"></td>
                <td><input type="text" name="f_n[]" class="form-control" placeholder="备注"></td>
                <td style="text-align:center;"><button type="button" onclick="if(confirm('确定要删除该期货估值参数吗？')) this.parentElement.parentElement.remove()" style="border:none; background:none; color:#e74c3c; cursor:pointer; font-size:18px;">&times;</button></td>
            `;
        }
        
        // 拖拽排序功能
        document.addEventListener('DOMContentLoaded', function() {
            const list = document.getElementById('fund-list');
            let draggingEl = null;

            list.addEventListener('dragstart', function(e) {
                const target = e.target.closest('.fund-link');
                if (target && target.hasAttribute('draggable')) {
                    draggingEl = target;
                    setTimeout(() => target.classList.add('dragging'), 0);
                    e.dataTransfer.effectAllowed = 'move';
                }
            });

            list.addEventListener('dragend', function(e) {
                const target = e.target.closest('.fund-link');
                if (target) target.classList.remove('dragging');
                draggingEl = null;
                
                // 收集新顺序并保存
                const newOrder = Array.from(list.querySelectorAll('.fund-link[data-code]')).map(el => el.getAttribute('data-code'));
                fetch('/reorder', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({order: newOrder})
                }).then(res => res.json()).then(data => {
                    if(data.status !== 'success') alert('排序保存失败');
                });
            });

            list.addEventListener('dragover', function(e) {
                e.preventDefault();
                const target = e.target.closest('.fund-link');
                if (target && target !== draggingEl && target.hasAttribute('draggable')) {
                    const rect = target.getBoundingClientRect();
                    const midY = rect.top + rect.height / 2;
                    if (e.clientY < midY) target.parentNode.insertBefore(draggingEl, target);
                    else target.parentNode.insertBefore(draggingEl, target.nextSibling);
                }
            });
        });
    </script>
    <script>
            // 监听基金类别变化，自动更新期货对冲数据
            document.addEventListener('DOMContentLoaded', function() {
                const categorySelect = document.querySelector('select[name="category"]');
                if (categorySelect) {
                    categorySelect.addEventListener('change', function() {
                        const newCategory = this.value;
                        const futureTable = document.getElementById('future-table');
                        
                        if (futureTable) {
                            const rows = futureTable.querySelectorAll('tbody tr');
                            rows.forEach(function(row) {
                                const symbolInput = row.querySelector('input[name="f_sym[]"]');
                                if (symbolInput) {
                                    if (newCategory === '黄金') {
                                        symbolInput.value = 'GC';
                                    } else if (newCategory === '其他') {
                                        symbolInput.value = '沪银Ag';
                                    } else if (newCategory === '指数') {
                                        symbolInput.value = 'NQ';
                                    }
                                    // 原油类别保持不变，因为有多个选择
                                }
                            });
                        }
                    });
                }
            });
        </script>
    </body>
</html>
"""

# 排序基金列表

def sort_funds(funds):
    """
    按照类别排序基金列表：黄金 > 原油 > 其他
    """
    # 定义类别优先级
    category_order = {"黄金": 0, "原油": 1, "其他": 2}
    # 排序函数
    def sort_key(fund):
        # 首先按类别排序，然后按代码排序
        return (category_order.get(fund['category'], 999), fund['code'])
    # 排序并返回
    return sorted(funds, key=sort_key)


# 首页路由
@app.route('/')
def index():
    cfg, err = load_config()
    # 取消强制排序，尊重用户拖拽或YAML的原有物理顺序
    # cfg['funds'] = sort_funds(cfg['funds'])
    current_date = datetime.now().strftime('%Y-%m-%d')
    if cfg['funds']:
        return redirect(url_for('edit', code=cfg['funds'][0]['code']))
    return render_template_string(
        HTML_TEMPLATE, config=cfg, fund=None, active_code=None,
        success_message=None, error_message=err,
        CSS_STYLES=CSS_STYLES, markets=MARKETS, anchors=ANCHORS,
        current_date=current_date
    )

# 编辑路由
@app.route('/edit/<code>')
def edit(code):
    cfg, err = load_config()
    # cfg['funds'] = sort_funds(cfg['funds'])
    fund = next((f for f in cfg['funds'] if str(f['code']) == str(code)), None)
    
    # 智能分发：根据基金类型决定哪个 TAB 亮起，并回填数据
    active_val_tab = 'multi'
    multi_port, sec_port, idx_port = [], [], []
    if fund:
        active_val_tab = fund.get('val_tab_type')
        if not active_val_tab:
            cat = fund.get('category', '')
            fcode = str(fund.get('code', ''))
            if cat == '指数': active_val_tab = 'index'
            elif cat in ['纯ETF', '其他'] or fcode in ['162411', '161127']: active_val_tab = 'sector'
            else: active_val_tab = 'multi'
        
        if active_val_tab == 'multi': multi_port = fund.get('valuation_portfolio', [])
        elif active_val_tab == 'sector': sec_port = fund.get('valuation_portfolio', [])
        elif active_val_tab == 'index': idx_port = fund.get('valuation_portfolio', [])

    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(
        HTML_TEMPLATE, config=cfg, fund=fund, active_code=code,
        active_val_tab=active_val_tab, multi_port=multi_port, sec_port=sec_port, idx_port=idx_port,
        success_message=None, error_message=err,
        CSS_STYLES=CSS_STYLES, markets=MARKETS, anchors=ANCHORS,
        current_date=current_date
    )

# 新建路由
@app.route('/new')
def new():
    cfg, err = load_config()
    default_fund = {
        'code': '',
        'name': '',
        'category': '黄金',
        'holdings': {
            'equity_ratio': 90.0,
            'cash_ratio': 10.0
        },
            'trade_etf': '',
        'trade_future': '',
            'valuation_portfolio': [],
        'sina_index_url': '',
        'holdings_portfolio': [],
        'future_hedging': [],
        'val_tab_type': 'multi'
    }
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template_string(
        HTML_TEMPLATE, config=cfg, fund=default_fund, active_code=None,
        active_val_tab='multi', multi_port=[], sec_port=[], idx_port=[],
        success_message=None, error_message=err,
        CSS_STYLES=CSS_STYLES, markets=MARKETS, anchors=ANCHORS,
        current_date=current_date
    )

# 保存路由
@app.route('/save', methods=['POST'])
def save():
    full_cfg, _ = load_config()
    code = (request.form.get('code') or '').strip()
    trade_etf = (request.form.get('trade_etf') or '').strip().upper()
    trade_future = (request.form.get('trade_future') or '').strip()
    val_tab_type = request.form.get('val_tab_type', 'multi')
    valuation, holdings = [], []

    def to_float(val, field_name, errors):
        try:
            return float(val)
        except Exception:
            errors.append(f"{field_name} 必须是数字")
            return 0.0
    
    errors = []
    
    # 1. 智能聚合前三个 TAB 的数据，全部喂给统一的估值底层数组
    def parse_val_tab(prefix):
        syms = request.form.getlist(f'{prefix}_sym[]')
        ws = request.form.getlist(f'{prefix}_w[]')
        a_s = request.form.getlist(f'{prefix}_a[]')
        ns = request.form.getlist(f'{prefix}_n[]')
        res = []
        for i in range(len(syms)):
            sym = (syms[i] or '').strip()
            if sym:
                w = to_float(ws[i] or 0, f"估值权重[{sym}]", errors)
                if w < 0: errors.append(f"估值权重[{sym}] 不能为负")
                res.append({"symbol": sym, "weight": w, "anchor": a_s[i], "name": ns[i], "currency": "USD", "exchange": "SMART"})
        return res

    val_multi = parse_val_tab('v_multi')
    val_sec = parse_val_tab('v_sec')
    val_idx = parse_val_tab('v_idx')
    valuation = val_multi + val_sec + val_idx  # 三合一底层汇流
    
    sina_index_url = request.form.get('sina_index_url', '').strip()

    # 2. 解析持仓 Tab
    p_syms = request.form.getlist('p_sym[]')
    p_ws = request.form.getlist('p_w[]')
    p_ms = request.form.getlist('p_m[]')
    p_ns = request.form.getlist('p_n[]')
    for i in range(len(p_syms)):
        sym = (p_syms[i] or '').strip()
        if sym:
            w = to_float(p_ws[i] or 0, f"持仓权重[{sym}]", errors)
            if w < 0:
                errors.append(f"持仓权重[{sym}] 不能为负")
            m = MARKETS[p_ms[i]]
            holdings.append({"symbol": sym, "weight": w, "currency": m['curr'], "exchange": m['exch'], "name": p_ns[i]})

    # 3. 解析期货对冲 Tab
    future_hedging = []
    f_syms = request.form.getlist('f_sym[]')
    f_months = request.form.getlist('f_month[]')
    f_ws = request.form.getlist('f_w[]')
    f_ns = request.form.getlist('f_n[]')
    for i in range(len(f_syms)):
        sym = (f_syms[i] or '').strip()
        if sym:
            # 期货默认使用美国市场
            m = MARKETS['US']
            w = to_float(f_ws[i] or 0, f"期货权重[{sym}]", errors)
            if w < 0:
                errors.append(f"期货权重[{sym}] 不能为负")
            future_hedging.append({"symbol": sym, "delivery_month": f_months[i] if i < len(f_months) else '', "weight": w, "currency": m['curr'], "exchange": m['exch'], "name": f_ns[i] if i < len(f_ns) else ''})

    equity_ratio = to_float(request.form.get('equity', 90.0), "基础仓位", errors)
    if equity_ratio < 0 or equity_ratio > 100:
        errors.append("基础仓位必须在 0 到 100 之间")
    if not code:
        errors.append("基金代码不能为空")
    elif (not code.isdigit()) or len(code) != 6:
        errors.append("基金代码必须是 6 位数字")
    name_val = (request.form.get('name') or '').strip()
    if not name_val:
        errors.append("基金名称不能为空")

    new_fund = {
        "code": code, 
        "name": name_val, 
        "category": request.form.get('category'),
        "trade_etf": trade_etf,
        "trade_future": trade_future,
        "holdings": {"equity_ratio": equity_ratio, "cash_ratio": 100-equity_ratio},
        "valuation_portfolio": valuation,
        "sina_index_url": sina_index_url,
        "holdings_portfolio": holdings,
        "future_hedging": future_hedging,
        "val_tab_type": val_tab_type
    }

    if errors:
        current_date = datetime.now().strftime('%Y-%m-%d')
        # 保持用户出错前的视窗状态
        active_val_tab = val_tab_type
        
        return render_template_string(
            HTML_TEMPLATE, config=full_cfg, fund=new_fund, active_code=code,
            active_val_tab=active_val_tab, 
            multi_port=val_multi, sec_port=val_sec, idx_port=val_idx,
            success_message=None, error_message="；".join(errors),
            CSS_STYLES=CSS_STYLES, markets=MARKETS, anchors=ANCHORS,
            current_date=current_date
        )

    idx = next((i for i, f in enumerate(full_cfg['funds']) if str(f['code']) == str(code)), -1)
    if idx >= 0:
        full_cfg['funds'][idx] = new_fund
    else:
        full_cfg['funds'].append(new_fund)

    # 取消强制排序
    save_config(full_cfg)

    current_date = datetime.now().strftime('%Y-%m-%d')
    active_val_tab = val_tab_type
    
    return render_template_string(
        HTML_TEMPLATE, config=full_cfg, fund=new_fund, active_code=code,
        active_val_tab=active_val_tab, multi_port=val_multi, sec_port=val_sec, idx_port=val_idx,
        success_message='基金信息保存成功！', error_message=None,
        CSS_STYLES=CSS_STYLES, markets=MARKETS, anchors=ANCHORS,
        current_date=current_date
    )

# 删除基金路由
@app.route('/delete/<code>', methods=['POST'])
def delete(code):
    cfg, _ = load_config()
    # 过滤掉要删除的基金
    cfg['funds'] = [f for f in cfg['funds'] if str(f['code']) != str(code)]
    save_config(cfg)
    # 重定向到首页
    return redirect('/')

@app.route('/reorder', methods=['POST'])
def reorder():
    """接收前端拖拽后的新顺序，更新保存 YAML"""
    try:
        data = request.get_json()
        new_order = data.get('order', [])
        cfg, _ = load_config()
        if cfg and new_order:
            fund_dict = {str(f['code']): f for f in cfg['funds']}
            reordered_funds = []
            for code in new_order:
                if code in fund_dict:
                    reordered_funds.append(fund_dict[code])
            # 防丢机制：防止由于某种原因漏掉的基金
            for f in cfg['funds']:
                if str(f['code']) not in new_order:
                    reordered_funds.append(f)
            cfg['funds'] = reordered_funds
            save_config(cfg)
            return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
    return jsonify({"status": "error"})

# 运行应用
if __name__ == '__main__':
    # 自动选择空闲端口（从5001开始）
    port = 5001
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                break
        port += 1
    print(f"[INFO] LOF配置中心启动端口: {port}")
    app.run(debug=False, port=port)
