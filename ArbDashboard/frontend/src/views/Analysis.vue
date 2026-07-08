<template>
  <div class="analysis-page">
    <!-- 1. 雷达模式：当没有选择基金时显示机会榜单 -->
    <div v-if="!fundCode || fundCode === 'radar'" class="radar-mode animate-fade-in">
      <n-card :bordered="false" class="shadow-soft">
        <template #header>
          <!-- 标题行 -->
          <div class="flex-center gap-2" style="margin-bottom: 12px;">
            <n-icon size="24" color="#2563eb"><Zap /></n-icon>
            <span class="text-xl font-bold">全场套利机会实时雷达</span>
          </div>
          <!-- 筛选控件行 -->
          <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
            <!-- 左侧：Tab筛选 -->
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <!-- 我的自选Tab -->
              <n-checkbox v-model:checked="showWatchlistOnly" size="small" label-style="font-weight: bold; color: #f59e0b; font-size: 14px;">
                ★ 我的自选
              </n-checkbox>
              <n-divider vertical />
              <!-- 分类筛选 -->
              <n-checkbox :checked="selectedCategories.includes('gold_oil')" @update:checked="toggleCategory('gold_oil')" label-style="font-weight: bold; color: #333;">
                黄金原油
              </n-checkbox>
              <n-checkbox :checked="selectedCategories.includes('qdii_us')" @update:checked="toggleCategory('qdii_us')" label-style="font-weight: bold; color: #333;">
                QDII欧美
              </n-checkbox>
              <n-checkbox :checked="selectedCategories.includes('qdii_asia')" @update:checked="toggleCategory('qdii_asia')" label-style="font-weight: bold; color: #333;">
                QDII亚洲
              </n-checkbox>
              <n-checkbox :checked="selectedCategories.includes('domestic_lof')" @update:checked="toggleCategory('domestic_lof')" label-style="font-weight: bold; color: #333;">
                国内LOF
              </n-checkbox>
              <n-checkbox :checked="selectedCategories.includes('silver')" @update:checked="toggleCategory('silver')" label-style="font-weight: bold; color: #333;">
                白银
              </n-checkbox>
            </div>
            <!-- 右侧：折价率阈值 -->
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-size: 12px; color: #666;">折价率:</span>
              <n-input-number v-model:value="premiumThreshold" :min="-10" :max="10" :step="0.1" style="width: 100px;" size="small" @update:value="onThresholdChange" /> %
              <span style="font-size: 12px; color: #666;">~</span>
              <n-input-number v-model:value="premiumUpperThreshold" :min="-10" :max="10" :step="0.1" style="width: 100px;" size="small" @update:value="onThresholdChange" /> %
              <n-tag type="success" ghost>触发: {{ premiumThreshold }}% ~ {{ premiumUpperThreshold }}%</n-tag>
            </div>
          </div>
        </template>
        
        <n-data-table
          :columns="radarColumns"
          :data="opportunityData"
          size="small"
          bordered
          :pagination="{ pageSize: 10 }"
          class="radar-table"
        >
          <template #empty>
            <div style="padding: 40px 0; text-align: center; color: #999;">
              <n-icon size="48" color="#ddd"><SearchX /></n-icon>
              <p style="margin-top: 12px; font-size: 14px;">
                {{ selectedCategories.length === 0 ? '请在上方选择一个分类' : '该分类下暂无符合条件的基金' }}
              </p>
            </div>
          </template>
        </n-data-table>
      </n-card>
    </div>

    <!-- 2. 详情模式：专业狙击工作站 -->
    <div v-else class="detail-mode animate-fade-in">
      <!-- 顶部专业摘要栏 (标题 + 基础仓位) -->
      <div class="fund-summary-header shadow-soft" style="background: #fff; padding: 12px 20px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 2px solid #ffcc80;">
         <div class="header-left" style="display: flex; align-items: center; gap: 16px;">
            <n-button quaternary circle @click="handleBack"><template #icon><n-icon><ArrowLeft /></n-icon></template></n-button>
            <div class="fund-info">
               <div style="font-size:18px; font-weight:bold; color: #d35400;">
                   {{ fundName }} ({{ fundCode }})
                   <template v-if="vcRef?.isCashManagement && vcRef?.cashFundInfo">
                      <n-tag type="success" size="small" round style="margin-left: 8px;">{{ vcRef.cashFundInfo.type }}</n-tag>
                      <n-tag type="info" size="small" round style="margin-left: 4px;">{{ vcRef.cashFundInfo.riskLevel }}</n-tag>
                   </template>
                   <template v-else>
                      - 实时估值计算器
                   </template>
               </div>
            </div>
             <template v-if="!vcRef?.isCashManagement">
                <n-tag type="warning" size="medium" round style="font-weight: bold;">
                   基础仓位: {{ ((vcRef?.positionRatio ?? 0.95) * 100).toFixed(2) }}%
                </n-tag>
             </template>
             <template v-else>
                <n-tag type="success" size="medium" round style="font-weight: bold;">
                   日均增长: {{ vcRef?.meta?.avg_daily_growth ? (vcRef.meta.avg_daily_growth * 10000).toFixed(1) + '万' : '-' }}
                </n-tag>
             </template>
         </div>
         <div class="header-right" v-if="!vcRef?.isCashManagement" style="display: flex; align-items: center; gap: 12px;">
            <n-checkbox :disabled="!vcRef?.meta?.fund_config?.trade_future" :checked="!!vcRef?.showFutCalib" @update:checked="(v) => { if (vcRef) vcRef.showFutCalib = v }" size="large"><span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: vcRef?.meta?.fund_config?.trade_future ? 1 : 0.5 }">期货校准估值</span></n-checkbox>
            <n-checkbox :disabled="!vcRef?.meta?.fund_config?.trade_future" :checked="!!vcRef?.showPureFut" @update:checked="(v) => { if (vcRef) vcRef.showPureFut = v }" size="large"><span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: vcRef?.meta?.fund_config?.trade_future ? 1 : 0.5 }">纯期货估值</span></n-checkbox>
         </div>
      </div>

      <!-- [AI-2026-07-08] 共享估值计算器组件（替换原有 T-2/T-1/实时行 + 现金管理 + 估值推演面板） -->
      <ValuationCalculator ref="vcRef" :fund-code="fundCode" />

      <!-- 第五行: 买卖五档的行情表 (并排显示) -->
      <div class="depth-tables-container" v-if="vcRef?.isComplexCategory">
         <!-- A股 LOF 盘口 (QMT/TDX) -->
         <n-card title="A股 LOF 盘口" :bordered="false" class="depth-table-card-left shadow-soft" size="small">
            <template #header-extra>
               <n-tag size="tiny" :type="vcRef?.depth.source ? 'info' : 'default'">{{ vcRef?.localDepthSource }}</n-tag>
            </template>
            <div class="market-depth">
               <div class="depth-list asks">
                  <div v-for="i in [4,3,2,1,0]" :key="'ask'+i" class="depth-row clickable" @click="vcRef && (vcRef.simLofPrice = vcRef.depth.ask[i] || vcRef.simLofPrice)" style="cursor: pointer;">
                     <span class="label" style="color: #666;">卖 {{ i+1 }}</span>
                     <span class="price text-red" style="font-family: monospace;">{{ vcRef?.depth.ask[i]?.toFixed(3) || '-' }}</span>
                     <span class="vol" style="font-family: monospace;">{{ vcRef?.depth.ask_vol[i] || '-' }}</span>
                  </div>
               </div>
               <n-divider style="margin: 6px 0" />
               <div class="depth-list bids">
                  <div v-for="i in [0,1,2,3,4]" :key="'bid'+i" class="depth-row clickable" @click="vcRef && (vcRef.simLofPrice = vcRef.depth.bid[i] || vcRef.simLofPrice)" style="cursor: pointer;">
                     <span class="label" style="color: #666;">买 {{ i+1 }}</span>
                     <span class="price text-green" style="font-family: monospace;">{{ vcRef?.depth.bid[i]?.toFixed(3) || '-' }}</span>
                     <span class="vol" style="font-family: monospace;">{{ vcRef?.depth.bid_vol[i] || '-' }}</span>
                  </div>
               </div>
            </div>
         </n-card>

         <!-- 中间：下单执行面板与操作按键 -->
         <n-card title="交易执行面板" :bordered="false" class="chart-card-middle sandbox-card shadow-soft" size="small" style="background: #fffdf5; border: 1px solid #ffcc80;">
            <div class="sandbox-layout" style="display: flex; flex-direction: column; gap: 8px;">
               <!-- 下单区-1: A股 LOF -->
               <div style="width: 100%; display: flex; align-items: center; gap: 6px; background: #fff5f5; padding: 6px 10px; border-radius: 6px; border: 1px solid #ffcdd2; flex-wrap: wrap; box-sizing: border-box;">
                  <span style="color:#666; font-size: 12px;">券商:</span>
                  <n-select v-model:value="lofBroker" size="small" style="width: 130px;" :options="[ { label: '银河QMT', value: 'yinhe_qmt' }, { label: '通达信(华宝)', value: 'tdx' }, { label: '国金QMT', value: 'guojin_qmt' } ]" />
                  <span style="font-weight:bold; color:#d32f2f; font-size:13px;">{{ fundName }} ({{ fundCode }}):</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number v-model:value="orderVol" :step="100" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number :value="vcRef?.simLofPrice ?? 0" @update:value="(v: any) => { if (vcRef) vcRef.simLofPrice = v }" :step="0.001" size="small" style="width: 100px;" :show-button="false" />
               </div>

               <!-- 下单区-2: IB ETF -->
               <div style="width: 100%; display: flex; align-items: center; gap: 6px; background: #e3f2fd; padding: 6px 10px; border-radius: 6px; border: 1px solid #bbdefb; flex-wrap: wrap; box-sizing: border-box;">
                  <span style="font-weight:bold; color:#1565c0; font-size:13px;">🌍 IB {{ vcRef?.meta?.fund_config?.trade_etf }}:</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number v-model:value="hedgeVol" :step="10" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number v-model:value="hedgePrice" :step="0.01" size="small" style="width: 100px;" :show-button="false" />
               </div>

               <!-- 下单区-3: IB 期货 -->
               <div v-if="vcRef?.showFutCalib || vcRef?.showPureFut" style="width: 100%; display: flex; align-items: center; gap: 6px; background: #fff3e0; padding: 6px 10px; border-radius: 6px; border: 1px solid #ffcc80; flex-wrap: wrap; box-sizing: border-box;">
                  <span style="font-weight:bold; color:#e65100; font-size:13px;">🌍 IB期货 ({{ vcRef?.meta?.fund_config?.trade_future }}):</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number :value="vcRef?.targetLotsFuture ?? 1" @update:value="(v: any) => { if (vcRef) vcRef.targetLotsFuture = v }" :step="1" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number :value="vcRef?.testFutPrice ?? 0" @update:value="(v: any) => { if (vcRef) vcRef.testFutPrice = v }" :step="0.01" size="small" style="width: 100px;" :show-button="false" />
               </div>
            </div>

            <!-- 下单按键区 -->
            <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; margin-top: 12px; border-top: 1px dashed #fed7aa; padding-top: 12px;">

               
               <!-- 第一行：买入/开仓按键 -->
               <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                  <n-button type="success" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'lof')">{{ fundCode }} 折价买入</n-button>
                  <n-button type="warning" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'ib')">IB {{ vcRef?.meta?.fund_config?.trade_etf }} 卖空</n-button>
                  <n-button v-if="vcRef?.showFutCalib || vcRef?.showPureFut" type="warning" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'ib_future')">{{ vcRef?.meta?.fund_config?.trade_future }} 期货卖空</n-button>
               </div>
               <!-- 第二行：卖出/平仓按键 -->
               <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                  <n-button type="error" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'lof')">{{ fundCode }} 溢价卖出</n-button>
                  <n-button type="info" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'ib')">IB {{ vcRef?.meta?.fund_config?.trade_etf }} 买平</n-button>
                  <n-button v-if="vcRef?.showFutCalib || vcRef?.showPureFut" type="info" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'ib_future')">{{ vcRef?.meta?.fund_config?.trade_future }} 期货买平</n-button>
               </div>
            </div>

            <div style="margin-top: 8px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #888;">
               <n-checkbox v-model:checked="autoLog" size="small">同步记账</n-checkbox>
               <span>* 实时参数更新</span>
            </div>
         </n-card>

         <!-- 右侧：外盘/期货实时行情盘口 (IB/Futu) -->
         <n-card title="外盘/期货 盘口" :bordered="false" class="depth-table-card-right shadow-soft" size="small">
            <template #header-extra>
               <n-tag size="tiny" :type="(vcRef?.foreignSource ?? '').includes('等待') ? 'default' : 'success'">{{ vcRef?.foreignSource }}</n-tag>
            </template>
            <div style="padding: 10px; display: flex; flex-direction: column; gap: 8px;">
               <!-- ETF 实时价格 (USO, GLD, etc.) -->
               <div v-for="item in (vcRef?.uniqueValuationSymbols ?? [])" :key="item.symbol" 
                    style="background: #f0f7ff; padding: 6px 10px; border-radius: 6px; border: 1px solid #bae6fd; display: flex; flex-direction: column; gap: 4px;">
                  <div style="font-weight: bold; color: #0369a1; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
                     <span>📊 {{ item.symbol }} 实时盘口</span>
                     <span style="font-size: 10px; color: #64748b; font-weight: normal;">({{ item.currency }})</span>
                  </div>
                  <div style="display: flex; justify-content: space-between; font-size: 12px;">
                     <span style="color:#2e7d32; font-weight:bold; cursor:pointer;" @click="hedgePrice = (vcRef?.meta?.realtime_quotes as any)?.[item.symbol]?.bid ?? hedgePrice" title="点击填入买一价">
                        买一: <span style="font-family: monospace;">{{ (vcRef?.meta?.realtime_quotes as any)?.[item.symbol]?.bid?.toFixed(2) || '等待数据' }}</span>
                     </span>
                     <span style="color:#d32f2f; font-weight:bold; cursor:pointer;" @click="hedgePrice = (vcRef?.meta?.realtime_quotes as any)?.[item.symbol]?.ask ?? hedgePrice" title="点击填入卖一价">
                        卖一: <span style="font-family: monospace;">{{ (vcRef?.meta?.realtime_quotes as any)?.[item.symbol]?.ask?.toFixed(2) || '等待数据' }}</span>
                     </span>
                  </div>
               </div>

               <!-- 期货实时价格 (CL, GC, etc.) -->
               <div v-if="vcRef?.meta?.fund_config?.trade_future && (vcRef?.showFutCalib || vcRef?.showPureFut)" 
                    style="background: #fff3e0; padding: 6px 10px; border-radius: 6px; border: 1px solid #fef08a; display: flex; flex-direction: column; gap: 4px;">
                  <div style="font-weight: bold; color: #d97706; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
                     <span>📊 {{ vcRef?.meta?.fund_config?.trade_future }} 实时盘口:</span>
                     <span style="font-size: 10px; color: #78350f; font-weight: normal;">({{ vcRef?.meta?.future_quote?.source || '新浪' }})</span>
                  </div>
                  <div style="display: flex; justify-content: space-between; font-size: 12px;">
                     <span style="color:#2e7d32; font-weight:bold; cursor:pointer;" @click="vcRef && (vcRef.testFutPrice = (typeof vcRef.meta?.future_quote === 'object' ? (vcRef.meta.future_quote as any)?.bid : vcRef.meta?.future_quote) ?? vcRef.testFutPrice)" title="点击填入买一价">
                        买一: <span style="font-family: monospace;">{{ (typeof vcRef?.meta?.future_quote === 'object' ? (vcRef?.meta?.future_quote as any)?.bid?.toFixed(2) : (vcRef?.meta?.future_quote as any)?.toFixed(2)) || '等待数据' }}</span>
                     </span>
                     <span style="color:#d32f2f; font-weight:bold; cursor:pointer;" @click="vcRef && (vcRef.testFutPrice = (typeof vcRef.meta?.future_quote === 'object' ? (vcRef.meta.future_quote as any)?.ask : vcRef.meta?.future_quote) ?? vcRef.testFutPrice)" title="点击填入卖一价">
                        卖一: <span style="font-family: monospace;">{{ (typeof vcRef?.meta?.future_quote === 'object' ? (vcRef?.meta?.future_quote as any)?.ask?.toFixed(2) : (vcRef?.meta?.future_quote as any)?.toFixed(2)) || '等待数据' }}</span>
                     </span>
                  </div>
               </div>
            </div>
         </n-card>
      </div>

      <!-- [现金管理] 估值算法历史记录表 (替代分时曲线图) -->
      <n-card v-if="vcRef?.isCashManagement && (fundCode === '511520' || fundCode === '511360') && historyBacktestData.length > 0" :title="fundCode === '511520' ? '估值算法回测 (预估 vs 实际)' : '历史记录'" :bordered="false" class="shadow-soft" style="margin-top: 12px;" size="small">
         <template #header-extra>
            <span v-if="fundCode === '511520'" style="font-size: 12px; color: #64748b;">公式: 前日NAV + 0.0082 + 前日NAV × T2609涨幅% × 1.0</span>
         </template>
         <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 12px; font-family: monospace;">
               <thead>
                  <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                     <th style="padding: 6px 8px; text-align: left;">日期</th>
                     <th style="padding: 6px 8px; text-align: right;">净值涨幅</th>
                     <th style="padding: 6px 8px; text-align: right;">收盘价</th>
                     <template v-if="fundCode === '511520'">
                        <th style="padding: 6px 8px; text-align: right;">T2609%</th>
                        <th style="padding: 6px 8px; text-align: right;">预估NAV</th>
                     </template>
                     <th style="padding: 6px 8px; text-align: right;">实际NAV</th>
                     <template v-if="fundCode === '511520'">
                        <th style="padding: 6px 8px; text-align: right;">误差</th>
                        <th style="padding: 6px 8px; text-align: right;">误差率</th>
                     </template>
                     <template v-if="fundCode === '511360'">
                        <th style="padding: 6px 8px; text-align: right;">国债指数%</th>
                     </template>
                  </tr>
               </thead>
               <tbody>
                  <tr v-for="(row, idx) in historyBacktestData" :key="idx" :style="{ background: row.estimation_error_pct != null && row.estimation_error_pct > 0.05 ? '#fef2f2' : 'transparent', borderBottom: '1px solid #f1f5f9' }">
                     <td style="padding: 4px 8px;">{{ row.date ? row.date.substring(5) : '-' }}</td>
                     <!-- 净值涨幅 = 今日NAV / 昨日NAV - 1 -->
                     <td style="padding: 4px 8px; text-align: right;">
                        <template v-if="row.nav && idx < historyBacktestData.length - 1 && historyBacktestData[idx + 1].nav">
                           <span :style="{ color: (row.nav / historyBacktestData[idx + 1].nav - 1) > 0 ? '#d32f2f' : (row.nav / historyBacktestData[idx + 1].nav - 1) < 0 ? '#388e3c' : '#999', fontWeight: 'bold' }">
                              {{ ((row.nav / historyBacktestData[idx + 1].nav - 1) * 100).toFixed(3) }}%
                           </span>
                        </template>
                        <span v-else style="color: #999;">-</span>
                     </td>
                     <!-- 收盘价 -->
                     <td style="padding: 4px 8px; text-align: right;">{{ row.price != null ? row.price.toFixed(3) : '-' }}</td>
                     <!-- 511520 专属列 -->
                     <template v-if="fundCode === '511520'">
                        <td style="padding: 4px 8px; text-align: right;" :style="{ color: row.futures_pct != null ? (row.futures_pct > 0 ? '#d32f2f' : '#388e3c') : '#999' }">{{ row.futures_pct != null ? (row.futures_pct > 0 ? '+' : '') + row.futures_pct.toFixed(3) + '%' : '-' }}</td>
                        <td style="padding: 4px 8px; text-align: right; font-weight: bold; color: #1565c0;">{{ row.estimated_nav != null ? row.estimated_nav.toFixed(4) : '-' }}</td>
                     </template>
                     <td style="padding: 4px 8px; text-align: right; font-weight: bold;">{{ row.nav != null ? row.nav.toFixed(4) : '-' }}</td>
                     <!-- 511520 误差列 -->
                     <template v-if="fundCode === '511520'">
                        <td style="padding: 4px 8px; text-align: right;" :style="{ color: row.estimation_error != null ? (row.estimation_error > 0 ? '#388e3c' : '#d32f2f') : '#999' }">{{ row.estimation_error != null ? (row.estimation_error > 0 ? '+' : '') + row.estimation_error.toFixed(4) : '-' }}</td>
                        <td style="padding: 4px 8px; text-align: right;">
                           <n-tag v-if="row.estimation_error_pct != null" :type="row.estimation_error_pct <= 0.05 ? 'success' : row.estimation_error_pct <= 0.10 ? 'warning' : 'error'" size="tiny" round>
                              {{ row.estimation_error_pct.toFixed(4) }}%
                           </n-tag>
                           <span v-else style="color: #999;">-</span>
                        </td>
                     </template>
                     <!-- 511360 国债指数列 -->
                     <template v-if="fundCode === '511360'">
                        <td style="padding: 4px 8px; text-align: right;" :style="{ color: row.idx_pct != null ? (row.idx_pct > 0 ? '#d32f2f' : '#388e3c') : '#999' }">{{ row.idx_pct != null ? (row.idx_pct > 0 ? '+' : '') + row.idx_pct.toFixed(3) + '%' : '-' }}</td>
                     </template>
                  </tr>
               </tbody>
            </table>
         </div>
         <!-- 511520 回测统计 -->
         <div v-if="fundCode === '511520'" style="margin-top: 8px; font-size: 11px; color: #64748b; display: flex; gap: 16px;">
            <span>有效回测天数: {{ historyBacktestData.filter(r => r.estimation_error_pct != null).length }}</span>
            <span>平均误差: {{ (historyBacktestData.filter(r => r.estimation_error_pct != null).reduce((s, r) => s + r.estimation_error_pct, 0) / Math.max(historyBacktestData.filter(r => r.estimation_error_pct != null).length, 1)).toFixed(4) }}%</span>
            <span>最大误差: {{ Math.max(...historyBacktestData.filter(r => r.estimation_error_pct != null).map(r => r.estimation_error_pct), 0).toFixed(4) }}%</span>
            <span>≤0.05%: {{ (historyBacktestData.filter(r => r.estimation_error_pct != null && r.estimation_error_pct <= 0.05).length / Math.max(historyBacktestData.filter(r => r.estimation_error_pct != null).length, 1) * 100).toFixed(1) }}%</span>
            <span>≤0.10%: {{ (historyBacktestData.filter(r => r.estimation_error_pct != null && r.estimation_error_pct <= 0.10).length / Math.max(historyBacktestData.filter(r => r.estimation_error_pct != null).length, 1) * 100).toFixed(1) }}%</span>
         </div>
      </n-card>

      <!-- 第六行: 分时曲线图 (从中间移到下方) -->
      <!-- [现金管理] 隐藏：债券ETF无分时采样数据 -->
      <n-card v-if="!vcRef?.isCashManagement" title="分时对冲走势 (1分钟采样)" :bordered="false" class="shadow-soft" style="margin-top: 12px;" size="small">
         <template #header-extra>
            <n-tag :type="intradayData.length > 0 ? 'success' : 'warning'" size="tiny" round>{{ intradayData.length }} 采样点</n-tag>
         </template>
         <div class="chart-container" style="height: 300px;">
           <n-empty v-if="intradayData.length === 0" description="该日期暂无采样数据" style="padding-top: 60px;" />
           <v-chart v-else class="chart" :option="chartOption" autoresize />
         </div>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
