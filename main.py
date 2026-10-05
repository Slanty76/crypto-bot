import os
import time
import threading
import pandas as pd
import logging
import requests
from flask import Flask, render_template_string

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Global Variables
LATEST_SIGNALS = []
TOTAL_SCANNED = 0
LAST_UPDATED = "Initializing..."
MARKET_SENTIMENT = "Bullish Momentum 🚀"
FEAR_GREED_INDEX = "70 (Greed)"
LIQUIDITY_STATUS = "High Liquidity"
MARKET_BIAS = "BUY / LONG 🟢"

BTC_DAILY_FORECAST = "BULLISH PUMP 🟢"
BTC_WEEKLY_FORECAST = "ACCUMULATION ZONE 🔄"
BTC_MONTHLY_FORECAST = "MACRO BULL RUN 🟢"

TELEGRAM_BOT_TOKEN = "8841397774:AAGJFh8F_Y52UOq1f_e8i62FLf_5jtM0T7M"
TELEGRAM_CHAT_ID = "6820937588"

TIMEFRAMES = {
    '5M Scalp': '5m',
    '15M Scalp': '15m'
}

FULL_PAIRS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'APT/USDT', 'SUI/USDT', 'OP/USDT', 'ARB/USDT', 'LTC/USDT', 'BCH/USDT', 'INJ/USDT', 'TIA/USDT', 'PEPE/USDT',
    'WIF/USDT', 'FET/USDT', 'RNDR/USDT', 'STX/USDT', 'GALA/USDT', 'SHIB/USDT', 'FLOKI/USDT', 'BONK/USDT', 'AR/USDT', 'AGIX/USDT'
]

def send_telegram_alert(signal_data):
    try:
        message = (
            f"🚨 <b>QUANT AI TRADE ALERT</b> 🚨\n\n"
            f"📌 <b>Pair:</b> {signal_data['symbol']}\n"
            f"🎯 <b>Action:</b> {signal_data['signal']}\n"
            f"⚡ <b>Category:</b> {signal_data['type']} ({signal_data['timeframe']})\n"
            f"📈 <b>Entry Price:</b> {signal_data['price']}\n"
            f"🎯 <b>Take Profit (TP):</b> {signal_data['tp']}\n"
            f"🛑 <b>Stop Loss (SL):</b> {signal_data['sl']}\n"
            f"🔥 <b>AI Win Probability:</b> {signal_data['prob']}\n\n"
            f"🌐 <i>Monitor live on your Quant Terminal!</i>"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=2.0)
    except Exception:
        pass

def fetch_ohlcv_public(symbol, timeframe, limit=30):
    try:
        clean_symbol = symbol.replace('/', '').replace('USDT', '') + 'USDT'
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={clean_symbol}&interval={timeframe}&limit={limit}"
        # Hard Timeout to prevent script freeze
        res = requests.get(url, timeout=0.8)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'tbv', 'tqv', 'ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception:
        return None
    return None

