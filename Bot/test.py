import ccxt
import time
from datetime import datetime, timedelta
import json
import os
import sys
import requests  # For sending messages to Telegram
from constants import TELEGRAM_TOKEN, CHAT_ID

# Initialize Kraken connection without API keys
kraken = ccxt.kraken()

# Define constants
TRADING_PAIRS = 'SOL/USDT'
TRADE_AMOUNT = 0.01  # Adjust as necessary
TAKE_PROFIT_INITIAL = 0.02  # Initial 2% take profit
STOP_LOSS_BUFFER = 0.01  # 1% buffer for initial stop loss
COOLDOWN_PERIOD = 15 * 60  # 15 minutes in seconds
LOG_FILE = 'trade_log.json'
WEEKLY_LOG_FILE = 'weekly_log.json'

# Telegram Bot Credentials
#TELEGRAM_TOKEN = TELEGRAM_TOKEN
#CHAT_ID = CHAT_ID

# Set start time for 7-day tracking
start_time = datetime.now()

# List to track trades
trades = []

def send_telegram_message(message):
    """Send a message to the Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Failed to send message:", e)

def fetch_candles():
    # Fetch the last 10 minutes of 1-minute candles
    candles = kraken.fetch_ohlcv(TRADING_PAIRS, timeframe='1m', limit=10)
    return candles

def get_high_low(candles):
    high = max(candle[2] for candle in candles)
    low = min(candle[3] for candle in candles)
    return high, low

def monitor_market(high, low):
    entry_signal = None
    send_telegram_message("Monitoring market for signals.")
    start_timestamp = datetime.now().isoformat()

    while True:
        time.sleep(10)  # Polling interval
        current_price = kraken.fetch_ticker(TRADING_PAIRS)['last']
        print(f'Current Price: {current_price}')

        if entry_signal is None:
            if current_price > high:
                entry_signal = 'LONG'
                send_telegram_message(f"Signal generated: LONG above {high}")
            elif current_price < low:
                entry_signal = 'SHORT'
                send_telegram_message(f"Signal generated: SHORT below {low}")

        if entry_signal:
            # Wait for price to retest the range
            if entry_signal == 'LONG' and low < current_price < high:
                print("Entering LONG trade")
                send_telegram_message(f"Entering LONG trade at {current_price}")
                result = enter_trade('buy', current_price, low, start_timestamp)
                trades.append(result)
                break
            elif entry_signal == 'SHORT' and low < current_price < high:
                print("Entering SHORT trade")
                send_telegram_message(f"Entering SHORT trade at {current_price}")
                result = enter_trade('sell', current_price, high, start_timestamp)
                trades.append(result)
                break

def enter_trade(order_type, entry_price, opposite_level, start_timestamp):
    entry_timestamp = datetime.now().isoformat()
    stop_loss = opposite_level * (1 - STOP_LOSS_BUFFER) if order_type == 'buy' else opposite_level * (1 + STOP_LOSS_BUFFER)
    take_profit = entry_price * (1 + TAKE_PROFIT_INITIAL) if order_type == 'buy' else entry_price * (1 - TAKE_PROFIT_INITIAL)
    
    # Simulate trade monitoring
    outcome, exit_timestamp, duration, profit_loss = monitor_trade(entry_price, stop_loss, take_profit, order_type)
    
    # Log trade result
    trade_data = {
        'order_type': order_type,
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'entry_timestamp': entry_timestamp,
        'exit_timestamp': exit_timestamp,
        'outcome': outcome,
        'duration': duration,
        'profit_loss': profit_loss
    }
    
    save_trade_log(trade_data)
    
    # Notify on trade exit
    exit_type = "Take Profit" if outcome == "WIN" else "Stop Loss"
    send_telegram_message(f"Exiting {order_type} trade: {exit_type} reached at {exit_timestamp}. Result: {outcome}, Profit/Loss: {profit_loss}")

    return trade_data

def monitor_trade(entry_price, stop_loss, take_profit, order_type):
    entry_time = datetime.now()
    milestone_reached = 0  # Tracks the percentage milestones reached
    profit_loss = 0

    while True:
        time.sleep(10)  # Polling interval
        current_price = kraken.fetch_ticker(TRADING_PAIRS)['last']
        print(f'Trade Monitoring - Current Price: {current_price}')

        # Calculate price change percentage
        if order_type == 'buy':
            price_move_percent = (current_price - entry_price) / entry_price
        else:
            price_move_percent = (entry_price - current_price) / entry_price

        # Update stop loss and take profit as milestones are reached
        if price_move_percent >= 0.01 and milestone_reached < 1:
            stop_loss = entry_price  # Move stop loss to break even
            take_profit = entry_price * (1.03 if order_type == 'buy' else 0.97)  # Set new take profit at 3%
            milestone_reached = 1
            send_telegram_message("Price moved 1% in favor. Adjusted stop loss to break even and take profit to 3%.")

        elif price_move_percent >= 0.02 and milestone_reached < 2:
            stop_loss = entry_price * (1.01 if order_type == 'buy' else 0.99)  # Move stop loss to 1% in profit
            take_profit = entry_price * (1.04 if order_type == 'buy' else 0.96)  # Set new take profit at 4%
            milestone_reached = 2
            send_telegram_message("Price moved 2% in favor. Adjusted stop loss to 1% profit and take profit to 4%.")

        elif price_move_percent >= (milestone_reached + 1) * 0.01:
            stop_loss = entry_price * (1 + (milestone_reached * 0.01) if order_type == 'buy' else 1 - (milestone_reached * 0.01))
            take_profit = entry_price * (1 + ((milestone_reached + 2) * 0.01) if order_type == 'buy' else 1 - ((milestone_reached + 2) * 0.01))
            milestone_reached += 1
            send_telegram_message(f"Price moved to {milestone_reached}% in favor. Adjusted stop loss to {milestone_reached - 1}% profit and take profit to {milestone_reached + 1}%.")

        # Check if the trade hits take profit or stop loss
        if order_type == 'buy':
            if current_price >= take_profit:
                outcome = 'WIN'
                profit_loss = (take_profit - entry_price) * TRADE_AMOUNT
                break
            elif current_price <= stop_loss:
                outcome = 'WIN' if current_price >= entry_price else 'LOSS'
                profit_loss = (current_price - entry_price) * TRADE_AMOUNT
                break
        elif order_type == 'sell':
            if current_price <= take_profit:
                outcome = 'WIN'
                profit_loss = (entry_price - take_profit) * TRADE_AMOUNT
                break
            elif current_price >= stop_loss:
                outcome = 'WIN' if current_price <= entry_price else 'LOSS'
                profit_loss = (entry_price - current_price) * TRADE_AMOUNT
                break

    exit_timestamp = datetime.now().isoformat()
    duration = (datetime.now() - entry_time).seconds // 60  # Duration in minutes
    return outcome, exit_timestamp, duration, profit_loss

def save_trade_log(trade_data):
    # Load existing log if available
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            trade_log = json.load(f)
    else:
        trade_log = []

    # Append new trade and manage log length
    trade_log.append(trade_data)
    trade_log = [trade for trade in trade_log if datetime.fromisoformat(trade['entry_timestamp']) > datetime.now() - timedelta(days=7)]
    
    with open(LOG_FILE, 'w') as f:
        json.dump(trade_log, f, indent=4)
    
    print("Trade logged:", trade_data)
    send_telegram_message("Trade logged to JSON file.")
    
    # Weekly log dump
    if datetime.now() >= start_time + timedelta(days=7):
        with open(WEEKLY_LOG_FILE, 'w') as f:
            json.dump(trade_log, f, indent=4)
        send_telegram_message("Weekly trade log saved.")

def main():
    send_telegram_message("Starting trading bot...")
    print("Starting trading strategy...")

    while True:
        if datetime.now() >= start_time + timedelta(days=7):
            print("7 days have passed. Stopping the trading bot and saving weekly log.")
            send_telegram_message("7 days have passed. Stopping the trading bot.")
            sys.exit()

        candles = fetch_candles()
        high, low = get_high_low(candles)
        
        # Send initial high and low range to Telegram
        send_telegram_message(f"5-minute range identified: High = {high}, Low = {low}")
        print(f"5-minute range: High = {high}, Low = {low}")
        monitor_market(high, low)
        time.sleep(COOLDOWN_PERIOD)  # Cooldown period between trades

if __name__ == "__main__":
    main()