// [AI-2026-07-08] 重构：移除重复的估值计算器逻辑，使用共享 ValuationCalculator 组件
import { ref, onMounted, computed, watch, h, onUnmounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NSpace, NButton, NEmpty,
  NText, NDataTable, NTag, NDatePicker, NIcon, NInputNumber, useMessage, NCheckbox, NDivider, NSelect, useDialog
} from 'naive-ui'
import { RefreshCw, Zap, ArrowLeft, Star, StarOff, SearchX } from 'lucide-vue-next'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { getDashboard, getFundIntraday, getFundBasket, getFundHistory } from '../api'
import { useOrderLogic } from '../composables/useOrderLogic'
import ValuationCalculator from '../components/ValuationCalculator.vue'

use([CanvasRenderer, LineChart, BarChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent])

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

// 共享估值计算器组件 ref（通过它访问所有估值状态）
const vcRef = ref<InstanceType<typeof ValuationCalculator>>()

// 基础状态
const fundCode = ref((route.query.code as string) || '')
const fundName = ref((route.query.name as string) || '')
const opportunityData = ref<any[]>([])
const intradayData = ref<any[]>([])
const basketData = ref<any[]>([])
const historyBacktestData = ref<any[]>([])
const loading = ref(false)
const selectedDate = ref(Date.now())

