import os
import re

file_path = "LOFarb/LOF034_js_generator.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. 替换 calculateETFRealTimeValuation 逻辑 (包含健壮性增强与纯魔法公式支持，不带缩放)
new_calc_func = """            function calculateETFRealTimeValuation(fundCode, category, staticValuation) {
                var baseData = window.fundBaseData[fundCode];
                if (!baseData) { console.error('Missing baseData for ' + fundCode); return 0; }
                
                var position = parseFloat(baseData.position);
                if (isNaN(position) || position <= 0) position = 0.95; 

                var reqSpot = (baseData.rateType === 'spot');
                var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                
                if (!todayExchangeRate || todayExchangeRate <= 0) {
                    return 0; 
                }
                
                var baseNav = parseFloat(baseData.baseNav);
                var baseFX = parseFloat(baseData.baseExchangeRate);
                if (isNaN(baseNav) || baseNav <= 0 || isNaN(baseFX) || baseFX <= 0) {
                    return 0;
                }

                var hedgeValue = parseFloat(baseData.hedgeValue); 
                var etfCalibration = (hedgeValue > 0) ? hedgeValue * position : 0;
                
                function getCurrentPrice(sym) {
                    var upperSym = sym.toUpperCase().replace('^', '');
                    if (window.currentEtfPrices[upperSym] !== undefined && window.currentEtfPrices[upperSym] > 0) {
                        return window.currentEtfPrices[upperSym];
                    }
                    var cleanSym = upperSym.split('-')[0];
                    return window.currentEtfPrices[cleanSym] || 0;
                }

                // 1. 优先尝试魔法公式 (针对单标的基金，包括指数基金，直接使用 hedge，无需缩放)
                if (etfCalibration > 0 && baseData.hedgingPortfolio.length === 1) {
                    var primarySym = baseData.hedgingPortfolio[0].symbol;
                    var currentAssetPrice = getCurrentPrice(primarySym);
                    if (currentAssetPrice > 0) {
                        return baseNav * (1.0 - position) + (position / etfCalibration) * (currentAssetPrice * todayExchangeRate);
                    }
                }

                // 2. 矩阵兜底算法 (商品多资产或因子缺失)
                var weightedEtfChangeRate = 0;
                var hasValidData = false;
                var validWeight = 0;
                var exchangeRateChange = todayExchangeRate / baseFX;

                for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                    var item = baseData.hedgingPortfolio[i];
                    var sym = item.symbol;
                    var isAshare = /^[0-9]{5,6}$/.test(sym) || /^(sh|sz)[0-9]{6}$/i.test(sym);
                    var weight = parseFloat(item.weight);
                    if (isNaN(weight) || weight <= 0) continue;
                    
                    var normWeight = weight > 2 ? weight / 100.0 : weight;

                    var currentPrice = 0;
                    if (isAshare) {
                        var cleanCode = sym.replace(/^(sh|sz)/i, '');
                        currentPrice = (window.latestLofPrices && window.latestLofPrices[cleanCode]) || 0;
                        if (currentPrice === 0) {
                            var el = document.getElementById('realtime-price-' + cleanCode);
                            if (el) {
                                var match = el.textContent.match(/[\\d.]+/);
                                if (match) currentPrice = parseFloat(match[0]) || 0;
                            }
                        }
                    } else {
                        currentPrice = getCurrentPrice(sym);
                    }

                    var basePrice = parseFloat(baseData.baseEtfPrices[sym]);
                    if (isNaN(basePrice) || basePrice <= 0) {
                        basePrice = parseFloat(baseData.baseEtfPrices[sym.replace('^', '')]);
                    }
                    
                    if (basePrice > 0 && currentPrice > 0) {
                        var changeRate = currentPrice / basePrice;
                        if (!isAshare) changeRate = changeRate * exchangeRateChange;
                        weightedEtfChangeRate += changeRate * normWeight;
                        validWeight += normWeight;
                        hasValidData = true;
                    }
                }

                if (!hasValidData) return 0;
                
                if (Math.abs(validWeight - 1.0) > 0.01 && validWeight > 0) {
                    weightedEtfChangeRate = weightedEtfChangeRate / validWeight;
                }

                return baseNav * (1 + position * (weightedEtfChangeRate - 1));
            }"""

# 寻找旧函数并替换
pattern = r"            function calculateETFRealTimeValuation.*?window\.calculateETFRealTimeValuation = calculateETFRealTimeValuation;"
content = re.sub(pattern, new_calc_func + "\n\n            // 暴露到全局供其他模块调用\n            window.calculateETFRealTimeValuation = calculateETFRealTimeValuation;", content, flags=re.DOTALL)

# 2. 修复 updateSandboxRealtimePrices
new_update_sandbox = """            window.updateSandboxRealtimePrices = function(code) {
                var sandboxPage = document.getElementById('page-rt-etf-' + code);
                if (!sandboxPage || !sandboxPage.classList.contains('active')) return;

                var baseData = window.fundBaseData[code];
                if (!baseData) return;

                baseData.hedgingPortfolio.forEach(function(item) {
                    var sym = item.symbol;
                    var sanitizedSym = sym.replace(/\\^/g, '').replace(/-/g, '_').replace(/\\./g, '_');
                    var priceEl = document.getElementById('sb-rt-price-' + code + '-' + sanitizedSym);
                    if (priceEl) {
                        var cleanSymForPriceLookup = sym.replace(/^(sh|sz)/i, '').replace(/\\^/g, '').split('-')[0].toUpperCase();
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
            };"""

content = re.sub(r"            window\.updateSandboxRealtimePrices = function.*?            window\.openSandbox", new_update_sandbox + "\n\n            window.openSandbox", content, flags=re.DOTALL)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("SUCCESS: Cleanly restored LOF034_js_generator.py logic without mangling blocks.")
