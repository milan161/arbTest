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
              <n-checkbox-group v-model:value="selectedCategories">
                <n-checkbox value="gold_oil" label="黄金原油" label-style="font-weight: bold; color: #333;" />
                <n-checkbox value="qdii_us" label="QDII欧美" label-style="font-weight: bold; color: #333;" />
                <n-checkbox value="qdii_asia" label="QDII亚洲" label-style="font-weight: bold; color: #333;" />
                <n-checkbox value="domestic_lof" label="国内LOF" label-style="font-weight: bold; color: #333;" />
                <n-checkbox value="silver" label="白银" label-style="font-weight: bold; color: #333;" />
              </n-checkbox-group>
            </div>
            <!-- 右侧：折价率阈值 -->
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="font-size: 12px; color: #666;">折价率:</span>
              <n-input-number v-model:value="premiumThreshold" :min="-10" :max="10" :step="0.1" style="width: 100px;" size="small" /> %
              <span style="font-size: 12px; color: #666;">~</span>
              <n-input-number v-model:value="premiumUpperThreshold" :min="-10" :max="10" :step="0.1" style="width: 100px;" size="small" /> %
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
        />
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
                  {{ fundName }} ({{ fundCode }}) - 实时估值计算器
               </div>
            </div>
            <n-tag type="warning" size="medium" round style="font-weight: bold;">
               基础仓位: {{ (positionRatio * 100).toFixed(2) }}%
            </n-tag>
         </div>
         <div class="header-right" style="display: flex; align-items: center; gap: 12px;">
            <n-checkbox :disabled="!meta?.fund_config?.trade_future" v-model:checked="showFutCalib" size="large"><span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: meta?.fund_config?.trade_future ? 1 : 0.5 }">期货校准估值</span></n-checkbox>
            <n-checkbox :disabled="!meta?.fund_config?.trade_future" v-model:checked="showPureFut" size="large"><span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: meta?.fund_config?.trade_future ? 1 : 0.5 }">纯期货估值</span></n-checkbox>
         </div>
      </div>

      <!-- 统一参数区: T-2 基准日 + T-1 估值日 + 实时数据（三行同一底色，紧凑排列） -->
      <n-card :bordered="false" class="shadow-soft" style="margin-bottom: 8px; background: #fffbeb; border: 1px solid #fef08a; padding: 0;" :content-style="{padding: '8px 16px'}">
         <div style="display: flex; flex-direction: column; gap: 2px;">
            <!-- 第1行: T-2 基准日 -->
            <div class="base-info-row" style="display: flex; gap: 12px; font-size: 13px; color: #475569; align-items: center; font-weight: 500;">
               <div style="width: 160px;"><strong>【T-2 基准日】</strong> {{ meta?.base_data?.date ? meta.base_data.date.substring(5) : '-' }}</div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 140px;">💰 <strong>净值</strong> <span style="color: #1e3a8a; font-weight: bold; font-family: monospace;">{{ Number(meta?.base_data?.nav || 0).toFixed(4) }}</span></div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 110px;">💱 <strong>汇率</strong> <span style="font-family: monospace;">{{ Number(meta?.base_data?.exchange_rate || 0).toFixed(4) }}</span></div>
               <n-divider vertical style="margin: 0;" />
               <div style="flex: 1; display: flex; align-items: center; gap: 4px;">
                  <span>📊 <strong>ETF收盘价</strong></span>
                  <span style="font-family: monospace; color: #0369a1; font-size: 11.5px; letter-spacing: -0.5px;">{{ baseEtfsText.replace(/:/g, '') }}</span>
               </div>
               <template v-if="meta?.fund_config?.trade_future">
                  <n-divider vertical style="margin: 0;" />
                  <div style="width: 160px;">📊 <strong>{{ meta?.fund_config?.trade_future }}结算价</strong> <span style="font-family: monospace; color: #d97706;">{{ meta?.base_data?.calibration ? Number(meta?.base_data?.calibration).toFixed(2) : '-' }}</span></div>
               </template>
            </div>
            
            <!-- 第2行: T-1 估值日 -->
            <div v-if="meta?.t1_data && meta?.t1_data?.date" class="base-info-row" style="display: flex; gap: 12px; font-size: 13px; color: #1e293b; align-items: center; font-weight: 500; border-top: 1px dashed #e2e8f0; padding-top: 4px; margin-top: 4px;">
               <div style="width: 160px;"><strong>【T-1 估值日】</strong> {{ meta?.t1_data?.date ? meta.t1_data.date.substring(5) : '-' }}</div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 140px;">💰 <strong>估值</strong> <span style="color: #1565c0; font-weight: bold; font-family: monospace;">{{ Number(meta?.t1_data?.static_val || 0).toFixed(4) }}</span></div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 110px;">💱 <strong>汇率</strong> <span style="font-family: monospace;">{{ Number(meta?.t1_data?.exchange_rate || 0).toFixed(4) }}</span></div>
               <n-divider vertical style="margin: 0;" />
               <div style="flex: 1; display: flex; align-items: center; gap: 4px;">
                  <span>📊 <strong>ETF收盘价</strong></span>
                  <span v-if="meta?.t1_data?.etfs_info">
                     <span v-for="(info, idx) in meta.t1_data.etfs_info" :key="info.symbol">
                        <span style="font-family: monospace; color: #0f766e; font-size: 11.5px; letter-spacing: -0.5px;">{{ info.symbol }} {{ info.price.toFixed(2) }} </span>
                        <span :style="{ color: info.pct_change > 0 ? '#d32f2f' : '#388e3c', fontFamily: 'monospace', fontWeight: 'bold', fontSize: '11px', letterSpacing: '-0.5px' }">
                           ({{ info.pct_change > 0 ? '+' : '' }}{{ info.pct_change.toFixed(2) }}%)
                        </span>
                        <span v-if="idx < meta.t1_data.etfs_info.length - 1" style="color: #999; margin: 0 2px;">|</span>
                     </span>
                  </span>
                  <span v-else style="font-family: monospace; color: #0f766e; font-size: 11.5px; letter-spacing: -0.5px;">{{ (meta?.t1_data?.etfs_text || '-').replace(/:/g, '') }}</span>
               </div>
               <template v-if="meta?.fund_config?.trade_future">
                  <n-divider vertical style="margin: 0;" />
                  <div style="width: 160px;">📊 <strong>{{ meta?.fund_config?.trade_future }}结算价</strong> <span style="font-family: monospace; color: #b45309;">{{ meta?.t1_data?.calibration ? Number(meta?.t1_data?.calibration).toFixed(2) : '-' }}</span></div>
               </template>
            </div>

            <!-- 第3行: 实时数据（字段顺序与前两行一致：LOF价格 → 汇率 → ETF实时价） -->
            <div class="base-info-row" style="display: flex; gap: 12px; font-size: 13px; color: #0f172a; align-items: center; font-weight: 500; border-top: 1px dashed #e2e8f0; padding-top: 4px; margin-top: 4px;">
               <div style="width: 160px;">📍 <strong>【实时数据】</strong></div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 140px; display: flex; align-items: center; gap: 0;">
                  <strong style="color:#d32f2f; width: 60px; display: inline-block;">LOF价</strong>
                  <input 
                     type="number" 
                     v-model.number="simLofPrice" 
                     step="0.001" 
                     style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; color:#d32f2f; font-weight:bold; text-align:center;"
                  >
               </div>
               <n-divider vertical style="margin: 0;" />
               <div style="width: 110px;">💱 <strong style="color:#1976d2;">汇率</strong> <span style="font-size: 14px; font-weight: bold; color: #1976d2; font-family: monospace;">{{ Number(latestExchangeRateInput).toFixed(4) }}</span></div>
               <n-divider vertical style="margin: 0;" />
               <div style="flex: 1; display: flex; align-items: center; gap: 4px;">
                  <strong style="color: #64748b;">标的实时价</strong>
                  <span style="font-family: monospace; font-weight: bold; color: #d97706; font-size: 11.5px; letter-spacing: -0.5px;">{{ realtimeEtfsText.replace(/:/g, '') }}</span>
               </div>
            </div>
         </div>
      </n-card>

      <!-- 第三行: 估值与对冲数量推演区 -->
      <div style="display: flex; flex-direction: column; gap: 8px; width: 100%; margin-bottom: 8px;">
         <!-- Panel 1: ETF实时估值 + 对冲数量（合并） -->
         <div style="background: #f0f8ff; padding: 8px 14px; border-radius: 8px; border: 1px solid #bae6fd; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%;">
               <!-- 左侧 -->
               <div style="flex: 1; display: flex; align-items: center; flex-wrap: wrap;">
                  <span style="font-size:15px; font-weight:bold; color:#0284c7; width: 185px;">ETF实时估值</span>
                  <div v-for="(item, index) in uniqueValuationSymbols" :key="item.symbol" style="display: flex; align-items: center;">
                     <span v-if="index === 0" style="color:#1565c0; font-size:14px; font-weight:bold; width: 60px; text-align: right; padding-right: 6px;">{{ item.symbol }}:</span>
                     <span v-else style="color:#1565c0; font-size:14px; font-weight:bold; padding-right: 6px; padding-left: 12px;">{{ item.symbol }}:</span>
                     <input type="number" v-model.number="testEtfPrices[item.symbol]" step="0.01" style="width: 65px; padding: 2px 4px; font-size: 13px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; color:#1565c0; font-weight:bold; text-align:center;" :data-sym="item.symbol">
                  </div>
               </div>
               
               <n-divider vertical style="margin: 0;" />
               
               <!-- 中间 估值 & 溢价 -->
               <div style="width: 220px; display: flex; align-items: center; gap: 6px; justify-content: center;">
                  <span style="color:#555; font-size:14px; font-weight:bold;">估值:</span>
                  <span style="font-size: 18px; font-weight: bold; color: #1565c0; font-family: monospace; width: 65px; text-align: left;">{{ etfVal > 0 ? etfVal.toFixed(4) : '-' }}</span>
                  <span style="color:#555; font-size:14px; font-weight:bold;">溢价:</span>
                  <span :style="{ fontSize: '16px', fontWeight: 'bold', color: derivedEtfPremium > 0 ? '#d32f2f' : '#388e3c', fontFamily: 'monospace', width: '60px', textAlign: 'left' }">
                     {{ etfVal > 0 && simLofPrice > 0 ? (derivedEtfPremium > 0 ? '+' : '') + derivedEtfPremium.toFixed(2) + '%' : '-' }}
                  </span>
               </div>
               
               <n-divider vertical style="margin: 0;" v-if="isComplexCategory" />
               
               <!-- 右侧 交易 -->
               <div v-if="isComplexCategory" style="flex: 1.2; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
                  <span style="font-size:13px; color:#333;">投入</span>
                  <input type="number" v-model.number="targetCapitalEtf" step="1000" style="width: 65px; padding: 2px 4px; font-size: 13px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                  <span style="font-size:13px; color:#333;">元 买入LOF</span>
                  <span style="font-size: 15px; color: #d32f2f; font-weight:bold; font-family: monospace;">{{ lofQtyEtf ? lofQtyEtf.lofQty : '-' }}</span>
                  <span style="font-size:13px; color:#333;">股，做空 {{ meta?.fund_config?.trade_etf }}</span>
                  <span style="font-size: 15px; color: #1565c0; font-weight:bold; font-family: monospace;">{{ lofQtyEtf ? lofQtyEtf.etfQty : '-' }}</span>
                  <span style="font-size:13px; color:#333;">股</span>
               </div>
            </div>
            <div v-if="isComplexCategory" style="display: flex; justify-content: center; gap: 24px; font-size:11px; color:#888; margin-top: 3px;">
               <span>对冲值: <span style="color:#1565c0; font-family: monospace;">{{ (meta?.base_data?.hedge || 0).toFixed(4) }}</span></span>
               <span>敞口: <span style="color:#e65100; font-family: monospace;">{{ lofQtyEtf ? lofQtyEtf.exposure.toFixed(2) : '-' }}元</span></span>
               <span>锚点ETF: {{ lofQtyEtf ? lofQtyEtf.etfQty : '-' }}</span>
            </div>
            <!-- 一篮子详细拆解 -->
            <div v-if="lofQtyEtf && lofQtyEtf.breakdown && lofQtyEtf.breakdown.length > 1" style="display: flex; justify-content: center; font-size: 11px; color: #1565c0; margin-top: 2px;">
              <span>一篮子拆解: 
                <span v-for="(item, idx) in lofQtyEtf.breakdown" :key="item.symbol" style="font-family: monospace; font-weight: bold;">
                  {{ item.symbol }}={{ item.qty }}股<span v-if="idx < lofQtyEtf.breakdown.length - 1">, </span>
                </span>
              </span>
            </div>
         </div>

         <!-- Panel 2: 期货校准估值 + 对冲数量（合并） -->
         <div v-if="showFutCalib && isComplexCategory" style="background: #fffaf0; padding: 8px 14px; border-radius: 8px; border: 1px solid #fed7aa; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%;">
               <!-- 左侧 -->
               <div style="flex: 1; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                  <span style="font-size:15px; font-weight:bold; color:#c2410c; width: 95px;">期货校准估值</span>
                  <span style="color:#e65100; font-size:14px; font-weight:bold;">{{ meta?.fund_config?.trade_future }}:</span>
                  <input type="number" v-model.number="testFutPrice" step="0.01" style="width: 75px; padding: 3px; font-size: 14px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; color:#e65100; font-weight:bold; text-align:center;">
                  <span style="color:#555; font-size:13px; font-weight:bold; margin-left:4px;">校准:</span>
                  <input type="number" v-model.number="testFutCalib" step="0.0001" style="width: 60px; padding: 3px; font-size: 13px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; text-align:center;">
               </div>
               
               <n-divider vertical style="margin: 0;" />
               
               <!-- 中间 估值 & 溢价 -->
               <div style="width: 220px; display: flex; align-items: center; gap: 6px; justify-content: center;">
                  <span style="color:#555; font-size:14px; font-weight:bold;">估值:</span>
                  <span style="font-size: 18px; font-weight: bold; color: #e65100; font-family: monospace; width: 65px; text-align: left;">{{ futCalibVal > 0 ? futCalibVal.toFixed(4) : '-' }}</span>
                  <span style="color:#555; font-size:14px; font-weight:bold;">溢价:</span>
                  <span :style="{ fontSize: '16px', fontWeight: 'bold', color: derivedFutPremium > 0 ? '#d32f2f' : '#388e3c', fontFamily: 'monospace', width: '60px', textAlign: 'left' }">
                     {{ futCalibVal > 0 && simLofPrice > 0 ? (derivedFutPremium > 0 ? '+' : '') + derivedFutPremium.toFixed(2) + '%' : '-' }}
                  </span>
               </div>
               
               <n-divider vertical style="margin: 0;" />
               
               <!-- 右侧 交易 -->
               <div style="flex: 1.2; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
                  <span style="font-size:13px; color:#333;">交易</span>
                  <input type="number" v-model.number="targetLotsFuture" step="1" style="width: 65px; padding: 2px 4px; font-size: 13px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                  <span style="font-size:13px; color:#333;">手期货 → 对应LOF</span>
                  <span style="font-size: 15px; color: #d32f2f; font-weight:bold; font-family: monospace;">{{ lofQtyFuture ? lofQtyFuture.lofQty : '-' }}</span>
                  <span style="font-size:13px; color:#333;">股</span>
               </div>
            </div>
            <div style="display: flex; justify-content: center; gap: 24px; font-size:11px; color:#888; margin-top: 3px;">
               <span>对冲值: <span style="color:#c2410c; font-family: monospace;">{{ lofQtyFuture ? lofQtyFuture.hedgeValue.toFixed(4) : '-' }}</span></span>
               <span>敞口: <span style="color:#e65100; font-family: monospace;">{{ lofQtyFuture ? lofQtyFuture.exposure.toFixed(2) : '-' }}元</span></span>
               <span>校准ETF: <span style="color:#e65100; font-family: monospace;">{{ equivEtfPrice > 0 ? equivEtfPrice.toFixed(3) : '-' }}</span></span>
            </div>
         </div>

         <!-- Panel 3: 纯期货估值 + 对冲数量（合并） -->
         <div v-if="showPureFut && isComplexCategory" style="background: #f2fbf5; padding: 8px 14px; border-radius: 8px; border: 1px solid #bbf7d0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%;">
               <!-- 左侧 -->
               <div style="flex: 1; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                  <span style="font-size:15px; font-weight:bold; color:#15803d; width: 95px;">纯期货估值</span>
                  <span style="color:#15803d; font-size:14px; font-weight:bold;">{{ meta?.fund_config?.trade_future }}:</span>
                  <input type="number" v-model.number="testFutPrice" step="0.01" style="width: 75px; padding: 3px; font-size: 14px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; color:#15803d; font-weight:bold; text-align:center;">
               </div>
               
               <n-divider vertical style="margin: 0;" />
               
               <!-- 中间 估值 & 溢价 -->
               <div style="width: 220px; display: flex; align-items: center; gap: 6px; justify-content: center;">
                  <span style="color:#555; font-size:14px; font-weight:bold;">估值:</span>
                  <span style="font-size: 18px; font-weight: bold; color: #2e7d32; font-family: monospace; width: 65px; text-align: left;">{{ pureFutVal > 0 ? pureFutVal.toFixed(4) : '-' }}</span>
                  <span style="color:#555; font-size:14px; font-weight:bold;">溢价:</span>
                  <span :style="{ fontSize: '16px', fontWeight: 'bold', color: derivedPureFutPremium > 0 ? '#d32f2f' : '#388e3c', fontFamily: 'monospace', width: '60px', textAlign: 'left' }">
                     {{ pureFutVal > 0 && simLofPrice > 0 ? (derivedPureFutPremium > 0 ? '+' : '') + derivedPureFutPremium.toFixed(2) + '%' : '-' }}
                  </span>
               </div>
               
               <n-divider vertical style="margin: 0;" />
               
               <!-- 右侧 交易 -->
               <div style="flex: 1.2; display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
                  <span style="font-size:13px; color:#333;">交易</span>
                  <input type="number" v-model.number="targetLotsPureFuture" step="1" style="width: 65px; padding: 2px 4px; font-size: 13px; font-family:monospace; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                  <span style="font-size:13px; color:#333;">手期货 → 对应LOF</span>
                  <span style="font-size: 15px; color: #d32f2f; font-weight:bold; font-family: monospace;">{{ lofQtyPureFuture ? lofQtyPureFuture.lofQty : '-' }}</span>
                  <span style="font-size:13px; color:#333;">股</span>
               </div>
            </div>
            <div style="display: flex; justify-content: center; gap: 24px; font-size:11px; color:#888; margin-top: 3px;">
               <span>对冲值: <span style="color:#15803d; font-family: monospace;">{{ lofQtyPureFuture ? lofQtyPureFuture.hedgeValue.toFixed(4) : '-' }}</span></span>
               <span>敞口: <span style="color:#e65100; font-family: monospace;">{{ lofQtyPureFuture ? lofQtyPureFuture.exposure.toFixed(2) : '-' }}元</span></span>
            </div>
         </div>
      </div>

      <!-- 第五行: 买卖五档的行情表 (并排显示) -->
      <div class="depth-tables-container" v-if="isComplexCategory">
         <!-- A股 LOF 盘口 (QMT/TDX) -->
         <n-card title="A股 LOF 盘口" :bordered="false" class="depth-table-card-left shadow-soft" size="small">
            <template #header-extra>
               <n-tag size="tiny" :type="depth.source ? 'info' : 'default'">{{ localDepthSource }}</n-tag>
            </template>
            <div class="market-depth">
               <div class="depth-list asks">
                  <div v-for="i in [4,3,2,1,0]" :key="'ask'+i" class="depth-row clickable" @click="simLofPrice = depth.ask[i] || simLofPrice" style="cursor: pointer;">
                     <span class="label" style="color: #666;">卖 {{ i+1 }}</span>
                     <span class="price text-red" style="font-family: monospace;">{{ depth.ask[i]?.toFixed(3) || '-' }}</span>
                     <span class="vol" style="font-family: monospace;">{{ depth.ask_vol[i] || '-' }}</span>
                  </div>
               </div>
               <n-divider style="margin: 6px 0" />
               <div class="depth-list bids">
                  <div v-for="i in [0,1,2,3,4]" :key="'bid'+i" class="depth-row clickable" @click="simLofPrice = depth.bid[i] || simLofPrice" style="cursor: pointer;">
                     <span class="label" style="color: #666;">买 {{ i+1 }}</span>
                     <span class="price text-green" style="font-family: monospace;">{{ depth.bid[i]?.toFixed(3) || '-' }}</span>
                     <span class="vol" style="font-family: monospace;">{{ depth.bid_vol[i] || '-' }}</span>
                  </div>
               </div>
            </div>
         </n-card>

         <!-- 中间：下单执行面板与操作按键 -->
         <n-card title="交易执行面板" :bordered="false" class="chart-card-middle sandbox-card shadow-soft" size="small" style="background: #fffdf5; border: 1px solid #ffcc80;">
            <div class="sandbox-layout" style="display: flex; flex-direction: column; gap: 8px;">
               <!-- 下单区-1: A股 LOF -->
               <div style="width: 100%; display: flex; align-items: center; gap: 6px; background: #fff5f5; padding: 6px 10px; border-radius: 6px; border: 1px solid #ffcdd2; flex-wrap: wrap; box-sizing: border-box;">
                  <n-select v-model:value="lofBroker" size="small" style="width: 100px;" :options="[ { label: '银河QMT', value: 'yinhe_qmt' }, { label: '通达信', value: 'tdx' } ]" />
                  <span style="font-weight:bold; color:#d32f2f; font-size:13px;">{{ fundName }} ({{ fundCode }}):</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number v-model:value="orderVol" :step="100" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number v-model:value="simLofPrice" :step="0.001" size="small" style="width: 100px;" :show-button="false" />
               </div>

               <!-- 下单区-2: IB ETF -->
               <div style="width: 100%; display: flex; align-items: center; gap: 6px; background: #e3f2fd; padding: 6px 10px; border-radius: 6px; border: 1px solid #bbdefb; flex-wrap: wrap; box-sizing: border-box;">
                  <span style="font-weight:bold; color:#1565c0; font-size:13px;">🌍 IB {{ meta?.fund_config?.trade_etf }}:</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number v-model:value="hedgeVol" :step="10" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number v-model:value="hedgePrice" :step="0.01" size="small" style="width: 100px;" :show-button="false" />
               </div>

               <!-- 下单区-3: IB 期货 -->
               <div v-if="showFutCalib || showPureFut" style="width: 100%; display: flex; align-items: center; gap: 6px; background: #fff3e0; padding: 6px 10px; border-radius: 6px; border: 1px solid #ffcc80; flex-wrap: wrap; box-sizing: border-box;">
                  <span style="font-weight:bold; color:#e65100; font-size:13px;">🌍 IB期货 ({{ meta?.fund_config?.trade_future }}):</span>
                  <div style="flex: 1; min-width: 5px;"></div>
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">数量:</span>
                  <n-input-number v-model:value="targetLotsFuture" :step="1" size="small" style="width: 110px;" :show-button="false" />
                  <span style="color:#666; font-size: 12px; white-space: nowrap;">限价:</span>
                  <n-input-number v-model:value="testFutPrice" :step="0.01" size="small" style="width: 100px;" :show-button="false" />
               </div>
            </div>

            <!-- 下单按键区 -->
            <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; margin-top: 12px; border-top: 1px dashed #fed7aa; padding-top: 12px;">
               <!-- 第一行：买入/开仓按键 -->
               <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                  <n-button type="success" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'lof')">{{ fundCode }} 折价买入</n-button>
                  <n-button type="warning" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'ib')">IB {{ meta?.fund_config?.trade_etf }} 卖空</n-button>
                  <n-button v-if="showFutCalib || showPureFut" type="warning" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'ib_future')">{{ meta?.fund_config?.trade_future }} 期货卖空</n-button>
               </div>
               <!-- 第二行：卖出/平仓按键 -->
               <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                  <n-button type="error" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('SELL', 'lof')">{{ fundCode }} 溢价卖出</n-button>
                  <n-button type="info" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'ib')">IB {{ meta?.fund_config?.trade_etf }} 买平</n-button>
                  <n-button v-if="showFutCalib || showPureFut" type="info" style="flex: 1; min-width: 110px; font-weight:bold;" @click="sendOrder('BUY', 'ib_future')">{{ meta?.fund_config?.trade_future }} 期货买平</n-button>
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
               <n-tag size="tiny" :type="foreignSource.includes('等待') ? 'default' : 'success'">{{ foreignSource }}</n-tag>
            </template>
            <div style="padding: 10px; display: flex; flex-direction: column; gap: 8px;">
               <!-- ETF 实时价格 (USO, GLD, etc.) -->
               <div v-for="item in uniqueValuationSymbols" :key="item.symbol" 
                    style="background: #f0f7ff; padding: 6px 10px; border-radius: 6px; border: 1px solid #bae6fd; display: flex; flex-direction: column; gap: 4px;">
                  <div style="font-weight: bold; color: #0369a1; font-size: 12px; display: flex; justify-content: space-between; align-items: center;">
                     <span>📊 {{ item.symbol }} 实时盘口</span>
                     <span style="font-size: 10px; color: #64748b; font-weight: normal;">({{ item.currency }})</span>
                  </div>
                  <div style="display: flex; justify-content: space-between; font-size: 12px;">
                     <span style="color:#2e7d32; font-weight:bold; cursor:pointer;" @click="hedgePrice = meta?.realtime_quotes?.[item.symbol]?.bid || hedgePrice" title="点击填入买一价">
                        买一: <span style="font-family: monospace;">{{ meta?.realtime_quotes?.[item.symbol]?.bid?.toFixed(2) || '等待数据' }}</span>
                     </span>
                     <span style="color:#d32f2f; font-weight:bold; cursor:pointer;" @click="hedgePrice = meta?.realtime_quotes?.[item.symbol]?.ask || hedgePrice" title="点击填入卖一价">
                        卖一: <span style="font-family: monospace;">{{ meta?.realtime_quotes?.[item.symbol]?.ask?.toFixed(2) || '等待数据' }}</span>
                     </span>
                  </div>
               </div>

               <!-- 期货实时价格 (CL, GC, etc.) -->
               <div v-if="meta?.fund_config?.trade_future" 
                    style="background: #fff3e0; padding: 6px 10px; border-radius: 6px; border: 1px solid #fef08a; display: flex; flex-direction: column; gap: 4px;">
                  <div style="font-weight: bold; color: #d97706; font-size: 12px;">📊 {{ meta?.fund_config?.trade_future }} 实时盘口:</div>
                  <div style="display: flex; justify-content: space-between; font-size: 12px;">
                     <span style="color:#2e7d32; font-weight:bold; cursor:pointer;" @click="testFutPrice = (typeof meta?.future_quote === 'object' ? meta?.future_quote?.bid : meta?.future_quote) || testFutPrice" title="点击填入买一价">
                        买一: <span style="font-family: monospace;">{{ (typeof meta?.future_quote === 'object' ? meta?.future_quote?.bid?.toFixed(2) : meta?.future_quote?.toFixed(2)) || '等待数据' }}</span>
                     </span>
                     <span style="color:#d32f2f; font-weight:bold; cursor:pointer;" @click="testFutPrice = (typeof meta?.future_quote === 'object' ? meta?.future_quote?.ask : meta?.future_quote) || testFutPrice" title="点击填入卖一价">
                        卖一: <span style="font-family: monospace;">{{ (typeof meta?.future_quote === 'object' ? meta?.future_quote?.ask?.toFixed(2) : meta?.future_quote?.toFixed(2)) || '等待数据' }}</span>
                     </span>
                  </div>
               </div>
            </div>
         </n-card>
      </div>

      <!-- 第六行: 分时曲线图 (从中间移到下方) -->
      <n-card title="分时对冲走势 (1分钟采样)" :bordered="false" class="shadow-soft" style="margin-top: 12px;" size="small">
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
import { ref, onMounted, computed, reactive, watch, h, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NSpace, NButton,
  NText, NDataTable, NTag, NDatePicker, NIcon, NInputNumber, useMessage, NCheckbox, NDivider, NSelect
} from 'naive-ui'
import { RefreshCw, Zap, ArrowLeft, Star, StarOff } from 'lucide-vue-next'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import axios from 'axios'

