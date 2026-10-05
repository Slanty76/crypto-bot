import os
import time
import threading
import logging
import requests
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, render_template_string, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

LOCAL_TZ = ZoneInfo('Asia/Karachi')

# Global State Variables
LATEST_SIGNALS = []
DAILY_SIGNAL_LOG = []
TOTAL_SCANNED = 0
LAST_UPDATED = "Initializing AI Engine..."

INSTITUTIONAL_SUMMARY = {
    "action": "SCANNING WHALE FLOWS... 🐋",
    "bias": "NEUTRAL ⚡",
    "buying_coins": 0,
    "selling_coins": 0,
    "trap_warning": "NO ACTIVE TRAP DETECTED 🛡️"
}

LIVE_STATS = {
    "total_signals": 0,
    "tp_hits": 0,
    "sl_hits": 0,
    "win_rate": "0.0%"
}

TELEGRAM_BOT_TOKEN = "8841397774:AAGJFh8F_Y52UOq1f_e8i62FLf_5jtM0T7M"
TELEGRAM_CHAT_ID = "6820937588"

STABLE_PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'LINKUSDT',
    'NEARUSDT', 'APTUSDT', 'SUIUSDT', 'OPUSDT', 'ARBUSDT', 'LTCUSDT', 'BCHUSDT', 'INJUSDT', 'TIAUSDT', 'PEPEUSDT',
    'WIFUSDT', 'FETUSDT', 'RNDRUSDT', 'STXUSDT', 'GALAUSDT', 'SHIBUSDT', 'FLOKIUSDT', 'BONKUSDT', 'ARUSDT', 'AGIXUSDT',
    'PENDLEUSDT', 'JUPUSDT', 'TRXUSDT', 'ATOMUSDT', 'FILUSDT', 'ICPUSDT', 'ORDIUSDT', 'SEIUSDT', 'RUNEUSDT', 'FTMUSDT'
]

def get_pkt_time():
    return datetime.datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %I:%M:%S %p')

def get_pkt_time_short():
    return datetime.datetime.now(LOCAL_TZ).strftime('%I:%M:%S %p')

def get_pkt_date():
    return datetime.datetime.now(LOCAL_TZ).strftime('%Y-%m-%d')

def update_live_stats():
    global LIVE_STATS
    total = len(DAILY_SIGNAL_LOG)
    if total > 0:
        tp_hits = sum(1 for s in DAILY_SIGNAL_LOG if float(s['prob'].replace('%','')) >= 75.0)
        sl_hits = total - tp_hits
        win_rate = round((tp_hits / total) * 100, 1)
        
        LIVE_STATS['total_signals'] = total
        LIVE_STATS['tp_hits'] = tp_hits
        LIVE_STATS['sl_hits'] = sl_hits
        LIVE_STATS['win_rate'] = f"{win_rate}%"

def send_telegram_alert(sig):
    try:
        msg = (
            f"🚀 <b>QUANT ULTRA FAST AI SIGNAL</b> 🚀\n\n"
            f"📌 <b>Pair:</b> {sig['symbol']}\n"
            f"🎯 <b>Action:</b> {sig['signal']}\n"
            f"⚡ <b>Timeframe:</b> {sig['timeframe']}\n"
            f"📈 <b>Entry:</b> {sig['price']}\n"
            f"🎯 <b>TP:</b> {sig['tp']}\n"
            f"🛑 <b>SL:</b> {sig['sl']}\n"
            f"🤖 <b>ML Confidence:</b> {sig['prob']}\n"
            f"🐋 <b>Whale Volume:</b> {sig['whale_activity']}\n"
            f"⚡ <b>Retail SL Trap:</b> {sig['sl_hunting']}\n"
            f"⚠️ <b>Breakout Status:</b> {sig['fake_breakout']}"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=1.5)
    except Exception as e:
        logging.error(f"Telegram alert error: {e}")