// 雷达筛选相关
const selectedCategories = ref<string[]>([])
const premiumThreshold = ref(-0.5)
const premiumUpperThreshold = ref(2.0)
const showWatchlistOnly = ref(false)
const watchlist = ref<string[]>(JSON.parse(localStorage.getItem('watchlist') || '[]'))

// 分类映射：前端显示名称 → 数据库category值
const categoryMap: Record<string, string[]> = {
  'gold_oil': ['黄金原油'],
  'qdii_us': ['纯ETF', 'QDII欧美', '混合跨境', '指数'],
  'qdii_asia': ['QDII 亚洲', 'QDII亚洲'],
  'domestic_lof': ['指数LOF', '其他', '国内LOF'],
  'silver': ['白银']
}

// 监听自选列表变化，自动保存
watch(watchlist, (newVal) => {
  localStorage.setItem('watchlist', JSON.stringify(newVal))
}, { deep: true })

// 切换自选列表
const toggleWatchlist = (code: string) => {
  const index = watchlist.value.indexOf(code)
  if (index > -1) {
    watchlist.value.splice(index, 1)
  } else {
    watchlist.value.push(code)
  }
}

// 从localStorage加载筛选设置
const loadFilterSettings = () => {
  const savedCategories = localStorage.getItem('radar_selectedCategories')
  if (savedCategories) {
    try {
      selectedCategories.value = JSON.parse(savedCategories)
    } catch (e) {
      selectedCategories.value = []
    }
  }
  
  const savedLower = localStorage.getItem('premiumThreshold')
  if (savedLower) {
    premiumThreshold.value = parseFloat(savedLower) || -0.5
  }
  
  const savedUpper = localStorage.getItem('premiumUpperThreshold')
  if (savedUpper) {
    premiumUpperThreshold.value = parseFloat(savedUpper) || 2.0
  }
}