use([CanvasRenderer, LineChart, BarChart, TitleComponent, TooltipComponent, GridComponent, LegendComponent, DataZoomComponent, VisualMapComponent])

const route = useRoute()
const router = useRouter()
const message = useMessage()

// 基础状态
const fundCode = ref((route.query.code as string) || '')
const fundName = ref((route.query.name as string) || '')
const opportunityData = ref<any[]>([])
const intradayData = ref<any[]>([])
const basketData = ref<any[]>([])
const loading = ref(false)
const selectedDate = ref(Date.now())
const showFutCalib = ref(false)
const showPureFut = ref(false)

// 雷达筛选相关
const selectedCategories = ref<string[]>([])
const premiumThreshold = ref(-0.5)
const premiumUpperThreshold = ref(2.0)
const showWatchlistOnly = ref(true) // 我的自选Tab（默认选中）
const watchlist = ref<string[]>(JSON.parse(localStorage.getItem('watchlist') || '[]')) // 自选基金列表

// 分类映射：前端显示名称 → 数据库category值
const categoryMap: Record<string, string[]> = {
  'gold_oil': ['黄金原油'],
  'qdii_us': ['纯ETF', 'QDII欧美', '混合跨境', '指数'],
  'qdii_asia': ['QDII 亚洲', 'QDII亚洲'],
  'domestic_lof': ['指数LOF', '其他', '国内LOF'],
  'silver': ['白银']
}

