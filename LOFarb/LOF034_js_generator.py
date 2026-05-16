import json

class JsGenerator:
    """生成繁杂的前端交互代码，将其从业务逻辑核心中剥离以保持整洁"""
    
    @staticmethod
    def generate_js_code(active_etfs, js_fund_base_data, gold_calibration, oil_calibration):
        return r'''
        <script>
            // 注入Python预先计算的基金基准数据，彻底抛弃前端读CSV
            window.activeEtfs = ''' + json.dumps(active_etfs) + r''';
            window.fundBaseData = ''' + json.dumps(js_fund_base_data, ensure_ascii=False) + r''';
            window.calibData = { "gold": ''' + str(gold_calibration) + r''', "oil": ''' + str(oil_calibration) + r''' };

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
                
                // 触发估值计算
                updateFuturesData();
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
                    if (data.prices.AG) {
                        var agPriceElement = document.querySelector('#ag0-price');
                        if (agPriceElement) {
                            agPriceElement.textContent = data.prices.AG.toFixed(2);
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
                    var el = document.getElementById('realtime-price-' + data.code);
                    if (el) {
                        el.textContent = data.price.toFixed(3);
                        el.style.color = '#d32f2f'; // 闪烁红字提醒更新
                        setTimeout(function() { el.style.color = ''; }, 500);
                    }
                    // 更新关联的沙盘推演(如果沙盘被打开，让测试价同步跳动)
                    var tpInput = document.getElementById('sb-target-price-' + data.code);
                    if (tpInput && !document.activeElement.isSameNode(tpInput)) {
                        tpInput.value = data.price;
                    }
                    if (window.calcSandbox) window.calcSandbox(data.code);
                    if (window.calcFutureSandbox) window.calcFutureSandbox(data.code);
                    if (window.calcPureFutureSandbox) window.calcPureFutureSandbox(data.code);
                }
            });
            
            // 接收 LOF A股价格快照 (页面刚刷新时)
            socket.on('lof_price_snapshot', function(data) {
                if (data && data.prices) {
                    Object.keys(data.prices).forEach(function(code) {
                        var el = document.getElementById('realtime-price-' + code);
                        if (el && data.prices[code] > 0) {
                            el.textContent = data.prices[code].toFixed(3);
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
                
                // 🌟 魔法公式：使用真实的 Woody Calibration 计算实时估值
                var calibration = baseData.latestCalibrationFactor;
                var position = baseData.position;
                
                // 如果后端没有传真实的 calibration，则用 hedgeValue 动态推导一个兜底的 calibration
                if (!calibration || calibration <= 0) {
                    var hedgeValue = baseData.hedgeValue;
                    if (!hedgeValue || hedgeValue <= 0) {
                        hedgeValue = baseData.etfHedgeValue; 
                    }
                    if (hedgeValue && hedgeValue > 0 && position > 0) {
                        calibration = hedgeValue * position;
                    }
                }
                
                function getCurrentPrice(sym) {
                    var cleanSym = sym.replace('^', '').split('-')[0].toUpperCase();
                    return window.currentEtfPrices[cleanSym] || 0;
                }

                // 🌟 仅限单一资产(如XOP等纯ETF)使用校准魔法。指数类(SPY/QQQ)由于WoodyAPI返回的校准因子其实是期货的，强制退回降级的传统兜底算法(矩阵)
                if (category !== '指数' && calibration && calibration > 0 && baseData.hedgingPortfolio.length === 1 && position > 0) {
                    var primarySym = baseData.hedgingPortfolio[0].symbol;
                    var currentAssetPrice = getCurrentPrice(primarySym);
                    
                    if (currentAssetPrice > 0) {
                        // 原汁原味的 Woody 公式：实时估值 = 现金底仓 + (仓位 / Calibration) * (ETF实时价 * 实时汇率)
                        return baseData.baseNav * (1.0 - position) + (position / calibration) * (currentAssetPrice * todayExchangeRate);
                    }
                }
                
                // 🌟 矩阵兜底：商品多资产组合(黄金/原油)，或魔法因子缺失时，退回 T-1 权重矩阵
                var weightedEtfChangeRate = 0;
                var hasValidData = false;
                var validWeight = 0;
                
                for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                    var item = baseData.hedgingPortfolio[i];
                    var currentPrice = getCurrentPrice(item.symbol);
                    
                    var basePrice = baseData.baseEtfPrices[item.symbol];
                    if (basePrice > 0 && currentPrice > 0 && item.weight > 0) {
                        weightedEtfChangeRate += (currentPrice / basePrice) * item.weight;
                        validWeight += item.weight;
                        hasValidData = true;
                    }
                }
                
                if (!hasValidData) return 0;
                if (validWeight < 0.98 || validWeight > 1.02) {
                    weightedEtfChangeRate = weightedEtfChangeRate / validWeight;
                }
                
                if (!baseData.baseExchangeRate || isNaN(baseData.baseExchangeRate) || baseData.baseExchangeRate <= 0) {
                    return 0;
                }
                
                var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                return baseData.baseNav * (1 + baseData.position * (weightedEtfChangeRate * exchangeRateChange - 1));
            }
            
            // 暴露到全局供其他模块调用
            window.calculateETFRealTimeValuation = calculateETFRealTimeValuation;
            
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
                    
                    // 严格同步主面板当前生效的测试价 (无论是手工干预还是IB夜盘)
                    if (window.currentEtfPrices && window.currentEtfPrices[baseSym] !== undefined && window.currentEtfPrices[baseSym] > 0) {
                        inp.value = window.currentEtfPrices[baseSym];
                    } else {
                        // 兜底逻辑：如果全局变量未初始化，则依据单选状态提取
                        var useIB = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                        if (useIB) {
                            var upperSym = baseSym.toUpperCase();
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
                if (futSym === 'GC') futPriceEl = document.getElementById('gc-price');
                else if (futSym === 'CL') futPriceEl = document.getElementById('cl-price');
                else if (futSym === 'NQ') futPriceEl = document.getElementById('nq-price');
                else if (futSym === 'ES') futPriceEl = document.getElementById('es-price');
                
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
                var calib = baseData.category === '黄金' ? window.calibData.gold : window.calibData.oil;
                var sbFutCalibEl = document.getElementById('sb-fut-calib-' + code);
                if (sbFutCalibEl && calib > 0) {
                    sbFutCalibEl.value = calib;
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
                if (livePriceEl) {
                    var lpText = livePriceEl.textContent;
                    var lpMatch = lpText.match(/[\d.]+/);
                    if (lpMatch) {
                        var qmtPriceInput = document.getElementById('trade-price-' + code + '-etf');
                        if (qmtPriceInput) qmtPriceInput.value = parseFloat(lpMatch[0]);
                        var futQmtPriceInput = document.getElementById('trade-price-' + code + '-future');
                        if (futQmtPriceInput) futQmtPriceInput.value = parseFloat(lpMatch[0]);
                        var pureQmtPriceInput = document.getElementById('trade-price-' + code + '-pure_future');
                        if (pureQmtPriceInput) pureQmtPriceInput.value = parseFloat(lpMatch[0]);
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
                window.calcHedgeQty(code, 'future');
                window.calcHedgeQty(code, 'pure_future');
            };
            
            // 🎯 新增：独立的对冲数量计算逻辑
            window.calcHedgeQty = function(code, stype, isReverse = false) { 
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                var capitalInput = document.getElementById('sb-target-capital-' + code + '-' + stype);
                var capitalA = capitalInput ? parseFloat(capitalInput.value) || 0 : 0;
                
                var realtimePriceEl = document.getElementById('realtime-price-' + code);
                var lofLivePriceStr = realtimePriceEl ? realtimePriceEl.textContent : '';
                var lofLiveMatch = lofLivePriceStr ? lofLivePriceStr.match(/[\d.]+/) : null;
                var lofRealtimePrice = lofLiveMatch ? parseFloat(lofLiveMatch[0]) : 0;
                
                var hedgeValue = baseData.baseHedgeValue;
                if (!hedgeValue || hedgeValue <= 0) {
                    if (stype === 'etf') hedgeValue = baseData.etfHedgeValue;
                    else if (stype === 'future' || stype === 'pure_future') hedgeValue = baseData.futHedgeValue;
                }
                
                var lofQtyEl = document.getElementById('sb-lof-qty-' + code + '-' + stype);
                var etfQtyEl = document.getElementById('sb-etf-qty-' + code + '-' + stype);
                
                var dbgHedgeEl = document.getElementById('sb-debug-hedge-' + code + '-' + stype);
                var dbgExposureEl = document.getElementById('sb-debug-exposure-' + code + '-' + stype);
                
                var hedgeValue = 0;
                if (isReverse) { 
                    hedgeValue = baseData.hedgeValue;
                } else { 
                    hedgeValue = baseData.hedgeValue;
                    if (!hedgeValue || hedgeValue <= 0) {
                        hedgeValue = baseData.etfHedgeValue;
                    }
                }

                if(dbgHedgeEl) dbgHedgeEl.textContent = hedgeValue > 0 ? hedgeValue.toFixed(4) : '-';
                
                if (hedgeValue && hedgeValue > 0 && capitalA > 0 && lofRealtimePrice > 0) {
                    var finalEtfQty = 0;
                    var finalLofQty = 0;
                    
                    if (baseData.category === '纯ETF' || baseData.category === '指数') {
                        var tempLofQty = capitalA / lofRealtimePrice;
                        finalEtfQty = Math.max(1, Math.round(tempLofQty / hedgeValue));
                        finalLofQty = Math.round((finalEtfQty * hedgeValue) / 100) * 100;
                    } else {
                        finalLofQty = Math.round((capitalA / lofRealtimePrice) / 100) * 100;
                        finalEtfQty = Math.max(1, Math.round(finalLofQty / hedgeValue));
                    }
                    
                    var realExposure = capitalA * baseData.position;
                    if(dbgExposureEl) dbgExposureEl.textContent = realExposure > 0 ? realExposure.toFixed(2) + ' 元' : '-';
                    
                    if(lofQtyEl) lofQtyEl.textContent = finalLofQty;
                    if(etfQtyEl) etfQtyEl.textContent = finalEtfQty;
                    
                    var tradeVolEl = document.getElementById('trade-vol-' + code + '-' + stype);
                    var ibTradeVolEl = document.getElementById('ib-trade-vol-' + code + '-' + stype);
                    var ibFutureVolEl = document.getElementById('ib-future-vol-' + code);
                    
                    var isUserTrigger = (window.event && window.event.type === 'input' && window.event.target && window.event.target.id.startsWith('sb-target-'));
                    if (isUserTrigger) {
                        if (tradeVolEl) delete tradeVolEl.dataset.manual;
                        if (ibTradeVolEl) delete ibTradeVolEl.dataset.manual;
                        if (ibFutureVolEl) delete ibFutureVolEl.dataset.manual;
                    }
                    
                    if(tradeVolEl && !tradeVolEl.dataset.manual) tradeVolEl.value = finalLofQty;
                    
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

                    if(typeof isReverse !== 'undefined' && isReverse && ibFutureVolEl && !ibFutureVolEl.dataset.manual) ibFutureVolEl.value = typeof futuresLots !== 'undefined' ? futuresLots : 0;
                } else {
                    if(lofQtyEl) lofQtyEl.textContent = '?';
                    if(etfQtyEl) etfQtyEl.textContent = '?';
                }
            };

            // 实时估值计算刷新（由夜盘或轮询触发）
            window.calculateRealTimeValues = function() {
                var isIb = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                var isFutu = document.getElementById('source-futu') && document.getElementById('source-futu').checked;
                var isManual = document.getElementById('source-manual') && document.getElementById('source-manual').checked;
        
                window.currentEtfPrices = {};
                window.activeEtfs.forEach(function(sym) {
                    var price = 0;
                    if (isIb && window.latestIbPrices && window.latestIbPrices[sym] && window.latestIbPrices[sym].bid) {
                        price = window.latestIbPrices[sym].bid;
                    } else if (isFutu && window.latestFutuPrices && window.latestFutuPrices[sym] && window.latestFutuPrices[sym].bid) {
                        price = window.latestFutuPrices[sym].bid;
                    } else if (isManual) {
                        var manualEl = document.getElementById(sym.toLowerCase() + '-price');
                        if (manualEl) price = parseFloat(manualEl.value);
                    }
                    if (!price || isNaN(price)) {
                        var prevEl = document.getElementById('prev-val-' + sym.toLowerCase());
                        if (prevEl) price = parseFloat(prevEl.textContent);
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
                    var equivEtf = futPrice / calib;
                    if (equivEl) equivEl.textContent = equivEtf.toFixed(3);
                    
                    var weightedEtfChangeRate = 0;
                    var validWeight = 0;
                    baseData.hedgingPortfolio.forEach(function(item) {
                        var basePrice = baseData.baseEtfPrices[item.symbol];
                        if (basePrice > 0 && item.weight > 0) {
                            weightedEtfChangeRate += (equivEtf / basePrice) * item.weight;
                            validWeight += item.weight;
                        }
                    });
                    
                    if (validWeight > 0) {
                        if (validWeight < 0.98 || validWeight > 1.02) {
                            weightedEtfChangeRate = weightedEtfChangeRate / validWeight;
                        }
                        var exchangeRateChange = baseData.todayExchangeRate / baseData.baseExchangeRate;
                        val = baseData.baseNav * (1 + baseData.position * (weightedEtfChangeRate * exchangeRateChange - 1));
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
        
                window.calcHedgeQty(code, 'future');
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
                    var futureChangeRate = futPrice / baseData.baseFuturePrice;
                    var exchangeRateChange = baseData.todayExchangeRate / baseData.baseExchangeRate;
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
        
                window.calcHedgeQty(code, 'pure_future');
            };
        
            window.updateFuturesData = function() {
                // 如有额外统一联动的页面要素更新，在此触发
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
                var downloadUrl = 'http://localhost:5000/api/export_fund/' + code;
                var a = document.createElement('a');
                a.href = downloadUrl; a.download = 'fund_' + code + '_export.csv';
                document.body.appendChild(a); a.click(); document.body.removeChild(a);
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