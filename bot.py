import logging
import random
import string
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# ===================== CONFIG =====================
BOT_TOKEN    = "8787082671:AAG5WJW2BY1cshrWY2rbch9ZeR-tndUEhuQ"
CHANNEL_ID   = -1003676153007   # private storage channel (files saved here)
DELETE_AFTER = 300              # 5 min auto-delete

ADMIN_IDS    = [8107369195]

# Force-subscribe channels — add your backup channels here
# Format: ("Display Name", "https://t.me/username", channel_id_number)
FORCE_SUB_CHANNELS = [
    ("📢 Channel 1", "https://t.me/yourchannel1", -1001111111111),
    ("📢 Channel 2", "https://t.me/yourchannel2", -1001222222222),
]
# ==================================================

file_db = {}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)


# ─── Check if user is member of all force-sub channels ───────────────────────
async def check_membership(bot, user_id: int) -> list:
    """Returns list of channels user has NOT joined."""
    not_joined = []
    for name, link, cid in FORCE_SUB_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=cid, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                not_joined.append((name, link))
        except TelegramError:
            not_joined.append((name, link))
    return not_joined


# ─── Build join keyboard ──────────────────────────────────────────────────────
def join_keyboard(not_joined: list, code: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, url=link)] for name, link in not_joined]
    buttons.append([InlineKeyboardButton("✅ I Joined — Try Again", callback_data=f"verify:{code}")])
    return InlineKeyboardMarkup(buttons)


# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if context.args:
        code = context.args[0]
        await deliver_file(update, context, user, code)
        return

    await update.message.reply_text(
        f"👋 <b>Hello {user.first_name}!</b>\n\n"
        "Click a share link to receive files.",
        parse_mode=ParseMode.HTML
    )


# ─── Deliver file (with membership check) ────────────────────────────────────
async def deliver_file(update_or_query, context, user, code):
    """Send file if member, else show join buttons."""
    is_callback = hasattr(update_or_query, 'data')

    if code not in file_db:
        text = "❌ Invalid or expired link."
        if is_callback:
            await update_or_query.edit_message_text(text)
        else:
            await update_or_query.message.reply_text(text)
        return

    # Check membership
    not_joined = await check_membership(context.bot, user.id)

    if not_joined:
        text = (
            "🔒 <b>Access Restricted</b>\n\n"
            "You must join our channels to receive this file:\n"
            "After joining, press <b>✅ I Joined — Try Again</b>"
        )
        kb = join_keyboard(not_joined, code)
        if is_callback:
            await update_or_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await update_or_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Member — send file
    data = file_db[code]
    chat_id = user.id

    if is_callback:
        await update_or_query.edit_message_text("⏳ Verified! Sending your file...")
    else:
        await update_or_query.message.reply_text("⏳ Verified! Sending your file...")

    if data["type"] == "photo":
        sent = await context.bot.send_photo(chat_id, data["file_id"], caption=data["caption"])
    elif data["type"] == "video":
        sent = await context.bot.send_video(chat_id, data["file_id"], caption=data["caption"])
    elif data["type"] == "audio":
        sent = await context.bot.send_audio(chat_id, data["file_id"], caption=data["caption"])
    else:
        sent = await context.bot.send_document(chat_id, data["file_id"], caption=data["caption"])

    notice = await context.bot.send_message(
        chat_id,
        "⚠️ <b>This file deletes in 5 minutes. Save it now!</b>",
        parse_mode=ParseMode.HTML
    )

    asyncio.create_task(auto_delete(context, chat_id, sent.message_id, notice.message_id))
    log.info(f"File sent to user {user.id} | code={code}")


# ─── Callback: "Try Again" button ─────────────────────────────────────────────
async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, code = query.data.split(":", 1)
    await deliver_file(query, context, query.from_user, code)


# ─── Admin uploads file ───────────────────────────────────────────────────────
async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if update.effective_user.id not in ADMIN_IDS:
        await msg.reply_text("⛔ Only the bot owner can upload files.")
        return

    if not (msg.photo or msg.video or msg.document or msg.audio):
        return

    status = await msg.reply_text("⏳ Uploading & securing...")

    forwarded = await msg.forward(chat_id=CHANNEL_ID)

    if forwarded.photo:
        file_id, ftype = forwarded.photo[-1].file_id, "photo"
    elif forwarded.video:
        file_id, ftype = forwarded.video.file_id, "video"
    elif forwarded.audio:
        file_id, ftype = forwarded.audio.file_id, "audio"
    else:
        file_id, ftype = forwarded.document.file_id, "document"

    code = "".join(random.choices(string.ascii_letters + string.digits, k=8))
    file_db[code] = {"file_id": file_id, "type": ftype, "caption": forwarded.caption}

    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"

    await status.edit_text(
        f"✅ <b>Link Generated!</b>\n\n"
        f"🔗 <b>Share this link:</b>\n{link}\n\n"
        f"⏳ File auto-deletes from user chat after <b>5 minutes</b>.",
        parse_mode=ParseMode.HTML
    )


# ─── Auto delete ──────────────────────────────────────────────────────────────
async def auto_delete(context, chat_id, *message_ids):
    await asyncio.sleep(DELETE_AFTER)
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except:
            pass


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).job_queue(None).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify:"))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.Document.ALL,
        handle_upload
    ))
    print("✅ File Sharing Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
