<template>
  <div class="holding-analysis-page">
    <n-card :bordered="false" class="shadow-soft" size="small">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <n-button text size="small" @click="router.push('/dashboard')" style="color: #64748b; padding: 0 4px;">
              ← 返回主看板
            </n-button>
            <n-icon size="20" color="#2563eb"><PieChart /></n-icon>
            <span style="font-size: 16px; font-weight: bold;">季报持仓分析</span>
            <n-tag size="small" type="info">{{ fundCode }}</n-tag>
            <span style="font-size: 14px; color: #475569;">{{ fundName || fundCode }}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 12px; color: #64748b;">持仓静态估值:</span>
            <n-tag v-if="staticSynced" size="small" :bordered="false" type="success">
              已同步（最新 {{ staticLatestDate }}）
            </n-tag>
            <n-tag v-else size="small" :bordered="false" type="warning">未同步</n-tag>
            <n-button size="small" :loading="staticSyncLoading" @click="syncStaticValuation">
              同步静态持仓估值
            </n-button>
          </div>
        </div>
      </template>

      <n-alert v-if="syncAlert" type="warning" :show-icon="true" style="margin-bottom: 12px;">
        {{ syncAlert }}
      </n-alert>
      <n-alert
        v-if="staticSyncMsg"
        :type="staticSyncMsg.startsWith('✅') ? 'success' : 'error'"
        :show-icon="true"
        style="margin-bottom: 12px;"
      >
        {{ staticSyncMsg }}
      </n-alert>

      <!-- [AI-2026-09-24 东哥需求] 美股价新鲜度：ARM 缺「新浪口径最新交易日」收盘价时提示 + 一键重抓推送 -->
      <n-alert
        v-if="priceFresh && priceFresh.stale"
        type="warning"
        :show-icon="true"
        style="margin-bottom: 12px;"
      >
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
          <div style="font-size: 12px; line-height: 1.7; color: #92400e;">
            新浪已更新 <strong>{{ priceFresh.reference_date }}</strong> 美股收盘价，但 ARM 最新只到
            <strong>{{ priceFresh.arm_clock || priceFresh.arm_latest || '-' }}</strong>
            → 静态估值不会起该日新行（宁缺毋假）。
            <span v-if="priceFresh.missing_auto && priceFresh.missing_auto.length">
              <br>参考日缺价：{{ priceFresh.missing_auto.join('、') }}
            </span>
          </div>
          <n-button size="small" type="warning" :loading="refetchLoading" @click="refetchUsPrices">
            重新从数据源抓取并推送到 ARM
          </n-button>
        </div>
      </n-alert>
      <n-alert
        v-if="refetchMsg"
        :type="refetchMsg.startsWith('✅') ? 'success' : 'error'"
        :show-icon="true"
        style="margin-bottom: 12px;"
      >
        {{ refetchMsg }}
      </n-alert>

      <div v-if="loading" style="text-align: center; padding: 40px; color: #999;">
        <n-spin size="small" />
        <span style="margin-left: 8px;">加载中...</span>
      </div>

      <n-empty v-else-if="error" :description="error" style="padding: 40px;" />

      <template v-else-if="holdings.length > 0">
        <!-- 顶部概览：报告日期 + 披露持仓数 + 地区分布 + 总权重 + 底层期货 -->
        <n-grid :cols="24" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
          <n-gi :span="4">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">报告截止日</div>
              <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ reportDate || '-' }}</div>
            </n-card>
          </n-gi>
          <n-gi :span="4">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">披露持仓数</div>
              <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ holdings.length }} 只</div>
            </n-card>
          </n-gi>
          <n-gi :span="5">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b; margin-bottom: 4px;">地区分布</div>
              <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <div v-for="r in regionDistribution" :key="r.region" style="display: flex; align-items: center; gap: 3px;">
                  <span style="font-weight: 600; color: #1e293b; font-size: 11px;">{{ regionLabel(r.region) }}</span>
                  <span style="font-size: 13px; font-weight: bold; color: #2563eb;">{{ r.pct.toFixed(1) }}%</span>
                </div>
              </div>
            </n-card>
          </n-gi>
          <n-gi :span="5">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">总权重（前十大）</div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">{{ totalWeight.toFixed(2) }}%</div>
            </n-card>
          </n-gi>
          <n-gi :span="6">
            <n-card
              size="small"
              class="stat-card"
              content-style="padding: 10px; cursor: pointer;"
              style="transition: background 0.2s;"
              :style="penetrationReady ? { background: '#f0f9ff', border: '1px solid #bae6fd' } : { background: '#f8fafc' }"
              @click="penetrationReady ? goToPenetration() : null"
              @mouseenter="penetrationReady = true"
              @mouseleave="penetrationReady = false"
            >
              <div style="font-size: 11px; color: #64748b; margin-bottom: 4px;">底层期货（点击穿透）</div>
              <div v-if="penetrationData" style="display: flex; gap: 12px; flex-wrap: wrap;">
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #ea580c;">{{ wtiPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">WTI (CL)</div>
                </div>
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #7c3aed;">{{ brentPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">Brent (B)</div>
                </div>
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #16a34a;">{{ penetratedPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">已穿透</div>
                </div>
              </div>
              <div v-else style="font-size: 13px; color: #94a3b8;">—</div>
            </n-card>
          </n-gi>
        </n-grid>

        <!-- 持仓实时估值 -->
        <n-card v-if="valuation" size="small" class="shadow-soft" style="margin-bottom: 16px; background: #f8fafc;">
          <template #header>
            <div style="font-size: 14px; font-weight: bold;">持仓实时估值（CL 合约月 · 近月±1）</div>
          </template>
          <n-grid :cols="24" :x-gap="12" :y-gap="12">
            <n-gi :span="4" style="cursor: pointer;" @click="openRecalcModal">
              <div style="font-size: 12px; color: #64748b;">
                最新净值<span v-if="latestNavDate" style="font-size: 11px; color: #94a3b8;">（{{ latestNavDate }}）</span>
              </div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">
                {{ latestNav != null ? latestNav.toFixed(4) : '-' }}
              </div>
              <div style="font-size: 10px; color: #2563eb; margin-top: 2px;">点击查看持仓静态估值</div>
            </n-gi>
            <!-- 实时估值：选中合约蓝字大 + 其他合约灰字小 -->
            <n-gi :span="4" style="cursor: pointer;" @click="openRealtimeModal">
              <div style="font-size: 12px; color: #64748b;">实时估值</div>
              <template v-if="cSel">
                <div style="font-size: 18px; font-weight: bold; line-height: 1.25; color: #2563eb;">
                  {{ cSel.realtime_nav != null ? cSel.realtime_nav.toFixed(4) : '缺失' }}<span style="font-size: 11px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(hedgeContract) }}</span>
                </div>
                <div v-for="oc in otherContracts" :key="oc" style="font-size: 13px; font-weight: bold; line-height: 1.25; color: #94a3b8;">
                  {{ cData(oc)?.realtime_nav != null ? cData(oc)!.realtime_nav.toFixed(4) : '-' }}<span style="font-size: 10px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(oc) }}</span>
                </div>
              </template>
              <div v-else style="font-size: 18px; font-weight: bold; color: #94a3b8;">-</div>
              <div style="font-size: 10px; color: #2563eb; margin-top: 2px;">点击核对CL分母</div>
            </n-gi>
            <n-gi :span="4">
              <div style="font-size: 12px; color: #64748b;">实时ETF现价</div>
              <div style="font-size: 18px; font-weight: bold;" :style="{ color: cSel && cSel.lof_price != null ? '#dc2626' : '#94a3b8' }">
                {{ cSel && cSel.lof_price != null ? cSel.lof_price.toFixed(3) : '-' }}
              </div>
              <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">
                {{ lofSrcLabel(cSel && cSel.lof_price_source) }}
              </div>
            </n-gi>
            <!-- 实时持仓溢价：选中蓝 + 其他灰 -->
            <n-gi :span="4">
              <div style="font-size: 12px; color: #64748b;">实时持仓溢价</div>
              <template v-if="cSel">
                <div style="font-size: 18px; font-weight: bold; line-height: 1.25;" :style="{ color: priceColor((cSel.realtime_premium || 0) * 100) }">
                  {{ cSel.realtime_premium != null ? formatPercent(cSel.realtime_premium * 100, 3) : '-' }}<span style="font-size: 11px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(hedgeContract) }}</span>
                </div>
                <div v-for="oc in otherContracts" :key="'p'+oc" style="font-size: 13px; font-weight: bold; line-height: 1.25;" :style="{ color: priceColor((cData(oc)?.realtime_premium || 0) * 100) }">
                  {{ cData(oc)?.realtime_premium != null ? formatPercent(cData(oc)!.realtime_premium * 100, 3) : '-' }}<span style="font-size: 10px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(oc) }}</span>
                </div>
              </template>
              <div v-else style="font-size: 18px; font-weight: bold; color: #94a3b8;">-</div>
              <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">现价/实时估值-1</div>
            </n-gi>
            <!-- 累计涨跌贡献：选中蓝 + 其他灰 -->
            <n-gi :span="4">
              <div style="font-size: 12px; color: #64748b;">累计涨跌贡献</div>
              <template v-if="cSel">
                <div style="font-size: 18px; font-weight: bold; line-height: 1.25;" :style="{ color: priceColor((cSel.total_change_pct || 0) * 100) }">
                  {{ cSel.total_change_pct != null ? formatPercent(cSel.total_change_pct * 100, 2) : '-' }}<span style="font-size: 11px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(hedgeContract) }}</span>
                </div>
                <div v-for="oc in otherContracts" :key="'t'+oc" style="font-size: 13px; font-weight: bold; line-height: 1.25;" :style="{ color: priceColor((cData(oc)?.total_change_pct || 0) * 100) }">
                  {{ cData(oc)?.total_change_pct != null ? formatPercent(cData(oc)!.total_change_pct * 100, 2) : '-' }}<span style="font-size: 10px; font-weight: normal; margin-left: 2px;">{{ contractMonthLabel(oc) }}</span>
                </div>
              </template>
              <div v-else style="font-size: 18px; font-weight: bold; color: #94a3b8;">-</div>
            </n-gi>
            <n-gi :span="4">
              <div style="font-size: 12px; color: #64748b;">有效权重覆盖</div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">
                {{ cSel && cSel.valid_weight_sum != null ? (cSel.valid_weight_sum * 100).toFixed(2) + '%' : '-' }}
              </div>
            </n-gi>
          </n-grid>
          <div v-if="cSel && cSel.components && cSel.components.some((c: any) => c.status !== 'ok')" style="margin-top: 10px; font-size: 11px; color: #64748b;">
            注：部分底层标的缺少报告日收盘价或实时行情，仅使用有效标的计算估值。
          </div>
        </n-card>

        <!-- 前十大持仓表 -->
        <n-card size="small" class="shadow-soft" style="margin-bottom: 16px;">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
              <div style="font-size: 14px; font-weight: bold;">前十大持仓</div>
              <div style="display: flex; align-items: center; gap: 8px;">
                <span style="font-size: 12px; color: #64748b;">报告期:</span>
                <n-button
                  v-for="p in periods"
                  :key="p.period"
                  size="small"
                  type="default"
                  :style="currentPeriod === p.period
                    ? { background: '#16a34a !important', borderColor: '#16a34a !important', color: '#fff !important', fontWeight: 'bold' }
                    : { background: 'transparent !important', borderColor: '#cbd5e1 !important', color: '#64748b !important' }"
                  @click="switchPeriod(p.period)"
                >
                  {{ p.period }}
                </n-button>
              </div>
            </div>
          </template>
          <n-data-table
            :columns="holdingColumns"
            :data="holdings"
            :summary="holdingSummary"
            size="small"
            bordered
            :pagination="false"
            style="max-height: 500px;"
          />
        </n-card>

        <!-- 退出 / 新进前十 — 并排（只要有上期就显示，列表为空则提示"无"，让用户看清朝季度持仓无变化） -->
        <n-grid :cols="24" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
          <n-gi :span="12" v-if="prevPeriod">
            <n-card size="small" class="shadow-soft" style="background: #fff7ed;">
              <template #header>
                <div style="font-size: 13px; font-weight: bold; color: #9a3412;">本期已退出前十（上期 {{ prevPeriod }}）</div>
              </template>
              <div v-for="(item, idx) in exited" :key="idx" style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #ffedd5;">
                <span style="font-size: 12px;">
                  <span v-if="item.symbol" style="font-weight: 600; margin-right: 6px;">{{ item.symbol }}</span>
                  {{ item.name }}
                </span>
                <span style="font-size: 12px; color: #64748b;">{{ item.weight != null ? (item.weight * 100).toFixed(2) + '%' : '-' }}</span>
              </div>
              <div v-if="exited.length === 0" style="font-size: 12px; color: #94a3b8; padding: 6px 0;">无</div>
            </n-card>
          </n-gi>
          <n-gi :span="12" v-if="prevPeriod">
            <n-card size="small" class="shadow-soft" style="background: #f0fdf4;">
              <template #header>
                <div style="font-size: 13px; font-weight: bold; color: #166534;">本期新进前十（上期 {{ prevPeriod }}）</div>
              </template>
              <div v-for="(item, idx) in newIn" :key="idx" style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #dcfce7;">
                <span style="font-size: 12px;">
                  <span v-if="item.symbol" style="font-weight: 600; margin-right: 6px;">{{ item.symbol }}</span>
                  {{ item.name }}
                </span>
                <span style="font-size: 12px; color: #64748b;">{{ item.weight != null ? (item.weight * 100).toFixed(2) + '%' : '-' }}</span>
              </div>
              <div v-if="newIn.length === 0" style="font-size: 12px; color: #94a3b8; padding: 6px 0;">无</div>
            </n-card>
          </n-gi>
        </n-grid>
      </template>

      <n-empty v-else description="暂无持仓数据" style="padding: 40px;" />
    </n-card>

    <!-- 持仓静态估值弹窗（7-1 至今，降序分页） -->
    <n-modal
      v-model:show="recalcModalShow"
      preset="card"
      :title="fundCode + ' 持仓静态估值（7-1 至今）'"
      style="width: 760px; max-width: 92vw;"
    >
      <!-- [AI-2026-09-26] 手喂补录面板已删：OILUSA/1671/1699 已由 ARM sampler 自动抓取
           （SIX 官方 CSV / 雅虎日本），013_2 §9.1 旧"手动补数"结论废止。 -->
      <n-data-table
        v-if="recalcDisplayRows.length"
        :columns="recalcColumns"
        :data="recalcDisplayRows"
        :row-key="(row: any) => row.date"
        :pagination="{ pageSize: 15 }"
        :row-class-name="(row: any) => (row.pending ? 'recalc-pending-row' : (row.fill_warning ? 'recalc-warn-row' : (row.carried_forward ? 'recalc-carry-row' : '')))"
        size="small"
        bordered
      />
      <div v-if="recalcDetailLoading" style="font-size: 11px; color: #94a3b8; margin-top: 6px;">
        诊断细节加载中（底层 ETF / 缺价标注）…
      </div>
      <n-empty v-else description="该基金暂无持仓静态估值数据" />
    </n-modal>

    <!-- 持仓实时估值 - CL 分母核对弹窗（全合约对比，不单选切换） -->
    <n-modal
      v-model:show="realtimeModalShow"
      preset="card"
      style="width: 900px; max-width: 96vw;"
    >
      <template #header>
        {{ fundCode }} 对冲（全合约对比）<span
          v-if="modalPriceSeg"
          style="color: #1d4ed8; font-weight: bold; margin-left: 4px;"
        > · 现价 {{ modalPriceSeg.price }}{{ modalPriceSeg.src ? `（${modalPriceSeg.src}）` : '' }}</span>
      </template>
      <div v-if="valuation" style="font-size: 13px;">
        <!-- [AI-2026-09-17] 实时估值 / 溢价 / 反算：全 CL 合约同屏对比（不再单选切换），便于手动 Excel 核对 -->
        <div style="font-size: 13px; font-weight: bold; margin: 4px 0 6px;">实时估值 · 溢价 · 反算对比（全 CL 合约同屏）</div>
        <n-grid :cols="24" :x-gap="12" :y-gap="8" style="margin-bottom: 8px;">
          <n-gi :span="9">
            <div style="font-size: 12px; color: #64748b;">做空 MCL 手数（统一用于下方反算）</div>
            <n-input-number v-model:value="mclLots" :min="0" :step="1" size="small" style="width: 100%;" />
          </n-gi>
          <n-gi :span="15" style="font-size: 11px; color: #94a3b8; align-self: end;">
            合约按 YYMM 排（2611/2612/2701）；Brent 2611/2701 敞口以同月 CL 价跨品种对冲，并入对应 CL 合约行（标「Brent同月」）。实时价弹窗打开期间每 20 秒自动刷新，关闭即停。
          </n-gi>
        </n-grid>
        <!-- [AI-2026-09-18] 基础数据条：β/基准日/基准静态估值 对所有合约相同，从对比表抽出只显示一次 -->
        <div style="font-size: 12px; color: #475569; background: #f1f5f9; border-radius: 4px; padding: 6px 10px; margin-bottom: 8px;">
          <span style="font-weight: bold; color: #1e293b;">基础数据：</span>
          β(仓位) <span style="font-weight: bold;">{{ firstContract?.valid_weight_sum != null ? (firstContract!.valid_weight_sum * 100).toFixed(2) + '%' : '-' }}</span>
          　｜　基准日 <span style="font-weight: bold;">{{ firstContract?.base_date || firstContract?.freeze_trade_date || '-' }}</span>
          　｜　基准静态估值 <span style="font-weight: bold;">{{ firstContract?.base_nav != null ? firstContract!.base_nav.toFixed(4) : '-' }}</span>
        </div>
        <n-table :single-line="false" size="small" style="margin-bottom: 8px;">
          <thead>
            <tr>
              <th>对冲合约</th>
              <th>CL 实时价</th>
              <th>实时估值</th>
              <th>实时持仓溢价</th>
              <th>每手MCL→份数</th>
              <th>{{ mclLots }}手→份数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in contractKeys" :key="k">
              <td style="font-weight: bold; white-space: nowrap;">
                <n-tooltip trigger="hover" placement="top-start">
                  <template #trigger>
                    <span style="color: #2563eb; cursor: pointer; text-decoration: underline dotted #93c5fd;" @click="openCompareModal(k)">CL {{ k }}（{{ contractMonthLabel(k) }}<span v-if="brentMonthSet.has(k)" style="color: #d85a30;"> · Brent同月</span>）</span>
                  </template>
                  3个原油LOF对比（160723 / 161129 / 501018 同合约月套利对比，点击进入）
                </n-tooltip>
              </td>
              <td>
                <div style="font-size: 14px; font-weight: bold;">{{ cData(k)?.cl_now != null ? cData(k)!.cl_now.toFixed(3) : '-' }}</div>
                <div style="font-size: 10px; color: #94a3b8;">{{ cData(k)?.cl_time || '' }}</div>
              </td>
              <td style="font-size: 14px; font-weight: bold; color: #2563eb;">{{ cData(k)?.realtime_nav != null ? cData(k)!.realtime_nav.toFixed(4) : '-' }}</td>
              <td :style="{ fontSize: '14px', fontWeight: 'bold', color: cData(k)?.realtime_premium != null ? (cData(k)!.realtime_premium >= 0 ? '#dc2626' : '#16a34a') : '#1e293b' }">{{ cData(k)?.realtime_premium != null ? (cData(k)!.realtime_premium * 100).toFixed(3) + '%' : '-' }}</td>
              <td>{{ lofSharesPerLot(k) != null ? lofSharesPerLot(k)!.toLocaleString() : '-' }}</td>
              <td style="font-size: 14px; font-weight: bold; color: #16a34a;">{{ lofSharesForMclOf(k) != null ? lofSharesForMclOf(k)!.toLocaleString() : '-' }}</td>
            </tr>
          </tbody>
        </n-table>
        <!-- [AI-2026-09-21] 混合估值（WTI 动态加权）：抹平"单月 vs 混合持仓"基差残余；与进阶对冲 68/32 在 2611/2612 两合约分仓配对即根治 WTI 残差（"两"指两个合约月，非2手；实盘整手下需放大规模或接受近似） -->
        <div v-if="hedgeExposure?.hedge_plan && mixedValuation != null" style="background: #ecfeff; border: 1px solid #67e8f9; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px;">
          <div style="font-size: 13px; font-weight: bold; color: #0e7490;">
            混合估值（WTI {{ hedgeExposure.hedge_plan.months.join('+') }} 按 {{ hedgeExposure.hedge_plan.weights.join('/') }} 动态加权）＝
            <span style="font-size: 15px;">{{ mixedValuation.toFixed(4) }}</span>
            <span style="margin-left: 14px; color: {{ mixedPremium != null ? (mixedPremium >= 0 ? '#dc2626' : '#16a34a') : '#1e293b' }};">对应实时持仓溢价 {{ mixedPremium != null ? (mixedPremium * 100).toFixed(3) + '%' : '-' }}</span>
          </div>
          <div style="font-size: 11px; color: #64748b; margin-top: 4px;">
            把 WTI 内部 {{ hedgeExposure.hedge_plan.months.join('/') }} 比例还原，抹平"单月估值 vs 基金真实混合持仓"的基差残余（Brent 部分微扰可忽略）。与进阶对冲方案 68/32 在 2611/2612 两合约分仓配对即根治 WTI 基差残余（"两"指两个合约月、非2手；实盘整手约束下精确配比难落地，当前单月对冲仅作更接近真值的参考）。
          </div>
        </div>
        <div style="font-size: 11px; color: #94a3b8; margin-bottom: 10px;">
          公式：每手份数 = 100桶 × CL实时价 × 中间价(usd_cny_mid) ÷ (实时估值 × β)；N手 = 每手 × 手数。Brent 同月行与对应 WTI 行 CL 价/估值相同（同月跨品种对冲），仅对冲用途不同；Brent 2701 需 2701 冻结价（今夜 ARM 采样后生效，落地前该格显 -）。
        </div>

        <!-- [AI-2026-09-17] CL 三时点冻结价（ARM 采样，分母）：矩阵，上移到穿透表前（每天变的数据集中顶部） -->
        <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">CL 三时点冻结价（ARM 采样，分母）</div>
        <n-table :single-line="false" size="small" style="margin-bottom: 8px;">
          <thead>
            <tr><th>时点(NY)</th><th v-for="k in contractKeys" :key="k">CL {{ k }}（{{ contractMonthLabel(k) }}）</th></tr>
          </thead>
          <tbody>
            <tr v-for="pt in ['1130', '1430', '1600']" :key="pt">
              <td>{{ pt }}</td>
              <td v-for="k in contractKeys" :key="k">
                <div>{{ (cData(k)?.freeze_points && cData(k)!.freeze_points[pt]) ? cData(k)!.freeze_points[pt].price : '-' }}</div>
                <div style="font-size: 10px; color: #94a3b8;">{{ (cData(k)?.freeze_points && cData(k)!.freeze_points[pt]) ? cData(k)!.freeze_points[pt].trade_date : '' }}</div>
              </td>
            </tr>
          </tbody>
        </n-table>

        <!-- FX 实时（每天变，随冻结价上移） -->
        <div style="font-size: 12px; color: #64748b; margin-bottom: 10px;">
          今日中间价(usd_cny_mid, DB): {{ firstContract?.fx_now != null ? firstContract!.fx_now.toFixed(4) : '-' }} ｜
          汇率基准: {{ firstContract?.fx_point != null ? firstContract!.fx_point.toFixed(4) : '-' }} ｜
          状态: {{ firstContract?.fx_status }}
        </div>

        <!-- [AI-2026-09-17] 对冲穿透两表：静态估值(ETC市价)≠对冲(期货月份匹配)，两个独立问题 -->
        <template v-if="hedgeExposure && hedgeExposure.etfs && hedgeExposure.etfs.length">
          <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">底层 ETF → 实际持有合约月（穿透 · as-of {{ hedgeExposure.as_of }}）</div>
          <n-table :single-line="false" size="small" style="margin-bottom: 8px;">
            <thead>
              <tr><th>ETF</th><th>季报权重</th><th>结构 / 指数</th><th>当前持有合约</th><th>品种</th></tr>
            </thead>
            <tbody>
              <tr v-for="e in hedgeExposure.etfs" :key="e.etf">
                <td style="font-weight: bold;">{{ e.etf }}<span v-if="e.pending" style="color: #b45309;"> *</span></td>
                <td>{{ e.weight_pct }}%</td>
                <td style="font-size: 11px; color: #64748b;">{{ e.structure }}</td>
                <td>
                  <span v-if="e.pending" style="color: #b45309; font-weight: bold;">待核实（结构见左列）</span>
                  <span v-else>{{ e.contracts.map((c: any) => (e.variety === 'WTI' ? 'CL ' : 'Brent ') + c.month + (e.contracts.length > 1 ? ' ×' + c.pct + '%' : '')).join(' / ') }}</span>
                </td>
                <td :style="{ color: e.variety === 'WTI' ? '#2563eb' : '#d85a30', fontWeight: 'bold' }">{{ e.variety }}</td>
              </tr>
            </tbody>
          </n-table>
          <div v-if="hedgeExposure.pending_nav_pct > 0" style="font-size: 11px; color: #b45309; margin-bottom: 12px;">
            * 标 {{ hedgeExposure.pending_nav_pct }}% 净值的 ETF（DBO/OILUSA 等结构特殊：动态单月 / 曲线多期限分散）未计入下方月份敞口，待实测当前合约后补。
          </div>

          <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">归一化对冲分布：该空哪个月（WTI 书占净值 {{ hedgeExposure.wti_book_nav_pct }}%，MCL 唯一能盖的部分）</div>
          <n-table :single-line="false" size="small" style="margin-bottom: 8px;">
            <thead>
              <tr><th>月份</th><th>占WTI书</th><th>占净值</th><th>来自</th><th>MCL 可操作性</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in hedgeExposure.wti_months" :key="m.month">
                <td>CL {{ m.month }}</td>
                <td>{{ m.book_pct }}%</td>
                <td>{{ m.exp_nav_pct }}%</td>
                <td>{{ m.from }}</td>
                <td>{{ m.mcl_ok ? '可交易' : 'MCL 远月流动性差' }}</td>
              </tr>
              <tr>
                <td style="font-weight: bold;">WTI 小计</td>
                <td>100%</td>
                <td style="font-weight: bold;">{{ hedgeExposure.wti_book_nav_pct }}%</td>
                <td colspan="2">可对冲部分（MCL）</td>
              </tr>
              <tr v-for="bm in hedgeExposure.brent.months" :key="'b' + bm.month" style="color: #993c1d;">
                <td>Brent {{ bm.month }}</td>
                <td>{{ bm.book_pct }}%</td>
                <td>{{ bm.exp_nav_pct }}%</td>
                <td>{{ bm.from }}</td>
                <td>用 CL{{ bm.month }} 同月对冲（跨品种，WTI-Brent 相关≈0.9）</td>
              </tr>
              <tr style="color: #993c1d;">
                <td style="font-weight: bold;">Brent 小计</td>
                <td>100%</td>
                <td style="font-weight: bold;">{{ hedgeExposure.brent.book_nav_pct }}%</td>
                <td colspan="2">跨品种同月对冲（CL 对应月），覆盖至 95%；非精确，承担 WTI-Brent 价差</td>
              </tr>
            </tbody>
          </n-table>
          <div v-if="hedgeExposure.hedge_plan" style="font-size: 11px; color: #64748b; margin-bottom: 12px;">
            进阶对冲方案：{{ hedgeExposure.hedge_plan.months.join(' + ') }} 按 {{ hedgeExposure.hedge_plan.weights.join('/') }} 分配手数（覆盖 WTI 书 {{ hedgeExposure.hedge_plan.coverage_book_pct }}%，占净值 {{ hedgeExposure.hedge_plan.coverage_nav_pct }}%）；远月（MCL 流动性差）放弃。指数每月滚动，上表 as-of {{ hedgeExposure.as_of }}，滚仓后需人工更新。
          </div>
          <div v-if="mixedValuation != null" style="font-size: 11px; color: #0e7490; margin-bottom: 12px; background: #ecfeff; border-left: 3px solid #22d3ee; padding: 6px 10px;">
            此进阶方案的「混合估值」＝上方高亮框的 <b>{{ mixedValuation.toFixed(4) }}</b>，即 WTI 部分真实混合 NAV。若按 {{ hedgeExposure.hedge_plan.months.join('/') }} 的 {{ hedgeExposure.hedge_plan.weights.join('/') }} 在 2611/2612 两合约分仓空单（而非单月对冲），WTI 基差残余≈0，混合估值即你的锁定折价基准——这是<b>根治 WTI 基差残余</b>的方案（"两合约"指 2611+2612、非"2手"；实盘整手约束下难精确落地，当前单月对冲仅作参考）。
          </div>
        </template>

      </div>
      <n-empty v-else description="暂无实时估值数据（进入页面会自动从 ARM 同步 CL 分母，若失败顶部会报警）" />
    </n-modal>

    <!-- [AI-2026-09-18] 三原油 LOF 同合约月套利对比（从对冲弹窗"对冲合约"列合约名点击进入） -->
    <n-modal
      v-model:show="compareModalShow"
      preset="card"
      :title="'3个原油LOF对比 · CL ' + compareContract + '（' + contractMonthLabel(compareContract) + '）' + (compareClNow != null ? ' · CL实时价 ' + compareClNow.toFixed(3) : '')"
      style="width: 880px; max-width: 96vw;"
    >
      <div style="font-size: 13px;">
        <div v-if="compareLoading" style="color: #64748b; padding: 8px 0;">加载三基金实时数据…</div>
        <n-table v-else :single-line="false" size="small">
          <thead>
            <tr>
              <th>基金</th>
              <th>β(仓位)</th>
              <th>实时估值</th>
              <th>实时持仓溢价</th>
              <th>实时ETF现价</th>
              <th>每手MCL→份数</th>
              <th>赎回费</th>
              <th>扣费后净折价</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in compareRows" :key="row.code" :style="bestNetCode === row.code ? 'background: #f0fdf4;' : ''">
              <td style="font-weight: bold; white-space: nowrap;">{{ row.code }} {{ row.name }}</td>
              <td>{{ cmpBeta(row.data) }}</td>
              <td style="font-weight: bold; color: #2563eb;">{{ cmpNav(row.data) }}</td>
              <td :style="{ fontWeight: 'bold', color: row.data?.realtime_premium != null ? (row.data.realtime_premium >= 0 ? '#dc2626' : '#16a34a') : '#1e293b' }">{{ cmpPremium(row.data) }}</td>
              <td>
                <div>{{ cmpPrice(row.data) }}</div>
                <div style="font-size: 10px; color: #94a3b8;">{{ cmpPriceSrc(row.data) }}</div>
              </td>
              <td>{{ cmpShares(row.data) }}</td>
              <td>{{ (row.redeemFee * 100).toFixed(3) + '%' }}</td>
              <td :style="{ fontWeight: 'bold', color: cmpNet(row) != null ? (cmpNet(row)! <= 0 ? '#16a34a' : '#dc2626') : '#1e293b' }">
                {{ cmpNetLabel(row) }}<span v-if="bestNetCode === row.code" style="font-size: 10px; color: #16a34a; margin-left: 4px;">最优</span>
              </td>
            </tr>
          </tbody>
        </n-table>
        <div style="font-size: 11px; color: #94a3b8; margin-top: 8px;">
          净折价 = 实时持仓溢价 + 赎回费（市价买入 → 按估值赎回：毛利=|溢价|，扣赎回费后 = |净折价|；负值 = 扣费后仍有套利空间，越负越优，绿底行=当前最优）。三基金数据与各自"对冲"弹窗同源同口径，随主弹窗每 20 秒刷新。
        </div>
      </div>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NTag, NIcon, NEmpty, NSpin, NButton, NDataTable, NGrid, NGi, NModal, NTable, NRadioGroup, NRadioButton, NInputNumber, NInput, NTooltip
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { PieChart } from 'lucide-vue-next'
import { getFundHoldingPeriods, getFundHoldings, getFundHoldingRealtime, getFundHedgeExposure, getFundPenetration, getFundHoldingRecalc, getFundHoldingRecalcDetail, syncOilStatic, syncFuturesFreeze, getOilPriceFreshness, refetchOilPrices } from '../api'
import { formatPercent, priceColor } from '../utils'