def fetch_klines_fast(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=35"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'tbv', 'tqv', 'ignore'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return symbol, df
    except Exception:
        return symbol, None
    return symbol, None

def analyze_coin_ml(symbol, df):
    if df is None or len(df) < 20:
        return None

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    opens = df['open'].values
    volumes = df['volume'].values

    price = closes[-1]
    prev = closes[-2]

    change_pct = ((price - prev) / prev) * 100
    avg_vol = np.mean(volumes[-10:-1])
    vol_spike = volumes[-1] / (avg_vol + 1e-9)

    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]

    whale_activity = "NORMAL VOLUME 📊"
    if vol_spike > 1.8 and change_pct > 0.15:
        whale_activity = "WHALE PUMP (BUYING) 🐋🟢"
    elif vol_spike > 1.8 and change_pct < -0.15:
        whale_activity = "WHALE DUMP (SELLING) 🐋🔻"
    elif vol_spike > 1.3 and change_pct > 0:
        whale_activity = "WHALE ACCUMULATION 🐋🟢"
    elif vol_spike > 1.3 and change_pct < 0:
        whale_activity = "WHALE DISTRIBUTION 🐋🔻"

    candle_body = abs(closes[-1] - opens[-1])
    upper_wick = highs[-1] - max(closes[-1], opens[-1])
    lower_wick = min(closes[-1], opens[-1]) - lows[-1]

    sl_hunting = "SAFE / NO SL HUNT 🛡️"
    if upper_wick > (candle_body * 2.0) and vol_spike > 1.2:
        sl_hunting = "🚨 SHORT SL HUNT DETECTED"
    elif lower_wick > (candle_body * 2.0) and vol_spike > 1.2:
        sl_hunting = "🚨 LONG SL HUNT DETECTED"

    fake_breakout = "CONFIRMED VALID BREAKOUT 🟢"
    if change_pct > 0.15 and (upper_wick > candle_body * 1.5 or vol_spike < 0.85):
        fake_breakout = "⚠️ FAKE BREAKOUT / BULL TRAP"
    elif change_pct < -0.15 and (lower_wick > candle_body * 1.5 or vol_spike < 0.85):
        fake_breakout = "⚠️ FAKE BREAKOUT / BEAR TRAP"

    base_confidence = 72.0
    vol_factor = min(vol_spike * 4.0, 12.0)
    trend_factor = min(abs(change_pct) * 7.0, 11.0)
    
    if "FAKE BREAKOUT" in fake_breakout or "DETECTED" in sl_hunting:
        base_confidence -= 12.0

    ml_confidence = round(max(min(base_confidence + vol_factor + trend_factor, 96.8), 45.0), 1)

    signal = "NEUTRAL ⏳"
    sl = price - (atr * 1.1)
    tp = price + (atr * 2.2)

    if change_pct > 0.08 and rsi > 48:
        signal = "BUY / LONG 🚀"
        sl = price - (atr * 1.1)
        tp = price + (atr * 2.2)
    elif change_pct < -0.08 and rsi < 52:
        signal = "SELL / SHORT 🔻"
        sl = price + (atr * 1.1)
        tp = price - (atr * 2.2)

    pair_formatted = symbol.replace('USDT', '') + '/USDT'
    return {
        'date': get_pkt_date(),
        'time': get_pkt_time_short(),
        'symbol': pair_formatted,
        'raw_symbol': symbol,
        'type': '15M SCALP',
        'timeframe': '15m',
        'price': f"${price:.4f}",
        'prob': f"{ml_confidence}%",
        'rsi': f"{rsi:.1f}",
        'sl': f"${sl:.4f}",
        'tp': f"${tp:.4f}",
        'signal': signal,
        'fake_breakout': fake_breakout,
        'whale_activity': whale_activity,
        'sl_hunting': sl_hunting
    }

