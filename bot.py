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
import secrets
from flask import Flask, request, jsonify
import threading

# ---------- CONFIG ----------
TELEGRAM_TOKEN = "8511168805:AAFMV_AwHsgVVMBmvBTmfYYicRyJ5E7qcsU"
ADMIN_CHAT_ID = 8457706605
WELCOME_VIDEO_URL = "https://files.catbox.moe/ykynt9.mp4"
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
NEW_USER_BONUS = 25
REFERRAL_BONUS = 0.5
MIN_WITHDRAWAL = 10

PORT = int(os.environ.get('PORT', 10000))
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')

DEPOSIT_ADDRESSES = {
    "TRC20 (USDT)": "TLC8bebj9L57ZsihNiY32d4nWH8CVDvLpu",
    "BEP20 (USDT)": "0xc09B4D0a9b0EDfbE30753F5b79360a4F82e570a1",
    "ERC20 (USDT)": "0x798022D87F929f576191722A8431340aF5282bD4",
    "BITCOIN": "bc1q5agzp3dtmv2yk7mth7gj76a0k60rv22r5ldnjc",
    "SOLANA": "36vUEHqYxpLn54yreV7YLPgunuxoUMLcwpH7NUcunA78",
    "TON": "UQC-HTnL3mvMe3GiZ-6hu15MUW5r5pA_M-Q-cZhAULtQ-pmt"
}

WALLETS_FILE = "user_wallets.json"
POSITIONS_FILE = "user_positions.json"
BONUS_CLAIMED_FILE = "bonus_claimed.json"
REFERRALS_FILE = "referrals.json"

# ---------- PERSISTENCE FUNCTIONS ----------
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

