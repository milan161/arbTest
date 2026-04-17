---
name: codex-lofarb-helper
description: Expert assistant for the CodexLOFarb LOF monitoring and trading system. Use for debugging data flows, updating fund configurations, explaining valuation algorithms, and managing the real-time monitoring service.
---

# CodexLOFarb Helper

This skill provides specialized knowledge and workflows for the CodexLOFarb system, a real-time monitoring and arbitrage tool for Listed Open-Ended Funds (LOF).

## System Overview

CodexLOFarb is composed of several modules (`LOF00` to `LOF03`) that handle configuration, data ingestion, real-time fetching, and UI generation.

### Module Reference
- **LOF00 (Config Center)**: Flask app (Port 5001) for managing `lof_config.yaml`.
- **LOF011 (Basic Data)**: Fetches FX rates and ETF history. Saves to `data/GLD_USO_basic_data.csv`.
- **LOF012 (LOF Data)**: Fetches LOF NAV and calculates static valuations. Saves to `data/LOF_{code}_history.csv`.
- **LOF013 (Woody Crawler)**: Scrapes Woody's web data as a fallback for API data.
- **LOF02 (Data Engine)**: Core service (Port 5000) providing real-time data via REST, WebSocket, and SSE. Integrates IB, QMT, and Sina.
- **LOF03 (Monitor UI)**: Generates `lof_monitor.html`. Delegated to `LOF031` (Config), `LOF032` (Data), and `LOF033` (HTML).

## Common Workflows

### 1. Adding/Updating a Fund
To add a new fund or update an existing one:
1. Modify `lof_config.yaml` or use the `LOF00` UI.
2. Run `LOF011.py` and `LOF012.py` to refresh historical data and base valuations.
3. Restart `LOF02.py` to load the new configuration.
4. Run `LOF03_generate_monitor_html.py` to update the monitor UI.

### 2. Troubleshooting Data Gaps
If real-time data is missing:
- Check `LOF02` logs for connection errors (IB Gateway, QMT).
- Verify `lof_config.yaml` has the correct `trade_etf` and `trade_future` symbols.
- Ensure `data/access_status.json` shows successful recent fetches.

### 3. Explaining Valuation Algorithms
The system uses three main valuation methods:
- **Static Official**: Based on T-1 NAV and current ETF/FX changes.
- **Futures Calibration**: Uses a dynamic calibration value ($Future / ETF$) to map futures to equivalent ETF prices.
- **Futures Native**: Directly uses futures price changes adjusted by Beta.

## Core Files & Locations
- **Config**: `lof_config.yaml`
- **Database**: `data/access_status.json`, `data/*.csv`
- **Logs**: `logs/*.log`
- **Core Logic**: `readers/data_fetcher.py`, `readers/trade_manager.py`

## Troubleshooting Tips
- **Port 5000/5001 Busy**: Use `netstat -ano | findstr :5000` to find and kill the process.
- **IB Data Missing**: Check if IB Gateway is running and if the account has market data subscriptions.
- **QMT Connection**: Ensure QMT is in "Expert Mode" and the socket server is enabled.
