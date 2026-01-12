import os
import asyncio
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime, timezone

# =======================
# ENV VARIABLES
# =======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")

PAIRS = os.getenv("SYMBOLS", "").split(",")
TIMEFRAME = os.getenv("TIMEFRAME", "1min")
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))

RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

CHECK_INTERVAL = 60  # seconds

API_URL = "https://api.twelvedata.com/rsi"

# =======================
# TELEGRAM COMMANDS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ RSI Bot started")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Status\nPairs: {', '.join(PAIRS)}\nTF: {TIMEFRAME}\nRSI Period: {RSI_PERIOD}"
    )

# =======================
# RSI CHECKER
# =======================
async def check_rsi(app):
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            for symbol in PAIRS:
                params = {
                    "symbol": symbol,
                    "interval": TIMEFRAME,
                    "period": RSI_PERIOD,
                    "apikey": TWELVE_API_KEY
                }

                try:
                    r = await client.get(API_URL, params=params)
                    data = r.json()

                    if "values" not in data:
                        continue

                    rsi = float(data["values"][0]["rsi"])

                    if rsi >= RSI_OVERBOUGHT:
                        await app.bot.send_message(
                            chat_id=os.getenv("CHAT_ID"),
                            text=f"🔴 {symbol} RSI {rsi:.2f} → OVERBOUGHT"
                        )

                    elif rsi <= RSI_OVERSOLD:
                        await app.bot.send_message(
                            chat_id=os.getenv("CHAT_ID"),
                            text=f"🟢 {symbol} RSI {rsi:.2f} → OVERSOLD"
                        )

                except Exception as e:
                    print("Error:", e)

            await asyncio.sleep(CHECK_INTERVAL)

# =======================
# MAIN
# =======================
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    asyncio.create_task(check_rsi(app))

    print("🤖 Bot is running...")
    await app.run_polling()

if name == "__main__":
    asyncio.run(main())
