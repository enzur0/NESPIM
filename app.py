import os
import sys
import asyncio
import logging
import sqlite3
import aiohttp
import aiofiles
import random
import string
import time
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask, request
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ===== CONFIGURARE LOGGING =====
logging.basicConfig(level=logging.INFO)

# ===== IA TOKEN-UL DE LA RENDER =====
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN', "8591787155:AAF4ez3ipdVmADCn2n-uttjq5NxEusvg4DY")

if not BOT_TOKEN:
    raise ValueError("EROARE: Nu există TELEGRAM_TOKEN în Environment Variables!")

# ===== SERVER WEB PENTRU RENDER =====
app = Flask(__name__)


@app.route('/')
def home():
    return "🇲🇩 Botul Moldovean e viu pe Render! 🤖"


@app.route('/health')
def health():
    return "OK", 200


@app.route(f'/webhook/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Primește update-uri de la Telegram"""
    update = types.Update(**request.json)
    asyncio.run_coroutine_threadsafe(dp.feed_update(bot, update), asyncio.get_event_loop())
    return {"ok": True}


def run_web():
    """Rulează serverul web pe portul dat de Render"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)


# ===== INIȚIALIZARE BOT =====
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# ===== BAZĂ DE DATE =====
def get_db():
    db = sqlite3.connect('moldova_bot.db')
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS users
                   (
                       user_id
                       INTEGER
                       PRIMARY
                       KEY,
                       username
                       TEXT,
                       first_name
                       TEXT,
                       referrer_id
                       INTEGER,
                       downloads_today
                       INTEGER
                       DEFAULT
                       0,
                       total_downloads
                       INTEGER
                       DEFAULT
                       0,
                       unlimited
                       BOOLEAN
                       DEFAULT
                       0,
                       unlimited_until
                       TEXT,
                       join_date
                       TEXT,
                       last_download
                       TEXT,
                       is_admin
                       BOOLEAN
                       DEFAULT
                       0,
                       banned
                       BOOLEAN
                       DEFAULT
                       0
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS admins
                   (
                       user_id
                       INTEGER
                       PRIMARY
                       KEY,
                       added_by
                       INTEGER,
                       added_date
                       TEXT,
                       role
                       TEXT
                       DEFAULT
                       'moderator',
                       can_generate_codes
                       BOOLEAN
                       DEFAULT
                       1,
                       can_ban_users
                       BOOLEAN
                       DEFAULT
                       1,
                       can_view_stats
                       BOOLEAN
                       DEFAULT
                       1,
                       can_promote
                       BOOLEAN
                       DEFAULT
                       0
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS secret_codes
                   (
                       code
                       TEXT
                       PRIMARY
                       KEY,
                       days
                       INTEGER,
                       used_by
                       INTEGER,
                       used_date
                       TEXT,
                       created_by
                       INTEGER,
                       created_date
                       TEXT
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS referrals
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       referrer_id
                       INTEGER,
                       referred_id
                       INTEGER,
                       date
                       TEXT,
                       bonus_given
                       BOOLEAN
                       DEFAULT
                       0
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS admin_logs
                   (
                       id
                       INTEGER
                       PRIMARY
                       KEY
                       AUTOINCREMENT,
                       admin_id
                       INTEGER,
                       action
                       TEXT,
                       target_id
                       INTEGER,
                       details
                       TEXT,
                       date
                       TEXT
                   )
                   ''')

    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS ban_list
                   (
                       user_id
                       INTEGER
                       PRIMARY
                       KEY,
                       banned_by
                       INTEGER,
                       ban_reason
                       TEXT,
                       ban_date
                       TEXT
                   )
                   ''')

    db.commit()
    db.close()


# Inițializăm baza de date
init_db()


# ===== FUNCȚII AJUTĂTOARE =====
def is_admin(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result and result['is_admin'] == 1


def is_banned(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result and result['banned'] == 1


def has_unlimited(user_id):
    if is_banned(user_id):
        return False

    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT unlimited, unlimited_until FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()

    if result and result['unlimited'] == 1 and result['unlimited_until']:
        until = datetime.strptime(result['unlimited_until'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() < until:
            return True
    return False


def generate_secret_code(length=8):
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))


def register_user(user_id, username, first_name, referrer_id=None):
    if is_banned(user_id):
        return False

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    if not cursor.fetchone():
        cursor.execute('''
                       INSERT INTO users (user_id, username, first_name, referrer_id, join_date)
                       VALUES (?, ?, ?, ?, ?)
                       ''', (user_id, username, first_name, referrer_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        if referrer_id and not is_banned(referrer_id):
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (referrer_id,))
            if cursor.fetchone():
                cursor.execute('''
                               INSERT INTO referrals (referrer_id, referred_id, date)
                               VALUES (?, ?, ?)
                               ''', (referrer_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                give_unlimited_bonus(referrer_id, 2)

        db.commit()
        db.close()
        return True

    db.close()
    return False


def give_unlimited_bonus(user_id, days):
    if is_banned(user_id):
        return False

    db = get_db()
    cursor = db.cursor()

    unlimited_until = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
                   UPDATE users
                   SET unlimited       = 1,
                       unlimited_until = ?
                   WHERE user_id = ?
                   ''', (unlimited_until, user_id))

    db.commit()
    db.close()
    return True


def check_daily_limit(user_id):
    if is_banned(user_id):
        return False

    if has_unlimited(user_id):
        return True

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT last_download FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result and result['last_download']:
        last = datetime.strptime(result['last_download'], '%Y-%m-%d %H:%M:%S')
        if last.date() < datetime.now().date():
            cursor.execute('UPDATE users SET downloads_today = 0 WHERE user_id = ?', (user_id,))

    cursor.execute('SELECT downloads_today FROM users WHERE user_id = ?', (user_id,))
    downloads_today = cursor.fetchone()['downloads_today']

    db.close()
    return downloads_today < 3  # 3 video-uri pe zi


def increment_downloads(user_id):
    if is_banned(user_id):
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   UPDATE users
                   SET downloads_today = downloads_today + 1,
                       total_downloads = total_downloads + 1,
                       last_download   = ?
                   WHERE user_id = ?
                   ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))

    db.commit()
    db.close()


def ban_user(admin_id, user_id, reason=None):
    if not is_admin(admin_id) or is_admin(user_id):
        return False

    db = get_db()
    cursor = db.cursor()

    cursor.execute('UPDATE users SET banned = 1 WHERE user_id = ?', (user_id,))
    cursor.execute('''
        INSERT OR REPLACE INTO ban_list (user_id, banned_by, ban_reason, ban_date)
        VALUES (?, ?, ?, ?)
    ''', (user_id, admin_id, reason, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    db.commit()
    db.close()

    log_admin_action(admin_id, 'ban', user_id, reason)
    return True


def unban_user(admin_id, user_id):
    if not is_admin(admin_id):
        return False

    db = get_db()
    cursor = db.cursor()

    cursor.execute('UPDATE users SET banned = 0 WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM ban_list WHERE user_id = ?', (user_id,))

    db.commit()
    db.close()

    log_admin_action(admin_id, 'unban', user_id)
    return True


def log_admin_action(admin_id, action, target_id=None, details=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
                   INSERT INTO admin_logs (admin_id, action, target_id, details, date)
                   VALUES (?, ?, ?, ?, ?)
                   ''', (admin_id, action, target_id, details, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    db.commit()
    db.close()


def add_admin(admin_id, new_admin_id):
    if not is_admin(admin_id):
        return False

    db = get_db()
    cursor = db.cursor()

    cursor.execute('UPDATE users SET is_admin = 1 WHERE user_id = ?', (new_admin_id,))
    cursor.execute('''
        INSERT OR REPLACE INTO admins (user_id, added_by, added_date, role)
        VALUES (?, ?, ?, 'moderator')
    ''', (new_admin_id, admin_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    db.commit()
    db.close()

    log_admin_action(admin_id, 'add_admin', new_admin_id)
    return True


# ===== FUNCȚII DESCĂRCARE =====
async def download_video(url):
    try:
        api_url = f"https://tikwm.com/api/?url={url}"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("code") == 0:
                        video_data = data.get("data", {})
                        video_url = video_data.get("play")

                        if video_url:
                            async with session.get(video_url, timeout=30) as video_response:
                                if video_response.status == 200:
                                    filename = f"downloads/video_{hash(url)}.mp4"

                                    async with aiofiles.open(filename, 'wb') as f:
                                        await f.write(await video_response.read())

                                    return filename, video_data.get("title", "video")
    except Exception as e:
        print(f"Eroare descărcare: {e}")

    return None, None


def is_valid_url(text):
    platforms = ['tiktok.com', 'instagram.com', 'pin.it', 'pinterest.com', 'youtube.com', 'youtu.be']
    return any(platform in text for platform in platforms)


# ===== MENIURI =====
def get_user_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 CUM SĂ DESCARCI", callback_data="howto")],
        [InlineKeyboardButton(text="🎁 SISTEM REFERAL", callback_data="referal")],
        [InlineKeyboardButton(text="🔐 COD SECRET", callback_data="secret_code")],
        [InlineKeyboardButton(text="📊 STATISTICI", callback_data="stats")],
        [InlineKeyboardButton(text="🌐 PLATFORME", callback_data="platforms")]
    ])
    return keyboard


def get_admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 STATISTICI", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 UTILIZATORI", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔐 GENEREAZĂ COD", callback_data="admin_gencode")],
        [InlineKeyboardButton(text="🚫 BANARE", callback_data="admin_ban")],
        [InlineKeyboardButton(text="👑 ADMINI", callback_data="admin_list")],
        [InlineKeyboardButton(text="📋 LOG-URI", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🔙 MENIU USER", callback_data="back_to_user")]
    ])
    return keyboard


# ===== COMENZI USER =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if is_banned(message.from_user.id):
        await message.answer("❌ <b>AI FOST BANAT!</b>")
        return

    args = message.text.split()
    referrer_id = None

    if len(args) > 1 and args[1].startswith('ref'):
        try:
            referrer_id = int(args[1][3:])
        except:
            pass

    register_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        referrer_id
    )

    welcome_text = """
<b>🔥 BUN VENIT LA MOLDOVAN BOT! 🔥</b>

<code>╔══════════════════════════╗</code>
<code>║  📹 VIDEO FĂRĂ WATERMARK ║</code>
<code>║  🎯 TIKTOK | INSTAGRAM   ║</code>
<code>║  📌 PINTEREST | YOUTUBE  ║</code>
<code>╚══════════════════════════╝</code>

<b>🇲🇩 CE POT SĂ FAC:</b>
➤ Descarc video fără semn de apă
➤ Sistem referal cu bonusuri
➤ Coduri pentru acces nelimitat

<b>📌 CUM FOLOSEȘTI:</b>
1. Găsești un video
2. Copiezi link-ul
3. Îl trimiți aici
4. Primești video curat

<b>👇 ALEGE O OPȚIUNE 👇</b>
"""

    if is_admin(message.from_user.id):
        welcome_text += "\n\n<b>👑 AI ACCES ADMIN!</b>"
        keyboard = get_admin_keyboard()
    else:
        keyboard = get_user_keyboard()

    await message.answer(welcome_text, reply_markup=keyboard)


@dp.message(Command("code"))
async def use_secret_code(message: Message):
    args = message.text.split()
    user_id = message.from_user.id

    if len(args) < 2:
        await message.answer("❌ <b>Folosește:</b> /code NUMELE_CODULUI")
        return

    code = args[1].upper()

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT * FROM secret_codes WHERE code = ? AND used_by IS NULL', (code,))
    code_data = cursor.fetchone()

    if code_data:
        cursor.execute('''
                       UPDATE secret_codes
                       SET used_by   = ?,
                           used_date = ?
                       WHERE code = ?
                       ''', (user_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), code))

        give_unlimited_bonus(user_id, code_data['days'])

        db.commit()
        db.close()

        await message.answer(f"""
✅ <b>COD ACTIVAT!</b>

<b>🔐 COD:</b> {code}
<b>📅 ZILE UNLIMITED:</b> {code_data['days']}

Acum poți descărca fără limită! 🔥
""")
    else:
        db.close()
        await message.answer("❌ <b>COD INVALID!</b>")


# ===== CALLBACK-URI USER =====
@dp.callback_query(lambda c: c.data == "howto")
async def howto_callback(callback: CallbackQuery):
    text = """
<b>📥 CUM SĂ DESCARCI?</b>

<b>1️⃣ GĂSEȘTE VIDEO:</b>
• Deschide TikTok/IG/YT

<b>2️⃣ COPIAZĂ LINK-UL:</b>
• Apasă "Distribuie"
• Alege "Copiază link-ul"

<b>3️⃣ TRIMITE AICI:</b>
• Lipește link-ul în chat
• Așteaptă câteva secunde
• Primești video FĂRĂ WATERMARK!
"""
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "referal")
async def referal_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start=ref{user_id}"

    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?', (user_id,))
    ref_count = cursor.fetchone()['count']
    db.close()

    text = f"""
<b>🎁 SISTEM REFERAL!</b>

<b>👥 PRIETENI INVITAȚI: {ref_count}</b>

<b>🎯 CUM FUNCȚIONEAZĂ?</b>
➤ Dai link-ul la prieteni
➤ Ei intră pe bot
➤ TU primești 2 ZILE UNLIMITED

<b>🔗 LINK-UL TĂU:</b>
<code>{ref_link}</code>
"""

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "secret_code")
async def secret_code_callback(callback: CallbackQuery):
    text = """
<b>🔐 COD SECRET</b>

<b>Ai un cod? Scrie:</b>
<code>/code NUMELE_CODULUI</code>

<b>Exemplu:</b>
<code>/code MOLDOVA2024</code>

<b>Codurile oferă acces NELIMITAT!</b>
"""
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   SELECT downloads_today, total_downloads, unlimited, unlimited_until
                   FROM users
                   WHERE user_id = ?
                   ''', (user_id,))
    user_stats = cursor.fetchone()

    cursor.execute('SELECT COUNT(*) as count FROM referrals WHERE referrer_id = ?', (user_id,))
    ref_count = cursor.fetchone()['count']

    db.close()

    unlimited_text = "DA 🔥" if has_unlimited(user_id) else "NU ❌"
    remaining = 3 - user_stats['downloads_today'] if not has_unlimited(user_id) else "∞"

    text = f"""
<b>📊 STATISTICI PERSONALE</b>

<b>👤 UTILIZATOR:</b> {callback.from_user.first_name}
<b>📥 DESCĂRCĂRI AZI:</b> {user_stats['downloads_today']}/{remaining}
<b>📥 DESCĂRCĂRI TOTAL:</b> {user_stats['total_downloads']}
<b>🎁 REFERAL-URI:</b> {ref_count}
<b>⚡ ACCES NELIMITAT:</b> {unlimited_text}
"""

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "platforms")
async def platforms_callback(callback: CallbackQuery):
    text = """
<b>🌐 PLATFORME SUPORTATE</b>

✅ <b>TikTok</b>
✅ <b>Instagram</b>
✅ <b>Pinterest</b>
✅ <b>YouTube</b>

<i>Trimite link și primești video curat!</i>
"""
    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_user")
async def back_to_user_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "📋 <b>MENIU PRINCIPAL</b>",
        reply_markup=get_user_keyboard()
    )
    await callback.answer()


# ===== COMENZI ADMIN =====
@dp.message(Command("codegen"))
async def cmd_codegen(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Folosește: /codegen ZILE")
        return

    try:
        days = int(args[1])
        code = generate_secret_code()

        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
                       INSERT INTO secret_codes (code, days, created_by, created_date)
                       VALUES (?, ?, ?, ?)
                       ''', (code, days, message.from_user.id, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        db.commit()
        db.close()

        await message.answer(f"""
✅ <b>COD GENERAT!</b>

<b>🔐 COD:</b> <code>{code}</code>
<b>📅 ZILE:</b> {days}
""")
    except:
        await message.answer("❌ Eroare!")


@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Folosește: /ban ID")
        return

    try:
        target_id = int(args[1])
        reason = ' '.join(args[2:]) if len(args) > 2 else "Fără motiv"

        if ban_user(message.from_user.id, target_id, reason):
            await message.answer(f"✅ User-ul {target_id} a fost banat!")
        else:
            await message.answer("❌ Nu s-a putut bana!")
    except:
        await message.answer("❌ ID invalid!")


@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Folosește: /unban ID")
        return

    try:
        target_id = int(args[1])

        if unban_user(message.from_user.id, target_id):
            await message.answer(f"✅ User-ul {target_id} a fost debanat!")
        else:
            await message.answer("❌ Nu s-a putut debana!")
    except:
        await message.answer("❌ ID invalid!")


@dp.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Folosește: /addadmin ID")
        return

    try:
        target_id = int(args[1])

        if add_admin(message.from_user.id, target_id):
            await message.answer(f"✅ User-ul {target_id} a devenit ADMIN!")
        else:
            await message.answer("❌ Nu s-a putut adăuga!")
    except:
        await message.answer("❌ ID invalid!")


# ===== CALLBACK-URI ADMIN =====
@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute('SELECT COUNT(*) as count FROM users')
    total_users = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM users WHERE banned = 1')
    banned_users = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM admins')
    total_admins = cursor.fetchone()['count']

    cursor.execute('SELECT SUM(total_downloads) as total FROM users')
    total_downloads = cursor.fetchone()['total'] or 0

    cursor.execute('SELECT COUNT(*) as count FROM referrals')
    total_refs = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM secret_codes WHERE used_by IS NOT NULL')
    codes_used = cursor.fetchone()['count']

    db.close()

    text = f"""
<b>📊 STATISTICI ADMIN</b>

<b>👥 UTILIZATORI:</b>
• Total: {total_users}
• Banați: {banned_users}
• Admini: {total_admins}

<b>📥 DESCĂRCĂRI:</b> {total_downloads}
<b>🎁 REFERAL-URI:</b> {total_refs}
<b>🔐 CODURI FOLOSITE:</b> {codes_used}
"""

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   SELECT user_id, username, first_name, total_downloads, banned, is_admin
                   FROM users
                   ORDER BY join_date DESC LIMIT 10
                   ''')

    users = cursor.fetchall()
    db.close()

    text = "<b>👥 ULTIMII 10 UTILIZATORI</b>\n\n"

    for user in users:
        status = "👑" if user['is_admin'] else "🚫" if user['banned'] else "✅"
        name = user['username'] or user['first_name'] or f"User{user['user_id']}"
        text += f"{status} <b>{name[:20]}</b>\n"
        text += f"   ID: <code>{user['user_id']}</code> | 📥 {user['total_downloads']}\n\n"

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_gencode")
async def admin_gencode_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer(
        "🔐 <b>GENEREAZĂ COD:</b>\n\nScrie: /codegen ZILE\n\nExemplu: /codegen 30"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_ban")
async def admin_ban_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer(
        "🚫 <b>BANEAZĂ:</b>\n\nScrie: /ban ID MOTIV\n\nExemplu: /ban 123456789 Spam"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_list")
async def admin_list_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   SELECT a.user_id, a.role, u.username, u.first_name
                   FROM admins a
                            JOIN users u ON a.user_id = u.user_id
                   ''')

    admins = cursor.fetchall()
    db.close()

    text = "<b>👑 LISTĂ ADMINI</b>\n\n"

    for admin in admins:
        name = admin['username'] or admin['first_name'] or f"User{admin['user_id']}"
        text += f"👑 <b>{name}</b>\n"
        text += f"   ID: <code>{admin['user_id']}</code> | {admin['role']}\n\n"

    await callback.message.answer(text)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "admin_logs")
async def admin_logs_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    db = get_db()
    cursor = db.cursor()

    cursor.execute('''
                   SELECT *
                   FROM admin_logs
                   ORDER BY date DESC
                       LIMIT 10
                   ''')

    logs = cursor.fetchall()
    db.close()

    text = "<b>📋 ULTIMELE 10 ACȚIUNI</b>\n\n"

    for log in logs:
        text += f"• {log['date'][:16]} - {log['action']}\n"
        if log['target_id']:
            text += f"  → {log['target_id']}\n"
        if log['details']:
            text += f"  <i>{log['details']}</i>\n"
        text += "\n"

    await callback.message.answer(text)
    await callback.answer()


# ===== HANDLER PRINCIPAL PENTRU LINK-URI =====
@dp.message()
async def handle_message(message: Message):
    user_id = message.from_user.id

    if is_banned(user_id):
        await message.answer("❌ <b>AI FOST BANAT!</b>")
        return

    if not message.text or message.text.startswith('/'):
        return

    if not is_valid_url(message.text):
        await message.answer(
            "❌ <b>ĂSTA NU-I LINK VALID!</b>\n\n"
            "Platforme suportate:\n"
            "✓ TikTok\n✓ Instagram\n✓ Pinterest\n✓ YouTube"
        )
        return

    if not check_daily_limit(user_id):
        await message.answer(
            f"❌ <b>AI EPUIZAT LIMITA DE 3 VIDEO/AZI!</b>\n\n"
            "🎁 Fă referal-uri pentru acces nelimitat!\n"
            "🔐 Sau bagă un cod secret!"
        )
        return

    status_msg = await message.answer("⏬ <b>Procesez video-ul...</b>")

    filename, title = await download_video(message.text)

    if filename and os.path.exists(filename):
        try:
            increment_downloads(user_id)

            with open(filename, 'rb') as video:
                await message.answer_video(
                    video=types.BufferedInputFile(video.read(), filename=f"video.mp4"),
                    caption=f"✅ <b>GATA!</b>\n\n📥 <b>VIDEO FĂRĂ WATERMARK</b>"
                )

            os.remove(filename)
        except Exception as e:
            await message.answer(f"❌ <b>Eroare: {str(e)[:50]}</b>")
        finally:
            await status_msg.delete()
    else:
        await status_msg.delete()
        await message.answer("❌ <b>NU AM PUTUT DESCARCA!</b>")


# ===== PORNIRE BOT =====
async def on_startup():
    """Setăm webhook-ul când pornește botul"""
    RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/webhook/{BOT_TOKEN}"
        await bot.set_webhook(url=webhook_url)
        print(f"✅ Webhook setat la: {webhook_url}")


async def main():
    await on_startup()
    print("🚀 Botul e gata de lucru!")


if __name__ == "__main__":
    # Pornim serverul web într-un thread separat
    web_thread = Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()

    # Pornim botul
    asyncio.run(main())

    # Ținem programul în viață
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("👋 Bot oprit!")
