# -*- coding: utf-8 -*-
# LOF_cloud_siphon.py - 部署在云端 VPS 上的轻量化数据采集器
import os
import json
import time
import logging
import argparse
from datetime import datetime
import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("CloudSiphon")

def fetch_woody_api(symbols_str, bot_token):
    url = f"https://palmmicro.com/php/telegram.php?token={bot_token}"
    payload = {
        'update_id': 886050244,
        'message': {
            'message_id': 6620,
            'from': {'id': 992671436, 'is_bot': False, 'first_name': 'woody', 'username': 'palmmicro'},
            'chat': {'id': 992671436, 'first_name': 'woody', 'username': 'palmmicro', 'type': 'private'},
            'date': int(time.time()),
            'text': symbols_str
        }
    }
    logger.info(f"📡 请求 Woody API (基金数量: {len(symbols_str.split(','))})...")
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result and 'text' in result:
                logger.info("✅ Woody API 请求成功")
                return result
    except Exception as e:
        logger.error(f"❌ Woody API 请求失败: {e}")
    return None

def fetch_exchange_rates():
    url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"
    logger.info("📡 请求人民币中间价...")
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            res = {
                "date": data.get('data', {}).get('lastDate', '').split(' ')[0],
                "usd_cny_mid": None,
                "hkd_cny_mid": None
            }
            records = data.get('records', []) or data.get('data', {}).get('records', [])
            for r in records:
                name = r.get('vrtName', '')
                price = r.get('price', '')
                # 兼容 "港元" 和 "港币" 的称呼
                if '美元' in name or 'USD' in name:
                    res["usd_cny_mid"] = float(price) if price else None
                elif '港' in name or 'HKD' in name:
                    res["hkd_cny_mid"] = float(price) if price else None
            
            if res["usd_cny_mid"]:
                logger.info(f"✅ 汇率获取成功: USD={res['usd_cny_mid']}, HKD={res['hkd_cny_mid']}")
                return res
    except Exception as e:
        logger.error(f"❌ 汇率获取失败: {e}")
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", type=str, required=True)
    parser.add_argument("--token", type=str, required=True)
    parser.add_argument("--outdir", type=str, default="/opt/arb_siphon_data")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    today_str = datetime.now().strftime('%Y-%m-%d')

    woody_data = fetch_woody_api(args.symbols, args.token)
    if woody_data:
        path = os.path.join(args.outdir, f"woody_{today_str}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(woody_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 Woody 数据已保存")

    fx_data = fetch_exchange_rates()
    if fx_data:
        path = os.path.join(args.outdir, f"fx_{today_str}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(fx_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 汇率数据已保存")

if __name__ == "__main__":
    main()