const route = useRoute()
const router = useRouter()

const fundCode = computed(() => (route.query.code as string) || '')
const fundName = computed(() => (route.query.name as string) || '')
const currentPeriod = ref('')

const loading = ref(false)
const error = ref('')
const periods = ref<any[]>([])
const holdings = ref<any[]>([])
const regionDistribution = ref<any[]>([])
const prevPeriod = ref('')
const exited = ref<any[]>([])
const newIn = ref<any[]>([])
const reportDate = ref('')
const valuation = ref<any>(null)
// [AI-2026-09-17] 对冲穿透：底层 ETF 实际持有合约月 + 归一化 CL 对冲分布
const hedgeExposure = ref<any>(null)

// [AI-2026-09-15] 进页面自动同步 CL 三时点冻结价（从 ARM），每天只拉一次；
// 拉取失败弹出黄色报警，提示东哥检查 ARM 连接/采样。
const syncAlert = ref('')

// [AI-2026-09-15] 有效近月±1 三合约对比：动态合约列表来自后端 active_contracts。
// [AI-2026-09-17] UI 只显示底层实际持有的 MCL 可操作月份（权威=etf_contract_exposure 穿透配置）：
// 穿透证实底层 WTI 敞口已无 2610（USO 滚至 2611 100%、CRUD 2611/2612/2701），主连 2610 估值对对冲无意义 → 不显示。
// 无穿透配置的基金（161129/501018 暂无）退回显示全部 active_contracts；滚仓后改配置表即自动跟随，无需改代码。
const shownContracts = computed(() => {
  const list: string[] = valuation.value?.active_contracts || []
  const months = hedgeExposure.value?.wti_months as any[] | undefined
  if (months && months.length) {
    const ok = new Set(months.filter((m) => m.mcl_ok).map((m) => m.month as string))
    const filtered = list.filter((c) => ok.has(c))
    if (filtered.length) return filtered
  }
  return list
})
// [AI-2026-09-17] 对冲合约选项：WTI 直接对冲（2611/2612）+ Brent 同月 CL 跨品种对冲（2611/2701）。
// 选 Brent 月即代表用同月 CL 跨品种对冲，反算工具（读 cSel）同步覆盖。
const hedgeOptions = computed(() => {
  const wti = shownContracts.value.map((c: string) => ({
    label: `CL ${c}（${contractMonthLabel(c)} · WTI 直接）`,
    value: c,
  }))
  const brent = (hedgeExposure.value?.brent?.months || []).map((b: any) => ({
    label: `Brent ${b.month}（→CL${b.month} 同月）`,
    value: b.month,
  }))
  return [...wti, ...brent]
})
const hedgeContract = ref<string>('')
// 默认 2611（穿透显示当前 WTI 敞口主力月）；选中项被过滤掉时自动纠正
watch(shownContracts, (list: string[]) => {
  if (list.length && !list.includes(hedgeContract.value)) {
    hedgeContract.value = list.includes('2611') ? '2611' : list[0]
  }
}, { immediate: true })

