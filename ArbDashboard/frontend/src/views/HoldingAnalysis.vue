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
            <n-button size="small" :loading="usaSyncLoading" @click="syncUsaEtfData">同步美股ETF日K（从ARM）</n-button>
            <span v-if="usaSyncMsg" :style="{ fontSize: '12px', color: usaSyncMsg.startsWith('⚠️') ? '#dc2626' : '#64748b' }">{{ usaSyncMsg }}</span>
            <span style="font-size: 12px; color: #64748b;">报告期:</span>
            <n-button
              v-for="p in periods"
              :key="p.period"
              size="small"
              :type="currentPeriod === p.period ? 'primary' : 'default'"
              :ghost="currentPeriod !== p.period"
              :style="currentPeriod === p.period ? { background: '#2563eb', borderColor: '#2563eb', color: '#fff' } : {}"
              @click="switchPeriod(p.period)"
            >
              {{ p.period }}
            </n-button>
          </div>
        </div>
      </template>

      <n-alert v-if="syncAlert" type="warning" :show-icon="true" style="margin-bottom: 12px;">
        {{ syncAlert }}
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
          <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap;">
            <span style="font-size: 12px; color: #64748b;">对冲合约：</span>
            <n-radio-group v-model:value="hedgeContract" size="small">
              <n-radio-button v-for="opt in hedgeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio-button>
            </n-radio-group>
            <span style="font-size: 11px; color: #94a3b8;">选择用于对冲/对比的 CL 合约（近月 / +1 / +2），多合约估值同步显示便于对比精度</span>
          </div>
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
                {{ cSel && cSel.lof_price_source === 'close' ? '收盘(盘后)' : (cSel && cSel.lof_price_source ? cSel.lof_price_source.replace('realtime:', '') : '') }}
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
            <div style="font-size: 14px; font-weight: bold;">前十大持仓</div>
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
      <n-data-table
        v-if="recalcRows.length"
        :columns="recalcColumns"
        :data="recalcRows"
        :pagination="{ pageSize: 15 }"
        :row-class-name="(row: any) => (row.fill_warning ? 'recalc-warn-row' : '')"
        size="small"
        bordered
      />
      <n-empty v-else description="该基金暂无持仓静态估值数据" />
    </n-modal>

    <!-- 持仓实时估值 - CL 分母核对弹窗 -->
    <n-modal
      v-model:show="realtimeModalShow"
      preset="card"
      :title="fundCode + ' 对冲（CL ' + (cSel?.contract || hedgeContract || '') + ' · ' + contractMonthLabel(cSel?.contract || hedgeContract || '') + '）'"
      style="width: 720px; max-width: 92vw;"
    >
      <div v-if="valuation" style="font-size: 13px;">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px;">
          <span style="font-size: 12px; color: #64748b;">查看合约：</span>
          <n-radio-group v-model:value="hedgeContract" size="small">
            <n-radio-button v-for="opt in hedgeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</n-radio-button>
          </n-radio-group>
        </div>
        <!-- 基准日期 + 当前 CL 实时价 + 冻结采样日 -->
        <n-grid :cols="24" :x-gap="12" :y-gap="10" style="margin-bottom: 12px;">
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">基准日（CL采样日）</div>
            <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ cSel?.base_date || cSel?.freeze_trade_date || '-' }}</div>
          </n-gi>
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">当前 CL 实时价（{{ cSel?.cl_contract_name || '' }}）</div>
            <div style="font-size: 16px; font-weight: bold; color: #2563eb;">{{ cSel?.cl_now != null ? cSel.cl_now.toFixed(3) : '-' }}</div>
            <div style="font-size: 10px; color: #94a3b8;">{{ cSel?.cl_time || '' }}</div>
          </n-gi>
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">基准静态估值（holding_static_val）</div>
            <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ cSel?.base_nav != null ? cSel.base_nav.toFixed(4) : '-' }}</div>
          </n-gi>
        </n-grid>

        <!-- [AI-2026-09-15] 实时估值（选中合约月）+ MCL→LOF 反算：置于 CL 三时点冻结价之前 -->
        <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">实时估值与对冲手数反算（CL {{ cSel?.cl_contract_name || '' }}）</div>
        <n-grid :cols="24" :x-gap="12" :y-gap="10" style="margin-bottom: 10px;">
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">实时估值（{{ contractMonthLabel(cSel?.contract || '') }}）</div>
            <div style="font-size: 20px; font-weight: bold; color: #2563eb;">{{ cSel?.realtime_nav != null ? cSel.realtime_nav.toFixed(4) : '-' }}</div>
            <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">持仓估值法（季报真实篮子）</div>
          </n-gi>
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">篮子油价权重 β（仓位）</div>
            <div style="font-size: 20px; font-weight: bold; color: #1e293b;">{{ cSel?.valid_weight_sum != null ? (cSel.valid_weight_sum * 100).toFixed(2) + '%' : '-' }}</div>
            <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">油价敞口占比</div>
          </n-gi>
          <n-gi :span="8">
            <div style="font-size: 12px; color: #64748b;">CL 实时价（{{ cSel?.contract || '' }}）</div>
            <div style="font-size: 20px; font-weight: bold; color: #1e293b;">{{ cSel?.cl_now != null ? cSel.cl_now.toFixed(3) : '-' }}</div>
            <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">{{ cSel?.cl_time || '' }}</div>
          </n-gi>
        </n-grid>

        <!-- MCL 手数 → 反算应买 LOF 份数（纯前端，用当刻估值/CL/汇率/β 实时算） -->
        <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">对冲手数 → 应买 LOF 份数（实时反算）</div>
        <n-grid :cols="24" :x-gap="12" :y-gap="10" style="margin-bottom: 8px;">
          <n-gi :span="6">
            <div style="font-size: 12px; color: #64748b;">做空 MCL 手数</div>
            <n-input-number v-model:value="mclLots" :min="0" :step="1" size="small" style="width: 100%;" />
          </n-gi>
          <n-gi :span="9">
            <div style="font-size: 12px; color: #64748b;">应买入 {{ fundCode }} 份数（{{ cSel?.contract || '' }} 对冲）</div>
            <div style="font-size: 20px; font-weight: bold; color: #16a34a;">{{ lofSharesForMcl != null ? lofSharesForMcl.toLocaleString() : '-' }}</div>
            <div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">1 张 MCL = 100 桶 WTI</div>
          </n-gi>
          <n-gi :span="9">
            <div style="font-size: 12px; color: #64748b;">对应 LOF 市值（@实时估值）</div>
            <div style="font-size: 20px; font-weight: bold; color: #1e293b;">{{ lofMarketValueForMcl != null ? '¥' + lofMarketValueForMcl.toLocaleString() : '-' }}</div>
          </n-gi>
        </n-grid>
        <div style="font-size: 11px; color: #94a3b8; margin-bottom: 12px;">
          公式：份数 = MCL手数 × 100桶 × CL实时价 × 中间价(usd_cny_mid) ÷ (实时估值 × β)。用当刻实时估值 / CL{{ cSel?.contract || '' }} 实时价 / 中间价(usd_cny_mid) / 季报篮子 β 实时计算，下单前零手算偏差。
        </div>

        <!-- 三时点 CL 冻结价（ARM 采样，分母） -->
        <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">CL 三时点冻结价（ARM 采样，分母 · {{ cSel?.cl_contract_name || '' }}）</div>
        <n-table :single-line="false" size="small" style="margin-bottom: 12px;">
          <thead>
            <tr><th>时点(NY)</th><th>价格</th><th>采样日</th></tr>
          </thead>
          <tbody>
            <tr v-for="pt in ['1130', '1430', '1600']" :key="pt">
              <td>{{ pt }}</td>
              <td>{{ cSel && cSel.freeze_points && cSel.freeze_points[pt] ? cSel.freeze_points[pt].price : '-' }}</td>
              <td>{{ cSel && cSel.freeze_points && cSel.freeze_points[pt] ? cSel.freeze_points[pt].trade_date : '-' }}</td>
            </tr>
          </tbody>
        </n-table>

        <!-- 各底层标的贡献明细 -->
        <div style="font-size: 13px; font-weight: bold; margin: 8px 0 6px;">各底层标的贡献明细（便于手动核对 · {{ cSel?.cl_contract_name || '' }}）</div>
        <n-table :single-line="false" size="small" style="margin-bottom: 12px;">
          <thead>
            <tr><th>标的</th><th>权重%</th><th>时点</th><th>冻结价</th><th>CL实时</th><th>涨跌</th><th>贡献</th></tr>
          </thead>
          <tbody>
            <tr v-for="(c, i) in (cSel?.components || [])" :key="i">
              <td>{{ c.symbol }}</td>
              <td>{{ c.weight_pct }}</td>
              <td>{{ c.point }}</td>
              <td>{{ c.freeze_price != null ? c.freeze_price : '-' }}</td>
              <td>{{ c.cl_now != null ? c.cl_now : '-' }}</td>
              <td :style="{ color: priceColor((c.ratio || 0) * 100) }">{{ c.ratio != null ? formatPercent(c.ratio * 100, 2) : '-' }}</td>
              <td>{{ c.contrib != null ? c.contrib.toFixed(4) : '-' }}</td>
            </tr>
          </tbody>
        </n-table>

        <!-- FX 实时 -->
        <div style="font-size: 12px; color: #64748b; margin-bottom: 10px;">
          汇率实时(腾讯·中间价 usd_cny_mid): {{ cSel?.fx_now != null ? cSel.fx_now.toFixed(4) : '-' }} ｜
          汇率基准: {{ cSel?.fx_point != null ? cSel.fx_point.toFixed(4) : '-' }} ｜
          状态: {{ cSel?.fx_status }}
        </div>
        <div style="font-size: 11px; color: #94a3b8; margin-bottom: 10px;">
          注：hf_CL{合约YYMM} 为指定月份 WTI 合约（近月/+1/+2），与 ARM 三时点冻结采样合约一致；切换上方"对冲合约"可对比各合约估值精度。CL 实时价弹窗打开期间每 20 秒自动刷新，关闭即停。
        </div>
      </div>
      <n-empty v-else description="暂无实时估值数据（进入页面会自动从 ARM 同步 CL 分母，若失败顶部会报警）" />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NTag, NIcon, NEmpty, NSpin, NButton, NDataTable, NGrid, NGi, NModal, NTable, NRadioGroup, NRadioButton, NInputNumber
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { PieChart } from 'lucide-vue-next'
import { getFundHoldingPeriods, getFundHoldings, getFundHoldingRealtime, getFundPenetration, getFundHoldingRecalc, syncFuturesFreeze, syncUsaEtf } from '../api'
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