// 是否为复杂业务分类（黄金原油、纯ETF、QDII欧美、混合跨境）
// 对于亚洲、国内LOF、白银等，隐藏盘口对冲和下单组件
const isComplexCategory = computed(() => {
  const cat = meta.value?.fund_config?.category || ''
  const simpleCategories = ['QDII 亚洲', 'QDII亚洲', '国内LOF', '指数LOF', '白银', '其他']
  return !simpleCategories.includes(cat)
})

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
  fetchDashboard() // 筛选条件变化时重新刷新数据
}, { deep: true })

// 摘要与盘口数据
const navDate = ref('-')
const calibrationValue = ref('-')
const t2Nav = ref(0)
const t1StaticVal = ref(0)
const depth = reactive({ ask: [0,0,0,0,0], ask_vol: [0,0,0,0,0], bid: [0,0,0,0,0], bid_vol: [0,0,0,0,0], source: '', price: 0 })
const isLofPriceInitialized = ref(false)
const isHedgePriceInitialized = ref(false)

// 实时估值计算器新增反应状态
const meta = ref<any>(null)
const lofBroker = ref('yinhe_qmt')
const latestExchangeRateInput = ref(7.0)
const testEtfPrices = reactive<Record<string, number>>({})
const testFutPrice = ref(0)
const testFutCalib = ref(1.0)
const targetCapitalEtf = ref(100000)
const targetLotsFuture = ref(1)
const targetLotsPureFuture = ref(1)

