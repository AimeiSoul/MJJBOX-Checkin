import logging
import os
import json
import asyncio
import cloudscraper
import datetime
import aiofiles
import traceback
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.helpers import escape_markdown
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------------------- 配置 ----------------------
BOT_TOKEN = "8202241005:AAGBKjeBTqJ7RF8tIRqgpg1y0ckDm2Rxnqk"
BASE_URL = "https://mjjbox.com"
DATA_FILE = "users.json"
ADMIN_IDS = {8070909196}  # ✅ 管理员 ID 集合（注意是 set）

# 保存用户信息 {chat_id: {"username": str, "password": str, "time": "HH:MM"}}
users = {}
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

# ---------------------- 登录逻辑 ----------------------
def login(username, password):
    scraper = cloudscraper.create_scraper()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest"
    }

    # 获取 CSRF
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

# ---------------------- 签到逻辑（新版） ----------------------
def checkin(scraper_csrf):
    scraper, csrf = scraper_csrf
    headers = {"X-CSRF-Token": csrf, "X-Requested-With": "XMLHttpRequest"}

    # Step 1: 检查签到状态
    r = scraper.get(f"{BASE_URL}/checkin", headers=headers)
    try:
        data = r.json()
    except Exception:
        return None, f"❌ 获取签到状态失败: {r.text[:200]}"

    if data.get("today_checked_in") is True:
        consecutive_days = data.get("consecutive_days", "-")
        today_points = "-"
        if data.get("checkin_history"):
            today_points = data["checkin_history"][0].get("points_earned", "-")

        msg = (
            f"⚠️ 今天已经签到过了\n"
            f"连续签到: {consecutive_days} 天\n"
            f"获得积分: {today_points}\n"
        )
        return data, msg

    # Step 2: 执行签到
    r = scraper.post(f"{BASE_URL}/checkin", headers=headers)
    try:
        data = r.json()
    except Exception:
        return None, f"❌ 签到请求失败: {r.text[:200]}"

    # Step 3: 解析结果
    if isinstance(data, dict) and "success" in data:
        if data.get("success"):
            msg = (
                f"🎉 签到成功！\n"
                f"{data.get('message', '')}\n"
                f"连续签到: {data.get('consecutive_days', '?')} 天\n"
                f"获得积分: {data.get('points_earned', '?')}"
            )
        else:
            msg = f"❌ 签到失败: {data.get('message', '未知错误')}"
        return data, msg

    return data, f"⚠️ 未知签到响应: {data}"

# ---------------------- Bot 命令 ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 欢迎使用 MJJBOX 签到机器人！\n\n"
        "可用命令:\n"
        "/setuser 用户名 密码 - 保存账号\n"
        "/checkin - 手动签到\n"
        "/settime HH:MM - 设置每日自动签到时间\n"
        "/deluser - 删除账号\n"
        "/listuser - 查看保存的账号\n"
        "/history - 查看签到记录\n"
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
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 你还没有保存账号，请先使用 /setuser")
        return
    info = users[chat_id]
    username = info.get("username", "-")
    time_str = info.get("time") if info.get("time") else "未设置"
    msg = f"👤 用户名：{username}\n🕓 签到时间：{time_str}"
    await update.message.reply_text(msg)

async def listall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ 你没有权限使用此命令。")
        return

    if not users:
        await update.message.reply_text("⚠️ 当前没有保存的用户。")
        return

    msg = "📋 所有绑定的用户信息：\n\n"
    for uid, info in users.items():
        username = info.get("username", "-")
        time_str = info.get("time") if info.get("time") else "未设置"
        msg += f"👤 用户ID: `{uid}`\n账号: `{username}`\n自动签到时间: {time_str}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ---------------------- 手动签到命令 ----------------------
async def checkin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 请先使用 /setuser 保存账号。")
        return

    temp_msg = await update.message.reply_text("⏳ 正在登录并签到，请稍候...")
    asyncio.create_task(run_checkin(chat_id, temp_msg.message_id, context.application))