// 保存筛选设置到localStorage
const saveFilterSettings = () => {
  localStorage.setItem('radar_selectedCategories', JSON.stringify(selectedCategories.value))
  localStorage.setItem('premiumThreshold', premiumThreshold.value.toString())
  localStorage.setItem('premiumUpperThreshold', premiumUpperThreshold.value.toString())
}

// 监听筛选条件变化，自动保存并刷新
watch([selectedCategories, premiumThreshold, premiumUpperThreshold, showWatchlistOnly], () => {
  saveFilterSettings()
  fetchDashboard()
}, { deep: true })

// 摘要与盘口数据（仅 Analysis 特有的状态）
const navDate = ref('-')
const calibrationValue = ref('-')
const t2Nav = ref(0)
const t1StaticVal = ref(0)

// 沙盘执行状态（仅 Analysis 特有）
const lofBroker = ref('yinhe_qmt')
const orderVol = ref(10000)
const autoLog = ref(true)
const hedgeVol = ref(10)
const hedgePrice = ref(0)

// 轮询计数
let realtimeTimer: any = null
let pollCount = 0

const stats = reactive({ maxPremium: 0, minPremium: 0, avgPremium: 0 })

const updateStats = () => {
  const premiums = intradayData.value.map(i => i.premium).filter(p => p !== null && !isNaN(p))
  if (premiums.length === 0) {
    stats.maxPremium = 0
    stats.minPremium = 0
    stats.avgPremium = 0
    return
  }
  stats.maxPremium = Math.max(...premiums)
  stats.minPremium = Math.min(...premiums)
  stats.avgPremium = premiums.reduce((a, b) => a + b, 0) / premiums.length
}