/** 从 YYMM 取可读月份标签，如 '2610'→'10月', '2701'→'01月' */
function contractMonthLabel(yymm: string): string {
  if (!yymm || yymm.length < 4) return yymm
  const m = parseInt(yymm.slice(2), 10)
  return `${m}月`
}

/** 取某合约的估值对象 */
function cData(contract: string) {
  return valuation.value?.contracts?.[contract] || null
}
/** 当前选中合约的估值对象 */
const cSel = computed(() => cData(hedgeContract.value))
/** 所有非选中合约列表（用于灰字副行显示；同 shownContracts 口径，2610 不显示） */
const otherContracts = computed(() => {
  return shownContracts.value.filter((c: string) => c !== hedgeContract.value)
})
const penetrationData = ref<any>(null)
const penetrationReady = ref(false)

// [AI-2026-09-11] 持仓静态估值（季报持仓法全 USD 简化口径）
const recalcRows = ref<any[]>([])
const latestNav = ref<number | null>(null)
const latestNavDate = ref<string>('')
const recalcModalShow = ref(false)
// [AI-2026-09-23 B方案] 静态持仓估值"是否已从 ARM 同步到本地缓存"状态（读本地 holding_static_val）
const staticSynced = computed(() => recalcRows.value.length > 0)
const staticLatestDate = computed(() => recalcRows.value.length ? recalcRows.value[0].date : '')
const staticSyncLoading = ref(false)
const staticSyncMsg = ref('')

