"""
Ghost Trader Weekend Simulator
Mock data engine for testing the Ghost Trader pipeline on weekends.
Generates realistic random-walk prices for 162411/XOP, calculates premiums,
and logs whether signals would fire. NEVER places real orders.
"""
import os
import time
import random
import threading
import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'database', 'arb_master.db')


class GhostSimulator:
    def __init__(self):
        self.running = False
        self.thread = None
        self.tick_interval = 30  # seconds

        # Will be loaded from DB on start
        self.lof_price = 0.8130    # 162411 last close
        self.us_price = 153.36     # XOP last close
        self.fx_rate = 6.8130      # USD/CNY last mid
        self.hedge = 1352.24       # hedge ratio for 162411
        self.position = 0.95       # position ratio
        self.base_nav = 0.8247     # 162411 last NAV

        self.redemption_fee = 0.3316  # 162411 redemption fee %

        # History buffer (last 100 ticks)
        self.history = deque(maxlen=100)
        self.tick_count = 0
        self.signal_count = 0
        self.forced_signal = False  # force a signal for testing

    def _load_base_prices(self):
        """Load real base prices from database for realistic simulation"""
        try:
            import sqlite3
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            # 1. LOF 162411 last closing price
            cur.execute(
                "SELECT price FROM unified_fund_history "
                "WHERE fund_code='162411' AND price IS NOT NULL AND price > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.lof_price = float(row[0])
                logger.info("[GhostSim] LOF base price: %.4f", self.lof_price)

            # 2. LOF 162411 last NAV
            cur.execute(
                "SELECT nav FROM unified_fund_history "
                "WHERE fund_code='162411' AND nav IS NOT NULL AND nav > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.base_nav = float(row[0])
                logger.info("[GhostSim] LOF base NAV: %.4f", self.base_nav)

            # 3. XOP last closing price
            cur.execute(
                "SELECT price FROM usa_etf_daily_prices "
                "WHERE symbol='XOP' AND price IS NOT NULL AND price > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.us_price = float(row[0])
                logger.info("[GhostSim] XOP base price: %.2f", self.us_price)

            # 4. USD/CNY last mid rate
            cur.execute(
                "SELECT usd_cny_mid FROM exchange_rate "
                "WHERE usd_cny_mid IS NOT NULL AND usd_cny_mid > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.fx_rate = float(row[0])
                logger.info("[GhostSim] FX base rate: %.4f", self.fx_rate)

            # 5. Hedge ratio for 162411
            cur.execute(
                "SELECT hedge FROM fund_daily_factors "
                "WHERE fund_code='162411' AND hedge IS NOT NULL AND hedge > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.hedge = float(row[0])
                logger.info("[GhostSim] Hedge ratio: %.4f", self.hedge)

            # 6. Position ratio
            cur.execute(
                "SELECT position FROM fund_daily_factors "
                "WHERE fund_code='162411' AND position IS NOT NULL AND position > 0 "
                "ORDER BY date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                self.position = float(row[0])
                logger.info("[GhostSim] Position ratio: %.4f", self.position)

            conn.close()
        except Exception as e:
            logger.warning("[GhostSim] Failed to load base prices from DB: %s, using defaults", e)

    def start(self):
        if self.running:
            return {"status": "already_running"}
        self._load_base_prices()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("[GhostSim] Simulation started, interval=%ds", self.tick_interval)
        return {"status": "started", "base_prices": {
            "lof": self.lof_price, "us": self.us_price,
            "fx": self.fx_rate, "nav": self.base_nav,
            "hedge": self.hedge, "position": self.position,
        }}

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[GhostSim] Simulation stopped after %d ticks", self.tick_count)
        return {"status": "stopped"}

    def reset(self):
        self.stop()
        self._load_base_prices()  # Reload real base prices
        self.history.clear()
        self.tick_count = 0
        self.signal_count = 0
        self.forced_signal = False
        logger.info("[GhostSim] Simulation reset with real base prices")
        return {"status": "reset", "base_prices": {
            "lof": self.lof_price, "us": self.us_price,
            "fx": self.fx_rate, "nav": self.base_nav,
        }}

    def set_forced_signal(self, enabled: bool):
        self.forced_signal = enabled
        return {"forced_signal": enabled}

    def get_status(self):
        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "signal_count": self.signal_count,
            "forced_signal": self.forced_signal,
            "tick_interval": self.tick_interval,
            "base_prices": {
                "lof": self.lof_price, "us": self.us_price,
                "fx": self.fx_rate, "nav": self.base_nav,
                "hedge": self.hedge, "position": self.position,
            },
            "current": self.history[0] if self.history else None,
            "history": list(self.history)[:50],
        }

    def _loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.error("[GhostSim] Tick error: %s", e)
            time.sleep(self.tick_interval)

    def _tick(self):
        self.tick_count += 1
        now = datetime.now()
        time_str = now.strftime("%H:%M:%S")

        # ±5% random walk from real base prices (DB-sourced)
        lof_fluct = random.uniform(-0.05, 0.05)
        self.lof_price = round(self.lof_price * (1 + lof_fluct), 4)

        us_fluct = random.uniform(-0.05, 0.05)
        self.us_price = round(self.us_price * (1 + us_fluct), 2)

        # FX: tiny fluctuation (±0.1%)
        fx_fluct = random.uniform(-0.001, 0.001)
        self.fx_rate = round(self.fx_rate * (1 + fx_fluct), 4)

        # Bid/Ask spreads
        lof_spread = 0.001
        lof_bid = round(self.lof_price - lof_spread / 2, 4)
        lof_ask = round(self.lof_price + lof_spread / 2, 4)
        lof_bid_size = random.randint(500, 5000)

        us_spread = random.uniform(0.05, 0.15)
        us_bid = round(self.us_price - us_spread / 2, 2)
        us_ask = round(self.us_price + us_spread / 2, 2)
        us_bid_size = random.randint(10, 50)

        # Premium calculation (same formula as ghost_calc main.py)
        # val = base_nav * (1 - pos) + pos * (us_price * fx) / hedge
        val_safe = self.base_nav * (1 - self.position) + self.position * (us_bid * self.fx_rate) / self.hedge if self.fx_rate > 0 and self.hedge > 0 else 0
        premium_safe = (lof_bid / val_safe - 1) * 100 if val_safe > 0 else 0

        peg_price = us_ask - 0.01 if us_ask > 0.01 else us_ask
        val_peg = self.base_nav * (1 - self.position) + self.position * (peg_price * self.fx_rate) / self.hedge if self.fx_rate > 0 and self.hedge > 0 else 0
        premium_peg = (lof_bid / val_peg - 1) * 100 if val_peg > 0 else 0

        net_profit_safe = abs(premium_safe) - self.redemption_fee
        net_profit_peg = abs(premium_peg) - self.redemption_fee

        # Signal logic: net profit >= 0.3% triggers
        target_profit = 0.3
        signal_safe = net_profit_safe >= target_profit
        signal_peg = net_profit_peg >= target_profit

        # Forced signal mode: override for testing
        if self.forced_signal:
            premium_safe = -1.2
            net_profit_safe = 1.2 - self.redemption_fee
            signal_safe = True
            premium_peg = -1.35
            net_profit_peg = 1.35 - self.redemption_fee
            signal_peg = True

        if signal_safe or signal_peg:
            self.signal_count += 1

        tick = {
            "time": time_str,
            "tick": self.tick_count,
            "lof": {
                "price": self.lof_price,
                "bid": lof_bid,
                "ask": lof_ask,
                "bid_size": lof_bid_size,
            },
            "us": {
                "price": self.us_price,
                "bid": us_bid,
                "ask": us_ask,
                "bid_size": us_bid_size,
            },
            "fx": self.fx_rate,
            "premium_safe": round(premium_safe, 3),
            "premium_peg": round(premium_peg, 3),
            "net_profit_safe": round(net_profit_safe, 3),
            "net_profit_peg": round(net_profit_peg, 3),
            "signal_safe": signal_safe,
            "signal_peg": signal_peg,
            "redemption_fee": self.redemption_fee,
        }
        self.history.appendleft(tick)

        # Log
        sig_mark = " --> SIGNAL!" if (signal_safe or signal_peg) else ""
        logger.info(
            "[SIM %s] #%d 162411=%.4f XOP=%.2f fx=%.4f prem_safe=%.3f%% net=%.3f%%%s",
            time_str, self.tick_count,
            self.lof_price, self.us_price, self.fx_rate,
            premium_safe, net_profit_safe, sig_mark,
        )


# Singleton
ghost_simulator_instance = GhostSimulator()
