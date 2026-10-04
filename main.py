import os
import time
import threading
import pandas as pd
import numpy as np
import ccxt
import logging
from flask import Flask, render_template_string
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Global Storage
LATEST_SIGNALS = []
TOTAL_SCANNED = 0
LAST_UPDATED = "N/A"

TIMEFRAMES = {
    '15M Scalp': '15m',
    '1H Swing': '1h',
    '4H Swing': '4h'
}

# Binance Futures Connection
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
})

def get_top_300_usdt_pairs():
    try:
        markets = exchange.load_markets()
        symbols = [symbol for symbol, market in markets.items() 
                   if market.get('swap') and market.get('quote') == 'USDT' and market.get('active', True)]
        if len(symbols) > 0:
            return symbols[:300]
        return ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT']
    except Exception as e:
        logging.error(f"Error fetching symbols: {e}")
        return ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'BNB/USDT:USDT', 'XRP/USDT:USDT']

def fetch_ohlcv(symbol, timeframe, limit=120):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception:
        return None

def compute_quant_indicators(df):
    # RSI (Probability & Momentum)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR (Risk Management & Volatility)
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()

    # Moving Averages
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()

    # Stochastic / Volatility Returns
    df['return'] = df['close'].pct_change()
    df['volatility'] = df['return'].rolling(10).std()
    
    # Target Setup for Machine Learning
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    return df.dropna()

def train_ensemble_agents(df):
    features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility']
    X = df[features]
    y = df['target']
    
    if len(X) < 35:
        return None, None

    # Agent 1: Random Forest Classifier
    rf_agent = RandomForestClassifier(n_estimators=60, max_depth=5, random_state=42)
    rf_agent.fit(X[:-1], y[:-1])

    # Agent 2: XGBoost Classifier
    xgb_agent = XGBClassifier(n_estimators=60, max_depth=4, learning_rate=0.05, eval_metric='logloss', random_state=42)
    xgb_agent.fit(X[:-1], y[:-1])

    return rf_agent, xgb_agent

def quant_background_scanner():
    global LATEST_SIGNALS, TOTAL_SCANNED, LAST_UPDATED
    while True:
        try:
            symbols = get_top_300_usdt_pairs()
            TOTAL_SCANNED = len(symbols)
            logging.info(f"Quant AI Engine Scanning {TOTAL_SCANNED} Pairs...")
            found_signals = []

            for symbol in symbols:
                for tf_name, tf_code in TIMEFRAMES.items():
                    df = fetch_ohlcv(symbol, tf_code)
                    if df is None or len(df) < 50:
                        continue

                    df = compute_quant_indicators(df)
                    if df.empty:
                        continue

                    rf_agent, xgb_agent = train_ensemble_agents(df)
                    if not rf_agent or not xgb_agent:
                        continue

                    latest = df.iloc[-1]
                    features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility']
                    current_features = [latest[features].tolist()]

                    # Agent Predictions & Probability
                    rf_prob = rf_agent.predict_proba(current_features)[0][1]
                    xgb_prob = xgb_agent.predict_proba(current_features)[0][1]

                    # Quant Multi-Agent Consensus Probability Score
                    consensus_score = float((rf_prob * 0.5) + (xgb_prob * 0.5)) * 100

                    price = float(latest['close'])
                    atr = float(latest['atr'])

                    signal = None
                    sl, tp = 0.0, 0.0

                    # Quant Strategy Rules with Probability Filter
                    if latest['rsi'] < 38 and latest['ema_9'] > latest['ema_21'] and consensus_score > 62:
                        signal = "BUY / LONG 🚀"
                        sl = price - (atr * 1.5)  # Dynamic Risk Management Stop Loss
                        tp = price + (atr * 3.0)  # 1:2 Risk Reward Take Profit
                    elif latest['rsi'] > 62 and latest['ema_9'] < latest['ema_21'] and consensus_score < 38:
                        signal = "SELL / SHORT 🔻"
                        consensus_score = 100 - consensus_score # Invert score for SHORT probability
                        sl = price + (atr * 1.5)
                        tp = price - (atr * 3.0)

                    if signal:
                        found_signals.append({
                            'symbol': symbol.replace(':USDT', ''),
                            'timeframe': tf_name,
                            'price': f"{price:.4f}",
                            'rsi': f"{latest['rsi']:.1f}",
                            'signal': signal,
                            'prob': f"{consensus_score:.1f}%",
                            'sl': f"{sl:.4f}",
                            'tp': f"{tp:.4f}",
                            'time': time.strftime('%H:%M:%S')
                        })

            LATEST_SIGNALS = found_signals
            LAST_UPDATED = time.strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"Quant Scan Finished. Signals Found: {len(LATEST_SIGNALS)}")
            time.sleep(90)
        except Exception as e:
            logging.error(f"Quant Loop Error: {e}")
            time.sleep(30)

