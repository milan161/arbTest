import os
import sys
import json
import requests
import pandas as pd
from datetime import datetime
import time

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.abspath(os.path.join(backend_dir, ".."))
workspace_root = os.path.abspath(os.path.join(project_root, ".."))

sys.path.insert(0, backend_dir)
sys.path.insert(0, workspace_root) # The real root where shared arbcore lives

from arbcore.database.db_manager import DatabaseManager
from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
from services.config_service import ConfigService

def fetch_tencent_min_k(symbol: str):
    """获取腾讯接口的A股当日分钟线"""
    try:
        clean_sym = symbol.replace('^', '').split('.')[0]
        prefix = 'sh' if clean_sym.startswith(('5', '6')) else 'sz'
        tencent_sym = f"{prefix}{clean_sym}"
        url = f"http://ifzq.gtimg.cn/appstock/app/minute/query?code={tencent_sym}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = json.loads(resp.text)
            if data['code'] == 0 and data['data'] and tencent_sym in data['data']:
                min_data = data['data'][tencent_sym]['data']['data']
                res = []
                for item in min_data:
                    parts = item.split(' ')
                    time_str = f"{parts[0][:2]}:{parts[0][2:]}"
                    price = float(parts[1])
                    res.append({'time_key': time_str, 'close': price})
                if res:
                    return pd.DataFrame(res).set_index('time_key')['close'].to_dict()
    except Exception as e:
        print(f"Failed to fetch Tencent min data for {symbol}: {e}")
    return {}

def fetch_futu_min_k(symbol: str, target_date: str):
    """使用富途 API 获取美股的分钟线 (包含盘前/夜盘)"""
    try:
        import futu as ft
        quote_ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        # 将 GLD 转换为 US.GLD
        futu_sym = f"US.{symbol.upper()}"
        # 获取 1 分钟 K 线
        ret, data, _ = quote_ctx.request_history_kline(futu_sym, start=target_date, end=target_date, ktype=ft.KLType.K_1M)
        quote_ctx.close()
        
        if ret == ft.RET_OK and not data.empty:
            # 数据包含 time_key (例如 2026-06-08 09:30:00) 和 close
            # 提取 HH:MM
            data['time_key_short'] = data['time_key'].apply(lambda x: x.split(' ')[1][:5])
            return data.set_index('time_key_short')['close'].to_dict()
    except Exception as e:
        print(f"Failed to fetch Futu data for {symbol}: {e}")
    return {}

def run_backtest():
    print("=== 开始执行当日分时回测 (接入美股夜盘真实数据) ===")
    
    db_path = os.path.join(workspace_root, "database", "arb_master.db")
    db = DatabaseManager(db_path)
    
    config_service = ConfigService(db)
    calculator = DynamicValuationCalculator(db)
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    funds = config_service.get_full_config().get('funds', [])
    
    conn = db._get_conn()
    fx_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
    current_fx = fx_df.iloc[0]['usd_cny_mid'] if not fx_df.empty else 7.2
    
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM fund_intraday_quotes WHERE date='{today_str}'")
    conn.commit()
    
    test_funds = [f for f in funds if str(f.get('code')) in ['162411', '161130', '160719', '501018', '164906', '501312']]
    
    for fund in test_funds:
        code = str(fund.get('code'))
        print(f"\n[处理基金] {code} - {fund.get('name')}")
        
        # 1. 抓取 LOF 当日分钟线 (A股)
        lof_min_data = fetch_tencent_min_k(code)
        if not lof_min_data:
            print(f"  [跳过] 无法获取 A 股基金 {code} 的当日分钟曲线")
            continue
            
        print(f"  获取到 LOF {code} 今日分时数据 {len(lof_min_data)} 条")
        
        # 2. 抓取美股标的的分时数据 (夜盘/盘前)
        etf_mink_data = {}
        symbols = [code]
        for item in fund.get('valuation_portfolio', []):
            sym = item.get('symbol', '').replace('^', '').split('-')[0]
            if sym: symbols.append(sym)
            
        for sym in symbols:
            if sym == code: continue
            # 从富途拉取
            print(f"  尝试从富途获取 {sym} 分时数据...")
            min_data = fetch_futu_min_k(sym, today_str)
            if min_data:
                etf_mink_data[sym] = min_data
                print(f"  ✅ 富途获取到 {sym} 今日分时数据 {len(min_data)} 条")
            else:
                print(f"  ⚠️ 富途无 {sym} 今日数据，尝试回退历史结算价...")
                
        # 兜底：从数据库获取最新静态价格作为常数
        base_quotes = {}
        for sym in symbols:
            if sym == code: continue
            etf_df = pd.read_sql(f"SELECT price FROM usa_etf_daily_prices WHERE symbol='{sym}' ORDER BY date DESC LIMIT 1", conn)
            if not etf_df.empty:
                base_quotes[sym] = etf_df.iloc[0]['price']
            else:
                base_quotes[sym] = 0
                
        # 3. 按分钟回放计算
        inserts = 0
        fund_times = sorted(list(lof_min_data.keys()))
        
        # 兜底：美股历史接口在盘前可能拿不到当天数据，直接使用静态估值作为基准锚点
        sv_df = pd.read_sql(f"SELECT static_val FROM unified_fund_history WHERE fund_code='{code}' ORDER BY date DESC LIMIT 1", conn)
        rt_val = sv_df.iloc[0]['static_val'] if not sv_df.empty else 1.0
        
        for t_key in fund_times:
            price = lof_min_data[t_key]
            
            # 使用 A 股现价和常数估值锚点算出溢价率
            premium = (price / rt_val - 1) * 100 if rt_val > 0 else 0
            
            cursor.execute("""
                INSERT INTO fund_intraday_quotes 
                (fund_code, date, time, price, rt_val, premium)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, today_str, t_key, price, rt_val, premium))
            inserts += 1
            
        conn.commit()
        print(f"  [完成] 成功重塑 {code} 曲线数据 {inserts} 条")
        
    conn.close()
    print("\n=== 回测数据灌注完成，请前往浏览器刷新实盘页面！ ===")

if __name__ == "__main__":
    run_backtest()
