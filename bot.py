"""TEMIRCHI GPS — Telegram bot (ega paneli + 19:00 avtomat hisobot)."""
import os, asyncio, logging, datetime as dt
from aiohttp import web as aioweb
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import db
from server import make_web_app, make_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gps")

TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = db.OWNER_ID
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "19"))


def _harita_link(hid, ism, sana):
    if not WEBAPP_URL:
        return ""
    tok = make_token(OWNER_ID, TOKEN) if OWNER_ID else ""
    import urllib.parse as up
    return f"{WEBAPP_URL}/harita?hid={hid}&sana={sana}&nom={up.quote(ism or '')}&tok={tok}"


def _hayd_matni(h, sana):
    x = db.kunlik_xulosa(h["id"], sana)
    if not x["soni"]:
        return f"🚚 *{h['ism']}* — {sana[5:]}\n   _bugun ma'lumot yo'q (ilova ochilmagan?)_"
    td = x["toxtash_daq"]; soat, daq = td // 60, td % 60
    link = _harita_link(h["id"], h["ism"], sana)
    s = (f"🚚 *{h['ism']}* — {sana[5:]}\n"
         f"🕐 {x['ish_vaqti']}\n"
         f"📏 {x['km']} km · 🛑 {len(x['toxtashlar'])} to'xtash"
         + (f" ({soat}s {daq}daq)" if td else "") )
    if link:
        s += f"\n🗺 [Kartada ko'rish]({link})"
    return s


async def _hisobot_yubor(bot, chat_id, sana=None):
    sana = sana or db.today_tk().isoformat()
    hlar = db.haydovchilar()
    if not hlar:
        await bot.send_message(chat_id, "Haydovchi qo'shilmagan. Panel orqali qo'shing.")
        return
    bosh = f"📊 *Kunlik hisobot — {sana}*\n"
    parts = [bosh] + [_hayd_matni(h, sana) for h in hlar]
    await bot.send_message(chat_id, "\n\n".join(parts), parse_mode="Markdown",
                           disable_web_page_preview=True)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if OWNER_ID and uid != OWNER_ID:
        await update.message.reply_text("🔒 Bu — shaxsiy kuzatuv paneli.")
        return
    kb = None
    if WEBAPP_URL:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "🗺 Kuzatuv paneli", web_app=WebAppInfo(url=WEBAPP_URL + "/"))]])
    await update.message.reply_text(
        "🚚 *TEMIRCHI — Haydovchi kuzatuvi*\n\n"
        "Panelda: haydovchilar, kunlik karta (issiqlik + to'xtashlar), kuzatuv havolasi.\n"
        f"Har kuni soat {REPORT_HOUR}:00 da avtomat hisobot keladi.\n\n"
        "/otchot — hozir hisobot",
        parse_mode="Markdown", reply_markup=kb)


async def otchot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if OWNER_ID and uid != OWNER_ID:
        return
    await _hisobot_yubor(ctx.bot, update.effective_chat.id)


async def hisobot_loop(app):
    """Har kuni REPORT_HOUR:00 da egaga avtomat hisobot."""
    yuborilgan = None
    while True:
        try:
            now = db.now_tk()
            kun = now.date().isoformat()
            if now.hour == REPORT_HOUR and yuborilgan != kun and OWNER_ID:
                await _hisobot_yubor(app.bot, OWNER_ID)
                yuborilgan = kun
                log.info("Kunlik hisobot yuborildi: %s", kun)
        except Exception:
            log.exception("hisobot_loop xato")
        await asyncio.sleep(50)


async def run():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("otchot", otchot))

    port = int(os.getenv("PORT", "8080"))
    runner = aioweb.AppRunner(make_web_app(TOKEN))
    await runner.setup()
    site = aioweb.TCPSite(runner, "0.0.0.0", port)

    await app.initialize()
    await app.start()
    await site.start()

    if WEBAPP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🗺 Panel", web_app=WebAppInfo(url=WEBAPP_URL + "/")))
        except Exception:
            log.exception("menyu tugmasi")

    await app.updater.start_polling()
    asyncio.create_task(hisobot_loop(app))
    log.info("GPS bot + panel ishga tushdi (port %s).", port)
    await asyncio.Event().wait()


def main():
    db.init_db()
    asyncio.run(run())


if __name__ == "__main__":
    main()