// [AI-2026-09-23 B方案] 持仓静态估值弹窗诊断：本地核心行（recalcRows）只含 date/nav/hsv/err，
// 诊断细节（etf_prices/fill_warning/note 等）由弹窗打开时按需从 ARM 取全量，按 date 合并后展示。
// 前端不直接 SSH 代理：/holding-recalc-detail 端点本机侧已代理到 ARM（只读）。
const recalcDetailMap = ref<Record<string, any>>({})
const recalcDetailLoading = ref(false)
// [AI-2026-09-24 方案A] 美股价未入库的「待补日」：后端按 us_clock 口径给出（只读，不落库）。
// 这些日不在 recalcRows（读库）里，以灰色行插回表格，避免"少一行"被误判为程序丢行。
const recalcPending = ref<any[]>([])
const recalcDisplayRows = computed(() => {
  const m = recalcDetailMap.value
  let base = recalcRows.value
  if (m && Object.keys(m).length) {
    base = recalcRows.value.map((r: any) => {
      const d = m[r.date]
      return d ? { ...r, ...d } : r
    })
  }
  if (!recalcPending.value.length) return base
  const pendRows = recalcPending.value.map((p: any) => ({
    date: p.date,
    official_nav: p.official_nav ?? null,
    holding_static_val: null,
    err_pct: null,
    err_bp: null,
    pending: true,
    note: p.message || `美股价未入库（美股时钟 ${p.us_clock}），该行待补`,
    fill_warning: false,
    carried_forward: false,
  }))
  return [...pendRows, ...base].sort((a: any, b: any) => (a.date < b.date ? 1 : -1))
})
const fetchRecalcDetail = async () => {
  recalcDetailLoading.value = true
  try {
    const r = await getFundHoldingRecalcDetail(fundCode.value, currentPeriod.value, '2026-07-01')
    if (r.data?.status === 'ok') {
      const rows: any[] = (r.data.data?.rows) || []
      const m: Record<string, any> = {}
      for (const row of rows) m[row.date] = row
      recalcDetailMap.value = m
    }
  } catch (e: any) {
    // 诊断细节取不到时静默降级：核心行仍可显示，仅展开明细/缺价标红缺失
    console.warn('recalc 诊断细节获取失败(降级):', e?.message || e)
  } finally {
    recalcDetailLoading.value = false
  }
}

