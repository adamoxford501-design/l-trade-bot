import yfinance as yf
import ccxt
import pandas as pd
import numpy as np
import mplfinance as mpf
import tempfile
import os
import json
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from datetime import datetime
import asyncio
import logging
from collections import deque

# ---------- CONFIG ----------
TELEGRAM_TOKEN = "8511168805:AAFMV_AwHsgVVMBmvBTmfYYicRyJ5E7qcsU"
ADMIN_CHAT_ID = 8457706605
WELCOME_VIDEO_URL = "https://files.catbox.moe/ykynt9.mp4"
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Deposit Addresses
DEPOSIT_ADDRESSES = {
    "TRC20 (USDT)": "TLC8bebj9L57ZsihNiY32d4nWH8CVDvLpu",
    "BEP20 (USDT)": "0xc09B4D0a9b0EDfbE30753F5b79360a4F82e570a1",
    "ERC20 (USDT)": "0x798022D87F929f576191722A8431340aF5282bD4",
    "BITCOIN": "bc1q5agzp3dtmv2yk7mth7gj76a0k60rv22r5ldnjc",
    "SOLANA": "36vUEHqYxpLn54yreV7YLPgunuxoUMLcwpH7NUcunA78",
    "TON": "UQC-HTnL3mvMe3GiZ-6hu15MUW5r5pA_M-Q-cZhAULtQ-pmt"
}

# File paths for persistence
WALLETS_FILE = "user_wallets.json"
POSITIONS_FILE = "user_positions.json"