// 沙盘执行状态
const simLofPrice = ref(0)
const simEtfPrice = ref(0)
const orderVol = ref(2000)
const hedgeVol = ref(10)
const hedgePrice = ref(0)
const autoLog = ref(true)

let realtimeTimer: any = null

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

const uniqueValuationSymbols = computed(() => {
  if (!meta.value?.fund_config?.valuation_portfolio) return []
  const seen = new Set()
  const result: any[] = []
  for (const item of meta.value.fund_config.valuation_portfolio) {
    if (!item.symbol) continue
    const baseSym = item.symbol.replace(/^\^/, '').split('-')[0].toUpperCase()
    if (!seen.has(baseSym)) {
      seen.add(baseSym)
      result.push({
        symbol: baseSym,
        currency: item.currency || 'USD'
      })
    }
  }
  return result
})

const positionRatio = computed(() => {
  if (!meta.value) return 0.95
  const bd = meta.value.base_data || {}
  const cfg = meta.value.fund_config || {}
  
  // 1. 优先尝试从数据库基准数据 bd.position 中读取（数据库中存的是小数，如 0.8823）
  if (bd.position !== undefined && bd.position !== null && !isNaN(parseFloat(bd.position))) {
    return parseFloat(bd.position)
  }
  // 2. 次选从配置文件 cfg.position 中读取（配置里是百分比，如 88.23，需要除以 100）
  if (cfg.position !== undefined && cfg.position !== null && !isNaN(parseFloat(cfg.position))) {
    return parseFloat(cfg.position) / 100.0
  }
  // 3. 兜底为 95%
  return 0.95
})

