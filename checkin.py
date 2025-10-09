import logging
import os
import json
import asyncio
import cloudscraper
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------------------- 配置 ----------------------
BOT_TOKEN = "your bot token"
BASE_URL = "https://mjjbox.com"
DATA_FILE = "users.json"

# 保存用户信息 {chat_id: {"username": str, "password": str, "time": "HH:MM"}}
users = {}

# 用户锁，防止同一用户同时签到
user_locks = {}  # {chat_id: asyncio.Lock()}

# APScheduler
scheduler = AsyncIOScheduler()

# ---------------------- 日志 ----------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------------- 数据持久化 ----------------------
def save_users():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def load_users():
    global users
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                tmp_users = json.load(f)
                users = {int(k): v for k, v in tmp_users.items()}
        except Exception as e:
            print(f"⚠️ 读取 {DATA_FILE} 出错: {e}")
            users = {}
    else:
        users = {}

# ---------------------- 登录签到逻辑 ----------------------
def login(username, password):
    scraper = cloudscraper.create_scraper()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    }

    r = scraper.get(f"{BASE_URL}/session/csrf", headers=headers)
    try:
        csrf_pre = r.json().get("csrf")
    except Exception:
        return None, f"获取登录前CSRF失败: {r.text[:200]}"

    headers["X-CSRF-Token"] = csrf_pre
    data = {"login": username, "password": password}
    r = scraper.post(f"{BASE_URL}/session", headers=headers, json=data)
    if r.status_code != 200:
        return None, f"登录失败: {r.text[:200]}"

    r = scraper.get(f"{BASE_URL}/session/csrf", headers=headers)
    try:
        csrf = r.json().get("csrf")
    except Exception:
        return None, f"获取登录后CSRF失败: {r.text[:200]}"

    return (scraper, csrf), "登录成功"

def checkin(scraper_csrf):
    scraper, csrf = scraper_csrf
    headers = {"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"}

    r = scraper.get(f"{BASE_URL}/checkin", headers=headers)
    try:
        data = r.json()
    except Exception:
        return None, f"❌ 获取签到状态失败: {r.text[:200]}"

    today_checked_in = data.get("today_checked_in")

    if today_checked_in:
        consecutive_days = data.get("consecutive_days", "-")
        current_points = data.get("current_points", "-")
        today_points = "-"
        if "checkin_history" in data and data["checkin_history"]:
            today_points = data["checkin_history"][0].get("points_earned", "-")

        msg = (
            f"*签到结果:* ⚠️ 今天已经签到过了\n"
            f"*连续签到:* {consecutive_days} 天\n"
            f"*今日获得积分:* {today_points}\n"
            f"*当前总积分:* {current_points}"
        )
        return data, msg

    r = scraper.post(f"{BASE_URL}/checkin", headers=headers)
    try:
        data = r.json()
    except Exception:
        return None, f"❌ 签到请求失败: {r.text[:200]}"

    if "today_checked_in" in data and data["today_checked_in"]:
        status = "🎉 签到成功"
    elif "errors" in data:
        err = str(data["errors"])
        return data, f"❌ 签到失败: {err}"
    else:
        status = "❌ 未知签到响应"

    consecutive_days = data.get("consecutive_days", "-")
    current_points = data.get("current_points", "-")
    today_points = "-"
    if "checkin_history" in data and data["checkin_history"]:
        today_points = data["checkin_history"][0].get("points_earned", "-")

    msg = (
        f"*签到结果:* {status}\n"
        f"*连续签到:* {consecutive_days} 天\n"
        f"*今日获得积分:* {today_points}\n"
        f"*当前总积分:* {current_points}"
    )
    return data, msg

# ---------------------- Bot命令 ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 欢迎使用 MJJBOX 签到机器人！\n\n"
        "可用命令:\n"
        "/setuser 用户名 密码 - 保存账号\n"
        "/checkin - 手动签到\n"
        "/settime HH:MM - 设置每日自动签到时间\n"
        "/deluser - 删除账号\n"
        "/listuser - 查看保存的账号\n"
        "/history - 查看最近签到记录\n"
    )
    await update.message.reply_text(msg)

async def setuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        await update.message.reply_text("用法: /setuser 用户名 密码")
        return
    username, password = context.args
    users[chat_id] = {"username": username, "password": password, "time": None}
    save_users()
    await update.message.reply_text("✅ 用户信息已保存！")

async def deluser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in users:
        users.pop(chat_id)
        save_users()
        if scheduler.get_job(str(chat_id)):
            scheduler.remove_job(str(chat_id))
        await update.message.reply_text("✅ 用户已删除")
    else:
        await update.message.reply_text("⚠️ 没有已保存的用户")