def load_bonus_claimed():
    if os.path.exists(BONUS_CLAIMED_FILE):
        try:
            with open(BONUS_CLAIMED_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_bonus_claimed():
    try:
        with open(BONUS_CLAIMED_FILE, 'w') as f:
            to_save = {str(k): v for k, v in bonus_claimed.items()}
            json.dump(to_save, f, indent=4, default=str)
    except:
        pass

def load_referrals():
    if os.path.exists(REFERRALS_FILE):
        try:
            with open(REFERRALS_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            return {}
    return {}

def save_referrals():
    try:
        with open(REFERRALS_FILE, 'w') as f:
            to_save = {str(k): v for k, v in referrals.items()}
            json.dump(to_save, f, indent=4, default=str)
    except:
        pass

# ---------- STORAGE ----------
user_wallets = load_wallets()
user_positions = load_positions()
bonus_claimed = load_bonus_claimed()
referrals = load_referrals()
user_trades = {}
pending_deposits = {}
pending_withdrawals = {}
request_counter = 0

def save_wallet(user_id, address, wallet_type):
    if user_id not in user_wallets:
        user_wallets[user_id] = {'wallets': {}, 'balance': 0, 'deposits': [], 'withdrawals': [], 'connected_on': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    user_wallets[user_id]['wallets'][wallet_type] = {'address': address, 'connected_on': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    save_wallets()
    return True

def get_wallet(user_id, wallet_type=None):
    if user_id not in user_wallets:
        return None
    if wallet_type:
        return user_wallets[user_id]['wallets'].get(wallet_type)
    return user_wallets.get(user_id)

def get_all_wallets(user_id):
    if user_id not in user_wallets:
        return {}
    return user_wallets[user_id].get('wallets', {})

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
    user_positions[user_id].append({'symbol': symbol, 'entry': entry_price, 'amount': amount, 'quantity': quantity, 'order_type': order_type, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    save_positions()
    return True

def get_positions(user_id):
    return user_positions.get(user_id, [])

def add_trade(user_id, symbol, signal_type, entry, exit_price, pnl, confidence, timestamp):
    if user_id not in user_trades:
        user_trades[user_id] = deque(maxlen=20)
    user_trades[user_id].appendleft({'symbol': symbol, 'signal': signal_type, 'entry': entry, 'exit': exit_price, 'pnl': pnl, 'confidence': confidence, 'timestamp': timestamp})
    return True

def get_recent_trades(user_id):
    if user_id not in user_trades or not user_trades[user_id]:
        return None
    return list(user_trades[user_id])

def has_claimed_bonus(user_id):
    return bonus_claimed.get(user_id, False)

def claim_bonus(user_id):
    if has_claimed_bonus(user_id):
        return False
    bonus_claimed[user_id] = True
    save_bonus_claimed()
    return True

def generate_referral_code(user_id):
    return f"LT{user_id}{secrets.token_hex(4)[:6].upper()}"

def get_referral_code(user_id):
    if user_id not in referrals:
        referrals[user_id] = {'code': generate_referral_code(user_id), 'referred_users': [], 'earned': 0, 'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_referrals()
    return referrals[user_id]['code']

def get_referral_stats(user_id):
    if user_id not in referrals:
        return {'code': None, 'count': 0, 'earned': 0}
    return {'code': referrals[user_id]['code'], 'count': len(referrals[user_id]['referred_users']), 'earned': referrals[user_id]['earned']}

def add_referral(referrer_id, referred_id):
    if referrer_id not in referrals:
        get_referral_code(referrer_id)
    for uid, data in referrals.items():
        if referred_id in data['referred_users']:
            return False
    if referrer_id != referred_id:
        referrals[referrer_id]['referred_users'].append(referred_id)
        referrals[referrer_id]['earned'] += REFERRAL_BONUS
        save_referrals()
        add_balance(referrer_id, REFERRAL_BONUS)
        return True
    return False

# ---------- KEYBOARD LAYOUTS ----------
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        ["🪙 CRYPTO SIGNALS", "💱 FOREX SIGNALS"],
        ["📈 STOCK SIGNALS", "🌍 ALL MARKETS"],
        ["👛 MY WALLET", "📊 MY POSITIONS"],
        ["💰 DEPOSIT", "💸 WITHDRAW"],
        ["🎁 CLAIM BONUS", "👥 REFER & EARN"],
        ["❓ HELP & SUPPORT", "📞 CONTACT DEVELOPER"]
    ], resize_keyboard=True)

def get_wallet_type_keyboard():
    return ReplyKeyboardMarkup([
        ["💎 TON", "🪙 TRC20 (USDT)"],
        ["🔷 BEP20 (USDT)", "💠 ERC20 (USDT)"],
        ["₿ BITCOIN", "◎ SOLANA"],
        ["🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

def get_withdraw_token_keyboard():
    return ReplyKeyboardMarkup([
        ["💎 TON", "🪙 TRC20 (USDT)"],
        ["🔷 BEP20 (USDT)", "💠 ERC20 (USDT)"],
        ["₿ BITCOIN", "◎ SOLANA"],
        ["🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

def get_crypto_keyboard():
    return ReplyKeyboardMarkup([
        ["₿ BTC/USDT", "⟠ ETH/USDT"],
        ["◎ SOL/USDT", "🐕 DOGE/USDT"],
        ["💱 XRP/USDT", "⬆️ ADA/USDT"],
        ["🏔️ AVAX/USDT", "🟣 MATIC/USDT"],
        ["🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

def get_forex_keyboard():
    return ReplyKeyboardMarkup([
        ["💶 EUR/USD", "💷 GBP/USD"],
        ["💴 USD/JPY", "🦘 AUD/USD"],
        ["🍁 USD/CAD", "🇨🇭 USD/CHF"],
        ["🇳🇿 NZD/USD", "🇪🇺 EUR/GBP"],
        ["🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

def get_stocks_keyboard():
    return ReplyKeyboardMarkup([
        ["🍎 AAPL", "🔍 GOOGL"],
        ["🪟 MSFT", "🚗 TSLA"],
        ["🎮 NVDA", "📦 AMZN"],
        ["📘 META", "🎬 NFLX"],
        ["🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

def get_deposit_amount_keyboard():
    return ReplyKeyboardMarkup([
        ["💰 $10", "💰 $25", "💰 $50"],
        ["💰 $100", "💰 $250", "💰 $500"],
        ["💰 $1000", "💰 CUSTOM", "🔙 BACK TO MAIN MENU"]
    ], resize_keyboard=True)

# ---------- CHART GENERATOR ----------
def generate_candlestick_chart(symbol, asset_type="crypto", period="7d", interval="1h"):
    try:
        if asset_type == "crypto":
            exchange = ccxt.binance()
            exchange.load_markets()
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
            exchange = ccxt.binance({'enableRateLimit': True, 'timeout': 30000})
            exchange.load_markets()
            symbol_formats = [symbol, f"{symbol}:USDT", symbol.replace('/', '')]
            ohlcv = None
            for sym in symbol_formats:
                try:
                    ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=200)
                    if ohlcv and len(ohlcv) > 0:
                        break
                except:
                    continue
            if not ohlcv or len(ohlcv) < 50:
                return None
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            current_price = df['Close'].iloc[-1]
        elif asset_type == "forex":
            forex_pair = symbol.replace("/", "") + "=X"
            ticker = yf.Ticker(forex_pair)
            df = ticker.history(period="7d", interval=timeframe)
            if df.empty or len(df) < 50:
                return None
            current_price = df['Close'].iloc[-1]
        else:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="7d", interval=timeframe)
            if df.empty or len(df) < 50:
                return None
            current_price = df['Close'].iloc[-1]
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
        tp1 = current_price
        tp2 = current_price
        tp3 = current_price
        sl = current_price
        rr_ratio = 0
        pips = None
        if buy_score > sell_score and total_score >= 3:
            signal_type = "🟢 BUY"
            confidence = "🔥 HIGH" if total_score >= 6 else "⚡ MEDIUM"
            entry = current_price
            tp1 = entry + (atr * 1.5)
            tp2 = entry + (atr * 2.5)
            tp3 = entry + (atr * 4)
            sl = entry - (atr * 1.5)
            rr_ratio = round(abs(tp1 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0
        elif sell_score > buy_score and total_score >= 3:
            signal_type = "🔴 SELL"
            confidence = "🔥 HIGH" if total_score >= 6 else "⚡ MEDIUM"
            entry = current_price
            tp1 = entry - (atr * 1.5)
            tp2 = entry - (atr * 2.5)
            tp3 = entry - (atr * 4)
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
        logging.error(f"Signal error for {symbol}: {e}")
        return None

# ---------- TELEGRAM HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and len(context.args) > 0:
        ref_code = context.args[0]
        if ref_code.startswith('ref_'):
            code = ref_code[4:]
            for uid, data in referrals.items():
                if data['code'] == code:
                    context.user_data['referrer_id'] = uid
                    break
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
🎁 *New User Bonus: $25 FREE!*
👥 *Refer & Earn: $0.50 per referral*

━━━━━━━━━━━━━━━━━━━━━
👇 *CLICK BUTTONS BELOW TO START* 👇

📞 *Support:* @LawlietTobi
"""
    try:
        await update.message.reply_video(video=WELCOME_VIDEO_URL, caption=welcome_caption, reply_markup=get_main_keyboard(), parse_mode='Markdown', supports_streaming=True)
    except:
        await update.message.reply_text(welcome_caption, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ *Action cancelled!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    existing_wallets = get_all_wallets(user_id)
    if existing_wallets:
        msg = "👛 *MY CONNECTED WALLETS* 👛\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        for w_type, w_data in existing_wallets.items():
            msg += f"🔗 *{w_type}:* `{w_data['address'][:12]}...{w_data['address'][-8:]}`\n"
        msg += "\n━━━━━━━━━━━━━━━━━━━━━\n👇 *Add New Wallet:*"
    else:
        msg = "👛 *CONNECT YOUR WALLET* 👛\n\n━━━━━━━━━━━━━━━━━━━━━\nSelect your wallet type below:"
    await update.message.reply_text(msg, reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')

async def handle_wallet_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    wallet_type_map = {"💎 TON": "TON", "🪙 TRC20 (USDT)": "TRC20", "🔷 BEP20 (USDT)": "BEP20", "💠 ERC20 (USDT)": "ERC20", "₿ BITCOIN": "BITCOIN", "◎ SOLANA": "SOLANA"}
    if text in wallet_type_map:
        context.user_data['wallet_type'] = wallet_type_map[text]
        await update.message.reply_text(f"✅ *Selected:* {text}\n\nSend your wallet address:", parse_mode='Markdown')
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
        referrer_id = context.user_data.get('referrer_id')
        if referrer_id and referrer_id != user_id:
            if add_referral(referrer_id, user_id):
                await context.bot.send_message(chat_id=referrer_id, text=f"🎉 *REFERRAL BONUS!* 🎉\n\n👤 New User joined!\n💰 +${REFERRAL_BONUS} USDT", parse_mode='Markdown')
        if not has_claimed_bonus(user_id):
            claim_bonus(user_id)
            add_balance(user_id, NEW_USER_BONUS)
            bonus_msg = f"\n\n🎁 *NEW USER BONUS!* 🎁\n💰 +${NEW_USER_BONUS} USDT added!"
        else:
            bonus_msg = ""
        await update.message.reply_text(f"✅ *Wallet Connected!* ✅\n\n🔗 *Type:* {wallet_type}\n📤 *Address:* `{address[:12]}...{address[-8:]}`\n💰 *Balance:* ${user_wallets[user_id]['balance']:.2f}{bonus_msg}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Invalid address!", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')
    context.user_data['awaiting_wallet_address'] = False
    context.user_data['wallet_type'] = None
    context.user_data['referrer_id'] = None

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = get_wallet(user_id)
    if not wallet:
        await update.message.reply_text("👛 *No wallet connected!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    msg = f"👛 *MY WALLET*\n━━━━━━━━━━━━━━━━━━━━━\n💰 *Balance:* `${wallet['balance']:.2f}`\n📊 *Total Deposits:* ${sum(d['amount'] for d in wallet['deposits']):.2f}\n📊 *Total Withdrawals:* ${sum(w['amount'] for w in wallet['withdrawals']):.2f}\n━━━━━━━━━━━━━━━━━━━━━\n🔗 *Connected Wallets:*\n"
    for w_type, w_data in get_all_wallets(user_id).items():
        msg += f"• {w_type}: `{w_data['address'][:12]}...{w_data['address'][-8:]}`\n"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def claim_bonus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_wallet(user_id):
        await update.message.reply_text("❌ Connect wallet first!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    if has_claimed_bonus(user_id):
        await update.message.reply_text("⚠️ *Bonus Already Claimed!*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    claim_bonus(user_id)
    add_balance(user_id, NEW_USER_BONUS)
    await update.message.reply_text(f"🎉 *BONUS CLAIMED!* 🎉\n\n💰 +${NEW_USER_BONUS} USDT\n💵 New Balance: ${get_wallet(user_id)['balance']:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not get_wallet(user_id):
        await update.message.reply_text("❌ Connect wallet first!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    code = get_referral_code(user_id)
    bot_username = (await context.bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start=ref_{code}"
    stats = get_referral_stats(user_id)
    msg = f"👥 *REFER & EARN*\n\n💰 Bonus per Referral: +${REFERRAL_BONUS} USDT\n📊 Your Stats:\n• Referrals: {stats['count']}\n• Earned: ${stats['earned']:.2f}\n\n🔗 Your Link:\n`{referral_link}`"
    keyboard = [[InlineKeyboardButton("📤 SHARE", url=f"https://t.me/share/url?url={referral_link}&text=Join%20L%20TRADE%20CORE!")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def deposit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_wallet(update.effective_user.id):
        await update.message.reply_text("❌ Connect wallet first!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    await update.message.reply_text("💰 *DEPOSIT FUNDS*\n\nSelect amount:", reply_markup=get_deposit_amount_keyboard(), parse_mode='Markdown')

async def handle_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    amount_map = {"💰 $10": 10, "💰 $25": 25, "💰 $50": 50, "💰 $100": 100, "💰 $250": 250, "💰 $500": 500, "💰 $1000": 1000}
    if text in amount_map:
        context.user_data['deposit_amount'] = amount_map[text]
        await update.message.reply_text(f"💰 *DEPOSIT ${amount_map[text]} USDT*\n\n👇 Select network:", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')
        context.user_data['awaiting_deposit_network'] = True
    elif text == "💰 CUSTOM":
        await update.message.reply_text("Enter amount (min $10, max $10000):", parse_mode='Markdown')
        context.user_data['awaiting_custom_deposit'] = True
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
    else:
        await update.message.reply_text("❌ Select from buttons!", reply_markup=get_deposit_amount_keyboard(), parse_mode='Markdown')

async def handle_deposit_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_deposit_network'):
        return
    wallet_type_map = {"💎 TON": "TON", "🪙 TRC20 (USDT)": "TRC20", "🔷 BEP20 (USDT)": "BEP20", "💠 ERC20 (USDT)": "ERC20", "₿ BITCOIN": "BITCOIN", "◎ SOLANA": "SOLANA"}
    if text in wallet_type_map:
        network = wallet_type_map[text]
        amount = context.user_data.get('deposit_amount', 0)
        await update.message.reply_text(f"💰 *DEPOSIT ${amount} USDT*\n\nSend to:\n`{DEPOSIT_ADDRESSES.get(network)}`\n\nNetwork: {network}\n\n✅ Click below after sending:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I HAVE SENT", callback_data=f"deposit_request_{amount}")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]), parse_mode='Markdown')
        context.user_data['awaiting_deposit_network'] = False
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
        context.user_data['awaiting_deposit_network'] = False
    else:
        await update.message.reply_text("❌ Select network!", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')

async def handle_custom_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_custom_deposit'):
        return
    try:
        amount = float(update.message.text.strip())
        if amount < 10 or amount > 10000:
            await update.message.reply_text("❌ Amount must be between $10 and $10000!")
        else:
            context.user_data['deposit_amount'] = amount
            await update.message.reply_text(f"💰 *DEPOSIT ${amount} USDT*\n\n👇 Select network:", reply_markup=get_wallet_type_keyboard(), parse_mode='Markdown')
            context.user_data['awaiting_deposit_network'] = True
    except ValueError:
        await update.message.reply_text("❌ Enter valid number!")
    context.user_data['awaiting_custom_deposit'] = False

async def deposit_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global request_counter
    query = update.callback_query
    await query.answer()
    amount = float(query.data.split('_')[2])
    user_id = update.effective_user.id
    user = update.effective_user
    request_counter += 1
    request_id = request_counter
    pending_deposits[request_id] = {'user_id': user_id, 'amount': amount, 'status': 'pending', 'username': user.username or user.first_name, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    await query.edit_message_text(f"⏳ *REQUEST #{request_id} SUBMITTED!*\n\n💰 Amount: ${amount}\n🕐 Status: PENDING\n\nAdmin will review shortly.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]), parse_mode='Markdown')
    admin_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVE", callback_data=f"admin_approve_deposit_{request_id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"admin_reject_deposit_{request_id}")]])
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🔔 NEW DEPOSIT REQUEST #{request_id}\n\n👤 User: @{user.username or user.first_name}\n💰 Amount: ${amount}", reply_markup=admin_buttons, parse_mode='Markdown')

async def withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = get_wallet(update.effective_user.id)
    if not wallet:
        await update.message.reply_text("❌ Connect wallet first!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    if wallet['balance'] < MIN_WITHDRAWAL:
        await update.message.reply_text(f"❌ Minimum withdrawal ${MIN_WITHDRAWAL}. Balance: ${wallet['balance']:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    await update.message.reply_text(f"💸 *WITHDRAW FUNDS*\n\n💰 Balance: ${wallet['balance']:.2f}\n\n👇 Select network:", reply_markup=get_withdraw_token_keyboard(), parse_mode='Markdown')
    context.user_data['awaiting_withdraw_network'] = True

async def handle_withdraw_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_withdraw_network'):
        return
    text = update.message.text
    wallet_type_map = {"💎 TON": "TON", "🪙 TRC20 (USDT)": "TRC20", "🔷 BEP20 (USDT)": "BEP20", "💠 ERC20 (USDT)": "ERC20", "₿ BITCOIN": "BITCOIN", "◎ SOLANA": "SOLANA"}
    if text in wallet_type_map:
        network = wallet_type_map[text]
        user_id = update.effective_user.id
        user_wallets_dict = get_all_wallets(user_id)
        if network not in user_wallets_dict:
            await update.message.reply_text(f"❌ {network} wallet not connected!", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            context.user_data['awaiting_withdraw_network'] = False
            return
        context.user_data['withdraw_network'] = network
        context.user_data['withdraw_address'] = user_wallets_dict[network]['address']
        await update.message.reply_text(f"💸 *WITHDRAW FUNDS*\n\n🔗 Network: {network}\n📤 To: `{user_wallets_dict[network]['address'][:12]}...{user_wallets_dict[network]['address'][-8:]}`\n💰 Balance: ${get_wallet(user_id)['balance']:.2f}\n\nEnter amount (min ${MIN_WITHDRAWAL}):", parse_mode='Markdown')
        context.user_data['awaiting_withdraw_amount'] = True
        context.user_data['awaiting_withdraw_network'] = False
    elif text == "🔙 BACK TO MAIN MENU":
        await show_main_menu(update, context)
        context.user_data['awaiting_withdraw_network'] = False
    else:
        await update.message.reply_text("❌ Select network!", reply_markup=get_withdraw_token_keyboard(), parse_mode='Markdown')

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_withdraw_amount'):
        return
    try:
        amount = float(update.message.text.strip())
        user_id = update.effective_user.id
        user = update.effective_user
        wallet = get_wallet(user_id)
        network = context.user_data.get('withdraw_network')
        withdraw_address = context.user_data.get('withdraw_address')
        if amount < MIN_WITHDRAWAL:
            await update.message.reply_text(f"❌ Minimum withdrawal ${MIN_WITHDRAWAL}!")
        elif amount > wallet['balance']:
            await update.message.reply_text(f"❌ Insufficient balance! Balance: ${wallet['balance']:.2f}")
        else:
            global request_counter
            request_counter += 1
            request_id = request_counter
            pending_withdrawals[request_id] = {'user_id': user_id, 'amount': amount, 'wallet_type': network, 'address': withdraw_address, 'status': 'pending', 'username': user.username or user.first_name, 'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            await update.message.reply_text(f"⏳ *WITHDRAWAL REQUEST #{request_id} SUBMITTED!*\n\n💰 Amount: ${amount}\n🔗 Network: {network}\n📤 To: `{withdraw_address[:12]}...{withdraw_address[-8:]}`\n🕐 Status: PENDING", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            admin_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVE", callback_data=f"admin_approve_withdraw_{request_id}"), InlineKeyboardButton("❌ REJECT", callback_data=f"admin_reject_withdraw_{request_id}")]])
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🔔 NEW WITHDRAWAL REQUEST #{request_id}\n\n👤 User: @{user.username or user.first_name}\n💰 Amount: ${amount}\n🔗 Network: {network}\n📤 To: `{withdraw_address}`", reply_markup=admin_buttons, parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Enter valid number!")
    context.user_data['awaiting_withdraw_amount'] = False
    context.user_data['withdraw_network'] = None
    context.user_data['withdraw_address'] = None

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("admin_approve_deposit_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_deposits:
            req = pending_deposits[request_id]
            add_balance(req['user_id'], req['amount'])
            await context.bot.send_message(chat_id=req['user_id'], text=f"✅ *DEPOSIT APPROVED!*\n\n💰 Amount: ${req['amount']:.2f}\n💵 New Balance: ${get_wallet(req['user_id'])['balance']:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            await query.edit_message_text(f"✅ Deposit #{request_id} approved!")
            del pending_deposits[request_id]
    elif data.startswith("admin_reject_deposit_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_deposits:
            req = pending_deposits[request_id]
            await context.bot.send_message(chat_id=req['user_id'], text=f"❌ *DEPOSIT REJECTED!*\n\n💰 Amount: ${req['amount']:.2f}\n\nContact @LawlietTobi", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            await query.edit_message_text(f"❌ Deposit #{request_id} rejected!")
            del pending_deposits[request_id]
    elif data.startswith("admin_approve_withdraw_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_withdrawals:
            req = pending_withdrawals[request_id]
            deduct_balance(req['user_id'], req['amount'])
            await context.bot.send_message(chat_id=req['user_id'], text=f"✅ *WITHDRAWAL APPROVED!*\n\n💰 Amount: ${req['amount']:.2f}\n💵 New Balance: ${get_wallet(req['user_id'])['balance']:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            await query.edit_message_text(f"✅ Withdrawal #{request_id} approved!")
            del pending_withdrawals[request_id]
    elif data.startswith("admin_reject_withdraw_"):
        request_id = int(data.split('_')[3])
        if request_id in pending_withdrawals:
            req = pending_withdrawals[request_id]
            await context.bot.send_message(chat_id=req['user_id'], text=f"❌ *WITHDRAWAL REJECTED!*\n\n💰 Amount: ${req['amount']:.2f}\n\nContact @LawlietTobi", reply_markup=get_main_keyboard(), parse_mode='Markdown')
            await query.edit_message_text(f"❌ Withdrawal #{request_id} rejected!")
            del pending_withdrawals[request_id]
    elif data == "back_to_menu":
        await show_main_menu_callback(query)

async def show_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    positions = get_positions(user_id)
    wallet = get_wallet(user_id)
    if not positions:
        await update.message.reply_text("📊 *NO OPEN POSITIONS*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    msg = "📊 *YOUR OPEN POSITIONS*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    total_pnl = 0
    for i, pos in enumerate(positions, 1):
        try:
            if 'USDT' in pos['symbol']:
                exchange = ccxt.binance({'enableRateLimit': True})
                exchange.load_markets()
                current_price = exchange.fetch_ticker(pos['symbol'])['last']
            else:
                current_price = yf.Ticker(pos['symbol']).history(period="1d", interval="5m")['Close'].iloc[-1]
        except:
            current_price = pos['entry']
        pnl_percent = ((current_price - pos['entry']) / pos['entry']) * 100
        pnl_amount = pos['amount'] * (pnl_percent / 100)
        total_pnl += pnl_amount
        emoji = "🟢" if pnl_amount > 0 else "🔴" if pnl_amount < 0 else "⚪"
        msg += f"{emoji} *{i}. {pos['symbol']}*\n   Entry: ${pos['entry']:.4f}\n   Current: ${current_price:.4f}\n   Amount: ${pos['amount']:.2f}\n   P&L: {pnl_percent:+.2f}% (${pnl_amount:+.2f})\n   Opened: {pos['timestamp']}\n   ━━━━━━━━━━━━━━━━━\n"
    msg += f"\n💰 *Total P&L:* ${total_pnl:+.2f}\n💵 *Balance:* ${wallet['balance']:.2f}"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def show_recent_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trades = get_recent_trades(user_id)
    if not trades:
        await update.message.reply_text("📜 *NO RECENT TRADES*", reply_markup=get_main_keyboard(), parse_mode='Markdown')
        return
    msg = "📜 *YOUR RECENT TRADES*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, trade in enumerate(trades, 1):
        msg += f"*{i}. {trade['symbol']}*\n   Signal: {trade['signal']}\n   Entry: ${trade['entry']:.4f}\n   Exit: ${trade['exit']:.4f}\n   P&L: {trade['pnl']}\n   ⏰ {trade['timestamp']}\n   ━━━━━━━━━━━━━━━━━\n"
    await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def send_signal_with_chart(update: Update, context: ContextTypes.DEFAULT_TYPE, symbol, asset_type, name):
    user_id = update.effective_user.id
    await update.message.reply_text(f"📊 *FETCHING SIGNAL FOR {name}* 🔍", parse_mode='Markdown')
    signal = generate_signal(symbol, asset_type, "1h")
    if not signal:
        await update.message.reply_text(f"❌ *Could not fetch signal for {name}*", parse_mode='Markdown')
        return
    chart_path = generate_candlestick_chart(symbol, asset_type, "7d", "1h")
    msg = f"📊 *{name}* | {asset_type.upper()} SIGNAL\n━━━━━━━━━━━━━━━━━━━━━\n⏰ {signal['timestamp']}\n📈 *SIGNAL:* {signal['signal']}\n🎯 *Confidence:* {signal['confidence']}\n💰 *ENTRY:* `${signal['entry']:.4f}`\n🎯 *TP1:* `${signal['tp1']:.4f}`\n🎯 *TP2:* `${signal['tp2']:.4f}`\n🎯 *TP3:* `${signal['tp3']:.4f}`\n🛑 *SL:* `${signal['sl']:.4f}`\n📈 *Risk:Reward:* `1:{signal['rr_ratio']}`\n📊 *RSI:* `{signal['rsi']}`\n💡 *REASONS:*\n"
    for r in signal['reasons'][:3]:
        msg += f"  • {r}\n"
    keyboard = [[InlineKeyboardButton("🟢 BUY", callback_data=f"custom_buy_{symbol}_{asset_type}_{signal['entry']}"), InlineKeyboardButton("🔴 SELL", callback_data=f"sell_{symbol}_{asset_type}_{signal['entry']}")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]
    if chart_path and os.path.exists(chart_path):
        with open(chart_path, 'rb') as chart:
            await update.message.reply_photo(photo=chart, caption=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        os.unlink(chart_path)
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

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
        await query.message.reply_text("❌ *Wallet not connected!*", parse_mode='Markdown')
        return
    if wallet['balance'] < 10:
        await query.message.reply_text(f"❌ *Insufficient balance!* Balance: ${wallet['balance']:.2f}", parse_mode='Markdown')
        return
    await query.message.reply_text(f"💰 *ENTER TRADE AMOUNT*\n\nSymbol: {symbol}\nEntry: ${entry_price:.4f}\nBalance: ${wallet['balance']:.2f}\n\nEnter amount (min $10, max ${wallet['balance']:.2f}):", parse_mode='Markdown')
    context.user_data['pending_custom_buy'] = {'symbol': symbol, 'asset_type': asset_type, 'entry_price': entry_price, 'user_id': user_id}

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
            await update.message.reply_text("❌ *Minimum $10!*", parse_mode='Markdown')
        elif amount > wallet['balance']:
            await update.message.reply_text(f"❌ *Insufficient balance!* Balance: ${wallet['balance']:.2f}", parse_mode='Markdown')
        else:
            quantity = round(amount / entry_price, 6)
            deduct_balance(user_id, amount)
            add_position(user_id, symbol, entry_price, amount, quantity, 'BUY')
            await update.message.reply_text(f"✅ *BUY ORDER PLACED!*\n\nSymbol: {symbol}\nEntry: ${entry_price:.4f}\nAmount: ${amount:.2f}\nQuantity: {quantity}\n\nTP1: ${entry_price * 1.02:.4f}\nTP2: ${entry_price * 1.04:.4f}\nSL: ${entry_price * 0.98:.4f}\n\nRemaining Balance: ${wallet['balance'] - amount:.2f}", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ *Enter valid number!*", parse_mode='Markdown')
    context.user_data['pending_custom_buy'] = None

async def sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    symbol = data[1]
    asset_type = data[2]
    entry_price = float(data[3])
    user_id = update.effective_user.id
    try:
        if asset_type == "crypto":
            exchange = ccxt.binance({'enableRateLimit': True})
            exchange.load_markets()
            current_price = exchange.fetch_ticker(symbol)['last']
        else:
            ticker = yf.Ticker(symbol if asset_type != "forex" else symbol.replace("/", "") + "=X")
            current_price = ticker.history(period="1d", interval="5m")['Close'].iloc[-1]
    except:
        current_price = entry_price
    wallet = get_wallet(user_id)
    if not wallet:
        await query.message.reply_text("❌ *Wallet not connected!*", parse_mode='Markdown')
        return
    profit_percent = ((current_price - entry_price) / entry_price) * 100
    profit_amount = 100 * (profit_percent / 100)
    add_balance(user_id, profit_amount)
    await query.message.reply_text(f"✅ *SELL ORDER EXECUTED!*\n\nSymbol: {symbol}\nEntry: ${entry_price:.4f}\nExit: ${current_price:.4f}\nP&L: {profit_percent:+.2f}% (${profit_amount:+.2f})\n\nNew Balance: ${get_wallet(user_id)['balance']:.2f}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]), parse_mode='Markdown')

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

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👇 *Main Menu* 👇", reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def show_main_menu_callback(query):
    await query.edit_message_text("👇 *Main Menu* 👇", reply_markup=get_main_keyboard(), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if context.user_data.get('pending_custom_buy'):
        await process_custom_buy(update, context)
        return
    if context.user_data.get('awaiting_wallet_address'):
        await handle_wallet_address(update, context)
        return
    if context.user_data.get('awaiting_custom_deposit'):
        await handle_custom_deposit(update, context)
        return
    if context.user_data.get('awaiting_deposit_network'):
        await handle_deposit_network(update, context)
        return
    if context.user_data.get('awaiting_withdraw_network'):
        await handle_withdraw_network(update, context)
        return
    if context.user_data.get('awaiting_withdraw_amount'):
        await handle_withdraw_amount(update, context)
        return
    if text in ["💎 TON", "🪙 TRC20 (USDT)", "🔷 BEP20 (USDT)", "💠 ERC20 (USDT)", "₿ BITCOIN", "◎ SOLANA"]:
        await handle_wallet_type(update, context)
        return
    if text in ["💰 $10", "💰 $25", "💰 $50", "💰 $100", "💰 $250", "💰 $500", "💰 $1000", "💰 CUSTOM"]:
        await handle_deposit_amount(update, context)
        return
    if text == "🪙 CRYPTO SIGNALS":
        await update.message.reply_text("🪙 *SELECT CRYPTO COIN*", reply_markup=get_crypto_keyboard(), parse_mode='Markdown')
    elif text == "💱 FOREX SIGNALS":
        await update.message.reply_text("💱 *SELECT FOREX PAIR*", reply_markup=get_forex_keyboard(), parse_mode='Markdown')
    elif text == "📈 STOCK SIGNALS":
        await update.message.reply_text("📈 *SELECT STOCK*", reply_markup=get_stocks_keyboard(), parse_mode='Markdown')
    elif text == "🌍 ALL MARKETS":
        await update.message.reply_text("🌍 *SCANNING...*", parse_mode='Markdown')
        for symbol in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            signal = generate_signal(symbol, "crypto", "1h")
            if signal and signal['signal'] != "⚪ NEUTRAL":
                await update.message.reply_text(f"🪙 *{symbol}*\n📊 {signal['signal']}\n💰 ${signal['entry']:.2f}", parse_mode='Markdown')
        await update.message.reply_text("🔙 Back", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif text == "👛 MY WALLET":
        await wallet_menu(update, context)
    elif text == "📊 MY POSITIONS":
        await show_positions(update, context)
    elif text == "💰 DEPOSIT":
        await deposit_menu(update, context)
    elif text == "💸 WITHDRAW":
        await withdraw_menu(update, context)
    elif text == "🎁 CLAIM BONUS":
        await claim_bonus_handler(update, context)
    elif text == "👥 REFER & EARN":
        await referral_handler(update, context)
    elif text == "📜 RECENT TRADES":
        await show_recent_trades(update, context)
    elif text == "❓ HELP & SUPPORT":
        await update.message.reply_text("❓ *HELP*\n\n1. Connect Wallet\n2. Claim Bonus\n3. Deposit Funds\n4. Get Signals\n5. Click BUY\n6. Track Positions\n7. Withdraw\n8. Refer Friends", reply_markup=get_main_keyboard(), parse_mode='Markdown')
    elif text == "📞 CONTACT DEVELOPER":
        await update.message.reply_text("📞 *CONTACT:* @LawlietTobi", reply_markup=get_main_keyboard(), parse_mode='Markdown')
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
async def main():
    global bot_app
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("cancel", cancel_command))
    bot_app.add_handler(CallbackQueryHandler(callback_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await bot_app.initialize()
    await bot_app.start()
    
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await bot_app.bot.set_webhook(webhook_url)
    print(f"✅ Bot started! Webhook set to {webhook_url}")
    
    threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=PORT), daemon=True).start()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