const baseEtfsText = computed(() => {
  if (!meta.value || !meta.value.base_data || !meta.value.fund_config) return '-'
  const bd = meta.value.base_data
  const cfg = meta.value.fund_config
  const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
  return portfolio.map((item: any) => {
    let sym = item.symbol || ''
    for (const suffix of ['-EU', '-JP', '-HK']) {
      if (sym.endsWith(suffix) && !sym.startsWith('^')) {
        sym = '^' + sym
        break
      }
    }
    const cleanSym = sym.replace(/^\^/, '')
    const caretSym = sym.startsWith('^') ? sym : '^' + sym
    const price = bd[caretSym] !== undefined ? bd[caretSym] : (bd[cleanSym] !== undefined ? bd[cleanSym] : 0)
    return `${sym}: ${Number(price).toFixed(2)} (${Number(item.weight).toFixed(1)}%)`
  }).join(' | ')
})

const rateHeaderName = computed(() => {
  if (!meta.value || !meta.value.fund_config) return '汇率'
  const currency = meta.value.fund_config.valuation_portfolio?.[0]?.currency || 'USD'
  return `${currency}/CNY 汇率`
})

const realtimeEtfsText = computed(() => {
  if (!meta.value || !meta.value.realtime_quotes) return '-'
  return Object.entries(meta.value.realtime_quotes).map(([sym, quoteObj]) => {
    const price = quoteObj && typeof quoteObj === 'object' ? (quoteObj as any).price : quoteObj
    return `${sym}: ${price ? Number(price).toFixed(2) : '-'}`
  }).join(' | ')
})

const foreignSource = computed(() => {
  if (!meta.value) return '等待行情...'
  const quotes = meta.value.realtime_quotes
  if (quotes) {
    for (const key in quotes) {
      if (quotes[key] && quotes[key].source) {
        return quotes[key].source
      }
    }
  }
  if (meta.value.future_quote && meta.value.future_quote.source) {
    return meta.value.future_quote.source
  }
  return '未连接 IB/富途'
})

const localDepthSource = computed(() => {
  if (!depth.source) return '等待行情...'
  const s = depth.source.toLowerCase()
  if (s.includes('tongdaxin') || s.includes('tdx')) return '通达信'
  if (s.includes('yinhe')) return '银河QMT'
  if (s.includes('guojin') || s.includes('gj')) return '国金QMT'
  if (s.includes('sina')) return '新浪'
  if (s.includes('tencent')) return '腾讯'
  return depth.source
})

