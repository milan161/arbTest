import json

class JsGenerator:
    """生成繁杂的前端交互代码，将其从业务逻辑核心中剥离以保持整洁"""
    
    @staticmethod
    def generate_js_code(active_etfs, js_fund_base_data, calibrations_dict, ib_night_prices=None):
        ib_prices_json = json.dumps(ib_night_prices) if ib_night_prices else "{}"
        return r'''
        <script>
            // 注入Python预先计算的基金基准数据，彻底抛弃前端读CSV
            window.activeEtfs = ''' + json.dumps(active_etfs) + r''';
            window.fundBaseData = ''' + json.dumps(js_fund_base_data, ensure_ascii=False) + r''';
            window.calibData = ''' + json.dumps(calibrations_dict) + r''';
            window.latestIbPrices = ''' + ib_prices_json + r''';

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
                // 🌟 动态更新所有匹配 class 的期货价格显示
                if (data && data.symbol && data.price > 0) {
                    var className = data.symbol.toLowerCase().replace('ag0', 'ag0') + '-price';
                    var elements = document.querySelectorAll('.' + className);
                    elements.forEach(function(el) {
                        el.textContent = data.price.toFixed(2);
                    });
                }
                
                // 触发估值计算
                updateFuturesData();
            });

            // 接收期货价格快照
            socket.on('futures_price_snapshot', function(data) {
                console.log('收到期货价格快照:', data);
                // 更新所有期货价格
                if (data.prices) {
                    Object.keys(data.prices).forEach(function(symbol) {
                        var price = data.prices[symbol];
                        if (price > 0) {
                            var className = symbol.toLowerCase().replace('ag0', 'ag0') + '-price';
                            var elements = document.querySelectorAll('.' + className);
                            elements.forEach(function(el) {
                                el.textContent = price.toFixed(2);
                            });
                        }
                    });
                }
            });

            // 🌟 接收 IB 夜盘价格极速更新
            function updateIbDomPrices(prices) {
                if (!prices) return;
                var hasValidData = false;
                Object.keys(prices).forEach(function(sym) {
                    var el = document.getElementById('ib-val-' + sym.toLowerCase());
                    if (el && prices[sym] && prices[sym].bid) {
                        hasValidData = true;
                        var newPrice = prices[sym].bid.toFixed(2);
                        if (el.textContent !== newPrice) {
                            el.textContent = newPrice;
                            el.style.color = '#d32f2f';
                            setTimeout(function() { el.style.color = '#1976d2'; }, 500);
                        }
                    }
                });
                
                // 动态点亮状态指示牌 (仅当选中的是IB时才改变牌子)
                var isIbSelected = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                if (hasValidData && isIbSelected) {
                    var statusEl = document.getElementById('ib-status-text');
                    if (statusEl) {
                        statusEl.textContent = '✅ IB夜盘数据已连通更新';
                        statusEl.style.backgroundColor = '#1976d2';
                    }
                }
            }

            socket.on('ib_price_snapshot', function(data) {
                if (data && data.prices) {
                    window.latestIbPrices = window.latestIbPrices || {};
                    Object.assign(window.latestIbPrices, data.prices);
                    updateIbDomPrices(data.prices);
                    var isIb = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                    if (isIb) window.calculateRealTimeValues();
                }
            });

            socket.on('ib_price_update', function(data) {
                window.latestIbPrices = window.latestIbPrices || {};
                var pricesToUpdate = null;
                if (data && data.prices) {
                    pricesToUpdate = data.prices;
                } else if (data && data.symbol) {
                    pricesToUpdate = {};
                    pricesToUpdate[data.symbol] = data;
                } else if (data) {
                    pricesToUpdate = data;
                }
                
                if (pricesToUpdate) {
                    Object.assign(window.latestIbPrices, pricesToUpdate);
                    updateIbDomPrices(pricesToUpdate);
                    var isIb = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                    if (isIb) window.calculateRealTimeValues();
                }
            });

            // 🌟 接收 A股 五档盘口极速更新 (打通 TAB5 自留地沙盘的"最后一公里")
            socket.on('lof_order_book_update', function(data) {
                // 1. 全局缓存最新盘口数据，供沙盘随时提取
                window.latestOrderBooks = window.latestOrderBooks || {};
                window.latestOrderBooks[data.code] = data.data;
                
                // 2. 尝试直接调用沙盘的渲染函数 (如果您在 LOF004 里定义了这些函数)
                if (typeof window.renderSniperOrderBook === 'function') {
                    window.renderSniperOrderBook(data.code, data.data);
                } else if (typeof window.updateSandboxOrderBook === 'function') {
                    window.updateSandboxOrderBook(data.code, data.data);
                }
                
                // 3. 广播标准事件，供自留地 JS 监听接管
                window.dispatchEvent(new CustomEvent('QmtOrderBookUpdate', { detail: data }));
            });

            // 接收 LOF A股实时价格更新
            socket.on('lof_price_update', function(data) {
                if (data && data.code && data.price) {
                    window.latestLofPrices = window.latestLofPrices || {};
                    window.latestLofPrices[data.code] = data.price;
                    var el = document.getElementById('realtime-price-' + data.code);
                    if (el) {
                        el.textContent = data.price.toFixed(3);
                        el.style.color = '#d32f2f'; // 闪烁红字提醒更新
                        setTimeout(function() { el.style.color = ''; }, 500);
                    }

                    // [核心修正] 更新价格涨跌幅
                    var chgEl = document.getElementById('t-1-premium-' + data.code);
                    var baseData = window.fundBaseData[data.code];
                    if (chgEl && baseData && baseData.baseClosePrice > 0) {
                        var chg = (data.price / baseData.baseClosePrice - 1) * 100;
                        chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
                        chgEl.className = 'num-font premium-big ' + (chg >= 0 ? 'premium-positive' : 'premium-negative');
                        chgEl.style.color = chg >= 0 ? '#d32f2f' : '#388e3c';
                    }
                    // 更新关联的沙盘推演(如果沙盘被打开，让测试价同步跳动)
                    var tpInput = document.getElementById('sb-target-price-' + data.code);
                    if (tpInput && !document.activeElement.isSameNode(tpInput)) {
                        tpInput.value = data.price;
                    }
                    if (window.calcSandbox) window.calcSandbox(data.code);
                    if (window.calcFutureSandbox) window.calcFutureSandbox(data.code);
                    if (window.calcPureFutureSandbox) window.calcPureFutureSandbox(data.code);
                    if (window.updateSandboxRealtimePrices) window.updateSandboxRealtimePrices(data.code);
                }
            });
            
            // 接收 LOF A股价格快照 (页面刚刷新时)
            socket.on('lof_price_snapshot', function(data) {
                if (data && data.prices) {
                    window.latestLofPrices = window.latestLofPrices || {};
                    Object.keys(data.prices).forEach(function(code) {
                        var price = data.prices[code];
                        window.latestLofPrices[code] = price;
                        var el = document.getElementById('realtime-price-' + code);
                        if (el && price > 0) {
                            el.textContent = price.toFixed(3);
                        }

                        // [新增] 快照时同步更新涨跌幅
                        var chgEl = document.getElementById('t-1-premium-' + code);
                        var baseData = window.fundBaseData[code];
                        if (chgEl && baseData && baseData.baseClosePrice > 0 && price > 0) {
                            var chg = (price / baseData.baseClosePrice - 1) * 100;
                            chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
                            chgEl.className = 'num-font premium-big ' + (chg >= 0 ? 'premium-positive' : 'premium-negative');
                            chgEl.style.color = chg >= 0 ? '#d32f2f' : '#388e3c';
                        }
                    });
                }
            });

            // 获取并更新 LOF 行情数据源状态指示器
            window.updateLofSourceBadge = function() {
                fetch('/api/lof_source')
                    .then(res => res.json())
                    .then(data => {
                        var badge = document.getElementById('lof-source-badge');
                        var select = document.getElementById('lof-source-select');
                        if (badge && data.source) {
                            badge.textContent = data.source;
                            if (data.source.includes('通达信')) {
                                badge.style.color = '#2e7d32'; badge.style.borderColor = '#c8e6c9'; badge.style.background = '#e8f5e9';
                                if(select) select.value = 'tongdaxin';
                            } else if (data.source.includes('QMT')) {
                                badge.style.color = '#1565c0'; badge.style.borderColor = '#bbdefb'; badge.style.background = '#e3f2fd';
                                if(select) select.value = 'qmt';
                            } else {
                                badge.style.color = '#d32f2f'; badge.style.borderColor = '#ffcdd2'; badge.style.background = '#ffebee';
                                if(select) select.value = 'sina';
                            }
                        }
                    }).catch(err => console.error('获取LOF数据源状态失败', err));
            };
            
            window.switchLofSource = function(source) {
                var badge = document.getElementById('lof-source-badge');
                if(badge) badge.textContent = '切换中...';
                fetch('/api/set_lof_source', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: source }) })
                .then(res => res.json()).then(data => { window.updateLofSourceBadge(); }).catch(err => { if(badge) badge.textContent = '切换失败'; });
            };
            
            window.reconnectLofSource = function() {
                var badge = document.getElementById('lof-source-badge');
                if(badge) badge.textContent = '重连中...';
                fetch('/api/reconnect_lof', { method: 'POST' })
                .then(res => res.json()).then(data => { window.updateLofSourceBadge(); }).catch(err => { if(badge) badge.textContent = '重连失败'; });
            };

            // 更新时间显示
            function updateTime() {
                const now = new Date();
                const timeString = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const dateString = now.toISOString().split('T')[0];
                document.getElementById('current-date-time').textContent = `${dateString} ${timeString}`;
            }
            
            // 高效的O(1)计算实时估值函数，抛弃AJAX读取CSV的卡顿机制
            function calculateETFRealTimeValuation(fundCode, category, staticValuation) {
                var baseData = window.fundBaseData[fundCode];
                if (!baseData || !baseData.position || baseData.hedgingPortfolio.length === 0) {
                    return 0;
                }

                // 动态获取：如果在岸价要求且后台提供了在岸价，则使用在岸价；否则降级中间价
                var reqSpot = (baseData.rateType === 'spot');
                var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;

                if (!todayExchangeRate || todayExchangeRate <= 0) {
                    return 0; // 彻底没有有效汇率，强制熔断返回0
                }

                var position = baseData.position;
                var hedgeValue = baseData.hedgeValue; // 严格只取 woody API 真实传入的 hedge
                var etfCalibration = 0;

                // 严格遵循要求：只有获取到了真实 hedge，才能启用魔法公式，如果获取不到则保持 0 以便后续降级矩阵算法
                if (hedgeValue && hedgeValue > 0 && position > 0) {
                    etfCalibration = hedgeValue * position;
                }

                function getCurrentPrice(sym) {
                    var upperSym = sym.toUpperCase().replace('^', '');
                    // 1. 优先尝试完全匹配 (针对 Sandbox 手工输入的 USO-EU 等)
                    if (window.currentEtfPrices[upperSym] !== undefined && window.currentEtfPrices[upperSym] > 0) {
                        return window.currentEtfPrices[upperSym];
                    }
                    // 2. 降级尝试基础标的匹配 (USO-EU -> USO)
                    var cleanSym = upperSym.split('-')[0];
                    return window.currentEtfPrices[cleanSym] || 0;
                }

                // 🌟 核心估值逻辑分叉：
                // 1. 优先使用“魔法公式”（基于 woody hedge 导出的 etfCalibration）。支持所有单标的（包括指数）。
                if (etfCalibration > 0 && baseData.hedgingPortfolio.length === 1 && position > 0) {
                    var primarySym = baseData.hedgingPortfolio[0].symbol;
                    var currentAssetPrice = getCurrentPrice(primarySym);

                    if (currentAssetPrice > 0) {
                        // 魔法公式：实时估值 = 现金底仓 + (仓位 / etfCalibration) * (ETF实时价 * 实时汇率)
                        return baseData.baseNav * (1.0 - position) + (position / etfCalibration) * (currentAssetPrice * todayExchangeRate);
                    }
                }

                // 🌟 矩阵兜底：多资产组合，或魔法因子缺失时，退回 T-1 权重矩阵
                var weightedEtfChangeRate = 0;
                var hasValidData = false;
                var validWeight = 0;
                var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;

                for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                    var item = baseData.hedgingPortfolio[i];
                    var sym = item.symbol;
                    var isAshare = /^[0-9]{5,6}$/.test(sym) || /^(sh|sz)[0-9]{6}$/i.test(sym);

                    var currentPrice = 0;
                    if (isAshare) {
                        // 🌟 A股资产: 直接从主面板的A股实时流抓取
                        var cleanCode = sym.replace(/^(sh|sz)/i, '');
                        currentPrice = (window.latestLofPrices && window.latestLofPrices[cleanCode]) || 0;
                        if (currentPrice === 0) {
                            var el = document.getElementById('realtime-price-' + cleanCode);
                            if (el) currentPrice = parseFloat(el.textContent) || 0;
                        }
                    } else {
                        currentPrice = getCurrentPrice(sym);
                    }

                    // 🌟 核心：baseEtfPrices 存储的是带 ^ 的原始符号
                    var basePrice = baseData.baseEtfPrices[sym];
                    // 兜底尝试去 ^ 匹配
                    if (!basePrice) basePrice = baseData.baseEtfPrices[sym.replace('^', '')];

                    if (basePrice > 0 && currentPrice > 0 && item.weight > 0) {
                        var changeRate = currentPrice / basePrice;
                        // 🌟 核心：如果是美元计价资产，乘汇率；若是A股，免疫汇率！
                        if (!isAshare) {
                            changeRate = changeRate * exchangeRateChange;
                        }
                        // 兼容权重的百分比写法 (如果是 95 则除以 100)
                        var normWeight = item.weight > 2 ? item.weight / 100.0 : item.weight;
                        weightedEtfChangeRate += changeRate * normWeight;
                        validWeight += normWeight;
                        hasValidData = true;
                    }
                }
                
                if (!hasValidData) return 0;
                
                if (Math.abs(validWeight - 1.0) > 0.01 && validWeight > 0) {
                    weightedEtfChangeRate = weightedEtfChangeRate / validWeight;
                }
                
                return baseData.baseNav * (1 + baseData.position * (weightedEtfChangeRate - 1));
            }
            
            // 暴露到全局供其他模块调用
            window.calculateETFRealTimeValuation = calculateETFRealTimeValuation;
            
            window.updateSandboxRealtimePrices = function(code) {
                var sandboxPage = document.getElementById('page-rt-etf-' + code);
                if (!sandboxPage || !sandboxPage.classList.contains('active')) return;

                var baseData = window.fundBaseData[code];
                if (!baseData) return;

                baseData.hedgingPortfolio.forEach(function(item) {
                    var sym = item.symbol;
                    var sanitizedSym = sym.replace(/\^/g, '').replace(/-/g, '_').replace(/\./g, '_');
                    var priceEl = document.getElementById('sb-rt-price-' + code + '-' + sanitizedSym);
                    if (priceEl) {
                        var cleanSymForPriceLookup = sym.replace(/^(sh|sz)/i, '').replace(/\^/g, '').split('-')[0].toUpperCase();
                        var isAshare = /^[0-9]{5,6}$/.test(sym) || /^(sh|sz)[0-9]{6}$/i.test(sym);
                        var price = 0;
                        if (isAshare) {
                            cleanSymForPriceLookup = cleanSymForPriceLookup.replace(/^(sh|sz)/i, '');
                            price = (window.latestLofPrices && window.latestLofPrices[cleanSymForPriceLookup]) || 0;
                        } else {
                            price = (window.currentEtfPrices && window.currentEtfPrices[cleanSymForPriceLookup]) || 0;
                        }
                        priceEl.textContent = price > 0 ? price.toFixed(isAshare ? 3 : 2) : '-';
                    }
                });
            };

            window.openSandbox = function(code, type) {
                // 无论点击哪个列，都显示同一个沙盒页面
                showDetail('page-rt-etf-' + code);
                
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                // 取后端注入的精确汇率 (避开 DOM 正则匹配导致的格式错乱)
                var fxRate = baseData.todayExchangeRate || '';
                // 设置所有三个估值模块的汇率
                var fxEl = document.getElementById('sb-exchange-rate-' + code);
                if(fxEl) fxEl.textContent = fxRate;
                
                // 1. 初始化ETF估值的价格数据（使用与主面板相同的实时价格）
                var inputs = document.querySelectorAll('.sandbox-input-' + code);
                inputs.forEach(function(inp) {
                    var baseSym = inp.getAttribute('data-base');
                    var upperSym = baseSym ? baseSym.toUpperCase() : '';
                    
                    // 严格同步主面板当前生效的测试价 (无论是手工干预还是IB夜盘)
                    if (window.currentEtfPrices && window.currentEtfPrices[upperSym] !== undefined && window.currentEtfPrices[upperSym] > 0) {
                        inp.value = window.currentEtfPrices[upperSym];
                    } else {
                        // 兜底逻辑：如果全局变量未初始化，则依据单选状态提取
                        var useIB = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                        if (useIB) {
                            if (window.latestIbPrices && window.latestIbPrices[upperSym] && window.latestIbPrices[upperSym].bid) {
                                inp.value = window.latestIbPrices[upperSym].bid;
                            } else {
                                var ibValEl = document.getElementById('ib-val-' + baseSym);
                                inp.value = ibValEl ? (parseFloat(ibValEl.textContent) || '') : '';
                            }
                        } else {
                            var manualEl = document.getElementById(baseSym + '-price');
                            inp.value = manualEl ? (manualEl.value || manualEl.textContent) : '';
                        }
                    }
                });
                
                // 设置ETF估值的实时价格 - 直接从 realtime-price-{code} 读取即可，不需要 sb-live-price-{code}
                var livePriceEl = document.getElementById('realtime-price-' + code);
                if(livePriceEl) {
                    var lpText = livePriceEl.textContent;
                    var lpMatch = lpText.match(/[\d.]+/);
                    var tpInput = document.getElementById('sb-target-price-' + code);
                    if (lpMatch && tpInput) { tpInput.value = parseFloat(lpMatch[0]); }
                }
                
                // 2. 初始化期货校准估值的价格数据（使用与主面板相同的实时期货价格）
                var futSym = baseData.futureSymbol;
                var futPriceEl = null;
                if (futSym) {
                    // 主面板期货价格现已使用 class 渲染，需使用 querySelector 获取
                    futPriceEl = document.querySelector('.' + futSym.toLowerCase().replace('ag0', 'ag0') + '-price');
                }
                
                var futPrice = '';
                if (futPriceEl) {
                    futPrice = futPriceEl.textContent || futPriceEl.value || '';
                }
                
                var sbFutPriceEl = document.getElementById('sb-fut-price-' + code);
                if (sbFutPriceEl) {
                    if (futPrice) {
                        sbFutPriceEl.value = parseFloat(futPrice);
                    }
                }
                
                // 设置校准值（使用与主面板相同的校准值）
                var calib = 0;
                if (window.calibData && baseData.futureSymbol && window.calibData[baseData.futureSymbol]) {
                    calib = window.calibData[baseData.futureSymbol];
                } else {
                    if (baseData.category === '黄金') {
                        calib = window.calibData.GC || window.calibData.gold || 10.9067;
                    } else if (baseData.category === '原油') {
                        calib = window.calibData.CL || window.calibData.oil || 0.8227;
                    }
                }
                var sbFutCalibEl = document.getElementById('sb-fut-calib-' + code);
                if (sbFutCalibEl) {
                    if (calib > 0) sbFutCalibEl.value = calib;
                    else { sbFutCalibEl.value = ''; sbFutCalibEl.placeholder = '缺少'; }
                }
                
                // 3. 初始化纯期货估值的价格数据（使用与主面板相同的实时期货价格）
                var sbPureFutPriceEl = document.getElementById('sb-pure-fut-price-' + code);
                if (sbPureFutPriceEl) {
                    if (futPrice) {
                        sbPureFutPriceEl.value = parseFloat(futPrice);
                    }
                }
                
                // 根据点击的列切换标签页
                if (type === 'future') {
                    switchValuationTab(code, 'future');
                } else if (type === 'pure_future') {
                    switchValuationTab(code, 'pure_future');
                }
                
                // 主动调用一次计算函数
                if (window.calcSandbox) {
                    window.calcSandbox(code);
                }
                if (window.calcFutureSandbox) {
                    window.calcFutureSandbox(code);
                }
                if (window.calcPureFutureSandbox) {
                    window.calcPureFutureSandbox(code);
                }
                
                // 5. 设置交易价格
                var targetPrice = 0;
                if (livePriceEl) {
                    var lpText = livePriceEl.textContent;
                    var lpMatch = lpText.match(/[\d.]+/);
                    if (lpMatch) {
                        targetPrice = parseFloat(lpMatch[0]);
                        var qmtPriceInput = document.getElementById('trade-price-' + code + '-etf');
                        if (qmtPriceInput) qmtPriceInput.value = targetPrice;
                        var futQmtPriceInput = document.getElementById('trade-price-' + code + '-future');
                        if (futQmtPriceInput) futQmtPriceInput.value = targetPrice;
                        var pureQmtPriceInput = document.getElementById('trade-price-' + code + '-pure_future');
                        if (pureQmtPriceInput) pureQmtPriceInput.value = targetPrice;
                    }
                }
                
                // 设置期货校准和纯期货估值的目标价格
                if (targetPrice > 0) {
                    var futTargetPriceInput = document.getElementById("sb-fut-target-price-" + code);
                    if (futTargetPriceInput) futTargetPriceInput.value = targetPrice;
                    var pureTargetPriceInput = document.getElementById("sb-pure-target-price-" + code);
                    if (pureTargetPriceInput) pureTargetPriceInput.value = targetPrice;
                }
                
                // 6. 设置IB交易价格
                var suffixes = ['etf'];
                var idx = 1;
                while(document.getElementById('ib-trade-sym-' + code + '-etf_' + idx)) {
                    suffixes.push('etf_' + idx);
                    idx++;
                }
                
                suffixes.forEach(function(suffix) {
                    var defaultSymEl = document.getElementById('ib-trade-sym-' + code + '-' + suffix);
                    if (defaultSymEl) {
                        var defaultSym = defaultSymEl.value.toUpperCase();
                        var ibPriceEl = document.getElementById('ib-trade-price-' + code + '-' + suffix);
                        var bidEl = document.getElementById('sb-ib-bid-' + code + '-' + suffix);
                        var askEl = document.getElementById('sb-ib-ask-' + code + '-' + suffix);
                        
                        if (window.latestIbPrices && window.latestIbPrices[defaultSym]) {
                            var p = window.latestIbPrices[defaultSym];
                            if (bidEl && p.bid) bidEl.textContent = p.bid.toFixed(2);
                            if (askEl && p.ask) askEl.textContent = p.ask.toFixed(2);
                            if (ibPriceEl && p.bid) ibPriceEl.value = p.bid.toFixed(2);
                        } else {
                            var refPriceEl = document.getElementById(defaultSym.toLowerCase() + '-price');
                            if (refPriceEl && ibPriceEl) ibPriceEl.value = refPriceEl.value || refPriceEl.textContent;
                        }
                    }
                });
                
                // 7. 计算三套对冲数量
                window.calcHedgeQty(code, 'etf');
                window.calcHedgeQty(code, 'future', true);
                window.calcHedgeQty(code, 'pure_future', true);
                window.updateSandboxRealtimePrices(code);
            };
            
            // 🎯 新增：独立的对冲数量计算逻辑
            window.calcHedgeQty = function(code, stype, isReverse = false) {
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                // 获取输入的数量（金额或手数）
                var inputVal = 0;
                if (isReverse) {
                    var lotsInput = document.getElementById('sb-target-futures-lots-' + code + '-' + stype);
                    inputVal = lotsInput ? parseFloat(lotsInput.value) || 0 : 0;
                } else {
                    var capitalInput = document.getElementById('sb-target-capital-' + code + '-' + stype);
                    inputVal = capitalInput ? parseFloat(capitalInput.value) || 0 : 0;
                }
                
                var realtimePriceEl = document.getElementById('realtime-price-' + code);
                var lofLivePriceStr = realtimePriceEl ? realtimePriceEl.textContent : '';
                var lofLiveMatch = lofLivePriceStr ? lofLivePriceStr.match(/[\d.]+/) : null;
                var lofRealtimePrice = lofLiveMatch ? parseFloat(lofLiveMatch[0]) : 0;
                
                var etfHedge = (baseData.hedgeValue && baseData.hedgeValue > 0) ? baseData.hedgeValue : baseData.etfHedgeValue;
                var displayHedgeValue = 0;
                
                if (stype === 'etf') {
                    // ETF 对应的物理意义：1 股 ETF = 多少股 LOF
                    displayHedgeValue = etfHedge;
                } else {
                    // 期货 对应的物理意义：1 手期货 = 多少股 LOF
                    var multiplier = baseData.futureMultiplier || 1;
                    var calib = baseData.latestCalibrationFactor || 1;
                    displayHedgeValue = etfHedge * calib * multiplier;
                }
                
                var lofQtyEl = document.getElementById('sb-lof-qty-' + code + '-' + stype);
                var etfQtyEl = document.getElementById('sb-etf-qty-' + code + '-' + stype);
                
                var dbgHedgeEl = document.getElementById('sb-debug-hedge-' + code + '-' + stype);
                var dbgExposureEl = document.getElementById('sb-debug-exposure-' + code + '-' + stype);
                
                if(dbgHedgeEl) dbgHedgeEl.textContent = displayHedgeValue > 0 ? displayHedgeValue.toFixed(4) : '-';
                
                if (inputVal > 0 && displayHedgeValue > 0) {
                    var finalEtfQty = 0;
                    var finalLofQty = 0;
                    var realExposure = 0;
                    
                    if (!isReverse) {
                        // 【正向计算：ETF 面板】输入金额推导对应 LOF 和 ETF 数量
                        if (lofRealtimePrice > 0) {
                            if (baseData.category === '纯ETF' || baseData.category === '指数') {
                                var tempLofQty = inputVal / lofRealtimePrice;
                                finalEtfQty = Math.max(1, Math.round(tempLofQty / displayHedgeValue));
                                finalLofQty = Math.round((finalEtfQty * displayHedgeValue) / 100) * 100;
                            } else {
                                finalLofQty = Math.round((inputVal / lofRealtimePrice) / 100) * 100;
                                finalEtfQty = Math.max(1, Math.round(finalLofQty / displayHedgeValue));
                            }
                            realExposure = inputVal * baseData.position;
                        }
                    } else {
                        // 【反向计算：期货 面板】输入手数推导对应 LOF 股数
                        var lots = inputVal;
                        finalLofQty = Math.round((lots * displayHedgeValue) / 100) * 100;
                        if (lofRealtimePrice > 0 && baseData.position > 0) {
                            realExposure = (finalLofQty * lofRealtimePrice) * baseData.position;
                        }
                    }
                    
                    if(dbgExposureEl) dbgExposureEl.textContent = realExposure > 0 ? realExposure.toFixed(2) + ' 元' : '-';
                    
                    if(lofQtyEl) lofQtyEl.textContent = finalLofQty > 0 ? finalLofQty : '-';
                    if(etfQtyEl) etfQtyEl.textContent = finalEtfQty > 0 ? finalEtfQty : '-';
                    
                    var tradeVolEl = document.getElementById('trade-vol-' + code + '-' + stype);
                    var ibTradeVolEl = document.getElementById('ib-trade-vol-' + code + '-' + stype);
                    var ibFutureVolEl = document.getElementById('ib-future-vol-' + code);
                    
                    var isUserTrigger = (window.event && window.event.type === 'input' && window.event.target && window.event.target.id.startsWith('sb-target-'));
                    if (isUserTrigger) {
                        if (tradeVolEl) delete tradeVolEl.dataset.manual;
                        if (ibTradeVolEl) delete ibTradeVolEl.dataset.manual;
                        if (ibFutureVolEl) delete ibFutureVolEl.dataset.manual;
                    }
                    
                    if(tradeVolEl && !tradeVolEl.dataset.manual && finalLofQty > 0) tradeVolEl.value = finalLofQty;
                    
                    if (!isReverse) {
                        var tradeEtfs = [];
                        var defaultSymEl = document.getElementById('ib-trade-sym-' + code + '-etf');
                        if (defaultSymEl) {
                            tradeEtfs.push({sym: defaultSymEl.value, suffix: 'etf', weight: 0});
                            var idx = 1;
                            while(true) {
                                var symEl = document.getElementById('ib-trade-sym-' + code + '-etf_' + idx);
                                if (symEl) {
                                    tradeEtfs.push({sym: symEl.value, suffix: 'etf_' + idx, weight: 0});
                                    idx++;
                                } else {
                                    break;
                                }
                            }
                            var totalTradeWeight = 0;
                            tradeEtfs.forEach(function(t) {
                                var w = 0;
                                baseData.hedgingPortfolio.forEach(function(hp) {
                                    if (hp.symbol.includes(t.sym)) w += hp.weight;
                                });
                                t.weight = w;
                                totalTradeWeight += w;
                            });
                            if (totalTradeWeight > 0) {
                                tradeEtfs.forEach(function(t) { t.normWeight = t.weight / totalTradeWeight; });
                            } else {
                                tradeEtfs[0].normWeight = 1;
                                for (var j = 1; j < tradeEtfs.length; j++) tradeEtfs[j].normWeight = 0;
                            }
                        }
                        
                        tradeEtfs.forEach(function(t) {
                            var ibVolEl = document.getElementById('ib-trade-vol-' + code + '-' + t.suffix);
                            if (ibVolEl && !ibVolEl.dataset.manual) {
                                var qty = Math.max(1, Math.round(finalEtfQty * t.normWeight));
                                if (t.normWeight === 0) qty = 0;
                                ibVolEl.value = qty;
                            }
                        });
                    } else {
                        if(ibFutureVolEl && !ibFutureVolEl.dataset.manual) ibFutureVolEl.value = inputVal;
                    }
                } else {
                    if(lofQtyEl) lofQtyEl.textContent = '-';
                    if(etfQtyEl) etfQtyEl.textContent = '-';
                }
            };

            // 实时估值计算刷新（由夜盘或轮询触发）
            window.calculateRealTimeValues = function() {
                var isIb = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                var isFutu = document.getElementById('source-futu') && document.getElementById('source-futu').checked;
                var isManual = document.getElementById('source-manual') && document.getElementById('source-manual').checked;
        
                // 🌟 修复切换数据源后指示牌状态不更新的问题
                var statusEl = document.getElementById('ib-status-text');
                if (statusEl) {
                    if (isIb && !statusEl.textContent.includes('IB')) {
                        statusEl.textContent = 'IB夜盘数据测算中...';
                        statusEl.style.backgroundColor = '#1976d2';
                    } else if (isFutu && !statusEl.textContent.includes('富途')) {
                        statusEl.textContent = '富途夜盘数据测算中...';
                        statusEl.style.backgroundColor = '#2e7d32';
                    } else if (isManual && !statusEl.textContent.includes('手工')) {
                        statusEl.textContent = '手工参数测算中';
                        statusEl.style.backgroundColor = '#f57c00';
                    }
                }

                window.currentEtfPrices = {};
                
                // 🌟 核心修复：提取全市场所需的标的，而不是局限于表格里硬编码的 activeEtfs
                var allNeededSyms = new Set(window.activeEtfs);
                Object.values(window.fundBaseData).forEach(function(baseData) {
                    if (baseData.hedgingPortfolio) {
                        baseData.hedgingPortfolio.forEach(function(item) {
                            var sym = item.symbol.replace('^', '').split('-')[0].toUpperCase();
                            var isAshare = /^[0-9]{5,6}$/.test(sym) || /^(sh|sz)[0-9]{6}$/i.test(sym);
                            if (!isAshare) allNeededSyms.add(sym);
                        });
                    }
                });

                allNeededSyms.forEach(function(sym) {
                    var price = 0;
                    if (isIb) {
                        if (window.latestIbPrices && window.latestIbPrices[sym] && window.latestIbPrices[sym].bid) {
                            price = window.latestIbPrices[sym].bid;
                        } else {
                            var ibValEl = document.getElementById('ib-val-' + sym.toLowerCase());
                            if (ibValEl) price = parseFloat(ibValEl.textContent);
                        }
                    } else if (isFutu && window.latestFutuPrices && window.latestFutuPrices[sym] && window.latestFutuPrices[sym].bid) {
                        price = window.latestFutuPrices[sym].bid;
                    } else if (isManual) {
                        var manualEl = document.getElementById(sym.toLowerCase() + '-price');
                        if (manualEl) price = parseFloat(manualEl.value);
                    }
                    if (!price || isNaN(price)) {
                    price = 0; // 🛑 坚决拒绝昨收价兜底：没有最新实时数据就记为 0，触发异常熔断白屏，拒绝误导
                    }
                    window.currentEtfPrices[sym] = price;
                });
        
                Object.keys(window.fundBaseData).forEach(function(code) {
                    var val = window.calculateETFRealTimeValuation(code, window.fundBaseData[code].category);
                    var valEl = document.getElementById('realtime-valuation-' + code);
                    var premEl = document.getElementById('realtime-premium-' + code);
                    var lightEl = document.getElementById('realtime-light-' + code);
                    var lofPriceEl = document.getElementById('realtime-price-' + code);
                    
                    if (valEl) valEl.textContent = val > 0 ? val.toFixed(4) : '-';
                    
                    if (val > 0 && lofPriceEl) {
                        var lofPrice = parseFloat(lofPriceEl.textContent);
                        if (lofPrice > 0) {
                            var prem = (lofPrice / val - 1) * 100;
                            if (premEl) {
                                premEl.textContent = (prem > 0 ? '+' : '') + prem.toFixed(2) + '%';
                                premEl.className = 'num-font ' + (prem > 0 ? 'premium-positive' : 'premium-negative');
                                premEl.style.color = prem > 0 ? '#d32f2f' : '#388e3c'; 
                            }
                            if (lightEl) {
                                lightEl.innerHTML = prem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            }
                        }
                    }
                    
                    // 追加：更新“期货校准估值”的实时溢价
                    var calibValEl = document.getElementById('rt-calib-val-' + code);
                    var calibPremEl = document.getElementById('rt-calib-prem-' + code);
                    var calibLightEl = document.getElementById('rt-calib-light-' + code);
                    if (calibValEl && calibPremEl) {
                        var cVal = parseFloat(calibValEl.textContent);
                        if (cVal > 0) {
                            var cPrem = (lofPrice / cVal - 1) * 100;
                            calibPremEl.textContent = (cPrem > 0 ? '+' : '') + cPrem.toFixed(2) + '%';
                            calibPremEl.className = 'num-font ' + (cPrem > 0 ? 'premium-positive' : 'premium-negative');
                            calibPremEl.style.color = cPrem > 0 ? '#d32f2f' : '#388e3c';
                            if (calibLightEl) {
                                calibLightEl.innerHTML = cPrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            }
                        }
                    }

                    // 追加：更新“纯期货估值”的实时溢价
                    var exactValEl = document.getElementById('rt-exact-val-' + code);
                    var exactPremEl = document.getElementById('rt-exact-prem-' + code);
                    var exactLightEl = document.getElementById('rt-exact-light-' + code);
                    if (exactValEl && exactPremEl) {
                        var eVal = parseFloat(exactValEl.textContent);
                        if (eVal > 0) {
                            var ePrem = (lofPrice / eVal - 1) * 100;
                            exactPremEl.textContent = (ePrem > 0 ? '+' : '') + ePrem.toFixed(2) + '%';
                            exactPremEl.className = 'num-font ' + (ePrem > 0 ? 'premium-positive' : 'premium-negative');
                            exactPremEl.style.color = ePrem > 0 ? '#d32f2f' : '#388e3c';
                            if (exactLightEl) {
                                exactLightEl.innerHTML = ePrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            }
                        }
                    }
                    window.updateSandboxRealtimePrices(code);
                });
            };

            // ETF 沙盘计算
            window.calcSandbox = function(code) {
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                var targetPriceEl = document.getElementById('sb-target-price-' + code);
                var targetPrice = targetPriceEl ? parseFloat(targetPriceEl.value) : 0;
                
                var sandboxEtfPrices = Object.assign({}, window.currentEtfPrices);
                var inputs = document.querySelectorAll('.sandbox-input-' + code);
                inputs.forEach(function(inp) {
                    var baseSym = inp.getAttribute('data-base').toUpperCase();
                    sandboxEtfPrices[baseSym] = parseFloat(inp.value) || 0;
                });
        
                var globalCurrentEtfPrices = window.currentEtfPrices;
                window.currentEtfPrices = sandboxEtfPrices;
        
                var val = window.calculateETFRealTimeValuation(code, baseData.category);
        
                window.currentEtfPrices = globalCurrentEtfPrices;
        
                var valEl = document.getElementById('sb-val-' + code);
                if (valEl) valEl.textContent = val > 0 ? val.toFixed(4) : '-';
        
                var premEl = document.getElementById('sb-target-prem-' + code);
                if (premEl && val > 0 && targetPrice > 0) {
                    var prem = (targetPrice / val - 1) * 100;
                    premEl.textContent = (prem > 0 ? '+' : '') + prem.toFixed(2) + '%';
                    premEl.style.color = prem > 0 ? '#d32f2f' : '#388e3c';
                } else if (premEl) {
                    premEl.textContent = '-';
                }
        
                window.calcHedgeQty(code, 'etf');
            };
        
            // 期货校准沙盘计算
            window.calcFutureSandbox = function(code) {
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                var futPriceEl = document.getElementById('sb-fut-price-' + code);
                var futCalibEl = document.getElementById('sb-fut-calib-' + code);
                var targetPriceEl = document.getElementById('sb-target-price-' + code);
                
                var futPrice = futPriceEl ? parseFloat(futPriceEl.value) : 0;
                var calib = futCalibEl ? parseFloat(futCalibEl.value) : 0;
                var targetPrice = targetPriceEl ? parseFloat(targetPriceEl.value) : 0;
                
                var equivEl = document.getElementById('sb-equiv-etf-' + code);
                var valEl = document.getElementById('sb-fut-val-' + code);
                var premEl = document.getElementById('sb-fut-target-prem-' + code);
        
                var val = 0;
                if (futPrice > 0 && calib > 0) {
                    var reqSpot = (baseData.rateType === 'spot');
                    var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;

                    if (baseData.category === '指数') {
                        // 指数专用逻辑：期货价格/校准值（此时代表升贴水率，如 1.0028）还原为现货大盘点位
                        var equivSpot = futPrice / calib;
                        
                        // 为了让"期货校准估值"和"ETF实时估值"严格对齐（支持魔法公式），需将现货指数转化为等效的ETF
                        var equivEtfPrice = 0;
                        var mainAnchorSymbol = baseData.hedgingPortfolio[0].symbol;
                        var baseEtfPrice = baseData.baseEtfPrices[mainAnchorSymbol] || 0;
                        
                        if (baseData.baseIndexPrice && baseData.baseIndexPrice > 0 && baseEtfPrice > 0) {
                            equivEtfPrice = equivSpot * (baseEtfPrice / baseData.baseIndexPrice);
                        } else if (baseData.baseFuturePrice > 0 && baseData.latestCalibrationFactor > 0 && baseEtfPrice > 0) {
                            var derivedBaseIndexPrice = baseData.baseFuturePrice / baseData.latestCalibrationFactor;
                            equivEtfPrice = equivSpot * (baseEtfPrice / derivedBaseIndexPrice);
                        }
                        
                        if (equivEl) equivEl.textContent = equivEtfPrice > 0 ? equivEtfPrice.toFixed(3) : equivSpot.toFixed(2);
                        
                        var position = baseData.position;
                        var hedgeValue = baseData.hedgeValue;
                        var etfCalibration = (hedgeValue && hedgeValue > 0 && position > 0) ? hedgeValue * position : 0;
                        
                        if (etfCalibration > 0 && equivEtfPrice > 0) {
                            val = baseData.baseNav * (1.0 - position) + (position / etfCalibration) * (equivEtfPrice * todayExchangeRate);
                        } else {
                            if (baseData.baseIndexPrice && baseData.baseIndexPrice > 0) {
                                var spotChangeRate = equivSpot / baseData.baseIndexPrice;
                                var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                                val = baseData.baseNav * (1 + baseData.position * (spotChangeRate * exchangeRateChange - 1));
                            } else if (baseData.baseFuturePrice > 0 && baseData.latestCalibrationFactor > 0) {
                                var derivedBaseIndexPrice = baseData.baseFuturePrice / baseData.latestCalibrationFactor;
                                var spotChangeRate = equivSpot / derivedBaseIndexPrice;
                                var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                                val = baseData.baseNav * (1 + baseData.position * (spotChangeRate * exchangeRateChange - 1));
                            }
                        }
                    } else {
                                // 商品类基金（黄金/原油）的校准估值：使用加权平均
                        var equivEtfPrice = futPrice / calib;
                        if (equivEl) equivEl.textContent = equivEtfPrice.toFixed(3);
                                
                                var weightedFuturesChangeRate = 0.0;
                                var totalValidWeight = 0.0;
                                var validEtfs = [];
                                
                        for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                            var item = baseData.hedgingPortfolio[i];
                                    if (item.weight <= 0 || item.weight < 0.02 || item.symbol.includes('SLV')) {
                                        continue;
                                    }
                                    validEtfs.push(item);
                                    totalValidWeight += item.weight;
                        }
                                
                                if (totalValidWeight > 0) {
                                    for (var j = 0; j < validEtfs.length; j++) {
                                        var vItem = validEtfs[j];
                                        var baseEtfPrice = baseData.baseEtfPrices[vItem.symbol];
                                        if (baseEtfPrice > 0) {
                                            var etfChangeRate = equivEtfPrice / baseEtfPrice;
                                            var normalizedWeight = vItem.weight / totalValidWeight;
                                            weightedFuturesChangeRate += etfChangeRate * normalizedWeight;
                                        }
                                    }
                            var exchangeRateChange = baseData.todayExchangeRate / baseData.baseExchangeRate;
                                    val = baseData.baseNav * (1 + baseData.position * (weightedFuturesChangeRate * exchangeRateChange - 1));
                        }
                    }
                } else {
                    if (equivEl) equivEl.textContent = '-';
                }
        
                if (valEl) valEl.textContent = val > 0 ? val.toFixed(4) : '-';
        
                if (premEl && val > 0 && targetPrice > 0) {
                    var prem = (targetPrice / val - 1) * 100;
                    premEl.textContent = (prem > 0 ? '+' : '') + prem.toFixed(2) + '%';
                    premEl.style.color = prem > 0 ? '#d32f2f' : '#388e3c';
                } else if (premEl) {
                    premEl.textContent = '-';
                }
        
                window.calcHedgeQty(code, 'future', true);
            };
        
            // 纯期货沙盘计算
            window.calcPureFutureSandbox = function(code) {
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                var futPriceEl = document.getElementById('sb-pure-fut-price-' + code);
                var targetPriceEl = document.getElementById('sb-target-price-' + code);
                
                var futPrice = futPriceEl ? parseFloat(futPriceEl.value) : 0;
                var targetPrice = targetPriceEl ? parseFloat(targetPriceEl.value) : 0;
                
                var valEl = document.getElementById('sb-pure-val-' + code);
                var premEl = document.getElementById('sb-pure-target-prem-' + code);
        
                var val = 0;
                if (futPrice > 0 && baseData.baseFuturePrice > 0 && baseData.baseExchangeRate > 0) {
                    var reqSpot = (baseData.rateType === 'spot');
                    var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                    var futureChangeRate = futPrice / baseData.baseFuturePrice;
                    var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                    val = baseData.baseNav * (1 + baseData.position * (futureChangeRate * exchangeRateChange - 1));
                }
        
                if (valEl) valEl.textContent = val > 0 ? val.toFixed(4) : '-';
        
                if (premEl && val > 0 && targetPrice > 0) {
                    var prem = (targetPrice / val - 1) * 100;
                    premEl.textContent = (prem > 0 ? '+' : '') + prem.toFixed(2) + '%';
                    premEl.style.color = prem > 0 ? '#d32f2f' : '#388e3c';
                } else if (premEl) {
                    premEl.textContent = '-';
                }
        
                window.calcHedgeQty(code, 'pure_future', true);
            };
        
            window.updateFuturesData = function() {
                Object.keys(window.fundBaseData).forEach(function(code) {
                    var baseData = window.fundBaseData[code];
                    if (!baseData || !baseData.futureSymbol || baseData.futureSymbol.trim() === '') return;

                    var futSym = baseData.futureSymbol;
                    var futPriceEl = document.querySelector('.' + futSym.toLowerCase().replace('ag0', 'ag0') + '-price');
                    var futurePrice = 0;
                    if (futPriceEl && futPriceEl.textContent && futPriceEl.textContent !== '-') {
                        futurePrice = parseFloat(futPriceEl.textContent);
                    }
                    
                    if (futurePrice > 0 && baseData.baseFuturePrice > 0 && baseData.baseExchangeRate > 0 && baseData.todayExchangeRate > 0) {
                        var reqSpot = (baseData.rateType === 'spot');
                        var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                        
                        // 1. 更新纯期货估值
                        var futureChangeRate = futurePrice / baseData.baseFuturePrice;
                        var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                        var exactVal = baseData.baseNav * (1 + baseData.position * (futureChangeRate * exchangeRateChange - 1));
                        
                        var exactValEl = document.getElementById('rt-exact-val-' + code);
                        if (exactValEl) exactValEl.textContent = exactVal.toFixed(4);
                        
                        // 2. 更新期货校准估值 (如果支持)
                        var calib = baseData.latestCalibrationFactor;
                        var calibValEl = document.getElementById('rt-calib-val-' + code);
                        if (calib > 0 && calibValEl) {
                            var calibVal = 0;
                            if (baseData.category === '指数') {
                                var equivSpot = futurePrice / calib;
                                
                                if (baseData.baseIndexPrice > 0) {
                                    var spotChangeRate = equivSpot / baseData.baseIndexPrice;
                                    calibVal = baseData.baseNav * (1 + baseData.position * (spotChangeRate * exchangeRateChange - 1));
                                } else if (baseData.baseFuturePrice > 0 && baseData.latestCalibrationFactor > 0) {
                                    var derivedBaseIndexPrice = baseData.baseFuturePrice / baseData.latestCalibrationFactor;
                                    var spotChangeRate = equivSpot / derivedBaseIndexPrice;
                                    calibVal = baseData.baseNav * (1 + baseData.position * (spotChangeRate * exchangeRateChange - 1));
                                }
                            } else {
                                // 商品类基金（黄金/原油）的校准估值：使用加权平均
                                var equivEtfPrice = futurePrice / calib;
                                
                                var weightedFuturesChangeRate = 0.0;
                                var totalValidWeight = 0.0;
                                var validEtfs = [];
                                
                                for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                                    var item = baseData.hedgingPortfolio[i];
                                    if (item.weight <= 0 || item.weight < 0.02 || item.symbol.includes('SLV')) {
                                        continue;
                                    }
                                    validEtfs.push(item);
                                    totalValidWeight += item.weight;
                                }
                                
                                if (totalValidWeight > 0) {
                                    for (var j = 0; j < validEtfs.length; j++) {
                                        var vItem = validEtfs[j];
                                        var baseEtfPrice = baseData.baseEtfPrices[vItem.symbol];
                                        if (baseEtfPrice > 0) {
                                            var etfChangeRate = equivEtfPrice / baseEtfPrice;
                                            var normalizedWeight = vItem.weight / totalValidWeight;
                                            weightedFuturesChangeRate += etfChangeRate * normalizedWeight;
                                        }
                                    }
                                    calibVal = baseData.baseNav * (1 + baseData.position * (weightedFuturesChangeRate * exchangeRateChange - 1));
                                }
                            }
                            if (calibValEl && calibVal > 0) calibValEl.textContent = calibVal.toFixed(4);
                        }
                    }
                });
                
                // 触发整体页面颜色/红绿灯渲染刷新
                window.calculateRealTimeValues();
            };

            // A股下单执行
            window.executeTrade = function(code, action, sandboxType) {
                var brokerEl = document.getElementById('trade-broker-' + code + '-' + sandboxType);
                var broker = brokerEl ? brokerEl.value : 'yinhe_qmt';
                var volEl = document.getElementById('trade-vol-' + code + '-' + sandboxType);
                var priceEl = document.getElementById('trade-price-' + code + '-' + sandboxType);
                var msgEl = document.getElementById('trade-msg-' + code + '-' + sandboxType);
        
                if (!volEl || !priceEl || !msgEl) return;
        
                var vol = parseFloat(volEl.value);
                var price = parseFloat(priceEl.value);
        
                if (isNaN(vol) || vol <= 0) { msgEl.textContent = '❌ 数量无效'; msgEl.style.color = '#d32f2f'; return; }
                if (isNaN(price) || price <= 0) { msgEl.textContent = '❌ 价格无效'; msgEl.style.color = '#d32f2f'; return; }
        
                // [核心加固] 下单确认
                var actionText = (action === 'BUY' ? '买入' : '卖出');
                if (!confirm('【实盘下单确认】\n\n代码: ' + code + '\n动作: ' + actionText + '\n价格: ' + price + '\n数量: ' + vol + '\n通道: ' + broker + '\n\n确认发送指令吗？')) {
                    return;
                }

                msgEl.textContent = '🚀 指令发送中...';
                msgEl.style.color = '#1976d2';
        
                fetch('/api/trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action, symbol: code, volume: vol, price: price, broker: broker })
                }).then(res => res.json()).then(data => {
                    if (data.status === 'success') {
                        msgEl.textContent = '✅ ' + (data.message || '下单成功');
                        msgEl.style.color = '#2e7d32';
                    } else {
                        msgEl.textContent = '❌ ' + (data.message || '下单失败');
                        msgEl.style.color = '#d32f2f';
                    }
                }).catch(err => {
                    msgEl.textContent = '❌ 网络异常: ' + err;
                    msgEl.style.color = '#d32f2f';
                });
            };
            
            // IB外盘下单执行
            window.executeIbTrade = function(code, action, sandboxType) {
                var symEl = document.getElementById('ib-trade-sym-' + code + '-' + sandboxType);
                var volEl = document.getElementById('ib-trade-vol-' + code + '-' + sandboxType);
                var priceEl = document.getElementById('ib-trade-price-' + code + '-' + sandboxType);
                var msgEl = document.getElementById('ib-trade-msg-' + code + '-' + sandboxType);
        
                if (!symEl || !volEl || !priceEl || !msgEl) return;
        
                var sym = symEl.value;
                var vol = parseFloat(volEl.value);
                var price = parseFloat(priceEl.value);
        
                if (!sym) { msgEl.textContent = '❌ 代码无效'; msgEl.style.color = '#d32f2f'; return; }
                if (isNaN(vol) || vol <= 0) { msgEl.textContent = '❌ 数量无效'; msgEl.style.color = '#d32f2f'; return; }
                if (isNaN(price) || price <= 0) { msgEl.textContent = '❌ 价格无效'; msgEl.style.color = '#d32f2f'; return; }
        
                // [核心加固] IB下单确认
                var actionText = (action === 'BUY' ? '买入平仓' : '卖空开仓');
                if (!confirm('【IB外盘实盘确认】\n\n合约: ' + sym + '\n动作: ' + actionText + '\n价格: ' + price + '\n数量: ' + vol + '\n路由: OVERNIGHT\n\n确认发送指令吗？')) {
                    return;
                }

                msgEl.textContent = '🚀 指令发送中...';
                msgEl.style.color = '#1976d2';
        
                fetch('/api/ib_trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action, symbol: sym, volume: vol, price: price })
                }).then(res => res.json()).then(data => {
                    if (data.status === 'success') {
                        msgEl.textContent = '✅ ' + (data.message || '下单成功');
                        msgEl.style.color = '#2e7d32';
                    } else {
                        msgEl.textContent = '❌ ' + (data.message || '下单失败');
                        msgEl.style.color = '#d32f2f';
                    }
                }).catch(err => {
                    msgEl.textContent = '❌ 网络异常: ' + err;
                    msgEl.style.color = '#d32f2f';
                });
            };
            
            window.exportFundData = function() {
                var code = document.getElementById('export-fund-code').value;
                var msgEl = document.getElementById('export-msg');
                if (!code || code.length !== 6) return;
                
                msgEl.textContent = "⏳ 正在生成对账文件...";
                msgEl.style.color = "#1565c0";
                
                fetch('/api/export_fund/' + code)
                    .then(res => {
                        if (!res.ok) { return res.json().then(err => { throw new Error(err.message || '导出失败'); }); }
                        return res.blob();
                    })
                    .then(blob => {
                        var url = window.URL.createObjectURL(blob);
                        var a = document.createElement('a');
                        a.href = url; a.download = 'fund_' + code + '_export.csv';
                        document.body.appendChild(a); a.click(); a.remove();
                        window.URL.revokeObjectURL(url);
                        msgEl.textContent = "✅ 导出成功！";
                        msgEl.style.color = "#2e7d32";
                    })
                    .catch(err => {
                        msgEl.textContent = "❌ " + err.message;
                        msgEl.style.color = "#d32f2f";
                    });
            };
            
            window.switchTab = function(tabIndex) {
                document.querySelectorAll('.tab-content').forEach(function(tab) { tab.classList.remove('active'); });
                document.querySelectorAll('.tab-button').forEach(function(button) { button.style.background = 'var(--secondary-light)'; button.style.color = 'var(--secondary-dark)'; });
                var activeTab = document.getElementById('tab-' + tabIndex);
                if (activeTab) activeTab.classList.add('active');
                var activeButton = document.querySelectorAll('.tab-button')[tabIndex - 1];
                if (activeButton) { activeButton.style.background = 'var(--primary-color)'; activeButton.style.color = 'white'; }
            };

            // 页面展示切换逻辑
            window.showDetail = function(pageId) {
                document.querySelectorAll('.page-section').forEach(function(el) { el.classList.remove('active'); });
                document.getElementById(pageId).classList.add('active');
                window.scrollTo(0, 0);
            };
        
            window.goHome = function() {
                document.querySelectorAll('.page-section').forEach(function(el) { el.classList.remove('active'); });
                document.getElementById('page-home').classList.add('active');
            };
        
            window.toggleVerify = function(uid) {
                var row = document.getElementById('verify-' + uid);
                if (row) {
                    row.style.display = (row.style.display === 'none' || row.style.display === '') ? 'table-row' : 'none';
                }
            };

            // 启动时初始化数据源状态并定时轮询防掉线
            setTimeout(window.updateLofSourceBadge, 1000);
            setInterval(window.updateLofSourceBadge, 10000);

            // 🌟 [终极兜底] 每 3 秒强制轮询富途和 IB，彻底解决断流和白屏问题
            setInterval(function() {
                var isFutu = document.getElementById('source-futu') && document.getElementById('source-futu').checked;
                if (isFutu) {
                    fetch('/api/futu_prices').then(res => res.json()).then(data => {
                        if (data.status === 'success' && data.prices) {
                            window.latestFutuPrices = window.latestFutuPrices || {};
                            Object.assign(window.latestFutuPrices, data.prices);
                            var hasValid = false;
                            Object.keys(data.prices).forEach(function(sym) {
                                var el = document.getElementById('futu-val-' + sym.toLowerCase());
                                if (el && data.prices[sym] && data.prices[sym].bid) {
                                    hasValid = true;
                                    var newPrice = data.prices[sym].bid.toFixed(2);
                                    if (el.textContent !== newPrice) {
                                        el.textContent = newPrice;
                                        el.style.color = '#2e7d32'; // 富途专属绿色闪烁
                                    }
                                }
                            });
                            if (hasValid) {
                                var statusEl = document.getElementById('ib-status-text');
                                if (statusEl) {
                                    statusEl.textContent = '✅ 富途夜盘数据已连通更新';
                                    statusEl.style.backgroundColor = '#2e7d32';
                                }
                            }
                            window.calculateRealTimeValues();
                        }
                    }).catch(e => console.log('Futu fetch error:', e));
                }
                
                var isIb = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                if (isIb) {
                    fetch('/api/ib_prices').then(res => res.json()).then(data => {
                        if (data.status === 'success' && data.prices) {
                            window.latestIbPrices = window.latestIbPrices || {};
                            Object.assign(window.latestIbPrices, data.prices);
                            updateIbDomPrices(data.prices);
                            window.calculateRealTimeValues();
                        }
                    }).catch(e => console.log('IB fetch error:', e));
                }
            }, 3000);
        </script>
        '''

    @staticmethod
    def generate_admin_js():
        return r'''
        <script>
            const ADMIN_BASE = 'http://127.0.0.1:5002';
            let prevTaskStatus = {};

            function openConfig() {
                window.open(ADMIN_BASE + '/admin/config', '_blank');
            }

            function formatShortDate(ts) {
                if (!ts) return '未运行';
                return ts.replace(/^\d{4}-/, '').replace(' ', ' ');
            }

            function setAdminStatus(key, status, lastRun) {
                var statusEl = document.getElementById('admin-' + key + '-status');
                var lastEl = document.getElementById('admin-' + key + '-time');
                if (statusEl) statusEl.textContent = status || '未知';
                if (lastEl) lastEl.textContent = formatShortDate(lastRun);
            }

            function setLof00Status(running, port) {
                var el = document.getElementById('admin-lof00-status');
                if (!el) return;
                if (running) {
                    el.textContent = '在线 (端口 ' + port + ')';
                } else {
                    el.textContent = '未启动';
                }
            }

            async function refreshAdminStatus() {
                try {
                    const resp = await fetch(ADMIN_BASE + '/admin/status');
                    const data = await resp.json();
                    
                    if (data['01']) setAdminStatus('01', data['01'].status, data['01'].last_run);
                    if (data['012']) setAdminStatus('012', data['012'].status, data['012'].last_run);
                    if (data['woody']) setAdminStatus('woody', data['woody'].status, data['woody'].last_run);
                } catch (e) {
                    console.log('维护状态获取失败');
                }
            }

            async function runAdminTask(task) {
                var msgEl = document.getElementById('admin-msg');
                if (msgEl) msgEl.textContent = '启动中...';
                try {
                    window.open(ADMIN_BASE + '/admin/stream/' + task, 'log_' + task, 'width=900,height=600');
                    const resp = await fetch(ADMIN_BASE + '/admin/run/' + task, { method: 'POST' });
                    if (msgEl) msgEl.textContent = '已启动：' + task;
                    setTimeout(refreshAdminStatus, 1000);
                } catch (e) {
                    if (msgEl) msgEl.textContent = '启动失败';
                }
            }

            document.addEventListener('DOMContentLoaded', function() {
                refreshAdminStatus();
                setInterval(refreshAdminStatus, 15000);
            });
        </script>
        '''