async def listuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not users:
        await update.message.reply_text("⚠️ 当前没有保存的用户")
        return

    msg = "*当前自动签到用户:*"
    for chat_id, info in users.items():
        username = info.get("username", "-")
        time_str = info.get("time") if info.get("time") else "未设置"
        msg += f"\n**用户名**：{username}\n**签到时间**：{time_str}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 先使用 /setuser 保存账号")
        return

    temp_msg = await update.message.reply_text("⏳ 签到请求已接收，正在处理...")
    temp_msg_id = temp_msg.message_id
    asyncio.create_task(run_checkin(chat_id, temp_msg_id))

async def run_checkin(chat_id, temp_msg_id=None):
    if chat_id not in user_locks:
        user_locks[chat_id] = asyncio.Lock()

    async with user_locks[chat_id]:
        info = users[chat_id]
        scraper_csrf, msg_login = await asyncio.to_thread(login, info["username"], info["password"])
        if not scraper_csrf:
            if temp_msg_id:
                try:
                    await bot.delete_message(chat_id, temp_msg_id)
                except Exception:
                    pass
            await bot.send_message(chat_id, f"登录失败: {msg_login}")
            return

        _, msg_checkin = await asyncio.to_thread(checkin, scraper_csrf)

        if temp_msg_id:
            try:
                await bot.delete_message(chat_id, temp_msg_id)
            except Exception:
                pass

        await bot.send_message(chat_id, msg_checkin, parse_mode="Markdown")

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 先使用 /setuser 保存账号")
        return
    if len(context.args) != 1 or ":" not in context.args[0]:
        await update.message.reply_text("用法: /settime HH:MM （24小时制）")
        return

    local_hour, minute = map(int, context.args[0].split(":"))
    utc_hour = (local_hour - 8) % 24  # 转换为 UTC

    users[chat_id]["time"] = f"{local_hour:02d}:{minute:02d}"
    save_users()

    if scheduler.get_job(str(chat_id)):
        scheduler.remove_job(str(chat_id))

    scheduler.add_job(
        run_checkin,
        trigger="cron",
        hour=utc_hour,
        minute=minute,
        args=[chat_id, None],
        id=str(chat_id)
    )

    await update.message.reply_text(f"✅ 每日签到时间已设置为 {local_hour:02d}:{minute:02d}")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 先使用 /setuser 保存账号")
        return

    info = users[chat_id]
    scraper_csrf, msg_login = await asyncio.to_thread(login, info["username"], info["password"])
    if not scraper_csrf:
        await update.message.reply_text(f"登录失败: {msg_login}")
        return

    scraper, csrf = scraper_csrf
    headers = {"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"}
    r = scraper.get(f"{BASE_URL}/checkin", headers=headers)
    try:
        data = r.json()
    except Exception:
        await update.message.reply_text(f"❌ 获取签到记录失败: {r.text[:200]}")
        return

    history_data = data.get("checkin_history", [])
    if not history_data:
        await update.message.reply_text("⚠️ 暂无签到记录")
        return

    msg = "*最近签到记录:*\n```\n日期        | 积分 | 连续签到\n-----------|-----|--------\n"
    for record in history_data[:10]:
        msg += f"{record['date']} | {record['points_earned']:>3} | {record['consecutive_days']:>3}\n"
    msg += "```"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------------- 主程序 ----------------------
if __name__ == "__main__":
    load_users()  # 加载本地数据

    async def start_scheduler(app):
        scheduler.start()
        print("Scheduler已启动...")

        # 自动恢复已有 /settime 用户的任务
        for chat_id, info in users.items():
            if info.get("time"):
                hour, minute = map(int, info["time"].split(":"))
                utc_hour = (hour - 8) % 24
                if not scheduler.get_job(str(chat_id)):
                    scheduler.add_job(
                        run_checkin,
                        trigger="cron",
                        hour=utc_hour,
                        minute=minute,
                        args=[chat_id, None],
                        id=str(chat_id)
                    )
                    print(f"✅ 恢复用户 {chat_id} 的自动签到任务 ({hour:02d}:{minute:02d})")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(start_scheduler).build()
    bot = app.bot

    # 添加命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setuser", setuser))
    app.add_handler(CommandHandler("deluser", deluser))
    app.add_handler(CommandHandler("listuser", listuser))
    app.add_handler(CommandHandler("checkin", checkin_command))
    app.add_handler(CommandHandler("settime", settime))
    app.add_handler(CommandHandler("history", history))

    print("Bot已启动...")
    app.run_polling()
