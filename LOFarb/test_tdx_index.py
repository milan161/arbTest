# test_tdx_index.py - 单独测试通达信API获取指数行情
import os
import sys
import time

# 将项目根目录添加到系统路径，以便导入现有的 readers 模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

try:
    from readers.trade_manager import TradeManager
except ImportError:
    print("❌ 无法导入 TradeManager，请确保该脚本放在 LOFarb 目录下。")
    sys.exit(1)

try:
    from futu import OpenQuoteContext, SubType, Session
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

def test_index_prices():
    print("⚙️ 正在初始化 TradeManager (通达信新版接口)...")
    trade_manager = TradeManager()
    
    if not trade_manager.tdx_available:
        print("❌ 通达信新版接口 (TDX) 未就绪，请检查通达信客户端或 qmt/xtquant 是否已启动！")
        return
        
    tq = trade_manager.tq
    try:
        tq.initialize(__file__)
        print("✅ 通达信接口挂载成功！\n")
    except Exception as e:
        print(f"❌ 通达信初始化失败: {e}")
        return

    # 准备测试的指数代码字典 (键为代码，值为名称说明)
    # 注意：请根据你底层使用的 pytdx 或 xtquant 的格式要求，可能需要调整后缀
    index_dict = {
        # ====== A股指数 ======
        "399998.SZ": "中证煤炭",
        "399300.SZ": "沪深300(深)",
        "399330.SZ": "深证100",
        "399001.SZ": "深证成指",
        "399417.SZ": "新能源车",
        "399989.SZ": "中证医疗",
        "399707.SZ": "CS地产",
        "399807.SZ": "高铁产业",
        "399803.SZ": "工业4.0",
        "399987.SZ": "中证酒",
        "399441.SZ": "生物医药",
        "399809.SZ": "保险主题",
        "399997.SZ": "中证白酒",
        "000922.CSI": "中证红利",
        "000979.CSI": "大宗商品",
        "000961.CSI": "中证能源",
        "000905.SH": "中证500",
        "000869.SH": "中证动漫",
        # ====== 中证指数 ======
        "H30094.CSI": "H30094",
        "950090.CSI": "950090",
        "930713.CSI": "930713",
        "930875.CSI": "930875",
        "930720.CSI": "930720",
        "930997.CSI": "930997",
        "CES300.HI":  "CES300.HI",
        "H11136.CSI": "H11136",
        "930914.CSI": "930914",
        "930917.CSI": "930917",
        # ====== 港股指数 ======
        "HSI.HK":    "恒生指数(HSI)",
        "HSCI.HK":   "恒生综合(HSCI)",
        "HSMI.HK":   "恒生中型(HSMI)",
        "HSCEI.HK":  "恒生国企(HSCEI)",
        "HSCCI.HK":  "恒生红筹(HSCCI)",
        "HSSCNE.HK": "HSSCNE",
        "HSSI.HK":   "恒生小型(HSSI)",
        ".SPHCMSHP": "SPHCMSHP"
    }
    
    print(f"{'时间':<12} | {'代码':<15} | {'名称':<18} | {'最新价':>10} | {'涨跌幅':>8}")
    print("-" * 75)
    
    for code, name in index_dict.items():
        try:
            # 传 field_list=[] 以获取完整五档/快照数据，与你的主程序保持一致
            snap = tq.get_market_snapshot(stock_code=code, field_list=[])
            
            if snap:
                # 通达信或 QMT 接口返回的最新价可能是 'Now' 或 'lastPrice'
                now_price = float(snap.get('Now', snap.get('lastPrice', snap.get('last_price', 0))))
                # 昨收价，增加 Close 作为兜底
                pre_close = float(snap.get('PreClose', snap.get('lastClose', snap.get('pre_close', snap.get('Close', 0)))))
                
                change_str = "      -"
                # 如果能拿到有效的昨收价，并且最新价和昨收价不完全相等（排除服务器敷衍填充的情况）
                if pre_close > 0 and now_price > 0 and pre_close != now_price:
                    change_pct = (now_price / pre_close - 1) * 100
                    change_str = f"{change_pct:>7.2f}%"
                elif now_price > 0 and pre_close == now_price:
                    # 如果前后价格一样，但确实有价格，标记为 0.00%
                    change_str = "  0.00%"
                
                # 打印结果
                time_str = time.strftime('%H:%M:%S')
                print(f"[{time_str}] | {code:<15} | {name:<18} | {now_price:>10.2f} | {change_str}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] | {code:<15} | {name:<18} | {'无数据':>10} | {'-':>8}")
                
        except Exception as e:
            print(f"获取 {code} 数据时报错/被拦截: {e}")
            
    print("-" * 75)
    
    # 清理并释放资源
    try:
        tq.close()
        print("\n✅ 测试结束，通达信接口连接已断开。")
    except:
        pass

def test_futu_hk_indices():
    if not FUTU_AVAILABLE:
        print("\n❌ 未安装 futu-api，跳过富途港股指数测试。")
        return
        
    print("\n⚙️ 正在初始化 富途 OpenD 接口 (获取港股指数)...")
    try:
        # 禁用富途底层日志刷屏
        import futu
        futu.SysConfig.set_client_info('LOFarb')
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    except Exception as e:
        print(f"❌ 连接富途 OpenD 失败: {e}")
        return
        
    # 富途的港股指数使用的是专用的数字代码
    hk_indices = {
        "HK.800000": "恒生指数(HSI)",
        "HK.800100": "恒生国企(HSCEI)",
        "HK.800152": "恒生红筹(HSCCI)", 
        "HK.800700": "恒生科技(HSTECH)",
        "HK.800151": "恒生综合(HSCI)"
    }
    
    print(f"{'时间':<12} | {'代码':<15} | {'名称':<18} | {'最新价':>10} | {'涨跌幅':>8}")
    print("-" * 75)
    
    codes = list(hk_indices.keys())
    ret, data = ctx.get_stock_quote(codes)
    
    if ret == 0:
        for _, row in data.iterrows():
            code = row['code']
            name = hk_indices.get(code, code)
            last_price = float(row['last_price'])
            change_pct = float(row['amplitude']) if 'amplitude' in row else 0.0
            time_str = time.strftime('%H:%M:%S')
            print(f"[{time_str}] | {code:<15} | {name:<18} | {last_price:>10.2f} | {change_pct:>7.2f}%")
    else:
        print(f"❌ 获取富途数据失败: {data}")
        
    ctx.close()
    print("-" * 75)
    print("✅ 富途港股指数测试结束。\n")

if __name__ == "__main__":
    test_index_prices()
    time.sleep(1)
    test_futu_hk_indices()