# Institutional Quant Terminal UI Design
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuantPulse AI Terminal</title>
    <meta http-equiv="refresh" content="25">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: #080a0c; color: #eaebed; padding: 24px; min-height: 100vh; }
        .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid #1e232a; margin-bottom: 24px; flex-wrap: wrap; gap: 15px; }
        .logo { font-size: 22px; font-weight: 700; color: #f0b90b; display: flex; align-items: center; gap: 10px; }
        .quant-badge { background: rgba(240, 185, 11, 0.1); color: #f0b90b; padding: 4px 8px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(240, 185, 11, 0.3); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: #12161c; padding: 16px; border-radius: 10px; border: 1px solid #1e232a; }
        .stat-card span { color: #848e9c; font-size: 12px; display: block; margin-bottom: 6px; }
        .stat-card strong { font-size: 18px; color: #ffffff; }
        .table-wrapper { background: #12161c; border-radius: 12px; border: 1px solid #1e232a; overflow-x: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        table { width: 100%; border-collapse: collapse; text-align: left; }
        th { background-color: #0d1015; color: #848e9c; font-size: 12px; font-weight: 600; text-transform: uppercase; padding: 16px 20px; border-bottom: 1px solid #1e232a; }
        td { padding: 16px 20px; border-bottom: 1px solid #1e232a; font-size: 14px; }
        tr:hover { background-color: #1a1f26; }
        .badge-long { background: rgba(14, 203, 129, 0.15); color: #0ecb81; padding: 6px 12px; border-radius: 6px; font-weight: 600; font-size: 13px; display: inline-block; border: 1px solid rgba(14, 203, 129, 0.3); }
        .badge-short { background: rgba(246, 70, 93, 0.15); color: #f6465d; padding: 6px 12px; border-radius: 6px; font-weight: 600; font-size: 13px; display: inline-block; border: 1px solid rgba(246, 70, 93, 0.3); }
        .prob-pill { background: #1e232a; color: #f0b90b; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px; }
        .pulse-dot { height: 10px; width: 10px; background-color: #0ecb81; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0.7); } 70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(14, 203, 129, 0); } 100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(14, 203, 129, 0); } }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">
            <span class="pulse-dot"></span> QuantPulse AI Terminal <span class="quant-badge">Ensemble Multi-Agent</span>
        </div>
        <div style="color: #848e9c; font-size: 13px;">
            Last Quant Sync: <strong style="color: #eaebed;">{{ last_updated }}</strong>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card"><span>Scanned Futures</span><strong>{{ total_scanned }} Pairs</strong></div>
        <div class="stat-card"><span>Active Signals</span><strong>{{ signals|length }} Detected</strong></div>
        <div class="stat-card"><span>AI Engines</span><strong>RandomForest + XGBoost</strong></div>
        <div class="stat-card"><span>Risk Protocol</span><strong>ATR Dynamic SL/TP (1:2)</strong></div>
    </div>

    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Coin Pair</th>
                    <th>Strategy</th>
                    <th>Price ($)</th>
                    <th>Win Prob</th>
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
                        <td><span style="background: #1e232a; padding: 4px 8px; border-radius: 4px; font-size: 12px; color: #848e9c;">{{ sig.timeframe }}</span></td>
                        <td style="font-weight: 600;">${{ sig.price }}</td>
                        <td><span class="prob-pill">{{ sig.prob }}</span></td>
                        <td style="color: #f6465d; font-weight: 500;">${{ sig.sl }}</td>
                        <td style="color: #0ecb81; font-weight: 500;">${{ sig.tp }}</td>
                        <td>
                            <span class="{{ 'badge-long' if 'LONG' in sig.signal else 'badge-short' }}">
                                {{ sig.signal }}
                            </span>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="8" style="text-align: center; padding: 60px 20px; color: #848e9c;">
                            🤖 Quant Multi-Agent System is analyzing Binance Futures data... Signals with SL/TP & High Win Probability will appear automatically.
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
    return render_template_string(HTML_TEMPLATE, signals=LATEST_SIGNALS, total_scanned=TOTAL_SCANNED, last_updated=LAST_UPDATED)

if __name__ == '__main__':
    t = threading.Thread(target=quant_background_scanner)
    t.daemon = True
    t.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