// [AI-2026-09-23 B方案] 手动触发 本地←ARM 拉取原油三基金 holding_static_val（pull_oil_static_from_arm）
const syncStaticValuation = async () => {
  staticSyncLoading.value = true
  staticSyncMsg.value = ''
  try {
    const r = await syncOilStatic(fundCode.value)
    const d = r?.data?.data || r?.data
    if (r?.data?.status === 'ok' || d?.status === 'ok') {
      staticSyncMsg.value = `✅ ${d?.message || '同步完成'}`
      // 重新读取本地缓存（holding-recalc 读本地），刷新 最新净值 / 同步状态
      await loadData()
    } else {
      staticSyncMsg.value = `❌ ${d?.message || '同步失败'}`
    }
  } catch (e: any) {
    staticSyncMsg.value = `❌ 同步失败: ${e?.message || e}`
  } finally {
    staticSyncLoading.value = false
  }
}

// [AI-2026-09-24 东哥需求] ARM 美股价新鲜度检测 + 一键重抓推送闭环：
// 新浪凌晨收盘价未到（ARM 07:30 采集抓空）→ 本页提示 → 点按钮 → 本机重抓 → 推 ARM → ARM 重算 → 拉回。
const priceFresh = ref<any>(null)
const refetchLoading = ref(false)
const refetchMsg = ref('')

const checkPriceFreshness = async () => {
  try {
    const r = await getOilPriceFreshness()
    priceFresh.value = r?.data?.status === 'ok' ? (r.data.data || null) : null
  } catch (e: any) {
    // 非关键检测：失败静默，不打扰主流程
    priceFresh.value = null
  }
}

