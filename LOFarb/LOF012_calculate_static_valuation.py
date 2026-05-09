# -*- coding: utf-8 -*-
# 012_generate_lof_data.py - 纯享版静态估值计算器 (Pure DB-driven)
# 不再爬取任何数据，完全基于 SQLite 基础表进行数学推演，彻底抛弃 CSV

import os
import sys
import pandas as pd
import yaml
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arbcore.database.db_manager import DatabaseManager
from arbcore.calculators.static_valuation import StaticValuationCalculator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LofValuationApp:
    def __init__(self):
        self.db = DatabaseManager()
        self.config = self._load_config()
        self.calculator = StaticValuationCalculator(self.db)

    def diagnose_global_environment(self):
        """在开始计算前，先打印全局的汇率环境"""
        conn = self.db._get_conn()
        try:
            fx_df = pd.read_sql("SELECT date, usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 5", conn)
            logger.info("🌍 === [全局环境] 最近 5 个交易日的人民币中间价 ===")
            if fx_df.empty:
                logger.error("  ❌ 数据库中没有任何汇率记录！")
            for _, row in fx_df.iterrows():
                logger.info(f"    📅 {row['date']}: {row['usd_cny_mid']}")
            logger.info("==================================================")
        except Exception as e:
            pass
        finally:
            conn.close()

    def diagnose_fund(self, fund):
        """精准诊断底层数据缺失情况并输出详细日志"""
        code = str(fund.get('code', ''))
        name = fund.get('name', '')
        
        conn = self.db._get_conn()
        try:
            # 查找最近 3 个有净值的交易日
            nav_df = pd.read_sql(f"SELECT date, nav FROM fund_data WHERE fund_code='{code}' AND nav IS NOT NULL ORDER BY date DESC LIMIT 3", conn)
            if nav_df.empty:
                logger.error(f"  ❌ [诊断] {name}({code}): 数据库完全没有该基金的净值(nav)记录！")
                return

            logger.info(f"  🕵️ [数据探针] {name}({code}) 最近3个净值日的数据对齐情况:")
            for _, row in nav_df.iterrows():
                d = row['date']
                nav = row['nav']
                missing = []
                
                # 1. 查汇率
                fx = pd.read_sql(f"SELECT usd_cny_mid FROM exchange_rate WHERE date='{d}'", conn)
                if fx.empty or pd.isna(fx.iloc[0,0]) or float(fx.iloc[0,0]) <= 0:
                    missing.append("人民币中间价")
                    
                # 2. 查底层ETF
                etfs = [item['symbol'] for item in fund.get('valuation_portfolio', [])]
                for etf in etfs:
                    ep = pd.read_sql(f"SELECT price FROM usa_etf_daily_prices WHERE symbol='{etf}' AND date='{d}'", conn)
                    if ep.empty or pd.isna(ep.iloc[0,0]) or float(ep.iloc[0,0]) <= 0:
                        missing.append(f"ETF[{etf}]")
                
                if missing:
                    logger.warning(f"    ⚠️ {d} (NAV={nav}): 缺失 -> {', '.join(missing)}")
                else:
                    logger.info(f"    ✅ {d} (NAV={nav}): 底层数据齐备！")
        except Exception as e:
            pass
        finally:
            conn.close()

    def _load_config(self):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from arbcore.config.config_loader import load_config
        
        config_file = os.path.join(os.path.dirname(__file__), "lof_config.yaml")
        logger.info(f"📋 加载配置文件: {config_file}")
        return load_config(config_file)
            
    def pre_diagnose_fund(self, fund):
        """在计算前把该基金的仓位、净值、价格全透视打印出来"""
        code = str(fund.get('code', ''))
        name = fund.get('name', '')
        conn = self.db._get_conn()
        try:
            pos_df = pd.read_sql(f"SELECT date, position, nav as woody_nav FROM fund_factor WHERE fund_code='{code}' ORDER BY date DESC LIMIT 1", conn)
            pos_info = f"仓位={pos_df.iloc[0]['position']*100}% (Woody备份NAV={pos_df.iloc[0]['woody_nav']})" if not pos_df.empty else "仓位因子缺失"
            
            # 读取 fund_data，不管有没有 nav，直接把最近3天的原始记录全拉出来看
            raw_df = pd.read_sql(f"SELECT date, nav, price, premium FROM fund_data WHERE fund_code='{code}' ORDER BY date DESC LIMIT 3", conn)
            
            logger.info(f"  🔍 [盘前透视] {name}({code}) 基础信息: {pos_info}")
            if raw_df.empty:
                logger.error(f"      ❌ fund_data 表完全空白，没有任何收盘价或净值！")
            for i, row in raw_df.iterrows():
                logger.info(f"      📍 日期: {row['date']} | 净值(nav)={row['nav']} | 收盘价(price)={row['price']} | 溢价(premium)={row['premium']}")
        except Exception as e:
            pass
        finally:
            conn.close()

    def run(self):
        logger.info("🚀 开始执行全市场静态估值计算 (SQLite纯享版)...")
        self.diagnose_global_environment()
        
        funds = self.config.get('funds', [])
        for fund in funds:
            # 核心格式对齐修复：将 YAML 配置文件里的变种 ETF 自动补齐 ^ 前缀，确保与数据库的存储格式完全匹配
            for port_type in ['valuation_portfolio', 'hedging_portfolio', 'holdings_portfolio']:
                for item in fund.get(port_type, []):
                    sym = item.get('symbol', '')
                    if isinstance(sym, str) and ('-JP' in sym or '-EU' in sym or '-HK' in sym) and not sym.startswith('^'):
                        item['symbol'] = f"^{sym}"
                        
            try:
                self.pre_diagnose_fund(fund)
                self.calculator.process_fund(fund)
                # 无论是否成功，追加执行强力诊断探针，让缺失数据无所遁形
                self.diagnose_fund(fund)
            except Exception as e:
                logger.error(f"❌ 处理基金 {fund.get('code')} 时出错: {e}")
                import traceback
                traceback.print_exc()
                
        # 强制启动数据库去重，防止底层 append 重复写入导致 03 前台崩溃
        self.clean_duplicate_db()
        logger.info("🎉 静态估值计算流水线全部完成！")

    def clean_duplicate_db(self):
        conn = self.db._get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fund_history_%'")
            for (table,) in cursor.fetchall():
                cursor.execute(f"DELETE FROM {table} WHERE rowid NOT IN (SELECT MAX(rowid) FROM {table} GROUP BY date)")
            conn.commit()
            logger.info("🧹 已自动执行底层表冗余数据清理。")
        except Exception as e:
            logger.warning(f"清理重复数据失败: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    LofValuationApp().run()
