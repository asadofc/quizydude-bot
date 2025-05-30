import os
import logging
import random
import psycopg2
import asyncio
import copy
from telegram import Update, Poll, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
)
''')
conn.commit()

# Helper for async-safe connections (for threading)
def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# --- QUIZ QUESTIONS SETUP ---
quizzes = {
    'xquiz': [
        ("What's the most sensitive erogenous zone? 🔥", ["Neck", "Fingers", "Toes", "Elbows"], 0),
        ("Which sense is strongest during intimacy? 👃", ["Sight", "Touch", "Smell", "Taste"], 2),
    ],
    'hquiz': [
        ("What hormone spikes during orgasm? ⚡", ["Adrenaline", "Oxytocin", "Cortisol", "Dopamine"], 1),
        ("Which body part is nicknamed 'love button'? ❤️", ["Neck", "G-spot", "Clitoris", "Lips"], 2),
    ],
    'fquiz': [
        ("Best body language sign of flirting? 😉", ["Crossed arms", "Eye contact", "Yawning", "Looking away"], 1),
        ("Best compliment starter? ✨", ["You look smart", "You're breathtaking", "Nice shoes", "Cool vibe"], 1),
    ],
    'lolquiz': [
        ("What gets wetter the more it dries? 🧻", ["Sponge", "Towel", "Rain", "Soap"], 1),
        ("Why don't skeletons fight? ☠️", ["Lazy", "No guts", "Cowards", "Busy"], 1),
    ],
    'cquiz': [
        ("Can pigs actually fly? ✈️", ["Only in dreams", "Yes", "No", "Maybe"], 2),
        ("What color is a mirror? 🪞", ["Silver", "Clear", "Invisible", "Depends"], 0),
    ],
    'squiz': [
        ("What planet is known as the Red Planet? 🔴", ["Earth", "Mars", "Jupiter", "Venus"], 1),
        ("How many legs does a spider have? 🕷️", ["6", "8", "10", "12"], 1),
    ],
}

# Merge all into aquiz
all_questions = []
for lst in quizzes.values():
    all_questions.extend(lst)
quizzes['aquiz'] = all_questions

# --- SHUFFLED QUIZZES SETUP ---
shuffled_quizzes = {}
def reset_shuffled(quiz_type):
    shuffled_quizzes[quiz_type] = copy.deepcopy(quizzes[quiz_type])
    random.shuffle(shuffled_quizzes[quiz_type])
for quiz_type in quizzes:
    reset_shuffled(quiz_type)

# --- USER MANAGEMENT ---
def ensure_user_sync(user_id, username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    result = cursor.fetchone()
    if not result:
        cursor.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
    conn.commit()
    cursor.close()
    conn.close()

async def ensure_user(user_id, username):
    await asyncio.to_thread(ensure_user_sync, user_id, username)

def update_score(user_id: int, correct: bool):
    if correct:
        cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id=%s", (user_id,))
    else:
        cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id=%s", (user_id,))
    conn.commit()

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await ensure_user(user.id, user.username or user.first_name)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Updates", url="https://t.me/WorkGlows"),
         InlineKeyboardButton("Support", url="https://t.me/TheCryptoElders")],
        [InlineKeyboardButton("Add Me To Your Group", url="https://t.me/quizydudebot?startgroup=true")]
    ])

    msg = (
        f"👋 Hey {user.mention_html()}!\n\n"
        "✨ Welcome to the Ultimate Quiz Challenge Bot! ✨\n\n"
        "Here, you can test your knowledge, have fun, flirt a little, or even go crazy with different types of quizzes!\n\n"
        "🎯 Categories you can explore:\n"
        " - 🔥 /xquiz — Steamy Sex Quiz\n"
        " - ❤️ /hquiz — Horny Quiz\n"
        " - 💋 /fquiz — Flirty Quiz\n"
        " - 😂 /lolquiz — Funny Quiz\n"
        " - 🤪 /cquiz — Crazy Quiz\n"
        " - 📚 /squiz — Study Quiz\n"
        " - 🎲 /aquiz — Random Mix\n\n"
        "🏆 Correct answers will boost your rank on the leaderboard!\n"
        "❌ Wrong answers? No worries, practice makes perfect!\n\n"
        "⭐ Start now, challenge your friends, and become the Quiz Master!\n\n"
        "👉 Use /help if you need guidance.\n\n"
        "🎉 LET'S PLAY & HAVE FUN!"
    )
    await update.message.reply_html(msg, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
<b>📚 Quiz Bot Help</b>

Get ready to test your knowledge with these fun quizzes! 🎉

📝 <b>Quiz Categories:</b>
- /xquiz <i>Sex Quiz</i> 🔥
- /hquiz <i>Horny Quiz</i> 😏
- /fquiz <i>Flirty Quiz</i> 💋
- /lolquiz <i>Funny Quiz</i> 😂
- /cquiz <i>Crazy Quiz</i> 🤪
- /squiz <i>Study Quiz</i> 📚
- /aquiz <i>Random Mixed Quiz</i> 🎲

🏆 <b>Leaderboard:</b>
- /statistics See the current leaderboard 📊

💡 <b>Tip:</b> Answer polls correctly to climb the leaderboard! 🚀
"""
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await update.message.reply_html(help_text)

async def send_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, quiz_type: str):
    if quiz_type not in quizzes:
        return
    if not shuffled_quizzes.get(quiz_type):
        reset_shuffled(quiz_type)
    if not shuffled_quizzes[quiz_type]:
        await update.message.reply_text("No more questions in this category!")
        return

    question = shuffled_quizzes[quiz_type].pop()
    q_text, options, correct_id = question

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    msg = await context.bot.send_poll(
    chat_id=update.effective_chat.id,
    question=q_text,
    options=options,
    type=Poll.QUIZ,
    correct_option_id=correct_id,
    is_anonymous=False,
    allows_multiple_answers=False,
    open_period=60  # ⏱️ Add this line for 60 seconds timer
)
    payload = {
        msg.poll.id: {
            "correct_option_id": correct_id,
            "message_id": msg.message_id,
            "chat_id": update.effective_chat.id,
        }
    }
    context.bot_data.update(payload)

# --- Quiz Commands ---
async def xquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'xquiz')
async def hquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'hquiz')
async def fquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'fquiz')
async def lolquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'lolquiz')
async def cquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'cquiz')
async def squiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'squiz')
async def aquiz(update: Update, context: ContextTypes.DEFAULT_TYPE): await send_quiz(update, context, 'aquiz')

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user.id
    selected = answer.option_ids[0]
    poll_id = answer.poll_id
    correct_option_id = context.bot_data.get(poll_id, {}).get("correct_option_id")
    await ensure_user(user_id, answer.user.username or answer.user.first_name)
    update_score(user_id, correct=(selected == correct_option_id))

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    cursor.execute("SELECT * FROM users ORDER BY wins DESC, losses ASC LIMIT 10")
    top_users = cursor.fetchall()
    
    if not top_users:
        msg = await update.message.reply_text("No players yet!")
        await asyncio.sleep(60)
        await msg.delete()
        return

    text = "<b>🏆 Quiz Global Leaderboard 🏆</b>\n\n"
    for i, (uid, username, wins, losses) in enumerate(top_users, start=1):
        try:
            user = await context.bot.get_chat(uid)
            mention = f"{user.mention_html()}"
        except Exception:
            mention = f"<i>{username or 'Unknown'}</i>"
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"
        text += f"{icon} {mention} — W: {wins} & L: {losses}\n"

    msg = await update.message.reply_html(text)
    await asyncio.sleep(60)
    await msg.delete()

# --- MAIN ---
def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("xquiz", xquiz))
    app.add_handler(CommandHandler("hquiz", hquiz))
    app.add_handler(CommandHandler("fquiz", fquiz))
    app.add_handler(CommandHandler("lolquiz", lolquiz))
    app.add_handler(CommandHandler("cquiz", cquiz))
    app.add_handler(CommandHandler("squiz", squiz))
    app.add_handler(CommandHandler("aquiz", aquiz))
    app.add_handler(CommandHandler("statistics", show_statistics))
    app.add_handler(PollAnswerHandler(receive_poll_answer))

    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "How to use the bot"),
        BotCommand("xquiz", "Sex Quiz"),
        BotCommand("hquiz", "Horny Quiz"),
        BotCommand("fquiz", "Flirty Quiz"),
        BotCommand("lolquiz", "Funny Quiz"),
        BotCommand("cquiz", "Crazy Quiz"),
        BotCommand("squiz", "Study Quiz"),
        BotCommand("aquiz", "All Random Quiz"),
        BotCommand("statistics", "Show leaderboard"),
    ]
    async def set_commands(application): await application.bot.set_my_commands(commands)
    app.post_init = set_commands

    app.run_polling()

if __name__ == '__main__':
    main()