const refetchUsPrices = async () => {
  refetchLoading.value = true
  refetchMsg.value = ''
  try {
    const r = await refetchOilPrices()
    const d = r?.data?.data
    if (r?.data?.status === 'ok') {
      refetchMsg.value = `✅ ${d?.summary || '重抓并推送完成'}`
      await checkPriceFreshness()
      await loadData()
    } else {
      refetchMsg.value = `❌ ${d?.summary || r?.data?.message || '重抓失败'}`
    }
  } catch (e: any) {
    refetchMsg.value = `❌ 重抓失败: ${e?.message || e}`
  } finally {
    refetchLoading.value = false
  }
}

// [AI-2026-09-12] 持仓实时估值弹窗：核对 CL 三时点分母 + 实时 CL 价
const realtimeModalShow = ref(false)
const rtRefreshing = ref(false)
const openRealtimeModal = () => { realtimeModalShow.value = true }
const refreshRealtime = async () => {
  rtRefreshing.value = true
  try {
    const r = await getFundHoldingRealtime(fundCode.value)
    // error 也覆盖旧值，避免残留
    valuation.value = r?.data?.data || null
    // [AI-2026-09-18] 三基金对比弹窗若开着，随同一 20s 定时器同步刷新
    if (compareModalShow.value && compareContract.value) fetchCompareRows()
  } catch (e: any) {
    error.value = `刷新CL实时价失败: ${e?.message || e}`
  } finally {
    rtRefreshing.value = false
  }
}
// 弹窗打开期间每 20s 刷新一次 CL 实时价（新浪），关闭即停
let rtTimer: ReturnType<typeof setInterval> | null = null
watch(realtimeModalShow, (v) => {
  if (v) {
    refreshRealtime()
    rtTimer = setInterval(() => { refreshRealtime() }, 20000)
  } else if (rtTimer) {
    clearInterval(rtTimer)
    rtTimer = null
  }
})

// [AI-2026-09-15] 对冲手数 → 应买 LOF 份数：纯前端实时反算。
// 用当刻实时估值(realtime_nav) / 选中合约 CL 实时价(cl_now) / 中间价(fx_now, usd_cny_mid) / 季报篮子 β(valid_weight_sum)。
// 物理含义：LOF 每份油价敞口 = NAV × β(仓位)；1 张 MCL = 100 桶 WTI 敞口 = 100 × CL × fx(CNY)。
// 对冲平衡：shares × realtime_nav × β = n × 100 × cl_now × fx → shares = n×100×cl_now×fx / (realtime_nav × β)。
const mclLots = ref(1)
const lofSharesForMcl = computed(() => {
  const c = cSel.value
  if (!c || c.realtime_nav == null || c.valid_weight_sum == null || c.valid_weight_sum <= 0) return null
  const cl = c.cl_now
  const fx = c.fx_now
  if (cl == null || fx == null || fx <= 0) return null
  const shares = mclLots.value * 100 * cl * fx / (c.realtime_nav * c.valid_weight_sum)
  return Math.round(shares)
})
const lofMarketValueForMcl = computed(() => {
  const c = cSel.value
  if (lofSharesForMcl.value == null || !c || c.realtime_nav == null) return null
  return Math.round(lofSharesForMcl.value * c.realtime_nav)
})

// [AI-2026-09-17] 全合约对比（弹窗不再单选切换）：以下函数按合约 key 直接计算，不依赖选中。
// 合约 key 按 YYMM 数值排序（2611/2612/2701），保证展示顺序稳定。
const contractKeys = computed(() => {
  const ks = Object.keys(valuation.value?.contracts || {})
  return ks.sort((a: string, b: string) => parseInt(a) - parseInt(b))
})
const firstContract = computed(() => (contractKeys.value.length ? cData(contractKeys.value[0]) : null))
// Brent 同月 CL 合约集合（从穿透配置派生；用于对比表标注跨品种对冲）
const brentMonthSet = computed(() => new Set((hedgeExposure.value?.brent?.months || []).map((m: any) => m.month as string)))
/** 每合约：N 手 MCL → 应买 LOF 份数（用当刻估值/CL/汇率/β 实时算） */
function lofSharesForMclOf(contract: string): number | null {
  const c = cData(contract)
  if (!c || c.realtime_nav == null || c.valid_weight_sum == null || c.valid_weight_sum <= 0) return null
  const cl = c.cl_now, fx = c.fx_now
  if (cl == null || fx == null || fx <= 0) return null
  return Math.round(mclLots.value * 100 * cl * fx / (c.realtime_nav * c.valid_weight_sum))
}
/** 每合约：每 1 手 MCL → 应买 LOF 份数（mclLots=1，便于东哥 Excel 按任意手数乘） */
function lofSharesPerLot(contract: string): number | null {
  return perLotShares(cData(contract))
}
/** 每 1 手 MCL → 应买 LOF 份数（任意基金/合约通用；三基金对比弹窗复用） */
function perLotShares(c: any): number | null {
  if (!c || c.realtime_nav == null || c.valid_weight_sum == null || c.valid_weight_sum <= 0) return null
  const cl = c.cl_now, fx = c.fx_now
  if (cl == null || fx == null || fx <= 0) return null
  return Math.round(100 * cl * fx / (c.realtime_nav * c.valid_weight_sum))
}

// [AI-2026-09-21] 混合估值（WTI 动态加权）：用进阶对冲方案的真实月份占比，把 WTI 内部 2611/2612 比例误差抹平，更接近基金真实混合持仓 NAV。
// V_mix = Σ(weights[i]% × cData(months[i]).realtime_nav)；仅当 hedge_plan 存在且每个月都能取到估值时返回，否则 null（不兜底）。
const mixedValuation = computed<number | null>(() => {
  const hp = hedgeExposure.value?.hedge_plan
  if (!hp || !hp.months || !hp.weights || hp.months.length !== hp.weights.length) return null
  let sum = 0
  for (let i = 0; i < hp.months.length; i++) {
    const c = cData(hp.months[i])
    if (!c || c.realtime_nav == null) return null
    sum += (hp.weights[i] / 100) * c.realtime_nav
  }
  return sum
})
// 混合估值对应的实时持仓溢价（用同一 LOF 市价 firstContract.lof_price；与三合约行同口径）
const mixedPremium = computed<number | null>(() => {
  if (mixedValuation.value == null) return null
  const price = firstContract.value?.lof_price
  if (price == null || price <= 0) return null
  return price / mixedValuation.value - 1
})

// [AI-2026-09-18] 弹窗标题带实时现价（复用"实时ETF现价"卡的 lof_price/数据源；表格不动，只在标题后追加）
// [AI-2026-09-18] 现价段改蓝色醒目（东哥要求）：header 插槽渲染，现价段独立上色
const modalPriceSeg = computed(() => {
  const c = firstContract.value
  if (c?.lof_price == null) return null
  const src = lofSrcLabel(c.lof_price_source)
  return { price: c.lof_price.toFixed(3), src }
})