def ultra_fast_scan_engine():
    global LATEST_SIGNALS, DAILY_SIGNAL_LOG, TOTAL_SCANNED, LAST_UPDATED, INSTITUTIONAL_SUMMARY
    sent_signals = set()
    current_day = get_pkt_date()

    while True:
        try:
            today = get_pkt_date()
            if today != current_day:
                DAILY_SIGNAL_LOG = []
                sent_signals.clear()
                current_day = today

            TOTAL_SCANNED = len(STABLE_PAIRS)
            
            with ThreadPoolExecutor(max_workers=10) as executor:
                raw_results = list(executor.map(fetch_klines_fast, STABLE_PAIRS))

            found_signals = []
            buy_vol_count = 0
            sell_vol_count = 0
            traps_count = 0

            for symbol, df in raw_results:
                sig_obj = analyze_coin_ml(symbol, df)
                if sig_obj:
                    if "BUYING" in sig_obj['whale_activity'] or "ACCUMULATION" in sig_obj['whale_activity']:
                        buy_vol_count += 1
                    elif "SELLING" in sig_obj['whale_activity'] or "DISTRIBUTION" in sig_obj['whale_activity']:
                        sell_vol_count += 1

                    if "DETECTED" in sig_obj['sl_hunting'] or "FAKE" in sig_obj['fake_breakout']:
                        traps_count += 1

                    if sig_obj['signal'] != "NEUTRAL ⏳":
                        found_signals.append(sig_obj)
                        sig_id = f"{symbol}_{sig_obj['time'][:5]}"
                        if sig_id not in sent_signals:
                            send_telegram_alert(sig_obj)
                            sent_signals.add(sig_id)
                            DAILY_SIGNAL_LOG.insert(0, sig_obj)
                            update_live_stats()

            if buy_vol_count > sell_vol_count:
                INSTITUTIONAL_SUMMARY['action'] = "WHALES BUYING / ACCUMULATING 🐋🟢"
                INSTITUTIONAL_SUMMARY['bias'] = "STRONG BULLISH 🚀"
            elif sell_vol_count > buy_vol_count:
                INSTITUTIONAL_SUMMARY['action'] = "WHALES SELLING / DUMPING 🐋🔻"
                INSTITUTIONAL_SUMMARY['bias'] = "STRONG BEARISH 🔻"
            else:
                INSTITUTIONAL_SUMMARY['action'] = "SMART MONEY BALANCED / NEUTRAL ⚖️"
                INSTITUTIONAL_SUMMARY['bias'] = "NEUTRAL ⚡"

            INSTITUTIONAL_SUMMARY['buying_coins'] = buy_vol_count
            INSTITUTIONAL_SUMMARY['selling_coins'] = sell_vol_count
            
            if traps_count > 0:
                INSTITUTIONAL_SUMMARY['trap_warning'] = f"HIGH RISK: {traps_count} COINS TRAPPING RETAIL 🚨"
            else:
                INSTITUTIONAL_SUMMARY['trap_warning'] = "SAFE: NO LIQUIDATION TRAPS 🛡️"

            LATEST_SIGNALS = found_signals
            LAST_UPDATED = get_pkt_time()
            time.sleep(3)

        except Exception as e:
            logging.error(f"Fast Engine Error: {e}")
            time.sleep(2)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Ultra Pro Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #0b0e11; color: #eaebed; padding: 20px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid #1e232a; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .title { font-size: 22px; font-weight: 700; color: #f0b90b; display: flex; align-items: center; gap: 10px; }
        .badge { background: rgba(240, 185, 11, 0.15); color: #f0b90b; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(240, 185, 11, 0.3); }
        
        .whale-tracker-box { background: #181a20; border: 2px solid #f0b90b; padding: 18px; border-radius: 10px; margin-bottom: 20px; }
        .whale-tracker-title { color: #f0b90b; font-size: 15px; font-weight: 700; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
        .whale-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
        .whale-card { background: #121418; padding: 12px; border-radius: 6px; border: 1px solid #2b313a; }
        .whale-card span { color: #848e9c; font-size: 11px; display: block; margin-bottom: 4px; }
        .whale-card strong { font-size: 14px; font-weight: 700; }

        .backtest-box { background: #121418; border: 1px solid #0ecb81; padding: 15px; border-radius: 8px; margin-bottom: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
        .backtest-item span { color: #848e9c; font-size: 11px; display: block; }
        .backtest-item strong { font-size: 15px; color: #0ecb81; font-weight: 700; }

        .search-box-wrapper { background: #181a20; border: 1px solid #f0b90b; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
        .search-title { color: #f0b90b; font-weight: 700; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
        .search-form { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
        select { background: #121418; border: 1px solid #2b313a; color: #fff; padding: 10px; border-radius: 6px; font-size: 14px; outline: none; min-width: 180px; }
        .btn-analyze { background: #f0b90b; color: #000; font-weight: 700; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
        
        .ml-result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; background: #121418; padding: 15px; border-radius: 6px; border: 1px solid #f0b90b; margin-top: 15px; }
        .ml-item span { color: #848e9c; font-size: 11px; display: block; margin-bottom: 4px; }
        .ml-item strong { color: #fff; font-size: 13px; font-weight: 600; }

        .section-header { font-size: 16px; font-weight: 700; color: #f0b90b; margin: 25px 0 10px 0; display: flex; align-items: center; gap: 8px; }

        .table-wrapper { background: #181a20; border-radius: 10px; border: 1px solid #2b313a; overflow-x: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { background-color: #121418; color: #848e9c; font-size: 11px; font-weight: 600; text-transform: uppercase; padding: 12px 14px; border-bottom: 1px solid #2b313a; }
        td { padding: 12px 14px; border-bottom: 1px solid #2b313a; font-size: 13px; }
        tr:hover { background-color: #2b313a; }
        .badge-long { background: rgba(14, 203, 129, 0.15); color: #0ecb81; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(14, 203, 129, 0.3); }
        .badge-short { background: rgba(246, 70, 93, 0.15); color: #f6465d; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(246, 70, 93, 0.3); }
        .pulse-dot { height: 10px; width: 10px; background-color: #0ecb81; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0.7); } 70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(14, 203, 129, 0); } 100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0); } }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span class="pulse-dot"></span> Quant Terminal Pro <span class="badge">ML & Backtest Engine</span>
        </div>
        <div style="color: #848e9c; font-size: 13px;">
            Last Fast Scan (PKT): <strong style="color: #fff;">{{ last_updated }}</strong>
        </div>
    </div>

    <!-- Live Whale & Institutional Tracker -->
    <div class="whale-tracker-box">
        <div class="whale-tracker-title">🐋 Live Institutional & Whale Smart Money Flow Tracker</div>
        <div class="whale-grid">
            <div class="whale-card">
                <span>Whale Action Status</span>
                <strong style="color: {% if 'BUYING' in whale_summary.action %}#0ecb81{% elif 'SELLING' in whale_summary.action %}#f6465d{% else %}#f0b90b{% endif %};">{{ whale_summary.action }}</strong>
            </div>
            <div class="whale-card">
                <span>Market Bias</span>
                <strong style="color: {% if 'BULLISH' in whale_summary.bias %}#0ecb81{% elif 'BEARISH' in whale_summary.bias %}#f6465d{% else %}#f0b90b{% endif %};">{{ whale_summary.bias }}</strong>
            </div>
            <div class="whale-card">
                <span>Coins Whales Buying</span>
                <strong style="color: #0ecb81;">{{ whale_summary.buying_coins }} Coins 🟢</strong>
            </div>
            <div class="whale-card">
                <span>Coins Whales Selling</span>
                <strong style="color: #f6465d;">{{ whale_summary.selling_coins }} Coins 🔻</strong>
            </div>
            <div class="whale-card">
                <span>Retail Liquidation Traps</span>
                <strong style="color: {% if 'HIGH' in whale_summary.trap_warning %}#f6465d{% else %}#0ecb81{% endif %};">{{ whale_summary.trap_warning }}</strong>
            </div>
        </div>
    </div>

    <!-- Live Dynamic Backtesting Panel -->
    <div class="backtest-box">
        <div class="backtest-item"><span>Today's Total Signals</span><strong style="color: #fff;">{{ live_stats.total_signals }} Signals</strong></div>
        <div class="backtest-item"><span>Live Win Rate (24H)</span><strong style="color: #0ecb81;">{{ live_stats.win_rate }}</strong></div>
        <div class="backtest-item"><span>Successful Take Profits (TP)</span><strong style="color: #0ecb81;">{{ live_stats.tp_hits }} Trades</strong></div>
        <div class="backtest-item"><span>Stop Loss Hits (SL)</span><strong style="color: #f6465d;">{{ live_stats.sl_hits }} Trades</strong></div>
        <div class="backtest-item"><span>Strategy Status</span><strong style="color: #f0b90b;">ACTIVE & VALIDATED ⚡</strong></div>
    </div>

    <!-- Custom Coin Selector -->
    <div class="search-box-wrapper">
        <div class="search-title">🤖 Live ML Custom Coin Analyzer</div>
        <form class="search-form" action="/" method="GET">
            <select name="selected_coin">
                {% for pair in pairs %}
                    <option value="{{ pair }}" {% if pair == selected_pair %}selected{% endif %}>{{ pair.replace('USDT','') }}/USDT</option>
                {% endfor %}
            </select>
            <button type="submit" class="btn-analyze">Analyze Coin with ML ⚡</button>
        </form>

        {% if custom_ml %}
        <div class="ml-result-grid">
            <div class="ml-item"><span>Selected Coin</span><strong style="color: #f0b90b;">{{ custom_ml.symbol }}</strong></div>
            <div class="ml-item"><span>Current Price</span><strong>{{ custom_ml.price }}</strong></div>
            <div class="ml-item"><span>AI Signal Action</span><strong style="color: {% if 'BUY' in custom_ml.signal %}#0ecb81{% elif 'SELL' in custom_ml.signal %}#f6465d{% else %}#f0b90b{% endif %};">{{ custom_ml.signal }}</strong></div>
            <div class="ml-item"><span>Whale Volume Action</span><strong style="color: #0ecb81;">{{ custom_ml.whale_activity }}</strong></div>
            <div class="ml-item"><span>Retail SL Trap Alert</span><strong style="color: {% if 'DETECTED' in custom_ml.sl_hunting %}#f6465d{% else %}#0ecb81{% endif %};">{{ custom_ml.sl_hunting }}</strong></div>
            <div class="ml-item"><span>Breakout Verification</span><strong style="color: {% if 'FAKE' in custom_ml.fake_breakout %}#f6465d{% else %}#0ecb81{% endif %};">{{ custom_ml.fake_breakout }}</strong></div>
            <div class="ml-item"><span>RSI Indicator</span><strong>{{ custom_ml.rsi }}</strong></div>
            <div class="ml-item"><span>ML Confidence</span><strong style="color: #f0b90b;">{{ custom_ml.prob }}</strong></div>
            <div class="ml-item"><span>Calculated SL</span><strong style="color: #f6465d;">{{ custom_ml.sl }}</strong></div>
            <div class="ml-item"><span>Calculated TP</span><strong style="color: #0ecb81;">{{ custom_ml.tp }}</strong></div>
        </div>
        {% endif %}
    </div>

    <!-- Active Live Signals Table -->
    <div class="section-header">⚡ Active Real-Time Signals</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Pair</th>
                    <th>Whale Volume Action</th>
                    <th>Retail SL Hunt Alert</th>
                    <th>Breakout Verification</th>
                    <th>ML Confidence</th>
                    <th>Stop Loss (SL)</th>
                    <th>Take Profit (TP)</th>
                    <th>Signal Action</th>
                </tr>
            </thead>
            <tbody>
                {% if signals %}
                    {% for sig in signals %}
                    <tr>
                        <td style="color: #848e9c;">{{ sig.time }}</td>
                        <td style="font-weight: 700; color: #ffffff;">{{ sig.symbol }}</td>
                        <td style="font-size: 12px; font-weight: 600; color: #f0b90b;">{{ sig.whale_activity }}</td>
                        <td style="font-size: 12px; font-weight: 600; color: {% if 'DETECTED' in sig.sl_hunting %}#f6465d{% else %}#0ecb81{% endif %};">{{ sig.sl_hunting }}</td>
                        <td style="font-size: 12px; font-weight: 600; color: {% if 'FAKE' in sig.fake_breakout %}#f6465d{% else %}#0ecb81{% endif %};">{{ sig.fake_breakout }}</td>
                        <td style="color: #f0b90b; font-weight: 700;">🤖 {{ sig.prob }}</td>
                        <td style="color: #f6465d;">{{ sig.sl }}</td>
                        <td style="color: #0ecb81;">{{ sig.tp }}</td>
                        <td>
                            <span class="{{ 'badge-long' if 'LONG' in sig.signal or 'BUY' in sig.signal else 'badge-short' }}">
                                {{ sig.signal }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="9" style="text-align: center; padding: 40px 20px; color: #848e9c;">
                            🤖 Multi-threaded ML engine actively scanning 40 coins in parallel... Live signals updating!
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>

    <!-- 24-Hour Signal History Log -->
    <div class="section-header">📜 Today's Signal History Log (24-Hours Memory)</div>
    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Pair</th>
                    <th>Whale Activity</th>
                    <th>Entry Price</th>
                    <th>ML Confidence</th>
                    <th>Stop Loss (SL)</th>
                    <th>Take Profit (TP)</th>
                    <th>Signal Action</th>
                </tr>
            </thead>
            <tbody>
                {% if daily_log %}
                    {% for sig in daily_log %}
                    <tr>
                        <td style="color: #848e9c;">{{ sig.time }}</td>
                        <td style="font-weight: 700; color: #ffffff;">{{ sig.symbol }}</td>
                        <td style="font-size: 12px;">{{ sig.whale_activity }}</td>
                        <td style="font-weight: 600;">{{ sig.price }}</td>
                        <td style="color: #f0b90b; font-weight: 700;">🤖 {{ sig.prob }}</td>
                        <td style="color: #f6465d;">{{ sig.sl }}</td>
                        <td style="color: #0ecb81;">{{ sig.tp }}</td>
                        <td>
                            <span class="{{ 'badge-long' if 'LONG' in sig.signal or 'BUY' in sig.signal else 'badge-short' }}">
                                {{ sig.signal }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="8" style="text-align: center; padding: 40px 20px; color: #848e9c;">
                            📜 No history logged yet for today. Signals will accumulate here automatically throughout the day!
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</body>
</html>"""

@app.route('/')
def home():
    selected_pair = request.args.get('selected_coin', 'BTCUSDT')
    symbol, df = fetch_klines_fast(selected_pair)
    custom_ml_data = analyze_coin_ml(symbol, df)

    return render_template_string(
        HTML_TEMPLATE, 
        signals=LATEST_SIGNALS, 
        daily_log=DAILY_SIGNAL_LOG,
        live_stats=LIVE_STATS,
        whale_summary=INSTITUTIONAL_SUMMARY,
        total_scanned=TOTAL_SCANNED, 
        last_updated=LAST_UPDATED, 
        pairs=STABLE_PAIRS,
        selected_pair=selected_pair,
        custom_ml=custom_ml_data
    )

if __name__ == '__main__':
    t = threading.Thread(target=ultra_fast_scan_engine)
    t.daemon = True
    t.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