const currentPrice = computed(() => intradayData.value.length > 0 ? (intradayData.value[intradayData.value.length-1].price || 0) : 0)
const currentRtVal = computed(() => intradayData.value.length > 0 ? (intradayData.value[intradayData.value.length-1].rt_val || 0) : 0)
const currentPremium = computed(() => intradayData.value.length > 0 ? (intradayData.value[intradayData.value.length-1].premium || 0) : 0)

const chartOption = computed(() => {
  if (intradayData.value.length === 0) return {}
  const times = intradayData.value.map(item => item.time)
  return {
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: { xAxisIndex: 'all' } },
    legend: { data: ['基金价格', '实时估值', '实时溢价率'], top: 0 },
    grid: [
      { left: '55', right: '20', top: '12%', height: '50%' },
      { left: '55', right: '20', top: '74%', height: '18%' }
    ],
    xAxis: [
      { type: 'category', data: times, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, axisLabel: { show: false } },
      { type: 'category', gridIndex: 1, data: times, boundaryGap: false, axisLine: { onZero: true }, position: 'bottom' }
    ],
    yAxis: [
      { type: 'value', name: '价格/估值', scale: true, splitLine: { lineStyle: { type: 'dashed' } } },
      { type: 'value', gridIndex: 1, name: '溢价率(%)', axisLabel: { formatter: '{value}%' }, splitLine: { show: false } }
    ],
    series: [
      { name: '基金价格', type: 'line', data: intradayData.value.map(i => i.price), smooth: true, showSymbol: false, itemStyle: { color: '#3b82f6' } },
      { name: '实时估值', type: 'line', data: intradayData.value.map(i => i.rt_val), smooth: true, showSymbol: false, itemStyle: { color: '#f59e0b' }, lineStyle: { type: 'dashed' } },
      { name: '实时溢价率', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: intradayData.value.map(i => i.premium), itemStyle: { color: (p:any) => p.value > 0 ? '#ef4444' : '#22c55e' } }
    ]
  }
})