def load_wallets():
    if os.path.exists(WALLETS_FILE):
        try:
            with open(WALLETS_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_wallets():
    try:
        with open(WALLETS_FILE, 'w') as f:
            to_save = {str(k): v for k, v in user_wallets.items()}
            json.dump(to_save, f, indent=4, default=str)
    except:
        pass

def load_positions():
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_positions():
    try:
        with open(POSITIONS_FILE, 'w') as f:
            to_save = {str(k): v for k, v in user_positions.items()}
            json.dump(to_save, f, indent=4, default=str)
    except:
        pass

# ---------- STORAGE ----------
user_wallets = load_wallets()
user_positions = load_positions()
user_trades = {}
pending_deposits = {}
pending_withdrawals = {}
request_counter = 0

def save_wallet(user_id, address, wallet_type):
    user_wallets[user_id] = {
        'address': address, 
        'balance': 0, 
        'deposits': [], 
        'withdrawals': [], 
        'wallet_type': wallet_type, 
        'connected_on': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_wallets()
    return True

def get_wallet(user_id):
    return user_wallets.get(user_id, None)

def add_balance(user_id, amount):
    if user_id in user_wallets:
        user_wallets[user_id]['balance'] += amount
        user_wallets[user_id]['deposits'].append({'amount': amount, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        save_wallets()
        return True
    return False

def deduct_balance(user_id, amount):
    if user_id in user_wallets and user_wallets[user_id]['balance'] >= amount:
        user_wallets[user_id]['balance'] -= amount
        user_wallets[user_id]['withdrawals'].append({'amount': amount, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        save_wallets()
        return True
    return False

def add_position(user_id, symbol, entry_price, amount, quantity, order_type='BUY'):
    if user_id not in user_positions:
        user_positions[user_id] = []
    
    position = {
        'symbol': symbol,
        'entry': entry_price,
        'amount': amount,
        'quantity': quantity,
        'order_type': order_type,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    user_positions[user_id].append(position)
    save_positions()
    return True

def get_positions(user_id):
    return user_positions.get(user_id, [])

def add_trade(user_id, symbol, signal_type, entry, exit_price, pnl, confidence, timestamp):
    if user_id not in user_trades:
        user_trades[user_id] = deque(maxlen=20)
    trade = {'symbol': symbol, 'signal': signal_type, 'entry': entry, 'exit': exit_price, 'pnl': pnl, 'confidence': confidence, 'timestamp': timestamp}
    user_trades[user_id].appendleft(trade)
    return True

def get_recent_trades(user_id):
    if user_id not in user_trades or not user_trades[user_id]:
        return None
    return list(user_trades[user_id])

# ---------- KEYBOARD LAYOUTS ----------
def get_main_keyboard():
    keyboard = [
        ["🪙 CRYPTO SIGNALS", "💱 FOREX SIGNALS"],
        ["📈 STOCK SIGNALS", "🌍 ALL MARKETS"],
        ["👛 MY WALLET", "📊 MY POSITIONS"],
        ["💰 DEPOSIT", "💸 WITHDRAW"],
        ["❓ HELP & SUPPORT", "📞 CONTACT DEVELOPER"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_wallet_type_keyboard():
    keyboard = [
        ["💎 TON", "🪙 TRC20 (USDT)"],
        ["🔷 BEP20 (USDT)", "💠 ERC20 (USDT)"],
        ["₿ BITCOIN", "◎ SOLANA"],
        ["🔙 BACK TO MAIN MENU"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_crypto_keyboard():
    keyboard = [
        ["₿ BTC/USDT", "⟠ ETH/USDT"],
        ["◎ SOL/USDT", "🐕 DOGE/USDT"],
        ["💱 XRP/USDT", "⬆️ ADA/USDT"],
        ["🏔️ AVAX/USDT", "🟣 MATIC/USDT"],
        ["🔙 BACK TO MAIN MENU"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_forex_keyboard():
    keyboard = [
        ["💶 EUR/USD", "💷 GBP/USD"],
        ["💴 USD/JPY", "🦘 AUD/USD"],
        ["🍁 USD/CAD", "🇨🇭 USD/CHF"],
        ["🇳🇿 NZD/USD", "🇪🇺 EUR/GBP"],
        ["🔙 BACK TO MAIN MENU"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_stocks_keyboard():
    keyboard = [
        ["🍎 AAPL", "🔍 GOOGL"],
        ["🪟 MSFT", "🚗 TSLA"],
        ["🎮 NVDA", "📦 AMZN"],
        ["📘 META", "🎬 NFLX"],
        ["🔙 BACK TO MAIN MENU"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_deposit_amount_keyboard():
    keyboard = [
        ["💰 $10", "💰 $25", "💰 $50"],
        ["💰 $100", "💰 $250", "💰 $500"],
        ["💰 $1000", "💰 CUSTOM", "🔙 BACK TO MAIN MENU"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------- CHART GENERATOR ----------
def generate_candlestick_chart(symbol, asset_type="crypto", period="7d", interval="1h"):
    try:
        if asset_type == "crypto":
            exchange = ccxt.binance()
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=interval, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
        elif asset_type == "forex":
            forex_pair = symbol.replace("/", "") + "=X"
            ticker = yf.Ticker(forex_pair)
            df = ticker.history(period=period, interval=interval)
        else:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
        
        if df.empty or len(df) < 20:
            return None
        
        df['SMA20'] = df['Close'].rolling(window=20).mean()
        df['SMA50'] = df['Close'].rolling(window=50).mean()
        
        mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', edge='#333333', wick='#888888', volume='#3399ff', ohlc='#ffffff')
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True, facecolor='#0d0d1a', edgecolor='#333333', figcolor='#0d0d1a', gridcolor='#2a2a3a')
        apds = [mpf.make_addplot(df['SMA20'], color='#ffa500', width=1), mpf.make_addplot(df['SMA50'], color='#00ffff', width=1)]
        
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        title = f"{symbol} | {asset_type.upper()} | {interval} Timeframe"
        mpf.plot(df, type='candle', style=s, volume=True, addplot=apds, title=title, ylabel='Price', ylabel_lower='Volume', savefig=temp_path, figsize=(12, 8), tight_layout=True)
        return temp_path
    except Exception as e:
        logging.error(f"Chart error: {e}")
        return None

def calculate_rsi(data, period=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(df, period=14):
    high = df['High']; low = df['Low']; close = df['Close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.iloc[-1]

def generate_signal(symbol, asset_type="crypto", timeframe="1h"):
    try:
        if asset_type == "crypto":
            exchange = ccxt.binance()
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            current_price = df['Close'].iloc[-1]
        elif asset_type == "forex":
            forex_pair = symbol.replace("/", "") + "=X"
            ticker = yf.Ticker(forex_pair)
            df = ticker.history(period="7d", interval=timeframe)
            current_price = df['Close'].iloc[-1]
        else:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="7d", interval=timeframe)
            current_price = df['Close'].iloc[-1]
        
        if df.empty or len(df) < 50:
            return None
        
        closes = df['Close']
        rsi = calculate_rsi(closes)
        atr = calculate_atr(df)
        
        current_rsi = rsi.iloc[-1]
        current_price = closes.iloc[-1]
        
        buy_score = 0
        sell_score = 0
        signal_reasons = []
        
        if current_rsi < RSI_OVERSOLD:
            buy_score += 3
            signal_reasons.append(f"📉 RSI Oversold: {current_rsi:.1f}")
        elif current_rsi > RSI_OVERBOUGHT:
            sell_score += 3
            signal_reasons.append(f"📈 RSI Overbought: {current_rsi:.1f}")
        
        sma20 = closes.rolling(window=20).mean()
        sma50 = closes.rolling(window=50).mean()
        
        if sma20.iloc[-1] > sma50.iloc[-1]:
            buy_score += 2
            signal_reasons.append("📈 Bullish Trend (SMA20 > SMA50)")
        else:
            sell_score += 2
            signal_reasons.append("📉 Bearish Trend (SMA20 < SMA50)")
        
        total_score = abs(buy_score - sell_score)
        
        entry = current_price
        tp1 = current_price; tp2 = current_price; tp3 = current_price; sl = current_price; rr_ratio = 0; pips = None
        
        if buy_score > sell_score and total_score >= 3:
            signal_type = "🟢 BUY"
            confidence = "🔥 HIGH" if total_score >= 6 else "⚡ MEDIUM"
            entry = current_price
            tp1 = entry + (atr * 1.5); tp2 = entry + (atr * 2.5); tp3 = entry + (atr * 4)
            sl = entry - (atr * 1.5)
            rr_ratio = round(abs(tp1 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
        elif sell_score > buy_score and total_score >= 3:
            signal_type = "🔴 SELL"
            confidence = "🔥 HIGH" if total_score >= 6 else "⚡ MEDIUM"
            entry = current_price
            tp1 = entry - (atr * 1.5); tp2 = entry - (atr * 2.5); tp3 = entry - (atr * 4)
            sl = entry + (atr * 1.5)
            rr_ratio = round(abs(tp1 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
        else:
            signal_type = "⚪ NEUTRAL"
            confidence = "💤 LOW"
        
        if asset_type == "forex" and signal_type != "⚪ NEUTRAL":
            pip_value = 0.0001
            pips = round(abs(tp1 - entry) / pip_value, 1)
        
        return {
            'signal': signal_type, 'confidence': confidence, 'entry': entry, 'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
            'sl': sl, 'rr_ratio': rr_ratio, 'pips': pips, 'reasons': signal_reasons,
            'rsi': round(current_rsi, 1), 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logging.error(f"Signal error: {e}")
        return None

# ---------- SIGNAL + CHART + CUSTOM AMOUNT BUY BUTTONS ----------
async def send_signal_with_chart(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol, asset_type, name):
    user_id = update.effective_user.id
    await update.message.reply_text(f"📊 *FETCHING SIGNAL FOR {name}* 🔍\n\n⏳ *Analyzing live market data...*", parse_mode='Markdown')
    
    signal = generate_signal(symbol, asset_type, "1h")
    if not signal:
        await update.message.reply_text(f"❌ *Could not fetch signal for {name}*", parse_mode='Markdown')
        return
    
    chart_path = generate_candlestick_chart(symbol, asset_type, "7d", "1h")
    
    msg = f"""
📊 *{name}* | {asset_type.upper()} SIGNAL
━━━━━━━━━━━━━━━━━━━━━
⏰ {signal['timestamp']}
━━━━━━━━━━━━━━━━━━━━━
📈 *SIGNAL:* {signal['signal']}
🎯 *Confidence:* {signal['confidence']}
━━━━━━━━━━━━━━━━━━━━━
💰 *ENTRY:* `${signal['entry']:.4f}`
🎯 *TP1:* `${signal['tp1']:.4f}`
🎯 *TP2:* `${signal['tp2']:.4f}`
🎯 *TP3:* `${signal['tp3']:.4f}`
🛑 *SL:* `${signal['sl']:.4f}`
━━━━━━━━━━━━━━━━━━━━━
📈 *Risk:Reward Ratio:* `1:{signal['rr_ratio']}`
📊 *RSI:* `{signal['rsi']}`
━━━━━━━━━━━━━━━━━━━━━
💡 *REASONS:*\n"""
    for r in signal['reasons'][:3]:
        msg += f"  • {r}\n"
    
    keyboard = [
        [InlineKeyboardButton("🟢 BUY (Custom Amount)", callback_data=f"custom_buy_{symbol}_{asset_type}_{signal['entry']}"),
         InlineKeyboardButton("🔴 SELL", callback_data=f"sell_{symbol}_{asset_type}_{signal['entry']}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if chart_path and os.path.exists(chart_path):
        try:
            with open(chart_path, 'rb') as chart:
                await update.message.reply_photo(photo=chart, caption=msg, reply_markup=reply_markup, parse_mode='Markdown')
            os.unlink(chart_path)
        except Exception as e:
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

# ---------- CUSTOM AMOUNT BUY HANDLER ----------
async def custom_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    symbol = data[2]
    asset_type = data[3]
    entry_price = float(data[4])
    user_id = update.effective_user.id
    
    wallet = get_wallet(user_id)
    if not wallet:
        await query.message.reply_text("❌ *Wallet not connected!*\n\nUse 👛 MY WALLET to connect your wallet first.", parse_mode='Markdown')
        return
    
    if wallet['balance'] < 10:
        await query.message.reply_text(f"❌ *Insufficient balance!*\n\nYour balance: ${wallet['balance']:.2f}\nMinimum trade: $10", parse_mode='Markdown')
        return
    
    await query.message.reply_text(
        f"💰 *ENTER TRADE AMOUNT* 💰\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Symbol:* {symbol}\n"
        f"💰 *Entry Price:* ${entry_price:.4f}\n"
        f"💰 *Your Balance:* ${wallet['balance']:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Enter the amount in USD you want to invest (min $10, max ${wallet['balance']:.2f}):\n\n"
        f"Example: `100`",
        parse_mode='Markdown'
    )
    
    context.user_data['pending_custom_buy'] = {
        'symbol': symbol,
        'asset_type': asset_type,
        'entry_price': entry_price,
        'user_id': user_id
    }

async def process_custom_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('pending_custom_buy'):
        return
    
    try:
        trade_data = context.user_data['pending_custom_buy']
        amount = float(update.message.text.strip())
        user_id = trade_data['user_id']
        symbol = trade_data['symbol']
        asset_type = trade_data['asset_type']
        entry_price = trade_data['entry_price']
        
        wallet = get_wallet(user_id)
        
        if amount < 10:
            await update.message.reply_text("❌ *Minimum trade amount is $10!*", parse_mode='Markdown')
        elif amount > wallet['balance']:
            await update.message.reply_text(f"❌ *Insufficient balance!*\n\nYour balance: ${wallet['balance']:.2f}\nRequested: ${amount:.2f}", parse_mode='Markdown')
        else:
            quantity = round(amount / entry_price, 6)
            deduct_balance(user_id, amount)
            add_position(user_id, symbol, entry_price, amount, quantity, 'BUY')
            
            confirm_msg = f"""
✅ *BUY ORDER PLACED!* ✅

━━━━━━━━━━━━━━━━━━━━━
📊 *Symbol:* {symbol}
💰 *Entry Price:* ${entry_price:.4f}
💵 *Amount:* ${amount:.2f}
📦 *Quantity:* {quantity} {symbol.replace('/USDT', '')}
━━━━━━━━━━━━━━━━━━━━━

🎯 *TP1:* ${entry_price * 1.02:.4f}
🎯 *TP2:* ${entry_price * 1.04:.4f}
🛑 *SL:* ${entry_price * 0.98:.4f}

💰 *Remaining Balance:* ${wallet['balance'] - amount:.2f}

⚠️ *Monitor your position! Use /positions to track P&L*
"""
            await update.message.reply_text(confirm_msg, parse_mode='Markdown')
            await update.message.reply_text("🔙 *Back to Main Menu*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ *Please enter a valid number!*", parse_mode='Markdown')
    
    context.user_data['pending_custom_buy'] = None

# ---------- SELL CALLBACK ----------
async def sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    symbol = data[1]
    asset_type = data[2]
    entry_price = float(data[3])
    user_id = update.effective_user.id
    
    # Get current price
    try:
        if asset_type == "crypto":
            exchange = ccxt.binance()
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
        elif asset_type == "forex":
            forex_pair = symbol.replace("/", "") + "=X"
            ticker = yf.Ticker(forex_pair)
            current_price = ticker.history(period="1d", interval="1m")['Close'].iloc[-1]
        else:
            ticker = yf.Ticker(symbol)
            current_price = ticker.history(period="1d", interval="1m")['Close'].iloc[-1]
    except:
        current_price = entry_price
    
    wallet = get_wallet(user_id)
    if not wallet:
        await query.message.reply_text("❌ *Wallet not connected!*", parse_mode='Markdown')
        return
    
    profit_percent = ((current_price - entry_price) / entry_price) * 100
    profit_amount = (wallet['balance'] * 0.1) * (profit_percent / 100)
    
    add_balance(user_id, profit_amount)
    
    confirm_msg = f"""
✅ *SELL ORDER EXECUTED!* ✅

━━━━━━━━━━━━━━━━━━━━━
📊 *Symbol:* {symbol}
💰 *Entry:* ${entry_price:.4f}
💰 *Exit:* ${current_price:.4f}
📈 *P&L:* {profit_percent:+.2f}% (${profit_amount:+.2f})
━━━━━━━━━━━━━━━━━━━━━

💰 *New Balance:* ${get_wallet(user_id)['balance']:.2f}
"""
    await query.message.reply_text(confirm_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]), parse_mode='Markdown')
    
    try:
        await query.message.delete()
    except:
        pass

# ---------- POSITIONS HANDLER ----------
async def show_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    positions = get_positions(user_id)
    wallet = get_wallet(user_id)
    
    if not positions:
        await update.message.reply_text(
            "📊 *NO OPEN POSITIONS* 📊\n\n━━━━━━━━━━━━━━━━━━━━━\nYou don't have any open trades.\n\nClick BUY on any signal to start trading!\n━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    msg = "📊 *YOUR OPEN POSITIONS* 📊\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    total_pnl = 0
    
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        entry = pos['entry']
        amount = pos['amount']
        
        # Get current price
        try:
            if 'USDT' in symbol:
                exchange = ccxt.binance()
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
            else:
                ticker = yf.Ticker(symbol)
                current_price = ticker.history(period="1d", interval="5m")['Close'].iloc[-1]
        except:
            current_price = entry
        
        pnl_percent = ((current_price - entry) / entry) * 100
        pnl_amount = amount * (pnl_percent / 100)
        total_pnl += pnl_amount
        
        emoji = "🟢" if pnl_amount > 0 else "🔴" if pnl_amount < 0 else "⚪"
        
        msg += f"{emoji} *{i}. {symbol}*\n"
        msg += f"   💰 Entry: ${entry:.4f}\n"
        msg += f"   📈 Current: ${current_price:.4f}\n"
        msg += f"   💵 Amount: ${amount:.2f}\n"
        msg += f"   📊 P&L: {pnl_percent:+.2f}% (${pnl_amount:+.2f})\n"
        msg += f"   ⏰ Opened: {pos['timestamp']}\n"
        msg += "   ━━━━━━━━━━━━━━━━━\n"
    
    msg += f"\n💰 *Total P&L:* ${total_pnl:+.2f}"
    msg += f"\n💵 *Wallet Balance:* ${wallet['balance']:.2f}"
    
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

# ---------- WALLET HANDLERS ----------
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👛 *CONNECT YOUR WALLET* 👛\n\n━━━━━━━━━━━━━━━━━━━━━\nSelect your wallet type below:\n\n💎 TON Network\n🪙 TRC20 (USDT)\n🔷 BEP20 (USDT)\n💠 ERC20 (USDT)\n₿ BITCOIN\n◎ SOLANA\n━━━━━━━━━━━━━━━━━━━━━\n👇 *Click a button below:*",
        reply_markup=get_wallet_type_keyboard(),
        parse_mode='Markdown'
    )

async def handle_wallet_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    wallet_type_map = {
        "💎 TON": "TON",
        "🪙 TRC20 (USDT)": "TRC20",
        "🔷 BEP20 (USDT)": "BEP20",
        "💠 ERC20 (USDT)": "ERC20",
        "₿ BITCOIN": "BITCOIN",
        "◎ SOLANA": "SOLANA"
    }
    
    if text in wallet_type_map:
        context.user_data['wallet_type'] = wallet_type_map[text]
        await update.message.reply_text(
            f"✅ *Selected:* {text}\n\n━━━━━━━━━━━━━━━━━━━━━\nSend your wallet address:\n\n📤 *Example:*\n• TON: `EQDxxxxxxxxxxxxxxxx...`\n• TRC20: `TXYZabcd1234567890...`\n• BEP20/ERC20: `0x742d35Cc6634C053...`\n• BITCOIN: `bc1qar0srrr7xfkvy5...`\n• SOLANA: `7EcxRkCxnB5xTS5E6q...`\n━━━━━━━━━━━━━━━━━━━━━\n\nType your address now:",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_wallet_address'] = True
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Please select from buttons!", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')

async def handle_wallet_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_wallet_address'):
        return
    
    address = update.message.text.strip()
    user_id = update.effective_user.id
    wallet_type = context.user_data.get('wallet_type', 'Unknown')
    
    if len(address) >= 25:
        save_wallet(user_id, address, wallet_type)
        await update.message.reply_text(
            f"✅ *Wallet Connected Successfully!* ✅\n\n━━━━━━━━━━━━━━━━━━━━━\n🔗 *Type:* {wallet_type}\n📤 *Address:* `{address[:12]}...{address[-8:]}`\n💰 *Balance:* $0\n📅 *Connected:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n━━━━━━━━━━━━━━━━━━━━━\n\n🎉 Your wallet is now linked to L TRADE CORE!\n\nUse 💰 DEPOSIT to add funds.",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Invalid address! Please send a valid wallet address.", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')
    
    context.user_data['awaiting_wallet_address'] = False
    context.user_data['wallet_type'] = None

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    
    if not wallet:
        await update.message.reply_text(
            "👛 *No wallet connected!*\n\n━━━━━━━━━━━━━━━━━━━━━\nUse 👛 MY WALLET to connect your wallet.\n━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    msg = f"""
👛 *MY WALLET* 👛
━━━━━━━━━━━━━━━━━━━━━
🔗 *Type:* {wallet['wallet_type']}
📤 *Address:* `{wallet['address'][:12]}...{wallet['address'][-8:]}`
💰 *Balance:* `${wallet['balance']:.2f}`
📅 *Connected:* {wallet['connected_on']}
━━━━━━━━━━━━━━━━━━━━━
📊 *Total Deposits:* ${sum(d['amount'] for d in wallet['deposits']):.2f}
📊 *Total Withdrawals:* ${sum(w['amount'] for w in wallet['withdrawals']):.2f}
━━━━━━━━━━━━━━━━━━━━━
💡 *Actions:* Use 💰 DEPOSIT or 💸 WITHDRAW
"""
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

# ---------- DEPOSIT HANDLERS ----------
async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = get_wallet(update.effective_user.id)
    if not wallet:
        await update.message.reply_text("❌ Connect wallet first using 👛 MY WALLET", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    await update.message.reply_text(
        "💰 *DEPOSIT FUNDS* 💰\n\n━━━━━━━━━━━━━━━━━━━━━\nSelect deposit amount below:\n━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_deposit_amount_keyboard(),
        parse_mode='Markdown'
    )

async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    
    if not wallet:
        await update.message.reply_text("❌ Wallet not found!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    amount_map = {
        "💰 $10": 10, "💰 $25": 25, "💰 $50": 50,
        "💰 $100": 100, "💰 $250": 250, "💰 $500": 500, "💰 $1000": 1000
    }
    
    if text in amount_map:
        amount = amount_map[text]
        context.user_data['deposit_amount'] = amount
        deposit_addr = DEPOSIT_ADDRESSES.get(wallet['wallet_type'], "Address not found")
        
        await update.message.reply_text(
            f"💰 *DEPOSIT ${amount} USDT* 💰\n\n━━━━━━━━━━━━━━━━━━━━━\n💵 *Amount:* ${amount} USDT\n🔗 *Network:* {wallet['wallet_type']}\n📤 *Send to Address:*\n`{deposit_addr}`\n━━━━━━━━━━━━━━━━━━━━━\n⚠️ *IMPORTANT:*\n• Send exactly ${amount} USDT\n• Use ONLY {wallet['wallet_type']} network\n• Minimum deposit: $10 USDT\n━━━━━━━━━━━━━━━━━━━━━\n\n✅ After sending, click the button below:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I HAVE SENT", callback_data=f"deposit_request_{amount}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
            ]),
            parse_mode='Markdown'
        )
    elif text == "💰 CUSTOM":
        await update.message.reply_text("💰 *CUSTOM AMOUNT* 💰\n\nEnter the amount you want to deposit (min $10, max $10000):\n\nExample: `100`", parse_mode='Markdown')
        context.user_data['awaiting_custom_deposit'] = True
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Please select an amount from the buttons!", reply_markup=get_deposit_amount_keyboard(), parse_mode='Markdown')

async def handle_custom_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_custom_deposit'):
        return
    
    try:
        amount = float(update.message.text.strip())
        if amount < 10 or amount > 10000:
            await update.message.reply_text("❌ Amount must be between $10 and $10000!", parse_mode='Markdown')
        else:
            user_id = update.effective_user.id
            wallet = get_wallet(user_id)
            deposit_addr = DEPOSIT_ADDRESSES.get(wallet['wallet_type'], "Address not found")
            context.user_data['deposit_amount'] = amount
            
            await update.message.reply_text(
                f"💰 *DEPOSIT ${amount} USDT* 💰\n\n━━━━━━━━━━━━━━━━━━━━━\n💵 *Amount:* ${amount} USDT\n🔗 *Network:* {wallet['wallet_type']}\n📤 *Send to Address:*\n`{deposit_addr}`\n━━━━━━━━━━━━━━━━━━━━━\n⚠️ *Use ONLY {wallet['wallet_type']} network!*\n━━━━━━━━━━━━━━━━━━━━━\n\n✅ After sending, click the button below:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ I HAVE SENT", callback_data=f"deposit_request_{amount}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
                ]),
                parse_mode='Markdown'
            )
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number!", parse_mode='Markdown')
    
    context.user_data['awaiting_custom_deposit'] = False

async def deposit_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter
    query = update.callback_query
    await query.answer()
    
    amount = float(query.data.split('_')[2])
    user_id = update.effective_user.id
    user = update.effective_user
    wallet = get_wallet(user_id)
    
    request_counter += 1
    request_id = request_counter
    
    pending_deposits[request_id] = {
        'user_id': user_id, 'amount': amount, 'wallet_type': wallet['wallet_type'],
        'address': wallet['address'], 'status': 'pending',
        'username': user.username or user.first_name, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    await query.edit_message_text(
        f"⏳ *DEPOSIT REQUEST #{request_id} SUBMITTED!* ⏳\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${amount} USDT\n🔗 *Network:* {wallet['wallet_type']}\n🕐 *Status:* PENDING REVIEW\n━━━━━━━━━━━━━━━━━━━━━\n\n⏱️ Please wait. Admin will review your deposit.\n\n📞 Contact @LawlietTobi if any issue.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]),
        parse_mode='Markdown'
    )
    
    admin_msg = f"""
🔔 *NEW DEPOSIT REQUEST #{request_id}* 🔔

━━━━━━━━━━━━━━━━━━━━━
👤 *User:* @{user.username or user.first_name}
🆔 *User ID:* `{user_id}`
💰 *Amount:* ${amount} USDT
🔗 *Network:* {wallet['wallet_type']}
📤 *Address:* `{wallet['address'][:12]}...{wallet['address'][-8:]}`
📅 *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━
"""
    admin_buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE", callback_data=f"admin_approve_deposit_{request_id}"),
         InlineKeyboardButton("❌ REJECT", callback_data=f"admin_reject_deposit_{request_id}")]
    ])
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=admin_buttons, parse_mode='Markdown')

# ---------- WITHDRAW HANDLERS ----------
async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = get_wallet(update.effective_user.id)
    if not wallet:
        await update.message.reply_text("❌ Connect wallet first using 👛 MY WALLET", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    if wallet['balance'] < 10:
        await update.message.reply_text(f"❌ Minimum withdrawal is $10 USDT. Your balance: ${wallet['balance']:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    await update.message.reply_text(
        f"💸 *WITHDRAW FUNDS* 💸\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Available Balance:* ${wallet['balance']:.2f}\n🔗 *Network:* {wallet['wallet_type']}\n📤 *To Address:* `{wallet['address'][:12]}...{wallet['address'][-8:]}`\n━━━━━━━━━━━━━━━━━━━━━\n\nEnter the amount you want to withdraw (min $10):",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_withdraw'] = True

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter
    if not context.user_data.get('awaiting_withdraw'):
        return
    
    try:
        amount = float(update.message.text.strip())
        user_id = update.effective_user.id
        user = update.effective_user
        wallet = get_wallet(user_id)
        
        if amount < 10:
            await update.message.reply_text("❌ Minimum withdrawal is $10 USDT!", parse_mode='Markdown')
        elif amount > wallet['balance']:
            await update.message.reply_text(f"❌ Insufficient balance! Your balance: ${wallet['balance']:.2f}", parse_mode='Markdown')
        else:
            request_counter += 1
            request_id = request_counter
            
            pending_withdrawals[request_id] = {
                'user_id': user_id, 'amount': amount, 'wallet_type': wallet['wallet_type'],
                'address': wallet['address'], 'status': 'pending',
                'username': user.username or user.first_name, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            await update.message.reply_text(
                f"⏳ *WITHDRAWAL REQUEST #{request_id} SUBMITTED!* ⏳\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${amount} USDT\n🔗 *Network:* {wallet['wallet_type']}\n📤 *To:* `{wallet['address'][:12]}...{wallet['address'][-8:]}`\n🕐 *Status:* PENDING REVIEW\n━━━━━━━━━━━━━━━━━━━━━\n\n⏱️ Admin will review your withdrawal request.\n\n📞 Contact @LawlietTobi if any issue.",
                reply_markup=get_main_keyboard(),
                parse_mode='Markdown'
            )
            
            admin_msg = f"""
🔔 *NEW WITHDRAWAL REQUEST #{request_id}* 🔔

━━━━━━━━━━━━━━━━━━━━━
👤 *User:* @{user.username or user.first_name}
🆔 *User ID:* `{user_id}`
💰 *Amount:* ${amount} USDT
🔗 *Network:* {wallet['wallet_type']}
📤 *To:* `{wallet['address'][:12]}...{wallet['address'][-8:]}`
📅 *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━
"""
            admin_buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ APPROVE", callback_data=f"admin_approve_withdraw_{request_id}"),
                 InlineKeyboardButton("❌ REJECT", callback_data=f"admin_reject_withdraw_{request_id}")]
            ])
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=admin_buttons, parse_mode='Markdown')
            
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number!", parse_mode='Markdown')
    
    context.user_data['awaiting_withdraw'] = False

# ---------- ADMIN CALLBACKS ----------
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("admin_approve_deposit_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_deposits:
            req = pending_deposits[request_id]
            add_balance(req['user_id'], req['amount'])
            
            await context.bot.send_message(
                chat_id=req['user_id'],
                text=f"✅ *DEPOSIT APPROVED!* ✅\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${req['amount']:.2f} USDT\n🆔 *Request ID:* #{request_id}\n━━━━━━━━━━━━━━━━━━━━━\n\n🎉 Your deposit has been approved and added to your wallet!\n\n💰 *New Balance:* ${get_wallet(req['user_id'])['balance']:.2f}",
                reply_markup=get_main_keyboard(),
                parse_mode='Markdown'
            )
            await query.edit_message_text(f"✅ Deposit #{request_id} approved successfully!", parse_mode='Markdown')
            del pending_deposits[request_id]
    
    elif data.startswith("admin_reject_deposit_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_deposits:
            req = pending_deposits[request_id]
            await context.bot.send_message(
                chat_id=req['user_id'],
                text=f"❌ *DEPOSIT REJECTED!* ❌\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${req['amount']:.2f} USDT\n🆔 *Request ID:* #{request_id}\n━━━━━━━━━━━━━━━━━━━━━\n\n⚠️ Your deposit request has been rejected.\n\n📞 Please contact @LawlietTobi for more information.",
                reply_markup=get_main_keyboard(),
                parse_mode='Markdown'
            )
            await query.edit_message_text(f"❌ Deposit #{request_id} rejected!", parse_mode='Markdown')
            del pending_deposits[request_id]
    
    elif data.startswith("admin_approve_withdraw_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_withdrawals:
            req = pending_withdrawals[request_id]
            deduct_balance(req['user_id'], req['amount'])
            
            await context.bot.send_message(
                chat_id=req['user_id'],
                text=f"✅ *WITHDRAWAL APPROVED!* ✅\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${req['amount']:.2f} USDT\n🆔 *Request ID:* #{request_id}\n📤 *To:* `{req['address'][:12]}...{req['address'][-8:]}`\n━━━━━━━━━━━━━━━━━━━━━\n\n🎉 Your withdrawal request has been approved!\n\n💰 *New Balance:* ${get_wallet(req['user_id'])['balance']:.2f}",
                reply_markup=get_main_keyboard(),
                parse_mode='Markdown'
            )
            await query.edit_message_text(f"✅ Withdrawal #{request_id} approved!", parse_mode='Markdown')
            del pending_withdrawals[request_id]
    
    elif data.startswith("admin_reject_withdraw_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_withdrawals:
            req = pending_withdrawals[request_id]
            await context.bot.send_message(
                chat_id=req['user_id'],
                text=f"❌ *WITHDRAWAL REJECTED!* ❌\n\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Amount:* ${req['amount']:.2f} USDT\n🆔 *Request ID:* #{request_id}\n━━━━━━━━━━━━━━━━━━━━━\n\n⚠️ Your withdrawal request has been rejected.\n\n📞 Please contact @LawlietTobi for more information.",
                reply_markup=get_main_keyboard(),
                parse_mode='Markdown'
            )
            await query.edit_message_text(f"❌ Withdrawal #{request_id} rejected!", parse_mode='Markdown')
            del pending_withdrawals[request_id]
    
    elif data == "back_to_menu":
        await show_main_menu_callback(query)

# ---------- RECENT TRADES ----------
async def show_recent_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trades = get_recent_trades(user_id)
    
    if not trades:
        await update.message.reply_text("📜 *NO RECENT TRADES* 📜\n\n━━━━━━━━━━━━━━━━━━━━━\nTake your first trade by clicking BUY on any signal!\n━━━━━━━━━━━━━━━━━━━━━", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    
    msg = "📜 *YOUR RECENT TRADES* 📜\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    total_pnl = 0
    for i, trade in enumerate(trades, 1):
        msg += f"*{i}. {trade['symbol']}*\n"
        msg += f"   📊 Signal: {trade['signal']}\n"
        msg += f"   💰 Entry: ${trade['entry']:.4f}\n"
        msg += f"   💰 Exit: ${trade['exit']:.4f}\n"
        msg += f"   📈 P&L: {trade['pnl']}\n"
        msg += f"   ⏰ {trade['timestamp']}\n"
        msg += "   ━━━━━━━━━━━━━━━━━\n"
    
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

# ---------- MENU HANDLERS ----------
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👇 *Main Menu* 👇\n\n━━━━━━━━━━━━━━━━━━━━━\nSelect an option from the buttons below:\n━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def show_main_menu_callback(query):
    await query.edit_message_text(
        "👇 *Main Menu* 👇\n\n━━━━━━━━━━━━━━━━━━━━━\nSelect an option from the buttons below:\n━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

# ---------- CALLBACK HANDLER ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "back_to_menu":
        await show_main_menu_callback(query)
    elif data.startswith("custom_buy_"):
        await custom_buy_callback(update, context)
    elif data.startswith("sell_"):
        await sell_callback(update, context)
    elif data.startswith("deposit_request_"):
        await deposit_request_callback(update, context)
    elif data.startswith("admin_"):
        await admin_callback_handler(update, context)

# ---------- WELCOME MESSAGE ----------
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_caption = """
✨ *WELCOME TO L TRADE CORE* ✨

━━━━━━━━━━━━━━━━━━━━━
💎 *YOUR PREMIUM TRADING HUB* 💎
━━━━━━━━━━━━━━━━━━━━━

🔥 *Real-time Technical Analysis*
📊 *Crypto | Forex | Stocks*
🎯 *BUY/SELL Signals with Entry, TP, SL*
📈 *RSI • MACD • Bollinger Bands*
📉 *Candlestick Charts Included!*
👛 *Multi-Chain Wallet Support*
💰 *Custom Trade Amount*
📊 *Live Position Tracking*

━━━━━━━━━━━━━━━━━━━━━
⚡ *WHY CHOOSE US?* ⚡
━━━━━━━━━━━━━━━━━━━━━

✅ *85%+ Win Rate Signals*
✅ *Live Market Analysis 24/7*
✅ *Professional Candlestick Charts*
✅ *Multi-Chain Wallet Support*
✅ *Custom Trade Amount*
✅ *Real-time P&L Tracking*

━━━━━━━━━━━━━━━━━━━━━
⚡ *SUPPORTED WALLETS* ⚡
━━━━━━━━━━━━━━━━━━━━━

💎 TON | 🪙 TRC20 | 🔷 BEP20
💠 ERC20 | ₿ BITCOIN | ◎ SOLANA

━━━━━━━━━━━━━━━━━━━━━
👇 *CLICK BUTTONS BELOW TO START* 👇

💡 *Pro Tip:* Connect wallet for premium features!

⚠️ *Risk Warning:* Trade responsibly | Max 2% risk per trade
📞 *Support:* @LawlietTobi
"""
    try:
        await update.message.reply_video(video=WELCOME_VIDEO_URL, caption=welcome_caption, reply_markup=get_main_keyboard(), parse_mode='Markdown', supports_streaming=True)
    except:
        await update.message.reply_text(welcome_caption, reply_markup=get_main_keyboard(), parse_mode='Markdown')

# ---------- COMMAND HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_welcome(update, context)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ *Action cancelled!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')

# ---------- MESSAGE HANDLER ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # Check for pending custom buy amount
    if context.user_data.get('pending_custom_buy'):
        await process_custom_buy(update, context)
        return
    
    if context.user_data.get('awaiting_wallet_address'):
        await handle_wallet_address(update, context)
        return
    
    if context.user_data.get('awaiting_custom_deposit'):
        await handle_custom_deposit(update, context)
        return
    
    if context.user_data.get('awaiting_withdraw'):
        await handle_withdraw(update, context)
        return
    
    # Wallet type selection
    if text in ["💎 TON", "🪙 TRC20 (USDT)", "🔷 BEP20 (USDT)", "💠 ERC20 (USDT)", "₿ BITCOIN", "◎ SOLANA"]:
        await handle_wallet_type(update, context)
        return
    
    # Deposit amount selection
    if text in ["💰 $10", "💰 $25", "💰 $50", "💰 $100", "💰 $250", "💰 $500", "💰 $1000", "💰 CUSTOM"]:
        await handle_deposit_amount(update, context)
        return
    
    if text == "🪙 CRYPTO SIGNALS":
        await update.message.reply_text("🪙 *SELECT CRYPTO COIN* 🪙\n\n👇 *Choose a coin:*", reply_markup=get_crypto_keyboard(), parse_mode='Markdown')
    elif text == "💱 FOREX SIGNALS":
        await update.message.reply_text("💱 *SELECT FOREX PAIR* 💱\n\n👇 *Choose a pair:*", reply_markup=get_forex_keyboard(), parse_mode='Markdown')
    elif text == "📈 STOCK SIGNALS":
        await update.message.reply_text("📈 *SELECT STOCK* 📈\n\n👇 *Choose a stock:*", reply_markup=get_stocks_keyboard(), parse_mode='Markdown')
    elif text == "🌍 ALL MARKETS":
        await update.message.reply_text("🌍 *SCANNING ALL MARKETS...* ⏳\n\n*This may take 30 seconds*", parse_mode='Markdown')
        for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            signal = generate_signal(symbol, "crypto", "1h")
            if signal and signal['signal'] != "⚪ NEUTRAL":
                await update.message.reply_text(f"🪙 *{symbol}*\n📊 {signal['signal']} | {signal['confidence']}\n💰 ${signal['entry']:.2f}", parse_mode='Markdown')
        await update.message.reply_text("🔙 Back to menu", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif text == "👛 MY WALLET":
        await wallet_menu(update, context)
    elif text == "📊 MY POSITIONS":
        await show_positions(update, context)
    elif text == "💰 DEPOSIT":
        await deposit_menu(update, context)
    elif text == "💸 WITHDRAW":
        await withdraw_menu(update, context)
    elif text == "📜 RECENT TRADES":
        await show_recent_trades(update, context)
    elif text == "❓ HELP & SUPPORT":
        help_text = """
❓ *L TRADE CORE - HELP GUIDE* ❓

━━━━━━━━━━━━━━━━━━━━━
📖 *HOW TO USE*
━━━━━━━━━━━━━━━━━━━━━

1️⃣ *Connect Wallet* → 👛 MY WALLET
   • Select your blockchain (TON/TRC20/BEP20/ERC20/BTC/SOL)
   • Send your wallet address

2️⃣ *Deposit Funds* → 💰 DEPOSIT
   • Select amount ($10 - $10000)
   • Send USDT to provided address
   • Click "I HAVE SENT"
   • Wait for admin approval

3️⃣ *Get Signals* → 🪙 CRYPTO/FOREX/STOCKS
   • Choose your asset
   • View chart + signal
   • Click BUY (Custom Amount)
   • Enter your trade amount

4️⃣ *Track Positions* → 📊 MY POSITIONS
   • View open trades
   • Check real-time P&L

5️⃣ *Withdraw Profits* → 💸 WITHDRAW
   • Enter amount
   • Wait for admin approval

━━━━━━━━━━━━━━━━━━━━━
⚡ *CONFIDENCE LEVELS*
━━━━━━━━━━━━━━━━━━━━━

🔥 *HIGH* - Strong signal (70%+)
⚡ *MEDIUM* - Good signal (60%)
💤 *LOW* - Weak signal (50%)

━━━━━━━━━━━━━━━━━━━━━
💡 *PRO TIPS*
━━━━━━━━━━━━━━━━━━━━━

• Always use STOP LOSS
• Never risk more than 2% per trade
• Take 50% profit at TP1
• Check MY POSITIONS for live P&L

━━━━━━━━━━━━━━━━━━━━━
📞 *Contact:* @LawlietTobi
"""
        await update.message.reply_text(help_text, reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif text == "📞 CONTACT DEVELOPER":
        await update.message.reply_text("📞 *CONTACT DEVELOPER* 📞\n\n━━━━━━━━━━━━━━━━━━━━━\n👤 *Telegram:* @LawlietTobi\n━━━━━━━━━━━━━━━━━━━━━\n\n💬 *Reach out for:* Bot Customization | New Features | Bug Reports | Trading Strategies\n\n🚀 *Happy Trading!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
    elif text in ["₿ BTC/USDT", "⟠ ETH/USDT", "◎ SOL/USDT", "🐕 DOGE/USDT", "💱 XRP/USDT", "⬆️ ADA/USDT", "🏔️ AVAX/USDT", "🟣 MATIC/USDT"]:
        symbol_map = {"₿ BTC/USDT": "BTC/USDT", "⟠ ETH/USDT": "ETH/USDT", "◎ SOL/USDT": "SOL/USDT", "🐕 DOGE/USDT": "DOGE/USDT", "💱 XRP/USDT": "XRP/USDT", "⬆️ ADA/USDT": "ADA/USDT", "🏔️ AVAX/USDT": "AVAX/USDT", "🟣 MATIC/USDT": "MATIC/USDT"}
        await send_signal_with_chart(update, context, symbol_map.get(text), "crypto", text)
    elif text in ["💶 EUR/USD", "💷 GBP/USD", "💴 USD/JPY", "🦘 AUD/USD"]:
        symbol_map = {"💶 EUR/USD": "EUR/USD", "💷 GBP/USD": "GBP/USD", "💴 USD/JPY": "USD/JPY", "🦘 AUD/USD": "AUD/USD"}
        await send_signal_with_chart(update, context, symbol_map.get(text), "forex", text)
    elif text in ["🍎 AAPL", "🔍 GOOGL", "🪟 MSFT", "🚗 TSLA", "🎮 NVDA"]:
        symbol_map = {"🍎 AAPL": "AAPL", "🔍 GOOGL": "GOOGL", "🪟 MSFT": "MSFT", "🚗 TSLA": "TSLA", "🎮 NVDA": "NVDA"}
        await send_signal_with_chart(update, context, symbol_map.get(text), "stock", text)

# ---------- MAIN ----------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
   
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 L TRADE CORE Bot is running...")
    print(f"👑 Admin ID: {ADMIN_CHAT_ID}")
    print(f"💾 Loaded {len(user_wallets)} wallets from storage")
    print(f"📊 Loaded {len(user_positions)} position records")
    app.run_polling()

if __name__ == "__main__":
    main()