// ETF实时估值动态计算
const etfVal = computed(() => {
  if (!meta.value || !meta.value.base_data) return 0
  const bd = meta.value.base_data
  const cfg = meta.value.fund_config
  
  const baseNav = parseFloat(bd.nav) || 0
  const pos = positionRatio.value
  const currentFx = parseFloat(latestExchangeRateInput.value as any) || 0
  const baseFx = parseFloat(bd.exchange_rate) || 0
  
  if (baseNav <= 0 || currentFx <= 0) return 0
  
  const bHedge = parseFloat(bd.hedge) || 0
  const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
  
  if (bHedge > 0 && portfolio.length === 1) {
    const p = portfolio[0]
    const sym = p.symbol || ''
    const cleanSym = sym.replace(/^\^/, '').split('-')[0].toUpperCase()
    const cPrice = parseFloat(testEtfPrices[cleanSym] as any) || 0
    if (cPrice > 0) {
      return baseNav * (1.0 - pos) + (cPrice * currentFx) / bHedge
    }
  }
  
  if (portfolio.length > 0) {
    const fxChange = currentFx / (baseFx || 1.0)
    let wChange = 0.0
    let validW = 0.0
    
    for (const p of portfolio) {
      const fullSym = p.symbol || ''
      const cleanSymKey = fullSym.replace(/^\^/, '')
      const caretSymKey = '^' + cleanSymKey
      const bPrice = parseFloat(bd[caretSymKey] !== undefined ? bd[caretSymKey] : (bd[cleanSymKey] !== undefined ? bd[cleanSymKey] : (bd[fullSym] || 0))) || 0
      const cleanSym = fullSym.replace(/^\^/, '').split('-')[0].toUpperCase()
      const cPrice = parseFloat(testEtfPrices[cleanSym] as any) || 0
      const weight = (parseFloat(p.weight) || 0) / 100.0
      
      if (cPrice > 0 && bPrice > 0 && weight > 0) {
        wChange += (cPrice / bPrice) * weight
        validW += weight
      }
    }
    
    if (validW > 0) {
      if (Math.abs(validW - 1.0) > 0.001) {
        wChange = wChange / validW
      }
      const netRatio = pos * (wChange * fxChange - 1.0)
      return baseNav * (1.0 + netRatio)
    }
  }
  
  return 0
})

// 期货校准实时估值动态计算
const futCalibVal = computed(() => {
  if (!meta.value || !meta.value.base_data) return 0
  const bd = meta.value.base_data
  const cfg = meta.value.fund_config
  
  const baseNav = parseFloat(bd.nav) || 0
  const pos = positionRatio.value
  const todayExchangeRate = parseFloat(latestExchangeRateInput.value as any) || 0
  const baseExchangeRate = parseFloat(bd.exchange_rate) || 0
  
  const futPrice = parseFloat(testFutPrice.value as any) || 0
  const calib = parseFloat(testFutCalib.value as any) || 0
  
  if (baseNav <= 0 || todayExchangeRate <= 0 || futPrice <= 0 || calib <= 0) return 0
  
  const equivSpot = futPrice / calib
  const category = cfg.category || ''
  const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
  
  if (category === '指数') {
    let equivEtf = 0
    const mainAnchorSymbol = portfolio[0]?.symbol || ''
    const cleanMainSym = mainAnchorSymbol.replace(/^\^/, '')
    const caretMainSym = '^' + cleanMainSym
    const baseEtfPrice = parseFloat(bd[caretMainSym] !== undefined ? bd[caretMainSym] : (bd[cleanMainSym] !== undefined ? bd[cleanMainSym] : (bd[mainAnchorSymbol] || 0))) || 0
    const baseIndexPrice = parseFloat(bd.index_close) || 0
    
    if (baseIndexPrice > 0 && baseEtfPrice > 0) {
      equivEtf = equivSpot * (baseEtfPrice / baseIndexPrice)
    } else if (parseFloat(bd.calibration) > 0 && baseEtfPrice > 0) {
      const derivedBaseIndexPrice = parseFloat(bd.calibration) / calib
      equivEtf = equivSpot * (baseEtfPrice / derivedBaseIndexPrice)
    }
    
    const hedgeValue = parseFloat(bd.hedge) || 0
    const etfCalibration = (hedgeValue > 0 && pos > 0) ? hedgeValue * pos : 0
    
    if (etfCalibration > 0 && equivEtf > 0) {
      return baseNav * (1.0 - pos) + (pos / etfCalibration) * (equivEtf * todayExchangeRate)
    } else {
      if (baseIndexPrice > 0) {
        const spotChangeRate = equivSpot / baseIndexPrice
        const exchangeRateChange = todayExchangeRate / baseExchangeRate
        return baseNav * (1 + pos * (spotChangeRate * exchangeRateChange - 1))
      }
    }
  } else {
    let weightedFuturesChangeRate = 0.0
    let totalValidWeight = 0.0
    const validEtfs: any[] = []
    
    for (const item of portfolio) {
      if (item.weight <= 0 || item.weight < 0.02 || item.symbol.includes('SLV')) {
        continue
      }
      validEtfs.push(item)
      totalValidWeight += item.weight
    }
    
    if (totalValidWeight > 0) {
      for (const vItem of validEtfs) {
        const cleanVSym = vItem.symbol.replace(/^\^/, '')
        const caretVSym = '^' + cleanVSym
        const baseEtfPrice = parseFloat(bd[caretVSym] !== undefined ? bd[caretVSym] : (bd[cleanVSym] !== undefined ? bd[cleanVSym] : (bd[vItem.symbol] || 0))) || 0
        if (baseEtfPrice > 0) {
          const etfChangeRate = equivSpot / baseEtfPrice
          const normalizedWeight = vItem.weight / totalValidWeight
          weightedFuturesChangeRate += etfChangeRate * normalizedWeight
        }
      }
      const exchangeRateChange = todayExchangeRate / baseExchangeRate
      return baseNav * (1 + pos * (weightedFuturesChangeRate * exchangeRateChange - 1))
    }
  }
  
  return 0
})

// 纯期货实时估值动态计算
const pureFutVal = computed(() => {
  if (!meta.value || !meta.value.base_data) return 0
  const bd = meta.value.base_data
  
  const baseNav = parseFloat(bd.nav) || 0
  const pos = positionRatio.value
  const todayExchangeRate = parseFloat(latestExchangeRateInput.value as any) || 0
  const baseExchangeRate = parseFloat(bd.exchange_rate) || 0
  
  const futPrice = parseFloat(testFutPrice.value as any) || 0
  const baseFuturePrice = parseFloat(bd.calibration) || 0
  
  if (baseNav <= 0 || todayExchangeRate <= 0 || futPrice <= 0 || baseFuturePrice <= 0 || baseExchangeRate <= 0) return 0
  
  const futureChangeRate = futPrice / baseFuturePrice
  const exchangeRateChange = todayExchangeRate / baseExchangeRate
  return baseNav * (1 + pos * (futureChangeRate * exchangeRateChange - 1))
})

const derivedEtfPremium = computed(() => {
  if (etfVal.value <= 0 || simLofPrice.value <= 0) return 0
  return (simLofPrice.value / etfVal.value - 1) * 100
})

const derivedFutPremium = computed(() => {
  if (futCalibVal.value <= 0 || simLofPrice.value <= 0) return 0
  return (simLofPrice.value / futCalibVal.value - 1) * 100
})

