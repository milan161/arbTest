<template>
  <div>
    <!-- =============================================================
         统一参数区: T-2 基准日 + T-1 估值日 + 实时数据
         ============================================================= -->
    <n-card
      v-if="!calc.isCashManagement.value"
      :bordered="false"
      class="shadow-soft"
      style="margin-bottom: 8px; background: #fffbeb; border: 1px solid #fef08a; padding: 0"
      :content-style="{ padding: '8px 16px' }"
    >
      <div style="display: flex; flex-direction: column; gap: 2px">
        <!-- === 第1行: T-2 基准日 === -->
        <div
          class="base-info-row"
          style="display: flex; gap: 12px; font-size: 13px; color: #475569; align-items: center; font-weight: 500"
        >
          <div style="width: 160px">
            <strong>【T-2 基准日】</strong>
            {{ calc.meta.value?.base_data?.date ? calc.meta.value.base_data.date.substring(5) : '-' }}
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 140px">
            💰 <strong>净值</strong>
            <span style="color: #1e3a8a; font-weight: bold; font-family: monospace">{{
              Number(calc.meta.value?.base_data?.nav || 0).toFixed(4)
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 110px">
            💱 <strong>汇率</strong>
            <span style="font-family: monospace">{{
              Number(calc.meta.value?.base_data?.exchange_rate || 0).toFixed(4)
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="flex: 1; display: flex; align-items: center; gap: 4px">
            <span>📊 <strong>ETF收盘价</strong></span>
            <span
              style="font-family: monospace; color: #0369a1; font-size: 11.5px; letter-spacing: -0.5px"
              >{{ calc.baseEtfsText.value.replace(/:/g, '') }}</span
            >
          </div>
          <template v-if="calc.meta.value?.fund_config?.trade_future">
            <n-divider vertical style="margin: 0" />
            <div style="width: 160px">
              📊 <strong>{{ calc.meta.value?.fund_config?.trade_future }}校准因子</strong>
              <span style="font-family: monospace; color: #d97706">{{
                calc.meta.value?.base_data?.calibration
                  ? Number(calc.meta.value.base_data.calibration).toFixed(3)
                  : '-'
              }}</span>
            </div>
          </template>
        </div>

        <!-- === 第2行: T-1 估值日 === -->
        <div
          v-if="calc.meta.value?.t1_data?.date"
          class="base-info-row"
          style="display: flex; gap: 12px; font-size: 13px; color: #1e293b; align-items: center; font-weight: 500; border-top: 1px dashed #e2e8f0; padding-top: 4px; margin-top: 4px"
        >
          <div style="width: 160px">
            <strong>【T-1 估值日】</strong>
            {{ calc.meta.value.t1_data.date.substring(5) }}
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 140px">
            💰 <strong>估值</strong>
            <span style="color: #1565c0; font-weight: bold; font-family: monospace">{{
              Number(calc.meta.value?.t1_data?.static_val || 0).toFixed(4)
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 110px">
            💱 <strong>汇率</strong>
            <span style="font-family: monospace">{{
              Number(calc.meta.value?.t1_data?.exchange_rate || 0).toFixed(4)
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="flex: 1; display: flex; align-items: center; gap: 4px">
            <span>📊 <strong>ETF收盘价</strong></span>
            <span v-if="calc.meta.value?.t1_data?.etfs_info">
              <span
                v-for="(info, idx) in calc.meta.value.t1_data.etfs_info"
                :key="info.symbol"
              >
                <span
                  style="font-family: monospace; color: #0f766e; font-size: 11.5px; letter-spacing: -0.5px"
                  >{{ info.symbol }} {{ info.price.toFixed(2) }}
                </span>
                <span
                  :style="{
                    color: info.pct_change > 0 ? '#d32f2f' : '#388e3c',
                    fontFamily: 'monospace',
                    fontWeight: 'bold',
                    fontSize: '11px',
                    letterSpacing: '-0.5px',
                  }"
                >
                  ({{ info.pct_change > 0 ? '+' : '' }}{{ info.pct_change.toFixed(2) }}%)
                </span>
                <span v-if="idx < calc.meta.value.t1_data.etfs_info.length - 1" style="color: #999; margin: 0 2px">|</span>
              </span>
            </span>
            <span
              v-else
              style="font-family: monospace; color: #0f766e; font-size: 11.5px; letter-spacing: -0.5px"
              >{{ (calc.meta.value?.t1_data?.etfs_text || '-').replace(/:/g, '') }}</span
            >
          </div>
          <template v-if="calc.meta.value?.fund_config?.trade_future">
            <n-divider vertical style="margin: 0" />
            <div style="width: 160px">
              📊 <strong>{{ calc.meta.value?.fund_config?.trade_future }}校准因子</strong>
              <span style="font-family: monospace; color: #b45309">{{
                calc.meta.value?.t1_data?.calibration
                  ? Number(calc.meta.value.t1_data.calibration).toFixed(3)
                  : '-'
              }}</span>
            </div>
          </template>
        </div>

        <!-- === 第3行: 实时数据 === -->
        <div
          class="base-info-row"
          style="display: flex; gap: 12px; font-size: 13px; color: #0f172a; align-items: center; font-weight: 500; border-top: 1px dashed #e2e8f0; padding-top: 4px; margin-top: 4px"
        >
          <div style="width: 160px">📍 <strong>【实时数据】</strong></div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 140px; display: flex; align-items: center; gap: 0" data-role="lof-price">
            <strong style="color: #d32f2f; width: 60px; display: inline-block">LOF价</strong>
            <input
              type="number"
              :value="calc.simLofPrice.value"
              @input="onSimLofPriceInput"
              step="0.001"
              style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; color: #d32f2f; font-weight: bold; text-align: center"
            />
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="width: 110px">
            💱 <strong style="color: #1976d2">汇率</strong>
            <span style="font-size: 14px; font-weight: bold; color: #1976d2; font-family: monospace">{{
              Number(calc.latestExchangeRateInput.value).toFixed(4)
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="flex: 1; display: flex; align-items: center; gap: 4px">
            <strong style="color: #64748b">标的实时价</strong>
            <span
              style="font-family: monospace; font-weight: bold; color: #d97706; font-size: 11.5px; letter-spacing: -0.5px"
              >{{ calc.realtimeEtfsText.value.replace(/:/g, '') }}</span
            >
          </div>
        </div>
      </div>
    </n-card>

    <!-- =============================================================
         现金管理债券ETF专属面板
         ============================================================= -->
    <div
      v-if="calc.isCashManagement.value && cashFundInfo"
      style="display: flex; flex-direction: column; gap: 8px; width: 100%; margin-bottom: 8px"
    >
      <!-- 基本信息卡片 -->
      <div
        style="background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); padding: 12px 16px; border-radius: 8px; border: 1px solid #6ee7b7; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05)"
      >
        <div style="display: flex; align-items: center; gap: 16px; flex-wrap: wrap">
          <div style="display: flex; align-items: center; gap: 8px">
            <span style="font-size: 16px; font-weight: bold; color: #065f46">{{ cashFundInfo.name }}</span>
            <n-tag type="success" size="small" round>{{ cashFundInfo.type }}</n-tag>
            <n-tag type="warning" size="small" round>风险: {{ cashFundInfo.riskLevel }}</n-tag>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="font-size: 13px; color: #374151">
            <strong>赎回门槛:</strong> {{ cashFundInfo.redemptionMin }}
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="font-size: 13px; color: #374151">
            <strong>到账:</strong> {{ cashFundInfo.redemptionDays }}
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="font-size: 13px; color: #374151">
            <strong>节假日:</strong> {{ cashFundInfo.holidayRule }}
          </div>
        </div>
      </div>

      <!-- 估值计算器面板 -->
      <div
        style="background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); padding: 12px 16px; border-radius: 8px; border: 1px solid #93c5fd; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05)"
      >
        <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap">
          <div style="flex: 1; display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
            <span style="font-size: 14px; font-weight: bold; color: #1e40af">估值参数</span>
            <span style="font-size: 12px; color: #64748b">最新净值:</span>
            <span style="font-family: monospace; font-weight: bold; color: #1e40af; font-size: 14px">{{
              calc.meta.value?.latest_nav
                ? Number(calc.meta.value.latest_nav).toFixed(4)
                : calc.meta.value?.base_data?.nav
                  ? Number(calc.meta.value.base_data.nav).toFixed(4)
                  : '-'
            }}</span>
            <span style="font-size: 12px; color: #64748b">日均增长:</span>
            <span style="font-family: monospace; font-weight: bold; color: #059669; font-size: 14px">{{
              calc.meta.value?.avg_daily_growth
                ? (calc.meta.value.avg_daily_growth * 10000).toFixed(1) + '万'
                : '-'
            }}</span>
          </div>
          <n-divider vertical style="margin: 0" />
          <div style="display: flex; align-items: center; gap: 8px">
            <span style="color: #555; font-size: 14px; font-weight: bold">预估净值:</span>
            <span style="font-size: 18px; font-weight: bold; color: #1565c0; font-family: monospace">{{
              calc.meta.value?.estimated_nav && calc.meta.value.estimated_nav > 0
                ? calc.meta.value.estimated_nav.toFixed(4)
                : '-'
            }}</span>
            <span style="color: #555; font-size: 14px; font-weight: bold">折价率:</span>
            <span
              :style="{
                fontSize: '16px',
                fontWeight: 'bold',
                color:
                  calc.simLofPrice.value > 0 && getEstNav() > 0
                    ? calc.simLofPrice.value / getEstNav() - 1 < 0
                      ? '#d32f2f'
                      : '#388e3c'
                    : '#999',
                fontFamily: 'monospace',
                width: '70px',
                textAlign: 'left',
              }"
            >
              {{
                calc.simLofPrice.value > 0 && getEstNav() > 0
                  ? ((calc.simLofPrice.value / getEstNav() - 1) * 100).toFixed(2) + '%'
                  : '-'
              }}
            </span>
          </div>
        </div>
        <!-- 测试价说明 -->
        <div
          v-if="waterLinePrice"
          style="margin-top: 6px; font-size: 11px; color: #64748b; display: flex; gap: 16px; flex-wrap: wrap"
        >
          <span>测试价 = 预估赎回净值 - 逆回购成本（{{ waterLinePrice.redeemDays }}天）</span>
          <span>折价买入线: 场内价格 &lt; 测试价时可考虑赎回套利</span>
          <span>经验阈值: 折价 &gt; 万5 大概率盈利</span>
        </div>
      </div>

      <!-- 套利策略提示 -->
      <div
        style="background: linear-gradient(135deg, #fefce8 0%, #fef3c7 100%); padding: 10px 16px; border-radius: 8px; border: 1px solid #fde047"
      >
        <div style="font-size: 13px; color: #78350f; font-weight: bold; margin-bottom: 6px">套利策略参考</div>
        <div style="display: flex; gap: 24px; flex-wrap: wrap; font-size: 12px; color: #92400e">
          <div><strong>折价赎回套利:</strong> 场内折价买入 → 赎回 → 按净值结算现金</div>
          <div><strong>日内价差:</strong> 早盘折价买入 → 收盘溢价卖出 → 赚差价 + 逆回购</div>
          <div><strong>节假日套利:</strong> 节假日前持有 → 节前卖出 → 赚取假期利息</div>
        </div>
      </div>

      <!-- 511520 BP手动输入面板 -->
      <div
        v-if="fundCode === '511520'"
        style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); padding: 10px 16px; border-radius: 8px; border: 1px solid #7dd3fc"
      >
        <div style="font-size: 13px; color: #0369a1; font-weight: bold; margin-bottom: 6px">Choice BP手动输入</div>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
          <span style="font-size: 12px; color: #64748b">7年期:</span>
          <input
            type="number"
            v-model.number="manualBp7y"
            step="0.5"
            style="width: 55px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #bae6fd; border-radius: 4px; text-align: center"
          />
          <span style="font-size: 11px; color: #94a3b8">bp</span>
          <span style="font-size: 12px; color: #64748b">10年期:</span>
          <input
            type="number"
            v-model.number="manualBp10y"
            step="0.5"
            style="width: 55px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #bae6fd; border-radius: 4px; text-align: center"
          />
          <span style="font-size: 11px; color: #94a3b8">bp</span>
          <n-button size="tiny" type="primary" @click="submitBpOverride">应用</n-button>
          <n-button size="tiny" quaternary @click="clearBpOverride">清除</n-button>
          <span
            v-if="calc.meta.value?.bp_source === 'manual'"
            style="font-size: 11px; color: #d97706; font-weight: bold"
            >已应用 (今日有效)</span
          >
        </div>
      </div>
    </div>

    <!-- =============================================================
         估值与对冲数量推演区（非现金管理）
         ============================================================= -->
    <div
      v-if="!calc.isCashManagement.value"
      style="display: flex; flex-direction: column; gap: 8px; width: 100%; margin-bottom: 8px"
    >
      <!-- Panel 1: ETF实时估值 + 对冲数量 -->
      <div
        style="background: #f0f8ff; padding: 8px 14px; border-radius: 8px; border: 1px solid #bae6fd; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05)"
      >
        <div style="display: flex; flex-direction: column; gap: 6px; width: 100%">
          <!-- Row 1 -->
          <div style="display: flex; align-items: center; gap: 12px; width: 100%">
            <div style="width: 160px; flex-shrink: 0">
              <span style="font-size: 15px; font-weight: bold; color: #0284c7">ETF实时估值</span>
            </div>
            <div style="flex-shrink: 0; display: flex; align-items: center; gap: 2px">
              <div
                v-for="(item, index) in calc.uniqueValuationSymbols.value"
                :key="item.symbol"
                style="display: flex; align-items: center; white-space: nowrap"
              >
                <span
                  v-if="index === 0"
                  style="color: #1565c0; font-size: 14px; font-weight: bold; width: 60px; text-align: right; padding-right: 6px; flex-shrink: 0"
                  >{{ item.symbol }}价</span
                >
                <span
                  v-else
                  style="color: #1565c0; font-size: 14px; font-weight: bold; padding-right: 6px; padding-left: 12px; flex-shrink: 0"
                  >{{ item.symbol }}价</span
                >
                <input
                  type="number"
                  :value="calc.testEtfPrices[item.symbol]"
                  @input="onEtfPriceInput(item.symbol, $event)"
                  step="0.01"
                  style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; color: #1565c0; font-weight: bold; text-align: center; flex-shrink: 0"
                  :data-sym="item.symbol"
                />
              </div>
            </div>
            <div
              v-if="calc.isComplexCategory.value"
              style="flex: 1; min-width: 0; display: flex; align-items: center; gap: 4px; flex-wrap: nowrap"
            >
              <span style="font-size: 13px; color: #333; white-space: nowrap">买LOF</span>
              <input
                type="number"
                :value="calc.targetLofQty.value"
                @input="onTargetLofQtyInput"
                step="100"
                style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; text-align: center; color: #d35400"
              />
              <span style="font-size: 13px; color: #333; white-space: nowrap">股，投入</span>
              <span
                style="font-size: 15px; color: #d35400; font-weight: bold; font-family: monospace; white-space: nowrap"
                >{{ calc.syncedCapital.value || '-' }}</span
              >
              <span style="font-size: 13px; color: #333; white-space: nowrap"
                >元，做空 {{ calc.meta.value?.fund_config?.trade_etf }}</span
              >
              <span
                style="font-size: 15px; color: #1565c0; font-weight: bold; font-family: monospace; white-space: nowrap"
                >{{ calc.lofQtyEtf.value ? calc.lofQtyEtf.value.etfQty : '-' }}</span
              >
              <span style="font-size: 13px; color: #333; white-space: nowrap">股</span>
            </div>
          </div>
          <!-- Row 2 -->
          <div style="display: flex; align-items: center; gap: 12px; width: 100%">
            <div style="width: 160px; flex-shrink: 0; display: flex; align-items: center; gap: 6px">
              <span style="color: #555; font-size: 14px; font-weight: bold; white-space: nowrap">估值:</span>
              <span
                style="font-size: 18px; font-weight: bold; color: #1565c0; font-family: monospace"
                >{{ calc.etfVal.value > 0 ? calc.etfVal.value.toFixed(4) : '-' }}</span
              >
            </div>
            <div
              style="width: 140px; flex-shrink: 0; display: flex; align-items: center; gap: 6px"
            >
              <span
                style="color: #555; font-size: 14px; font-weight: bold; white-space: nowrap; padding-left: 16px"
                >溢价:</span
              >
              <span
                :style="{
                  fontSize: '16px',
                  fontWeight: 'bold',
                  color: calc.derivedEtfPremium.value > 0 ? '#d32f2f' : '#388e3c',
                  fontFamily: 'monospace',
                }"
              >
                {{
                  calc.etfVal.value > 0 && calc.simLofPrice.value > 0
                    ? (calc.derivedEtfPremium.value > 0 ? '+' : '') +
                      calc.derivedEtfPremium.value.toFixed(3) +
                      '%'
                    : '-'
                }}
              </span>
            </div>
            <div
              v-if="calc.isComplexCategory.value"
              style="flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; flex-wrap: nowrap"
            >
              <span style="font-size: 11px; color: #888; white-space: nowrap"
                >对冲值:
                <span style="color: #1565c0; font-family: monospace">{{
                  (calc.meta.value?.base_data?.hedge || 0).toFixed(4)
                }}</span></span
              >
              <span style="font-size: 11px; color: #888; white-space: nowrap"
                >敞口:
                <span style="color: #e65100; font-family: monospace">{{
                  calc.lofQtyEtf.value ? calc.lofQtyEtf.value.exposure.toFixed(2) : '-'
                }}元</span></span
              >
              <span
                v-if="
                  calc.lofQtyEtf.value &&
                  calc.lofQtyEtf.value.breakdown &&
                  calc.lofQtyEtf.value.breakdown.length > 0
                "
                style="font-size: 11px; color: #1565c0; white-space: nowrap"
              >
                一篮子拆解:
                <span
                  v-for="(item, idx) in calc.lofQtyEtf.value.breakdown"
                  :key="item.symbol"
                  style="font-family: monospace; font-weight: bold"
                  >{{ item.symbol }}={{ item.qty }}股<span v-if="idx < calc.lofQtyEtf.value.breakdown.length - 1">, </span></span
                >
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Panel 2: 期货校准估值 + 对冲数量 -->
      <div
        v-if="calc.showFutCalib.value && calc.isComplexCategory.value"
        style="background: #fffaf0; padding: 8px 14px; border-radius: 8px; border: 1px solid #fed7aa; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05)"
      >
        <div
          style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%"
        >
          <!-- 左侧 -->
          <div style="flex: 1; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
            <span style="font-size: 15px; font-weight: bold; color: #c2410c; width: 95px"
              >期货校准估值</span
            >
            <span style="color: #e65100; font-size: 14px; font-weight: bold"
              >{{ calc.meta.value?.fund_config?.trade_future }}:</span
            >
            <input
              type="number"
              :value="calc.testFutPrice.value"
              @input="onFutPriceInput"
              step="0.01"
              style="width: 75px; padding: 3px; font-size: 14px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; color: #e65100; font-weight: bold; text-align: center"
            />
            <span style="color: #555; font-size: 13px; font-weight: bold; margin-left: 4px"
              >校准:</span
            >
            <input
              type="number"
              :value="calc.testFutCalib.value"
              @input="onFutCalibInput"
              step="0.0001"
              style="width: 60px; padding: 3px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; text-align: center"
            />
          </div>

          <n-divider vertical style="margin: 0" />

          <!-- 中间 估值 & 溢价 -->
          <div
            style="width: 220px; display: flex; align-items: center; gap: 6px; justify-content: center"
          >
            <span style="color: #555; font-size: 14px; font-weight: bold">估值:</span>
            <span
              style="font-size: 18px; font-weight: bold; color: #e65100; font-family: monospace; width: 65px; text-align: left"
              >{{ calc.futCalibVal.value > 0 ? calc.futCalibVal.value.toFixed(4) : '-' }}</span
            >
            <span style="color: #555; font-size: 14px; font-weight: bold">溢价:</span>
            <span
              :style="{
                fontSize: '16px',
                fontWeight: 'bold',
                color: calc.derivedFutPremium.value > 0 ? '#d32f2f' : '#388e3c',
                fontFamily: 'monospace',
                width: '60px',
                textAlign: 'left',
              }"
            >
              {{
                calc.futCalibVal.value > 0 && calc.simLofPrice.value > 0
                  ? (calc.derivedFutPremium.value > 0 ? '+' : '') +
                    calc.derivedFutPremium.value.toFixed(3) +
                      '%'
                  : '-'
              }}
            </span>
          </div>

          <n-divider vertical style="margin: 0" />

          <!-- 右侧 交易 -->
          <div style="flex: 1.2; display: flex; align-items: center; gap: 4px; flex-wrap: wrap">
            <span style="font-size: 13px; color: #333">交易</span>
            <input
              type="number"
              :value="calc.targetLotsFuture.value"
              @input="onTargetLotsFutureInput"
              step="1"
              style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; text-align: center; color: #d35400"
            />
            <span style="font-size: 13px; color: #333">手期货 → 对应LOF</span>
            <span
              style="font-size: 15px; color: #d32f2f; font-weight: bold; font-family: monospace"
              >{{ calc.lofQtyFuture.value ? calc.lofQtyFuture.value.lofQty : '-' }}</span
            >
            <span style="font-size: 13px; color: #333">股</span>
          </div>
        </div>
        <div
          style="display: flex; justify-content: center; gap: 24px; font-size: 11px; color: #888; margin-top: 3px"
        >
          <span
            >对冲值:
            <span style="color: #c2410c; font-family: monospace">{{
              calc.lofQtyFuture.value ? calc.lofQtyFuture.value.hedgeValue.toFixed(4) : '-'
            }}</span></span
          >
          <span
            >敞口:
            <span style="color: #e65100; font-family: monospace">{{
              calc.lofQtyFuture.value ? calc.lofQtyFuture.value.exposure.toFixed(2) : '-'
            }}元</span></span
          >
          <span
            >校准ETF:
            <span style="color: #e65100; font-family: monospace">{{
              calc.equivEtfPrice.value > 0 ? calc.equivEtfPrice.value.toFixed(3) : '-'
            }}</span></span
          >
        </div>
      </div>

      <!-- Panel 3: 纯期货估值 + 对冲数量 -->
      <div
        v-if="calc.showPureFut.value && calc.isComplexCategory.value"
        style="background: #f2fbf5; padding: 8px 14px; border-radius: 8px; border: 1px solid #bbf7d0; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05)"
      >
        <div
          style="display: flex; align-items: center; justify-content: flex-start; gap: 12px; width: 100%"
        >
          <div style="flex: 1; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
            <span style="font-size: 15px; font-weight: bold; color: #15803d; width: 95px"
              >纯期货估值</span
            >
            <span style="color: #15803d; font-size: 14px; font-weight: bold"
              >{{ calc.meta.value?.fund_config?.trade_future }}:</span
            >
            <input
              type="number"
              :value="calc.testFutPrice.value"
              @input="onFutPriceInput"
              step="0.01"
              style="width: 75px; padding: 3px; font-size: 14px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; color: #15803d; font-weight: bold; text-align: center"
            />
          </div>

          <n-divider vertical style="margin: 0" />

          <div
            style="width: 220px; display: flex; align-items: center; gap: 6px; justify-content: center"
          >
            <span style="color: #555; font-size: 14px; font-weight: bold">估值:</span>
            <span
              style="font-size: 18px; font-weight: bold; color: #2e7d32; font-family: monospace; width: 65px; text-align: left"
              >{{
                calc.pureFutVal.value > 0 ? calc.pureFutVal.value.toFixed(4) : '-'
              }}</span
            >
            <span style="color: #555; font-size: 14px; font-weight: bold">溢价:</span>
            <span
              :style="{
                fontSize: '16px',
                fontWeight: 'bold',
                color: calc.derivedPureFutPremium.value > 0 ? '#d32f2f' : '#388e3c',
                fontFamily: 'monospace',
                width: '60px',
                textAlign: 'left',
              }"
            >
              {{
                calc.pureFutVal.value > 0 && calc.simLofPrice.value > 0
                  ? (calc.derivedPureFutPremium.value > 0 ? '+' : '') +
                    calc.derivedPureFutPremium.value.toFixed(3) +
                      '%'
                  : '-'
              }}
            </span>
          </div>

          <n-divider vertical style="margin: 0" />

          <div style="flex: 1.2; display: flex; align-items: center; gap: 4px; flex-wrap: wrap">
            <span style="font-size: 13px; color: #333">交易</span>
            <input
              type="number"
              :value="calc.targetLotsPureFuture.value"
              @input="onTargetLotsPureFutureInput"
              step="1"
              style="width: 65px; padding: 2px 4px; font-size: 13px; font-family: monospace; border: 1px solid #ccc; border-radius: 4px; font-weight: bold; text-align: center; color: #d35400"
            />
            <span style="font-size: 13px; color: #333">手期货 → 对应LOF</span>
            <span
              style="font-size: 15px; color: #d32f2f; font-weight: bold; font-family: monospace"
              >{{
                calc.lofQtyPureFuture.value ? calc.lofQtyPureFuture.value.lofQty : '-'
              }}</span
            >
            <span style="font-size: 13px; color: #333">股</span>
          </div>
        </div>
        <div
          style="display: flex; justify-content: center; gap: 24px; font-size: 11px; color: #888; margin-top: 3px"
        >
          <span
            >对冲值:
            <span style="color: #15803d; font-family: monospace">{{
              calc.lofQtyPureFuture.value
                ? calc.lofQtyPureFuture.value.hedgeValue.toFixed(4)
                : '-'
            }}</span></span
          >
          <span
            >敞口:
            <span style="color: #e65100; font-family: monospace">{{
              calc.lofQtyPureFuture.value
                ? calc.lofQtyPureFuture.value.exposure.toFixed(2)
                : '-'
            }}元</span></span
          >
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ValuationCalculator - 共享实时估值计算器组件
 *
 * 封装 T-2/T-1/实时数据行 + ETF估值 + 期货校准 + 纯期货面板。
 * 通过 defineExpose 暴露内部 composable 状态，供父页面通过模板 ref 访问。
 *
 * 用法：
 *   <ValuationCalculator ref="vcRef" :fund-code="fundCode" />
 *   父页面通过 vcRef?.simLofPrice, vcRef?.etfVal 等访问状态
 */
import { ref, computed, watch } from 'vue'
import { NCard, NDivider, NTag, NButton } from 'naive-ui'
import { useValuationCalculator } from '../composables/useValuationCalculator'
import { postBpOverride, clearBpOverride as clearBpOverrideApi } from '../api'

const props = defineProps<{
  fundCode: string
}>()

const calc = useValuationCalculator()

// 同步 fundCode 到 composable
watch(
  () => props.fundCode,
  (code) => {
    if (code && code !== calc.fundCode.value) {
      calc.fundCode.value = code
      calc.resetInitialized()
    }
  },
  { immediate: true },
)

// ============================================================
// 输入事件转发（使父页面可通过 defineExpose 访问最新值）
// ============================================================
const onSimLofPriceInput = (e: Event) => {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (!isNaN(val)) calc.simLofPrice.value = val
}

const onEtfPriceInput = (sym: string, e: Event) => {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (!isNaN(val)) calc.testEtfPrices[sym] = val
}

const onFutPriceInput = (e: Event) => {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (!isNaN(val)) calc.testFutPrice.value = val
}

const onFutCalibInput = (e: Event) => {
  const val = parseFloat((e.target as HTMLInputElement).value)
  if (!isNaN(val)) calc.testFutCalib.value = val
}

const onTargetLofQtyInput = (e: Event) => {
  const val = parseInt((e.target as HTMLInputElement).value, 10)
  if (!isNaN(val) && val >= 0) calc.targetLofQty.value = val
}

const onTargetLotsFutureInput = (e: Event) => {
  const val = parseInt((e.target as HTMLInputElement).value, 10)
  if (!isNaN(val) && val >= 0) calc.targetLotsFuture.value = val
}

const onTargetLotsPureFutureInput = (e: Event) => {
  const val = parseInt((e.target as HTMLInputElement).value, 10)
  if (!isNaN(val) && val >= 0) calc.targetLotsPureFuture.value = val
}

// ============================================================
// 现金管理（与 LazyMode 保持一致的完整版本）
// ============================================================
const manualBp7y = ref(0)
const manualBp10y = ref(0)

const cashFundInfo = computed(() => {
  const code = props.fundCode
  if (!code) return null
  const infoMap: Record<
    string,
    { name: string; type: string; redemptionMin: string; redemptionDays: string; holidayRule: string; riskLevel: string }
  > = {
    '511880': {
      name: '银华日利ETF',
      type: '货币基金',
      redemptionMin: '1份',
      redemptionDays: 'T+1盘中到账（银河）',
      holidayRule: '节前最后一天结算假期收益',
      riskLevel: '极低',
    },
    '511360': {
      name: '短融ETF',
      type: '短期融资券ETF',
      redemptionMin: '2000份（约22万）',
      redemptionDays: 'T+2盘中到账（银河）',
      holidayRule: '节后第一天更新净值',
      riskLevel: '中低',
    },
    '511520': {
      name: '政金债ETF',
      type: '中长期政金债ETF',
      redemptionMin: '10000份（约1.14万）',
      redemptionDays: 'T+2 14:30后到账',
      holidayRule: '-',
      riskLevel: '中',
    },
  }
  return infoMap[code] || null
})

const getEstNav = () => {
  if (calc.isCashManagement.value) {
    return calc.meta.value?.estimated_nav || 0
  }
  return calc.meta.value?.rt_val || 0
}

const waterLinePrice = computed(() => {
  if (!calc.meta.value?.base_data) return null
  const bd = calc.meta.value.base_data
  const nav = parseFloat(bd.nav) || 0
  const avgGrowth = calc.meta.value?.avg_daily_growth || 0

  if (nav <= 0 || avgGrowth === 0) return null

  const estimatedRedeemNav = nav + avgGrowth
  const repoCost = 0.02
  const dailyRepoCost = repoCost / 252
  const redeemDays = props.fundCode === '511880' ? 1 : 2
  const totalRepoCost = dailyRepoCost * redeemDays
  const waterLine = estimatedRedeemNav * (1 - totalRepoCost)

  return {
    estimatedRedeemNav: Math.round(estimatedRedeemNav * 10000) / 10000,
    waterLine: Math.round(waterLine * 10000) / 10000,
    avgDailyGrowth: avgGrowth,
    treasuryPct: calc.meta.value?.treasury_index_pct || 0,
    repoCost: (totalRepoCost * 10000).toFixed(1) + '万',
    redeemDays,
  }
})

const submitBpOverride = async () => {
  try {
    await postBpOverride(props.fundCode, manualBp7y.value, manualBp10y.value)
    calc.fetchValuationMeta()
  } catch {
    /* ignore */
  }
}

const clearBpOverride = async () => {
  try {
    await clearBpOverrideApi(props.fundCode)
    manualBp7y.value = 0
    manualBp10y.value = 0
    calc.fetchValuationMeta()
  } catch {
    /* ignore */
  }
}

// ============================================================
// 暴露内部状态给父页面（通过模板 ref 访问）
// ============================================================
defineExpose({
  // 直接透传 composable 的所有导出
  ...calc,
  // 额外的现金管理状态
  cashFundInfo,
  getEstNav,
  waterLinePrice,
  manualBp7y,
  manualBp10y,
})
</script>
