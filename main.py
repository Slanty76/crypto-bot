import os
import time
import threading
import numpy as np
import pandas as pd
import ccxt
import logging
import requests
from flask import Flask, render_template_string

# 1. Quant Machine Learning & AI Tools
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

# 2. PyTorch & SciPy Stats
import torch
from scipy.stats import norm

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Global Storage
LATEST_SIGNALS = []
TOTAL_SCANNED = 0
LAST_UPDATED = "N/A"
MARKET_SENTIMENT = "Neutral"

TIMEFRAMES = {
    '15M Scalp': '15m',
    '1H Swing': '1h',
    '4H Swing': '4h'
}

# Reliable Top USDT Perpetual Futures Pairs List (Bypasses Geo-Block)
TOP_FUTURES_PAIRS = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT',
    'ADA/USDT:USDT', 'AVAX/USDT:USDT', 'DOGE/USDT:USDT', 'DOT/USDT:USDT', 'LINK/USDT:USDT',
    'MATIC/USDT:USDT', 'NEAR/USDT:USDT', 'APT/USDT:USDT', 'SUI/USDT:USDT', 'OP/USDT:USDT',
    'ARB/USDT:USDT', 'LTC/USDT:USDT', 'BCH/USDT:USDT', 'ETC/USDT:USDT', 'ATOM/USDT:USDT',
    'FIL/USDT:USDT', 'TRX/USDT:USDT', 'INJ/USDT:USDT', 'TIA/USDT:USDT', 'FET/USDT:USDT',
    'RNDR/USDT:USDT', 'STX/USDT:USDT', 'GALA/USDT:USDT', 'SHIB/USDT:USDT', 'PEPE/USDT:USDT',
    'WIF/USDT:USDT', 'FLOKI/USDT:USDT', 'BONK/USDT:USDT', 'AR/USDT:USDT', 'FET/USDT:USDT',
    'AGIX/USDT:USDT', 'OCEAN/USDT:USDT', 'GMX/USDT:USDT', 'PENDLE/USDT:USDT', 'JUP/USDT:USDT'
]

def fetch_ohlcv_public(symbol, timeframe, limit=100):
    """Fetches Kline/OHLCV data directly using Binance Public Endpoint to avoid Geo-Restrictions"""
    try:
        clean_symbol = symbol.replace('/', '').replace(':USDT', '')
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={clean_symbol}&interval={timeframe}&limit={limit}"
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume', 
                'close_time', 'qav', 'num_trades', 'tbv', 'tqv', 'ignore'
            ])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logging.error(f"Error fetching data for {symbol}: {e}")
    return None