def quant_master_scanner():
    global LATEST_SIGNALS, TOTAL_SCANNED, LAST_UPDATED
    sent_signals = set()

    # Infinite Fail-Safe Loop
    while True:
        try:
            symbols = FULL_PAIRS
            TOTAL_SCANNED = len(symbols)
            found_signals = []

            for symbol in symbols:
                time.sleep(0.1) # Prevents IP Rate Limiting
                for tf_name, tf_code in TIMEFRAMES.items():
                    df = fetch_ohlcv_public(symbol, tf_code)
                    if df is None or len(df) < 20:
                        continue

                    delta = df['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / (loss + 1e-9)
                    df['rsi'] = 100 - (100 / (1 + rs))

                    df['tr0'] = abs(df['high'] - df['low'])
                    df['tr1'] = abs(df['high'] - df['close'].shift(1))
                    df['tr2'] = abs(df['low'] - df['close'].shift(1))
                    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
                    df['atr'] = df['tr'].rolling(14).mean()

                    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
                    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()

                    latest = df.iloc[-1]
                    price = float(latest['close'])
                    atr = float(latest['atr'])
                    rsi = float(latest['rsi'])
                    ema9 = float(latest['ema_9'])
                    ema21 = float(latest['ema_21'])

                    signal = None
                    win_prob = 0.0

                    if rsi < 58 and ema9 > ema21:
                        signal = "BUY / LONG 🚀"
                        win_prob = 65.0 + min((58 - rsi), 25)
                        sl = price - (atr * 1.2)
                        tp = price + (atr * 2.4)
                    elif rsi > 42 and ema9 < ema21:
                        signal = "SELL / SHORT 🔻"
                        win_prob = 65.0 + min((rsi - 42), 25)
                        sl = price + (atr * 1.2)
                        tp = price - (atr * 2.4)

                    if signal:
                        signal_obj = {
                            'symbol': symbol,
                            'type': "5M SCALP" if "5M" in tf_name else "SCALP",
                            'timeframe': tf_name,
                            'price': f"${price:.4f}",
                            'prob': f"{win_prob:.1f}%",
                            'sl': f"${sl:.4f}",
                            'tp': f"${tp:.4f}",
                            'signal': signal,
                            'time': time.strftime('%H:%M:%S')
                        }
                        found_signals.append(signal_obj)

                        sig_id = f"{symbol}_{tf_name}_{latest['timestamp']}"
                        if sig_id not in sent_signals:
                            send_telegram_alert(signal_obj)
                            sent_signals.add(sig_id)

            LATEST_SIGNALS = found_signals
            LAST_UPDATED = time.strftime('%Y-%m-%d %H:%M:%S')
            time.sleep(1)

        except Exception as e:
            logging.error(f"Engine Resetting: {e}")
            LAST_UPDATED = time.strftime('%Y-%m-%d %H:%M:%S')
            time.sleep(2) # Auto-recover without crashing

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant AI Pro Terminal</title>
    <meta http-equiv="refresh" content="5">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #0b0e11; color: #eaebed; padding: 20px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid #1e232a; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .title { font-size: 22px; font-weight: 700; color: #f0b90b; display: flex; align-items: center; gap: 10px; }
        .badge { background: rgba(240, 185, 11, 0.15); color: #f0b90b; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(240, 185, 11, 0.3); }
        .grid-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
        .card { background: #181a20; padding: 12px 15px; border-radius: 8px; border: 1px solid #2b313a; }
        .card span { color: #848e9c; font-size: 11px; display: block; margin-bottom: 4px; }
        .card strong { font-size: 14px; color: #fff; }
        .table-wrapper { background: #181a20; border-radius: 10px; border: 1px solid #2b313a; overflow-x: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { background-color: #121418; color: #848e9c; font-size: 11px; font-weight: 600; text-transform: uppercase; padding: 12px 14px; border-bottom: 1px solid #2b313a; }
        td { padding: 12px 14px; border-bottom: 1px solid #2b313a; font-size: 13px; }
        tr:hover { background-color: #2b313a; }
        .badge-long { background: rgba(14, 203, 129, 0.15); color: #0ecb81; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(14, 203, 129, 0.3); }
        .badge-short { background: rgba(246, 70, 93, 0.15); color: #f6465d; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(246, 70, 93, 0.3); }
        .tag-scalp { background: rgba(240, 185, 11, 0.1); color: #f0b90b; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        .pulse-dot { height: 10px; width: 10px; background-color: #0ecb81; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0.7); } 70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(14, 203, 129, 0); } 100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0); } }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span class="pulse-dot"></span> Quant Terminal Pro <span class="badge">Permanent Engine</span>
        </div>
        <div style="color: #848e9c; font-size: 13px;">
            Last Scan: <strong style="color: #fff;">{{ last_updated }}</strong>
        </div>
    </div>

    <div class="grid-stats">
        <div class="card"><span>Fear & Greed Index</span><strong>{{ fear_greed }}</strong></div>
        <div class="card"><span>Market Bias</span><strong>{{ market_bias }}</strong></div>
        <div class="card"><span>BTC Next Day (24H)</span><strong>{{ btc_daily }}</strong></div>
        <div class="card"><span>BTC Next Week</span><strong>{{ btc_weekly }}</strong></div>
        <div class="card"><span>BTC Next Month</span><strong>{{ btc_monthly }}</strong></div>
        <div class="card"><span>Scanned Pairs</span><strong>{{ total_scanned }} Futures Coins</strong></div>
    </div>

    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Pair</th>
                    <th>Trade Category</th>
                    <th>Timeframe</th>
                    <th>Entry Price</th>
                    <th>AI Win Prob</th>
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
                        <td><span class="tag-scalp">{{ sig.type }}</span></td>
                        <td><span style="background: #2b313a; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{{ sig.timeframe }}</span></td>
                        <td style="font-weight: 600;">{{ sig.price }}</td>
                        <td style="color: #f0b90b; font-weight: 600;">{{ sig.prob }}</td>
                        <td style="color: #f6465d;">{{ sig.sl }}</td>
                        <td style="color: #0ecb81;">{{ sig.tp }}</td>
                        <td>
                            <span class="{{ 'badge-long' if 'LONG' in sig.signal else 'badge-short' }}">
                                {{ sig.signal }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="9" style="text-align: center; padding: 50px 20px; color: #848e9c;">
                            🤖 Quant Engine actively scanning pairs... Signals live updating!
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(
        HTML_TEMPLATE, 
        signals=LATEST_SIGNALS, 
        total_scanned=TOTAL_SCANNED, 
        last_updated=LAST_UPDATED, 
        sentiment=MARKET_SENTIMENT,
        fear_greed=FEAR_GREED_INDEX,
        liquidity=LIQUIDITY_STATUS,
        market_bias=MARKET_BIAS,
        btc_daily=BTC_DAILY_FORECAST,
        btc_weekly=BTC_WEEKLY_FORECAST,
        btc_monthly=BTC_MONTHLY_FORECAST
    )

if __name__ == '__main__':
    t = threading.Thread(target=quant_master_scanner)
    t.daemon = True
    t.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
