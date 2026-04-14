# LOF033_html_generator.py - HTML生成模块
import datetime

class HtmlGenerator:
    """HTML生成类"""
    
    def __init__(self):
        """初始化HTML生成器"""
        self.css_styles = """
        <style>
            :root {
                --primary-color: #2563eb; --primary-light: #dbeafe; --primary-dark: #1d4ed8;
                --secondary-color: #64748b; --secondary-light: #f8fafc; --secondary-dark: #334155;
                --bg-color: #f1f5f9; --card-bg: #ffffff;
                --pos-color: #16a34a; --pos-light: #dcfce7; --neg-color: #dc2626; --neg-light: #fee2e2;
                --border-color: #cbd5e1; --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
                --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
                --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1);
                --radius-sm: 0.25rem; --radius-md: 0.375rem; --radius-lg: 0.5rem; --radius-xl: 0.75rem;
                --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", Roboto, "Helvetica Neue", Helvetica, Arial, sans-serif;
                --font-mono: 'JetBrains Mono', 'Consolas', 'Monaco', 'Courier New', monospace;
                /* 现代淡色系主题 */
                --theme-etf-bg: #f0f8ff; --theme-etf-border: #bae6fd; --theme-etf-text: #0284c7;
                --theme-fut-bg: #fffaf0; --theme-fut-border: #fed7aa; --theme-fut-text: #c2410c;
                --theme-pure-bg: #f2fbf5; --theme-pure-border: #bbf7d0; --theme-pure-text: #15803d;
                --theme-base-bg: #f8fafc; --theme-base-border: #e2e8f0; --theme-base-text: #475569;
            }
            
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            
            body {
                font-family: var(--font-sans);
                background-color: var(--bg-color);
                color: #1e293b;
                line-height: 1.5;
                padding: 20px;
                font-size: 14px;
            }
            
            .container {
                max-width: 98%;
                margin: 0 auto;
            }
            
            /* 卡片样式 */
            .card {
                background: var(--card-bg);
                border-radius: var(--radius-lg);
                box-shadow: var(--shadow-md);
                overflow: hidden;
                margin-bottom: 20px;
                border: 1px solid var(--border-color);
                transition: all 0.3s ease;
            }
            
            .card:hover {
                box-shadow: var(--shadow-lg);
                transform: translateY(-2px);
            }
            
            /* 顶部导航栏 */
            .top-bar {
                display: flex;
                justify-content: center;
                align-items: center;
                gap: 30px;
                margin-bottom: 20px;
                position: sticky;
                top: 0;
                background-color: var(--bg-color);
                z-index: 100;
                padding: 15px 0;
                border-bottom: 1px solid var(--border-color);
                backdrop-filter: blur(8px);
            }
            
            .app-title {
                font-size: 28px;
                font-weight: 700;
                color: var(--primary-color);
                margin: 0;
                text-align: center;
            }
            
            .main-date-tag {
                background: var(--primary-light);
                color: var(--primary-dark);
                padding: 6px 16px;
                border-radius: var(--radius-full, 9999px);
                font-size: 14px;
                font-weight: 600;
                border: 1px solid var(--primary-light);
            }
            
            /* 管理面板 */
            .admin-panel {
                background: var(--card-bg);
                border: 1px solid var(--border-color);
                border-radius: var(--radius-lg);
                padding: 16px 20px;
                margin-bottom: 20px;
                display: flex;
                justify-content: center;
                flex-wrap: wrap;
                gap: 16px;
                align-items: center;
                box-shadow: var(--shadow-sm);
            }
            
            .admin-status {
                font-size: 13px;
                color: var(--secondary-color);
                display: flex;
                gap: 16px;
                flex-wrap: wrap;
                align-items: center;
            }
            
            .admin-btn {
                border: 1px solid var(--border-color);
                background: var(--card-bg);
                color: var(--secondary-dark);
                padding: 8px 16px;
                border-radius: var(--radius-md);
                cursor: pointer;
                font-size: 13px;
                font-weight: 500;
                transition: all 0.2s ease;
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }
            
            .admin-btn:hover {
                background: var(--secondary-light);
                border-color: var(--secondary-color);
                transform: translateY(-1px);
            }
            
            .admin-btn.primary {
                background: var(--primary-color);
                color: white;
                border: none;
                box-shadow: var(--shadow-sm);
            }
            
            .admin-btn.primary:hover {
                background: var(--primary-dark);
                box-shadow: var(--shadow-md);
            }
            
            .admin-msg {
                font-size: 13px;
                color: var(--secondary-color);
                min-width: 200px;
                text-align: center;
            }
            
            /* 头部信息栏 */
            .header-info-bar {
                display: flex;
                justify-content: space-around;
                align-items: center;
                background-color: var(--secondary-light);
                padding: 16px 20px;
                border-bottom: 1px solid var(--border-color);
                font-size: 14px;
                color: var(--secondary-dark);
                gap: 20px;
            }
            
            .header-info-bar > div {
                text-align: center;
                flex: 1;
            }
            
            /* 状态栏 */
            .status-bar {
                display: flex;
                flex-wrap: wrap;
                gap: 12px;
                align-items: center;
                padding: 12px 20px;
                border-bottom: 1px solid var(--border-color);
                background: var(--card-bg);
                font-size: 13px;
                color: var(--secondary-dark);
            }
            
            .status-item {
                display: inline-flex;
                gap: 8px;
                align-items: center;
                padding: 6px 12px;
                border-radius: var(--radius-full, 9999px);
                border: 1px solid var(--border-color);
                background: var(--secondary-light);
                transition: all 0.2s ease;
            }
            
            .status-item:hover {
                background: var(--card-bg);
                box-shadow: var(--shadow-sm);
            }
            
            .status-dot {
                width: 10px;
                height: 10px;
                border-radius: 50%;
                display: inline-block;
                box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.8);
            }
            
            .status-ok { background: var(--pos-color); }
            .status-degraded { background: #f59e0b; }
            .status-error { background: var(--neg-color); }
            .status-idle { background: var(--secondary-color); }
            .status-unknown { background: #94a3b8; }
            
            /* 表格样式 */
            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 13px;
            }
            
            th {
                background-color: var(--primary-light);
                color: var(--primary-dark);
                font-weight: 600;
                padding: 10px 6px;
                text-align: center;
                border-bottom: 2px solid var(--primary-color);
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            td {
                padding: 8px 6px;
                border-bottom: 1px solid var(--border-color);
                text-align: center;
                vertical-align: middle;
                font-size: 13px;
                transition: all 0.2s ease;
            }
            
            tr:hover {
                background-color: var(--secondary-light);
            }
            
            /* 数字字体 */
            .num-font {
                font-family: var(--font-mono);
                font-weight: 600;
            }
            
            /* 负值样式 */
            .neg-value {
                color: var(--neg-color) !important;
            }
            
            /* 类型标签 */
            .type-tag {
                display: inline-block;
                padding: 4px 12px;
                border-radius: var(--radius-full, 9999px);
                font-size: 12px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .tag-gold {
                background: linear-gradient(135deg, #ffd700, #ffed4e);
                color: #2c3e50;
                border: 1px solid #ffd700;
            }
            
            .tag-oil {
                background: linear-gradient(135deg, #795548, #a1887f);
                color: #fff;
                border: 1px solid #795548;
            }
            
            .tag-other {
                background: linear-gradient(135deg, #eceff1, #cfd8dc);
                color: #546e7a;
                border: 1px solid #cfd8dc;
            }
            
            /* 日期提示 */
            .base-date-hint {
                display: block;
                font-size: 11px;
                color: var(--secondary-color);
                margin-top: 4px;
                font-weight: normal;
            }
            
            /* 强调文本 */
            .emphasize {
                font-weight: 700;
                color: #1e293b;
                font-size: 15px;
                margin: 0 6px;
            }
            
            /* 历史页面头部 */
            .history-header {
                background-color: var(--primary-light);
                color: var(--primary-dark);
                padding: 20px 24px;
                border-bottom: 1px solid var(--primary-color);
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
            
            .back-btn {
                cursor: pointer;
                background: var(--primary-color);
                border: none;
                padding: 10px 28px;
                border-radius: var(--radius-md);
                font-size: 14px;
                font-weight: 600;
                color: #fff;
                text-decoration: none;
                margin-left: auto;
                display: inline-flex;
                align-items: center;
                gap: 8px;
                box-shadow: var(--shadow-md);
                transition: all 0.2s ease;
            }
            
            .back-btn:hover {
                background: var(--primary-dark);
                transform: translateY(-2px);
                box-shadow: var(--shadow-lg);
            }
            
            /* 验证行 */
            .verify-row {
                display: none;
                background-color: var(--secondary-light);
            }
            
            /* 验证包装器 */
            .verify-wrapper {
                padding: 20px;
                border-left: 4px solid var(--primary-color);
                margin: 16px 24px;
                background: var(--primary-light);
                border-radius: var(--radius-md);
                border: 1px solid var(--primary-light);
            }
            
            /* 检查表格 */
            .check-table {
                width: 100%;
                border: 1px solid var(--border-color);
                margin-top: 12px;
                background: var(--card-bg);
                border-radius: var(--radius-md);
                overflow: hidden;
            }
            
            .check-table th {
                background: var(--secondary-light);
                color: var(--secondary-dark);
                font-size: 12px;
                padding: 10px;
                border: 1px solid var(--border-color);
                text-align: center;
            }
            
            .check-table td {
                padding: 10px;
                border: 1px solid var(--border-color);
                text-align: center;
                font-family: var(--font-mono);
                font-size: 13px;
            }
            
            /* 估算列 */
            .col-est {
                background-color: rgba(255, 248, 225, 0.5);
                font-weight: 600;
                border-left: 2px solid #f59e0b;
                color: #92400e;
            }
            
            /* 涨跌 pill */
            .pill {
                display: inline-block;
                padding: 3px 10px;
                border-radius: var(--radius-full, 9999px);
                font-size: 11px;
                font-weight: 700;
                margin-left: 8px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .pill-up {
                background-color: var(--pos-light);
                color: var(--pos-color);
                border: 1px solid var(--pos-light);
            }
            
            .pill-down {
                background-color: var(--neg-light);
                color: var(--neg-color);
                border: 1px solid var(--neg-light);
            }
            
            /* 页面部分 */
            .page-section {
                display: none;
                animation: fadeIn 0.3s ease-in-out;
            }
            
            .page-section.active {
                display: block;
            }
            
            /* 验证按钮 */
            .btn-verify {
                padding: 6px 16px;
                border: 1px solid var(--border-color);
                background: var(--card-bg);
                border-radius: var(--radius-md);
                cursor: pointer;
                font-size: 12px;
                font-weight: 500;
                transition: all 0.2s ease;
            }
            
            .btn-verify:hover {
                background: var(--secondary-light);
                border-color: var(--secondary-color);
            }
            
            /* 溢价套利指示灯样式 */
            .arb-light {
                display: inline-block;
                width: 16px;
                height: 16px;
                border-radius: 50%;
                margin-left: 10px;
                vertical-align: -3px;
                box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.8);
            }
            
            .arb-light-red {
                background-color: var(--neg-color);
                box-shadow: 0 0 12px var(--neg-color), 0 0 0 2px rgba(255, 255, 255, 0.8);
                animation: pulse-red 1.5s infinite;
            }
            
            .arb-light-green {
                background-color: var(--pos-color);
                opacity: 0.8;
            }
            
            /* 可点击单元格样式 */
            .clickable-cell {
                cursor: pointer;
                transition: all 0.2s ease;
                position: relative;
            }
            
            .clickable-cell:hover {
                background-color: rgba(245, 158, 11, 0.15) !important;
                z-index: 1;
            }
            
            .clickable-cell.col-realtime-bg:hover {
                background-color: rgba(33, 150, 243, 0.15) !important;
            }

            /* 添加高度区分的主面板列底色 */
            .col-static-bg { background-color: #fffdf5; border-right: 1px dashed #fce3b8; }
            .col-static-bg-th { background-color: #ffecd2 !important; border-bottom: 2px solid #fb8c00 !important; color: #e65100 !important; }
            
            .col-realtime-bg { background-color: #f0f7ff; }
            .col-realtime-bg-th { background-color: #e0efff !important; border-bottom: 2px solid #2196f3 !important; color: #1565c0 !important; }

            /* 历史对账页面的数据区分底色 */
            .col-etf-bg { background-color: #f0fdf4 !important; border-left: 1px dashed #dcfce7; }
            .col-etf-bg-th { background-color: #dcfce7 !important; border-bottom: 2px solid #22c55e !important; color: #166534 !important;}
            
            .col-future-bg { background-color: #fdf4ff !important; border-left: 1px dashed #fce7f3; }
            .col-future-bg-th { background-color: #fce7f3 !important; border-bottom: 2px solid #ec4899 !important; color: #991b1b !important;}
            
            /* 动画效果 */
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            
            @keyframes pulse-red {
                0% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.7), 0 0 0 2px rgba(255, 255, 255, 0.8); }
                70% { box-shadow: 0 0 0 12px rgba(220, 38, 38, 0), 0 0 0 2px rgba(255, 255, 255, 0.8); }
                100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0), 0 0 0 2px rgba(255, 255, 255, 0.8); }
            }
            
            /* 响应式设计 */
            @media (max-width: 768px) {
                .top-bar {
                    flex-direction: column;
                    gap: 10px;
                    padding: 10px 0;
                }
                
                .header-info-bar {
                    flex-direction: column;
                    gap: 10px;
                    text-align: center;
                }
                
                .admin-panel {
                    flex-direction: column;
                    align-items: stretch;
                }
                
                .admin-status {
                    justify-content: center;
                }
                
                .admin-btn {
                    justify-content: center;
                }
                
                table {
                    font-size: 12px;
                }
                
                th, td {
                    padding: 8px 4px;
                }
            }
        </style>
        """
        
        self.js_scripts = """
        <script>
            function showDetail(id) {
                var targets = document.getElementsByClassName('page-section');
                for(var i=0; i<targets.length; i++) {
                    targets[i].classList.remove('active');
                }
                var targetPage = document.getElementById(id);
                if (targetPage) {
                    targetPage.classList.add('active');
                }
                window.scrollTo(0,0);
                
                // 二级页面只显示静态历史数据，不显示实时数据
            }
            function goHome() {
                var pages = document.getElementsByClassName('page-section');
                for(var i=0; i<pages.length; i++) {
                    pages[i].classList.remove('active');
                }
                document.getElementById('page-home').classList.add('active');
                window.scrollTo(0,0);
            }
            function toggleVerify(id) {
                var row = document.getElementById('verify-' + id);
                row.style.display = (row.style.display === 'table-row') ? 'none' : 'table-row';
            }
            function updateNightPrices() {
                var input = document.getElementById('night-price-input').value;
                var prices = parseNightPrices(input);
                
                // 更新ETF价格
                if (prices.GLD) {
                    document.getElementById('gld-price').value = prices.GLD;
                }
                if (prices.USO) {
                    document.getElementById('uso-price').value = prices.USO;
                }
                if (prices.XOP) {
                    document.getElementById('xop-price').value = prices.XOP;
                }
                if (prices.SLV) {
                    document.getElementById('slv-price').value = prices.SLV;
                }
                
                // 更新基金的实时价格和估值
                window.calculateRealTimeValues();
            }
            function parseNightPrices(input) {
                var prices = {};
                var parts = input.split(',');
                parts.forEach(function(part) {
                    var kv = part.trim().split('=');
                    if (kv.length == 2) {
                        var key = kv[0].trim();
                        var value = parseFloat(kv[1].trim());
                        if (!isNaN(value)) {
                            prices[key] = value;
                        }
                    }
                });
                return prices;
            }
            function updateAllFunds() {
                // 这里可以添加更新基金数据的逻辑
                // 包括ETF实时价、ETF实时估值、ETF实时溢价
                // 以及期货实时价、期货实时估值、期货实时溢价
            }
            function fetchStatus() {
                var bar = document.getElementById('status-bar');
                if (!bar) return;
                fetch('/api/status')
                    .then(function(r){ return r.json(); })
                    .then(function(data){
                        var sources = data.sources || {};
                        var labels = {
                            ib_night: 'IB夜盘',
                            sina_futures: '新浪期货',
                            eastmoney_sse: '东财SSE',
                            sina_lof: 'LOF实时',
                            basic_csv: '基础CSV'
                        };
                        var html = '<strong>数据源状态</strong>';
                        Object.keys(labels).forEach(function(k){
                            var s = sources[k] || {status:'unknown', message:'未检测', ts:''};
                            var cls = 'status-' + (s.status || 'unknown');
                            var title = (s.message || '') + (s.ts ? (' @ ' + s.ts) : '');
                            html += '<span class="status-item" title="' + title + '">'
                                 + '<span class="status-dot ' + cls + '"></span>'
                                 + labels[k] + '</span>';
                        });
                        bar.innerHTML = html;
                    })
                    .catch(function(){
                        bar.innerHTML = '<strong>数据源状态</strong> 后端未连接';
                    });
            }
            setInterval(fetchStatus, 10000);
            window.addEventListener('load', fetchStatus);

            function fetchAdminStatus() {
                fetch('/admin/status')
                    .then(function(r){ return r.json(); })
                    .then(function(data){
                        // 更新011状态
                        var data_011 = data['011'] || {};
                        var status_011 = data_011.status || '未知';
                        var last_run_011 = data_011.last_run || '';
                        document.getElementById('admin-011-status').textContent = status_011;
                        document.getElementById('admin-011-time').textContent = last_run_011 || '未运行';
                        
                        // 更新012状态
                        var data_012 = data['012'] || {};
                        var status_012 = data_012.status || '未知';
                        var last_run_012 = data_012.last_run || '';
                        document.getElementById('admin-012-status').textContent = status_012;
                        document.getElementById('admin-012-time').textContent = last_run_012 || '未运行';
                    })
                    .catch(function(){
                        console.log('维护状态获取失败');
                    });
            }
            
            function openAdminLog(task) {
                window.open(ADMIN_BASE + '/admin/stream/' + task, '_blank');
            }

            function runAdminTask(task, forceWoody) {
                var msg = document.getElementById('admin-msg');
                msg.textContent = '正在启动 ' + task + ' ...';
                var url = '/admin/run/' + task;
                if (forceWoody) {
                    url += '?force_woody=1';
                }
                fetch(url, {method: 'POST'})
                    .then(function(r){ return r.json(); })
                    .then(function(data){
                        msg.textContent = data.message || '已启动';
                        setTimeout(fetchAdminStatus, 1000);
                    })
                    .catch(function(){
                        msg.textContent = '启动失败';
                    });
            }

            function openConfigCenter() {
                window.open('/admin/config', '_blank');
            }

            setInterval(fetchAdminStatus, 15000);
            window.addEventListener('load', fetchAdminStatus);

            // 更新时间
            function updateDateTime() {
                var now = new Date();
                var year = now.getFullYear();
                var month = String(now.getMonth() + 1).padStart(2, '0');
                var day = String(now.getDate()).padStart(2, '0');
                var hours = String(now.getHours()).padStart(2, '0');
                var minutes = String(now.getMinutes()).padStart(2, '0');
                var seconds = String(now.getSeconds()).padStart(2, '0');
                var dateTimeString = year + '-' + month + '-' + day + ' ' + hours + ':' + minutes + ':' + seconds;
                var element = document.getElementById('current-date-time');
                if (element) {
                    element.textContent = dateTimeString;
                }
            }
            setInterval(updateDateTime, 1000);
            window.addEventListener('load', updateDateTime);

            // WebSocket连接
            var socket = io();

            // 连接成功
            socket.on('connect', function() {
                console.log('WebSocket连接成功');
            });

            // 断开连接
            socket.on('disconnect', function() {
                console.log('WebSocket断开连接');
            });

            // 接收期货价格更新
            socket.on('futures_price_update', function(data) {
                console.log('收到期货价格更新:', data);
                // 更新期货价格显示
                if (data.symbol === 'GC') {
                    var gcPriceElement = document.querySelector('#gc-price');
                    if (gcPriceElement) {
                        gcPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'CL') {
                    var clPriceElement = document.querySelector('#cl-price');
                    if (clPriceElement) {
                        clPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'AG0') {
                    var agPriceElement = document.querySelector('#ag0-price');
                    if (agPriceElement) {
                        agPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'NQ') {
                    var nqPriceElement = document.querySelector('#nq-price');
                    if (nqPriceElement) {
                        nqPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'ES') {
                    var esPriceElement = document.querySelector('#es-price');
                    if (esPriceElement) {
                        esPriceElement.textContent = data.price.toFixed(2);
                    }
                }
            });

            // 接收期货价格快照
            socket.on('futures_price_snapshot', function(data) {
                console.log('收到期货价格快照:', data);
                // 更新所有期货价格
                if (data.prices) {
                    if (data.prices.GC) {
                        var gcPriceElement = document.querySelector('#gc-price');
                        if (gcPriceElement) {
                            gcPriceElement.textContent = data.prices.GC.toFixed(2);
                        }
                    }
                    if (data.prices.CL) {
                        var clPriceElement = document.querySelector('#cl-price');
                        if (clPriceElement) {
                            clPriceElement.textContent = data.prices.CL.toFixed(2);
                        }
                    }
                    if (data.prices.AG0) {
                        var agPriceElement = document.querySelector('#ag0-price');
                        if (agPriceElement) {
                            agPriceElement.textContent = data.prices.AG0.toFixed(2);
                        }
                    }
                    if (data.prices.NQ) {
                        var nqPriceElement = document.querySelector('#nq-price');
                        if (nqPriceElement) {
                            nqPriceElement.textContent = data.prices.NQ.toFixed(2);
                        }
                    }
                    if (data.prices.ES) {
                        var esPriceElement = document.querySelector('#es-price');
                        if (esPriceElement) {
                            esPriceElement.textContent = data.prices.ES.toFixed(2);
                        }
                    }
                }
            });
        </script>
        """

    
    def format_color(self, val):
        """格式化颜色"""
        cls = "neg-value" if val < -0.0001 else ""
        return cls, f"{val:+.2f}%"
    
    def pill_html(self, v_c, v_p, is_n=False):
        """生成变化百分比标签"""
        # 处理v_c或v_p为非数字的情况
        if not isinstance(v_c, (int, float)) or not isinstance(v_p, (int, float)):
            return '<span style="color:#999;font-size:11px">(未公布)</span>' if is_n else '-'
        if v_p <= 0.001 or v_c <= 0.001:
            return '<span style="color:#999;font-size:11px">(未公布)</span>' if is_n else '-'
        try:
            pct = (v_c / v_p - 1) * 100
            cls = "pill-up" if pct >= 0 else "pill-down"
            return f'<span class="pill {cls}">{pct:+.2f}%</span>'
        except (ValueError, ZeroDivisionError):
            return '<span style="color:#999;font-size:11px">(计算错误)</span>' if is_n else '-'
    
    def generate_header(self, global_date_str, today_exchange_rate, ib_night_prices, ib_status_message):
        """生成HTML头部"""
        header = f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>LOF基金套利监控</title>
            {self.css_styles}
            <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.6.1/socket.io.min.js"></script>
            {self.js_scripts}
        </head>
        <body>
            <div class="container">


        """
        return header
    
    def generate_footer(self):
        """生成HTML尾部"""
        footer = """
            </div>
        </body>
        </html>
        """
        return footer
