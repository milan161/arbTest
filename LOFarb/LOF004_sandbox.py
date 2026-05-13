# -*- coding: utf-8 -*-
# LOF004_sandbox.py - 私密沙盘与狙击面板

def generate_private_sniper_panel():
    html = """
    <div class="card" style="margin-bottom: 10px; padding: 20px; background-color: #fffdf5; border: 1px solid #ffcc80;">
        <h3 style="color: #d35400; text-align: center; margin-bottom: 20px;">🎯 私密套利狙击面板 (Legging in 实战版)</h3>
        
        <!-- 狙击控制栏 -->
        <div style="display: flex; justify-content: center; gap: 20px; margin-bottom: 20px; align-items: center; background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            <span style="font-weight:bold; color:#333;">狙击标的:</span>
            <select id="sniper-code" style="padding: 5px; border-radius: 4px; border: 1px solid #ccc; font-weight:bold; color:#1565c0;" onchange="window.initSniperPanel()">
                <option value="162411">162411 (华宝油气 - XOP)</option>
                <option value="161127">161127 (标普生物 - XBI)</option>
                <option value="161125">161125 (标普500 - SPY)</option>
                <option value="161130">161130 (纳斯达克 - QQQ)</option>
                <option value="501018">501018 (南方原油 - USO)</option>
                <option value="160719">160719 (嘉实黄金 - GLD)</option>
            </select>
            
            <div style="border-left: 2px dashed #eee; height: 30px; margin: 0 10px;"></div>
            
            <span style="font-weight:bold; color:#d35400;">⚙️ 期望折价率:</span>
            <input type="number" id="sniper-target-discount" value="-0.80" step="0.05" style="width: 70px; padding: 4px; text-align: center; border: 1px solid #ccc; border-radius: 4px; color: #d32f2f; font-weight: bold; font-family: Consolas;" oninput="delete document.getElementById('sniper-a-price').dataset.manual; delete document.getElementById('sniper-us-price').dataset.manual; window.calcSniper()"> %
            
            <span style="font-weight:bold; color:#1565c0; margin-left: 15px;">🎯 锚点数量:</span>
            <input type="number" id="sniper-anchor-qty" value="10" step="10" style="width: 70px; padding: 4px; text-align: center; border: 1px solid #ccc; border-radius: 4px; color: #1565c0; font-weight: bold; font-family: Consolas;" oninput="delete document.getElementById('sniper-us-vol').dataset.manual; delete document.getElementById('sniper-a-vol').dataset.manual; window.calcSniper()"> 股外盘
        </div>

        <!-- 三栏对称骨架布局 -->
        <div style="display: flex; gap: 20px; flex-wrap: wrap; justify-content: center; align-items: stretch;">
            
            <!-- 1. 左侧：A股深度盘口 -->
            <div style="flex: 1; min-width: 250px; max-width: 320px; background: #fff; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: var(--shadow-sm);">
                <div style="text-align: center; font-weight: bold; color: #333; margin-bottom: 12px; font-size: 15px; border-bottom: 1px solid #eee; padding-bottom: 8px;">📊 A股深度盘口 (QMT)</div>
                <table style="width: 100%; font-size: 13px; text-align: center; border-collapse: collapse; font-family: Consolas;">
                    <tbody id="sniper-order-book">
                        <tr><td colspan="4" style="color:#999; padding:30px 0;">📡 请先在下拉框选择标的以接入极速盘口...</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- 2. 中间：狙击推演结果 (决策大脑) -->
            <div style="flex: 1; min-width: 350px; max-width: 480px; background: #fff; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: var(--shadow-sm); display: flex; flex-direction: column;">
                <div style="text-align: center; font-weight: bold; color: #333; margin-bottom: 12px; font-size: 15px; border-bottom: 1px solid #eee; padding-bottom: 8px;">🎯 狙击推演计算器</div>
                <div id="sniper-result" style="font-size: 14px; line-height: 1.8; background: #f8faff; padding: 15px; border-radius: 6px; border: 1px solid #e3f2fd; flex-grow: 1;">
                    <div style="text-align:center; color:#999; padding-top:40px;">等待盘口数据接入并执行推演...</div>
                </div>
            </div>

            <!-- 3. 右侧：外盘实时盘口 (IB通道独立面板) -->
            <div style="flex: 1; min-width: 250px; max-width: 320px; background: #fff; padding: 15px; border-radius: 8px; border: 1px solid #bbdefb; box-shadow: var(--shadow-sm);">
                <div style="text-align: center; font-weight: bold; color: #1565c0; margin-bottom: 12px; font-size: 15px; border-bottom: 1px dashed #e3f2fd; padding-bottom: 8px;">🇺🇸 外盘实时盘口 (IB)</div>
                <table style="width: 100%; font-size: 13px; text-align: center; border-collapse: collapse; font-family: Consolas; margin-top: 15px;">
                    <tbody id="sniper-ib-order-book">
                        <tr><td style="color:#999; padding:30px 0;">📡 等待行情数据接入...</td></tr>
                    </tbody>
                </table>
            </div>
            
        </div>
        
        <!-- ⚔️ 独立发单控制台 (分步下单区) -->
        <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 20px; padding: 15px; background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px;">
            <div style="text-align: center; font-weight: bold; color: #333; font-size: 15px; margin-bottom: 5px;">⚡ 单腿先入 (Legging In) 交易面板</div>
            
            <!-- 第一步：美股卖空 -->
            <div style="display: flex; align-items: center; gap: 10px; background: #e3f2fd; padding: 10px 15px; border-radius: 6px; border: 1px solid #bbdefb;">
                <span style="font-weight: bold; color: #1565c0; width: 110px;">① 美股 (IB):</span>
                <span id="sniper-display-us-sym" style="font-weight:bold; color:#1565c0; width: 60px;">-</span>
                
                <span style="color: #555;">数量:</span>
                <input type="number" id="sniper-us-vol" style="width: 70px; padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-weight:bold;" value="10" step="10">
                
                <span style="color: #555;">限价:</span>
                <!-- 🌟 核心：oninput 实时触发溢价率重算 -->
                <input type="number" id="sniper-us-price" step="0.01" style="width: 90px; padding: 6px; border: 1px solid #1565c0; border-radius: 4px; color:#1565c0; font-weight:bold; font-family:Consolas;" oninput="window.calcSniperDynamicPremium()">
                
                <!-- 🌟 动态预期溢价显示 -->
                <span style="font-size: 13px; color: #666; margin-left: 15px; padding-left: 15px; border-left: 1px solid #bbdefb;">
                    以此价成交预期折价率: <b id="sniper-dynamic-prem" style="font-size: 18px;">-</b>
                </span>
                
                <div style="margin-left: auto; display: flex; gap: 8px;">
                    <button onclick="window.cancelAllIbOrders()" style="background: #fff; color: #d32f2f; border: 1px solid #ffcdd2; padding: 10px 15px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 13px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);" title="一键撤销IB所有未成交挂单" onmouseover="this.style.backgroundColor='#ffebee'" onmouseout="this.style.backgroundColor='#fff'">❌ 撤单</button>
                    <button onclick="window.executeSniperIbTrade()" style="background: #1565c0; color: white; border: none; padding: 10px 25px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 14px; box-shadow: 0 2px 4px rgba(21,101,192,0.3);">先发：挂单卖空美股</button>
                </div>
            </div>

            <!-- 第二步：A股买入 -->
            <div style="display: flex; align-items: center; gap: 10px; background: #ffebee; padding: 10px 15px; border-radius: 6px; border: 1px solid #ffcdd2;">
                <span style="font-weight: bold; color: #d32f2f; width: 110px;">② A股 (QMT):</span>
                <span id="sniper-display-a-sym" style="font-weight:bold; color:#d32f2f; width: 60px;">-</span>
                
                <span style="color: #555;">数量:</span>
                <input type="number" id="sniper-a-vol" style="width: 70px; padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-weight:bold;" value="1000">
                
                <span style="color: #555;">限价:</span>
                <!-- 🌟 A股价格改变同样触发重算 -->
                <input type="number" id="sniper-a-price" step="0.001" style="width: 90px; padding: 6px; border: 1px solid #d32f2f; border-radius: 4px; color:#d32f2f; font-weight:bold; font-family:Consolas;" oninput="window.calcSniperDynamicPremium()">
                
                <select id="sniper-broker" style="margin-left: 15px; padding:6px; border-radius:3px; border:1px solid #ffcdd2; color:#d32f2f; font-weight:bold; background:#fff;">
                    <option value="yinhe_qmt">银河QMT (8888)</option>
                    <option value="guojin_qmt">国金QMT (xtquant)</option>
                </select>

                <button onclick="window.executeSniperATrade()" style="margin-left: auto; background: #d32f2f; color: white; border: none; padding: 10px 25px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 14px; box-shadow: 0 2px 4px rgba(211,47,47,0.3);">后发：扫单买入A股</button>
            </div>
        </div>
    </div>
    """
    
    js = """
    <script>
        // 🎯 独立动态计算预期溢价率的核心函数
        window.calcSniperDynamicPremium = function() {
            var code = document.getElementById('sniper-code').value;
            var baseData = window.fundBaseData[code];
            if (!baseData) return;
            
            var aPriceInput = document.getElementById('sniper-a-price');
            var usPriceInput = document.getElementById('sniper-us-price');
            var premEl = document.getElementById('sniper-dynamic-prem');
            
            if (!aPriceInput || !usPriceInput || !premEl) return;
            
            var aPrice = parseFloat(aPriceInput.value);
            var usPrice = parseFloat(usPriceInput.value);
            
            if (isNaN(aPrice) || isNaN(usPrice) || aPrice <= 0 || usPrice <= 0) {
                premEl.textContent = '-';
                return;
            }
            
            // 提取最新汇率
            var reqSpot = (baseData.rateType === 'spot');
            var fx = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
            
            // 提取魔法兑换因子
            var calibration = baseData.latestCalibrationFactor;
            var position = baseData.position;
            var hedgeValue = baseData.hedgeValue;
            
            // 兜底逻辑
            if (!calibration || calibration <= 0) {
                if (!hedgeValue || hedgeValue <= 0) hedgeValue = baseData.etfHedgeValue; 
                if (hedgeValue && hedgeValue > 0 && position > 0) calibration = hedgeValue * position;
            }

            if (calibration && calibration > 0 && fx > 0) {
                // 原汁原味 Woody 魔法公式反推：根据你手填的美股目标价反算理论估值
                var expectedVal = baseData.baseNav * (1.0 - position) + (position / calibration) * (usPrice * fx);
                // 计算你准备买入的 A股价格 相对于该理论估值的溢价率
                var premium = (aPrice / expectedVal - 1) * 100;
                
                // 渲染到UI
                premEl.textContent = (premium >= 0 ? '+' : '') + premium.toFixed(2) + '%';
                premEl.style.color = premium >= 0 ? '#2e7d32' : '#d32f2f'; // 绿色溢价，红色折价（代表套利空间）
            } else {
                premEl.textContent = '参数缺失';
            }
        };

        window.sniperSelectedPrice = 0;
        window.sniperCurrentOb = null;
        window._sniperRenderTimer = null;

        // 监听来自 QMT 的极速盘口事件
        window.addEventListener('QmtOrderBookUpdate', function(e) {
            var code = e.detail.code;
            var orderBook = e.detail.data;
            var selectedCodeEl = document.getElementById('sniper-code');
            if (!selectedCodeEl) return;
            
            if (code === selectedCodeEl.value) {
                if (window._sniperRenderTimer) clearTimeout(window._sniperRenderTimer);
                window._sniperRenderTimer = setTimeout(function() {
                    window.sniperCurrentOb = orderBook;
                    window.renderSniperOrderBook(orderBook);
                    window.calcSniper();
                }, 100); 
            }
        });

        // 绑定首次点开页面的初始化动作
        window.initSniperPanel = function() {
            var code = document.getElementById('sniper-code').value;
            window.sniperSelectedPrice = 0; 
            
            if (window.sniperObInterval) clearInterval(window.sniperObInterval);
            if (window.sniperIbInterval) clearInterval(window.sniperIbInterval);
            
            window.pollSniperOrderBook(code);
            window.sniperObInterval = setInterval(function() {
                window.pollSniperOrderBook(code);
            }, 1000);
            
            window.updateSniperIbOrderBook();
            window.sniperIbInterval = setInterval(function() {
                window.updateSniperIbOrderBook();
            }, 1000);
        };

        // 🌟 独立刷新 IB 外盘盘口的极速函数
        window.updateSniperIbOrderBook = function() {
            var usSymEl = document.getElementById('sniper-display-us-sym');
            if (!usSymEl) return;
            var usSym = usSymEl.textContent;
            if (!usSym || usSym === '-' || usSym === '未知') return;
            
            var ibObDiv = document.getElementById('sniper-ib-order-book');
            if (!ibObDiv) return;
            
            if (window.latestIbPrices && window.latestIbPrices[usSym]) {
                var p = window.latestIbPrices[usSym];
                var bid = p.bid || 0, bidSize = p.bid_size || 0;
                var ask = p.ask || 0, askSize = p.ask_size || 0;
                
                if (bid > 0 || ask > 0) {
                    ibObDiv.innerHTML = 
                        `<tr><td style="color:#666; padding:12px 6px;">卖一(Ask)</td><td style="color:#d32f2f; font-size:18px; font-weight:bold;">$${ask > 0 ? ask.toFixed(2) : '-'}</td><td style="color:#d32f2f;">${askSize > 0 ? askSize + ' 手' : '<span style="color:#999;font-size:11px;">未知</span>'}</td></tr>
                        <tr><td colspan="3" style="border-top: 1px dashed #e3f2fd; padding: 4px 0;"></td></tr>
                        <tr><td style="color:#666; padding:12px 6px;">买一(Bid)</td><td style="color:#2e7d32; font-size:18px; font-weight:bold;">$${bid > 0 ? bid.toFixed(2) : '-'}</td><td style="color:#2e7d32;">${bidSize > 0 ? bidSize + ' 手' : '<span style="color:#999;font-size:11px;">未知</span>'}</td></tr>
                        <tr><td colspan="3" style="color:#888; font-size:11px; padding-top:25px;">实时标的: <b style="color:#1565c0;">${usSym}</b></td></tr>`;
                } else {
                    ibObDiv.innerHTML = `<tr><td style="color:#999; padding:30px 0;">📡 ${usSym} 暂无有效报价...</td></tr>`;
                }
            } else {
                ibObDiv.innerHTML = `<tr><td style="color:#999; padding:30px 0;">📡 等待 ${usSym} 行情跳动...</td></tr>`;
            }
        };

        // 🌟 核心修复：即使没有 QMT 五档盘口，也要自动降级读取主面板的现价，绝不白屏卡死！
        window.pollSniperOrderBook = function(code) {
            fetch('/api/order_book/' + code)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success' && data.data) {
                        window.sniperCurrentOb = data.data;
                        window.renderSniperOrderBook(data.data);
                    } else {
                        window.fallbackOrderBook(code);
                    }
                    window.calcSniper();
                }).catch(e => {
                    window.fallbackOrderBook(code);
                    window.calcSniper();
                });
        };

        window.fallbackOrderBook = function(code) {
            var livePriceEl = document.getElementById('realtime-price-' + code);
            var p = 0;
            if (livePriceEl) {
                var match = livePriceEl.textContent.match(/[\d.]+/);
                if (match) p = parseFloat(match[0]);
            }
            if (p > 0) {
                var fakeOb = { ask_p1: p, ask_v1: '未知', bid_p1: p, bid_v1: '未知' };
                window.sniperCurrentOb = fakeOb;
                window.renderSniperOrderBook(fakeOb);
            }
        };

        window.renderSniperOrderBook = function(book) {
            var tb = document.getElementById('sniper-order-book');
            if (!tb) return;
            var html = '';
            
            // 降级模式渲染 (仅有一档伪造数据)
            if (book.ask_v1 === '未知' || book.ask1_v === '未知') {
                var p = book.ask_p1 || book.ask1_p || 0;
                if (p > 0) {
                    var isSelected = (window.sniperSelectedPrice === p) || (window.sniperSelectedPrice === 0);
                    var rowStyle = isSelected ? 'background-color: #fff0f0; font-weight: bold;' : '';
                    html += `<tr style="${rowStyle}; cursor:pointer;" onclick="window.sniperSelectedPrice=${p}; window.renderSniperOrderBook(window.sniperCurrentOb); window.calcSniper();">
                        <td style="color:#d32f2f;">卖一</td><td style="color:#d32f2f;">${p.toFixed(3)}</td><td style="color:#d32f2f;">未知</td>
                    </tr>`;
                }
            } else {
                // 正常 5 档盘口渲染
                var asks = [];
                var bids = [];
                for (var i = 5; i >= 1; i--) {
                    var ap = book['ask_p' + i] || book['ask' + i + '_p'] || 0;
                    var av = book['ask_v' + i] || book['ask' + i + '_v'] || 0;
                    if (ap > 0) asks.push({level: i, p: ap, v: av});
                }
                for (var i = 1; i <= 5; i++) {
                    var bp = book['bid_p' + i] || book['bid' + i + '_p'] || 0;
                    var bv = book['bid_v' + i] || book['bid' + i + '_v'] || 0;
                    if (bp > 0) bids.push({level: i, p: bp, v: bv});
                }

                asks.forEach(function(ask) {
                    var isSelected = (window.sniperSelectedPrice === ask.p);
                    var rowStyle = isSelected ? 'background-color: #ffebee; font-weight: bold;' : '';
                    html += `<tr style="${rowStyle}; cursor:pointer;" onclick="window.sniperSelectedPrice=${ask.p}; window.renderSniperOrderBook(window.sniperCurrentOb); window.calcSniper();" onmouseover="this.style.backgroundColor='#ffebee'" onmouseout="this.style.backgroundColor='${isSelected ? '#ffebee' : 'transparent'}'">
                        <td style="color:#d32f2f;">卖${ask.level}</td><td style="color:#d32f2f;">${ask.p.toFixed(3)}</td><td style="color:#d32f2f;">${ask.v}</td>
                    </tr>`;
                });
                
                html += '<tr><td colspan="3" style="border-top: 1px solid #eee; border-bottom: 1px solid #eee; height: 4px; padding: 0;"></td></tr>';
                
                bids.forEach(function(bid) {
                    var isSelected = (window.sniperSelectedPrice === bid.p);
                    var rowStyle = isSelected ? 'background-color: #e8f5e9; font-weight: bold;' : '';
                    html += `<tr style="${rowStyle}; cursor:pointer;" onclick="window.sniperSelectedPrice=${bid.p}; window.renderSniperOrderBook(window.sniperCurrentOb); window.calcSniper();" onmouseover="this.style.backgroundColor='#e8f5e9'" onmouseout="this.style.backgroundColor='${isSelected ? '#e8f5e9' : 'transparent'}'">
                        <td style="color:#2e7d32;">买${bid.level}</td><td style="color:#2e7d32;">${bid.p.toFixed(3)}</td><td style="color:#2e7d32;">${bid.v}</td>
                    </tr>`;
                });
            }
            
            tb.innerHTML = html || '<tr><td colspan="3" style="color:#999; padding:30px 0;">无有效盘口数据</td></tr>';
            
            // 自动选中第一档有效卖价（如果没有手动选中的话）
            if (window.sniperSelectedPrice === 0) {
                var firstAsk = book.ask_p1 || book.ask1_p || 0;
                if (firstAsk > 0) {
                    window.sniperSelectedPrice = firstAsk;
                    window.calcSniper(); // recalculate with auto-selected price
                }
            }
        };

        window.calcSniper = function() {
            var code = document.getElementById('sniper-code').value;
            var baseData = window.fundBaseData[code];
            if (!baseData) return;
            
            var aPrice = window.sniperSelectedPrice;
            if (aPrice <= 0) return;
            
            // 将选中的 A 股价格填入下方的输入框
            var aPriceInput = document.getElementById('sniper-a-price');
            if (aPriceInput && !aPriceInput.dataset.manual) {
                aPriceInput.value = aPrice;
            }

            var discountEl = document.getElementById('sniper-target-discount');
            var targetDiscount = parseFloat(discountEl.value);
            if (isNaN(targetDiscount)) targetDiscount = -0.80;
            
            var anchorQtyEl = document.getElementById('sniper-anchor-qty');
            var anchorQty = parseInt(anchorQtyEl.value);
            if (isNaN(anchorQty)) anchorQty = 0;

            var reqSpot = (baseData.rateType === 'spot');
            var fx = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
            
            var calibration = baseData.latestCalibrationFactor;
            var position = baseData.position;
            var hedgeValue = baseData.hedgeValue;
            
            if (!calibration || calibration <= 0) {
                if (!hedgeValue || hedgeValue <= 0) hedgeValue = baseData.etfHedgeValue; 
                if (hedgeValue && hedgeValue > 0 && position > 0) calibration = hedgeValue * position;
            }

            var resEl = document.getElementById('sniper-result');
            if (!calibration || calibration <= 0 || !fx || fx <= 0) {
                resEl.innerHTML = '<div style="text-align:center; color:#d32f2f; padding-top:40px;">数据缺失 (无汇率或校准值)，无法推演</div>';
                return;
            }

            // 反推需要的美股目标价：
            // A股实盘价 / (1 + 期望折价率/100) = 理论估值
            // 理论估值 = 现金底仓 + (仓位 / 校准值) * 美股价 * 汇率
            var expectedVal = aPrice / (1 + targetDiscount / 100);
            var cashPart = baseData.baseNav * (1.0 - position);
            var requiredUsPrice = (expectedVal - cashPart) * calibration / (position * fx);

            // 推演需要的 A 股数量 = 锚点外盘数量 * 校准值
            var expectedLofQty = Math.round(anchorQty * calibration / 100) * 100;
            
            // 填充面板
            var usSym = "未知";
            if (baseData.hedgingPortfolio && baseData.hedgingPortfolio.length > 0) {
                usSym = baseData.hedgingPortfolio[0].symbol;
            }
            
            // 智能清洗带有区域后缀的变种ETF代码 (将 ^USO-EU 还原为 USO，让 IB 认识)
            var validSyms = ['GLD', 'USO', 'XOP', 'XBI', 'SPY', 'QQQ', 'SLV'];
            for (var i=0; i<validSyms.length; i++) {
                if (usSym.indexOf(validSyms[i]) !== -1) { 
                    usSym = validSyms[i]; 
                    break; 
                }
            }
            
            var usSymDisplay = document.getElementById('sniper-display-us-sym');
            if (usSymDisplay) usSymDisplay.textContent = usSym;
            var aSymDisplay = document.getElementById('sniper-display-a-sym');
            if (aSymDisplay) aSymDisplay.textContent = code;

            var usVolInput = document.getElementById('sniper-us-vol');
            if (usVolInput && !usVolInput.dataset.manual) usVolInput.value = anchorQty;
            
            var aVolInput = document.getElementById('sniper-a-vol');
            if (aVolInput && !aVolInput.dataset.manual) aVolInput.value = expectedLofQty;

            var usPriceInput = document.getElementById('sniper-us-price');
            if (usPriceInput && !usPriceInput.dataset.manual) {
                usPriceInput.value = requiredUsPrice.toFixed(2);
            }

            // 更新动态溢价显示
            window.calcSniperDynamicPremium();

            var html = `<div style="margin-bottom: 8px;">1. 当前锁定 A股 (${code}) 盘口价: <b style="color:#d32f2f; font-size:16px;">${aPrice.toFixed(3)}</b> 元</div>`;
            html += `<div style="margin-bottom: 8px;">2. 目标狙击折价率: <b style="color:#1565c0;">${targetDiscount}%</b></div>`;
            html += `<div style="margin-bottom: 8px;">3. 倒推目标理论估值: <b style="color:#333;">${expectedVal.toFixed(4)}</b></div>`;
            html += `<div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px dashed #ccc;">4. 倒推对应美股 (${usSym}) 卖空成交价需 <b>≥</b> <b style="color:#2e7d32; font-size:16px;">$${requiredUsPrice.toFixed(2)}</b></div>`;
            
            html += `<div style="margin-bottom: 8px; margin-top: 8px;">5. 资金配比: 准备打入 <b style="color:#1565c0;">${anchorQty}</b> 股 ${usSym} 空单</div>`;
            html += `<div style="margin-bottom: 8px;">6. 对应的 A股 (${code}) 扫单需求: <b style="color:#d32f2f;">${expectedLofQty}</b> 股</div>`;
            
            resEl.innerHTML = html;
            
            // 切换标的时，主动拉取并刷新一次外盘数据
            if (typeof window.updateSniperIbOrderBook === 'function') {
                window.updateSniperIbOrderBook();
            }
        };

        window.executeSniperIbTrade = function() {
            var usSym = document.getElementById('sniper-display-us-sym').textContent;
            var vol = parseInt(document.getElementById('sniper-us-vol').value);
            var price = parseFloat(document.getElementById('sniper-us-price').value);
            
            if (!usSym || usSym === '-') { alert('⚠️ 标的未初始化'); return; }
            if (!vol || vol <= 0) { alert('⚠️ 数量无效'); return; }
            if (!price || price <= 0) { alert('⚠️ 价格无效'); return; }
            
            var warningMsg = "";
            if (window.latestIbPrices && window.latestIbPrices[usSym]) {
                var p = window.latestIbPrices[usSym];
                var bid = p.bid || 0;
                var ask = p.ask || 0;
                var marketPrice = bid > 0 ? bid : ask;
                if (marketPrice > 0) {
                    var diffPct = Math.abs(price - marketPrice) / marketPrice * 100;
                    if (diffPct > 1.0) {
                        warningMsg += `\\n\\n🚨 【严重偏离警告】您输入的限价 $${price} 偏离当前盘口($${marketPrice}) 达 ${diffPct.toFixed(2)}%！请仔细检查百位/十位是否正确！！！`;
                    }
                    if (ask > 0 && price < ask) {
                        warningMsg += `\\n\\n🚨 【防误砸警告】卖空价 $${price} 低于当前卖一价 $${ask}！您定价过于激进，可能直接吃单或大幅拉低盘口！！！`;
                    }
                }
            }
            
            if (!confirm(`🚀 狙击第一步：准备在 IB [卖空] ${vol} 股 ${usSym}，限价 $${price}` + warningMsg + `\\n\\n确认发送？`)) return;
            
            fetch('http://localhost:5000/api/ib_trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'SELL', symbol: usSym, volume: vol, price: price })
            })
            .then(res => res.json())
            .then(data => { alert((data.status === 'success' ? '✅ ' : '❌ ') + data.message); })
            .catch(err => { alert('❌ 网络请求失败'); });
        };

        window.cancelAllIbOrders = function() {
            if (!confirm('🚨 撤单操作确认:\\n\\n确定要向盈透(IB)发送【一键全撤】指令，撤销所有未成交的挂单吗？\\n\\n(改价逻辑：如需改价，请先点撤单，修改价格后再重新点击挂单即可)')) return;
            
            fetch('http://localhost:5000/api/ib_cancel_all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(res => res.json())
            .then(data => { alert((data.status === 'success' ? '✅ ' : '❌ ') + data.message); })
            .catch(err => { alert('❌ 网络请求失败'); });
        };

        window.executeSniperATrade = function() {
            var code = document.getElementById('sniper-code').value;
            var broker = document.getElementById('sniper-broker').value;
            var vol = parseInt(document.getElementById('sniper-a-vol').value);
            var price = parseFloat(document.getElementById('sniper-a-price').value);
            
            if (!vol || vol <= 0 || vol % 100 !== 0) { alert('⚠️ 数量无效，须为100的整数倍'); return; }
            if (!price || price <= 0) { alert('⚠️ 价格无效'); return; }
            
            var fullSymbol = code + (code.startsWith('5') ? '.SH' : '.SZ');
            
            var warningMsg = "";
            var currentAsk = 0;
            if (window.sniperCurrentOb && (window.sniperCurrentOb.ask_p1 || window.sniperCurrentOb.ask1_p)) {
                currentAsk = window.sniperCurrentOb.ask_p1 || window.sniperCurrentOb.ask1_p;
            }
            
            var livePriceEl = document.getElementById('realtime-price-' + code);
            var livePrice = 0;
            if (livePriceEl) {
                var lpMatch = livePriceEl.textContent.match(/[\d.]+/);
                if (lpMatch) livePrice = parseFloat(lpMatch[0]);
            }
            
            var refPrice = currentAsk > 0 ? currentAsk : livePrice;
            if (refPrice > 0) {
                var diffPct = Math.abs(price - refPrice) / refPrice * 100;
                if (diffPct > 2.0) warningMsg += `\\n\\n🚨 【严重偏离警告】买入价 ￥${price} 偏离参考价(￥${refPrice}) 达 ${diffPct.toFixed(2)}%！`;
                
                if (currentAsk > 0 && price > currentAsk) {
                    warningMsg += `\\n\\n🚨 【防误吃警告】买入价 ￥${price} 高于当前卖一价 ￥${currentAsk}！将立刻跨越盘口吃单成交！！！`;
                } else if (currentAsk === 0 && livePrice > 0 && price > livePrice * 1.01) {
                    warningMsg += `\\n\\n🚨 【防误吃警告】买入价 ￥${price} 远高于市价 ￥${livePrice}！将立刻吃单成交！！！`;
                }
            }
            
            if (!confirm(`🚀 狙击第二步：准备在 ${broker} [买入] ${vol} 股 ${fullSymbol}，限价 ￥${price}` + warningMsg + `\\n\\n确认发送？`)) return;
            
            fetch('http://localhost:5000/api/trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'BUY', symbol: fullSymbol, volume: vol, price: price, broker: broker })
            })
            .then(res => res.json())
            .then(data => { alert((data.status === 'success' ? '✅ ' : '❌ ') + data.message); })
            .catch(err => { alert('❌ 网络请求失败'); });
        };
        
        // 手动干预输入框时，取消自动填入
        document.addEventListener('DOMContentLoaded', function() {
            var inputs = ['sniper-us-price', 'sniper-a-price', 'sniper-us-vol', 'sniper-a-vol'];
            inputs.forEach(function(id) {
                var el = document.getElementById(id);
                if (el) {
                    el.addEventListener('input', function() {
                        this.dataset.manual = "true";
                    });
                }
            });
            
            // 页面加载完成后，自动触发一次默认标的的初始化
            setTimeout(function() {
                if (typeof window.initSniperPanel === 'function') window.initSniperPanel();
            }, 800);
        });
    </script>
    """
    
    return html + js