def compute_quant_features(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR (Average True Range)
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()

    # Moving Averages
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()

    # Volatility & Returns
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(10).std()
    df['drift'] = df['returns'].rolling(10).mean() - (0.5 * (df['volatility'] ** 2))

    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    return df.dropna()

def train_ml_agents(df):
    features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility', 'drift']
    X = df[features]
    y = df['target']
    
    if len(X) < 30:
        return None, None

    rf_agent = RandomForestClassifier(n_estimators=40, max_depth=4, random_state=42)
    rf_agent.fit(X[:-1], y[:-1])

    xgb_agent = XGBClassifier(n_estimators=40, max_depth=3, learning_rate=0.05, eval_metric='logloss', random_state=42)
    xgb_agent.fit(X[:-1], y[:-1])

    return rf_agent, xgb_agent

def quant_master_scanner():
    global LATEST_SIGNALS, TOTAL_SCANNED, LAST_UPDATED, MARKET_SENTIMENT
    while True:
        try:
            symbols = TOP_FUTURES_PAIRS
            TOTAL_SCANNED = len(symbols)
            logging.info(f"Quant Engine Scanning {TOTAL_SCANNED} Pairs across Scalp & Swing...")
            found_signals = []

            btc_df = fetch_ohlcv_public('BTC/USDT:USDT', '1h', limit=30)
            if btc_df is not None and not btc_df.empty:
                btc_change = ((btc_df['close'].iloc[-1] - btc_df['close'].iloc[0]) / btc_df['close'].iloc[0]) * 100
                if btc_change > 0.8:
                    MARKET_SENTIMENT = "Bullish Momentum 🚀"
                elif btc_change < -0.8:
                    MARKET_SENTIMENT = "Bearish Pressure 🔻"
                else:
                    MARKET_SENTIMENT = "Sideways / Ranging 🔄"

            for symbol in symbols:
                for tf_name, tf_code in TIMEFRAMES.items():
                    df = fetch_ohlcv_public(symbol, tf_code)
                    if df is None or len(df) < 40:
                        continue

                    df = compute_quant_features(df)
                    if df.empty:
                        continue

                    rf_agent, xgb_agent = train_ml_agents(df)
                    if not rf_agent or not xgb_agent:
                        continue

                    latest = df.iloc[-1]
                    features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility', 'drift']
                    current_features = [latest[features].tolist()]

                    rf_prob = rf_agent.predict_proba(current_features)[0][1]
                    xgb_prob = xgb_agent.predict_proba(current_features)[0][1]

                    win_probability = float((rf_prob * 0.5) + (xgb_prob * 0.5)) * 100

                    price = float(latest['close'])
                    atr = float(latest['atr'])

                    # Scalp vs Swing Setup Rules
                    sl_multiplier = 1.2 if 'Scalp' in tf_name else 2.0
                    tp_multiplier = 2.4 if 'Scalp' in tf_name else 4.0

                    signal = None
                    trade_type = "SCALP" if "Scalp" in tf_name else "SWING"
                    sl, tp = 0.0, 0.0

                    if latest['rsi'] < 42 and latest['ema_9'] > latest['ema_21'] and win_probability > 58:
                        signal = "BUY / LONG 🚀"
                        sl = price - (atr * sl_multiplier)
                        tp = price + (atr * tp_multiplier)
                    elif latest['rsi'] > 58 and latest['ema_9'] < latest['ema_21'] and win_probability < 42:
                        signal = "SELL / SHORT 🔻"
                        win_probability = 100 - win_probability
                        sl = price + (atr * sl_multiplier)
                        tp = price - (atr * tp_multiplier)

                    if signal:
                        found_signals.append({
                            'symbol': symbol.replace(':USDT', ''),
                            'type': trade_type,
                            'timeframe': tf_name,
                            'price': f"${price:.4f}",
                            'prob': f"{win_probability:.1f}%",
                            'sl': f"${sl:.4f}",
                            'tp': f"${tp:.4f}",
                            'signal': signal,
                            'time': time.strftime('%H:%M:%S')
                        })

            LATEST_SIGNALS = found_signals
            LAST_UPDATED = time.strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"Quant Scan Finished. Signals Found: {len(LATEST_SIGNALS)}")
            time.sleep(60)
        except Exception as e:
            logging.error(f"Quant Loop Error: {e}")
            time.sleep(20)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant AI Terminal - Crypto Scalp & Swing Hub</title>
    <meta http-equiv="refresh" content="20">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #0b0e11; color: #eaebed; padding: 20px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid #1e232a; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .title { font-size: 22px; font-weight: 700; color: #f0b90b; display: flex; align-items: center; gap: 10px; }
        .badge { background: rgba(240, 185, 11, 0.15); color: #f0b90b; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(240, 185, 11, 0.3); }
        .grid-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .card { background: #181a20; padding: 15px; border-radius: 8px; border: 1px solid #2b313a; }
        .card span { color: #848e9c; font-size: 12px; display: block; margin-bottom: 5px; }
        .card strong { font-size: 16px; color: #fff; }
        .table-wrapper { background: #181a20; border-radius: 10px; border: 1px solid #2b313a; overflow-x: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { background-color: #121418; color: #848e9c; font-size: 11px; font-weight: 600; text-transform: uppercase; padding: 14px 16px; border-bottom: 1px solid #2b313a; }
        td { padding: 14px 16px; border-bottom: 1px solid #2b313a; font-size: 13px; }
        tr:hover { background-color: #2b313a; }
        .badge-long { background: rgba(14, 203, 129, 0.15); color: #0ecb81; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(14, 203, 129, 0.3); }
        .badge-short { background: rgba(246, 70, 93, 0.15); color: #f6465d; padding: 6px 10px; border-radius: 6px; font-weight: 600; border: 1px solid rgba(246, 70, 93, 0.3); }
        .tag-scalp { background: rgba(240, 185, 11, 0.1); color: #f0b90b; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        .tag-swing { background: rgba(112, 128, 144, 0.2); color: #00d2ff; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        .pulse-dot { height: 10px; width: 10px; background-color: #0ecb81; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0.7); } 70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(14, 203, 129, 0); } 100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0); } }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">
            <span class="pulse-dot"></span> Quant AI Pro Terminal <span class="badge">Scalp & Swing Live</span>
        </div>
        <div style="color: #848e9c; font-size: 13px;">
            Last Scan: <strong style="color: #fff;">{{ last_updated }}</strong>
        </div>
    </div>

    <div class="grid-stats">
        <div class="card"><span>Market Sentiment</span><strong>{{ sentiment }}</strong></div>
        <div class="card"><span>Scanned Pairs</span><strong>{{ total_scanned }} Futures Coins</strong></div>
        <div class="card"><span>Active Signals</span><strong>{{ signals|length }} Detected</strong></div>
        <div class="card"><span>AI Engines</span><strong>Random Forest + XGBoost</strong></div>
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
                        <td>
                            <span class="{{ 'tag-scalp' if sig.type == 'SCALP' else 'tag-swing' }}">
                                {{ sig.type }}
                            </span>
                        </td>
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
                            🤖 Quant AI Multi-Agent System is scanning 40+ Futures pairs... High win-rate Scalp & Swing setups will auto-refresh here.
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
    return render_template_string(HTML_TEMPLATE, signals=LATEST_SIGNALS, total_scanned=TOTAL_SCANNED, last_updated=LAST_UPDATED, sentiment=MARKET_SENTIMENT)

if __name__ == '__main__':
    t = threading.Thread(target=quant_master_scanner)
    t.daemon = True
    t.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