const derivedPureFutPremium = computed(() => {
  if (pureFutVal.value <= 0 || simLofPrice.value <= 0) return 0
  return (simLofPrice.value / pureFutVal.value - 1) * 100
})

const equivEtfPrice = computed(() => {
  const futPrice = parseFloat(testFutPrice.value as any) || 0
  const calib = parseFloat(testFutCalib.value as any) || 0
  if (futPrice > 0 && calib > 0) {
    return futPrice / calib
  }
  return 0
})

// ETF对冲数量计算
const lofQtyEtf = computed(() => {
  if (targetCapitalEtf.value <= 0 || etfVal.value <= 0 || simLofPrice.value <= 0) return null
  const bd = meta.value?.base_data
  if (!bd) return null
  const cfg = meta.value.fund_config
  const pos = positionRatio.value
  
  const etfHedge = parseFloat(bd.hedge) || 0
  if (etfHedge <= 0) return null
  
  let finalEtfQty = 0
  let finalLofQty = 0
  
  if (cfg.category === '纯ETF' || cfg.category === '指数') {
    const tempLofQty = targetCapitalEtf.value / simLofPrice.value
    finalEtfQty = Math.max(1, Math.round(tempLofQty / etfHedge))
    finalLofQty = Math.round((finalEtfQty * etfHedge) / 100) * 100
  } else {
    finalLofQty = Math.round((targetCapitalEtf.value / simLofPrice.value) / 100) * 100
    finalEtfQty = Math.max(1, Math.round(finalLofQty / etfHedge))
  }
  
  // 更加牛逼的一篮子拆解逻辑 (按照权重切分各ETF的数量)
  let portfolioBreakdown = []
  const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
  if (portfolio.length > 1) {
    // 实际建仓的 LOF 对应的目标 RMB 敞口
    const targetExposureRMB = finalLofQty * simLofPrice.value * pos
    const currentFx = parseFloat(latestExchangeRateInput.value) || 0
    if (currentFx > 0) {
      const targetExposureUSD = targetExposureRMB / currentFx
      for (const p of portfolio) {
        const fullSym = p.symbol || ''
        const cleanSym = fullSym.replace(/^\^/, '').split('-')[0].toUpperCase()
        const cPrice = parseFloat(testEtfPrices[cleanSym]) || 0
        const weight = (parseFloat(p.weight) || 0) / 100.0
        if (cPrice > 0 && weight > 0) {
          const qty = (targetExposureUSD * weight) / cPrice
          portfolioBreakdown.push({
            symbol: fullSym,
            qty: qty.toFixed(1)
          })
        }
      }
    }
  }
  
  return { lofQty: finalLofQty, etfQty: finalEtfQty, exposure: targetCapitalEtf.value * pos, breakdown: portfolioBreakdown }
})

// 期货校准对冲数量计算
const lofQtyFuture = computed(() => {
  if (targetLotsFuture.value <= 0 || !meta.value || !meta.value.base_data) return null
  const bd = meta.value.base_data
  const cfg = meta.value.fund_config
  const etfHedge = parseFloat(bd.hedge) || 0
  const calib = parseFloat(testFutCalib.value as any) || 1.0
  
  let multiplier = 1
  const tradeFutureSym = cfg.trade_future || ''
  if (tradeFutureSym.includes('MGC')) multiplier = 10
  else if (tradeFutureSym.includes('GC')) multiplier = 100
  else if (tradeFutureSym.includes('MCL')) multiplier = 100
  else if (tradeFutureSym.includes('CL')) multiplier = 1000
  else if (tradeFutureSym.includes('MNQ')) multiplier = 2
  else if (tradeFutureSym.includes('NQ')) multiplier = 20
  else if (tradeFutureSym.includes('MES')) multiplier = 5
  else if (tradeFutureSym.includes('ES')) multiplier = 50
  else if (tradeFutureSym.toUpperCase().includes('AG')) multiplier = 15
  
  const displayHedgeValue = etfHedge * calib * multiplier
  if (displayHedgeValue <= 0) return null
  
  const finalLofQty = Math.round((targetLotsFuture.value * displayHedgeValue) / 100) * 100
  const pos = positionRatio.value
  const exposure = finalLofQty * simLofPrice.value * pos
  
  return { lofQty: finalLofQty, hedgeValue: displayHedgeValue, exposure }
})

// 纯期货对冲数量计算
const lofQtyPureFuture = computed(() => {
  if (targetLotsPureFuture.value <= 0 || !meta.value || !meta.value.base_data) return null
  const bd = meta.value.base_data
  const cfg = meta.value.fund_config
  const etfHedge = parseFloat(bd.hedge) || 0
  const calib = parseFloat(bd.calibration) || 1.0
  
  let multiplier = 1
  const tradeFutureSym = cfg.trade_future || ''
  if (tradeFutureSym.includes('MGC')) multiplier = 10
  else if (tradeFutureSym.includes('GC')) multiplier = 100
  else if (tradeFutureSym.includes('MCL')) multiplier = 100
  else if (tradeFutureSym.includes('CL')) multiplier = 1000
  else if (tradeFutureSym.includes('MNQ')) multiplier = 2
  else if (tradeFutureSym.includes('NQ')) multiplier = 20
  else if (tradeFutureSym.includes('MES')) multiplier = 5
  else if (tradeFutureSym.includes('ES')) multiplier = 50
  else if (tradeFutureSym.toUpperCase().includes('AG')) multiplier = 15
  
  const displayHedgeValue = etfHedge * calib * multiplier
  if (displayHedgeValue <= 0) return null
  
  const finalLofQty = Math.round((targetLotsPureFuture.value * displayHedgeValue) / 100) * 100
  const pos = positionRatio.value
  const exposure = finalLofQty * simLofPrice.value * pos
  
  return { lofQty: finalLofQty, hedgeValue: displayHedgeValue, exposure }
})

watch(() => lofQtyEtf.value, (newVal) => {
  if (newVal && newVal.lofQty > 0) orderVol.value = newVal.lofQty
  if (newVal && newVal.etfQty > 0) hedgeVol.value = newVal.etfQty
})

watch(() => lofQtyFuture.value, (newVal) => {
  if (newVal && newVal.lofQty > 0) orderVol.value = newVal.lofQty
})

watch(() => route.query.code, (newCode) => {
  fundCode.value = (newCode as string) || ''; fundName.value = (route.query.name as string) || ''
  isLofPriceInitialized.value = false
  simLofPrice.value = 0
  if (fundCode.value) fetchAll(); else fetchDashboard()
})

const formatDate = (ts: number) => {
  const d = new Date(ts); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}

const handleBack = () => { window.location.replace('/') }
const disableFutureDates = (ts: number) => ts > Date.now()
const handleDateChange = () => { fetchIntraday(); fetchValuationMeta(); }

