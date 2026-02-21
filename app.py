import os
import asyncio
import threading
from flask import Flask
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Server web
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot e viu!"

@app.route('/health')
def health():
    return "OK", 200

# Bot
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not BOT_TOKEN:
    raise ValueError("Nu există TELEGRAM_TOKEN")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Comanda start
@dp.message()
async def handle_message(message):
    await message.answer("Botul rulează!")

def run_bot():
    asyncio.run(dp.start_polling(bot))

# Pornire
if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