// [AI-2026-09-18] 三原油 LOF 同合约月套利对比（点对冲弹窗"对冲合约"列的合约名进入）。
// 赎回费口径（东哥 2026-09-18）：160723/501018 = 0.5%，161129 = 0.365%。
// 套利逻辑：市价买入 → 按 NAV 赎回，毛利 = |实时持仓溢价|，净利 = |溢价| − 赎回费 → 净折价 = 溢价 + 赎回费，越负越优。
const OIL_FUNDS = [
  { code: '160723', name: '嘉实原油', redeemFee: 0.005 },
  { code: '161129', name: '易方达原油', redeemFee: 0.00365 },
  { code: '501018', name: '南方原油', redeemFee: 0.005 },
]
const compareModalShow = ref(false)
const compareContract = ref('')
const compareLoading = ref(false)
const compareRows = ref<any[]>([])
const fetchCompareRows = async () => {
  compareLoading.value = true
  try {
    compareRows.value = await Promise.all(OIL_FUNDS.map(async (f) => {
      let data: any = null
      try {
        const r = await getFundHoldingRealtime(f.code)
        data = r?.data?.data?.contracts?.[compareContract.value] || null
      } catch { data = null }
      return { ...f, data }
    }))
  } finally { compareLoading.value = false }
}
const openCompareModal = (contract: string) => {
  compareContract.value = contract
  compareModalShow.value = true
  fetchCompareRows()
}
/** 净折价 = 实时持仓溢价 + 赎回费（负值 = 扣费后仍有折价空间） */
function cmpNet(row: any): number | null {
  return row?.data?.realtime_premium != null ? row.data.realtime_premium + row.redeemFee : null
}
/** 三基金中净折价最小（最优套利标的）的代码 */
const bestNetCode = computed(() => {
  let best: string | null = null
  let bestV = Infinity
  for (const r of compareRows.value) {
    const n = cmpNet(r)
    if (n != null && n < bestV) { bestV = n; best = r.code }
  }
  return best
})
// —— 对比弹窗展示 helper（吸收 TS 断言噪音）——
const cmpBeta = (c: any) => c?.valid_weight_sum != null ? (c.valid_weight_sum * 100).toFixed(2) + '%' : '-'
const cmpNav = (c: any) => c?.realtime_nav != null ? c.realtime_nav.toFixed(4) : '-'
const cmpPremium = (c: any) => c?.realtime_premium != null ? (c.realtime_premium * 100).toFixed(3) + '%' : '-'
const cmpPrice = (c: any) => c?.lof_price != null ? c.lof_price.toFixed(3) : '-'
// [AI-2026-09-23] LOF 价格来源标签：非交易时段腾讯返回的是最近收盘价，必须区分标"昨收"/"收盘(今日)"，避免把昨收误显成实时误导决策
const lofSrcLabel = (src: string | null | undefined) => {
  if (!src) return ''
  if (src === 'close') return '收盘(盘后)'
  if (src === '昨收') return '昨收'
  if (src === '收盘') return '收盘(今日)'
  return src.replace('realtime:', '')
}
const cmpPriceSrc = (c: any) => lofSrcLabel(c?.lof_price_source)
const cmpShares = (c: any) => { const s = perLotShares(c); return s != null ? s.toLocaleString() : '-' }
const cmpNetLabel = (row: any) => { const n = cmpNet(row); return n != null ? (n * 100).toFixed(3) + '%' : '-' }
/** 对比弹窗标题用：取三基金同一合约月的 CL 实时价（任一非空即可，三基金值相同） */
const compareClNow = computed(() => {
  for (const r of compareRows.value) {
    if (r?.data?.cl_now != null) return r.data.cl_now
  }
  return null
})

// [AI-2026-09-03] 地区列直接显示英文缩写（US/UK/HK…），与东哥口径一致
const regionLabel = (region: string) => region || '其他'

// 总权重
const totalWeight = computed(() => {
  return holdings.value.reduce((s: number, r: any) => s + (typeof r.weight === 'number' ? r.weight : 0), 0) * 100
})

// 穿透数据展示
const wtiPct = computed(() => {
  if (!penetrationData.value?.summary?.by_variety?.WTI) return 0
  return Number(penetrationData.value.summary.by_variety.WTI)
})
const brentPct = computed(() => {
  if (!penetrationData.value?.summary?.by_variety?.Brent) return 0
  return Number(penetrationData.value.summary.by_variety.Brent)
})
const penetratedPct = computed(() => {
  if (!penetrationData.value?.summary?.total_penetrated) return 0
  return Number(penetrationData.value.summary.total_penetrated)
})

// 跳转到穿透分析页
const goToPenetration = () => {
  if (!fundCode.value || !currentPeriod.value) return
  router.push({
    path: '/penetration',
    query: { fund_code: fundCode.value, period: currentPeriod.value }
  })
}

// [AI-2026-09-03] 持仓表合计行：前 6 列合并为"总权重"，权重列求和，市值列求和
const holdingSummary = (pageData: any[]) => {
  const w = pageData.reduce((s: number, r: any) => s + (typeof r.weight === 'number' ? r.weight : 0), 0)
  const mvVals = pageData.map((r: any) => r.market_value).filter((v: any) => typeof v === 'number')
  const mv = mvVals.length > 0 ? mvVals.reduce((a: number, b: number) => a + b, 0) : null
  return {
    display_order: { colSpan: 6, value: h('strong', '总权重') },
    market_value: { value: h('strong', mv != null ? Math.round(mv).toLocaleString() : '-') },
    weight: { value: h('strong', (w * 100).toFixed(2) + '%') },
  }
}

const holdingColumns: DataTableColumns<any> = [
  { title: '序号', key: 'display_order', width: 50, align: 'center' },
  { title: '代码', key: 'symbol', width: 80, align: 'center', render(row: any) {
    return h('span', { style: 'font-family: monospace; font-weight: 600;' }, row.symbol || '-')
  }},
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '地区', key: 'region', width: 80, align: 'center', render(row: any) {
    return regionLabel(row.region)
  }},
  { title: '货币', key: 'currency', width: 60, align: 'center' },
  { title: '管理人', key: 'manager', ellipsis: { tooltip: true }, render(row: any) {
    return row.manager || '-'
  }},
  { title: '市值(元)', key: 'market_value', width: 140, align: 'right', render(row: any) {
    return row.market_value != null ? Math.round(row.market_value).toLocaleString() : '-'
  }},
  { title: '权重', key: 'weight', width: 90, align: 'right', render(row: any) {
    return h('span', { style: 'font-weight: 600;' }, row.weight != null ? (row.weight * 100).toFixed(2) + '%' : '-')
  }},
  { title: '相比上期变动', key: 'change', width: 110, align: 'right', render(row: any) {
    if (row.prev_weight == null) return '-'
    const delta = (row.weight || 0) - row.prev_weight
    const sign = delta >= 0 ? '+' : ''
    // 红涨绿跌（中国股市惯例）
    const color = delta >= 0 ? '#dc2626' : '#16a34a'
    return h('span', { style: `font-weight: 600; color: ${color};` }, `${sign}${(delta * 100).toFixed(2)}%`)
  }},
]

// [AI-2026-09-11] 持仓静态估值弹窗表：列 = 日期 / 官方净值 / 静态估值 / 误差%，涨跌幅等移入展开行
// [AI-2026-09-15] 底层 ETF 明细不再写死 160723 篮子：每行从自身 etf_prev/etf_prices 取键
// （后端按各基金季报篮子逐只生成，顺序即持仓权重序），161129/501018 各显各的篮子。
const rowEtfSymbols = (row: any): string[] =>
  Array.from(new Set([...Object.keys(row.etf_prev || {}), ...Object.keys(row.etf_prices || {})]))

const recalcColumns: DataTableColumns<any> = [
  {
    type: 'expand',
    renderExpand: (row: any) => {
      // [AI-2026-09-24 方案A] 待补行无底层明细可展开，直接说明原因
      if (row.pending) {
        return h('div', { style: 'padding: 8px 12px; font-size: 12px; color: #92400e;' }, row.note || '美股价未入库，该行待补')
      }
      const items = rowEtfSymbols(row).map((s) => {
        const p0 = row.etf_prev?.[s]
        const p1 = row.etf_prices?.[s]
        const chg = (p0 != null && p1 != null && p0 > 0) ? (p1 / p0 - 1) * 100 : null
        return { s, p0, p1, chg }
      })
      return h('div', { style: 'padding: 8px 12px; font-size: 12px; color: #475569;' }, [
        h('div', { style: 'margin-bottom: 6px; font-weight: 600; color: #334155;' }, '底层 ETF 明细'),
        ...items.map((it) =>
          h('div', { style: 'display: flex; gap: 16px; padding: 2px 0;' }, [
            h('span', { style: 'width: 52px; font-weight: 600; color: #1e293b;' }, it.s),
            h('span', {}, `前日 ${it.p0 != null ? it.p0.toFixed(2) : '-'}`),
            h('span', {}, `当日 ${it.p1 != null ? it.p1.toFixed(2) : '-'}`),
            h('span', {
              style: `color: ${it.chg != null ? (it.chg >= 0 ? '#dc2626' : '#16a34a') : '#999'}; font-weight: 600;`,
            }, it.chg != null ? `${it.chg >= 0 ? '+' : ''}${it.chg.toFixed(2)}%` : '-'),
          ])
        ),
        h('div', { style: 'margin-top: 6px; color: #64748b;' }, `USD/CNY: ${row.usd_cny != null ? row.usd_cny.toFixed(4) : '-'}`),
        h('div', {
          style: `margin-top: 6px; font-weight: ${row.fill_warning || row.carried_forward ? 600 : 400}; color: ${row.fill_warning ? '#dc2626' : (row.carried_forward ? '#d97706' : '#64748b')};`,
        }, `备注: ${row.note || '数据齐全'}`),
      ])
    },
  },
  { title: '日期', key: 'date', width: 110, align: 'center' },
  { title: '官方净值', key: 'official_nav', width: 110, align: 'right', render(row: any) {
    return row.official_nav != null ? row.official_nav.toFixed(4) : '-'
  }},
  { title: '静态估值', key: 'holding_static_val', width: 110, align: 'right', render(row: any) {
    // [AI-2026-09-24 方案A] 美股价未入库的待补行：显式标「待补」，不留空让人误判丢行
    if (row.pending) return h('span', { style: 'color: #d97706; font-weight: 600;', title: row.note || '美股价未入库，该行待补' }, '待补')
    if (row.holding_static_val == null) return '-'
    const mark = row.fill_warning ? ' ⚠️' : (row.carried_forward ? ' 🔸' : '')
    return h('span', null, `${row.holding_static_val.toFixed(4)}${mark}`)
  }},
  { title: '误差%', key: 'err_pct', width: 100, align: 'right', render(row: any) {
    if (row.pending) return h('span', { style: 'color: #d97706;' }, '—')
    if (row.err_pct == null) {
      if (row.fill_warning) return h('span', { style: 'color: #dc2626; font-weight: 600;' }, '⚠️')
      if (row.carried_forward) return h('span', { style: 'color: #d97706; font-weight: 600;' }, '🔸')
      return '-'
    }
    const color = row.err_pct >= 0 ? '#dc2626' : '#16a34a'
    const mark = row.fill_warning ? ' ⚠️' : (row.carried_forward ? ' 🔸' : '')
    return h('span', { style: `font-weight: 600; color: ${color};` }, `${row.err_pct >= 0 ? '+' : ''}${row.err_pct.toFixed(2)}%${mark}`)
  }},
]