// [AI-2026-09-15] 进页面自动同步 CL 三时点冻结价（从 ARM），每天只拉一次；
// 拉取失败弹出黄色报警，提示东哥检查 ARM 连接/采样。
const syncAlert = ref('')

// [AI-2026-09-15] 有效近月±1 三合约对比：动态合约列表来自后端 active_contracts。
// 规则：近月=当月+1（USO 持次月合约），如 9 月 → [2610,2611,2612]。
const hedgeOptions = computed(() => {
  const list = valuation.value?.active_contracts || []
  return list.map((c: string) => ({
    label: `CL ${c}（${contractMonthLabel(c)}）`,
    value: c,
  }))
})
const hedgeContract = ref<string>('')
// 当后端返回时自动设默认值（首个=当前近月）
watch(() => valuation.value?.active_contracts, (list: string[] | undefined) => {
  if (list && list.length > 0 && !hedgeContract.value) {
    hedgeContract.value = list[0]
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
/** 所有非选中合约列表（用于灰字副行显示） */
const otherContracts = computed(() => {
  return (valuation.value?.active_contracts || []).filter((c: string) => c !== hedgeContract.value)
})
const penetrationData = ref<any>(null)
const penetrationReady = ref(false)

// [AI-2026-09-11] 持仓静态估值（季报持仓法全 USD 简化口径）
const recalcRows = ref<any[]>([])
const latestNav = ref<number | null>(null)
const latestNavDate = ref<string>('')
const recalcModalShow = ref(false)

// [AI-2026-09-12] 美股/伦敦/港股 ETF 日 K：从 ARM 拉全表到本地（手动触发；本地非每日运行）
const usaSyncLoading = ref(false)
const usaSyncMsg = ref('')
const syncUsaEtfData = async () => {
  usaSyncLoading.value = true
  usaSyncMsg.value = ''
  try {
    const r = await syncUsaEtf()
    const d = r?.data?.data || r?.data
    if (r?.data?.status === 'ok' || d?.status === 'ok') {
      const missing: string[] = d?.fallback?.still_missing || []
      usaSyncMsg.value = missing.length ? `⚠️ ${d?.message || '同步完成'}` : `✅ ${d?.message || '同步完成'}`
      await loadData()
    } else {
      usaSyncMsg.value = `❌ ${d?.message || '同步失败'}`
    }
  } catch (e: any) {
    usaSyncMsg.value = `❌ 同步失败: ${e?.message || e}`
  } finally {
    usaSyncLoading.value = false
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
          style: `margin-top: 6px; font-weight: ${row.fill_warning ? 600 : 400}; color: ${row.fill_warning ? '#dc2626' : '#64748b'};`,
        }, `备注: ${row.note || '数据齐全'}`),
      ])
    },
  },
  { title: '日期', key: 'date', width: 110, align: 'center' },
  { title: '官方净值', key: 'official_nav', width: 110, align: 'right', render(row: any) {
    return row.official_nav != null ? row.official_nav.toFixed(4) : '-'
  }},
  { title: '静态估值', key: 'holding_static_val', width: 110, align: 'right', render(row: any) {
    if (row.holding_static_val == null) return '-'
    const warn = row.fill_warning ? ' ⚠️' : ''
    return h('span', null, `${row.holding_static_val.toFixed(4)}${warn}`)
  }},
  { title: '误差%', key: 'err_pct', width: 100, align: 'right', render(row: any) {
    if (row.err_pct == null) return row.fill_warning ? h('span', { style: 'color: #dc2626; font-weight: 600;' }, '⚠️') : '-'
    const color = row.err_pct >= 0 ? '#dc2626' : '#16a34a'
    const warn = row.fill_warning ? ' ⚠️' : ''
    return h('span', { style: `font-weight: 600; color: ${color};` }, `${row.err_pct >= 0 ? '+' : ''}${row.err_pct.toFixed(2)}%${warn}`)
  }},
]

const openRecalcModal = () => {
  if (recalcRows.value.length > 0) recalcModalShow.value = true
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
    const [holdingsRes, valuationRes, penetrationRes, recalcRes] = await Promise.all([
      getFundHoldings(fundCode.value, currentPeriod.value),
      getFundHoldingRealtime(fundCode.value),
      getFundPenetration(fundCode.value, currentPeriod.value),
      getFundHoldingRecalc(fundCode.value, currentPeriod.value, '2026-07-01'),
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
      // QDII 净值 T+2 公布：今天及最近未公布日 official_nav 为 null，
      // 取第一个 official_nav 非空的行作为"最新净值"
      const navRow = recalcRows.value.find((r: any) => r.official_nav != null)
      latestNav.value = navRow ? navRow.official_nav : null
      latestNavDate.value = navRow ? navRow.date : ''
    } else {
      recalcRows.value = []
      latestNav.value = null
      latestNavDate.value = ''
    }
  } catch (e: any) {
    error.value = `加载失败: ${e?.message || e}`
  } finally {
    loading.value = false
  }
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
</style>
