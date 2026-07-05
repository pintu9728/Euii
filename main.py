import asyncio
import logging
import time
import random
import string
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, OWNER_ID, DEFAULT_SETTINGS
from database import db
from captcha_gen import generate_math_captcha
from toxicity import ToxicityDetector

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

toxicity_detector = ToxicityDetector()

def mention(user) -> str:
    name = user.first_name or "User"
    return f'<a href="tg://user?id={user.id}">{name}</a>'

async def is_admin(update: Update, user_id: int = None) -> bool:
    if not update.effective_chat or update.effective_chat.type == "private":
        return False
    uid = user_id or update.effective_user.id
    if uid == OWNER_ID:
        return True
    try:
        member = await update.effective_chat.get_member(uid)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception:
        return False

async def is_bot_admin(chat) -> bool:
    try:
        bot_member = await chat.get_member((await chat.bot.get_me()).id)
        return bot_member.status == ChatMemberStatus.ADMINISTRATOR and bot_member.can_restrict_members
    except Exception:
        return False

async def log_to_channel(context: ContextTypes.DEFAULT_TYPE, group_id: int, text: str):
    settings = await db.get_group_settings(group_id)
    log_ch = settings.get("log_channel")
    if log_ch:
        try:
            await context.bot.send_message(log_ch, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Log failed: {e}")

async def get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message.reply_to_message:
        return message.reply_to_message.from_user
    if context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            try:
                return await context.bot.get_chat(arg)
            except Exception:
                return None
        else:
            try:
                return await context.bot.get_chat(int(arg))
            except Exception:
                return None
    return None

# ─── Start / Help ───

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    await update.message.reply_text(
        "🛡️ <b>Advanced Community Moderator Bot</b>\n\n"
        "Features: CAPTCHA, AI Toxicity, Federation Bans, Shadow Ban, Evasion Detection, Events, Invites, Karma, Filters, Notes, Locks, Anti-Spam, Scheduling, and more.\n\n"
        "Add me to your group with <b>full admin rights</b> and type /help.",
        parse_mode=ParseMode.HTML,
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>👮 Admin Commands</b>\n"
        "/ban @user [reason] | /unban @user | /kick @user [reason]\n"
        "/mute @user [time] [reason] | /unmute @user\n"
        "/warn @user [reason] | /unwarn @user | /warnings @user\n"
        "/purge [reply] | /pin [reply] | /unpin\n\n"
        "<b>🛡️ Protection</b>\n"
        "/settings | /welcome on/off | /captcha on/off | /captchatype image/button\n"
        "/antispam on/off | /toxicity on/off | /toxicityaction warn/mute/ban/delete\n"
        "/setwarnlimit N | /setflood N | /raidmode on/off | /antiservice on/off\n"
        "/slowmode N | /lock url/forward/sticker/gif/photo/video | /unlock ...\n\n"
        "<b>🚫 Shadow Ban & Evasion</b>\n"
        "/shadowban @user [reason] — Silent federation-wide ban\n"
        "/unshadowban @user — Remove shadow ban\n"
        "/shadowbanlist — View shadow banned users\n"
        "/autoevasion on/off — Auto-ban suspicious alt accounts\n\n"
        "<b>🌐 Federation</b>\n"
        "/fnew <name> | /fjoin <fed_id> | /fleave | /finfo\n"
        "/fban <user_id> [reason] | /funban <user_id> | /fbanlist\n\n"
        "<b>🎉 Events</b>\n"
        "/event create Title | Date | Desc | /events | /event join <id>\n"
        "/event leave <id> | /event info <id> | /event delete <id>\n\n"
        "<b>🔗 Invites</b>\n"
        "/invite | /myinvites | /topinviters\n\n"
        "<b>💾 Filters & Notes</b>\n"
        "/filter <kw> <reply> | /stopfilter <kw> | /filters\n"
        "/save <name> [reply] | /get <name> | /notes | /clear <name>\n\n"
        "<b>⭐ Extras</b>\n"
        "/rules | /setrules <text> | /id | /info [@user]\n"
        "/karma [@user] | reply +1 / -1\n"
        "/schedule HH:MM message | /stats | /report [reply]"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ─── Admin Actions ───

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not await is_bot_admin(update.effective_chat):
        return await update.message.reply_text("❌ I need ban permissions.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /ban @user [reason]")
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"
    try:
        await update.effective_chat.ban_member(target.id)
        await db.log_action(update.effective_chat.id, update.effective_user.id, "ban", target.id, reason)
        await log_to_channel(context, update.effective_chat.id,
            f"🔨 <b>Ban</b>\nUser: {mention(target)}\nBy: {mention(update.effective_user)}\nReason: {reason}")
        await update.message.reply_text(f"🔨 Banned {target.first_name}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /unban @user")
    try:
        await update.effective_chat.unban_member(target.id)
        await db.log_action(update.effective_chat.id, update.effective_user.id, "unban", target.id)
        await update.message.reply_text(f"✅ Unbanned {target.first_name}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not await is_bot_admin(update.effective_chat):
        return await update.message.reply_text("❌ I need ban permissions.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /kick @user [reason]")
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"
    try:
        await update.effective_chat.ban_member(target.id, until_date=datetime.utcnow() + timedelta(seconds=30))
        await db.log_action(update.effective_chat.id, update.effective_user.id, "kick", target.id, reason)
        await update.message.reply_text(f"👢 Kicked {target.first_name}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not await is_bot_admin(update.effective_chat):
        return await update.message.reply_text("❌ I need restrict permissions.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /mute @user [time] [reason]\nTime: 1h, 30m, 1d")
    duration = None
    reason = "No reason"
    if len(context.args) > 1:
        arg = context.args[1]
        if arg.endswith("m"):
            duration = timedelta(minutes=int(arg[:-1]))
        elif arg.endswith("h"):
            duration = timedelta(hours=int(arg[:-1]))
        elif arg.endswith("d"):
            duration = timedelta(days=int(arg[:-1]))
        else:
            reason = " ".join(context.args[1:])
        if duration and len(context.args) > 2:
            reason = " ".join(context.args[2:])
    until = datetime.utcnow() + duration if duration else None
    try:
        perms = {
            "can_send_messages": False,
            "can_send_media_messages": False,
            "can_send_other_messages": False,
            "can_add_web_page_previews": False,
        }
        await update.effective_chat.restrict_member(target.id, until_date=until, **perms)
        await db.log_action(update.effective_chat.id, update.effective_user.id, "mute", target.id, reason)
        time_str = f" for {duration}" if duration else " permanently"
        await update.message.reply_text(f"🔇 Muted {target.first_name}{time_str}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /unmute @user")
    try:
        perms = {
            "can_send_messages": True,
            "can_send_media_messages": True,
            "can_send_other_messages": True,
            "can_add_web_page_previews": True,
        }
        await update.effective_chat.restrict_member(target.id, **perms)
        await update.message.reply_text(f"🔊 Unmuted {target.first_name}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /warn @user [reason]")
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"
    await db.add_warning(update.effective_chat.id, target.id, update.effective_user.id, reason)
    count = await db.get_warnings(update.effective_chat.id, target.id)
    settings = await db.get_group_settings(update.effective_chat.id)
    max_warn = settings.get("max_warnings", 3)
    await db.log_action(update.effective_chat.id, update.effective_user.id, "warn", target.id, reason)
    if count >= max_warn:
        try:
            await update.effective_chat.ban_member(target.id)
            await db.clear_warnings(update.effective_chat.id, target.id)
            await update.message.reply_text(f"🚫 {target.first_name} reached {max_warn} warnings and was banned.")
        except Exception:
            await update.message.reply_text(f"⚠️ Warned {target.first_name} ({count}/{max_warn}).")
    else:
        await update.message.reply_text(f"⚠️ Warned {target.first_name} ({count}/{max_warn}).")

async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /unwarn @user")
    await db.clear_warnings(update.effective_chat.id, target.id)
    await update.message.reply_text(f"✅ Cleared warnings for {target.first_name}.")

async def warnings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target_user(update, context) or update.effective_user
    count = await db.get_warnings(update.effective_chat.id, target.id)
    warns = await db.get_user_warnings_list(update.effective_chat.id, target.id)
    text = f"⚠️ <b>{target.first_name}</b> has {count} warning(s).\n\n"
    for admin_id, reason, date in warns[:5]:
        text += f"• {date}: {reason}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def purge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message to purge from there.")
    start = update.message.reply_to_message.message_id
    end = update.message.message_id
    deleted = 0
    for msg_id in range(start, end + 1):
        try:
            await update.effective_chat.delete_message(msg_id)
            deleted += 1
        except Exception:
            pass
    msg = await update.message.reply_text(f"🗑 Purged {deleted} messages.")
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except Exception:
        pass

async def pin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message to pin.")
    try:
        await update.message.reply_to_message.pin()
        await update.message.reply_text("📌 Pinned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unpin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    try:
        await update.effective_chat.unpin_all_messages()
        await update.message.reply_text("📌 Unpinned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# ─── Shadow Ban & Evasion ───

async def shadowban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not await is_bot_admin(update.effective_chat):
        return await update.message.reply_text("❌ I need ban permissions.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /shadowban @user [reason]")
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"

    await db.add_shadow_ban(target.id, update.effective_user.id, update.effective_chat.id, reason)
    ban_count = 0
    try:
        await update.effective_chat.ban_member(target.id)
        await db.log_action(update.effective_chat.id, update.effective_user.id, "shadowban", target.id, reason)
        ban_count += 1
    except Exception as e:
        return await update.message.reply_text(f"Error in current chat: {e}")

    fed_id = await db.get_group_fed(update.effective_chat.id)
    if fed_id:
        groups = await db.get_fed_groups(fed_id)
        for gid in groups:
            if gid == update.effective_chat.id:
                continue
            try:
                await context.bot.ban_chat_member(gid, target.id)
                ban_count += 1
            except Exception:
                pass

    await update.message.reply_text(
        f"🚫 <b>Shadow Ban Applied</b>\nUser: {mention(target)}\nReason: {reason}\nGroups banned: {ban_count}\n\n"
        f"This user will be <b>silently banned on sight</b> in all linked groups. No alerts will be sent.",
        parse_mode=ParseMode.HTML,
    )

async def unshadowban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    target = await get_target_user(update, context)
    if not target:
        return await update.message.reply_text("Usage: /unshadowban @user")
    await db.remove_shadow_ban(target.id)
    await update.message.reply_text(f"✅ Removed shadow ban for {target.first_name}.")

async def shadowbanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    bans = await db.get_shadow_bans()
    if not bans:
        return await update.message.reply_text("No active shadow bans.")
    text = "🚫 <b>Shadow Ban List</b>\n\n"
    for uid, reason, banned_by, group_id, date in bans[:30]:
        text += f"• <code>{uid}</code> — {reason} ({date})\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def autoevasion_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /autoevasion on/off")
    arg = context.args[0].lower()
    if arg in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "auto_evasion_ban", True)
        return await update.message.reply_text("✅ Auto-evasion ban enabled. New accounts without usernames joining after recent bans will be silently banned.")
    elif arg in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "auto_evasion_ban", False)
        return await update.message.reply_text("✅ Auto-evasion ban disabled.")
    else:
        return await update.message.reply_text("Usage: /autoevasion on/off")

# ─── Welcome & CAPTCHA ───

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.chat_member:
        return
    old_status = update.chat_member.old_chat_member.status
    new_status = update.chat_member.new_chat_member.status
    if new_status != ChatMemberStatus.MEMBER or old_status == ChatMemberStatus.MEMBER:
        return

    chat = update.effective_chat
    user = update.chat_member.new_chat_member.user
    if user.is_bot:
        return

    await db.ensure_group_user(chat.id, user.id, user.username, user.first_name)
    settings = await db.get_group_settings(chat.id)

    # 1. Raid Mode
    if settings.get("raid_mode"):
        try:
            await chat.ban_member(user.id, until_date=datetime.utcnow() + timedelta(hours=1))
            await context.bot.send_message(
                chat.id,
                f"🛡️ <b>Raid Mode Active</b>\n{mention(user)} was banned for 1 hour.",
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception:
            pass

    # 2. Federation Ban
    fed_id = await db.get_group_fed(chat.id)
    if fed_id:
        ban_info = await db.is_fed_banned(fed_id, user.id)
        if ban_info:
            try:
                await chat.ban_member(user.id)
                await context.bot.send_message(
                    chat.id,
                    f"🌐 <b>Federation Ban</b>\n{mention(user)} is banned in this federation.\nReason: {ban_info[0]}",
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception:
                pass

    # 3. SHADOW BAN — Silent
    shadow = await db.is_shadow_banned(user.id)
    if shadow:
        try:
            await chat.ban_member(user.id)
            await db.log_action(chat.id, context.bot.id, "shadowban_trigger", user.id, f"Silent: {shadow[0]}")
        except Exception:
            pass
        return

    # 4. Evasion Detection
    if not user.username and settings.get("auto_evasion_ban"):
        recent_bans = await db.get_recent_bans(chat.id, minutes=10)
        if recent_bans:
            try:
                await chat.ban_member(user.id)
                await db.add_shadow_ban(user.id, context.bot.id, chat.id, "Auto-evasion detection", recent_bans[0][0])
                await db.log_action(chat.id, context.bot.id, "ban", user.id, "Auto-evasion detection")
                await db.log_evasion(recent_bans[0][0], user.id, chat.id, 'medium')
            except Exception:
                pass
            return

    # 5. Invite Tracking
    invite_link = update.chat_member.invite_link
    if invite_link and invite_link.invite_link:
        inv = await db.get_invite_by_link(invite_link.invite_link)
        if inv:
            invite_id, _, _, uses = inv
            await db.increment_invite(invite_id)
            await db.add_invite_use(invite_id, user.id)

    # 6. CAPTCHA / Welcome
    if settings.get("captcha_enabled"):
        captcha_type = settings.get("captcha_type", "image")
        perms = {
            "can_send_messages": False,
            "can_send_media_messages": False,
            "can_send_other_messages": False,
            "can_add_web_page_previews": False,
        }
        try:
            await chat.restrict_member(user.id, **perms)
        except Exception:
            pass

        if captcha_type == "image":
            img_buf, answer = generate_math_captcha()
            msg = await context.bot.send_photo(
                chat.id,
                photo=InputFile(img_buf, filename="captcha.png"),
                caption=f"🛡️ Welcome {mention(user)}! Please solve the CAPTCHA to chat.\nReply with the answer. You have 3 tries.",
                parse_mode=ParseMode.HTML,
            )
            await db.set_captcha(user.id, chat.id, answer, msg.message_id)
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I'm not a robot", callback_data=f"captcha_btn:{user.id}:{chat.id}")]
            ])
            text = settings.get("welcome_text", DEFAULT_SETTINGS["welcome_text"]).format(
                mention=mention(user), group=chat.title, name=user.first_name
            )
            try:
                await context.bot.send_message(chat.id, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        return

    if settings.get("welcome_enabled"):
        text = settings.get("welcome_text", DEFAULT_SETTINGS["welcome_text"]).format(
            mention=mention(user), group=chat.title, name=user.first_name
        )
        try:
            await context.bot.send_message(chat.id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass

async def captcha_btn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split(":")
    if len(data) != 3:
        return
    _, target_id, chat_id = data
    target_id = int(target_id)
    chat_id = int(chat_id)
    if query.from_user.id != target_id:
        return await query.answer("This isn't for you!", show_alert=True)
    await db.set_verified(chat_id, target_id, True)
    perms = {
        "can_send_messages": True,
        "can_send_media_messages": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
    }
    try:
        await context.bot.restrict_chat_member(chat_id, target_id, **perms)
        await query.edit_message_text("✅ Verification complete! You can now chat.")
    except Exception as e:
        logger.error(f"Captcha button error: {e}")

# ─── Anti-Spam & Message Handling ───

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    if not update.message or not update.message.from_user:
        return

    chat = update.effective_chat
    user = update.message.from_user
    settings = await db.get_group_settings(chat.id)

    if settings.get("antiservice_enabled") and (update.message.new_chat_members or update.message.left_chat_member):
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if user.is_bot:
        return

    await db.ensure_group_user(chat.id, user.id, user.username, user.first_name)

    captcha_state = await db.get_captcha(user.id, chat.id)
    if captcha_state:
        answer, captcha_msg_id, tries = captcha_state
        text = update.message.text or ""
        if text.strip() == answer:
            await db.delete_captcha(user.id, chat.id)
            try:
                await chat.delete_message(captcha_msg_id)
                await update.message.delete()
            except Exception:
                pass
            perms = {
                "can_send_messages": True,
                "can_send_media_messages": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True,
            }
            try:
                await chat.restrict_member(user.id, **perms)
            except Exception:
                pass
            await db.set_verified(chat.id, user.id, True)
            if settings.get("welcome_enabled"):
                welcome_text = settings.get("welcome_text", DEFAULT_SETTINGS["welcome_text"]).format(
                    mention=mention(user), group=chat.title, name=user.first_name
                )
                await context.bot.send_message(chat.id, welcome_text, parse_mode=ParseMode.HTML)
        else:
            await db.increment_captcha_tries(user.id, chat.id)
            new_tries = tries + 1
            try:
                await update.message.delete()
            except Exception:
                pass
            if new_tries >= 3:
                await db.delete_captcha(user.id, chat.id)
                try:
                    await chat.delete_message(captcha_msg_id)
                    await chat.ban_member(user.id, until_date=datetime.utcnow() + timedelta(minutes=5))
                    await context.bot.send_message(
                        chat.id,
                        f"🚫 {mention(user)} failed CAPTCHA 3 times and was banned for 5 minutes.",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            else:
                try:
                    await context.bot.send_message(
                        chat.id,
                        f"❌ {mention(user)} Wrong answer. Try again ({new_tries}/3).",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
        return

    if settings.get("captcha_enabled"):
        verified = await db.is_verified(chat.id, user.id)
        if not verified:
            try:
                await update.message.delete()
            except Exception:
                pass
            return

    if settings.get("toxicity_enabled") and update.message.text:
        result = await toxicity_detector.detect(update.message.text)
        if result["toxic"] and result["score"] >= settings.get("toxicity_threshold", 0.8):
            action = settings.get("toxicity_action", "warn")
            await db.log_toxicity(chat.id, user.id, update.message.text, result["score"], action)
            try:
                await update.message.delete()
            except Exception:
                pass
            if action == "warn":
                await db.add_warning(chat.id, user.id, context.bot.id, f"AI Toxicity: {result['score']:.2f}")
                count = await db.get_warnings(chat.id, user.id)
                await context.bot.send_message(
                    chat.id,
                    f"⚠️ {mention(user)} message deleted for toxicity ({result['score']:.2f}). Warning {count}/{settings.get('max_warnings', 3)}.",
                    parse_mode=ParseMode.HTML,
                )
            elif action == "mute":
                perms = {
                    "can_send_messages": False,
                    "can_send_media_messages": False,
                    "can_send_other_messages": False,
                    "can_add_web_page_previews": False,
                }
                await chat.restrict_member(user.id, until_date=datetime.utcnow() + timedelta(hours=1), **perms)
                await context.bot.send_message(
                    chat.id,
                    f"🔇 {mention(user)} muted 1h for toxicity ({result['score']:.2f}).",
                    parse_mode=ParseMode.HTML,
                )
            elif action == "ban":
                await chat.ban_member(user.id)
                await context.bot.send_message(
                    chat.id,
                    f"🔨 {mention(user)} banned for toxicity ({result['score']:.2f}).",
                    parse_mode=ParseMode.HTML,
                )
            elif action == "delete":
                await context.bot.send_message(
                    chat.id,
                    f"🗑 {mention(user)} toxic message deleted ({result['score']:.2f}).",
                    parse_mode=ParseMode.HTML,
                )
            return

    if update.message.text and update.message.reply_to_message:
        text = update.message.text.strip()
        target = update.message.reply_to_message.from_user
        if target.id != user.id and not target.is_bot:
            if text == "+1":
                new_score = await db.update_reputation(chat.id, target.id, 1)
                await update.message.reply_text(f"⭐ {mention(target)} gained karma! (Score: {new_score})", parse_mode=ParseMode.HTML)
                return
            elif text == "-1":
                new_score = await db.update_reputation(chat.id, target.id, -1)
                await update.message.reply_text(f"💩 {mention(target)} lost karma! (Score: {new_score})", parse_mode=ParseMode.HTML)
                return

    if settings.get("antispam_enabled"):
        now = time.time()
        count, first_time = await db.get_flood_count(user.id, chat.id)
        flood_limit = settings.get("flood_limit", 5)
        flood_window = settings.get("flood_window", 5)
        if now - first_time > flood_window:
            await db.reset_flood(user.id, chat.id)
            count = 1
        else:
            await db.add_flood_count(user.id, chat.id, now)
            count += 1
        if count > flood_limit:
            try:
                await update.message.delete()
                if count == flood_limit + 1:
                    perms = {
                        "can_send_messages": False,
                        "can_send_media_messages": False,
                        "can_send_other_messages": False,
                        "can_add_web_page_previews": False,
                    }
                    await chat.restrict_member(user.id, until_date=datetime.utcnow() + timedelta(minutes=5), **perms)
                    await context.bot.send_message(
                        chat.id,
                        f"🚫 {mention(user)} muted 5m for flooding.",
                        parse_mode=ParseMode.HTML,
                    )
            except Exception:
                pass
            return

    if settings.get("lock_url") and update.message.entities:
        for ent in update.message.entities:
            if ent.type in ["url", "text_link", "email"]:
                try:
                    await update.message.delete()
                    await context.bot.send_message(
                        chat.id,
                        f"🔗 {mention(user)}, links are not allowed.",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
                return

    if settings.get("lock_forward") and update.message.forward_date:
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    media_locks = {
        "photo": settings.get("lock_photo"),
        "video": settings.get("lock_video"),
        "sticker": settings.get("lock_sticker"),
        "animation": settings.get("lock_gif"),
    }
    msg_type = None
    if update.message.photo:
        msg_type = "photo"
    elif update.message.video:
        msg_type = "video"
    elif update.message.sticker:
        msg_type = "sticker"
    elif update.message.animation:
        msg_type = "animation"
    if msg_type and media_locks.get(msg_type):
        try:
            await update.message.delete()
        except Exception:
            pass
        return

    if update.message.text:
        text = update.message.text.lower()
        all_filters = await db.get_all_filters(chat.id)
        for keyword in all_filters:
            if keyword in text:
                response = await db.get_filter(chat.id, keyword)
                await update.message.reply_text(response)
                break

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message to report it.")
    admins = await update.effective_chat.get_administrators()
    reporter = update.effective_user
    reported = update.message.reply_to_message.from_user
    chat_id_str = str(update.effective_chat.id)
    if chat_id_str.startswith("-100"):
        chat_id_str = chat_id_str[4:]
    msg_link = f"https://t.me/c/{chat_id_str}/{update.message.reply_to_message.message_id}"
    for admin in admins:
        if not admin.user.is_bot:
            try:
                await context.bot.send_message(
                    admin.user.id,
                    f"🚨 <b>Report</b>\nGroup: {update.effective_chat.title}\n"
                    f"Reported: {mention(reported)}\nBy: {mention(reporter)}\n"
                    f"<a href='{msg_link}'>View Message</a>",
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
    await update.message.reply_text("📨 Report sent to admins.")

# ─── Settings ───

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    settings = await db.get_group_settings(update.effective_chat.id)
    fed_id = await db.get_group_fed(update.effective_chat.id)
    fed_text = f" ({fed_id})" if fed_id else " (None)"
    evasion_stats = await db.get_evasion_stats(update.effective_chat.id)
    text = (
        f"<b>⚙️ Settings for {update.effective_chat.title}</b>\n"
        f"Federation: {fed_text}\n"
        f"Evasion blocked: {evasion_stats}\n\n"
        f"Welcome: {'✅' if settings.get('welcome_enabled') else '❌'}\n"
        f"CAPTCHA: {'✅' if settings.get('captcha_enabled') else '❌'} (Type: {settings.get('captcha_type', 'image')})\n"
        f"Anti-Spam: {'✅' if settings.get('antispam_enabled') else '❌'}\n"
        f"Toxicity: {'✅' if settings.get('toxicity_enabled') else '❌'} (Action: {settings.get('toxicity_action', 'warn')})\n"
        f"Warn Limit: {settings.get('max_warnings')}\n"
        f"Flood Limit: {settings.get('flood_limit')}\n"
        f"Raid Mode: {'✅' if settings.get('raid_mode') else '❌'}\n"
        f"Anti-Service: {'✅' if settings.get('antiservice_enabled') else '❌'}\n"
        f"Auto-Evasion: {'✅' if settings.get('auto_evasion_ban') else '❌'}\n"
        f"Log Channel: {settings.get('log_channel') or 'Not set'}\n"
        f"Lock URL: {'✅' if settings.get('lock_url') else '❌'}\n"
        f"Lock Forward: {'✅' if settings.get('lock_forward') else '❌'}\n"
        f"Lock Photo: {'✅' if settings.get('lock_photo') else '❌'}\n"
        f"Lock Video: {'✅' if settings.get('lock_video') else '❌'}\n"
        f"Lock Sticker: {'✅' if settings.get('lock_sticker') else '❌'}\n"
        f"Lock GIF: {'✅' if settings.get('lock_gif') else '❌'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Usage: /setwelcome <text>\nVariables: {mention}, {group}, {name}")
    await db.set_group_setting(update.effective_chat.id, "welcome_text", text)
    await update.message.reply_text("✅ Welcome message updated.")

async def welcome_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "welcome_enabled", True)
        return await update.message.reply_text("✅ Welcome enabled.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "welcome_enabled", False)
        return await update.message.reply_text("✅ Welcome disabled.")
    else:
        await toggle_cmd(update, context, "welcome_enabled")

async def captcha_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "captcha_enabled", True)
        return await update.message.reply_text("✅ CAPTCHA enabled.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "captcha_enabled", False)
        return await update.message.reply_text("✅ CAPTCHA disabled.")
    else:
        await toggle_cmd(update, context, "captcha_enabled")

async def captcha_type_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args or context.args[0].lower() not in ["image", "button"]:
        return await update.message.reply_text("Usage: /captchatype image/button")
    await db.set_group_setting(update.effective_chat.id, "captcha_type", context.args[0].lower())
    await update.message.reply_text(f"✅ CAPTCHA type set to {context.args[0].lower()}.")

async def antispam_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "antispam_enabled", True)
        return await update.message.reply_text("✅ Anti-spam enabled.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "antispam_enabled", False)
        return await update.message.reply_text("✅ Anti-spam disabled.")
    else:
        await toggle_cmd(update, context, "antispam_enabled")

async def toxicity_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "toxicity_enabled", True)
        return await update.message.reply_text("✅ AI Toxicity detection enabled.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "toxicity_enabled", False)
        return await update.message.reply_text("✅ AI Toxicity detection disabled.")
    else:
        await toggle_cmd(update, context, "toxicity_enabled")

async def toxicity_action_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args or context.args[0].lower() not in ["warn", "mute", "ban", "delete"]:
        return await update.message.reply_text("Usage: /toxicityaction warn/mute/ban/delete")
    await db.set_group_setting(update.effective_chat.id, "toxicity_action", context.args[0].lower())
    await update.message.reply_text(f"✅ Toxicity action set to {context.args[0].lower()}.")

async def setwarnlimit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /setwarnlimit <number>")
    await db.set_group_setting(update.effective_chat.id, "max_warnings", int(context.args[0]))
    await update.message.reply_text(f"✅ Warn limit set to {context.args[0]}.")

async def setflood_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /setflood <number>")
    await db.set_group_setting(update.effective_chat.id, "flood_limit", int(context.args[0]))
    await update.message.reply_text(f"✅ Flood limit set to {context.args[0]}.")

async def logchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /logchannel <channel_id or @channel>")
    ch = context.args[0]
    try:
        chat = await context.bot.get_chat(ch)
        await db.set_group_setting(update.effective_chat.id, "log_channel", chat.id)
        await update.message.reply_text(f"✅ Log channel set to {chat.id}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def raidmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "raid_mode", True)
        return await update.message.reply_text("🚨 Raid mode enabled. All new members will be temporarily banned.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "raid_mode", False)
        return await update.message.reply_text("✅ Raid mode disabled.")
    else:
        await toggle_cmd(update, context, "raid_mode")

async def antiservice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if context.args and context.args[0].lower() in ["on", "yes", "true", "1"]:
        await db.set_group_setting(update.effective_chat.id, "antiservice_enabled", True)
        return await update.message.reply_text("✅ Anti-service enabled. Join/leave messages will be deleted.")
    elif context.args and context.args[0].lower() in ["off", "no", "false", "0"]:
        await db.set_group_setting(update.effective_chat.id, "antiservice_enabled", False)
        return await update.message.reply_text("✅ Anti-service disabled.")
    else:
        await toggle_cmd(update, context, "antiservice_enabled")

async def slowmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("Usage: /slowmode <seconds> (0 to disable)")
    seconds = int(context.args[0])
    try:
        await update.effective_chat.set_slow_mode_delay(seconds)
        await update.message.reply_text(f"✅ Slow mode set to {seconds}s.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /lock url/forward/sticker/gif/photo/video")
    arg = context.args[0].lower()
    mapping = {
        "url": "lock_url",
        "forward": "lock_forward",
        "sticker": "lock_sticker",
        "gif": "lock_gif",
        "photo": "lock_photo",
        "video": "lock_video",
    }
    if arg not in mapping:
        return await update.message.reply_text("Invalid lock type.")
    await db.set_group_setting(update.effective_chat.id, mapping[arg], True)
    await update.message.reply_text(f"🔒 Locked {arg}.")

async def unlock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /unlock url/forward/sticker/gif/photo/video")
    arg = context.args[0].lower()
    mapping = {
        "url": "lock_url",
        "forward": "lock_forward",
        "sticker": "lock_sticker",
        "gif": "lock_gif",
        "photo": "lock_photo",
        "video": "lock_video",
    }
    if arg not in mapping:
        return await update.message.reply_text("Invalid unlock type.")
    await db.set_group_setting(update.effective_chat.id, mapping[arg], False)
    await update.message.reply_text(f"🔓 Unlocked {arg}.")

async def toggle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    settings = await db.get_group_settings(update.effective_chat.id)
    current = settings.get(key, False)
    await db.set_group_setting(update.effective_chat.id, key, not current)
    state = "enabled" if not current else "disabled"
    await update.message.reply_text(f"✅ {key.replace('_', ' ').title()} {state}.")

# ─── Federation ───

async def fnew_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /fnew <name>")
    name = " ".join(context.args)
    fed_id = "fed_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    await db.create_federation(fed_id, update.effective_user.id, name)
    await db.set_group_fed(update.effective_chat.id, fed_id)
    await update.message.reply_text(
        f"🌐 Federation created!\n<b>Name:</b> {name}\n<b>ID:</b> <code>{fed_id}</code>\n\nShare this ID so other groups can join.",
        parse_mode=ParseMode.HTML,
    )

async def fjoin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /fjoin <fed_id>")
    fed_id = context.args[0]
    fed = await db.get_federation(fed_id)
    if not fed:
        return await update.message.reply_text("❌ Federation not found.")
    await db.set_group_fed(update.effective_chat.id, fed_id)
    await update.message.reply_text(f"✅ Joined federation: {fed[2]}")

async def fleave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    await db.set_group_fed(update.effective_chat.id, None)
    await update.message.reply_text("✅ Left federation.")

async def finfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    fed_id = await db.get_group_fed(update.effective_chat.id)
    if not fed_id:
        return await update.message.reply_text("This group is not in any federation.")
    fed = await db.get_federation(fed_id)
    if not fed:
        return await update.message.reply_text("Federation data missing.")
    groups = await db.get_fed_groups(fed_id)
    bans = await db.get_fed_bans(fed_id)
    text = (
        f"<b>🌐 Federation Info</b>\n\n"
        f"<b>ID:</b> <code>{fed_id}</code>\n"
        f"<b>Name:</b> {fed[2]}\n"
        f"<b>Owner:</b> {fed[1]}\n"
        f"<b>Groups:</b> {len(groups)}\n"
        f"<b>Banned Users:</b> {len(bans)}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def fban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    fed_id = await db.get_group_fed(update.effective_chat.id)
    if not fed_id:
        return await update.message.reply_text("This group is not in a federation.")
    if not context.args:
        return await update.message.reply_text("Usage: /fban <user_id> [reason]")
    try:
        user_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("User ID must be a number.")
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"
    await db.fban(fed_id, user_id, reason, update.effective_user.id, update.effective_chat.id)
    groups = await db.get_fed_groups(fed_id)
    banned_count = 0
    for gid in groups:
        try:
            await context.bot.ban_chat_member(gid, user_id)
            banned_count += 1
        except Exception:
            pass
    await update.message.reply_text(
        f"🌐 <b>Federation Ban</b>\nUser ID: <code>{user_id}</code>\nReason: {reason}\nBanned in {banned_count} groups.",
        parse_mode=ParseMode.HTML,
    )

async def funban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    fed_id = await db.get_group_fed(update.effective_chat.id)
    if not fed_id:
        return await update.message.reply_text("This group is not in a federation.")
    if not context.args:
        return await update.message.reply_text("Usage: /funban <user_id>")
    try:
        user_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("User ID must be a number.")
    await db.funban(fed_id, user_id)
    groups = await db.get_fed_groups(fed_id)
    unbanned_count = 0
    for gid in groups:
        try:
            await context.bot.unban_chat_member(gid, user_id)
            unbanned_count += 1
        except Exception:
            pass
    await update.message.reply_text(
        f"✅ <b>Federation Unban</b>\nUser ID: <code>{user_id}</code>\nUnbanned in {unbanned_count} groups.",
        parse_mode=ParseMode.HTML,
    )

async def fbanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    fed_id = await db.get_group_fed(update.effective_chat.id)
    if not fed_id:
        return await update.message.reply_text("This group is not in a federation.")
    bans = await db.get_fed_bans(fed_id)
    if not bans:
        return await update.message.reply_text("No federation bans.")
    text = "<b>🌐 Federation Ban List</b>\n\n"
    for uid, reason in bans[:20]:
        text += f"• <code>{uid}</code>: {reason}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ─── Events ───

async def event_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await event_list_cmd(update, context)
    sub = context.args[0].lower()
    if sub == "create":
        return await event_create_cmd(update, context)
    elif sub == "list":
        return await event_list_cmd(update, context)
    elif sub == "join":
        return await event_join_cmd(update, context)
    elif sub == "leave":
        return await event_leave_cmd(update, context)
    elif sub == "info":
        return await event_info_cmd(update, context)
    elif sub == "delete":
        return await event_delete_cmd(update, context)
    else:
        await update.message.reply_text("Unknown subcommand. Use: create, list, join, leave, info, delete")

async def event_create_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    rest = " ".join(context.args[1:])
    parts = [p.strip() for p in rest.split("|")]
    if len(parts) < 3:
        return await update.message.reply_text(
            "Usage: /event create Title | YYYY-MM-DD HH:MM | Description | MaxParticipants\n"
            "Example: /event create Game Night | 2026-07-10 20:00 | Fun and games | 20"
        )
    title = parts[0]
    date_str = parts[1]
    description = parts[2]
    max_p = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    try:
        datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return await update.message.reply_text("Date format: YYYY-MM-DD HH:MM")
    event_id = await db.create_event(update.effective_chat.id, update.effective_user.id, title, description, date_str, max_p)
    await update.message.reply_text(
        f"🎉 <b>Event Created!</b>\n\n<b>ID:</b> {event_id}\n<b>Title:</b> {title}\n<b>Date:</b> {date_str}\n<b>Desc:</b> {description}\n\nUse /event join {event_id}",
        parse_mode=ParseMode.HTML,
    )

async def event_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = await db.get_group_events(update.effective_chat.id)
    if not events:
        return await update.message.reply_text("No events scheduled.")
    text = "🎉 <b>Upcoming Events</b>\n\n"
    for eid, title, date in events:
        text += f"• <b>{title}</b> (ID: {eid}) — {date}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def event_join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /event join <id>")
    try:
        event_id = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("Event ID must be a number.")
    event = await db.get_event(event_id)
    if not event or event[1] != update.effective_chat.id:
        return await update.message.reply_text("Event not found.")
    await db.rsvp_event(event_id, update.effective_user.id)
    rsvps = await db.get_event_rsvps(event_id)
    await update.message.reply_text(
        f"✅ You're going to <b>{event[3]}</b>!\nCurrent attendees: {len(rsvps)}",
        parse_mode=ParseMode.HTML,
    )

async def event_leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /event leave <id>")
    try:
        event_id = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("Event ID must be a number.")
    await db.unrsvp_event(event_id, update.effective_user.id)
    await update.message.reply_text("✅ You left the event.")

async def event_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /event info <id>")
    try:
        event_id = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("Event ID must be a number.")
    event = await db.get_event(event_id)
    if not event or event[1] != update.effective_chat.id:
        return await update.message.reply_text("Event not found.")
    rsvps = await db.get_event_rsvps(event_id)
    text = (
        f"<b>🎉 {event[3]}</b>\n\n"
        f"<b>Date:</b> {event[5]}\n"
        f"<b>Description:</b> {event[4]}\n"
        f"<b>Attendees:</b> {len(rsvps)}\n"
        f"<b>Max:</b> {event[6] or 'Unlimited'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def event_delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /event delete <id>")
    try:
        event_id = int(context.args[1])
    except ValueError:
        return await update.message.reply_text("Event ID must be a number.")
    event = await db.get_event(event_id)
    if not event or event[1] != update.effective_chat.id:
        return await update.message.reply_text("Event not found.")
    await db.delete_event(event_id)
    await update.message.reply_text("🗑 Event deleted.")

# ─── Invites ───

async def invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return await update.message.reply_text("Use this in a group.")
    user = update.effective_user
    name = f"user_{user.id}"
    existing = await db.get_invite_by_name(update.effective_chat.id, name)
    if existing:
        return await update.message.reply_text(
            f"Your invite link: {existing[1]}\nUses: {existing[2]}"
        )
    try:
        link = await context.bot.create_chat_invite_link(
            update.effective_chat.id,
            name=name,
            member_limit=0,
        )
        await db.create_invite(update.effective_chat.id, user.id, link.invite_link, name)
        await update.message.reply_text(
            f"🔗 <b>Your Personal Invite Link</b>\n{link.invite_link}\n\nTrack who joins using your link with /myinvites",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def myinvites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        return await update.message.reply_text("Use this in a group.")
    invites = await db.get_user_invites(update.effective_chat.id, update.effective_user.id)
    if not invites:
        return await update.message.reply_text("You have no invite links. Use /invite to create one.")
    text = "🔗 <b>Your Invites</b>\n\n"
    for name, link, uses in invites:
        text += f"• {link}\n  Uses: {uses}\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def topinviters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    top = await db.get_top_inviters(update.effective_chat.id)
    if not top:
        return await update.message.reply_text("No invite data yet.")
    text = "🏆 <b>Top Inviters</b>\n\n"
    for i, (uid, total) in enumerate(top, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name
        except Exception:
            name = f"User {uid}"
        text += f"{i}. {name} — {total} invites\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# ─── Filters & Notes ───

async def filter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /filter <keyword> <response>")
    keyword = context.args[0]
    response = " ".join(context.args[1:])
    await db.add_filter(update.effective_chat.id, keyword, response)
    await update.message.reply_text(f"✅ Filter added: {keyword}")

async def stopfilter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /stopfilter <keyword>")
    await db.remove_filter(update.effective_chat.id, context.args[0])
    await update.message.reply_text(f"✅ Filter removed.")

async def filters_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filters_list = await db.get_all_filters(update.effective_chat.id)
    if not filters_list:
        return await update.message.reply_text("No filters set.")
    text = "📋 <b>Filters:</b>\n" + "\n".join(f"• {f}" for f in filters_list)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def save_note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /save <name> [reply to media]")
    name = context.args[0].lower()
    content = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    file_id = None
    file_type = None
    if update.message.reply_to_message:
        msg = update.message.reply_to_message
        if msg.photo:
            file_id = msg.photo[-1].file_id
            file_type = "photo"
        elif msg.video:
            file_id = msg.video.file_id
            file_type = "video"
        elif msg.document:
            file_id = msg.document.file_id
            file_type = "document"
        elif msg.animation:
            file_id = msg.animation.file_id
            file_type = "animation"
        elif msg.text:
            content = msg.text
    if not content and not file_id:
        return await update.message.reply_text("No content to save.")
    await db.save_note(update.effective_chat.id, name, content, file_id, file_type)
    await update.message.reply_text(f"✅ Note saved: #{name}")

async def get_note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    name = context.args[0].lower()
    note = await db.get_note(update.effective_chat.id, name)
    if not note:
        return
    content, file_id, file_type = note
    kwargs = {"caption": content or None, "parse_mode": ParseMode.HTML}
    if file_type == "photo":
        await update.message.reply_photo(file_id, **kwargs)
    elif file_type == "video":
        await update.message.reply_video(file_id, **kwargs)
    elif file_type == "document":
        await update.message.reply_document(file_id, **kwargs)
    elif file_type == "animation":
        await update.message.reply_animation(file_id, **kwargs)
    else:
        await update.message.reply_text(content, parse_mode=ParseMode.HTML)

async def notes_list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = await db.get_all_notes(update.effective_chat.id)
    if not notes:
        return await update.message.reply_text("No notes saved.")
    text = "📝 <b>Notes:</b>\n" + "\n".join(f"• #{n}" for n in notes)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def clear_note_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if not context.args:
        return await update.message.reply_text("Usage: /clear <name>")
    await db.delete_note(update.effective_chat.id, context.args[0])
    await update.message.reply_text("✅ Note deleted.")

# ─── Rules & Info ───

async def setrules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Usage: /setrules <text>")
    await db.set_rules(update.effective_chat.id, text)
    await update.message.reply_text("✅ Rules updated.")

async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = await db.get_rules(update.effective_chat.id)
    if not rules:
        return await update.message.reply_text("No rules set. Admins can set them with /setrules")
    await update.message.reply_text(f"📜 <b>Group Rules</b>\n\n{rules}", parse_mode=ParseMode.HTML)

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    text = f"👤 <b>Your ID:</b> <code>{user.id}</code>\n"
    if chat and chat.type != "private":
        text += f"💬 <b>Chat ID:</b> <code>{chat.id}</code>\n"
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        text += f"🎯 <b>Replied User ID:</b> <code>{target.id}</code>\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target_user(update, context) or update.effective_user
    if not target:
        return await update.message.reply_text("Usage: /info @user")
    karma = await db.get_reputation(update.effective_chat.id, target.id) if update.effective_chat.type != "private" else 0
    warns = await db.get_warnings(update.effective_chat.id, target.id) if update.effective_chat.type != "private" else 0
    shadow = await db.is_shadow_banned(target.id)
    text = (
        f"👤 <b>User Info</b>\n\n"
        f"Name: {target.first_name}\n"
        f"ID: <code>{target.id}</code>\n"
        f"Username: @{target.username or 'N/A'}\n"
    )
    if update.effective_chat.type != "private":
        text += f"Karma: {karma}\nWarnings: {warns}\n"
    if shadow:
        text += f"🚫 <b>Shadow Banned:</b> Yes\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def karma_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await get_target_user(update, context) or update.effective_user
    score = await db.get_reputation(update.effective_chat.id, target.id)
    await update.message.reply_text(f"⭐ {mention(target)} has {score} karma.", parse_mode=ParseMode.HTML)

async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return await update.message.reply_text("❌ Admin only.")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /schedule HH:MM Your message here")
    time_str = context.args[0]
    content = " ".join(context.args[1:])
    try:
        hour, minute = map(int, time_str.split(":"))
        now = datetime.utcnow()
        send_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if send_at < now:
            send_at += timedelta(days=1)
        send_at_str = send_at.strftime("%Y-%m-%d %H:%M:%S")
        await db.schedule_message(update.effective_chat.id, update.effective_user.id, content, send_at_str)
        await update.message.reply_text(f"✅ Message scheduled for {time_str} UTC.")
    except Exception as e:
        await update.message.reply_text(f"Invalid time format. Use HH:MM\nError: {e}")

async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    pending = await db.get_pending_scheduled()
    for msg_id, group_id, content in pending:
        try:
            await context.bot.send_message(group_id, content, parse_mode=ParseMode.HTML)
            await db.mark_scheduled_sent(msg_id)
        except Exception as e:
            logger.error(f"Scheduled message failed: {e}")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type == "private":
        return
    members, warns, actions = await db.get_stats(update.effective_chat.id)
    evasion_count = await db.get_evasion_stats(update.effective_chat.id)
    await update.message.reply_text(
        f"📊 <b>Stats for {update.effective_chat.title}</b>\n\n"
        f"👥 Members tracked: {members}\n"
        f"⚠️ Total warnings: {warns}\n"
        f"🔨 Admin actions: {actions}\n"
        f"🚫 Evasion attempts blocked: {evasion_count}",
        parse_mode=ParseMode.HTML,
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ─── Main ───

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Core
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("kick", kick_cmd))
    application.add_handler(CommandHandler("mute", mute_cmd))
    application.add_handler(CommandHandler("unmute", unmute_cmd))
    application.add_handler(CommandHandler("warn", warn_cmd))
    application.add_handler(CommandHandler("unwarn", unwarn_cmd))
    application.add_handler(CommandHandler("warnings", warnings_cmd))
    application.add_handler(CommandHandler("purge", purge_cmd))
    application.add_handler(CommandHandler("pin", pin_cmd))
    application.add_handler(CommandHandler("unpin", unpin_cmd))

    # Shadow Ban
    application.add_handler(CommandHandler("shadowban", shadowban_cmd))
    application.add_handler(CommandHandler("unshadowban", unshadowban_cmd))
    application.add_handler(CommandHandler("shadowbanlist", shadowbanlist_cmd))
    application.add_handler(CommandHandler("autoevasion", autoevasion_cmd))

    # Settings
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    application.add_handler(CommandHandler("welcome", welcome_toggle))
    application.add_handler(CommandHandler("captcha", captcha_toggle))
    application.add_handler(CommandHandler("captchatype", captcha_type_cmd))
    application.add_handler(CommandHandler("antispam", antispam_toggle))
    application.add_handler(CommandHandler("toxicity", toxicity_toggle))
    application.add_handler(CommandHandler("toxicityaction", toxicity_action_cmd))
    application.add_handler(CommandHandler("setwarnlimit", setwarnlimit_cmd))
    application.add_handler(CommandHandler("setflood", setflood_cmd))
    application.add_handler(CommandHandler("logchannel", logchannel_cmd))
    application.add_handler(CommandHandler("raidmode", raidmode_cmd))
    application.add_handler(CommandHandler("antiservice", antiservice_cmd))
    application.add_handler(CommandHandler("slowmode", slowmode_cmd))
    application.add_handler(CommandHandler("lock", lock_cmd))
    application.add_handler(CommandHandler("unlock", unlock_cmd))

    # Federation
    application.add_handler(CommandHandler("fnew", fnew_cmd))
    application.add_handler(CommandHandler("fjoin", fjoin_cmd))
    application.add_handler(CommandHandler("fleave", fleave_cmd))
    application.add_handler(CommandHandler("finfo", finfo_cmd))
    application.add_handler(CommandHandler("fban", fban_cmd))
    application.add_handler(CommandHandler("funban", funban_cmd))
    application.add_handler(CommandHandler("fbanlist", fbanlist_cmd))

    # Events
    application.add_handler(CommandHandler("event", event_cmd))

    # Invites
    application.add_handler(CommandHandler("invite", invite_cmd))
    application.add_handler(CommandHandler("myinvites", myinvites_cmd))
    application.add_handler(CommandHandler("topinviters", topinviters_cmd))

    # Filters & Notes
    application.add_handler(CommandHandler("filter", filter_cmd))
    application.add_handler(CommandHandler("stopfilter", stopfilter_cmd))
    application.add_handler(CommandHandler("filters", filters_list_cmd))
    application.add_handler(CommandHandler("save", save_note_cmd))
    application.add_handler(CommandHandler("get", get_note_cmd))
    application.add_handler(CommandHandler("notes", notes_list_cmd))
    application.add_handler(CommandHandler("clear", clear_note_cmd))

    # Extras
    application.add_handler(CommandHandler("setrules", setrules_cmd))
    application.add_handler(CommandHandler("rules", rules_cmd))
    application.add_handler(CommandHandler("id", id_cmd))
    application.add_handler(CommandHandler("info", info_cmd))
    application.add_handler(CommandHandler("karma", karma_cmd))
    application.add_handler(CommandHandler("schedule", schedule_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("report", report_cmd))

    # Callbacks & Handlers
    application.add_handler(CallbackQueryHandler(captcha_btn_callback, pattern=r"^captcha_btn:"))
    application.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, message_handler))
    application.add_error_handler(error_handler)

    # Init DB
    asyncio.get_event_loop().run_until_complete(db.connect())

    # Scheduled messages
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_job, interval=30, first=10)

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