const openRecalcModal = async () => {
  if (recalcRows.value.length > 0) {
    recalcModalShow.value = true
    // 弹窗打开时按需取全量诊断（etf_prices/fill_warning/note），与本地核心行按 date 合并
    await fetchRecalcDetail()
  }
}

const loadPeriods = async () => {
  if (!fundCode.value) return
  try {
    const res = await getFundHoldingPeriods(fundCode.value)
    if (res.data?.status === 'ok') {
      periods.value = res.data.data || []
      // 默认选中最新一期；若 URL 已带 period 则优先
      const urlPeriod = route.query.period as string
      if (urlPeriod && periods.value.some((p: any) => p.period === urlPeriod)) {
        currentPeriod.value = urlPeriod
      } else if (periods.value.length > 0) {
        currentPeriod.value = periods.value[0].period
      }
    }
  } catch (e: any) {
    error.value = `获取报告期失败: ${e?.message || e}`
  }
}

const loadData = async () => {
  if (!fundCode.value || !currentPeriod.value) return
  loading.value = true
  error.value = ''
  // 切换基金/报告期时先清空旧估值，避免 freeze_incomplete 时残留上一个基金的显示
  valuation.value = null
  try {
    const [holdingsRes, valuationRes, penetrationRes, recalcRes, exposureRes] = await Promise.all([
      getFundHoldings(fundCode.value, currentPeriod.value),
      getFundHoldingRealtime(fundCode.value),
      getFundPenetration(fundCode.value, currentPeriod.value),
      getFundHoldingRecalc(fundCode.value, currentPeriod.value, '2026-07-01'),
      getFundHedgeExposure(fundCode.value),
    ])

    if (holdingsRes.data?.status === 'ok') {
      const d = holdingsRes.data.data || {}
      holdings.value = d.holdings || []
      regionDistribution.value = d.region_distribution || []
      prevPeriod.value = d.prev_period || ''
      exited.value = d.exited || []
      newIn.value = d.new_in || []
      reportDate.value = d.report_date || ''
    } else {
      error.value = holdingsRes.data?.message || '获取持仓失败'
    }

    // 无论 ok/error 都覆盖：error 时让旧值清空，避免切换基金后看到上一个基金的残留
    valuation.value = valuationRes.data?.data || null

    // [AI-2026-09-17] 对冲穿透（etf_contract_exposure）：底层 ETF 实际持有合约月
    hedgeExposure.value = exposureRes.data?.data || null

    if (penetrationRes.data?.status === 'ok') {
      penetrationData.value = penetrationRes.data.data || null
    } else if (penetrationRes.data?.fund_code) {
      // 穿透API直接返回数据（无status包装）
      penetrationData.value = penetrationRes.data || null
    } else {
      penetrationData.value = null
    }

    if (recalcRes.data?.status === 'ok') {
      const d = recalcRes.data.data || {}
      recalcRows.value = d.rows || []
      // [AI-2026-09-24 方案A] 待补日（美股价未入库）：随核心行一起刷新
      recalcPending.value = d.pending || []
      // 重新载入核心行后清空诊断 map（诊断细节仅在弹窗打开时按需取，避免陈旧合并）
      recalcDetailMap.value = {}
      // QDII 净值 T+2 公布：今天及最近未公布日 official_nav 为 null，
      // 取第一个 official_nav 非空的行作为"最新净值"
      const navRow = recalcRows.value.find((r: any) => r.official_nav != null)
      latestNav.value = navRow ? navRow.official_nav : null
      latestNavDate.value = navRow ? navRow.date : ''
    } else {
      recalcRows.value = []
      recalcPending.value = []
      recalcDetailMap.value = {}
      latestNav.value = null
      latestNavDate.value = ''
    }
  } catch (e: any) {
    error.value = `加载失败: ${e?.message || e}`
  } finally {
    loading.value = false
  }
  // [AI-2026-09-24 东哥需求] 加载完成后异步检测 ARM 美股价新鲜度（失败静默，不挡页面）
  void checkPriceFreshness()
}

const switchPeriod = (period: string) => {
  currentPeriod.value = period
  router.replace({ query: { ...route.query, period } })
  loadData()
}

watch(fundCode, () => {
  loadPeriods().then(() => loadData())
})

watch(currentPeriod, () => {
  if (currentPeriod.value) loadData()
})

// [AI-2026-09-15] 自动同步 CL 分母：每天仅一次（localStorage 记当天日期），失败报警。
const autoSyncFreeze = async () => {
  const todayKey = new Date().toISOString().slice(0, 10)
  const lsKey = `cl_freeze_synced_${fundCode.value}_${todayKey}`
  if (localStorage.getItem(lsKey) === 'ok') {
    syncAlert.value = ''  // 今日已成功同步，清报警
    return
  }
  try {
    await syncFuturesFreeze()
    localStorage.setItem(lsKey, 'ok')
    syncAlert.value = ''
  } catch (e: any) {
    syncAlert.value = `⚠️ CL 分母（从 ARM）同步失败：${e?.message || e}。请检查 ARM 连接与采样，刷新页面可重试。`
  }
}

onMounted(() => {
  autoSyncFreeze()  // 进页面先自动拉 CL 分母（每天一次）
  loadPeriods().then(() => loadData())
})
</script>

<style scoped>
.holding-analysis-page {
  padding: 12px;
  color: #1f2937;
}
.shadow-soft {
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  border-radius: 8px;
  border: 1px solid #e5edf7;
}
.stat-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e5edf7;
}
/* 非假期缺价前填行：整行淡红醒目提示，便于人工核实数据漏抓 */
:deep(.recalc-warn-row td) {
  background-color: #fef2f2 !important;
}
:deep(.recalc-warn-row:hover td) {
  background-color: #fee2e2 !important;
}
/* 合法前填/沿用上一交易日行：整行淡琥珀提示（区别于红色真缺价报警） */
:deep(.recalc-carry-row td) {
  background-color: #fffbeb !important;
}
:deep(.recalc-carry-row:hover td) {
  background-color: #fef3c7 !important;
}
/* [AI-2026-09-24 方案A] 美股价未入库的「待补日」行：淡灰斜体，明示该日尚未生成（非程序丢行） */
:deep(.recalc-pending-row td) {
  background-color: #f8fafc !important;
  color: #94a3b8 !important;
  font-style: italic;
}
:deep(.recalc-pending-row:hover td) {
  background-color: #f1f5f9 !important;
}
</style>