# ---------------------- 签到执行 ----------------------
async def run_checkin(chat_id, temp_msg_id=None, app=None):
    bot = app.bot
    if chat_id not in user_locks:
        user_locks[chat_id] = asyncio.Lock()

    async with user_locks[chat_id]:
        info = users[chat_id]
        username = info.get("username", "-")

        async def safe_delete():
            if temp_msg_id:
                await asyncio.sleep(0.3)
                try:
                    await bot.delete_message(chat_id, temp_msg_id)
                except Exception:
                    pass

        try:
            scraper_csrf = None
            for i in range(3):
                scraper_csrf, msg_login = await asyncio.to_thread(login, info["username"], info["password"])
                if scraper_csrf:
                    break
                await asyncio.sleep(2)
            if not scraper_csrf:
                raise Exception(f"登录失败: {msg_login}")

            data, msg_checkin = await asyncio.to_thread(checkin, scraper_csrf)
            await safe_delete()

            safe_msg = escape_markdown(msg_checkin, version=2)
            await bot.send_message(chat_id, safe_msg, parse_mode="MarkdownV2")

            log_line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 用户 {chat_id} ({username}) 签到结果: {msg_checkin}\n"
            async with aiofiles.open("checkin.log", "a", encoding="utf-8") as f:
                await f.write(log_line)

        except Exception as e:
            await safe_delete()
            err_text = f"❌ 签到异常: {e}"
            safe_err = escape_markdown(err_text, version=2)
            await bot.send_message(chat_id, safe_err, parse_mode="MarkdownV2")

            err_log = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 用户 {chat_id} ({username}) 签到异常: {e}\n{traceback.format_exc(limit=2)}\n"
            async with aiofiles.open("checkin.log", "a", encoding="utf-8") as f:
                await f.write(err_log)

# ---------------------- 定时任务 ----------------------
async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in users:
        await update.message.reply_text("⚠️ 请先使用 /setuser 保存账号。")
        return
    if len(context.args) != 1 or ":" not in context.args[0]:
        await update.message.reply_text("用法: /settime HH:MM （24小时制）")
        return

    local_hour, minute = map(int, context.args[0].split(":"))
    utc_hour = (local_hour - 8) % 24

    users[chat_id]["time"] = f"{local_hour:02d}:{minute:02d}"
    save_users()

    if scheduler.get_job(str(chat_id)):
        scheduler.remove_job(str(chat_id))

    scheduler.add_job(
        run_checkin,
        trigger="cron",
        hour=utc_hour,
        minute=minute,
        args=[chat_id, None, context.application],
        id=str(chat_id)
    )
    await update.message.reply_text(f"✅ 每日签到时间已设置为 {local_hour:02d}:{minute:02d}")

# ---------------------- 签到历史 ----------------------
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
    for record in history_data[:5]:
        msg += f"{record['date']} | {record['points_earned']:>3} | {record['consecutive_days']:>3}\n"
    msg += "```"

    await update.message.reply_text(msg, parse_mode="Markdown")

# ------------------------ 启动主程序 ----------------------
if __name__ == "__main__":
    load_users()

    async def start_scheduler(app):
        scheduler.start()
        print("✅ Scheduler 已启动...")
        for chat_id, info in users.items():
            if info.get("time"):
                hour, minute = map(int, info["time"].split(":"))
                utc_hour = (hour - 8) % 24
                scheduler.add_job(
                    run_checkin,
                    trigger="cron",
                    hour=utc_hour,
                    minute=minute,
                    args=[chat_id, None, app],
                    id=str(chat_id)
                )
                print(f"✅ 恢复自动签到任务: {chat_id} ({hour:02d}:{minute:02d})")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(start_scheduler).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setuser", setuser))
    app.add_handler(CommandHandler("deluser", deluser))
    app.add_handler(CommandHandler("listuser", listuser))
    app.add_handler(CommandHandler("checkin", checkin_command))
    app.add_handler(CommandHandler("settime", settime))
    app.add_handler(CommandHandler("listall", listall))
    app.add_handler(CommandHandler("history", history))

    print("🤖 Bot 已启动...")
    app.run_polling()