// 路由变化监听
watch(() => route.query.code, (newCode) => {
  fundCode.value = (newCode as string) || ''; fundName.value = (route.query.name as string) || ''
  if (fundCode.value) fetchAll(); else fetchDashboard()
})

const formatDate = (ts: number) => {
  const d = new Date(ts); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

const handleBack = () => { window.location.replace('/') }
const disableFutureDates = (ts: number) => ts > Date.now()
const handleDateChange = () => { fetchIntraday(); if (vcRef.value) vcRef.value.fetchValuationMeta() }

const fetchDashboard = async (retryCount = 0) => {
  try {
    const res = await getDashboard()
    let data = res.data.data
    
    // 1. 我的自选筛选（交集关系）
    if (showWatchlistOnly.value && watchlist.value.length > 0) {
      data = data.filter((f: any) => watchlist.value.includes(f.fund_code))
    }
    
    // 2. 分类筛选（不选分类时不显示任何基金）
    if (selectedCategories.value && selectedCategories.value.length > 0) {
      const allowedCategories = new Set<string>()
      for (const catKey of selectedCategories.value) {
        const mappedCats = categoryMap[catKey] || []
        for (const cat of mappedCats) {
          allowedCategories.add(cat)
        }
      }
      data = data.filter((f: any) => allowedCategories.has(f.category))
    } else {
      data = []
    }
    
    // 3. 折价率阈值筛选
    const lower = premiumThreshold.value
    const upper = premiumUpperThreshold.value
    data = data.filter((f: any) => f.rt_premium >= lower && f.rt_premium <= upper)
    
    opportunityData.value = data
  } catch (e) {
    console.warn(`[雷达] fetchDashboard 失败 (第${retryCount + 1}次):`, e)
    if (retryCount < 3) {
      const delay = (retryCount + 1) * 2000
      setTimeout(() => fetchDashboard(retryCount + 1), delay)
    }
  }
}

const toggleCategory = (key: string) => {
  const idx = selectedCategories.value.indexOf(key)
  if (idx > -1) {
    selectedCategories.value.splice(idx, 1)
  } else {
    selectedCategories.value.push(key)
  }
  saveFilterSettings()
  fetchDashboard()
}

const onThresholdChange = () => {
  saveFilterSettings()
  fetchDashboard()
}

const fetchIntraday = async () => {
  if (!fundCode.value) return
  loading.value = true
  try {
    const res = await getFundIntraday(fundCode.value, formatDate(selectedDate.value))
    intradayData.value = res.data.data || []
    updateStats()
  } finally { loading.value = false }
}

const fetchBasket = async () => {
  if (!fundCode.value) return
  const res = await getFundBasket(fundCode.value)
  basketData.value = res.data.data || []
  if (basketData.value.length > 0) {
      hedgePrice.value = basketData.value[0].price || 0
  }
}

const fetchHistoryMeta = async () => {
    try {
        const res = await getFundHistory(fundCode.value)
        if (res.data.status === 'ok' && res.data.data.length > 0) {
            const latest = res.data.data[0]
            navDate.value = latest.nav_date || '-'; t2Nav.value = latest.nav || 0
            t1StaticVal.value = latest.static_val || 0; calibrationValue.value = latest.calibration || '-'
            if (fundCode.value === '511520' || fundCode.value === '511360') {
                historyBacktestData.value = res.data.data
            }
        }
    } catch (e) {}
}

const fetchAll = () => { 
  fetchIntraday()
  fetchBasket()
  fetchHistoryMeta()
  vcRef.value?.fetchRealtimeDepth()
  vcRef.value?.fetchValuationMeta()
  // [AI-2026-07-08] hedgePrice 由组件内的 bid 初始化
}

const { sendLofOrder, sendIbOrder, sendDirectIbOrder } = useOrderLogic()

const sendOrder = async (action: string, brokerType: 'lof' | 'ib' | 'ib_future') => {
  if (brokerType === 'lof') {
    await sendLofOrder(action, fundCode.value, fundName.value, vcRef.value?.simLofPrice ?? 0, orderVol.value, lofBroker.value)
  } else if (brokerType === 'ib') {
    const tradeEtf = vcRef.value?.meta?.fund_config?.trade_etf?.split(',')?.[0]?.trim() || ''
    await sendDirectIbOrder(action, tradeEtf, hedgePrice.value, hedgeVol.value)
  } else if (brokerType === 'ib_future') {
    const tradeFuture = vcRef.value?.meta?.fund_config?.trade_future || ''
    await sendDirectIbOrder(action, tradeFuture, vcRef.value?.testFutPrice ?? 0, vcRef.value?.targetLotsFuture ?? 1)
  }
}

const radarColumns = [
  {
    title: '★', key: 'watchlist', width: 40, align: 'center' as const,
    render: (r: any) => h(NIcon, {
      size: 18, color: watchlist.value.includes(r.fund_code) ? '#f59e0b' : '#ddd',
      style: 'cursor: pointer;',
      onClick: (e: MouseEvent) => { e.stopPropagation(); toggleWatchlist(r.fund_code) }
    }, { default: () => watchlist.value.includes(r.fund_code) ? h(Star) : h(StarOff) })
  },
  { title: '代码', key: 'fund_code', width: 80, align: 'center' as const },
  { title: '名称', key: 'fund_name', width: 180, render:(r:any)=>h(NText,{strong:true},{default:()=>r.fund_name}) },
  { title: '现价', key: 'price', width: 90, align: 'center' as const, render:(r:any)=>r.price.toFixed(3) },
  { title: '溢价', key: 'rt_premium', width: 110, align: 'center' as const, render: (r:any) => h(NTag, { strong: true, type: r.rt_premium > 0 ? 'error' : 'success', bordered:false }, { default: () => r.rt_premium.toFixed(2) + '%' }) },
  { title: '操作', key: 'ops', width: 80, align: 'center' as const, render: (r:any) => h(NButton, { size: 'small', type: 'primary', quaternary: true, onClick: () => router.push({ path: '/analysis', query: { code: r.fund_code, name: r.fund_name } }) }, { default: () => '进场推演' }) }
]

const pollRealtime = async () => {
  if (!fundCode.value) return
  await vcRef.value?.fetchRealtimeDepth()
  await vcRef.value?.fetchValuationMeta()
  pollCount++
  if (pollCount % 10 === 0) {
    await fetchIntraday()
  }
}

onMounted(() => {
    loadFilterSettings()
    if (fundCode.value) fetchAll()
    else fetchDashboard()
    realtimeTimer = setInterval(pollRealtime, 3000)
})
onUnmounted(() => { if (realtimeTimer) clearInterval(realtimeTimer) })
</script>

<style scoped>
.analysis-page { padding: 12px; background-color: #f8fafc; min-height: 100vh; }
.fund-summary-header { background: #fff; padding: 12px 20px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.market-depth { padding: 4px; }
.depth-row { display: flex; justify-content: space-between; font-family: monospace; font-size: 12px; margin-bottom: 2px; padding: 2px 8px; border-radius: 4px; transition: background-color 0.2s; }
.depth-row.clickable:hover { background-color: #f1f5f9; }
.depth-row .price { font-weight: bold; width: 60px; text-align: right; }
.depth-row .vol { width: 50px; text-align: right; color: #475569; }
.sandbox-card { background: #fffcf5; border: 1px solid #ffcc80; padding: 16px; }
.sandbox-layout { display: flex; justify-content: space-between; align-items: center; }
.text-red { color: #ef4444; } .text-green { color: #22c55e; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04); border-radius: 12px; }
.flex-between { display: flex; justify-content: space-between; width: 100%; align-items: center; }
.flex-center { display: flex; align-items: center; }
.animate-fade-in { animation: fadeIn 0.4s ease-out; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.depth-tables-container {
  display: flex;
  gap: 12px;
  width: 100%;
  margin-top: 12px;
  align-items: stretch;
}
.depth-table-card-left {
  width: 280px;
  flex-shrink: 0;
  box-sizing: border-box;
}
.chart-card-middle {
  flex: 1;
  box-sizing: border-box;
  min-width: 0;
}
.depth-table-card-right {
  width: 280px;
  flex-shrink: 0;
  box-sizing: border-box;
}
.chart-container {
  height: 250px;
  width: 100%;
}
.chart {
  height: 100%;
  width: 100%;
}
</style>
