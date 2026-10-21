import logging
from datetime import datetime
import csv
import os
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = "
8827972928:AAGkYSEfrIhah5DN_AmLdqVPpZeR4CJNOOw"
USER_CHAT_ID = None  
CSV_FILE = "energy_log.csv"

# প্রতিটি রুম এবং তার আলাদা আলাদা অ্যাপ্লায়েন্স ও ওয়াটেজ
ROOMS_APPLIANCES = {
    "Reading Room": {"Fan": 70, "Light": 18},
    "Bed Room": {"Fan": 70, "Light": 18, "TV": 45},
    "Bathroom": {"Light": 18},
    "Kitchen": {"Light": 18},
    "Refrigerator": {"Fridge": 52}
}

daily_log = {}
current_hour = 0
temp_hourly_data = {}  
current_room_idx = 0
current_app_idx = 0

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Date", "Time", "Hour_No", "Reading_Room", 
                "Bed_Room", "Bathroom", "Kitchen", "Refrigerator"
            ])

def save_to_csv(hour_no, room_data):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([
            date_str,
            time_str,
            f"Hour {hour_no}",
            str(room_data.get("Reading Room", {})),
            str(room_data.get("Bed Room", {})),
            str(room_data.get("Bathroom", {})),
            str(room_data.get("Kitchen", {})),
            str(room_data.get("Refrigerator", {}))
        ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global USER_CHAT_ID
    USER_CHAT_ID = update.effective_chat.id
    
    welcome_text = (
        "🤖 **Smart Energy Monitoring Bot Active!**\n\n"
        f"আপনার চ্যাট আইডি (`{USER_CHAT_ID}`) সেভ করা হয়েছে।\n"
        "এখন থেকে প্রতি ঘণ্টায় অটোমেটিক আপনার কাছে অ্যাপ্লায়েন্সের স্ট্যাটাস জানতে চাওয়া হবে।"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    
    if 'job_started' not in context.chat_data:
        context.chat_data['job_started'] = True
        context.job_queue.run_repeating(trigger_hourly_job, interval=3600, first=5, chat_id=USER_CHAT_ID)

async def trigger_hourly_job(context: ContextTypes.DEFAULT_TYPE):
    global current_hour, current_room_idx, current_app_idx, temp_hourly_data
    chat_id = context.job.chat_id or USER_CHAT_ID
    if not chat_id:
        return

    temp_hourly_data.clear()
    current_room_idx = 0
    current_app_idx = 0
    
    # রাত ১২টা থেকে সকাল ৮টার মধ্যে হলে নাইট মোড অ্যাপ্লাই হবে
    current_time_hour = datetime.now().hour
    is_night_mode = 0 <= current_time_hour < 8

    if is_night_mode:
        for room_name, devices in ROOMS_APPLIANCES.items():
            room_status = {}
            for dev_name in devices.keys():
                if room_name in ["Bathroom", "Kitchen"]:
                    room_status[dev_name] = "off"
                elif dev_name == "Fan":
                    room_status[dev_name] = "on"
                elif dev_name == "Light":
                    room_status[dev_name] = "off"
                else:
                    room_status[dev_name] = "on"
            temp_hourly_data[room_name] = room_status

        global daily_log
        daily_log[current_hour] = temp_hourly_data.copy()
        save_to_csv(current_hour + 1, temp_hourly_data)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🌙 **রাত ১২টা - সকাল ৮টা নাইট মোড অ্যাপ্লাই হয়েছে!**\nঘণ্টা {current_hour + 1}-এর ডেটা অটো সেভ করা হয়েছে।"
        )
        current_hour += 1
        if current_hour >= 24:
            await generate_24h_report(context)
            current_hour = 0
        return

    await send_next_prompt(chat_id, context)

async def send_next_prompt(chat_id, context: ContextTypes.DEFAULT_TYPE, message_id=None):
    global current_room_idx, current_app_idx
    rooms = list(ROOMS_APPLIANCES.keys())
    
    if current_room_idx >= len(rooms):
        return

    room_name = rooms[current_room_idx]
    appliances = list(ROOMS_APPLIANCES[room_name].keys())
    app_name = appliances[current_app_idx]

    keyboard = [
        [
            InlineKeyboardButton("🟢 অন (On)", callback_data=f"app_on"),
            InlineKeyboardButton("🔴 অফ (Off)", callback_data=f"app_off")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"⏰ **ঘণ্টা নং: {current_hour + 1} / ২৪**\n\n🏠 **{room_name}**\n👉 **{app_name}**-এর বর্তমান অবস্থা কী?"

    if message_id:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_room_idx, current_app_idx, current_hour, temp_hourly_data, USER_CHAT_ID
    query = update.callback_query
    await query.answer()

    data = query.data
    rooms = list(ROOMS_APPLIANCES.keys())
    room_name = rooms[current_room_idx]
    appliances = list(ROOMS_APPLIANCES[room_name].keys())
    app_name = appliances[current_app_idx]

    status = "on" if data == "app_on" else "off"
    if room_name not in temp_hourly_data:
        temp_hourly_data[room_name] = {}
    temp_hourly_data[room_name][app_name] = status

    current_app_idx += 1
    if current_app_idx >= len(appliances):
        current_app_idx = 0
        current_room_idx += 1

    if current_room_idx < len(rooms):
        await send_next_prompt(update.effective_chat.id, context, message_id=query.message.message_id)
    else:
        daily_log[current_hour] = temp_hourly_data.copy()
        save_to_csv(current_hour + 1, temp_hourly_data)

        await query.edit_message_text(
            text=f"✅ **ঘণ্টা {current_hour + 1}-এর সকল রুমের স্ট্যাটাস সফলভাবে সেভ হয়েছে!**"
        )
        current_hour += 1

        if current_hour >= 24:
            await generate_24h_report(context)
            current_hour = 0

async def download_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'rb') as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename="energy_log.csv",
                caption="📊 **আপনার সমস্ত ইনপুটের CSV ফাইল ডাউনলোড তৈরি হয়েছে!**"
            )
    else:
        await update.message.reply_text("❌ কোনো CSV ফাইল পাওয়া যায়নি! এখনও কোনো ইনপুট দেওয়া হয়নি।")

async def generate_24h_report(context: ContextTypes.DEFAULT_TYPE):
    global daily_log, USER_CHAT_ID
    total_energy_kwh = 0.0

    for h in range(24):
        h_status = daily_log.get(h, {})
        h_total_watt = 0
        for room, devices in ROOMS_APPLIANCES.items():
            r_dev_status = h_status.get(room, {})
            for dev, power in devices.items():
                if r_dev_status.get(dev, "off") == "on":
                    h_total_watt += power
        total_energy_kwh += (h_total_watt / 1000.0)

    report = (
        "📊 **২৪ ঘণ্টার রেসিডেন্সিয়াল লোড অ্যানালিসিস রিপোর্ট**\n"
        "----------------------------------------------\n"
        f"💡 **Total Electricity Consumed:** `{total_energy_kwh:.3f} Units (kWh)`\n"
        "----------------------------------------------\n"
        "পরবর্তী ২৪ ঘণ্টার ট্র্যাকিং চক্র শুরু হলো।"
    )

    await context.bot.send_message(chat_id=USER_CHAT_ID, text=report, parse_mode='Markdown')
    daily_log.clear()

# --- ফ্লাস্ক ডামি সার্ভার (Render ফ্রি ওয়েবের জন্য) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Smart Energy Bot is running alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

def main():
    init_csv()
    
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    custom_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = ApplicationBuilder().token(BOT_TOKEN).request(custom_request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_csv))
    app.add_handler(CommandHandler("csv", download_csv))
    app.add_handler(CallbackQueryHandler(button_click))

    print("🤖 Smart Load Bot is running as a Web Service...")
    app.run_polling()

if __name__ == "__main__":
    main()