const fetchDashboard = async () => {
  try {
    const res = await axios.get('/api/dashboard')
    let data = res.data.data
    
    // 1. 我的自选筛选（交集关系）
    if (showWatchlistOnly.value && watchlist.value.length > 0) {
      data = data.filter((f: any) => watchlist.value.includes(f.fund_code))
    }
    
    // 2. 分类筛选（不选分类时显示全部）
    if (selectedCategories.value && selectedCategories.value.length > 0) {
      // 收集所有选中的分类对应的数据库category值
      const allowedCategories = new Set<string>()
      for (const catKey of selectedCategories.value) {
        const mappedCats = categoryMap[catKey] || []
        for (const cat of mappedCats) {
          allowedCategories.add(cat)
        }
      }
      data = data.filter((f: any) => allowedCategories.has(f.category))
    }
    
    // 3. 折价率阈值筛选：显示折价率在阈值范围内的基金
    const lower = premiumThreshold.value
    const upper = premiumUpperThreshold.value
    data = data.filter((f: any) => f.rt_premium >= lower && f.rt_premium <= upper)
    
    opportunityData.value = data
  } catch (e) {}
}

const fetchIntraday = async () => {
  if (!fundCode.value) return
  loading.value = true
  try {
    const res = await axios.get(`/api/fund/${fundCode.value}/intraday`, { params: { date: formatDate(selectedDate.value) } })
    intradayData.value = res.data.data || []
    if (intradayData.value.length > 0 && !isLofPriceInitialized.value) {
       simLofPrice.value = currentPrice.value
       isLofPriceInitialized.value = true
    }
    updateStats()
  } finally { loading.value = false }
}

const fetchBasket = async () => {
  if (!fundCode.value) return
  const res = await axios.get(`/api/fund/${fundCode.value}/basket`)
  basketData.value = res.data.data || []
  if (basketData.value.length > 0) {
      simEtfPrice.value = basketData.value[0].price || 0
      hedgePrice.value = basketData.value[0].price || 0
  }
}

const fetchHistoryMeta = async () => {
    try {
        const res = await axios.get(`/api/fund/${fundCode.value}/history`)
        if (res.data.status === 'ok' && res.data.data.length > 0) {
            const latest = res.data.data[0]
            navDate.value = latest.nav_date || '-'; t2Nav.value = latest.nav || 0
            t1StaticVal.value = latest.static_val || 0; calibrationValue.value = latest.calibration || '-'
        }
    } catch (e) {}
}

const fetchRealtimeDepth = async () => {
    if (!fundCode.value) return
    try {
        const res = await axios.get(`/api/market/realtime/${fundCode.value}`)
        if (res.data.status === 'ok') {
            const q = res.data.data
            depth.ask = q.ask || [0,0,0,0,0]; depth.ask_vol = q.ask_vol || [0,0,0,0,0]
            depth.bid = q.bid || [0,0,0,0,0]; depth.bid_vol = q.bid_vol || [0,0,0,0,0]
            depth.source = q.source || ''
            depth.price = q.price || 0
            
            if (!isLofPriceInitialized.value && q.price > 0) {
                simLofPrice.value = q.price
                isLofPriceInitialized.value = true
            }
        }
    } catch (e) {}
}

const fetchValuationMeta = async () => {
  if (!fundCode.value) return
  try {
    const res = await axios.get(`/api/fund/${fundCode.value}/valuation_meta`)
    if (res.data.status === 'ok') {
      meta.value = res.data
      latestExchangeRateInput.value = res.data.latest_exchange_rate || 7.0
      
      for (const [sym, quoteObj] of Object.entries(res.data.realtime_quotes)) {
        const qVal = quoteObj && typeof quoteObj === 'object' ? (quoteObj as any).price : quoteObj
        const inputEl = document.activeElement as HTMLElement
        const isInputFocused = inputEl && inputEl.tagName === 'INPUT' && inputEl.getAttribute('data-sym') === sym
        if (!isInputFocused && qVal) {
          testEtfPrices[sym] = qVal as number
        } else if (!testEtfPrices[sym]) {
          let defaultPrice = parseFloat(res.data.base_data[sym]) || parseFloat(res.data.base_data['^' + sym]) || 0
          if (!defaultPrice && res.data.base_data) {
            const matchedKey = Object.keys(res.data.base_data).find(k => {
              const cleanK = k.replace(/^\^/, '').split('-')[0].toUpperCase()
              return cleanK === sym.toUpperCase()
            })
            if (matchedKey) {
              defaultPrice = parseFloat(res.data.base_data[matchedKey]) || 0
            }
          }
          testEtfPrices[sym] = (qVal || defaultPrice) as number
        }
      }
      
      const tradeEtf = res.data.fund_config?.trade_etf
      if (tradeEtf && res.data.realtime_quotes[tradeEtf]) {
        const qObj = res.data.realtime_quotes[tradeEtf]
        if (qObj && typeof qObj === 'object') {
          if (!isHedgePriceInitialized.value && qObj.bid > 0) {
            hedgePrice.value = qObj.bid
            isHedgePriceInitialized.value = true
          }
        }
      }
      
      const bd = res.data.base_data
      testFutCalib.value = bd.calibration || 1.0
      
      const futInputFocused = document.activeElement && document.activeElement.getAttribute('data-sym') === 'future'
      if (!futInputFocused) {
        const fPrice = res.data.future_quote && typeof res.data.future_quote === 'object' ? res.data.future_quote.price : res.data.future_quote
        testFutPrice.value = fPrice || bd.calibration || 0
      }
      
      if (!isLofPriceInitialized.value) {
        if (depth.price > 0) {
          simLofPrice.value = depth.price
          isLofPriceInitialized.value = true
        } else if (currentPrice.value > 0) {
          simLofPrice.value = currentPrice.value
          isLofPriceInitialized.value = true
        } else if (bd.close > 0) {
          simLofPrice.value = bd.close
          isLofPriceInitialized.value = true
        }
      }
    }
  } catch (e) {
    console.error("Failed to fetch valuation meta:", e)
  }
}

const fetchAll = () => { fetchIntraday(); fetchBasket(); fetchHistoryMeta(); fetchRealtimeDepth(); fetchValuationMeta(); }

const sendOrder = async (action: string, brokerType: 'lof' | 'ib' | 'ib_future') => {
  let p = 0, v = 0, sym = '', broker = ''
  if (brokerType === 'lof') {
    p = simLofPrice.value; v = orderVol.value; sym = fundCode.value; broker = lofBroker.value
  } else if (brokerType === 'ib') {
    p = hedgePrice.value; v = hedgeVol.value; sym = meta.value?.fund_config?.trade_etf?.split(',')?.[0]?.trim() || ''; broker = 'ib'
  } else if (brokerType === 'ib_future') {
    p = testFutPrice.value; v = targetLotsFuture.value; sym = meta.value?.fund_config?.trade_future || ''; broker = 'ib'
  }
  try {
    const res = await axios.post('/api/trading/order', { action, code: sym, volume: v, price: p, broker })
    if (res.data.status === 'ok') {
      message.success(`下单成功: ${res.data.message}`)
      if (autoLog.value) {
        await axios.post('/api/ledger/trades/add', {
          fund_code: fundCode.value, fund_name: fundName.value, action, volume: orderVol.value, price: simLofPrice.value,
          hedge_symbol: sym, hedge_price: p, hedge_vol: v
        })
      }
    } else message.error(`下单失败: ${res.data.message}`)
  } catch (e) { message.error('接口异常') }
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

let pollCount = 0
const pollRealtime = async () => {
  if (!fundCode.value) return
  await fetchRealtimeDepth()
  await fetchValuationMeta()
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
