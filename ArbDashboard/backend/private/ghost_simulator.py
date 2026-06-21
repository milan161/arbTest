"""
Ghost Trader Weekend Simulator
Mock data engine for testing the Ghost Trader pipeline on weekends.
Generates realistic random-walk prices for 162411/XOP, calculates premiums,
and logs whether signals would fire. NEVER places real orders.
"""
import time
import random
import threading
import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


class GhostSimulator:
    def __init__(self):
        self.running = False
        self.thread = None
        self.tick_interval = 30  # seconds

        # Realistic starting prices
        self.lof_price = 0.6850    # 162411 typical range: 0.65-0.75
        self.us_price = 140.25     # XOP typical range: 135-145
        self.fx_rate = 7.2500      # USD/CNY
        self.redemption_fee = 0.3316  # 162411 redemption fee %

        # History buffer (last 100 ticks)
        self.history = deque(maxlen=100)
        self.tick_count = 0
        self.signal_count = 0
        self.forced_signal = False  # force a signal for testing

    def start(self):
        if self.running:
            return {"status": "already_running"}
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("[GhostSim] Simulation started, interval=%ds", self.tick_interval)
        return {"status": "started"}

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[GhostSim] Simulation stopped after %d ticks", self.tick_count)
        return {"status": "stopped"}

    def reset(self):
        self.stop()
        self.lof_price = 0.6850
        self.us_price = 140.25
        self.fx_rate = 7.2500
        self.history.clear()
        self.tick_count = 0
        self.signal_count = 0
        self.forced_signal = False
        logger.info("[GhostSim] Simulation reset")
        return {"status": "reset"}

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

        # Random walk: LOF price drifts +/- 0.002 per tick
        lof_delta = random.gauss(0, 0.002)
        self.lof_price = round(max(0.60, min(0.80, self.lof_price + lof_delta)), 4)

        # Random walk: XOP price drifts +/- 0.3 per tick
        us_delta = random.gauss(0, 0.3)
        self.us_price = round(max(130.0, min(150.0, self.us_price + us_delta)), 2)

        # Tiny FX fluctuation
        fx_delta = random.gauss(0, 0.001)
        self.fx_rate = round(max(7.20, min(7.30, self.fx_rate + fx_delta)), 4)

        # Bid/Ask spreads
        lof_spread = 0.001
        lof_bid = round(self.lof_price - lof_spread / 2, 4)
        lof_ask = round(self.lof_price + lof_spread / 2, 4)
        lof_bid_size = random.randint(500, 5000)

        us_spread = random.uniform(0.05, 0.15)
        us_bid = round(self.us_price - us_spread / 2, 2)
        us_ask = round(self.us_price + us_spread / 2, 2)
        us_bid_size = random.randint(10, 50)  # XOP low liquidity

        # Premium calculation (same formula as ghost_calc main.py)
        # Correct formula: val = base_nav * (1 - pos) + pos * (us_price * fx) / hedge
        # For simulation, use typical 162411 values: base_nav=0.68, pos=0.95, hedge=1352
        base_nav = 0.6850
        position = 0.95
        hedge = 1352.24
        val_safe = base_nav * (1 - position) + position * (us_bid * self.fx_rate) / hedge if self.fx_rate > 0 else 0
        premium_safe = (lof_bid / val_safe - 1) * 100 if val_safe > 0 else 0

        peg_price = us_ask - 0.01 if us_ask > 0.01 else us_ask
        val_peg = base_nav * (1 - position) + position * (peg_price * self.fx_rate) / hedge if self.fx_rate > 0 else 0
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
