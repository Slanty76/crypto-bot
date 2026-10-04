import time
import requests
import pandas as pd
import numpy as np
import ccxt
import logging
from sklearn.ensemble import RandomForestClassifier

# Logging Configuration
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Configuration
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

TIMEFRAMES = {
    'SCALPING_15M': '15m',
    'SWING_1H': '1h',
    'SWING_4H': '4h'
}

# CCXT Binance Global Exchange Setup
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    },
    'urls': {
        'api': {
            'public': 'https://binance-proxy.zerodev.workers.dev/api/v3',
            'fapiPublic': 'https://binance-proxy.zerodev.workers.dev/fapi/v1',
            'fapiPublicV2': 'https://binance-proxy.zerodev.workers.dev/fapi/v2',
        }
    }
})

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Telegram Notification Error: {e}")

def get_top_300_usdt_pairs():
    try:
        markets = exchange.load_markets()
        symbols = []
        for symbol, market in markets.items():
            if market.get('swap') and market.get('quote') == 'USDT' and market.get('active', True):
                symbols.append(symbol)
        
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
    except Exception as e:
        return None

def compute_indicators(df):
    # 1. RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # 2. ATR (14)
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()

    # 3. EMA
    df['ema_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

    return df

def generate_features(df):
    df['return'] = df['close'].pct_change()
    df['volatility'] = df['return'].rolling(10).std()
    df['target'] = np.where(df['close'].shift(-1) > df['close'], 1, 0)
    return df.dropna()

def train_ml_model(df):
    features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility']
    X = df[features]
    y = df['target']
    
    if len(X) < 30:
        return None
        
    model = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
    model.fit(X[:-1], y[:-1])
    return model

def analyze_market():
    symbols = get_top_300_usdt_pairs()
    logging.info(f"Scanning {len(symbols)} Binance pairs across multiple timeframes...")

    for symbol in symbols:
        try:
            for tf_name, tf_code in TIMEFRAMES.items():
                df = fetch_ohlcv(symbol, tf_code)
                if df is None or len(df) < 50:
                    continue

                df = compute_indicators(df)
                df_feat = generate_features(df)
                
                if df_feat.empty:
                    continue

                model = train_ml_model(df_feat)
                latest = df_feat.iloc[-1]

                # Prediction
                features = ['rsi', 'atr', 'ema_9', 'ema_21', 'volatility']
                pred = model.predict([latest[features]])[0] if model else 0

                # Signal Logic
                signal = None
                if latest['rsi'] < 35 and latest['ema_9'] > latest['ema_21'] and pred == 1:
                    signal = "BUY/LONG"
                elif latest['rsi'] > 65 and latest['ema_9'] < latest['ema_21'] and pred == 0:
                    signal = "SELL/SHORT"

                if signal:
                    msg = (
                        f"🚨 <b>{signal} SIGNAL DETECTED</b> 🚨\n\n"
                        f"<b>Pair:</b> {symbol}\n"
                        f"<b>Timeframe:</b> {tf_name} ({tf_code})\n"
                        f"<b>Price:</b> {latest['close']:.4f}\n"
                        f"<b>RSI:</b> {latest['rsi']:.2f}\n"
                        f"<b>EMA 9/21:</b> {latest['ema_9']:.4f} / {latest['ema_21']:.4f}\n"
                    )
                    send_telegram(msg)
                    logging.info(f"Signal sent for {symbol} on {tf_name}")

        except Exception as e:
            logging.error(f"Error processing {symbol}: {e}")

if __name__ == "__main__":
    while True:
        try:
            analyze_market()
            logging.info("Scan completed. Sleeping for 3 minutes...")
            time.sleep(180)
        except Exception as e:
            logging.error(f"Main loop error: {e}")
            time.sleep(60)
