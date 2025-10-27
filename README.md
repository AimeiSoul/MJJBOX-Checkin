# MJJBOX 签到机器人

这是一个基于 Telegram 的 MJJBOX 签到机器人，支持自动签到和手动签到，并提供用户管理和签到记录功能。数据本地持久化，即使重启也不会丢失。

---

## 功能

- ✅ **自动签到**  
  可以为每个账号设置每日自动签到时间，Bot 会在设定时间自动完成签到。  

- ✅ **手动签到**  
  使用 `/checkin` 命令可以立即为账号签到。

- ✅ **删除账号**  
  使用 `/deluser` 删除指定账号。

- ✅ **查看签到历史**  
  使用 `/history` 命令查看最近的签到记录，包括日期、积分和连续签到天数。

- ✅ **查看当前保存的用户**  
  使用 `/listuser` 查看当前保存的账号及对应的自动签到时间（不显示密码）。

- ✅ **自定义自动签到时间**  
  使用 `/settime HH:MM` 设置每日自动签到时间（24小时制）。

- ✅ **数据持久化**  
  所有用户信息和签到时间都会保存到本地 `users.json` 文件，Bot 重启后仍然保留。

---

## 安装与运行

> **如不想自己再安装，可使用[Aimei_Notify](https://t.me/AimeiNotify_bot)**。不保证服务的可用性。

1. 安装依赖：

   ```bash
   pip install python-telegram-bot==20.0 apscheduler cloudscraper aiofiles
   ```

2. 复制checkin.py中的内容到本地，或者git到本地

   ```bash
   git clone https://github.com/AimeiSoul/MJJBOX-Checkin.git
   cd MJJBOX-Checkin
   ```

4. 配置 Bot Token：
   在`checkin.py`代码中修改 `BOT_TOKEN` 为你的 Telegram Bot Token：

   ```python
   BOT_TOKEN = "your bot token"
   ```

5. 运行 Bot：

   ```bash
   python3 checkin.py            #测试运行
   nohup python3 checkin.py &    #持久化运行
   ```

---

## Bot 指令

| 指令                | 功能                       |
| ----------------- | ------------------------ |
| `/start`          | 显示欢迎信息及可用命令              |
| `/setuser 用户名 密码` | 保存账号信息，支持同一 chat_id 多个账号 |
| `/deluser`        | 删除当前 chat_id 下的账号        |
| `/checkin`        | 手动签到当前 chat_id 下的所有账号    |
| `/settime HH:MM`  | 设置每日自动签到时间（24小时制）        |
| `/history`        | 查看最近签到记录                 |
| `/listuser`       | 查看当前保存的用户及自动签到时间         |

---

## 注意事项

* Bot 会在本地生成 `users.json` 保存用户信息。
* `/settime` 设置的时间为 **本地时间**，Bot 会自动转换为 UTC 用于 Scheduler 调度。（当你的VPS的时区是标准UTC+8时区，请根据实际情况进行修改）
* 一个TG账号仅支持一个MJJBOX账号的签到。

---

## 开源协议

本项目采用 MIT License。
