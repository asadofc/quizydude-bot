import os
import logging
import random
import copy
import asyncio
import signal
import sys
from typing import Dict, List, Tuple, Optional, Any

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from aiogram.enums import PollType, ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# ─── Imports for Dummy HTTP Server ──────────────────────────────────────────
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ----------------------------
# Logging configuration
# ----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("quiz_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# ----------------------------
# Configuration
# ----------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "quiz.db")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "60"))
LEADERBOARD_SIZE = int(os.getenv("LEADERBOARD_SIZE", "10"))
MESSAGE_DELETE_DELAY = int(os.getenv("MESSAGE_DELETE_DELAY", "60"))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is required!")
    sys.exit(1)

# ----------------------------
# Global variables
# ----------------------------
db: Optional[aiosqlite.Connection] = None
bot: Optional[Bot] = None
dp = Dispatcher()

# ----------------------------
# Database setup and management
# ----------------------------
async def init_db() -> None:
    """Initialize database connection and create tables if they don't exist."""
    global db
    try:
        db = await aiosqlite.connect(DATABASE_PATH)
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   INTEGER PRIMARY KEY,
                username  TEXT,
                first_name TEXT,
                last_name TEXT,
                wins      INTEGER DEFAULT 0,
                losses    INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id TEXT UNIQUE,
                correct_option_id INTEGER,
                message_id INTEGER,
                chat_id INTEGER,
                quiz_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

async def close_db() -> None:
    """Close the database connection."""
    global db
    if db:
        try:
            await db.close()
            logger.info("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {e}")

async def ensure_user(user_id: int, username: Optional[str] = None, 
                     first_name: Optional[str] = None, last_name: Optional[str] = None) -> None:
    """Insert or update user information."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        await db.execute(
            """INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, wins, losses, created_at, updated_at) 
               VALUES (?, ?, ?, ?, 
                       COALESCE((SELECT wins FROM users WHERE user_id = ?), 0),
                       COALESCE((SELECT losses FROM users WHERE user_id = ?), 0),
                       COALESCE((SELECT created_at FROM users WHERE user_id = ?), CURRENT_TIMESTAMP),
                       CURRENT_TIMESTAMP)""",
            (user_id, username, first_name, last_name, user_id, user_id, user_id)
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Error ensuring user {user_id}: {e}")
        raise

async def update_score(user_id: int, correct: bool) -> None:
    """Update user's score (wins/losses)."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        column = "wins" if correct else "losses"
        await db.execute(
            f"UPDATE users SET {column} = {column} + 1, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()
        logger.info(f"Updated score for user {user_id}: {'win' if correct else 'loss'}")
    except Exception as e:
        logger.error(f"Error updating score for user {user_id}: {e}")
        raise

async def store_poll_session(poll_id: str, correct_option_id: int, message_id: int, 
                           chat_id: int, quiz_type: str) -> None:
    """Store poll session data."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        await db.execute(
            """INSERT OR REPLACE INTO quiz_sessions 
               (poll_id, correct_option_id, message_id, chat_id, quiz_type) 
               VALUES (?, ?, ?, ?, ?)""",
            (poll_id, correct_option_id, message_id, chat_id, quiz_type)
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Error storing poll session {poll_id}: {e}")
        raise

async def get_poll_session(poll_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve poll session data."""
    if not db:
        raise RuntimeError("Database not initialized")
    
    try:
        cursor = await db.execute(
            """SELECT correct_option_id, message_id, chat_id, quiz_type 
               FROM quiz_sessions WHERE poll_id = ?""",
            (poll_id,)
        )
        row = await cursor.fetchone()
        if row:
            return {
                "correct_option_id": row[0],
                "message_id": row[1],
                "chat_id": row[2],
                "quiz_type": row[3]
            }
        return None
    except Exception as e:
        logger.error(f"Error retrieving poll session {poll_id}: {e}")
        return None

# ----------------------------
# Quiz data and management
# ----------------------------
QUIZ_DATA: Dict[str, List[Tuple[str, List[str], int]]] = {
    'xquiz': [
    ("Which hormone is primarily responsible for sexual desire? ❤️‍🔥", ["Estrogen", "Testosterone", "Progesterone", "Oxytocin"], 1),
    ("What’s the average duration of foreplay recommended for optimal arousal? ⏳", ["2–3 minutes", "5–10 minutes", "15–20 minutes", "30+ minutes"], 1),
    ("Which structure produces sperm in males? 🥚", ["Prostate", "Testes", "Epididymis", "Vas deferens"], 1),
    ("What’s the primary function of the clitoris? 🌟", ["Urination", "Reproduction", "Pleasure", "Lubrication"], 2),
    ("Which lubricant base is safest for use with silicone toys? 💧", ["Silicone-based", "Oil-based", "Water-based", "Aloe-based"], 2),
    ("What’s the typical pH of a healthy vaginal environment? 🔬", ["2.0–3.0", "3.5–4.5", "5.5–6.5", "7.0–8.0"], 1),
    ("Which contraceptive also helps regulate menstrual cycles? 🩸", ["Condom", "IUD", "Birth control pill", "Spermicide"], 2),
    ("What’s the most common STI worldwide? 🌍", ["HIV", "Syphilis", "Chlamydia", "Gonorrhea"], 2),
    ("Which position reduces pressure on the cervix? 🔄", ["Missionary", "Cowgirl", "Spooning", "Standing"], 2),
    ("What does BDSM stand for? ⛓️", ["Bondage, Discipline, Sadism, Masochism", "Bondage, Dominance, Submission, Masochism", "Bondage, Discipline, Submission, Masochism", "Bonding, Domination, Sadism, Masochism"], 0),
    ("Which sensory play involves temperature variation? ❄️🔥", ["Edible play", "Sensory deprivation", "Temperature play", "Role play"], 2),
    ("What’s a common sign of arousal in females? 🌸", ["Breast swelling", "Hair growth", "Toenail thickening", "Weight gain"], 0),
    ("Which vitamin deficiency can lower libido? 🍊", ["Vitamin D", "Vitamin C", "Vitamin B12", "Vitamin K"], 0),
    ("What’s the term for fear of sexual intimacy? 🚫", ["Aphobia", "Genophobia", "Erophobia", "Thanatophobia"], 2),
    ("Which nerve is key for clitoral sensation? 🧠", ["Sciatic", "Vagus", "Pudendal", "Median"], 2),
    ("What’s the safest way to clean a latex condom? 🧼", ["Dish soap", "Hand sanitizer", "Warm water only", "Vinegar rinse"], 2),
    ("Which oil is commonly used for erotic massage? 🌿", ["Coconut oil", "Mineral oil", "Olive oil", "Motor oil"], 0),
    ("What’s the typical length of the average erect penis? 📏", ["8–10 cm", "10–12 cm", "13–15 cm", "16–18 cm"], 2),
    ("Which toy is best for prostate stimulation? 🍑", ["Bullet vibrator", "Prostate massager", "Ben Wa balls", "Cock ring"], 1),
    ("What’s the term for simultaneous orgasm? 💥", ["Dual climax", "Mutual release", "Synchronized orgasm", "Couples’ high"], 2),
    ("Which practice involves refraining from orgasm? ✋", ["Tantric sex", "Karezza", "Sensate focus", "Erotic asphyxiation"], 1),
    ("What’s a common trigger for sexual arousal? 🌶️", ["Bright light", "Certain scents", "High noise", "Cool temperatures"], 1),
    ("Which fluid is produced by the Bartholin’s glands? 💧", ["Semen", "Pre-ejaculate", "Vaginal lubrication", "Sweat"], 2),
    ("What’s the most effective emergency contraception? ⏰", ["Yuzpe method", "Levonorgestrel pill", "Copper IUD", "Condom"], 2),
    ("Which area is known as the “G-spot”? 📍", ["Anterior vaginal wall", "Posterior vaginal wall", "Labia minora", "Perineum"], 0),
    ("What’s the recommended depth for safe anal play? 📏", ["2–3 cm", "4–5 cm", "6–7 cm", "As deep as comfortable"], 3),
    ("Which fruit is linked to increased sexual stamina? 🍓", ["Strawberries", "Bananas", "Apples", "Grapes"], 1),
    ("What’s the term for a man’s first ejaculation? 🌱", ["Menarche", "Ejaculation", "Semenarche", "Pubarche"], 2),
    ("Which practice focuses on breath control during sex? 🌬️", ["Pranayama", "Karezza", "Sensate focus", "BDSM"], 0),
    ("What’s the average pH of semen? 🔬", ["5.0–6.0", "7.2–8.0", "8.5–9.5", "6.5–7.0"], 1),
    ("Which lubricant ingredient can cause irritation for some? ⚠️", ["Glycerin", "Dimethicone", "Propylene glycol", "Water"], 0),
    ("What’s the safest sex practice to prevent STIs? 🛡️", ["Oral sex", "Condom use", "IUD", "Withdrawal"], 1),
    ("Which nerve endings are dense in the inner labia? 🧩", ["Messiner’s corpuscles", "Pacinian corpuscles", "Ruffini endings", "Free nerve endings"], 3),
    ("What’s the main benefit of pelvic floor exercises? 🏋️‍♀️", ["Increased stamina", "Better lubrication", "Stronger orgasms", "Reduced libido"], 2),
    ("Which sex position maximizes clitoral stimulation? 🔝", ["Missionary", "Doggy style", "Cowgirl", "Spooning"], 2),
    ("What does “aftercare” refer to in BDSM? 🤝", ["Cleaning toys", "Emotional support", "Next session planning", "Physical fitness"], 1),
    ("Which barrier method is reusable? 🔁", ["Male condom", "Female condom", "Diaphragm", "Spermicide"], 2),
    ("What’s the average time to ejaculate for men? ⏱️", ["1–2 minutes", "3–7 minutes", "10–15 minutes", "20+ minutes"], 1),
    ("Which aroma is thought to boost libido? 🌹", ["Rose", "Lavender", "Mint", "Eucalyptus"], 0),
    ("Which part of the brain controls sexual arousal? 🧠", ["Cerebellum", "Hypothalamus", "Cerebrum", "Brainstem"], 1),
    ("Which sense can heighten arousal when blindfolded? 🕶️", ["Taste", "Smell", "Touch", "Hearing"], 2),
    ("What is a common fantasy for both men and women? 💭", ["Group sex", "Voyeurism", "Domination", "All of the above"], 3),
    ("Which fabric is most associated with sensual touch? 👗", ["Silk", "Wool", "Cotton", "Denim"], 0),
    ("Which hormone surges after orgasm? 🌊", ["Cortisol", "Adrenaline", "Oxytocin", "Insulin"], 2),
    ("What’s the medical term for low sexual desire? 💤", ["Erectile dysfunction", "Libido fatigue", "Hypoactive sexual desire disorder", "Arousal anxiety"], 2),
    ("Which toy provides clitoral suction? 💨", ["Wand", "Rabbit", "Satisfyer", "Cock ring"], 2),
    ("Which practice emphasizes deep eye contact during intimacy? 👁️", ["Tantra", "Kama Sutra", "Roleplay", "Bondage"], 0),
    ("Where are the Skene's glands located? 💦", ["Labia", "Cervix", "Urethra", "Clitoris"], 2),
    ("Which activity is common in edging? 🛑", ["Prolonged stimulation", "Immediate climax", "Chastity", "Silent play"], 0),
    ("Which fluid may be expelled during female ejaculation? 💧", ["Sweat", "Lymph", "Squirting fluid", "Urine"], 2),
    ("What is the typical texture of a latex condom? 🧽", ["Smooth", "Rough", "Sticky", "Powdery"], 0),
    ("Which fruit resembles testicles and is high in testosterone-boosting zinc? 🥜", ["Apple", "Avocado", "Banana", "Walnut"], 1),
    ("Which ancient text details erotic positions? 📜", ["Quran", "Kama Sutra", "Bible", "Tao Te Ching"], 1),
    ("What kind of stimulation is best for nipples? 🍒", ["Slapping", "Tickling", "Rhythmic pressure", "No touch"], 2),
    ("Which drink is considered an aphrodisiac? 🍷", ["Water", "Tea", "Wine", "Soda"], 2),
    ("Which sound can increase arousal? 🔊", ["Whispers", "Silence", "Loud music", "Traffic"], 0),
    ("Which scent is associated with arousal in men? 👃", ["Pumpkin pie", "Lavender", "Vanilla", "Cinnamon"], 0),
    ("Where is the perineum located? 📍", ["Neck", "Between genitals and anus", "Back", "Behind the knee"], 1),
    ("Which nerve is involved in penile erections? ⚡", ["Femoral", "Pudendal", "Ulnar", "Tibial"], 1),
    ("Which toy is commonly used for kegel exercises? 🎾", ["Plug", "Ball gag", "Ben Wa balls", "Feather tickler"], 2),
    ("What’s the effect of too much alcohol on sex? 🥴", ["Increased pleasure", "Easier climax", "Delayed orgasm", "Enhanced sensitivity"], 2),
    ("What kind of oil is NOT condom-safe? 🛢️", ["Water-based", "Silicone-based", "Oil-based", "Aloe-based"], 2),
    ("Which erogenous zone is behind the ear? 👂", ["None", "Major", "Minor", "Hidden"], 1),
    ("What’s the key to successful sexual communication? 🗣️", ["Silence", "Directness", "Non-verbal cues", "Avoidance"], 1),
    ("Which tool is used in temperature play? 🔥", ["Ice cubes", "Whip", "Blindfold", "Feather"], 0),
    ("Which animal is known for long mating sessions? 🦥", ["Tiger", "Pig", "Sloth", "Porcupine"], 1),
    ("What’s the purpose of a dental dam? 🦷", ["Oral hygiene", "Oral sex protection", "Teeth whitening", "Jaw alignment"], 1),
    ("Which position allows deepest penetration? 🔛", ["Spooning", "Doggy style", "Cowgirl", "Lotus"], 1),
    ("Which organ swells during arousal in both sexes? 🎈", ["Liver", "Heart", "Nasal passages", "Genitals"], 3),
    ("What is ‘afterglow’? 🌅", ["Post-sex fatigue", "Post-orgasm euphoria", "Second orgasm", "Sex dreams"], 1),
    ("Which food increases vaginal lubrication? 🥒", ["Celery", "Cucumber", "Yogurt", "Carrot"], 2),
    ("Which sex practice involves tying up? 🪢", ["Voyeurism", "Fisting", "Bondage", "Roleplay"], 2),
    ("Which flavor is linked to sexual memory? 🍫", ["Vanilla", "Mint", "Chocolate", "Garlic"], 2),
    ("What’s the name for an obsession with feet? 🦶", ["Podophilia", "Footomania", "Pedomania", "Toelust"], 0),
    ("What’s an aphrodisiac found in oysters? 🦪", ["Iron", "Calcium", "Zinc", "Potassium"], 2),
    ("Which practice avoids genital contact completely? 🧘", ["Karezza", "Dry humping", "Oral sex", "Anal play"], 1),
    ("Which sense is most triggered by lingerie? 👗", ["Touch", "Sight", "Sound", "Smell"], 1),
    ("Which toy vibrates at multiple frequencies? 📳", ["Plug", "Wand", "Feather", "Gag"], 1),
    ("What’s the primary purpose of foreplay? 💞", ["Reproduction", "Lubrication", "Arousal", "Contraception"], 2),
    ("Which sexual act can best stimulate the A-spot? 📌", ["Clitoral stimulation", "Deep vaginal penetration", "Anal sex", "Breast play"], 1),
    ("Which item is common in sensory deprivation play? 🙈", ["Candle", "Blindfold", "Rope", "Whip"], 1),
    ("What’s the refractory period? 💤", ["Time between arousal and orgasm", "Post-orgasm recovery time", "Duration of foreplay", "Time before arousal"], 1),
    ("Which muscle contracts during orgasm? 💪", ["Trapezius", "Gluteus", "Pelvic floor", "Hamstrings"], 2),
    ("Which vitamin helps with blood flow during sex? 💉", ["Vitamin A", "Vitamin C", "Vitamin E", "Vitamin D"], 3),
    ("Which condition causes painful intercourse? ⚠️", ["Dysphoria", "Anhedonia", "Dyspareunia", "Anorgasmia"], 2),
    ("Which setting is key for romantic ambiance? 🕯️", ["Bright lights", "Fluorescent bulbs", "Dim lighting", "Ceiling fan"], 2),
    ("Which position is best for maintaining eye contact? 👁️‍🗨️", ["Doggy style", "Reverse cowgirl", "Missionary", "Spooning"], 2),
    ("What’s the common function of a vibrating ring? 💍", ["Penile growth", "Pleasure for both partners", "Lubrication", "Contraception"], 1),
    ("What is erotic literature called? 📚", ["Biography", "Non-fiction", "Erotica", "Fantasy"], 2),
    ("Which part of the male anatomy contains the most nerve endings? 🎯", ["Penile shaft", "Testicles", "Frenulum", "Scrotum"], 2),
    ("Which movement enhances G-spot stimulation? 🔄", ["In and out thrusts", "Circular motion", "Side-to-side", "Pulsating taps"], 1),
    ("Which practice involves mental stimulation over physical? 🧠", ["Voyeurism", "Fetishism", "Sapiosexuality", "BDSM"], 2),
    ("Which element helps reduce vaginal dryness? 💦", ["Estrogen", "Calcium", "Magnesium", "Iron"], 0),
    ("Which hormone increases skin sensitivity? 🧬", ["Insulin", "Testosterone", "Estrogen", "Melatonin"], 2),
    ("What is the average time for female arousal? ⏳", ["30 seconds", "1 minute", "5–7 minutes", "10+ minutes"], 2),
    ("What part of the male anatomy swells during arousal? 📈", ["Prostate", "Frenulum", "Corpus cavernosum", "Bladder"], 2),
    ("Which position is recommended during pregnancy? 🤰", ["Missionary", "Doggy style", "Spooning", "Lotus"], 2),
    ("Which is a common fantasy involving power dynamics? 🧷", ["Teacher/student", "Strangers", "Friends", "Neighbors"], 0),
    ("Which substance is often called 'natural lube'? 🍯", ["Sweat", "Saliva", "Coconut oil", "Pre-ejaculate"], 3),
    ("Which activity is often part of roleplay? 🎭", ["Blindfolds", "Characters", "Pain", "Breath play"], 1),
    ("Which toy is best for anal beginners? 🚪", ["Large dildo", "Anal beads", "Small butt plug", "Vibrator"], 2),
    ("What’s the outer part of the vulva called? 🌸", ["Clitoris", "Labia majora", "Cervix", "Vaginal canal"], 1),
    ("Which supplement may boost male libido? 💊", ["Iron", "Zinc", "Magnesium", "Calcium"], 1),
    ("Which position often stimulates the perineum? 🧎", ["Doggy style", "Spooning", "Cowgirl", "Standing"], 0),
    ("What’s a kink? 🎢", ["A sexual dysfunction", "A playful attitude", "A non-standard preference", "A type of STI"], 2),
    ("Which activity is often paired with dirty talk? 🗯️", ["Massage", "Silence", "Roleplay", "Aftercare"], 2),
    ("What’s a safe word used for? 🛑", ["Code to stop play", "Trigger word", "Word to start sex", "Word to climax"], 0),
    ("Which toy often comes with a remote control? 🎮", ["Plug", "Wand", "Panty vibe", "Ring"], 2),
    ("Which gland contributes to semen production? 🥼", ["Spleen", "Prostate", "Liver", "Thyroid"], 1),
    ("What’s the common female sexual response pattern? 🔁", ["Linear", "Circular", "Random", "Flatline"], 1),
    ("Which plant is considered a natural aphrodisiac? 🌿", ["Aloe vera", "Ginseng", "Basil", "Thyme"], 1),
    ("Which kink involves obeying commands? 📏", ["Switching", "Submission", "Top play", "Service topping"], 1),
    ("Which fluid acts as natural lube for anal sex? 🧴", ["Saliva", "Sweat", "None", "Mucus"], 2),
    ("Which part of the female anatomy is shaped like a wishbone? 🦴", ["Vulva", "Clitoris", "Urethra", "Ovaries"], 1),
    ("What’s pegging? 🍆", ["Oral sex from behind", "Anal penetration of a male by a female", "Mutual masturbation", "Breast play"], 1),
    ("Which common household item should NOT be used as lube? 🚫", ["Vaseline", "Baby oil", "Olive oil", "All of the above"], 3),
    ("Which term describes love of pain during sex? 🩸", ["Masochism", "Narcissism", "Voyeurism", "Phobophilia"], 0),
    ("Which term refers to a person attracted to intelligence? 🧠", ["Sapiophile", "Nerdo-erotic", "Sapiosexual", "Thinkophile"], 2),
    ("Which lube type is safest with latex condoms? 🧴", ["Oil-based", "Water-based", "Silicone-based", "Petroleum jelly"], 1),
    ("What’s the main erogenous zone in the male perineum? 📍", ["Near scrotum", "Inside urethra", "Lower abdomen", "Inner thigh"], 0),
    ("Which hormone surges during cuddling? 🤗", ["Cortisol", "Adrenaline", "Oxytocin", "Serotonin"], 2),
    ("Which item is often used in light BDSM? 🧣", ["Lotion", "Scarf", "Sponge", "Brush"], 1),
    ("Which action best stimulates the clitoral hood? 🎯", ["Firm rubbing", "Indirect pressure", "Suction", "Pinching"], 1),
    ("Which technique delays orgasm for men? 🕒", ["Pulsing", "Quick thrusts", "Edging", "Breath-holding"], 2),
    ("What does the ‘G’ in G-spot stand for? 🔠", ["Girth", "Grafenberg", "Glisten", "Grail"], 1),
    ("Which sound is often considered sensual? 🎼", ["Jazz", "Heavy metal", "Techno", "Marching band"], 0),
    ("What’s the scientific name for the female G-spot? 🔬", ["Grafenberg spot", "Vaginal apex", "Clitoral bundle", "Sacral bulb"], 0),
    ("Which practice uses feather-like touch to arouse? 🪶", ["Feathering", "Tickle play", "Tease and denial", "Petting"], 0),
    ("Which toy is commonly used for prostate massage? 📍", ["Plug", "Beads", "Vibrator", "Ring"], 2),
    ("What’s a sexual activity that doesn’t involve penetration? 🚫", ["Outerplay", "Dry sex", "Heavy petting", "Breast play"], 2),
    ("Which part of the vagina is closest to the exterior? 🚪", ["Cervix", "Canal", "Introitus", "G-spot"], 2),
    ("Which kink involves watching others? 👀", ["Voyeurism", "Exhibitionism", "Bondage", "Switching"], 0),
    ("What’s one effect of aphrodisiac foods? 🍓", ["Improved vision", "Reduced hunger", "Increased desire", "Lower blood sugar"], 2),
    ("Which is a discreet wearable sex toy? 👙", ["Cock ring", "Panty vibrator", "Ben Wa balls", "Nipple clamps"], 1),
    ("Which activity involves slow, intentional sex? 🧘‍♀️", ["Quickie", "Tantric", "Kink", "Roleplay"], 1),
    ("Which part of the male anatomy produces sperm? 🧫", ["Testicles", "Bladder", "Penis", "Seminal vesicle"], 0),
    ("Which fantasy involves being watched during sex? 🔍", ["Voyeurism", "Exhibitionism", "Domination", "Shibari"], 1),
    ("What is an anilingus colloquially known as? 🍑", ["Rimming", "Dry humping", "Fisting", "Teasing"], 0),
    ("Which part of the female anatomy contains erectile tissue? 🔥", ["Uterus", "Clitoris", "Cervix", "Labia minora"], 1),
    ("Which color lighting is often associated with erotic ambiance? 🔴", ["White", "Blue", "Red", "Green"], 2),
    ("Which practice includes binding with ropes? 🪢", ["Tantra", "Impact play", "Shibari", "Breath play"], 2),
    ("Which term means achieving climax without touch? 🌀", ["Mental orgasm", "Tantric release", "Dry orgasm", "Energetic orgasm"], 3),
    ("Which tool might you find in a kink kit? 🧰", ["Screwdriver", "Stethoscope", "Flogger", "Toothbrush"], 2),
    ("Which item is often used in temperature play? ❄️", ["Hairdryer", "Ice cube", "Metal rod", "Feather"], 1),
    ("What’s a common psychological benefit of sex? 😊", ["Anxiety", "Stress relief", "Forgetfulness", "Tiredness"], 1),
    ("Which position maximizes pelvic tilt for stimulation? 🧎‍♀️", ["Lotus", "Bridge", "Missionary", "Standing"], 1),
    ("What’s a safeword commonly used? 🟡", ["No", "Stop", "Banana", "Go"], 2),
    ("Which hormone is associated with sexual excitement? 🚀", ["Adrenaline", "Melatonin", "Insulin", "Thyroxine"], 0),
    ("What’s the purpose of a cock ring? ⭕", ["Prevent arousal", "Increase size", "Enhance erection", "Block blood flow"], 2),
    ("What is mutual masturbation? ✋", ["Solo only", "Watching only", "Touching each other", "Silent sex"], 2),
    ("What’s considered erotic when whispered? 👂", ["Math facts", "Dirty talk", "Cooking tips", "Book reviews"], 1),
    ("Which scent boosts female arousal? 🌸", ["Cedarwood", "Pumpkin pie", "Lavender", "Rose"], 3),
    ("What’s a roleplay dynamic involving control? 🎬", ["Stranger play", "Student/teacher", "Sibling fantasy", "Massage"], 1),
    ("Which act involves teasing without orgasm? 🧨", ["Edging", "Fisting", "Pegging", "Showering"], 0),
    ("What does BDSM stand for? 🕸️", ["Bondage, Discipline, Sadism, Masochism", "Boys Do Sexy Moves", "Basic Drama Sexual Method", "Bold Dominant Sexy Mode"], 0),
    ("What’s an example of exhibitionism? 📸", ["Sex in public", "Wearing latex", "Using a toy", "Silent foreplay"], 0),
    ("Which fabric is often considered sensual? 🧵", ["Denim", "Lace", "Polyester", "Velvet"], 1),
    ("What’s the primary purpose of aftercare in BDSM? 🫂", ["Sex", "Punishment", "Emotional support", "Dominance"], 2),
    ("Which area is most responsive to light kisses? 💋", ["Forehead", "Shoulder blades", "Nape of the neck", "Fingernails"], 2),
    ("What’s the name of the fetish for feet? 🦶", ["Podophilia", "Pedophilia", "Manophilia", "Footmania"], 0),
    ("Which toy is shaped like a wand for external use? 🪄", ["Butt plug", "Rabbit", "Wand massager", "Bullet"], 2),
    ("What kind of talk can build arousal through words? 🗣️", ["Dirty talk", "Small talk", "Storytelling", "Whining"], 0),
    ("Which is a safe lube for silicone toys? 🧪", ["Silicone-based", "Oil-based", "Water-based", "Butter"], 2),
    ("Which of these is a BDSM role? 👑", ["King", "Submissive", "Romantic", "Teaser"], 1),
    ("Which setting enhances intimacy naturally? 🌌", ["Crowded street", "Quiet bedroom", "Office", "Gym"], 1),
    ("What’s one benefit of sexual exploration? 🌱", ["Confusion", "Closeness", "Isolation", "Addiction"], 1),
    ("What’s the term for sexual arousal from being dominated? 🕯️", ["Switching", "Masochism", "Submission", "Voyeurism"], 2),
    ("Which sense is most commonly involved in kink play? 🎧", ["Sight", "Sound", "Taste", "Touch"], 3),
    ("What’s a common material used in restraints? 🪢", ["Plastic", "Silk", "Wool", "Foam"], 1),
    ("Which food is often used in erotic scenes? 🍫", ["Rice", "Chocolate", "Broccoli", "Bread"], 1),
    ("Which is an erogenous zone on the inner body? 🔍", ["Elbow", "Behind the knee", "Wrist", "Shoulder"], 1),
    ("What’s an erotic act that uses voice only? 📞", ["Moaning", "Dirty talking", "Phone sex", "Roleplay"], 2),
    ("Which fruit is symbolic in sexual imagery? 🍑", ["Apple", "Grape", "Peach", "Mango"], 2),
    ("Which action increases anticipation during foreplay? ⏱️", ["Direct stimulation", "Avoiding touch", "Talking", "Sudden movement"], 1),
    ("What’s a sign of consent during sex? ✅", ["Silence", "Active participation", "Stillness", "Tears"], 1),
    ("Which massage type focuses on erotic zones? 💆‍♀️", ["Swedish", "Tantric", "Shiatsu", "Thai"], 1),
    ("Which fabric is often worn in lingerie? 👙", ["Leather", "Cotton", "Lace", "Denim"], 2),
    ("What toy is used for both vaginal and anal play? 🎯", ["Flogger", "Dual-ended dildo", "Nipple clamps", "Ring"], 1),
    ("Which is a benefit of sexual communication? 📢", ["Confusion", "Connection", "Boredom", "Delay"], 1),
    ("What’s a common safe word system? 🟢", ["Yes/No", "Stop/Go", "Green/Yellow/Red", "Please/Don't"], 2),
    ("Which term describes arousal from being watched? 📺", ["Exhibitionism", "Voyeurism", "Masochism", "Fetishism"], 0),
    ("Which fruit often symbolizes testicles in sexting? 🍒", ["Banana", "Peach", "Grapes", "Cherries"], 3),
    ("What’s the outer structure surrounding the clitoris? 🧭", ["Labia majora", "Vaginal walls", "Clitoral hood", "Perineum"], 2),
    ("Which practice encourages non-orgasmic sex? 🧘", ["BDSM", "Tantra", "Quickies", "Dirty talk"], 1),
    ("Which sex act involves light pain for pleasure? 🧯", ["Spanking", "Tickling", "Cuddling", "Kissing"], 0),
    ("What does the prostate feel like when stimulated? 🧱", ["Smooth", "Rubbery", "Hard bone", "Soft tissue"], 1),
    ("What does mutual consent mean in intimacy? 🤝", ["One-sided want", "Both agree", "Unspoken agreement", "Surprise"], 1),
    ("What’s the safest practice for anal play? 🧼", ["No lube", "Use toys with flared base", "Rush penetration", "Ignore signals"], 1),
    ("Which sex toy mimics oral stimulation? 👅", ["Beads", "Wand", "Suction toy", "Dildo"], 2),
    ("What body part responds to pheromones? 👃", ["Eyes", "Skin", "Nose", "Mouth"], 2),
    ("Which visual is often used in erotic media? 📸", ["Mountains", "Hands", "Silhouettes", "Animals"], 2),
    ("Which kink involves dressing up in costume? 👗", ["Sensory play", "Roleplay", "Impact play", "Bondage"], 1),
    ("Which of these is NOT a typical kink? 🚫", ["Tickling", "Choking", "Respect", "Shibari"], 2),
    ("Which position allows for deep penetration? 📏", ["Spooning", "Missionary", "Doggy style", "Side by side"], 2),
    ("What is considered a basic rule in kink? 📜", ["No talking", "Surprise play", "Consent", "Ignore rules"], 2),
    ("What part of the body do some find erotic to bite? 🧄", ["Knee", "Shoulder", "Toes", "Fingernails"], 1),
	],
    'hquiz': [
    ("What kind of moan drives people wild? 🔊", ["Silent", "High-pitched", "Whispery", "Guttural"], 3),
    ("Which clothing item is often seen as a turn-on? 👙", ["Turtleneck", "Lingerie", "Sneakers", "Raincoat"], 1),
    ("Where is a love bite most commonly left? 💋", ["Shoulder", "Thigh", "Neck", "Ear"], 2),
    ("Which body part do people secretly love being kissed? 😘", ["Toes", "Inner thigh", "Forehead", "Back of knee"], 1),
    ("Which emoji is used flirtatiously in sexting? 🍆", ["🍎", "🍕", "🍆", "🎩"], 2),
    ("What kind of photo is called a 'thirst trap'? 📸", ["Travel selfie", "Pet picture", "Sultry selfie", "Food pic"], 2),
    ("Which sound is most associated with arousal? 🔥", ["Giggle", "Sigh", "Gasp", "Snore"], 2),
    ("Which flavor is most often associated with sensual lips? 💄", ["Vanilla", "Cherry", "Mint", "Orange"], 1),
    ("Where do naughty thoughts often start? 💭", ["In dreams", "At work", "In the shower", "At dinner"], 2),
    ("What kind of message starts the flirt game? 💌", ["Compliment", "Confession", "GIF", "Emoji"], 0),
    ("What's considered the ultimate tease move? 😈", ["Wink", "Eye contact", "Biting lip", "Foot tap"], 2),
    ("Which of these is a classic 'naughty' outfit? 👠", ["Overalls", "Tuxedo", "Schoolgirl skirt", "Jumpsuit"], 2),
    ("What kind of touch is most likely to give goosebumps? 🥶", ["Soft caress", "Firm grip", "Pat", "Pinch"], 0),
    ("Which part of the lips is most kissable? 💋", ["Corners", "Bottom lip", "Upper lip", "Cupid's bow"], 1),
    ("Where are hands placed in a classic steamy scene? ✋", ["On waist", "On face", "On thighs", "On knees"], 2),
    ("Which snack is considered sexy to eat slowly? 🍓", ["Popcorn", "Strawberry", "Chips", "Cheese stick"], 1),
    ("What’s a flirtatious way to drink something? 🥤", ["Fast gulp", "Eye contact sip", "Spill a little", "Straw slurp"], 3),
    ("Which move is the ultimate tease while dancing? 💃", ["Hip roll", "Shoulder shrug", "Hair flip", "Step touch"], 0),
    ("Where does the cheeky hand accidentally go? 😏", ["Elbow", "Lower back", "Knee", "Ankle"], 1),
    ("Which emoji screams ‘I’m feeling naughty’? 😜", ["😜", "😊", "😇", "🥶"], 0),
    ("Which action is often used in playful foreplay? 🫦", ["Staring", "Tickling", "Reading", "Talking politics"], 1),
    ("What’s the most seductive accessory? 🕶️", ["Sunglasses", "Earrings", "Choker", "Purse"], 2),
    ("Which innocent item becomes sexy when used right? 🧁", ["Notebook", "Whipped cream", "Ruler", "Candle"], 1),
    ("Where does the trail of kisses usually end? 🐾", ["Neck", "Chest", "Thighs", "Toes"], 2),
    ("What fabric feels sexiest on skin? 🪶", ["Wool", "Velvet", "Silk", "Corduroy"], 2),
    ("Which emoji pair hints at something naughty? 🍑💦", ["🍎🍇", "🥦🍅", "🍑💦", "🥖🧄"], 2),
    ("What’s a subtle way to show you're turned on? 🥵", ["Blushing", "Shaking", "Biting lip", "Stammering"], 2),
    ("Which outfit screams ‘I’m in the mood’? 🧥", ["Pajamas", "Oversized hoodie", "Lingerie", "Gym shorts"], 2),
    ("What body part is often left tingling after teasing? ⚡", ["Nose", "Arm", "Inner thigh", "Ear"], 2),
    ("What flavor is commonly associated with kissing games? 🍒", ["Chocolate", "Cherry", "Mango", "Cinnamon"], 1),
    ("Which moment usually leads to a naughty suggestion? ⏳", ["Eye lock", "Compliment", "Sigh", "Awkward silence"], 0),
    ("Which dance move often makes pulses race? 🩰", ["Twerk", "Spin", "Dip", "Slide"], 0),
    ("What kind of whisper turns someone on? 🗣️", ["Loud", "Raspy", "Breathy", "Fast"], 2),
    ("Which outfit detail is made to entice? 🔗", ["Loose pants", "Open shirt", "High socks", "Tucked-in tee"], 1),
    ("What’s the first step in a make-out session? 💞", ["Eye contact", "Compliment", "Hand touch", "Lick lips"], 0),
    ("What’s the sneakiest way to turn someone on in public? 🙈", ["Text", "Stare", "Touch under table", "Whisper joke"], 2),
    ("Which dessert is often used in flirty play? 🍰", ["Brownie", "Whipped cream", "Jelly", "Donut"], 1),
    ("Where does a flirtatious gaze usually land? 👁️", ["Eyes", "Lips", "Chest", "Hair"], 1),
    ("Which part of the back is most sensitive to touch? 🫱", ["Lower", "Upper", "Middle", "Shoulder blades"], 0),
    ("What’s the most common 'accidental' sexy move? 🧎", ["Dropping something", "Stretching", "Sitting slowly", "Shoe tie"], 0),
    ("Which part of undressing is often the biggest tease? 🧺", ["Unbuttoning", "Removing shoes", "Taking off socks", "Taking off earrings"], 0),
    ("What’s the classic naughty movie snack? 🍿", ["Gummy bears", "Popcorn", "Ice cream", "Pickles"], 1),
    ("Where does a teasing finger usually wander? ☝️", ["Ear", "Shoulder", "Inner thigh", "Forearm"], 2),
    ("Which look usually says 'take me now'? 👀", ["Blank stare", "Raised brow", "Bedroom eyes", "Blinking fast"], 2),
    ("What part of the neck is most kissable? 🧣", ["Back", "Side", "Front", "Base"], 1),
    ("What’s the most suggestive way to eat a popsicle? 🍭", ["Licking slowly", "Biting", "Snapping in half", "Sucking gently"], 3),
    ("What’s the biggest tease during a strip tease? 😮‍💨", ["Removing shirt", "Undoing belt", "Walking away", "Unzipping slowly"], 3),
    ("What does biting your lip usually signal? 🫦", ["Hunger", "Nervousness", "Seduction", "Pain"], 2),
    ("What’s the most erotic use of whipped cream? 🍦", ["In coffee", "On cake", "On skin", "In ice cream"], 2),
    ("What’s the steamiest time of day for many people? 🌇", ["Morning", "Afternoon", "Evening", "Late night"], 3),
    ("Where’s the best place to kiss to give shivers? 🥶", ["Elbow", "Behind the ear", "Forearm", "Knee"], 1),
    ("Which emoji screams ‘I’m horny’? 😩", ["😩", "😁", "🤢", "🥶"], 0),
    ("What’s a naughty way to reply to a text? 📲", ["Ignore", "Send a pic", "Use emojis", "Voice note"], 1),
    ("Which position is used in suggestive stretching? 🧘", ["Downward dog", "Lotus", "Plank", "Bridge"], 0),
    ("What body language shows secret desire? 🫣", ["Arms crossed", "Avoiding gaze", "Leaning in", "Tapping foot"], 2),
    ("Which item is often removed last for effect? 🧦", ["Shirt", "Bra", "Socks", "Underwear"], 3),
    ("What type of laugh hints at dirty thoughts? 😈", ["High-pitched", "Giggly", "Snort", "Low chuckle"], 3),
    ("What’s a flirty way to blow a kiss? 😘", ["Quick air kiss", "Two fingers", "Over the shoulder", "Slow and direct"], 3),
    ("What’s the real reason for a deep v-neck shirt? 👕", ["Air flow", "Style", "Comfort", "Flirting"], 3),
    ("What’s a sneaky way to flash someone? ✨", ["Lifting shirt", "Fixing top", "Bending over", "Stretching"], 2),
    ("What’s a naughty way to end a date? 🚪", ["Handshake", "Quick hug", "Lingering kiss", "Fist bump"], 2),
    ("What does it mean if someone texts ‘I’m bored 🥱’? 📱", ["They’re sleepy", "They want attention", "They're hungry", "They’re flirting"], 3),
    ("Which emoji combo screams sexting energy? 💋🔥", ["💋🔥", "😎🧊", "🍇🍕", "🥕🌪️"], 0),
    ("Which part of a slow dance is most intimate? 💃", ["Eye contact", "Arm placement", "Breathing", "Hip sway"], 3),
    ("Where is the most mischievous place to kiss in public? 💑", ["On lips", "On cheek", "On neck", "On hand"], 2),
    ("What’s the most flirty compliment? 🌶️", ["You're sweet", "You're dangerous", "You're smart", "You're polite"], 1),
    ("What action screams ‘I want you’? 🫠", ["Wink", "Smile", "Stare at lips", "Laugh"], 2),
    ("Which is a cheeky way to describe being turned on? 🌋", ["Heated", "Warm", "Energized", "Exploding"], 0),
    ("What’s a hot way to answer the door? 🚪", ["In a robe", "In towel", "Fully dressed", "Underwear only"], 1),
    ("Which zone is most teased during kissing games? 🎯", ["Fingers", "Thighs", "Neck", "Toes"], 2),
    ("What’s the kinkiest thing you can whisper? 🧨", ["Your name", "A secret", "What you’re wearing", "What I want to do to you"], 3),
    ("What kind of photo usually gets a '😳' reply? 📷", ["Group pic", "Meme", "Shower selfie", "Food snap"], 2),
    ("Which of these is an instant thirst trap? 💧", ["Bed selfie", "Beach pic", "Mirror gym selfie", "Bikini on chair"], 2),
    ("Which of these makes people think naughty thoughts? 🥵", ["Stretching", "Reading", "Snacking", "Blinking"], 0),
    ("What’s the most seductive accessory on a man? 👔", ["Necklace", "Watch", "Tie", "Belt"], 2),
    ("What kind of smile usually means someone’s horny? 😼", ["Soft smile", "Smirk", "Giggle", "Grin"], 1),
    ("What’s a suggestive act with a popsicle? 🍧", ["Biting", "Licking slowly", "Dropping it", "Crushing it"], 1),
    ("Which move is pure foreplay in disguise? 🪑", ["Sitting close", "Foot tap", "Breathing heavy", "Hair flip"], 0),
    ("What does an ‘accidental’ touch on the thigh suggest? 👖", ["Clumsiness", "Comfort", "Desire", "Cold"], 2),
    ("What’s the real reason for dim lighting in the bedroom? 🕯️", ["Saving energy", "Romance", "Hide mess", "Hide body"], 1),
    ("Which of these is a classic naughty text opener? 📩", ["Hey", "What u doin?", "Thinking of you...", "LOL"], 2),
    ("Where does wandering eye contact usually end up? 👁️", ["Eyes", "Lips", "Neck", "Chest"], 3),
    ("Which phrase is a dead giveaway for being horny? 💬", ["I'm bored", "You up?", "I miss you", "Hey stranger"], 1),
    ("Which drink is often associated with flirty vibes? 🍷", ["Coffee", "Tea", "Wine", "Juice"], 2),
    ("What is often the start of steamy roleplay? 🎭", ["Costume", "Story", "Voice", "Setting"], 0),
    ("Where does the hand 'accidentally' slide during cuddles? 🤭", ["Back", "Chest", "Thigh", "Neck"], 2),
    ("Which action turns a hug into something more? 🤗", ["Lifting", "Squeeze", "Whisper", "Prolonging"], 3),
    ("Which piece of clothing screams 'strip me'? 👗", ["Pajamas", "Tight dress", "Jacket", "T-shirt"], 1),
    ("What’s the real reason for licking lips? 👄", ["Thirsty", "Dry", "Nervous", "Flirting"], 3),
    ("What kind of movie is code for 'let’s cuddle'? 🎥", ["Comedy", "Romance", "Horror", "Action"], 2),
    ("What kind of look says 'I want you'? 🧿", ["Blank", "Intense", "Side glance", "Raised eyebrow"], 1),
    ("Which touch says more than words? ✋", ["High five", "Soft stroke", "Back pat", "Fist bump"], 1),
    ("What do playful texts at 2am usually mean? 🌙", ["Friendship", "Help", "Lonely", "Horny"], 3),
    ("Which object gets naughty in food play? 🍫", ["Bread", "Pasta", "Chocolate syrup", "Pickles"], 2),
    ("Which scent is most associated with arousal? 🌸", ["Rose", "Vanilla", "Mint", "Lavender"], 1),
    ("What’s a hot way to sit next to your crush? 💺", ["Cross arms", "Knees touching", "Staring ahead", "Slouched"], 1),
    ("Where does a seductive glance linger? 🔥", ["Eyes", "Lips", "Neck", "Feet"], 1),
    ("Which dance move gets the most attention? 🍑", ["Jumping", "Hair flip", "Twerking", "Spinning"], 2),
    ("Which emoji combo means 'ready for action'? 🛏️😈", ["🌮🍕", "🛏️😈", "📚😴", "🧃🍞"], 1),
    ("Which food is famously sensual to eat? 🍌", ["Breadstick", "Banana", "Carrot", "Apple"], 1),
    ("What’s often removed during a 'heated moment'? 🧢", ["Watch", "Socks", "Glasses", "Hat"], 1),
    ("Which surface is most likely for spontaneous fun? 🛋️", ["Bed", "Car", "Couch", "Chair"], 2),
    ("Which common phrase becomes dirty when whispered? 🗣️", ["Good night", "Yes", "Now", "Come here"], 3),
    ("Which position is always innocent—until it’s not? 🧘", ["Child's pose", "Lunge", "Bridge", "Plank"], 0),
    ("Which classic movie setting fuels fantasy? 🎬", ["Library", "Elevator", "Park", "Kitchen"], 1),
    ("Which action gets interpreted as a green light? ✅", ["Laughing", "Eye roll", "Biting lip", "Shrug"], 2),
    ("Which late-night snack is also used in the bedroom? 🍯", ["Cookies", "Honey", "Chips", "Pickles"], 1),
    ("What’s the sexiest part of a back massage? 👐", ["Pressure", "Slow pace", "Lower back", "Whispering"], 2),
    ("Where do the eyes travel when someone’s turned on? 👁️‍🗨️", ["Forehead", "Nose", "Lips", "Shoes"], 2),
    ("Which flirty question usually leads to mischief? 🫦", ["What's up?", "What are you wearing?", "Seen this movie?", "Did you eat?"], 1),
    ("Which phrase means ‘I'm thinking dirty’? 💭", ["Oops", "Hmmm", "Maybe", "Stop it"], 3),
    ("What makes biting your finger look sexy? 🖐️", ["Nervousness", "Eye contact", "Chewing nails", "Yawning"], 1),
    ("What kind of text gets a steamy response? 💌", ["You looked hot today", "Miss u", "LOL", "Busy?"], 0),
    ("Which article of clothing is made to slide off slowly? 👚", ["Socks", "Scarf", "Shirt", "Hat"], 2),
    ("Where’s the best place for a secret touch? 👟", ["Back", "Ankle", "Thigh", "Elbow"], 2),
    ("Which position is perfect for a suggestive photo? 🤳", ["Straight-on", "From above", "Over-the-shoulder", "Sitting slouch"], 2),
    ("Which compliment turns dirty depending on tone? 💬", ["You’re cute", "You smell good", "You're flexible", "You’re fun"], 2),
    ("What sound gives away that someone’s enjoying too much? 🎧", ["Breath hitch", "Sigh", "Gasp", "Snort"], 2),
    ("Which part of taking off shoes can be sensual? 👠", ["Slipping off slowly", "Throwing them", "Untying laces", "Jumping out"], 0),
    ("What’s a flirty way to eat spaghetti? 🍝", ["Slurping", "Biting", "Cutting it", "Sucking slowly"], 3),
    ("What sound is a giveaway during steamy moments? 🔊", ["Sniff", "Moan", "Cough", "Laugh"], 1),
    ("Where’s the riskiest place to be kissed? 🧨", ["Forehead", "Neck", "Hand", "Shoulder"], 1),
    ("Which item in a bedroom hints at kink? 🧣", ["Teddy bear", "Candle", "Silk scarf", "Books"], 2),
    ("Which pet name sounds naughtier when whispered? 🐾", ["Babe", "Love", "Daddy", "Sweetie"], 2),
    ("Which word becomes instantly dirty in the right tone? 🫢", ["Please", "Stop", "Now", "More"], 3),
    ("What’s the sexiest item to drop 'accidentally'? 📎", ["Pen", "Towel", "Phone", "Shirt"], 1),
    ("Where does a playful bite usually land? 🦷", ["Nose", "Finger", "Ear", "Toe"], 2),
    ("Which emoji says 'let’s get it on'? 🥵", ["🥶", "🥳", "🥵", "😴"], 2),
    ("Which line gets the naughtiest replies? 💌", ["Come over", "Goodnight", "Can I see you?", "Let’s cuddle"], 0),
    ("What’s a subtle way to say you’re turned on? 😮‍💨", ["I'm bored", "Need distraction", "Thinking of you", "Netflix?"], 2),
    ("Which body part is often teased with fingertips? 🤏", ["Back", "Neck", "Thigh", "Cheek"], 2),
    ("Which outfit piece often gets removed with a smirk? 👖", ["Socks", "Pants", "Glasses", "Watch"], 1),
    ("Which late-night text says ‘I'm down’? 📲", ["Hey", "Still awake?", "Lol", "Did you eat?"], 1),
    ("What action makes someone look irresistibly seductive? 👀", ["Hair flip", "Lip bite", "Pout", "Blink"], 1),
    ("What sound effect always makes scenes hotter? 🔥", ["Slow moans", "Giggle", "Sniff", "Snore"], 0),
    ("Where’s the best place to leave a love bite? 💋", ["Wrist", "Back", "Neck", "Shoulder"], 2),
    ("Which word whispered changes everything? 🗣️", ["Please", "Now", "Yes", "Closer"], 1),
    ("Which position during cuddling leads to more? 🛏️", ["Side by side", "Spooning", "Head on chest", "Face to face"], 1),
    ("What’s the most flirty kind of stretch? 🧘", ["Arms overhead", "Back arch", "Toe touch", "Neck roll"], 1),
    ("What’s a sexy way to take off a jacket? 🧥", ["Quickly", "Over shoulder", "Slow and teasing", "Tossing it"], 2),
    ("Where do ‘accidental’ touches always happen? 🫣", ["Shoulder", "Hand", "Thigh", "Back"], 2),
    ("What makes a whisper way more seductive? 🔇", ["Volume", "Proximity", "Content", "Timing"], 1),
    ("What do bedroom eyes usually mean? 😏", ["Tired", "Flirty", "Hungry", "Shy"], 1),
    ("Which act turns innocent cuddling into foreplay? 🤫", ["Tickling", "Hip grinding", "Breathing heavily", "Neck kissing"], 3),
    ("What item screams ‘leave it on’? 🧦", ["Shirt", "Watch", "Heels", "Necklace"], 2),
    ("What facial expression gives away naughty thoughts? 🫦", ["Smile", "Raised eyebrow", "Licking lips", "Blushing"], 2),
    ("What’s the flirtiest way to say ‘goodnight’? 🌙", ["Sleep tight", "Dream of me", "Talk soon", "Bye"], 1),
    ("What body part invites teasing with ice? 🧊", ["Toes", "Neck", "Back", "Thigh"], 1),
    ("What action makes a kiss extra sensual? 💋", ["Open eyes", "Grab hair", "Breath hold", "Smile"], 1),
    ("Which clothing removal is slowest on purpose? 🧤", ["Socks", "Gloves", "Shirt", "Pants"], 1),
    ("What phrase turns texts into sexts? 📲", ["Thinking of you", "Wish you were here", "I miss your hands", "Sweet dreams"], 2),
    ("Which bedroom item is secretly kinky? 🛏️", ["Pillow", "Belt", "Curtain", "Lamp"], 1),
    ("What emoji makes a flirty text thirstier? 🍑", ["😳", "😂", "🍑", "🧢"], 2),
    ("What touch sparks instant goosebumps? 🥶", ["Light tracing", "Slap", "Pressure point", "Grab"], 0),
    ("What snack becomes sensual depending on context? 🍓", ["Chips", "Strawberries", "Pretzels", "Crackers"], 1),
    ("Which phrase says ‘take me’ without saying it? 😈", ["I'm bored", "Come here", "Now or never", "I need help"], 1),
    ("Which slow action in bed is a total tease? 🛌", ["Getting in", "Rolling over", "Taking off socks", "Stretching"], 3),
    ("Which buttoned item is often undressed seductively? 👔", ["Jeans", "Shirt", "Coat", "Overalls"], 1),
    ("Which late-night emoji means you’re up to no good? 🌚", ["😅", "🌚", "😂", "😴"], 1),
    ("Which sound says you're totally into it? 🎶", ["Sigh", "Moan", "Laugh", "Sniffle"], 1),
    ("Which item hints at a playful night? 🐇", ["Lube", "Perfume", "Handcuffs", "Socks"], 2),
    ("What body part is often 'accidentally' grazed? 🤭", ["Arm", "Thigh", "Ankle", "Elbow"], 1),
    ("Which emoji screams 'send nudes'? 📸", ["😉", "🫦", "🍆", "🙈"], 3),
    ("Which word instantly changes the mood? 🔥", ["Please", "Now", "Don't", "Stop"], 0),
    ("Where does a naughty hand wander first? ✋", ["Hip", "Back", "Thigh", "Stomach"], 2),
    ("What's a subtle flirty move on a date? 🥂", ["Eye contact", "Cheers", "Foot touch", "Hair flip"], 2),
    ("Which phrase turns compliments steamy? 💬", ["You look good", "That color suits you", "You're glowing", "I'd ruin you"], 3),
    ("Which item in your drawer is secretly sexy? 🧦", ["Scarf", "Silk tie", "Sunglasses", "Gloves"], 1),
    ("What kind of glance causes weak knees? 👀", ["Long stare", "Smirk and look away", "Eyebrow raise", "Slow blink"], 0),
    ("Where do kisses linger during foreplay? 💋", ["Neck", "Forehead", "Back", "Earlobe"], 0),
    ("What’s a sign your crush is thinking dirty? 🤔", ["Biting lip", "Zoning out", "Texting fast", "Avoiding eye contact"], 0),
    ("What kind of voice gets the blood pumping? 🔊", ["Loud", "Playful", "Whiny", "Low and breathy"], 3),
    ("Where is the most seductive place to whisper? 👂", ["Ear", "Neck", "Shoulder", "Lips"], 0),
    ("What action makes cuddling 10x hotter? 🧸", ["Whispering", "Snoring", "Foot rub", "Hip pull"], 3),
    ("Which of these is code for 'I'm horny'? 🫠", ["I can't sleep", "Hey stranger", "You up?", "All of the above"], 3),
    ("What makes unbuttoning a shirt extra hot? 🧵", ["Fast motion", "Slow tease", "With eye contact", "Accidentally"], 2),
    ("What usually happens after intense eye contact? 🫦", ["Smile", "Blush", "Kiss", "Look away"], 2),
    ("Which flirt tactic works without speaking? 🤐", ["Lip biting", "Eye roll", "Hair twirl", "Smile"], 0),
    ("Which setting is most likely to start something steamy? 🛀", ["Car", "Shower", "Park", "Couch"], 1),
    ("What kind of clothing makes teasing easier? 🧼", ["Leather", "Denim", "Lace", "Wool"], 2),
    ("Which food makes for perfect body topping? 🍯", ["Whipped cream", "Popcorn", "Chips", "Fruit"], 0),
    ("What time of day are naughty thoughts strongest? 🕒", ["Morning", "Afternoon", "Late night", "Midday"], 2),
    ("Which phrase can go from sweet to spicy fast? 🥵", ["I need you", "Come here", "You're cute", "I can't wait"], 1),
    ("What gesture invites naughty imagination? 🤌", ["Neck touch", "Finger lick", "Hair flip", "Knee bounce"], 1),
    ("Which area is often teased but off-limits—at first? ❌", ["Neck", "Back", "Inner thigh", "Feet"], 2),
    ("What emoji do you send after a steamy message? 😈", ["🙈", "🔥", "😈", "🫣"], 2),
    ("What body language screams 'take me now'? 💃", ["Leaning in", "Leg cross", "Heavy breathing", "Head tilt"], 2),
    ("What’s a go-to phrase in a hot roleplay? 🎭", ["Yes, sir", "Oops", "Are you ready?", "No way"], 0),
    ("Where do seductive fingers love to trace? ☝️", ["Spine", "Wrist", "Forearm", "Ankle"], 0),
    ("Which reaction confirms you hit the right spot? 😵‍💫", ["Sigh", "Gasp", "Shiver", "All of the above"], 3),
    ("What kind of laugh signals flirt overload? 😂", ["Soft chuckle", "Snort", "Giggly", "Fake"], 2),
    ("Which clothing is practically begging to be untied? 🎀", ["Corset", "Tie", "Scarf", "Drawstring pants"], 0),
    ("Which public gesture is most secretly pervy? 😏", ["Thigh touch", "Neck kiss", "Whisper", "Wink"], 1),
    ("What makes a voice message extra hot? 🎙️", ["Low tone", "Fast talking", "Giggling", "Pause-heavy"], 0),
    ("Which kind of stare means 'undress me now'? 👁️", ["Lingering", "Darting", "Averting", "Sideways"], 0),
    ("Where do love bites leave the biggest mark? 🍎", ["Wrist", "Back", "Neck", "Chest"], 2),
    ("Which item doubles as a bedroom toy? 🎀", ["Hair tie", "Toothbrush", "Pillow", "Belt"], 3),
    ("Which time of night feels the sexiest? 🌃", ["10 PM", "Midnight", "3 AM", "5 AM"], 1),
    ("What action gives away bedroom confidence? 😮‍💨", ["Slow walking", "Direct eye contact", "Soft touch", "Open shirt"], 1),
	],
    'fquiz': [
    ("What's the cutest way to say good morning? ☀️", ["Good morning", "Hey you", "Morning superstar", "Hello"], 2),
    ("Best emoji to break the ice? 😉", ["😊", "😎", "😉", "😴"], 2),
    ("Most flirty way to ask someone out? 💌", ["Wanna hang?", "Free tonight?", "Coffee date?", "Sup?"], 2),
    ("Best compliment about their smile? 😁", ["Nice smile", "Love that grin", "Cute teeth", "Bright face"], 1),
    ("Ideal movie night snack? 🍿", ["Popcorn", "Nachos", "Chocolate", "Fruit"], 0),
    ("Top way to say they look amazing? ✨", ["You look nice", "Wow, stunning", "Cool outfit", "Looking good"], 1),
    ("Cutest nickname to use? 🐻", ["Buddy", "Champ", "Sunshine", "Pal"], 2),
    ("Best way to subtly touch their arm? 🤏", ["High-five", "Arm tap", "Elbow lean", "Shoulder bump"], 2),
    ("Sweetest dessert to share? 🍰", ["Ice cream", "Cupcake", "Brownie", "Apple"], 1),
    ("Ideal song dedication? 🎵", ["Happy Day", "My Heart", "Chill Vibe", "Summer Jam"], 1),
    ("Most charming way to say bye? 👋", ["See ya", "Later", "Bye-bye", "Catch you later"], 3),
    ("Best flirty GIF to send? 😘", ["Thumbs up", "Wink", "Clap", "Thinking"], 1),
    ("Cutest way to ask for a selfie? 📸", ["Send pic?", "Selfie time?", "Show me you", "Picture?"], 1),
    ("Top coffee order to impress? ☕", ["Black", "Latte", "Espresso", "Americano"], 1),
    ("Most playful text opener? 📲", ["Hey", "Yo", "Guess what", "Psst"], 2),
    ("Best way to compliment their laugh? 😂", ["Nice laugh", "Cute giggle", "Great humor", "Funny bone"], 1),
    ("Sweetest flower to send? 🌹", ["Daisy", "Rose", "Sunflower", "Tulip"], 1),
    ("Ideal weekend plan? 🌴", ["Netflix", "Beach", "Gym", "Work"], 1),
    ("Best way to say they’re special? 💖", ["Cool person", "Unique soul", "One of a kind", "Nice"], 2),
    ("Cutest emoji pairing? 🥰", ["😊😊", "😍😘", "😜😜", "🤗🤗"], 1),
    ("Most flirty question to ask? ❓", ["How are you?", "What’s up?", "Missing me?", "Busy?"], 2),
    ("Best late-night text? 🌙", ["You there?", "Miss you", "Sweet dreams", "What's up?"], 1),
    ("Top compliment for their style? 👗", ["Nice clothes", "Love your style", "Cool outfit", "Sharp look"], 1),
    ("Most inviting way to hang out? 🎉", ["Party at mine", "Netflix night", "Gym sesh", "Study group"], 1),
    ("Cutest way to say thank you? 🙏", ["Thanks!", "Appreciate it", "You’re the best", "Got it"], 2),
    ("Best flirty emoji combo? ❤️😉", ["❤️😊", "😏😏", "😉❤️", "😜💜"], 2),
    ("Sweetest midnight message? 🌌", ["You up?", "Dream of me?", "Sweet dreams", "Goodnight"], 2),
    ("Most charming first date spot? 🍽️", ["Fast food", "Cafe", "Fine dining", "Food truck"], 2),
    ("Best way to show you care? 💌", ["Call them", "Text heart", "Surprise gift", "Wave hi"], 1),
    ("Top way to boost their confidence? 🚀", ["You got this", "Try harder", "Do better", "Keep quiet"], 0),
    ("Cutest way to send hugs? 🤗", ["Air hug", "Virtual hug", "Real hug", "High-five"], 1),
    ("Best flirty nickname in chat? 🐥", ["Buddy", "Mate", "Cutie", "Pal"], 2),
    ("Most playful dare? 🎲", ["Truth", "Dance", "Sing", "Run"], 1),
    ("Ideal romantic gesture? 💐", ["Flowers", "Card", "Chocolate", "Note"], 0),
    ("Top way to compliment eyes? 👀", ["Pretty eyes", "Love your gaze", "Nice look", "Bright stare"], 1),
    ("Cutest way to ask their favorite song? 🎧", ["What song?", "Your jam?", "Turn up?", "Playlist?"], 1),
    ("Best icebreaker at party? 🥂", ["Hello", "You dance?", "Nice tune", "Cute vibe"], 1),
    ("Most flirty coffee chat topic? ☕", ["Weather", "Work", "Dreams", "Taxes"], 2),
    ("Cutest way to say you're thinking of them? 🤔", ["What's up?", "Miss your face", "Hey", "Remember me?"], 1),
    ("Most playful pet name? 🐶", ["Snugglebug", "Dude", "Chief", "Sport"], 0),
    ("Top outfit compliment? 👔", ["Looks fine", "You clean up well", "Nice pants", "Cool shirt"], 1),
    ("Sweetest message to wake up to? 🌅", ["Morning!", "Thinking of you", "Up yet?", "Wakey wakey"], 1),
    ("Best flirty comeback? 😏", ["You wish", "Maybe 😉", "Try again", "Sure thing"], 1),
    ("Cutest plan for a lazy Sunday? 🛋️", ["Laundry", "Movies and snacks", "Errands", "Brunch"], 1),
    ("Flirtiest reaction to a selfie? 📷", ["Wow!", "🔥🔥🔥", "Who dis?", "Nice one"], 1),
    ("Most fun date idea? 🎡", ["Walk", "Museum", "Amusement park", "Zoom call"], 2),
    ("Best way to make them laugh? 😂", ["Tell a joke", "Dad pun", "Dance badly", "Silent stare"], 1),
    ("Most romantic meal? 🍝", ["Pizza", "Pasta", "Burgers", "Ramen"], 1),
    ("Best time to send a flirty text? ⏰", ["9 AM", "Noon", "8 PM", "3 AM"], 2),
    ("Sweetest reply to 'I miss you'? 💭", ["Same here", "Why?", "Missed who?", "Aww, me too"], 3),
    ("Best message after a date? 💬", ["Thanks", "Good time", "Let’s do it again 😉", "Bye"], 2),
    ("Cutest way to tease someone? 😜", ["You’re silly", "You're a mess 😆", "Stop it", "Oh please"], 1),
    ("Best subtle flirty question? 🧐", ["Where are you?", "Are you single?", "Who’s texting?", "What’s new?"], 1),
    ("Flirtiest emoji to end a sentence? 🔥", ["!", "😂", "🔥", "😶"], 2),
    ("Sweetest thing to say during a walk? 🚶", ["Tired?", "Let’s hold hands", "Are we done?", "Watch your step"], 1),
    ("Cutest way to ask to hang out? 📅", ["Plans?", "What u doing?", "Wanna chill?", "You free later?"], 3),
    ("Best thing to write in a flirty note? ✍️", ["Hey", "You're cool", "Can’t stop smiling", "LOL"], 2),
    ("Most fun flirty challenge? 🕹️", ["TikTok duet", "Selfie war", "Truth or dare", "Netflix quiz"], 2),
    ("Cutest response to a compliment? 😊", ["Thanks!", "You too", "Stop 😳", "Okay"], 2),
    ("Flirtiest food to share? 🍓", ["Pizza", "Fries", "Strawberries", "Noodles"], 2),
    ("Best way to start a flirty convo? 💭", ["How are you?", "Dreamt of you", "What's up?", "New here?"], 1),
    ("Most playful compliment? 🥺", ["You're cool", "You’re a 10", "Nice vibe", "Can’t look away"], 3),
    ("Sweetest response to 'wyd?' 📲", ["Just thinking of you", "Not much", "Busy", "Nothing"], 0),
    ("Cutest way to ask for a kiss (jokingly)? 😘", ["Dare you", "Kiss me maybe?", "So... lips?", "Wanna taste?"], 1),
    ("Best compliment on their voice? 🎤", ["Nice tone", "You sound like music", "Loud lol", "So soft"], 1),
    ("Most charming compliment about their laugh? 😄", ["It’s loud", "It’s music", "It’s weird", "It’s you"], 1),
    ("Flirtiest thing to say after they wink? 😉", ["Blink again", "Gotcha", "Whoa", "Your move"], 3),
    ("Sweetest text to send at 11:11? 🕚", ["Wish you were here", "Hope you're okay", "Thinking of us", "Night night"], 0),
    ("Cutest response to 'I’m bored'? 🐣", ["Let’s fix that", "Me too", "Sleep?", "Hmm"], 0),
    ("Top response to a flirty meme? 😂", ["Haha", "LOL", "Too real", "You’re wild"], 3),
    ("Best time for a flirty call? 📞", ["Afternoon", "Late night", "Morning", "During lunch"], 1),
    ("Cutest way to say 'you're cute'? 🧡", ["You're cute", "You're adorable", "OMG, you", "Love your face"], 3),
    ("Flirtiest way to say 'I like you'? 💘", ["You're fun", "You’re trouble", "You’re something else", "I like you"], 3),
    ("Most playful reason to call them? ☎️", ["Missed your voice", "Bored", "Phone test", "Accident"], 0),
    ("Best excuse to text first? 📤", ["Needed to", "Oops wrong text 😉", "Felt like it", "Why not?"], 1),
    ("Cutest rainy day plan together? ☔", ["Movie marathon", "Go outside", "Phone call", "Sleep"], 0),
    ("Top way to compliment their eyes? 👁️", ["You have eyes", "They sparkle", "I see you", "Wow"], 1),
    ("Flirtiest song lyric to send? 🎶", ["Hello, it's me", "You belong with me", "I got my eyes on you", "I’m blue"], 2),
    ("Best way to say 'you make me smile'? 😄", ["LOL", "You're hilarious", "You light up my day", "Haha"], 2),
    ("Cutest way to say 'I miss you'? 💭", ["Miss ya", "Come back", "Where you at?", "Wish you were here"], 3),
    ("Most charming way to flirt through text? 💬", ["Nice shirt", "Your vibe is insane", "You're weird", "Cool story"], 1),
    ("Flirtiest food to cook together? 🍳", ["Pasta", "Salad", "Toast", "Cereal"], 0),
    ("Cutest way to steal their hoodie? 🧥", ["Gimme", "That’s mine now", "Looks warmer on me", "Can I try it?"], 2),
    ("Most playful thing to say after they compliment you? 😌", ["Tell me more", "Thanks", "Duh", "Oh stop"], 0),
    ("Best way to say 'you're fun'? 🎈", ["You’re cool", "You’re wild", "You’re a good time", "You're odd"], 2),
    ("Top way to flirt during a game night? 🎲", ["You're going down", "Winner gets a kiss?", "Try to beat me", "Haha, no chance"], 1),
    ("Flirtiest snack to bring to a picnic? 🧺", ["Chips", "Chocolate-dipped strawberries", "Sandwiches", "Fruit salad"], 1),
    ("Cutest way to end a convo? 🌙", ["G’night", "Sweet dreams", "Text me tomorrow", "Bye"], 1),
    ("Best compliment about their laugh lines? 😊", ["They’re cute", "They're real", "They show life", "They sparkle"], 0),
    ("Sweetest way to say 'you're amazing'? 🥇", ["You rock", "You shine", "You’re unreal", "You win"], 2),
    ("Most playful flirty emoji? 😋", ["😋", "😶", "😤", "😐"], 0),
    ("Flirtiest thing to whisper during a movie? 🎥", ["You cold?", "This reminds me of you", "I like this", "We should do this more"], 1),
    ("Best thing to say when they make you laugh? 😆", ["Stop it 😂", "You're funny", "I can’t breathe", "I hate you lol"], 2),
    ("Cutest way to say 'I'm into you'? 💓", ["You're fun", "You're my fav notification", "You're cool", "I like hanging out"], 1),
    ("Flirtiest moment to hold hands? ✋", ["During a scary scene", "While crossing street", "In public", "At home"], 0),
    ("Top late-night snack to share? 🌃", ["Cookies", "Ice cream", "Popcorn", "Cereal"], 1),
    ("Best pet name to use once you're close? 🐱", ["Lovebug", "Cutie", "Pumpkin", "Babe"], 3),
    ("Sweetest rainy text? 🌧️", ["Stay dry", "Miss you more in weather like this", "Don’t forget umbrella", "Mood"], 1),
    ("Flirtiest icebreaker in a DM? 📥", ["Hi", "Soo... you’re kinda cute", "What’s up?", "Hey stranger"], 1),
    ("Cutest unexpected compliment? 🎁", ["You’re glowing today", "Looking okay", "Not bad today", "Nice one"], 0),
    ("Best way to say 'I want to see you'? 👀", ["We should meet", "You owe me a date", "Where you hiding?", "Long time no see"], 1),
    ("Top text to make them blush? 🌹", ["You're seriously cute", "Are you real?", "You're decent", "Not bad lol"], 0),
    ("Flirtiest way to describe their eyes? 💎", ["Deep", "Hypnotic", "Cool", "Round"], 1),
    ("Most playful flirty dare? 🎯", ["Call me", "Sing to me", "Send a pic", "Say my name 3x"], 2),
    ("Cutest compliment about their voice? 🔊", ["Soothing AF", "Radio vibes", "Chill sound", "Echo-y"], 0),
    ("Best casual flirty question? ❔", ["What's your type?", "Fav food?", "You dating?", "Age?"], 0),
    ("Sweetest way to end a call? 📞", ["Bye", "Talk later", "Kisses", "Call you again"], 2),
    ("Cutest reason to send a heart emoji? ❤️", ["Because", "You’re cute", "Felt like it", "Why not"], 1),
    ("Flirtiest type of message to wake up to? ⛅", ["Good morning ❤️", "Hey", "Up?", "Don't forget me"], 0),
    ("Most fun flirty outfit accessory? 🧢", ["Hat", "Necklace", "Sunglasses", "Smile"], 3),
    ("Best way to say 'you’re hot'? 🔥", ["You're lit", "Scorching", "🔥🔥🔥", "Nice outfit"], 2),
    ("Cutest emoji to send after a compliment? 😚", ["😎", "😚", "😳", "😂"], 1),
    ("Top beach date activity? 🏖️", ["Sunbathe", "Swim", "Flirt in sand", "Build sandcastles"], 2),
    ("Best sweet treat to surprise them with? 🍪", ["Cookies", "Donuts", "Brownies", "Fruit"], 0),
    ("Flirtiest compliment about their energy? ⚡", ["You’re a vibe", "So chill", "You’re intense", "Crazy energy"], 0),
    ("Most fun flirty response to 'wyd?' 📱", ["Thinking of you", "Busy", "Staring at my screen", "None ya"], 0),
    ("Cutest excuse to text them late? 🌌", ["Just missed you", "Dream check-in", "Can’t sleep", "You up?"], 0),
    ("Sweetest way to show you care in a text? 💖", ["Call me", "Thinking of you 💭", "What’s up?", "Hey"], 1),
    ("Cutest way to flirt with just a look? 👀", ["Wink 😉", "Smile 😁", "Stare 👁️", "Nod 🙃"], 0),
    ("Most charming response to a compliment? 😌", ["Aww, stop", "You too!", "Me? Never!", "Haha thanks"], 0),
    ("Flirtiest picnic food? 🧃", ["Cheese platter", "Hot dogs", "Chips", "Granola"], 0),
    ("Best time to send a heart emoji? ⏳", ["Morning", "Lunch", "Evening", "Mid-text"], 2),
    ("Cutest playful tease? 🙃", ["Nerd", "Troublemaker 😈", "Lazy", "Goof"], 1),
    ("Flirtiest outfit color? 🎨", ["Black", "Red ❤️", "Green", "Blue"], 1),
    ("Most flirty compliment about their laugh? 😂", ["I could listen all day", "You sound like joy", "Nice one", "It’s so loud"], 0),
    ("Cutest reason to send a selfie? 🤳", ["Feeling myself", "You asked for it", "Needed attention", "Just ‘cause"], 3),
    ("Flirtiest pizza topping to suggest? 🍕", ["Pepperoni", "Heart-shaped olives", "Extra cheese", "Pineapple"], 1),
    ("Most fun pet name to use in a chat? 🐰", ["Snuggle", "Muffin", "Cutiepie", "Tiger"], 2),
    ("Best flirty response to 'wyd'? 💬", ["Waiting for your text", "Just chilling", "Thinking of you", "Nothin much"], 0),
    ("Cutest way to ask them out casually? 🍦", ["Grab coffee?", "Hang out soon?", "Ice cream date?", "Walk n talk?"], 2),
    ("Flirtiest song to send in the morning? 🎶", ["Can't Take My Eyes Off You", "Good Morning", "Sunshine", "Hello Beautiful"], 0),
    ("Most charming compliment about their hair? 💇", ["Looks soft", "Perfect every time", "Nice cut", "Good volume"], 1),
    ("Top flirty reason to send a meme? 😂", ["It’s us", "This made me think of you", "You’ll laugh", "Random"], 1),
    ("Best flirty emoji combo? 😍🔥", ["😍🔥", "😎💥", "😉😇", "😘🎯"], 0),
    ("Cutest way to say 'you make me nervous'? 😳", ["You shake my Wi-Fi", "Butterflies", "You're distracting", "Whoa 😅"], 1),
    ("Flirtiest way to describe a hug? 🤗", ["Electric", "Soft trap", "Instant smile", "Too short"], 2),
    ("Most playful way to invite them over? 🏡", ["Netflix?", "Hangout?", "Pop by 😏", "Bring snacks"], 2),
    ("Cutest flirty voice message starter? 🎙️", ["Sooo hey", "Guess who", "Hi you", "Yo"], 0),
    ("Best way to show you're thinking of them? 🧠", ["Random heart", "Throwback pic", "Text them", "Gifs"], 1),
    ("Most charming compliment for their eyes? ✨", ["Like stars", "Hypnotic", "So shiny", "Pretty"], 0),
    ("Top beach flirt move? 🏄", ["Splash them", "Lay next to them", "Put sunscreen", "Smile in shades"], 2),
    ("Best moment for a surprise text? 💌", ["After lunch", "Before sleep", "Mid-work", "Rainy day"], 1),
    ("Cutest way to suggest a date? 📍", ["Let’s vibe soon", "You + me = fun?", "Drinks?", "Plan something?"], 1),
    ("Flirtiest response to 'miss me?' 🧡", ["Always", "Who are you again?", "Maybe", "Duh"], 0),
    ("Cutest rainy-day text? ☔", ["Wanna cuddle?", "Weather’s dull without you", "Rain check?", "Feeling grey"], 1),
    ("Most charming social media move? 📸", ["Like old pic", "React to story ❤️", "Slide in DMs", "Drop a fire emoji"], 1),
    ("Best way to say 'you looked amazing today'? 😍", ["Wow", "Stunning as always", "Not bad", "Fire outfit"], 1),
    ("Flirtiest seat to choose on a date? 🪑", ["Opposite", "Next to them 😉", "Corner", "Far end"], 1),
    ("Sweetest excuse to call? 📲", ["Missed your voice", "Bored", "Needed help", "Just cuz"], 0),
    ("Most fun way to say 'you're mine'? 🐾", ["All mine 😏", "You belong to me", "Claimed 😌", "No sharing"], 0),
    ("Best movie genre for a cozy date? 🎬", ["Action", "Rom-com 💕", "Horror", "Thriller"], 1),
    ("Cutest flirty text to send at 2 AM? 💤", ["Can’t sleep", "Thinking of your smile", "Missed you", "Soo… up?"], 1),
    ("Top fun way to end a flirty chat? 🥱", ["Sweet dreams 😘", "Call me", "Chat soon", "Bye cutie"], 0),
    ("Most playful reason to send a heart? ❤️", ["No reason", "Feeling things", "You’re cute", "Saw your pic"], 1),
    ("Flirtiest compliment to give out of the blue? 🎯", ["You're unreal", "Hot stuff", "Lookin' like a snack", "Glow up!"], 0),
    ("Cutest way to say 'I want more time with you'? ⏳", ["Don’t leave", "Stay longer?", "This went fast", "Raincheck?"], 1),
    ("Flirtiest compliment about their style? 👗", ["Sharp dresser", "You always slay", "Cool", "Stylish"], 1),
    ("Sweetest way to say 'I like you a lot'? 🧡", ["You're awesome", "You're my fave", "So into you", "You're alright"], 2),
    ("Cutest pet name to drop mid-convo? 🐣", ["Boo", "Sweetpea", "Pookie", "Honeybun"], 3),
    ("Best time to send a flirty GIF? 🎞️", ["Right after a joke", "At night", "Randomly", "When they’re online"], 0),
    ("Most charming 'just because' text? 💌", ["You popped into my mind", "Hope you’re smiling", "You good?", "Sup"], 0),
    ("Flirtiest compliment about their smell? 👃", ["Addictive", "So fresh", "Nice perfume", "Smells great"], 0),
    ("Cutest way to start a video call? 📹", ["Smile check!", "Guess who", "Surprise!", "Can you hear me?"], 0),
    ("Best flirty reason to bump into them? 😇", ["Totally accidental", "You were in my area", "Needed coffee", "It was fate"], 3),
    ("Top 'miss you' message style? 📬", ["Classic 'miss u'", "Sappy song lyrics", "Old photo drop", "Heart emoji only"], 1),
    ("Cutest response to 'wyd rn?' 🕒", ["Thinking about you", "Chillin", "Guessing your next text", "Looking at the wall"], 0),
    ("Best activity for a low-key flirty date? 🧘", ["Stargazing 🌌", "Hiking", "Board games", "Bowling"], 0),
    ("Flirtiest phone wallpaper? 📱", ["Selfie of them", "Couple meme", "Inside joke", "Cute quote"], 0),
    ("Sweetest flirty text after a date? 🌟", ["I had fun 😚", "We should do that again", "You made my night", "Thanks"], 2),
    ("Most fun shared playlist name? 🎧", ["Vibe Check", "Us 🥰", "Late Night Feels", "Flirt Mode"], 3),
    ("Flirtiest message reaction? 💬", ["Heart eyes", "Fire emoji", "Laugh react", "Thumbs up"], 0),
    ("Best way to break the texting silence? 🔔", ["Miss me?", "Hey trouble", "Long time 😏", "Still alive?"], 1),
    ("Cutest thing to say when they say 'I'm bored'? 💤", ["Wanna call?", "I'm fun 😎", "Let’s do something", "Why though?"], 1),
    ("Top reason to ask for a selfie? 📸", ["I miss that face", "Need a new wallpaper", "Prove you’re real", "Just cuz"], 0),
    ("Most charming rainy date idea? 🌧️", ["Movie & cuddles", "Coffee shop chill", "Walk with umbrella", "Stay in"], 0),
    ("Best time to flirt subtly? 🕶️", ["In between jokes", "When texting at night", "While teasing", "During goodbye"], 2),
    ("Sweetest goodnight message? 🌙", ["Dream of me", "Sleep tight 😘", "G’night", "Out like a light"], 1),
    ("Flirtiest photo caption? 📷", ["Your future crush", "Mood", "Caught a vibe", "This one’s for you 😉"], 3),
    ("Cutest reason to DM first? 📲", ["Couldn't wait", "Missed your vibe", "Just had to", "Random thought"], 1),
    ("Best flirty move in a group chat? 👀", ["Inside joke drop", "Only reply to them", "Tag them in memes", "Late reply"], 2),
    ("Most playful text to wake up to? ☀️", ["Morning cutie", "Rise & flirt", "Up yet?", "Sunshine alert 🌞"], 0),
    ("Flirtiest voice note message? 🎤", ["Miss hearing you", "This is what I sound like", "Just saying hey 😏", "Guess who"], 0),
    ("Top compliment to give during a call? ☎️", ["You sound happy", "You have a great voice", "You’re glowing over audio", "This is nice"], 1),
    ("Cutest way to say 'we should hang out'? 🗓️", ["Let’s catch up soon", "Make time for me", "What’s your schedule?", "Let’s vibe"], 3),
    ("Flirtiest dessert to share? 🍰", ["Chocolate cake", "Tiramisu", "Ice cream sundae", "Strawberry shortcake"], 2),
    ("Sweetest subtle flirt in person? 😊", ["Long eye contact", "Little touches", "Cheeky jokes", "All of the above"], 3),
    ("Best emoji to end a flirty sentence? 💫", ["😏", "❤️", "😚", "✨"], 3),
    ("Cutest way to say 'I saved your message'? 💾", ["This one’s a keeper", "Screenshot vibes", "Noted 😌", "Saving that forever"], 0),
    ("Flirtiest thing to say while playing a game? 🎮", ["Loser kisses the winner", "Don't get distracted by me", "Watch out 😈", "Bet you can't win"], 0),
    ("Best way to sneak a compliment? 😎", ["You make this fun", "That shirt looks amazing", "You're really cool", "You're distracting 😉"], 3),
    ("Cutest reason to send a throwback? 📸", ["Good times", "You looked cute here", "Miss that smile", "Found this 💘"], 1),
    ("Top subtle flirt move online? 🌐", ["React to old stories", "Like their comments", "Tag in posts", "Start a random convo"], 0),
    ("Most charming thing to say after a long chat? ⏱️", ["Time flies with you", "You're easy to talk to", "That was fun", "Let’s chat again"], 0),
    ("Flirtiest way to respond to a 'hi'? 🙋", ["Hey you 😉", "Howdy", "Hi cutie", "Long time no flirt"], 2),
    ("Cutest accidental message excuse? 😅", ["Oops, meant for someone else 😏", "Or did I?", "Freudian slip?", "My bad... or not"], 1),
	],
    'lolquiz': [
    ("What’s the most powerful way to win an argument? 🧠", ["Logic", "Screaming", "Walk away", "Pretend to cry 😢"], 3),
    ("Best way to survive a zombie apocalypse? 🧟", ["Hide", "Fight", "Befriend the zombies 🤝", "Cry in corner"], 2),
    ("Funniest reason to skip work? 🏖️", ["Lost my voice", "Alien abduction 👽", "Pet emotional support", "It's Tuesday"], 1),
    ("Best use for a broken phone? 📱", ["Paperweight", "Modern art", "Throw at ex", "Soup stirrer 🥄"], 3),
    ("Most chaotic breakfast choice? 🍳", ["Cereal", "Pizza slice", "Cold fries", "Hot sauce on toast 🌶️"], 3),
    ("What’s a ninja’s favorite drink? 🥷", ["Tea", "Water", "Stealth smoothie", "Karate mocha 🥋"], 3),
    ("Best excuse for being late? 🕒", ["Time travel glitch", "Cat held me hostage 🐱", "Sleep happened", "Traffic"], 1),
    ("Why did the chicken REALLY cross the road? 🐔", ["Existential crisis", "Spicy gossip", "To escape TikTok", "To flex legs"], 0),
    ("Funniest pet name? 🐶", ["Chair", "Lord Wiggles", "Sir Poops-a-lot 💩", "Toast"], 2),
    ("Most dramatic way to say you're hungry? 🍔", ["Stomach betrayal", "Dying slowly", "Feed me or I cry", "Send food NOW 😫"], 3),
    ("Best dance move when you're losing a fight? 🕺", ["The worm", "Flop & roll", "Twerk of surrender", "Tornado twirl"], 2),
    ("Most chaotic thing to say on a first date? 🥴", ["I collect toenails", "I have 12 cats", "I see ghosts", "I Googled you 😈"], 3),
    ("Weirdest pizza topping combo? 🍕", ["Pineapple + ketchup", "Banana + mayo", "Pickles + peanut butter", "Cereal flakes"], 2),
    ("What’s the best way to make an entrance? 🚪", ["Backflip", "Fog machine", "Theme song 🎵", "Yell 'I’m here!'"], 2),
    ("What’s your evil villain origin story? 🦹", ["Ran out of coffee ☕", "Stepped on LEGO", "Lost Wi-Fi", "Denied snacks"], 1),
    ("Strangest bedtime ritual? 😴", ["Argue with mirror", "Bark at moon", "Brush teeth with soda", "Read cereal box"], 3),
    ("Funniest thing to name a Wi-Fi network? 📶", ["Pretty Fly for Wi-Fi", "Mom Click Here", "Virus.exe", " FBI Surveillance Van 🚓"], 3),
    ("Best insult with zero actual offense? 🤭", ["Bless your heart", "You tried", "Interesting choice", "Bold of you to exist"], 3),
    ("What's the ultimate power move in a pillow fight? 🛏️", ["Surprise attack", "Use blanket as shield", "Tickle distract", "Call in reinforcements"], 3),
    ("Weirdest way to say 'I love you'? ❤️", ["You're tolerable", "I’d share my fries", "You smell decent", "My favorite weirdo"], 1),
    ("Most awkward thing to do on Zoom? 💻", ["Mute yourself", "Accidentally unmute during bathroom", "Eat loudly", "Start singing"], 1),
    ("Funniest fake award to win? 🏆", ["Most likely to nap anywhere", "Best imaginary friend", "Loudest yawn", "Professional overthinker"], 0),
    ("Craziest conspiracy theory? 🧠", ["Birds work for the government 🐦", "Toasters have feelings", "The moon is a disco ball", "Your socks disappear to escape"], 0),
    ("Funniest way to break up? 💔", ["Through karaoke", "GIF-only text", "Fake my own kidnapping", "Hire a skywriter"], 2),
    ("What’s your secret superhero identity? 🦸", ["Captain Cringe", "The Snackinator", "Awkward Avenger", "Meme Lord"], 3),
    ("Best response to 'You okay?' 😬", ["I'm emotionally constipated", "No, but thanks", "Just floating", "Define okay"], 0),
    ("Worst way to end a job interview? 💼", ["Mic drop", "I’m only here for snacks", "So… do we hug?", "Call interviewer ‘bruh’"], 2),
    ("Best use for glitter? ✨", ["Mark enemies", "Emotional armor", "Confetti sneeze", "Sparkle sneeze attack"], 3),
    ("Funniest imaginary friend name? 🧸", ["Beef Wellington", "Sir Fluffington", "Uncle Tuna", "Dr. Sniffles"], 2),
    ("Worst idea for a party theme? 🎉", ["Taxes", "Sleep paralysis demons", "Broken printers", "Expired snacks"], 0),
    ("Most cursed ice cream flavor? 🍦", ["Toothpaste chunk", "Sock water swirl", "Garlic onion delight", "Pickle ripple"], 2),
    ("Funniest thing to text your crush by accident? 📱", ["Grandma’s recipe", "Bathroom selfie", "Doctor's appointment", "Googly eyes"], 1),
    ("What’s the most chaotic snack combo? 🥨", ["Chips + toothpaste", "Cookies + mustard", "Popcorn + soy sauce", "Cereal + ranch"], 3),
    ("Weirdest reason to leave a party early? 🎈", ["My cactus is lonely", "Moon’s in retrograde", "TV missed me", "Too many people breathing"], 0),
    ("Best new holiday idea? 🎄", ["National Nap Day", "Pet a Lizard Day", "International Awkward Hug Day", "Socks with Sandals Day"], 3),
    ("Funniest thing to say to a cat? 🐱", ["What’s your 401k?", "Pay rent or leave", "Explain quantum physics", "You dropped your dignity again"], 1),
    ("What’s your sleep style? 🛏️", ["Starfish", "Taco wrap 🌯", "Falling piano", "Possessed burrito"], 3),
    ("Funniest autocorrect fail? ⌨️", ["Duck off", "I’m in the oven (meant: on my way)", "Let’s meat up", "I lava you"], 1),
    ("Most dramatic snack food? 🥔", ["Popcorn (it explodes)", "Cheese (melts under pressure)", "Hot Cheetos (burn everything)", "Ice cream (melts under drama)"], 2),
    ("What’s the funniest thing to yell in public? 📢", ["I lost my eyebrows!", "Who stole my spaghetti?", "I’m a pineapple! 🍍", "All of the above"], 3),
    ("Best method to avoid responsibilities? 🛋️", ["Fake sleep", "Hide in fridge", "Change name", "Join circus 🤡"], 3),
    ("Funniest way to say you're broke? 💸", ["Financially allergic", "Wallet's on vacation", "Credit card’s ghosting me", "I’m in a committed relationship with debt"], 3),
    ("Craziest reason to return an item? 🛍️", ["It looked at me weird", "It made a noise", "It called me ugly", "It betrayed my trust"], 3),
    ("Most chaotic way to clean your room? 🧹", ["Shove it under bed", "Light a candle and pray", "Leave forever", "Declare it a nature reserve"], 3),
    ("Weirdest thing to do while brushing teeth? 🪥", ["Sing opera", "Dance like a crab", "Make eye contact with mirror", "Cry dramatically"], 2),
    ("What would you do if you saw a UFO? 🛸", ["Wave", "Ask for snacks", "Join them", "Challenge them to Uno"], 3),
    ("Funniest way to sign off an email? 📧", ["Toodles", "Stay crunchy", "Yours awkwardly", "Respectfully confused"], 2),
    ("Weirdest fashion trend we secretly need? 👘", ["Pajama suits", "Banana hats 🍌", "Shoes with snacks", "Glow-in-the-dark socks"], 2),
    ("What's your secret talent? 🎪", ["Teleporting bread", "Falling dramatically", "Laughing at bad jokes", "Existential panic"], 1),
    ("Best thing to say while tripping over nothing? 🤸", ["I was testing gravity", "Earth just pulled me", "I meant to do that", "Sneaky ghost attack"], 0),
    ("Funniest excuse for not texting back? 📲", ["Finger fell asleep", "Was talking to my plants", "Lost in thought (and IKEA)", "Accidentally joined a cult"], 3),
    ("What's the wildest alarm sound? ⏰", ["Screaming goat", "Clown horn", "Baby crying opera", "Your mom yelling your name"], 3),
    ("Weirdest school subject idea? 🏫", ["Advanced Meme Studies", "How to Avoid People 101", "Napping Theory", "Sarcasm Fluency"], 0),
    ("Most cursed cooking experiment? 🍳", ["Spaghetti smoothie", "Microwaved salad", "Toast in a washing machine", "Ice cream soup"], 0),
    ("Funniest panic reaction? 😱", ["Stand still", "Flail like a squid", "Yell 'banana!' 🍌", "Sing the national anthem"], 2),
    ("What should we ban forever? 🚫", ["Autocorrect", "Unskippable ads", "Soggy cereal", "People who say 'literally' too much"], 1),
    ("Most dramatic way to enter a room? 🚪", ["Slide in socks", "Kick door open", "Cartwheel in", "With background music 🎶"], 3),
    ("Funniest thing to say to a stranger? 🧍", ["Do you smell toast?", "Have you seen my invisible dog?", "Are you my destiny?", "Nice elbows 👍"], 3),
    ("Worst time for your phone to ring? 📵", ["At a funeral", "During hide-and-seek", "Mid-movie jump scare", "In a ninja mission"], 0),
    ("What’s the strangest way to flirt? 😏", ["Speak only in riddles", "Show them your rock collection", "Name a sandwich after them", "Morse code blinking"], 2),
    ("Best reason to run out of a date? 🏃", ["Forgot I’m allergic to eye contact", "Realized I left the oven on in 2014", "He asked to share fries 😤", "She called me bro"], 3),
    ("Funniest prank call line? ☎️", ["Is your refrigerator running?", "Do you accept emotional baggage?", "Is this Krusty Krab?", "Want to hear my mixtape?"], 1),
    ("What’s your superhero sidekick’s name? 🦸‍♂️", ["Captain Clumsy", "The Flying Burrito 🌯", "Sir Awkward", "Moody McMeme"], 1),
    ("Weirdest secret habit? 🤫", ["Talk to furniture", "Name your food", "Practice arguments in the shower", "Stare into fridge for answers"], 3),
    ("Funniest sneeze sound? 🤧", ["Achoop!", "KABLOOM!", "Snarfle!", "Moo 🐮"], 3),
    ("Weirdest Wi-Fi password ever? 🔐", ["ILoveToes", "BananaBreadOverlord", "NoOneKnows", "PickleParty2020"], 1),
    ("Best fake profession to use at parties? 🥳", ["Lawn whisperer", "Professional hug tester", "Space spoon designer", "Freelance vampire"], 2),
    ("Funniest way to say 'I'm tired'? 🛌", ["My soul left", "Energy on vacation", "Powered by yawns", "Brain.exe not found"], 3),
    ("What would you name a pet goldfish? 🐟", ["Chairman Bubbles", "Wet Wiggle", "Noodle", "CEO of Water"], 3),
    ("Best chaotic life advice? 🤪", ["Eat dessert first", "Name your plants", "Marry a raccoon", "Run only when chased"], 2),
    ("Most awkward ringtone in public? 📱", ["Baby shark", "Evil laugh", "Cow mooing", "Screaming goat"], 3),
    ("Weirdest way to quit a job? 💼", ["Slam a rubber chicken down", "Email a meme", "Do a musical number", "Just ghost them 👻"], 2),
    ("Funniest name for a new planet? 🪐", ["Fartonia", "Snacktopolis", "Yeetopia", "Bing Bong Zorp"], 3),
    ("Weirdest thing to dream about? 🌙", ["Fighting spaghetti", "Dating a pineapple", "Becoming a sock", "Being eaten by a sandwich"], 2),
    ("Funniest thing to say after burping? 🍺", ["Thank you", "Nature is healing", "I bless myself", "That was the ghost"], 3),
    ("What would your autobiography be called? 📘", ["Oops: A Life", "Chronicles of Awkward", "Still Loading", "The Snack Saga"], 2),
    ("What would you name your imaginary island? 🏝️", ["Chilladelphia", "Sleepyland", "TacoTopia", "Moody Banana Cove"], 3),
    ("Best way to survive a boring meeting? 👔", ["Doodle dragons", "Count blinks", "Silently scream", "Pretend you're on a cooking show"], 3),
    ("Funniest way to respond to 'How are you?' 😐", ["Emotionally scrambled", "Alive-ish", "Running on snacks", "404: Feelings Not Found"], 3),
    ("Most chaotic grocery list? 🛒", ["Bananas, glitter, a single sock", "Cheese, drama, patience", "Milk, shovel, duck tape", "Soap, sword, gummy bears"], 2),
    ("Weirdest talent to show on a talent show? 🎤", ["Sneeze on command", "Recite cereal slogans", "Interpretive dance of taxes", "Make toast with thoughts"], 3),
    ("Best thing to yell at a haunted house? 👻", ["Do your worst!", "Pay rent, ghost!", "I’m emotionally unavailable!", "Casper, is that you?"], 1),
    ("Worst time to get hiccups? 😳", ["During wedding vows", "Sneaking around", "Giving a TED talk", "In a staring contest"], 0),
    ("Weirdest sport to invent? 🏑", ["Underwater chess", "Extreme ironing", "Pillow jousting", "Slipper dodgeball"], 3),
    ("Funniest group chat name? 📱", ["Cereal Killers", "The Meme Team", "404 Brain Not Found", "Oops We Typed Again"], 2),
    ("Most cursed cooking show name? 📺", ["Cooking with Chaos", "Whisk Takers", "Grill or Be Grilled", "Burnt to a Crisp"], 3),
    ("Weirdest thing to name a child? 👶", ["Lamp", "Banana", "Exclamation Mark", "PowerPoint"], 3),
    ("Funniest fake disease? 🦠", ["Chronic nap disorder", "Snack deficiency", "Hyper-cringe syndrome", "Can't-Even-itis"], 3),
    ("Best prank gift idea? 🎁", ["Box of air", "Screaming potato", "Glitter explosion", "Calendar of awkward faces"], 2),
    ("Strangest ringtone to wake up to? 🔊", ["Opera squirrel", "Yelling 'WAKE UP!'", "Angry ducks", "Your boss screaming"], 2),
    ("Most unhelpful app idea? 📲", ["How to forget things", "Mood translator for furniture", "Flirt translator (broken)", "Find socks (beta only)"], 1),
    ("Best fake language? 🗣️", ["Borkish", "Blahblahese", "Yawnish", "Emoji-only 🐸🍕✨"], 3),
    ("Worst name for a perfume? 🌸", ["Eau de Gym", "Desperation Mist", "Sweaty Elegance", "Mystery Odor"], 2),
    ("Funniest wrong lyrics ever sung? 🎶", ["Hold me closer, Tony Danza", "Sweet dreams are made of cheese", "I can pee your hero, baby", "There's a wiener in the sky"], 1),
    ("What would you name a pet rock? 🪨", ["Stony Stark", "Rocky Balboa", "Pebbleton", "Sir Crumbles-a-lot"], 3),
    ("What’s the weirdest phobia ever? 😱", ["Fear of buttons", "Fear of ducks watching you", "Fear of long words", "Fear of peanut butter sticking to the roof of your mouth"], 1),
    ("Best imaginary job title? 🧑‍💼", ["Professional Overthinker", "Snack Strategist", "Meme Curator", "Chief Awkward Officer"], 3),
    ("Strangest phone wallpaper? 🖼️", ["Toaster selfie", "Goat in a suit", "My foot", "Random barcodes"], 2),
    ("Best sound effect when confused? 🤔", ["Boing!", "Meep?", "Cluck?", "Windows error noise"], 3),
    ("Funniest superhero weakness? 🦸‍♀️", ["Tickles", "Mild inconvenience", "Tangled headphones", "Wet socks"], 3),
    ("Funniest insult from a kid? 👶", ["You're not invited to my birthday", "You smell like cheese", "You're weird", "You're a butt-nugget"], 3),
    ("Best use of a pool noodle? 🏊", ["Jousting", "DIY antenna", "Mood sword", "Pillow substitute"], 2),
    ("Weirdest dream job ever? 💤", ["Toothpaste taste tester", "Penguin therapist", "Sandwich critic", "Professional hide-and-seeker"], 3),
    ("Funniest pet peeve? 🐾", ["Loud blinking", "People breathing too loud", "Alphabet out of order", "Chewing air"], 1),
    ("Most dramatic way to quit a group chat? 📤", ["Smoke bomb exit", "Just leave", "Type 'I must go... my planet needs me'", "Send 99 crying emojis"], 2),
    ("Best reaction to a magic trick? 🎩", ["Yell 'WITCH!'", "Scream and run", "Cry softly", "Start clapping aggressively"], 0),
    ("Weirdest song title idea? 🎼", ["Dancing With My Lint", "Ode to Cereal", "My Sock Ran Away", "Banana Heartbeat"], 0),
    ("Worst thing to say at a wedding? 💒", ["So… who’s next?", "Didn't think they’d last", "I object... just kidding", "Nice dress… for a ghost"], 2),
    ("Funniest way to answer the phone? 📞", ["Talk to me, goose", "State your business", "You're live on air!", "Whatchu want?"], 0),
    ("Weirdest vending machine ever? 🥤", ["Dispenses socks", "Only gives ketchup", "Random advice", "Angry cat figurines"], 3),
    ("Best fake excuse for not working out? 🏋️", ["Gym was haunted", "Shoes betrayed me", "Allergic to effort", "Muscles called in sick"], 2),
    ("Worst bedtime story ever? 📚", ["The Man Who Forgot He Was Boring", "Little Sleepy Steve", "The Day Nothing Happened", "The Snore King Returns"], 2),
    ("Funniest fortune cookie message? 🥠", ["You will trip soon", "Nice try, human", "Your cat is judging you", "Oops, wrong cookie"], 3),
    ("Best awkward silence filler? 😶", ["So… potatoes?", "Ever sneeze in a dream?", "What’s your third favorite toe?", "I like turtles"], 2),
    ("Weirdest birthday wish? 🎂", ["May your socks stay dry", "Don’t get eaten by seagulls", "Avoid mysterious cheese", "Live long and awkward"], 3),
    ("Most cursed object in your house? 🧸", ["Talking blender", "Possessed fridge light", "That one chair", "Mismatched Tupperware lids"], 3),
    ("Funniest item to bring to a desert island? 🏝️", ["Saxophone", "Bubble wrap", "Glow stick", "Couch"], 1),
    ("Funniest way to say 'I'm lost'? 🧭", ["Where the map at?", "I’m geographically confused", "I’m in the Bermuda backyard", "Where even is here?"], 2),
    ("What’s the worst thing to find in your sandwich? 🥪", ["A sock", "Another sandwich", "A breakup note", "Your ex’s name written in mustard"], 3),
    ("Funniest way to introduce yourself? 🙋", ["I’m a human, mostly", "I cry at commercials", "I’m legally required to be here", "Call me... maybe"], 2),
    ("Best unexpected talent? 🎯", ["Speed folding napkins", "Fluent in duck", "Can sneeze in Morse code", "Making cereal cry"], 2),
    ("Worst autocorrect fail? 📱", ["'I'm ducking mad!'", "'Let's meat at 6'", "'I lava you'", "'I'm outside your horse'"], 3),
    ("Best fake reality show idea? 📺", ["Survivor: IKEA", "America’s Next Top Noodle", "Keeping Up with the Lizards", "Bake It Till You Make It"], 0),
    ("What’s a terrible tattoo idea? 🖊️", ["Mom spelled wrong", "Wi-Fi password", "Your old MySpace handle", "A potato with sunglasses"], 3),
    ("Most dramatic way to eat chips? 🥔", ["With opera music", "By candlelight", "Wearing gloves", "Crying slowly"], 0),
    ("Weirdest thing to keep in your wallet? 💳", ["Glitter", "Mini sandwich", "Emergency crayon", "A picture of a stranger"], 3),
    ("Best way to end a conversation? 🗨️", ["Smoke bomb exit", "Sneeze and run", "Say 'To be continued…'", "Pretend you're buffering"], 3),
    ("Funniest thing to say when late? ⏰", ["Time is a social construct", "Traffic was emotional", "I had a vibe emergency", "I was abducted by vibes"], 2),
    ("What’s a bad thing to say on a date? 💔", ["You remind me of my dentist", "My ex loved that too!", "This feels like jury duty", "Do you like cheese? A lot?"], 2),
    ("Weirdest emoji combo? 😬", ["🦄🍞🚀", "🥒👑💤", "🐸📞🧼", "💡👀🥶"], 0),
    ("Best band name idea? 🎸", ["Panic At The Laundry", "Flaming Tacos", "Couch Potatoes United", "Cringe Symphony"], 0),
    ("What would you name a spaghetti superhero? 🍝", ["Noodlena", "Pasta Puncher", "The Meatball Avenger", "Sir Sauce-a-lot"], 3),
    ("What should be illegal but isn’t? 🚔", ["Clapping when the plane lands", "Group texts", "Replying all", "Using speakerphone in public"], 3),
    ("Worst movie sequel idea? 🎬", ["Titanic 2: Still Floating", "The Notebook: Spiral Bound", "Fast & Curious", "Frozen 3: Lukewarm"], 1),
    ("Funniest wrong turn GPS instruction? 🗺️", ["Turn left into your regrets", "Recalculating… your life choices", "In 500 ft, cry", "At the next light, become a bird"], 1),
    ("What’s a hilarious alarm label? ⏰", ["Wake up or else", "Time to panic", "You slept through life", "Do NOT snooze this"], 2),
    ("Worst thing to yell at karaoke? 🎤", ["I FORGOT THE WORDS", "Is this the remix?", "Help me!", "Call 911! (jk)"], 0),
    ("Weirdest gym workout? 🏋️", ["Angry walking", "Staring contest with dumbbells", "Emotional lunges", "Treadmill karaoke"], 2),
    ("Most cursed holiday tradition? 🎄", ["Tofu snowmen", "Family argument speedrun", "Singing to houseplants", "Wrapping air"], 1),
    ("Funniest Wi-Fi name? 📶", ["TellMyWiFiLoveHer", "DropItLikeItsHotspot", "MomGetOffTheInternet", "404SignalNotFound"], 3),
    ("Worst time to sneeze? 🤧", ["While proposing", "Mid-jump", "In hide and seek", "During a group selfie"], 0),
    ("Funniest spell a wizard could cast? 🧙", ["Summon extra fries", "Make socks disappear", "Turn enemies into spreadsheets", "Confusion blast"], 2),
    ("Weirdest item on a dating profile? 💘", ["Certified napper", "Owns 42 hats", "Talks to spoons", "Fluent in sarcasm"], 2),
    ("Funniest excuse to leave a party? 🎉", ["My couch misses me", "I forgot to feed my cactus", "My left sock feels weird", "Netflix sent me a sign"], 1),
    ("Best use of bubble wrap? 📦", ["Dance floor", "Stress pillow", "Soundproof hat", "DIY trampoline"], 0),
    ("Worst cooking disaster? 🔥", ["Microwaved soup explosion", "Burnt water", "Frozen toast", "Instant noodles… caught fire"], 1),
    ("Funniest job rejection reason? 📄", ["Too awesome", "You intimidate the office plant", "Laugh too loud", "Keyboard vibes off"], 2),
    ("Silliest family heirloom? 🏺", ["Ancient spoon of confusion", "Haunted hairbrush", "Mysterious sock", "A VHS labeled 'DO NOT WATCH'"], 3),
    ("Most awkward Zoom moment? 💻", ["Mic on, brain off", "Pet invades camera", "Talking to a muted room", "Accidentally sharing memes"], 1),
    ("Funniest horror movie title? 👹", ["Attack of the Sporks", "The Couch That Watched", "Don’t Eat That!", "Grandma's Haunted Lasagna"], 3),
    ("Best awkward elevator moment? 🛗", ["Staring contest", "Humming the Jeopardy theme", "Pressed all buttons", "Accidental group therapy"], 2),
    ("Funniest app notification? 📲", ["Time to drink water and mind your business", "You up? Your goals are", "Still single?", "Delete something, fatty!"], 0),
    ("Weirdest thing to put in a smoothie? 🥤", ["Popcorn", "Pickles", "French fries", "Socks (clean?)"], 1),
    ("What should you never Google at 3 AM? 🌙", ["Do cats know I'm sad?", "Are ghosts single?", "Can cereal hear me?", "Why do I exist?"], 2),
    ("Best fake emergency? 🚨", ["Running out of cheese", "Too many open tabs", "Bad hair day", "Allergic to boring people"], 1),
    ("Funniest replacement for 'hello'? 👋", ["Greetings, carbon unit", "What up, buttercup?", "Yo spaghetti-o", "It's-a me, awkward-o!"], 3),
    ("Worst thing to say before skydiving? 🪂", ["Wait, how does this work?", "I thought this was yoga!", "Is that duct tape?", "Y’all ever regret stuff?"], 0),
    ("Funniest reason to run? 🏃", ["Saw a bee", "Accidentally hit 'Reply All'", "Pizza in danger", "Existential panic"], 1),
    ("Weirdest thing to find in your fridge? 🧊", ["A wig", "Sunglasses", "Toy car", "Uncooked ideas"], 3),
    ("Best fake award to win? 🏆", ["Best Couch Potato", "Most Confused in a Group Chat", "Fastest to Forget Passwords", "World’s Okayest Human"], 3),
    ("Funniest way to quit your job? 📝", ["Left a meme as a resignation letter", "Balloons spelling BYE", "Zoom meeting fade out", "Trained a raccoon to replace you"], 3),
    ("Silliest sports team name? 🏈", ["The Snaccidents", "Crying Burritos", "Sweaty Unicorns", "Waffle Stompers"], 2),
    ("Worst text to send your boss? 💬", ["I think I quit?", "You're not the boss of me!", "Accidentally sent memes", "U up?"], 3),
    ("Weirdest flavor idea? 🍦", ["Toothpaste taco", "Sadness sprinkle", "Soap & onion", "Mystery Tuesday"], 3),
    ("Best fake crime show title? 🕵️", ["CSI: Snack Division", "Law & Order: Pet Unit", "NCIS: Backyard", "Crimes of the Couch"], 0),
    ("Funniest out-of-office message? 🏖️", ["Gone to find myself (probably at Taco Bell)", "Currently avoiding responsibilities", "On vacation, please don’t", "Talk to the fridge instead"], 1),
    ("Best name for a goldfish? 🐟", ["Sharkbait", "Mr. Bubbles", "Sir Swims-a-lot", "Orange Water Dog"], 3),
    ("Worst advice from a fortune teller? 🔮", ["Invest in lettuce", "Avoid Tuesdays forever", "Marry a snack", "Dance during exams"], 0),
    ("Silliest thing to collect? 📦", ["Empty soap bottles", "Leftover air", "Used joke napkins", "Compliments you didn't say out loud"], 2),
    ("Funniest cooking show twist? 🍳", ["Cook blindfolded", "Swap dishes halfway", "Only use spoons", "Narrated by cats"], 3),
    ("Worst wedding DJ move? 🎧", ["Playing 'Let It Go' on loop", "Slow dancing to heavy metal", "Accidentally hits airhorn", "Rickrolling grandma"], 3),
    ("Funniest thing to say in an elevator full of strangers? 🛗", ["So, we meet again...", "I see you've chosen the lift of destiny", "Anyone wanna hear my rap?", "I licked the buttons"], 3),
    ("Strangest social media challenge? 📸", ["Duct tape fashion", "Sleep-posting", "Laugh without smiling", "Dance like you're buffering"], 3),
    ("Most awkward pet name to yell in public? 🐶", ["Mr. Fluffbutt", "PeePee", "Lord Barkington", "Tootsie Von Sniff"], 1),
    ("Funniest insult that’s actually a compliment? 😏", ["You’re weird. I like it.", "You look like a meme", "You’re the human version of Wi-Fi", "You’re suspiciously decent"], 2),
    ("Worst job interview response? 💼", ["Strengths? I nap like a champ.", "I panic professionally.", "I once fed 7 cats by mistake.", "I'm just here for snacks"], 3),
    ("Funniest karaoke song choice? 🎤", ["Baby Shark remix", "Alphabet rap", "National anthem in pig Latin", "Silent performance"], 3),
    ("What would you name a talking blender? 🥤", ["Whirly", "Blendjamin", "Sir Mix-a-Lot", "Captain Purée"], 2),
    ("Most cursed phone wallpaper? 📱", ["Zoomed-in armpit", "Screenshot of low battery", "Your own nose", "A sock selfie"], 3),
    ("Worst way to start a TED Talk? 🎙️", ["I have no idea why I'm here", "Oops wrong stage", "Let’s cry together", "So… cats, right?"], 0),
    ("Silliest conspiracy theory? 🧠", ["Birds charge on power lines", "The moon is shy", "Cows invented jazz", "Toasters are spies"], 3),
    ("Weirdest baby product idea? 👶", ["Sleep-tracking diapers", "Bluetooth pacifier", "Crib with Wi-Fi", "Mood-sensing onesie"], 3),
    ("Funniest elevator music remix? 🎵", ["Trap Beethoven", "Lo-fi cow sounds", "Screamo Mozart", "Elevator Polka Battle"], 1),
    ("Worst bedtime routine? 🛌", ["Scroll into existential dread", "Scream into pillow", "Dance it out", "Call grandma at 2 AM"], 3),
    ("Weirdest ringtone? 🔔", ["Sneeze loop", "Cat meowing math", "Random compliments", "Grandpa yelling 'Pick up!'"], 3),
    ("Most bizarre world record? 🏅", ["Fastest sock folding", "Longest dramatic gasp", "Loudest whisper", "Most consecutive fake yawns"], 3),
    ("What would you name a grumpy cactus? 🌵", ["Prickleton", "Nope", "Spikey Mike", "Moodplant"], 1),
    ("Worst time to realize your mic is on? 🎧", ["During bathroom break", "Talking to your plant", "Muttering regrets", "Singing about nachos"], 3),
    ("Funniest Zoom background? 🖼️", ["Toilet paper throne", "Alien abduction", "Historical reenactment", "Inside a burrito"], 3),
    ("Best insult from a grandma? 👵", ["You're special... like my old curtains", "You dress like Tuesday", "You're loud and shiny", "You remind me of mystery meat"], 0),
    ("Strangest fear? 😨", ["Toes watching you", "The wind knowing your secrets", "Elevators that judge you", "Getting haunted by autocorrect"], 3),
    ("Silliest secret identity? 🕶️", ["Captain Procrastination", "The Invisible Napper", "Banana Avenger", "Mildly Confused Man"], 2),
    ("Worst name for a pet snake? 🐍", ["Hiss-teria", "Noodle", "Snaccident", "Cuddles"], 3),
    ("Funniest reason to cry? 😭", ["Dropped my sandwich", "Too many tabs open", "My cereal smiled at me", "My sock betrayed me"], 3),
    ("Most awkward icebreaker? 🧊", ["Ever sneeze with your eyes open?", "What's your 17th favorite smell?", "Do you dream in fonts?", "Let’s talk about elbows"], 3),
    ("Best way to exit a boring meeting? 🚪", ["Smoke bomb!", "Cough 'bye' and vanish", "Pretend to freeze", "Slide away slowly"], 2),
	],
    'cquiz': [
    ("Which streamer is famous for yelling “RARRR!” during intense moments? 🎮", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 1),
    ("Who hosts the “Ultimate Tag” YouTube challenge? 🏷️", ["IShowSpeed", "CarryMinati", "MrBeast", "Kai Cenat"], 2),
    ("Which YouTuber is known for roasting videos in Hindi? 🔥", ["MrBeast", "Kai Cenat", "CarryMinati", "IShowSpeed"], 2),
    ("What meme features an over-muscled man flexing with the caption “Chad”? 💪", ["Beta", "Gamma", "Gigachad", "Sigma"], 2),
    ("“Mewing” refers to correct positioning of which body part? 😬", ["Fingers", "Tongue", "Eyebrows", "Elbow"], 1),
    ("Which meme depicts a dog calmly sitting in a burning room saying “This is fine”? 🔥🐶", ["Doge", "Shiba", "This is fine", "Hide the Pain Harold"], 2),
    ("Who started the “Reacting to my old videos” trend? 🎥", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 0),
    ("The “Diddy Party” meme originated from which platform? 🕺", ["Twitter", "Instagram", "TikTok", "YouTube"], 2),
    ("Which meme stock joke features a chart and the word “Stonks”? 📈", ["Bulls", "Stonks", "Bears", "Banks"], 1),
    ("Who challenged fans to find “$10,000 gold coin” on the ocean floor? 🌊", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which YouTuber’s catchphrase is “Speed, what’s going on?” 🚀", ["Kai Cenat", "IShowSpeed", "MrBeast", "CarryMinati"], 1),
    ("The “Sigma Male” meme promotes what attitude? 🧘", ["Zero-effort", "Confident solitude", "Pack mentality", "Obsession"], 1),
    ("Which meme shows a distracted boyfriend looking at another girl? 👀", ["Epic Handshake", "Distracted Boyfriend", "Two Buttons", "Is This a Pigeon?"], 1),
    ("Who once ate a $40,000 Golden Ice Cream? 🍦", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("“Hide the Pain Harold” is known for which expression? 😐", ["Pure joy", "Wincing smile", "Angry glare", "Surprise"], 1),
    ("Which challenge involved people flipping water bottles to land upright? 🍼", ["Cinnamon", "Ice Bucket", "Bottle Flip", "Mannequin"], 2),
    ("Who popularized the phrase “I don’t cook” during a roast? 🍳", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 0),
    ("The “Is this a pigeon?” meme is from which genre? 🦋", ["Anime", "Western", "Cartoon", "Documentary"], 0),
    ("Who teamed up with Elon Musk to plant trees? 🌳", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which Ariana Grande meme says “Thank you, next”? 🎶", ["7 Rings", "Thank U, Next", "Positions", "Dangerous Woman"], 1),
    ("Which meme features a businessman slapping a red button? 🔴", ["Two Buttons", "Button Slap", "Choice Meme", "Press Here"], 0),
    ("Which YouTuber’s face turns bright red when excited? 🔴", ["IShowSpeed", "Kai Cenat", "CarryMinati", "MrBeast"], 0),
    ("“All your base are belong to us” originated from which medium? 💻", ["Manga", "Video Game", "Anime", "Movie"], 1),
    ("Which TikTok dance is known as the “Renegade”? 💃", ["Savage", "Renegade", "Git Up", "Woah"], 1),
    ("Who once donated $100,000 to small Twitch streamers? 💸", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme animal says “wow so amaze”? 🐕", ["Doge", "Grumpy Cat", "Nyan Cat", "Keyboard Cat"], 0),
    ("“Coffin Dance” features pallbearers dancing from which country? ⚰️", ["Ghana", "Nigeria", "USA", "UK"], 0),
    ("Which YouTuber held a $1,000,000 hide-and-seek game? 🕵️", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme features a man at a crossroads choosing two paths? 🛣️", ["Two Buttons", "Crossroads", "Fork in Road", "Choice Paradise"], 1),
    ("What is the main color of the ‘Drake Hotline Bling’ first panel? 📞", ["Blue", "Yellow", "Orange", "Pink"], 1),
    ("Who is known for the nickname “Speed” on Twitch? 🏎️", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 1),
    ("Which viral song asks “Do you want to build a snowman?” ❄️", ["Frozen Theme", "Let It Go", "Under the Sea", "The Climb"], 0),
    ("“Charlie bit my finger” features siblings from which country? 👶", ["USA", "UK", "Canada", "Australia"], 1),
    ("Which meme features a man angrily stating “It’s over 9000!”? 🔋", ["Dragon Ball Z", "One Punch Man", "Naruto", "Bleach"], 0),
    ("Who joked “I’m not a businessman, I’m a business, man”? 💼", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme shows Keanu Reeves sitting alone on a bench? 🪑", ["Sad Keanu", "Lonely Reeves", "Bench Boy", "Reeves Mood"], 0),
    ("What color is the light saber in “Nyan Cat”? 🌈", ["Red", "Green", "Rainbow", "Blue"], 2),
    ("Which challenge had people eating spoonfuls of cinnamon? 🥄", ["Cinnamon Challenge", "Salt Bae", "Ice Bucket", "Bottle Flip"], 0),
    ("Which YouTuber is nicknamed “Beast Philanthropist”? 🎁", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme uses a two-panel Drake approving/disapproving format? 🔄", ["Two Buttons", "Drake Hotline Bling", "Distracted Boyfriend", "Expanding Brain"], 1),
    ("Who famously did a 24-hour live stream on Twitch? ⏰", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 2),
    ("“Gangnam Style” was popularized by which artist? 🕺", ["PSY", "BTS", "Justin Bieber", "Bruno Mars"], 0),
    ("Which meme features a stock photo man giving a thumbs up? 👍", ["Success Kid", "Stock Guy", "Hide the Pain Harold", "Dandy Dog"], 2),
    ("Who once bought every billboard in Times Square? 🏙️", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("What does SIGMA stand for in ‘Sigma Male’? 🚹", ["Self-interest Gains Might Achieve", "Solo, Independent, Great, Masculine, Alpha", "Silent, Independent, Groundbreaking, Mystic, Alpha", "It’s not an acronym"], 3),
    ("Which meme is literally a flying Pop-Tart cat leaving a rainbow trail? 🌈", ["Grumpy Cat", "Nyan Cat", "Doge", "Lil Bub"], 1),
    ("Who roasted Pakistani news anchors in a viral video? 📺", ["MrBeast", "CarryMinati", "Kai Cenat", "IShowSpeed"], 1),
    ("“Tide Pod Challenge” involved eating what? 🧼", ["Soap Pods", "Candy", "Chips", "Ice"], 0),
    ("Which meme shows two superheroes fist-bumping? 🦸", ["Epic Handshake", "Super Bros", "Hero High-Five", "Power Duo"], 0),
    ("Which YouTuber often says “Bro, bro, bro!” on stream? 🎙️", ["Kai Cenat", "IShowSpeed", "MrBeast", "CarryMinati"], 1),
    ("What fruit is used in the “Fruit Ninja” meme? 🍉", ["Apple", "Banana", "Watermelon", "Grapes"], 2),
    ("Which viral video starts with “Hi, welcome to Chili’s”? 🍽️", ["Chili’s Intro", "Subway Clip", "McDonald’s Ad", "Burger King Spot"], 0),
    ("Which meme girl carries a huge stack of books? 📚", ["Schoolgirl Wojak", "Book Smuggler", "Study Hard", "Nerd Girl"], 0),
    ("“Storm Area 51” was a plan to “see them” in which year? 👽", ["2015", "2018", "2019", "2020"], 2),
    ("Which YouTuber did the ‘Last to Leave Circle’ challenge? 🔵", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 1),
    ("Which meme is based on a grinning elderly man? 😊", ["Hide the Pain Harold", "Serious Harold", "Meme Grandpa", "Happy Harold"], 0),
    ("What social app popularized the ‘Savage’ dance? 🎵", ["Instagram", "YouTube", "TikTok", "Facebook"], 2),
    ("Who created the “$1 Pizza” donation campaign? 🍕", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme features a close-up of a surprised Pikachu? 😲", ["Shocked Pikachu", "Surprised Pokemon", "Wowchu", "Pika Shock"], 0),
    ("Who once paid fans’ rent for a month? 🏠", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme depicts a businessman reaching for money on a conveyor belt? 💰", ["Stonks", "Money Grab", "Rich Business", "Cash Flow"], 0),
    ("Which YouTuber’s real name is Darren Watkins Jr.? 🏎️", ["IShowSpeed", "Kai Cenat", "CarryMinati", "MrBeast"], 0),
    ("The “Mannequin Challenge” required people to… freeze in place. 🧍", ["Run", "Dance", "Freeze", "Sing"], 2),
    ("Which meme shows an expanding brain to illustrate ideas? 🧠", ["Expanding Brain", "Big Brain", "Brainstorm", "Mind Blown"], 0),
    ("Who shouted “POV: You’re broke” in a viral clip? 💸", ["CarryMinati", "IShowSpeed", "MrBeast", "Kai Cenat"], 1),
    ("Which viral dance move involves swinging your hips like a rope? 🪢", ["Renegade", "Woah", "Git Up", "Floss"], 3),
    ("Which meme pictures a frog with a humanoid body and sad eyes? 🐸", ["Pepe the Frog", "Kermit", "Frogman", "Sad Frog"], 0),
    ("Who hosted a $250,000 game of musical chairs? 💺", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme features a guy saying “Why you always lying?” 🎤", ["Lying Song", "Why You Always Lying", "Fake Falls", "Honesty Mic"], 1),
    ("Which challenge had people dumping ice water on their heads? ❄️", ["Ice Bucket", "Cinnamon", "Bottle Flip", "Hot Pepper"], 0),
    ("Which YouTuber’s fanbase is called “Beast Nation”? 🌐", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme is a cartoon doge in an Italian café? ☕", ["Italian Doge", "Café Shiba", "Espresso Pup", "Doge Latte"], 0),
    ("What year did the CarryMinati vs TikTok roast war happen? 📱", ["2017", "2019", "2020", "2021"], 2),
    ("Which viral trend involved people walking backward in public? 🔙", ["Backwards Walk", "Reverse Challenge", "Rewind", "Stroll Back"], 1),
    ("Which meme features a cat wearing a tie and speaking? 🐱", ["Business Cat", "CEO Cat", "Tie Cat", "Office Kitty"], 0),
    ("Who once made a hidden cash giveaway in real life? 💵", ["IShowSpeed", "MrBeast", "Kai Cenat", "CarryMinati"], 1),
    ("The “Floss” dance was popularized by which game? 🎮", ["Fortnite", "Minecraft", "Roblox", "Among Us"], 0),
    ("Which YouTuber is known for extreme eating challenges? 🍔", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("The “Distracted Boyfriend” meme originated in which country? 🇪🇸", ["USA", "Spain", "France", "Italy"], 1),
    ("Which meme features a waving man labeled ‘I should buy a boat’? 🚤", ["Should I Start a Yacht?", "Decision Dog", "Buy a Boat Dog", "Stonks Doge"], 2),
    ("Who frequently uses the phrase “Let’s goooo!” on stream? 🎉", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 1),
    ("Which viral song’s lyrics go “Milkshake brings all the boys to the yard”? 🥤", ["Milkshake", "Lollipop", "Juice", "Waterfalls"], 0),
    ("Which meme shows two wolves howling at a dog? 🐺", ["Surprised Wolf", "Dog vs Wolves", "Alpha Wolf", "Pack Attack"], 0),
    ("What is CarryMinati’s nationality? 🌏", ["Pakistani", "Indian", "Bangladeshi", "Nepalese"], 1),
    ("Which challenge had people eating ghost peppers? 🌶️", ["Ghost Pepper", "Ice Bucket", "Cinnamon", "Tide Pod"], 0),
    ("Which YouTuber threw a $100,000 party on stream? 🎊", ["Kai Cenat", "IShowSpeed", "MrBeast", "CarryMinati"], 0),
    ("Which meme begins with ‘One does not simply…’? 🚶", ["One does not simply", "Nobody expects", "Brace yourselves", "In a world"], 0),
    ("Who coined the term “Bro code”? 📜", ["IShowSpeed", "CarryMinati", "MrBeast", "Kai Cenat"], 2),
    ("Which meme features Kermit sipping tea saying ‘But that’s none of my business’? 🫖", ["Tea Frog", "Kermit Tea", "But That’s None Of My Business", "Savage Kermit"], 2),
    ("Which YouTuber’s real name is Jimmy Donaldson? 📛", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("“How do you do, fellow kids?” comes from which show? 🏫", ["The Simpsons", "30 Rock", "Friends", "Community"], 1),
    ("Which dance move looks like swinging arms side-to-side? 🕺", ["Floss", "Woah", "Renegade", "Git Up"], 0),
    ("Who made the “$1 House” giveaway video? 🏠", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme shows a caveman hitting a computer? 💻", ["Surprised Pikachu", "Caveman Spongebob", "Caveman Computer", "First World Problems"], 2),
    ("Which streamer is known for the ‘Speed Draw’ livestreams? ✍️", ["IShowSpeed", "Kai Cenat", "MrBeast", "CarryMinati"], 0),
    ("Which meme is a cartoon dog saying ‘Such wow’? 🐶", ["Wow Doge", "Much Wow Doge", "Such Wow Doge", "Very Meme Doge"], 2),
    ("What dance did TikTokers call the “Oh Na Na Na”? 🎵", ["Oh Na Na Na", "Savage", "Renegade", "Blinding Lights"], 0),
    ("Which YouTuber’s crew is known as “The Dream Team”? 🌟", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme features a baby dancing to ‘M to the B’? 👶", ["Baby Shark", "M to the B", "Baby Cha-Cha", "Dancing Infant"], 1),
    ("Who headlined the biggest Twitch subathon of 2023? 📺", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 2),
    ("Which meme depicts a French bulldog saying ‘Oui oui’? 🐕", ["French Doge", "Oui Oui Dog", "Bonjour Dog", "Meme Bulldog"], 0),
    ("Which YouTuber once survived 50 hours in a desert? 🏜️", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme from SpongeBob features blurred text? 🌫️", ["Blurred Mr. Krabs", "Blurred Spongebob", "Sans Blur", "Fuzzy Bob"], 0),
    ("Which viral challenge involved eating raw onions? 🧅", ["Onion Challenge", "Cinnamon", "Ice Bucket", "Tide Pod"], 0),
    ("Which YouTuber set a world record for most hot dogs eaten? 🌭", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("What year did the ‘Ken Block Gymkhana’ car meme explode? 🚗", ["2010", "2012", "2014", "2016"], 2),
    ("Which meme shows a hand controlling puppet strings? 🎭", ["Puppet Master", "Hand Control", "Manipulation", "Social Experiment"], 2),
    ("Who is known for the phrase “Can you do it without moving your face?” 🤡", ["CarryMinati", "Kai Cenat", "MrBeast", "IShowSpeed"], 3),
    ("Which meme shows a caveman version of Spongebob? 🗿", ["Caveman Sponge", "Primitive SpongeBob", "Mocking SpongeBob", "Stone Age Sponge"], 2),
    ("Which YouTuber did the “Last to Stop Riding Roller Coaster”? 🎢", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme shows a guy yelling at his cat? 😾", ["Woman Yelling Cat", "Angry Cat", "Cat Fight", "Yelling Cat"], 0),
    ("Which challenge went viral for licking ice cream off cars? 🍦", ["Car Lick", "Ice Cream Challenge", "Dare Lick", "Street Lick"], 0),
    ("Which upstate NY town’s sign was stolen in the ‘Lake Placid’ prank? 🪧", ["Placid Lake", "Lake Placid", "Whiteface", "Saranac"], 1),
    ("Which YouTuber once built a real-life Monopoly board? 🎲", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme shows a guy running in panic toward another car? 🚗", ["Crazy Gary", "Panic Guy", "Drive Run Guy", "Racing Man"], 0),
    ("Who popularized the “ROAST” streams? 🔥", ["CarryMinati", "MrBeast", "Kai Cenat", "IShowSpeed"], 0),
    ("Which meme features a baby with sunglasses saying “Deal with it”? 😎", ["Cool Baby", "Deal With It", "Baby Shades", "Sunglass Kid"], 1),
    ("What social platform started the ‘Here’s Johnny!’ door opening meme? 🚪", ["TikTok", "Instagram", "Reddit", "YouTube"], 3),
    ("Which YouTuber did a $500,000 charity stream? ❤️", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme has a split panel of a calm dog and a fierce dog? 🐕", ["Two Dogs", "Everything is Fine", "Doggo Mood", "Doge Split"], 0),
    ("Which viral video features a toddler shouting ‘No! No! No!’? 🚫", ["Toddler Tantrum", "No No Kid", "Baby Reject", "Little Protest"], 1),
    ("Which YouTuber’s merch sold out in under an hour? 🛒", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme shows a cartoon fish attacking SpongeBob? 🐠", ["Tired Patrick", "Mocking SpongeBob", "Surprised Patrick", "Angry Walmart Fish"], 1),
    ("Who coined “I’m tall, so…” on stream? 📏", ["IShowSpeed", "CarryMinati", "MrBeast", "Kai Cenat"], 0),
    ("Which meme features a knight asking a king about service? 🤴", ["Royal Service", "Knight Duty", "Medieval Service", "Is This Medieval?"], 2),
    ("Which challenge was about staying inside a circle drawn on the ground? 🔵", ["Last to Leave Circle", "Circle of Doom", "Ground Bound", "Stay Inside Challenge"], 0),
    ("Which meme is a photo of a distracted girl on her phone? 📱", ["Phone Girl", "Distracted Girlfriend", "Mobile Obsession", "Screen Stare"], 1),
    ("Which YouTuber lost a bet and had to get a tattoo live? 🖋️", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 3),
    ("Which meme shows a screaming woman and a cat at a dinner table? 🍽️", ["Woman Yelling at a Cat", "Dinner Dispute", "Screaming Cat", "Angry Dinner"], 0),
    ("What year did the Harlem Shake trend go viral? 🕺", ["2010", "2012", "2013", "2015"], 2),
    ("Which YouTuber launched a school for coding? 💻", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme features a guy with a smug grin and finger guns? 👉", ["Finger Guns", "Smug Guy", "Cool Finger", "Gotcha"], 0),
    ("Which challenge asked people to hold their breath underwater? 🌊", ["Breath Challenge", "Ice Bucket", "Tide Pod", "Ghost Pepper"], 0),
    ("Which YouTuber once bought an entire island? 🏝️", ["MrBeast", "CarryMinati", "IShowSpeed", "Kai Cenat"], 0),
    ("Which meme shows a guy asking for help in a burning building? 🚒", ["Help Me", "Burning Man", "This is fine", "Rescue Me"], 2),
    ("Which viral video features ducklings following a tractor? 🦆", ["Duck Army", "Nature March", "Tractor Ducks", "Follow the Leader"], 3),
    ("Which YouTuber’s headphones once broke on live stream? 🎧", ["Kai Cenat", "IShowSpeed", "MrBeast", "CarryMinati"], 1),
    ("Which meme features a policeman slapping a kid? 🚨", ["Stop That Kid", "Police vs Kid", "No Running", "Kid Slap"], 0),
    ("Which challenge was called the “Bean Boozled Challenge”? 🍬", ["Bean Boozled", "Tide Pod", "Ghost Pepper", "Cinnamon"], 0),
    ("Which YouTuber’s catchphrase is “Take that, bro!”? 🥊", ["IShowSpeed", "CarryMinati", "MrBeast", "Kai Cenat"], 0),
    ("Which meme shows a rocket launch labeled “Me launching into the DMs”? 🚀", ["DM Rocket", "DM Launch", "Insta Rocket", "Tweet Launch"], 0),
    ("Which viral dance was set to “Blinding Lights”? 🌃", ["Blinding Lights", "Renegade", "Floss", "Savage"], 0),
    ("Which YouTuber gave away a Lamborghini? 🚗", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme shows a toddler in a spider costume screaming? 🕷️", ["Spider Baby", "Toddler Scream", "Costume Kid", "Scary Baby"], 0),
    ("Which challenge involved painting eyeballs on fruit? 🍊", ["Scary Fruit", "Eye Fruit", "Spooky Paint", "Fruit Art"], 1),
    ("Which YouTuber’s video “I gave $1,000,000 to charity” went viral in what year? 📅", ["2018", "2019", "2020", "2021"], 1),
    ("Which meme depicts a skeleton dancing in a graveyard? 💀", ["Spooky Skeleton", "Dancing Bones", "Graveyard Dance", "Skeleton Party"], 1),
    ("Which challenge was called the “No Thumbs Challenge”? 🤚", ["No Thumbs", "No Hands", "One Thumb", "Thumb-less"], 0),
    ("Which meme shows a penguin walking confidently? 🐧", ["Confident Penguin", "Happy Feet", "Strutting Bird", "Bold Penguin"], 0),
    ("Which YouTuber played Fortnite with Drake? 🎮", ["IShowSpeed", "Kai Cenat", "MrBeast", "CarryMinati"], 2),
    ("Which viral meme is simply a blinking white guy? 👀", ["Blinking Guy", "Surprised Pikachu", "Disbelief Nick Young", "Mocking SpongeBob"], 0),
    ("Which YouTuber’s first video was a reaction to PewDiePie? 📹", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 0),
    ("Which challenge had people cooking mac and cheese in coffee makers? 🍜", ["Mac Coffee", "Kitchen Hack", "Coffee Maker Challenge", "Instant Noodles"], 2),
    ("Which meme features a frog sipping tea under a window? 🫖", ["Kermit Tea", "Pepe Tea", "But That’s None of My Business", "Frog Sip"], 2),
    ("Who once recreated Fortnite in real life with nerf guns? 🔫", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme shows a cartoon kid with a smug grin closing his eyes? 😏", ["Smug Child", "Smug Kid", "Deal With It Child", "Grin Boy"], 1),
    ("Which viral video features a man lip-syncing “M to the B”? 🎤", ["M to the B", "Lip Sync Battle", "Singing Guy", "Beatbox Man"], 0),
    ("Which YouTuber’s channel started as “MrBeast6000”? 🔢", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme shows an astronaut discovering memes are on fire? 👨‍🚀", ["Astronaut Meme", "Ancient Aliens", "Mind Blown", "Flaming Discovery"], 0),
    ("Which challenge was called the “100 Layers” challenge? ➗", ["100 Layers", "Layer Up", "Stack Challenge", "Mega Layers"], 0),
    ("Which YouTuber’s editing style uses rapid cuts and zooms? 🎞️", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 2),
    ("Which meme involves a talking baby at a dinner table? 🍽️", ["Woman Yelling at Cat", "Talking Baby", "Dinner Kid", "Shouting Toddler"], 1),
    ("Which viral dance is called the “Woah”? 🤟", ["Woah", "Floss", "Renegade", "Chicken Dance"], 0),
    ("Who made the “I gave you guys $50,000” streamer surprise? 💰", ["IShowSpeed", "Kai Cenat", "MrBeast", "CarryMinati"], 2),
    ("Which meme features Captain Picard facepalming? 🤦", ["Facepalm Picard", "Picard Meme", "Star Trek Fail", "Captain’s Shame"], 0),
    ("Which YouTuber once lived in a 100-foot cube for a day? 📦", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme shows a man running away from an explosion? 💥", ["Guy Running", "Explosion Run", "Revenge", "Nope.gif"], 1),
    ("Which challenge involved building a boat out of cardboard? 📦", ["Cardboard Boat", "Boat Hack", "DIY Ship", "Paper Sail"], 0),
    ("Which YouTuber did the “Survive On $0.01” challenge? 🪙", ["MrBeast", "IShowSpeed", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme features a snail with a helmet saying ‘Slow and steady’? 🐌", ["Helmet Snail", "Slow Meme", "Steady Snail", "Turtle vs Snail"], 0),
    ("Which viral song goes “Oops, I did it again”? 🎶", ["Oops I Did It Again", "Baby One More Time", "Toxic", "Genie in a Bottle"], 0),
    ("Who popularized the $10,000 gold bar opening video? 🏅", ["CarryMinati", "MrBeast", "IShowSpeed", "Kai Cenat"], 1),
    ("Which meme shows a dog sitting in a chair shrugging? 🤷", ["Confused Dog", "Shrug Pup", "IDK Doge", "Doge Shrug"], 1),
    ("Which challenge asked people to not laugh while eating lemons? 🍋", ["Lemon Laugh", "No Laugh Challenge", "Sour Face", "Citrus Dare"], 1),
    ("Which YouTuber’s fans are called ‘KinGgang’? 👑", ["IShowSpeed", "MrBeast", "Kai Cenat", "CarryMinati"], 0),
    ("Which meme features a toddler saying ‘Mama, why?’ 😢", ["Mama Why", "Sad Baby", "Why Cry", "Tearful Kid"], 0),
    ("Which viral dance is called the “Savage” routine? ❤️‍🔥", ["Savage", "Woah", "Floss", "Renegade"], 0),
    ("Who built a real-life Squid Game for 456 participants? 🎲", ["MrBeast", "Kai Cenat", "IShowSpeed", "CarryMinati"], 0),
    ("Which meme features a person walking away from a burning building? 🔥", ["This is fine", "Fire Walk", "Run Away", "Building Meme"], 0),
    ("Which YouTuber once did a “spend 24 hours in jail” video? 🚔", ["MrBeast", "CarryMinati", "IShowSpeed", "Kai Cenat"], 0),
    ("Which meme shows a guy with a massive jawline labeled ‘Alpha’? 🤵", ["Gigachad", "Chad", "Beta", "Sigma"], 0),
    ("Which challenge involved eating only McDonald’s for 30 days? 🍔", ["McChallenge", "Fast Food Only", "30-Day Mc", "Burger Trial"], 1),
    ("Which YouTuber donated 100 cars to random subscribers? 🚙", ["Kai Cenat", "MrBeast", "IShowSpeed", "CarryMinati"], 1),
    ("Which meme features a skeleton playing a violin with ‘Taps’? 🎻", ["Taps Skeleton", "Violin Bones", "Sad Skeleton", "Funeral Bones"], 0),
    ("Which viral video has a baby dancing to Latin music? 🕺", ["Latin Baby", "Dancing Infant", "Baby Groove", "Tiny Twerker"], 0),
    ("Which meme shows a couple riding a bike into oblivion? 🚴", ["Bike Meme", "Couple Ride", "Off the Edge", "Into the Void"], 2),
    ("Which YouTuber’s stunts include building a real dinosaur park? 🦖", ["MrBeast", "CarryMinati", "IShowSpeed", "Kai Cenat"], 0),
    ("What happens if you mew too hard? 😬", ["You unlock jawline powers", "You summon a dentist", "You become a Sigma", "You bite your tongue off"], 0),
    ("Which meme character is known for sipping tea and judging silently? 🍵", ["Kermit the Frog", "Pepe the Frog", "Dat Boi", "Grumpy Cat"], 0),
    ("Why did the GigaChad cross the road? 💪", ["To flex on the other side", "To find his mirror", "To escape the betas", "To chase the sigma grind"], 2),
    ("What is the primary ingredient in a 'fluffernutter' sandwich? 🥪", ["Peanut butter", "Marshmallow fluff", "Jelly", "Nutella"], 1),
    ("What does the 'Distracted Boyfriend' meme depict? 👀", ["A man looking at another woman", "A man texting while driving", "A man eating while on a diet", "A man ignoring his pet"], 0),
    ("Which social media platform is known for the 'Trash Dove' sticker? 🕊️", ["Facebook", "Instagram", "Snapchat", "Twitter"], 0),
    ("What is the name of the purple bird that headbangs in a popular sticker? 🐦", ["Trash Dove", "Party Pigeon", "Headbanger Bird", "Disco Dove"], 0),
    ("What is the 'Math Lady' meme commonly used to represent? 🧮", ["Confusion", "Intelligence", "Excitement", "Anger"], 0),
    ("Which meme features a woman yelling at a cat sitting at a dinner table? 🐱", ["Woman Yelling at a Cat", "Angry Karen", "Dinner Dispute", "Cat Fight"], 0),
    ("What is the 'Coffin Dance' meme associated with? ⚰️", ["Pallbearers dancing", "Halloween parties", "Zombie movies", "Funeral parades"], 0),
    ("Which meme involves a frog sipping tea with the caption 'But that's none of my business'? 🐸", ["Kermit the Frog", "Pepe the Frog", "Dat Boi", "Frog and Toad"], 0),
    ("What is the 'Ice Bucket Challenge' meme associated with? 🧊", ["ALS awareness", "Summer fun", "Pranks", "Water conservation"], 0),
    ("Which meme features a dog in a burning room saying 'This is fine'? 🔥", ["This is Fine", "Dog in Danger", "Burning Dog", "Calm Chaos"], 0),
    ("What is the 'Hide the Pain Harold' meme known for? 😐", ["Forced smiles", "Excitement", "Anger", "Surprise"], 0),
    ("Which meme features a man in a purple suit known as 'Purple Guy'? 🟣", ["Five Nights at Freddy's", "Barney", "Willy Wonka", "Joker"], 0),
    ("What is the 'Woman Yelling at a Cat' meme a combination of? 🗣️🐱", ["TV show scene and a cat photo", "Movie scene and a meme", "Cartoon and a real cat", "News clip and a cat meme"], 0),
    ("Which meme features a character with a confused expression surrounded by math equations? 📐", ["Math Lady", "Confused Girl", "Thinking Man", "Equation Guy"], 0),
    ("What is the 'Distracted Boyfriend' meme format used to depict? 💑", ["Temptation", "Loyalty", "Confusion", "Happiness"], 0),
    ("Which meme features a dancing baby from the early internet era? 👶", ["Baby Cha-Cha", "Dancing Baby", "Internet Baby", "Cha-Cha Kid"], 0),
    ("What is the 'Dat Boi' meme known for? 🚴", ["Frog on a unicycle", "Dancing frog", "Singing frog", "Flying frog"], 0),
    ("Which meme features a man in a suit with the caption 'Well, that escalated quickly'? 📈", ["Anchorman", "The Office", "Parks and Recreation", "Brooklyn Nine-Nine"], 0),
    ("What is the 'Pepe the Frog' meme often associated with? 🐸", ["Internet culture", "Political movements", "Cartoons", "Children's books"], 0),
    ("Which meme features a character saying 'Ain't nobody got time for that'? ⏰", ["Sweet Brown", "Sassy Girl", "Time Lady", "Busy Bee"], 0),
    ("What is the 'Overly Attached Girlfriend' meme known for? 😍", ["Clinginess", "Happiness", "Sadness", "Anger"], 0),
    ("Which meme features a man in a suit saying 'I'm not even mad, that's amazing'? 😮", ["Anchorman", "The Office", "Parks and Recreation", "Brooklyn Nine-Nine"], 0),
    ("What is the 'Ermahgerd' meme known for? 😱", ["Excitement over books", "Fear", "Anger", "Sadness"], 0),
    ("Which meme features a dog with a concerned expression in a burning room? 🔥🐶", ["This is Fine", "Dog in Danger", "Burning Dog", "Calm Chaos"], 0),
    ("What is the 'Success Kid' meme known for? 👶", ["Celebrating small victories", "Anger", "Sadness", "Confusion"], 0),
    ("Which meme features a man in a suit saying 'I don't know who you are, but I will find you'? 🎯", ["Taken", "The Office", "Parks and Recreation", "Brooklyn Nine-Nine"], 0),
    ("What is the 'Grumpy Cat' meme known for? 😾", ["Permanent frown", "Happiness", "Surprise", "Excitement"], 0),
    ("Which meme features a character saying 'Y U NO'? 🤷", ["Y U NO Guy", "Confused Man", "Angry Dude", "Frustrated Guy"], 0),
    ("What is the 'Bad Luck Brian' meme known for? 🍀", ["Unfortunate events", "Good luck", "Happiness", "Success"], 0),
    ("Which meme features a man with a skeptical expression and the caption 'Really? Really?'? 🤨", ["Skeptical Third World Kid", "Confused Man", "Angry Dude", "Frustrated Guy"], 0),
    ("What is the 'First World Problems' meme known for? 😢", ["Minor inconveniences", "Major issues", "Happiness", "Success"], 0),
    ("Which meme features a character saying 'One does not simply walk into Mordor'? 🧙", ["Boromir", "Gandalf", "Frodo", "Aragorn"], 0),
    ("What is the 'Condescending Wonka' meme known for? 🍫", ["Sarcasm", "Kindness", "Anger", "Happiness"], 0),
    ("Which meme features a character saying 'Brace yourselves, winter is coming'? ❄️", ["Ned Stark", "Jon Snow", "Arya Stark", "Tyrion Lannister"], 0),
    ("What is the 'Philosoraptor' meme known for? 🦖", ["Deep questions", "Jokes", "Anger", "Happiness"], 0),
    ("Which meme features a character saying 'I can haz cheezburger'? 🧀", ["Lolcat", "Grumpy Cat", "Nyan Cat", "Keyboard Cat"], 0),
    ("What is the 'Scumbag Steve' meme known for? 🧢", ["Bad behavior", "Kindness", "Happiness", "Success"], 0),
    ("Which meme features a character saying 'Not sure if...' with a skeptical expression? 🤔", ["Futurama Fry", "Skeptical Third World Kid", "Confused Man", "Angry Dude"], 0),
    ("What happens if you mew while doing pushups? 💪😬", ["Giga jaw gains", "Summon a sigma portal", "You teleport to a mirror selfie", "Mew level up"], 0),
    ("What did Kai Cenat break during his record-breaking stream? 💻🔥", ["A chair", "The internet", "Twitch HQ", "His keyboard"], 1),
    ("What’s the most powerful combo in meme land? ⚔️😂", ["GigaChad + Mewing", "Sigma + Rizz", "Speed + Bark", "Shrek + Crocs"], 2),
    ("What do you call someone who mews, rizzes, and goes to the gym? 🧠🗿", ["Ultimate Sigma", "Alpha Giga Rizzer", "Maxed NPC", "Cenat Master"], 0),
    ("Which YouTuber is known for giving away houses and islands? 🏝️💰", ["MrBeast", "IShowSpeed", "Kai Cenat", "Ryan Trahan"], 0),
    ("What animal represents 'sigma energy' on TikTok? 🐺", ["Wolf", "Tiger", "Owl", "Capybara"], 0),
    ("What is the loudest phrase IShowSpeed screams? 📢🔥", ["CRISTIANO RONALDO", "SUIIIIIII", "WHAT THE DOG DOIN", "BARK BARK BARK"], 1),
    ("If GigaChad met Skibidi Toilet, what would happen? 🚽💥🗿", ["The universe folds", "Sigma flushes cringe", "Toilet gets abs", "Dance battle"], 1),
    ("What’s a logical consequence of skipping leg day? 🦵💀", ["Top-heavy walking", "Lose your sigma badge", "No stair access", "You vanish"], 0),
    ("Which meme involves people pretending to walk like zombies at prom? 🧟‍♂️💃", ["NPC dancing", "Zombie Prom", "Sigma Walk", "AI Prom"], 2),
    ("What food is considered ultra meme-worthy on TikTok? 🍝", ["Pizza", "Ramen", "Chicken wings", "Pink sauce"], 3),
    ("What is the logical opposite of a Sigma male? 🤔", ["Alpha NPC", "Emotional extrovert", "Beta catboy", "Mega cringe"], 2),
    ("Which animal represents internet chaos and cute memes? 🦫", ["Capybara", "Quokka", "Sloth", "Otter"], 0),
    ("What does 'mewing in Ohio' unlock? 🛸🦷", ["Alien jaw symmetry", "Extra cheekbones", "Ohio 4D rizz", "Nothing, Ohio logic is different"], 3),
    ("Which YouTuber runs at the camera full-speed yelling? 🏃📸🔥", ["Speed", "Kai Cenat", "MrBeast", "JiDion"], 0),
    ("What’s the logical thing to do when your crush says 'you’re like a brother to me'? 😅", ["Sigma silence", "Block her", "Leave the planet", "Time travel to undo friendship"], 1),
    ("What emoji perfectly represents Kai Cenat’s energy? ⚡️", ["🗣️", "🔥", "🤯", "😤"], 2),
    ("What meme happens when you stare too long at yourself in the mirror? 🪞🧠", ["Third person unlocked", "Narcissist Mode", "Sigma Reflection", "Ego Boss Battle"], 0),
    ("If your rizz is too powerful, what could logically happen? 💬❤️", ["Wi-Fi explodes", "Heart emoji overload", "NPCs stare", "You get reported for charm hacks"], 3),
    ("Which meme word describes giving up in style? 🎭", ["Mid", "L + Ratio", "Skill issue", "Dramatic exit"], 1),
    ("Who started a firework inside his house for fun? 🎆🏠", ["IShowSpeed", "Kai Cenat", "SpeedyBoyz", "MrBeast"], 0),
    ("What happens if you try to mew during sleep? 💤🦷", ["Jawline fairy visits", "Sigma dream begins", "Teeth teleport", "You choke on air"], 1),
    ("What do you call a villain with good aesthetics? 🦹‍♂️💅", ["Sigma antagonist", "Fashion menace", "Glamour Chad", "Stylish NPC"], 0),
    ("What’s the IQ of someone who argues in comment sections daily? 🧠📉", ["2000 (reverse)", "69", "Depends on timezone", "NPC level 2"], 3),
    ("What’s the cure for cringe according to meme scientists? 🧪😂", ["Touch grass", "Delete TikTok", "Breathe air", "GigaPunch"], 0),
    ("If you see 3 capybaras chilling, what must you do? 🧘‍♂️🦫", ["Sit with them", "Record a TikTok", "Offer snacks", "Become one"], 0),
    ("What does it mean if someone says 'bro thinks he’s him'? 🤨", ["Sigma delusion", "NPC confusion", "High self-confidence", "Certified bruh moment"], 0),
    ("What is 'Mew Year Resolution'? 🦷🗓️", ["Jawline goal", "New year mewing", "Sigma grind mindset", "All of the above"], 3),
    ("Which YouTuber gave away an entire chocolate factory? 🍫🏭", ["MrBeast", "Logan Paul", "Mark Rober", "MrWillyWonka"], 0),
    ("What is the most meme-worthy gym mirror move? 🏋️‍♂️🪞", ["Flex and nod", "Stare into soul", "Alpha grunt", "Whisper 'Giga'"], 0),
    ("What’s the main ingredient in a Sigma smoothie? 🍹🗿", ["Creatine + Rizz", "Mew protein", "Alpha tears", "Jawline juice"], 0),
    ("What would you yell if you stubbed your toe during a live stream? 🦶📢", ["BROOOOOOO!", "OWWWWWW", "MOM!", "IShowSpeed style scream"], 3),
    ("What meme happens when you open TikTok and it's 3am? ⏰📱", ["NPC marathon", "Sigma whispering motivation", "RizzTok takeover", "You turn into an Ohio character"], 3),
    ("What emoji best describes ‘rizz in progress’? 😎💬", ["💬", "😏", "📈", "💘"], 2),
    ("What do you call a failed flirt attempt? 😅", ["Rizz fail", "Skill issue", "Emotional L", "Microcringe"], 1),
    ("What is the meme logic behind ‘go touch grass’? 🌱", ["Stop being terminally online", "Reconnect with soil", "Photosynthesis for brain", "NPC detox"], 0),
    ("What happens when you mix GigaChad with a capybara? 🦫🗿", ["World peace", "Balance", "Viral overload", "Jawline float"], 2),
    ("What’s the final boss of meme culture? 👑😂", ["Shrek in Ohio", "Speed with fireworks", "Sigma vs Skibidi", "Elon tweeting while eating hotdogs"], 3),
    ("What’s the side effect of watching too many prank videos? 🎥😵", ["Trust issues", "Extreme rizz", "NPC behavior", "Become the prank"], 0),
    ("What do people say when Speed does something outrageous? 🤯", ["Bro ain't real", "WHAT DID I JUST SEE", "SUIIIII", "Nah this is AI"], 0),
    ("What's the side effect of too much 'rizz'? 💘🧠", ["Instant marriage", "Lose ability to blink", "Wi-Fi boost", "Personality overload"], 3),
    ("What’s the most cursed TikTok trend? 📱👻", ["Toilet singing", "Ohio gym selfies", "NPC livestreams", "Mewing while crying"], 2),
    ("Why did the NPC refuse the quest? 🎮🙅‍♂️", ["It was cringe", "Too much rizz involved", "He wasn’t coded for it", "No XP gain"], 2),
    ("What does a Sigma eat for breakfast? 🥣🗿", ["Rizz flakes", "Air and ambition", "Jawline juice", "NPC tears"], 1),
    ("What happens when you say 'Ohio' three times in a mirror? 🪞😨", ["Portal opens", "Lose gravity", "Speed appears", "Get rizzed unexpectedly"], 0),
    ("What is 'Skibidi' actually a language of? 🗣️🛁", ["Bathroom nation", "Meme culture", "Toilet diplomacy", "Unspoken rizz"], 0),
    ("Which streamer is most likely to bark mid-sentence? 🐶🗣️", ["IShowSpeed", "Kai Cenat", "YourRAGE", "Adin Ross"], 0),
    ("What is the final level of rizz called? 💬📈", ["Omega Rizz", "Infinite Rizz", "Rizzgod Mode", "Rizzlightenment"], 3),
    ("Which meme involves absolute chaos and explosions for no reason? 💥🤯", ["Ohio memes", "MrBeast challenges", "Speed streams", "All of the above"], 3),
    ("What emoji best symbolizes ‘NPC behavior’? 🤖", ["😐", "🧍", "🤖", "🪑"], 2),
    ("If MrBeast knocks on your door, what's he likely to say? 🚪💰", ["Here's 10k", "I bought your house", "Wanna be in a challenge?", "All of the above"], 3),
    ("What’s the side effect of a GigaChad wink? 😉🗿", ["Earthquake", "Mirror cracks", "NPC respawn", "Instant blush"], 1),
    ("Why did the Sigma fail his math test? ➗🧠", ["Too busy mewing", "Numbers were too beta", "Didn’t believe in limits", "Only counts jawlines"], 1),
    ("What’s the Ohio version of Spider-Man called? 🕷️🛸", ["Spider-Oh", "Toilet-Man", "Skibidi Swinger", "Web Wizard"], 0),
    ("What’s the most logical time to post a meme? ⏰📸", ["3:33am", "When NPCs sleep", "During peak Sigma", "Right before touching grass"], 0),
    ("What happens when rizz reaches 100%? 💯🔥", ["Spontaneous romance", "Lose gravity", "Infinite rizzy loop", "Start floating"], 0),
    ("What’s the rarest YouTuber evolution? 📺🐉", ["Philanthropic MrBeast", "Speed reading calmly", "Kai being quiet", "Silent prankster"], 1),
    ("If a capybara made a mixtape, what genre would it be? 🎶🦫", ["Chill hop", "Sigma lo-fi", "Bathtub jazz", "Meme-core"], 0),
    ("Why can't NPCs rizz? 💬🚫", ["They have no dialogue options", "Programmed for Ls", "They lack jawline updates", "No passion"], 0),
    ("What is the proper reaction to someone saying 'Skibidi'? 😮‍💨", ["Toilet salute", "Run", "Join in", "Respond with 'Toilet Rizzler'"], 2),
    ("What do you gain when you mew for 90 days straight? 📅🦷", ["Cheekbone pass", "Sigma pass", "Visible jaw aura", "Dental sponsorship"], 2),
    ("What's the natural predator of a rizzless NPC? 🧍🔥", ["Sigma male", "Giga meme", "Speed livestream", "Capybara confidence"], 0),
    ("Why did the TikToker yell at the wall? 📲🧱", ["Content!", "Wall had an opinion", "Echo had rizz", "For views"], 3),
    ("What's the danger of over-rizzing? 💘💀", ["Exploding DMs", "Charm fatigue", "Romantic lawsuits", "You start levitating"], 1),
    ("What’s the true capital of meme land? 🌍😂", ["Ohio", "TikTok", "Reddit", "Discord"], 0),
    ("What does it mean to get ‘ratioed’? 📊💔", ["More replies than likes", "Sigma denial", "Internet L", "Cringe confirmed"], 0),
    ("Which creature is said to control Ohio memes? 👹", ["Toilet Demon", "Sigma Clown", "Rizz God", "Skibidi Emperor"], 3),
    ("What is the primary fuel of a GigaChad? ⛽🗿", ["Attention", "Gym selfies", "Jawline tension", "Creatine"], 2),
    ("What happens if you combine MrBeast and Speed? 🤝🎥", ["Explosive giveaways", "Tornado of chaos", "Loud philanthropy", "Unstoppable entertainment"], 3),
    ("Why did Kai Cenat fall off the chair laughing? 🪑😂", ["Too much W energy", "Speed said SUIIIII", "Twitch chat wildin'", "He saw Ohio memes"], 0),
    ("What’s a logical side hustle in meme economy? 💸😂", ["Selling rizz", "Sigma training", "Capybara daycare", "Comment farming"], 3),
    ("What happens when an NPC gains awareness? 🤖💡", ["Becomes self-rizzing", "Turns into TikToker", "Deletes itself", "Writes an apology tweet"], 1),
    ("What's the top meme exercise? 🏋️‍♂️💬", ["Rizz-ups", "Mew squats", "Sigma curls", "Comment crunches"], 0),
    ("What's the Ohio version of GigaChad called? 🗿👽", ["Giga-void", "Chad from 5D", "Mewgan", "SigmaToilet"], 1),
    ("Why did Speed cook chicken in a toaster? 🍗⚡", ["Efficiency", "Chaos", "It’s content", "He lost the oven"], 2),
    ("What do memes evolve into after 10,000 likes? 🧬🔥", ["Virals", "Meme gods", "Internet relics", "NFTs"], 0),
    ("What is the national bird of meme world? 🐦📱", ["Trash Dove", "Twitter Blue", "Capybara Hawk", "Sigma Eagle"], 0),
    ("Why did the Sigma bring a mirror to school? 🪞🎓", ["For reflection", "To flex jawline", "To spot NPCs", "To rizz himself"], 1),
    ("What’s the strongest material in meme logic? 🧱🧠", ["Ohio steel", "Chadnium", "Sigma fiber", "Unbreakable cringe"], 1),
    ("What's the final unlock of rizz evolution? 🔓💞", ["Romantic Ultra Instinct", "Eternal W", "Infinite flirt loop", "Sigma-Rizz Fusion"], 0),
    ("What’s the first rule of Meme Club? 🧠😂", ["Always post the cringe", "Don’t talk about Meme Club", "Never delete drafts", "Touch grass monthly"], 1),
    ("Which drink boosts rizz by 300%? 🥤🔥", ["Giga Juice", "Sigma Shake", "NPCade", "Rizz Fizz"], 3),
    ("Why did the Ohio NPC start levitating? 🛸🧍‍♂️", ["Too much WiFi", "Mewing too hard", "He reached level 100", "Because Ohio"], 3),
    ("What do you unlock after completing the Mewing side quest? 🦷🗿", ["Diamond Jawline", "NPC immunity", "Rizz resistance", "Sigma badge"], 0),
    ("What happens if you 'Breathe Air' unironically? 💨😤", ["Unlock alpha lungs", "Sigma rank up", "NPCs around collapse", "Energy boost"], 1),
    ("Who is most likely to bark while playing FIFA? ⚽🐕", ["IShowSpeed", "Kai Cenat", "MrBeast", "A regular dog"], 0),
    ("What’s the rarest gym transformation? 🏋️‍♂️🦸", ["Chad to Capybara", "Beta to Sigma", "Meme to Machine", "GigaNPC"], 1),
    ("If you scream 'SUIII' 3 times, what appears? 🗣️⚡", ["Ronaldo", "Speed", "Mirror cracks", "TikTok opens"], 1),
    ("Which emoji best represents someone losing an argument with an NPC? 😵‍💫", ["🤔", "😐", "🧍", "💀"], 3),
    ("What's the logical response when someone says 'touch grass'? 🌱👀", ["Where’s the charger?", "What's grass?", "I'm allergic", "Let me mew first"], 2),
    ("What happens if you mix a meme, a rizz tip, and a YouTube short? 🔀🎬", ["World explodes", "Instant virality", "Your phone catches fire", "NPCs level up"], 1),
    ("Which content trend requires zero logic but maximum energy? 📸😵", ["Speed Streams", "Skibidi Toilet", "TikTok dances", "Ohio memes"], 0),
    ("Who would survive in an Ohio horror movie? 😱🚽", ["Capybara", "GigaChad", "MrBeast", "No one"], 0),
    ("What’s the natural habitat of a Sigma male? 🌍🧍‍♂️", ["Gym", "Mirror", "Bookstore", "Any place with NPCs"], 1),
    ("Why did the meme fail? 😓📉", ["Too logical", "Not enough emojis", "Posted at 6pm", "NPCs didn’t get it"], 0),
    ("What's the scientifically proven cringe repellent? 🧪🚫", ["Mewing", "Rizz Spray", "Touching grass", "Muted comments"], 2),
    ("What is the national sport of meme culture? 🏆😂", ["Comment Wars", "Rizz Ball", "Emoji Archery", "Sigma Tag"], 0),
    ("If you wake up in Ohio, what’s your first move? 🛌🚀", ["Teleport out", "Record a meme", "Yell SUIII", "Join NPC society"], 1),
    ("What happens if a capybara and GigaChad fuse? 🦫🗿", ["World peace", "Float to gym", "New god unlocked", "Rizz singularity"], 3),
    ("Why did the YouTuber eat ice cream in a volcano? 🌋🍦", ["Content", "He lost a bet", "It’s Ohio logic", "Too hot for cold takes"], 0),
    ("What’s the best meme investment of 2025? 💹📲", ["RizzCoin", "Skibidi NFTs", "CapyStocks", "MewDAO"], 0),
    ("Why did Speed set off fireworks in his bedroom? 🎆🤯", ["Tradition", "Boredom", "He thought it was a light switch", "Because Speed"], 3),
    ("What happens when an NPC watches Sigma content? 📺🧠", ["Their brain upgrades", "They vanish", "They start mewing", "They gain opinions"], 1),
    ("What’s the most feared meme boss? 👹🧍", ["Toilet Titan", "Ohio Giga NPC", "Meme Godfather", "Rizz Mage"], 1),
    ("Who is the final form of YouTube chaos energy? 🧨📹", ["Kai Cenat", "MrBeast", "Speed", "JJ Olatunji"], 2),
    ("Why can’t NPCs wink? 😉🚫", ["Uncoded emotion", "Too cringe", "Software limit", "No rizz module"], 0),
    ("If Speed and MrBeast did a collab, what would happen? 🤝🎥", ["Explosions", "Million-dollar chaos", "End of TikTok", "All of the above"], 3),
    ("What's the sound of pure meme energy? 🔊😂", ["SUIII", "Ohio echo", "Sigma grunt", "Meme bell"], 0),
    ("What’s the best caption for a shirtless mirror selfie? 🪞📸", ["#Mewing", "Grind Mode", "NPCs fear me", "Built different"], 3),
    ("What do NPCs dream of? 💤🤖", ["Loading screens", "Grass", "TikTok dances", "Unspoken rizz"], 0),
    ("What happens when a Sigma male hits 10,000 pushups? 💪🔥", ["Unlocks Rizz Form", "Starts levitating", "Gym explodes", "Jawline becomes visible from space"], 0),
    ("Which meme animal has the most chill? 🐾😎", ["Capybara", "Sloth", "Owl", "Chad Dog"], 0),
    ("Why did the influencer cry while mewing? 😢🦷", ["Jaw cramps", "Over-rizzed", "NPC heartbreak", "Emotional transformation"], 3),
    ("What is the most Ohio thing ever? 🚧🗿", ["Toilet DJ battle", "Exploding Walmart", "Levitating Llamas", "All of the above"], 3),
    ("What is the internet's version of a midlife crisis? 📱💥", ["Starting a podcast", "Cringe rebrand", "Sigma montage", "NPC arc"], 1),
    ("Which phrase instantly summons NPCs in the comments? 💬🧍", ["Skill issue", "Ratio", "L opinion", "All of them"], 3),
    ("What does 'Built Different' actually mean? 🏗️😤", ["Sigma tier", "NPC repellent", "Max rizz level", "Unknown genetic code"], 0),
    ("What’s the rarest emoji combo in meme battles? ⚔️🤣", ["🗿🧍💀", "💨🦷📉", "🧠💘🔥", "🚽🗣️🦫"], 0),
    ("If you laugh in Ohio, what happens? 😂💥", ["Air explodes", "Meme curse", "You get streamed", "Toilet starts talking"], 1),
    ("What does an NPC call a vacation? 🧳🧍", ["Walking in a circle", "Buffering elsewhere", "Touching simulated grass", "AFK mode"], 1),
    ("What's Speed's spirit animal during a stream? 🐕🎙️", ["Chihuahua", "Wired golden retriever", "WiFi raccoon", "Firecracker goat"], 0),
    ("Which action is illegal in Ohio but normal elsewhere? 🚓🛸", ["Blowing bubbles", "Mewing in public", "Thinking logically", "Blinking twice"], 2),
    ("What is the final exam for a Sigma male? 📚🗿", ["Rizz theory", "NPC detection", "Staring contest", "Jawline physics"], 3),
    ("Why did the TikToker slap bread on a mirror? 🍞🪞", ["Meme ritual", "Cringe sacrifice", "NPC summoning", "Content reasons"], 0),
    ("What do GigaChads eat post-workout? 🏋️‍♂️🍽️", ["Rizz Wrap", "NPC stew", "Protein pixels", "Flex flakes"], 3),
    ("What’s the best defense against an Ohio meme attack? 🛡️🚽", ["Meme shield", "Sigma calm", "Toilet armor", "Comment disabling"], 2),
    ("If memes were a currency, what would be the highest value coin? 🪙😂", ["Rizz Token", "Skibidi Coin", "Sigma Gold", "LOL Dollar"], 0),
    ("Why did Kai Cenat yell at a vending machine? 🍬📢", ["It took his rizz", "Livestream dare", "It rejected NPCs", "Why not"], 3),
    ("What happens when your cringe limit reaches 100%? 📉💀", ["Explode into emojis", "Instant TikTok ban", "Become a meme", "Respawn in Ohio"], 2),
    ("What's the Ohio version of ChatGPT? 🤖🛸", ["ChatNPC", "CringeBot", "RizzGPT", "ToiletGPT"], 0),
    ("What’s the ultimate TikTok power move? 📲💃", ["Dancing with zero emotion", "Silent barking", "Eating cereal mid-transition", "Staring into your soul"], 3),
    ("What does a meme need to ascend? ☁️🔥", ["Relatable pain", "Low quality", "Unhinged energy", "A CapCut template"], 3),
    ("Which emoji best represents 'GigaRizz'? 💘🗿", ["🔥", "🗿", "💯", "😤"], 1),
    ("Why did the NPC glitch mid-sentence? 🧍💬", ["Too much rizz nearby", "Bad WiFi", "Beta overload", "He saw a mirror"], 0),
    ("What's the gym PR for Sigma flex? 💪📊", ["Lifting logic", "Bench-pressing NPCs", "One-arm memes", "Deadlift disrespect"], 1),
    ("Why did MrBeast buy an entire zoo? 🐘💰", ["For a thumbnail", "He lost a bet", "Meme tax break", "To hide Speed"], 0),
    ("What's the strongest form of meme logic? 🧠🌀", ["Inverted IQ", "NPC denial", "Ohio physics", "Unfiltered Sigma"], 2),
    ("What does mewing at 3am unlock? 🌙🦷", ["Shadow jawline", "Sigma aura", "Meme ghosts", "Sleep paralysis rizzer"], 1),
    ("Why did the streamer fight his webcam? 🎥🥊", ["It barked first", "Frame drop disrespect", "Meme moment", "Ohio challenge"], 3),
    ("What is the rarest meme job title? 👔🖥️", ["Full-time commenter", "Sigma consultant", "Mewfluencer", "Rizz Strategist"], 2),
    ("What's the Ohio equivalent of gravity? 🌀🌎", ["Confusion", "Floatiness", "Backflip force", "Comment section pressure"], 1),
    ("What’s a capybara’s favorite playlist? 🎧🦫", ["Lo-fi chill jawlines", "Barkless bangers", "Toilet tunes", "Silent Waves"], 0),
    ("Why did Speed yell 'Cristo Ronaldo!' in Walmart? 🛒⚽", ["Channeling power", "Content energy spike", "Lost a challenge", "He saw a soccer ball"], 3),
    ("What happens if you drink Rizz Juice and stare into the mirror? 🧃🪞", ["Romance spawns", "NPCs run", "You ascend", "Skibidi starts playing"], 2),
    ("What do meme overlords fear? 😱📉", ["Ratio storms", "Capybara revolt", "Sigma meditation", "Over-rizzing"], 0),
    ("Why do NPCs avoid eye contact? 👁️👁️", ["No rendering", "Too much cringe", "Rizz detection", "Fear of becoming real"], 3),
    ("What’s the best dating tactic in meme world? 💘📲", ["Emoji-only messages", "Post jawline pic", "Reply with 'SUIII'", "Challenge them to rizz battle"], 3),
    ("What's the final stage of online fame? 🧠📸", ["Sigma collapse", "Meme reincarnation", "Capybara guest spot", "Livestream yourself thinking"], 1),
    ("Why are Ohio mirrors banned? 🚫🪞", ["Too reflective", "They talk back", "NPCs get stuck", "They mew back at you"], 3),
    ("What’s the logical ending to a Speed stream? 📴🔥", ["Camera explodes", "Mic barks", "Internet collapses", "No logic at all"], 3),
    ("What happens if you mix NPC DNA with Sigma code? 🧬🗿", ["World glitches", "Rizz virus spreads", "Self-awareness overload", "Cringe implodes"], 0),
    ("What unlocks once you win an argument online? 🧠🏆", ["Nothing", "You level down", "NPCs block you", "Sigma invisibility"], 0),
    ("Which emoji combo scares NPCs the most? 😨🧍", ["🗿💀💨", "😐😤🦷", "📉🧠🤣", "📲🛸🚽"], 0),
    ("What does an alpha do when told to 'calm down'? 😤🧘", ["Starts pushups", "Barks", "Starts podcast", "Quietly mews"], 1),
    ("Why did a TikToker marry their own content? 💍📲", ["Unspoken rizz", "Sigma loneliness", "Trend wave", "Comment section dared them"], 3),
    ("What is the dark side of 'Built Different'? 🏗️🌑", ["Can’t sit still", "Too much rizz", "Unrelatable memes", "No NPC friends"], 2),
    ("Why is every Ohio meme blurry? 📸🌫️", ["Filmed on a toaster", "NPC effect", "Unstable reality", "Camera was levitating"], 2),
    ("What’s the best strategy in meme warfare? ⚔️😂", ["Comment before watching", "Be unhinged", "Post and ghost", "Win by confusion"], 3),
	],
    'squiz': [
    ("What is the chemical symbol for water? 💧", ["H2O", "O2", "CO2", "NaCl"], 0),
    ("Which planet is closest to the Sun? ☀️", ["Venus", "Mercury", "Mars", "Earth"], 1),
    ("Who wrote 'Romeo and Juliet'? 🎭", ["Charles Dickens", "Jane Austen", "William Shakespeare", "Mark Twain"], 2),
    ("What is 7 × 8? ✖️", ["54", "56", "58", "60"], 1),
    ("Which element has atomic number 6? 🔬", ["Oxygen", "Carbon", "Nitrogen", "Helium"], 1),
    ("What internet protocol is used to send web pages? 🌐", ["FTP", "HTTP", "SMTP", "SSH"], 1),
    ("What year did the World Wide Web become publicly available? 📅", ["1983", "1989", "1991", "1995"], 2),
    ("Who is known as the Father of Computers? 💻", ["Alan Turing", "Charles Babbage", "John von Neumann", "Steve Jobs"], 1),
    ("Which country is home to the Eiffel Tower? 🇫🇷", ["Italy", "Germany", "France", "Spain"], 2),
    ("What is the powerhouse of the cell? 🧬", ["Nucleus", "Mitochondria", "Ribosome", "Golgi apparatus"], 1),
    ("Which language is primarily spoken in Brazil? 🗣️", ["Spanish", "Portuguese", "French", "English"], 1),
    ("What does 'HTTP' stand for? 🔗", ["HyperText Transfer Protocol", "HighText Transmission Protocol", "Hyperlink Text Transfer Portal", "HyperText Transmission Program"], 0),
    ("What is the capital of Japan? 🗾", ["Tokyo", "Kyoto", "Osaka", "Nagoya"], 0),
    ("Which instrument has keys, pedals, and strings? 🎹", ["Guitar", "Piano", "Violin", "Drum"], 1),
    ("What social science studies human societies? 🏛️", ["Psychology", "Anthropology", "Biology", "Astronomy"], 1),
    ("Which device measures atmospheric pressure? 🌡️", ["Thermometer", "Barometer", "Hygrometer", "Anemometer"], 1),
    ("Who painted the Mona Lisa? 🖼️", ["Vincent van Gogh", "Pablo Picasso", "Leonardo da Vinci", "Claude Monet"], 2),
    ("What does CPU stand for? 🖥️", ["Central Processing Unit", "Control Program Unit", "Central Program Utility", "Computer Processing Unit"], 0),
    ("What gas do plants absorb? 🌿", ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], 2),
    ("Which social media platform uses a blue bird as its logo? 🐦", ["Instagram", "LinkedIn", "Twitter", "Snapchat"], 2),
    ("What is the largest ocean on Earth? 🌊", ["Atlantic", "Indian", "Arctic", "Pacific"], 3),
    ("Which number is a prime? 🔢", ["21", "27", "29", "33"], 2),
    ("What technology is used for virtual currency? 💳", ["Blockchain", "Cloud computing", "AI", "IoT"], 0),
    ("Who discovered penicillin? 🧫", ["Alexander Fleming", "Louis Pasteur", "Marie Curie", "Gregor Mendel"], 0),
    ("What year did man first land on the Moon? 🌕", ["1965", "1969", "1972", "1959"], 1),
    ("Which social quiz asks about trending hashtags? #️⃣", ["Hashtag Hero", "Trend Tracker", "Tag Talk", "Hash Hunt"], 1),
    ("What is the square root of 144? 📐", ["10", "11", "12", "13"], 2),
    ("Which programming language is known for its snake logo? 🐍", ["Java", "C++", "Python", "Ruby"], 2),
    ("What instrument is used to view tiny objects? 🔭", ["Telescope", "Microscope", "Binoculars", "Periscope"], 1),
    ("Who was the first President of the United States? 🇺🇸", ["Thomas Jefferson", "George Washington", "Abraham Lincoln", "John Adams"], 1),
    ("What is the main ingredient in guacamole? 🥑", ["Tomato", "Avocado", "Onion", "Pepper"], 1),
    ("Which internet company began as 'Backrub'? 🔍", ["Yahoo", "Google", "Bing", "DuckDuckGo"], 1),
    ("What is 15% of 200? 💯", ["20", "25", "30", "35"], 2),
    ("Which mythological creature breathes fire? 🐉", ["Unicorn", "Phoenix", "Dragon", "Griffin"], 2),
    ("What social science studies economies? 📊", ["Sociology", "Economics", "Psychology", "Geography"], 1),
    ("Which layer of Earth do we live on? 🌍", ["Mantle", "Core", "Crust", "Inner core"], 2),
    ("What year was the first iPhone released? 📱", ["2005", "2007", "2009", "2010"], 1),
    ("Which chemical element is a noble gas? 🎈", ["Chlorine", "Argon", "Sodium", "Calcium"], 1),
    ("What is the fastest land animal? 🐆", ["Lion", "Cheetah", "Tiger", "Leopard"], 1),
    ("What metric unit measures mass? ⚖️", ["Meter", "Liter", "Gram", "Watt"], 2),
    ("Which social media feature disappears after 24 hours? ⏳", ["Stories", "Posts", "Reels", "Tweets"], 0),
    ("What does 'RAM' stand for in computers? 💾", ["Read Access Memory", "Random Access Memory", "Rapid Array Module", "Read Array Memory"], 1),
    ("Which artist sang 'Thriller'? 🎤", ["Prince", "Michael Jackson", "Madonna", "Whitney Houston"], 1),
    ("What is the hardest natural substance? 💎", ["Steel", "Diamond", "Graphite", "Quartz"], 1),
    ("Which country invented paper? 📜", ["Egypt", "China", "Greece", "India"], 1),
    ("What part of speech describes an action? 📖", ["Noun", "Verb", "Adjective", "Adverb"], 1),
    ("Which web language structures content? 🖥️", ["CSS", "HTML", "JavaScript", "SQL"], 1),
    ("What is the boiling point of water at sea level in °C? 🌡️", ["90", "95", "100", "105"], 2),
    ("Which nutrient helps build muscle? 🥩", ["Carbohydrates", "Fats", "Proteins", "Vitamins"], 2),
    ("Who developed the theory of relativity? 🧠", ["Isaac Newton", "Galileo Galilei", "Albert Einstein", "Nikola Tesla"], 2),
    ("What file format is used for images on the web? 🖼️", [".docx", ".xlsx", ".png", ".pptx"], 2),
    ("Which social quiz tests your personality? 🧩", ["Math Master", "Geek Quiz", "Personality Test", "History Hunt"], 2),
    ("Which continent is the largest by land area? 🌍", ["Africa", "Asia", "Europe", "North America"], 1),
    ("What programming language is used for web styling? 🎨", ["HTML", "CSS", "JavaScript", "Python"], 1),
    ("What vitamin do you get from sunlight? ☀️", ["Vitamin A", "Vitamin B", "Vitamin C", "Vitamin D"], 3),
    ("Which famous scientist formulated the laws of motion? 🏃‍♂️", ["Galileo", "Einstein", "Newton", "Hawking"], 2),
    ("What gas do humans exhale? 😮‍💨", ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], 2),
    ("Which city is known as the Big Apple? 🍎", ["Los Angeles", "Chicago", "New York City", "Miami"], 2),
    ("What is the currency of Japan? 💴", ["Dollar", "Won", "Yen", "Euro"], 2),
    ("Which blood type is a universal donor? 🩸", ["A", "B", "AB", "O negative"], 3),
    ("What is the first element on the periodic table? 🔢", ["Hydrogen", "Helium", "Oxygen", "Carbon"], 0),
    ("What is the tallest mountain in the world? 🏔️", ["K2", "Kangchenjunga", "Mount Everest", "Makalu"], 2),
    ("What part of the plant conducts photosynthesis? 🌿", ["Roots", "Stem", "Leaves", "Flowers"], 2),
    ("Which tech company created the Android OS? 🤖", ["Apple", "Google", "Microsoft", "Samsung"], 1),
    ("Which continent is home to the Sahara Desert? 🏜️", ["Asia", "Africa", "Australia", "South America"], 1),
    ("What is the currency of the United Kingdom? 💷", ["Euro", "Dollar", "Pound", "Franc"], 2),
    ("What does DNA stand for? 🧬", ["Deoxyribonucleic Acid", "Dioxyribonucleic Acid", "Dioxyribose Acid", "Deoxyribose Amino"], 0),
    ("Which planet has the most moons? 🪐", ["Earth", "Mars", "Jupiter", "Saturn"], 3),
    ("Which animal is known for its black and white stripes? 🦓", ["Tiger", "Zebra", "Panda", "Skunk"], 1),
    ("What is the freezing point of water in Celsius? ❄️", ["0", "32", "-1", "100"], 0),
    ("Who was the first woman in space? 👩‍🚀", ["Sally Ride", "Mae Jemison", "Valentina Tereshkova", "Kalpana Chawla"], 2),
    ("Which tool is used to cut wood? 🪚", ["Hammer", "Saw", "Drill", "Screwdriver"], 1),
    ("What is the capital of Italy? 🇮🇹", ["Rome", "Milan", "Venice", "Naples"], 0),
    ("Which animal is the largest mammal? 🐋", ["Elephant", "Blue Whale", "Giraffe", "Hippopotamus"], 1),
    ("What does Wi-Fi stand for? 📶", ["Wireless Fidelity", "Wired Finance", "Wide Function", "Wireless Framework"], 0),
    ("Who discovered gravity by observing a falling apple? 🍏", ["Galileo", "Newton", "Einstein", "Tesla"], 1),
    ("What instrument is used to measure temperature? 🌡️", ["Barometer", "Thermometer", "Altimeter", "Speedometer"], 1),
    ("Which month has 28 days in common years? 📆", ["January", "February", "April", "June"], 1),
    ("Which social media app is known for short videos and dances? 🎵", ["Facebook", "Instagram", "TikTok", "Snapchat"], 2),
    ("What does a paleontologist study? 🦴", ["Stars", "Plants", "Fossils", "Oceans"], 2),
    ("Which programming language is used for data analysis? 📊", ["C#", "Java", "Python", "Swift"], 2),
    ("What is the main gas found in the air we breathe? 🌬️", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Hydrogen"], 2),
    ("Which color is made by mixing red and blue? 🎨", ["Orange", "Purple", "Green", "Brown"], 1),
    ("Which country is known for the Great Wall? 🏯", ["Japan", "Korea", "China", "India"], 2),
    ("What is the binary value of 5? 🧮", ["0101", "1010", "1000", "0010"], 0),
    ("Which continent has the most countries? 🌍", ["Europe", "Asia", "Africa", "South America"], 2),
    ("What does the 'www' stand for in a website URL? 🌐", ["World Web Window", "Wide Web World", "World Wide Web", "Web Window Work"], 2),
    ("What is the capital of Canada? 🍁", ["Toronto", "Ottawa", "Vancouver", "Montreal"], 1),
    ("Who is the author of 'Harry Potter'? 🧙‍♂️", ["J.R.R. Tolkien", "J.K. Rowling", "C.S. Lewis", "Stephen King"], 1),
    ("What type of energy comes from the sun? 🔆", ["Thermal", "Nuclear", "Solar", "Kinetic"], 2),
    ("Which organ is responsible for pumping blood? ❤️", ["Brain", "Lungs", "Liver", "Heart"], 3),
    ("Which is the longest river in the world? 🌊", ["Amazon", "Yangtze", "Mississippi", "Nile"], 3),
    ("What is a group of lions called? 🦁", ["Flock", "Pack", "Pride", "Herd"], 2),
    ("What is the chemical symbol for gold? 🪙", ["Gd", "Ag", "Au", "Go"], 2),
    ("What is the main function of white blood cells? 🦠", ["Carry oxygen", "Fight infection", "Clot blood", "Store nutrients"], 1),
    ("Who invented the light bulb? 💡", ["Edison", "Tesla", "Newton", "Einstein"], 0),
    ("What is 1000 bytes called? 🧾", ["Gigabyte", "Megabyte", "Kilobyte", "Terabyte"], 2),
    ("What is a baby goat called? 🐐", ["Cub", "Kid", "Calf", "Foal"], 1),
    ("Which planet spins the fastest? 🌀", ["Earth", "Jupiter", "Mars", "Venus"], 1),
    ("What does a botanist study? 🌱", ["Insects", "Planets", "Plants", "Fossils"], 2),
    ("Which tool is used to find directions? 🧭", ["Barometer", "Thermometer", "Compass", "Odometer"], 2),
    ("What is the capital of Australia? 🇦🇺", ["Sydney", "Melbourne", "Canberra", "Perth"], 2),
    ("Which mammal lays eggs? 🥚", ["Kangaroo", "Dolphin", "Platypus", "Bat"], 2),
    ("Which scientist is famous for the three laws of motion? ⚖️", ["Einstein", "Galileo", "Newton", "Hawking"], 2),
    ("What is the capital of Germany? 🇩🇪", ["Berlin", "Munich", "Frankfurt", "Hamburg"], 0),
    ("Which planet has a day longer than its year? ⏳", ["Mercury", "Venus", "Mars", "Neptune"], 1),
    ("Which web language adds interactivity? 🧩", ["HTML", "CSS", "JavaScript", "PHP"], 2),
    ("What is the largest bone in the human body? 🦴", ["Humerus", "Femur", "Tibia", "Spine"], 1),
    ("What organ is responsible for filtering blood? 🩺", ["Liver", "Kidney", "Heart", "Lungs"], 1),
    ("Who is credited with inventing the telephone? ☎️", ["Edison", "Bell", "Tesla", "Marconi"], 1),
    ("Which U.S. state is known as the Sunshine State? 🌞", ["California", "Texas", "Florida", "Nevada"], 2),
    ("What is the capital of Russia? 🏰", ["Moscow", "St. Petersburg", "Kazan", "Sochi"], 0),
    ("Which gas is most abundant in Earth's atmosphere? 🌫️", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Hydrogen"], 2),
    ("Which planet is famous for its rings? 💍", ["Saturn", "Jupiter", "Neptune", "Uranus"], 0),
    ("Who created the theory of evolution by natural selection? 🧬", ["Darwin", "Mendel", "Lamarck", "Pasteur"], 0),
    ("What is the primary language spoken in Egypt? 🗣️", ["French", "English", "Arabic", "Spanish"], 2),
    ("Which famous ship sank in 1912? 🚢", ["Lusitania", "Titanic", "Endeavour", "Olympic"], 1),
    ("What is the study of weather called? 🌦️", ["Geology", "Meteorology", "Climatology", "Astronomy"], 1),
    ("Which planet is the smallest? 🪐", ["Mercury", "Mars", "Venus", "Pluto"], 0),
    ("What is the hardest known substance? 🧱", ["Quartz", "Iron", "Diamond", "Graphite"], 2),
    ("Which branch of science deals with living organisms? 🧫", ["Physics", "Biology", "Chemistry", "Astronomy"], 1),
    ("What is the most used search engine? 🔍", ["Bing", "Yahoo", "DuckDuckGo", "Google"], 3),
    ("Which language uses characters like あ, い, う? 🇯🇵", ["Korean", "Chinese", "Japanese", "Thai"], 2),
    ("What is a baby cat called? 🐱", ["Kit", "Cub", "Kitten", "Pup"], 2),
    ("What is the opposite of digital? 📼", ["Analog", "Virtual", "Visual", "Hybrid"], 0),
    ("Which app is known for photo filters and stories? 📸", ["TikTok", "Instagram", "Facebook", "X"], 1),
    ("Which ocean is between Africa and Australia? 🌍", ["Atlantic", "Arctic", "Indian", "Pacific"], 2),
    ("Which scientist developed the laws of planetary motion? 🪐", ["Newton", "Galileo", "Kepler", "Copernicus"], 2),
    ("What does the Richter scale measure? 📊", ["Temperature", "Wind speed", "Earthquake magnitude", "Rainfall"], 2),
    ("Which planet is known for the Great Red Spot? 🔴", ["Mars", "Saturn", "Jupiter", "Neptune"], 2),
    ("What organ helps you see? 👁️", ["Heart", "Brain", "Liver", "Eye"], 3),
    ("What shape has four equal sides and angles? ⏹️", ["Rectangle", "Triangle", "Square", "Rhombus"], 2),
    ("Which mobile OS is owned by Apple? 🍏", ["Android", "iOS", "Windows", "Harmony"], 1),
    ("What is the process of water turning into vapor? 💨", ["Condensation", "Evaporation", "Freezing", "Boiling"], 1),
    ("Which metal is liquid at room temperature? 🌡️", ["Iron", "Mercury", "Aluminum", "Zinc"], 1),
    ("Who invented the World Wide Web? 🌐", ["Bill Gates", "Tim Berners-Lee", "Steve Jobs", "Linus Torvalds"], 1),
    ("Which country has the maple leaf on its flag? 🍁", ["USA", "Canada", "UK", "Switzerland"], 1),
    ("Which body part helps pump blood? ❤️", ["Liver", "Kidney", "Heart", "Lung"], 2),
    ("What is 9 squared? 🔢", ["81", "72", "64", "91"], 0),
    ("Which is the largest internal organ? 🧍‍♂️", ["Heart", "Liver", "Kidney", "Lungs"], 1),
    ("What do we call animals that eat only plants? 🌾", ["Omnivores", "Carnivores", "Insectivores", "Herbivores"], 3),
    ("Which language is primarily spoken in Argentina? 🇦🇷", ["Portuguese", "Spanish", "English", "French"], 1),
    ("What number comes after a billion? 🔢", ["Trillion", "Zillion", "Million", "Quadrillion"], 0),
    ("What is the boiling point of water in Fahrenheit? 🔥", ["212", "100", "180", "250"], 0),
    ("Which instrument is used in geometry? 📐", ["Microscope", "Compass", "Telescope", "Scale"], 1),
    ("What’s the term for animals active at night? 🌙", ["Diurnal", "Nocturnal", "Crepuscular", "Subterranean"], 1),
    ("Which app has a ghost icon? 👻", ["Instagram", "Facebook", "Snapchat", "TikTok"], 2),
    ("Which landform is completely surrounded by water? 🏝️", ["Peninsula", "Island", "Isthmus", "Plateau"], 1),
    ("Which bird is known for mimicking sounds? 🦜", ["Sparrow", "Owl", "Parrot", "Pigeon"], 2),
    ("Which science deals with the study of the universe? 🌌", ["Biology", "Geology", "Astronomy", "Ecology"], 2),
    ("Which country hosted the 2020 Summer Olympics? 🏅", ["China", "Japan", "Brazil", "UK"], 1),
    ("What is the speed of light? ⚡", ["300,000 km/s", "150,000 km/s", "100,000 km/s", "1,000,000 km/s"], 0),
    ("Which planet is closest to the Sun? ☀️", ["Venus", "Earth", "Mercury", "Mars"], 2),
    ("Which body system controls your breathing? 🫁", ["Digestive", "Circulatory", "Respiratory", "Endocrine"], 2),
    ("What do bees collect from flowers? 🌸", ["Water", "Pollen", "Nectar", "Sap"], 2),
    ("What is the chemical symbol for water? 💧", ["H2O", "CO2", "NaCl", "O2"], 0),
    ("Which part of the brain controls balance? 🧠", ["Cerebrum", "Medulla", "Cerebellum", "Thalamus"], 2),
    ("What does the CPU stand for in computing? 🖥️", ["Central Program Unit", "Central Process Unit", "Central Processing Unit", "Core Program Unit"], 2),
    ("What is the capital of Spain? 🇪🇸", ["Barcelona", "Seville", "Madrid", "Valencia"], 2),
    ("Which vitamin is known for helping eyesight? 👀", ["A", "B", "C", "D"], 0),
    ("What is the smallest unit of life? 🧬", ["Organ", "Tissue", "Cell", "Molecule"], 2),
    ("Who painted the Mona Lisa? 🎨", ["Picasso", "Michelangelo", "Van Gogh", "Da Vinci"], 3),
    ("Which continent has the fewest countries? 🧭", ["Europe", "Antarctica", "Asia", "Australia"], 1),
    ("What is the capital of South Korea? 🇰🇷", ["Busan", "Incheon", "Seoul", "Daegu"], 2),
    ("What do we call a triangle with all equal sides? 🔺", ["Isosceles", "Scalene", "Equilateral", "Right"], 2),
    ("What is the study of rocks called? 🪨", ["Astronomy", "Ecology", "Geology", "Zoology"], 2),
    ("What organ produces insulin? 🍬", ["Liver", "Pancreas", "Kidney", "Stomach"], 1),
    ("Which social media app has a blue bird icon? 🐦", ["Facebook", "Instagram", "X (Twitter)", "Reddit"], 2),
    ("Which layer of Earth do we live on? 🌍", ["Core", "Mantle", "Crust", "Outer core"], 2),
    ("Which branch of math deals with shapes and space? 📐", ["Algebra", "Geometry", "Trigonometry", "Calculus"], 1),
    ("How many teeth does an adult human usually have? 😁", ["28", "30", "32", "34"], 2),
    ("What is the name of the galaxy we live in? 🌌", ["Andromeda", "Milky Way", "Alpha Centauri", "Orion"], 1),
    ("Which mammal can fly? 🦇", ["Penguin", "Bat", "Flying Squirrel", "Ostrich"], 1),
    ("What is the process of turning solid to gas called? 💨", ["Melting", "Freezing", "Sublimation", "Condensation"], 2),
    ("Which ancient civilization built the pyramids? 🏺", ["Romans", "Greeks", "Aztecs", "Egyptians"], 3),
    ("What gas do plants absorb from the air? 🌿", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Hydrogen"], 1),
    ("What does 'CPU' stand for in tech? 🧠", ["Computer Power Unit", "Central Performance Unit", "Central Processing Unit", "Core Performance Unit"], 2),
    ("Which app is owned by Meta? 📱", ["TikTok", "Snapchat", "Instagram", "Telegram"], 2),
    ("What’s the main ingredient in guacamole? 🥑", ["Lettuce", "Avocado", "Tomato", "Spinach"], 1),
    ("Which country is shaped like a boot? 👢", ["France", "Italy", "Spain", "Portugal"], 1),
    ("What is the study of the mind and behavior? 🧠", ["Neurology", "Psychology", "Biology", "Sociology"], 1),
    ("What tool helps you access websites? 🌐", ["Spreadsheet", "Search Engine", "Compiler", "IDE"], 1),
    ("What’s the tallest building in the world (as of 2025)? 🏙️", ["Shanghai Tower", "Burj Khalifa", "One World Trade", "Taipei 101"], 1),
    ("Which animal is known as man's best friend? 🐶", ["Cat", "Horse", "Dog", "Bird"], 2),
    ("What do you call a word that is the same forward and backward? 🔁", ["Acronym", "Palindrome", "Antonym", "Homonym"], 1),
    ("How many colors are in a rainbow? 🌈", ["5", "6", "7", "8"], 2),
    ("What does HTTP stand for? 🛜", ["Hypertext Transfer Protocol", "High-Tech Text Processing", "Host Transfer Tool Protocol", "Hyperlink Tracking Protocol"], 0),
    ("What is the boiling point of water in Celsius? 🌡️", ["0", "50", "100", "200"], 2),
    ("Which country has the most population? 👥", ["USA", "China", "India", "Indonesia"], 2),
    ("Which invention lets you see faraway objects? 🔭", ["Microscope", "Telescope", "Camera", "Projector"], 1),
    ("Which type of energy is stored in food? 🍽️", ["Nuclear", "Chemical", "Thermal", "Kinetic"], 1),
    ("What device converts sound into electrical signals? 🎙️", ["Speaker", "Microphone", "Antenna", "Receiver"], 1),
    ("What is 10 multiplied by 10? ✖️", ["100", "20", "110", "10"], 0),
    ("Which gas do humans need to survive? 🌬️", ["Carbon", "Oxygen", "Hydrogen", "Nitrogen"], 1),
    ("What is the capital of France? 🇫🇷", ["Rome", "Berlin", "Paris", "Madrid"], 2),
    ("What sense is associated with the nose? 👃", ["Hearing", "Smell", "Taste", "Touch"], 1),
    ("Which shape has three sides? 🔺", ["Circle", "Rectangle", "Triangle", "Hexagon"], 2),
    ("What is the term for frozen water? ❄️", ["Steam", "Vapor", "Ice", "Fog"], 2),
    ("Which instrument is used to look at stars? 🌟", ["Microscope", "Telescope", "Stethoscope", "Compass"], 1),
    ("What is a young dog called? 🐕", ["Cub", "Kit", "Pup", "Foal"], 2),
    ("Which field involves computer algorithms and logic? 💻", ["Biology", "Chemistry", "Computer Science", "Geography"], 2),
    ("What is the main gas found in the air we breathe? 🌬️", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Hydrogen"], 2),
    ("Which instrument measures temperature? 🌡️", ["Barometer", "Thermometer", "Hygrometer", "Altimeter"], 1),
    ("Who wrote 'Romeo and Juliet'? 🎭", ["Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain"], 1),
    ("Which blood type is known as the universal donor? 🩸", ["O-", "AB+", "A+", "B-"], 0),
    ("What is the largest ocean on Earth? 🌊", ["Atlantic", "Indian", "Pacific", "Arctic"], 2),
    ("Which shape has eight sides? 🛑", ["Hexagon", "Octagon", "Pentagon", "Heptagon"], 1),
    ("What is the currency of Japan? 💴", ["Yuan", "Won", "Yen", "Ringgit"], 2),
    ("Which planet is known as the 'Morning Star'? 🌟", ["Mars", "Venus", "Jupiter", "Saturn"], 1),
    ("Which programming language is named after a snake? 🐍", ["Java", "C++", "Python", "Ruby"], 2),
    ("What part of the plant conducts photosynthesis? 🌿", ["Stem", "Root", "Leaf", "Flower"], 2),
    ("How many continents are there? 🌍", ["5", "6", "7", "8"], 2),
    ("What is the powerhouse of the cell? 🔋", ["Nucleus", "Mitochondria", "Ribosome", "Chloroplast"], 1),
    ("Which bird is the symbol of peace? 🕊️", ["Crow", "Dove", "Eagle", "Swan"], 1),
    ("What type of animal is a frog? 🐸", ["Reptile", "Bird", "Mammal", "Amphibian"], 3),
    ("Which part of the computer shows visual output? 🖥️", ["CPU", "Monitor", "Mouse", "Hard Drive"], 1),
    ("Which festival is known as the Festival of Lights? 🪔", ["Christmas", "Hanukkah", "Eid", "Diwali"], 3),
    ("What do you call a person who studies space? 🚀", ["Astronomer", "Geologist", "Physicist", "Biologist"], 0),
    ("How many hours are in a day? ⏰", ["24", "12", "48", "36"], 0),
    ("What is the capital of Australia? 🇦🇺", ["Sydney", "Melbourne", "Canberra", "Perth"], 2),
    ("Which is the largest planet in the solar system? 🪐", ["Earth", "Saturn", "Neptune", "Jupiter"], 3),
    ("What is a group of lions called? 🦁", ["Pack", "Flock", "Herd", "Pride"], 3),
    ("What color is chlorophyll? 💚", ["Red", "Yellow", "Green", "Blue"], 2),
    ("What is the freezing point of water in Celsius? 🧊", ["0", "100", "-10", "10"], 0),
    ("Which language is used for Android app development? 📱", ["Swift", "Java", "C#", "Kotlin"], 3),
    ("Which planet is tilted on its side? 🌀", ["Neptune", "Uranus", "Jupiter", "Mars"], 1),
    ("What is the longest river in the world? 🌎", ["Amazon", "Nile", "Yangtze", "Mississippi"], 1),
    ("Which famous scientist developed relativity? 🧠", ["Einstein", "Newton", "Tesla", "Edison"], 0),
    ("Which human organ is responsible for hearing? 👂", ["Eye", "Nose", "Ear", "Skin"], 2),
    ("What is the capital city of Canada? 🇨🇦", ["Toronto", "Ottawa", "Montreal", "Vancouver"], 1),
    ("Which energy source is renewable? ⚡", ["Coal", "Oil", "Wind", "Gas"], 2),
    ("What is the antonym of 'hot'? ❄️", ["Cold", "Warm", "Boiling", "Cool"], 0),
    ("Which metal is most used in electrical wiring? 🔌", ["Iron", "Steel", "Aluminum", "Copper"], 3),
    ("What is a synonym for 'happy'? 😊", ["Sad", "Joyful", "Angry", "Tired"], 1),
    ("Which part of the eye controls how much light enters? 👁️", ["Retina", "Pupil", "Lens", "Cornea"], 1),
    ("Which country is famous for the Eiffel Tower? 🗼", ["Italy", "France", "Spain", "Germany"], 1),
    ("What type of cloud is fluffy and white? ☁️", ["Cumulus", "Stratus", "Cirrus", "Nimbus"], 0),
    ("How many seconds are in one minute? ⏱️", ["100", "30", "60", "120"], 2),
    ("Which device is used to take photos? 📷", ["Printer", "Camera", "Microscope", "Scanner"], 1),
    ("What is the term for animals that eat both plants and meat? 🍖", ["Herbivore", "Carnivore", "Omnivore", "Insectivore"], 2),
    ("Who painted the ceiling of the Sistine Chapel? 🖌️", ["Da Vinci", "Michelangelo", "Van Gogh", "Picasso"], 1),
    ("What do plants give off during photosynthesis? 🌱", ["CO2", "Oxygen", "Hydrogen", "Nitrogen"], 1),
    ("Which subject deals with the study of matter? 🧪", ["Biology", "Physics", "Chemistry", "Astronomy"], 2),
    ("Which natural satellite orbits the Earth? 🌕", ["Mars", "The Moon", "Venus", "Sun"], 1),
    ("What is the study of ancient cultures called? 🏺", ["Sociology", "Geology", "Anthropology", "Archaeology"], 3),
    ("What is a polygon with five sides called? 🔷", ["Hexagon", "Octagon", "Pentagon", "Heptagon"], 2),
    ("What do we call molten rock that erupts from a volcano? 🌋", ["Lava", "Magma", "Ash", "Sediment"], 0),
    ("Which branch of science deals with energy and forces? 💥", ["Biology", "Chemistry", "Physics", "Botany"], 2),
    ("How many milliliters are in a liter? 🧪", ["10", "100", "500", "1000"], 3),
    ("Which animal is known for changing its color? 🦎", ["Octopus", "Chameleon", "Frog", "Cuttlefish"], 1),
    ("What is the name of the process plants use to make food? 🌞", ["Digestion", "Fermentation", "Photosynthesis", "Respiration"], 2),
    ("Which gas is released when we breathe out? 😮‍💨", ["Oxygen", "Nitrogen", "Carbon Dioxide", "Hydrogen"], 2),
    ("What do we call a baby cat? 🐱", ["Cub", "Kitten", "Pup", "Chick"], 1),
    ("What type of energy comes from the sun? ☀️", ["Thermal", "Solar", "Nuclear", "Kinetic"], 1),
    ("Which is the smallest prime number? 🔢", ["0", "1", "2", "3"], 2),
    ("What is the study of weather called? 🌦️", ["Geology", "Climatology", "Meteorology", "Oceanography"], 2),
    ("How many strings does a standard guitar have? 🎸", ["4", "5", "6", "7"], 2),
    ("Which continent is the Sahara Desert located in? 🏜️", ["Asia", "Africa", "Australia", "South America"], 1),
    ("What is the longest bone in the human body? 🦴", ["Spine", "Femur", "Tibia", "Humerus"], 1),
    ("Which country invented pizza? 🍕", ["France", "Greece", "USA", "Italy"], 3),
    ("What is H2SO4 commonly known as? 🧪", ["Hydrochloric acid", "Sulfuric acid", "Nitric acid", "Acetic acid"], 1),
    ("What is the center of an atom called? ⚛️", ["Electron", "Proton", "Neutron", "Nucleus"], 3),
    ("Which scientist proposed the three laws of motion? 🧠", ["Einstein", "Newton", "Kepler", "Galileo"], 1),
    ("Which part of the computer stores data permanently? 💾", ["RAM", "CPU", "ROM", "Hard Drive"], 3),
    ("What is the square root of 81? ✔️", ["7", "8", "9", "10"], 2),
    ("Which sense is strongest in dogs? 🐾", ["Sight", "Smell", "Taste", "Hearing"], 1),
    ("What is the capital of Germany? 🇩🇪", ["Berlin", "Frankfurt", "Munich", "Hamburg"], 0),
    ("What is the speed of light? ⚡", ["3x10^8 m/s", "3x10^5 m/s", "1.5x10^6 m/s", "2x10^4 m/s"], 0),
    ("What is a triangle with one 90-degree angle called? 📐", ["Acute", "Obtuse", "Right", "Scalene"], 2),
    ("What tool helps programmers write code? 💻", ["Word Processor", "Spreadsheet", "IDE", "Browser"], 2),
    ("Which musical instrument has black and white keys? 🎹", ["Guitar", "Flute", "Drum", "Piano"], 3),
    ("What is 3 cubed (3³)? 🧮", ["6", "9", "27", "81"], 2),
    ("Which country is known for the Taj Mahal? 🕌", ["India", "Pakistan", "Bangladesh", "Iran"], 0),
    ("What does DNA stand for? 🧬", ["Digital Network Access", "Data Numeric Algorithm", "Deoxyribonucleic Acid", "None of these"], 2),
    ("Which animal lives both in water and on land? 🐸", ["Fish", "Frog", "Lizard", "Bird"], 1),
    ("How many legs does an insect have? 🐞", ["4", "6", "8", "10"], 1),
    ("What is the result of 7 × 8? ➗", ["56", "48", "64", "63"], 0),
    ("What is the boiling point of water in Fahrenheit? 🔥", ["100°F", "180°F", "212°F", "220°F"], 2),
    ("Which part of the body helps you move? 💪", ["Muscles", "Skin", "Hair", "Nails"], 0),
    ("What is the process of water vapor turning into liquid? 💧", ["Evaporation", "Freezing", "Condensation", "Melting"], 2),
    ("What type of rock is formed from lava? 🌋", ["Sedimentary", "Metamorphic", "Igneous", "Fossil"], 2),
    ("Which month has 28 or 29 days? 📅", ["January", "February", "March", "April"], 1),
    ("Who is known as the 'Father of Computers'? 🖥️", ["Bill Gates", "Charles Babbage", "Alan Turing", "Steve Jobs"], 1),
    ("Which planet has the most moons? 🪐", ["Earth", "Mars", "Jupiter", "Venus"], 2),
    ("What number is represented by the Roman numeral X? 🔟", ["5", "10", "50", "100"], 1),
    ("Which force pulls objects toward the Earth? 🌎", ["Magnetism", "Electricity", "Friction", "Gravity"], 3),
    ("Which is not a primary color? 🎨", ["Red", "Green", "Blue", "Yellow"], 1),
    ("What kind of animal is a penguin? 🐧", ["Mammal", "Reptile", "Bird", "Fish"], 2),
    ("What does www stand for in a website address? 🌐", ["Web World Wide", "World Web Wide", "World Wide Web", "Wide World Web"], 2),
    ("Which direction does the sun rise from? 🌅", ["North", "South", "East", "West"], 2),
    ("Which device is used to measure weight? ⚖️", ["Thermometer", "Scale", "Barometer", "Timer"], 1),
    ("How many bones are in the adult human body? 🦴", ["206", "208", "210", "212"], 0),
    ("Which color absorbs the most light? 🖤", ["White", "Red", "Yellow", "Black"], 3),
    ("Which science deals with classifying organisms? 🔬", ["Botany", "Taxonomy", "Zoology", "Genetics"], 1),
    ("Which country is known for Mount Fuji? 🗻", ["China", "Japan", "Nepal", "South Korea"], 1),
    ("Which part of the plant absorbs water? 🌱", ["Leaf", "Root", "Stem", "Flower"], 1),
    ("How many planets are there in our solar system (2025)? 🪐", ["7", "8", "9", "10"], 1),
    ("What is the opposite of 'minimum'? 🔁", ["Mean", "Small", "Maximum", "Equal"], 2),
    ("Which app uses disappearing messages and ghost logo? 👻", ["Instagram", "Facebook", "Snapchat", "Telegram"], 2),
    ("What do you call someone who writes computer code? 👨‍💻", ["Designer", "Editor", "Coder", "Technician"], 2),
    ("What does HTML stand for? 🌐", ["Hyper Text Makeup Language", "Hyper Transfer Markup Language", "Hyper Text Markup Language", "Hyper Tag Machine Language"], 2),
    ("Which vitamin is produced when sunlight hits the skin? 🌞", ["Vitamin A", "Vitamin B", "Vitamin C", "Vitamin D"], 3),
    ("What unit is used to measure electric current? 🔌", ["Ohm", "Volt", "Watt", "Ampere"], 3),
    ("Which ocean is the deepest in the world? 🌊", ["Atlantic", "Indian", "Southern", "Pacific"], 3),
    ("Who was the first person to walk on the moon? 🌕", ["Buzz Aldrin", "Yuri Gagarin", "Neil Armstrong", "Michael Collins"], 2),
    ("Which device converts sound to digital signals? 🎙️", ["Speaker", "Microphone", "Camera", "Antenna"], 1),
    ("Which country is the largest by land area? 🌍", ["USA", "Canada", "China", "Russia"], 3),
    ("How many teeth does an adult human have? 😁", ["30", "32", "34", "28"], 1),
    ("What color do you get when you mix red and white? 🎨", ["Pink", "Orange", "Purple", "Beige"], 0),
    ("What organ helps filter blood in the human body? 🩸", ["Heart", "Lungs", "Liver", "Kidneys"], 3),
    ("How many planets have rings in our solar system? 💍", ["1", "2", "4", "5"], 2),
    ("Which continent has the most countries? 🗺️", ["Asia", "Africa", "Europe", "South America"], 1),
    ("What is the capital of Spain? 🇪🇸", ["Barcelona", "Madrid", "Seville", "Valencia"], 1),
    ("What’s the process by which ice turns into water? 💧", ["Evaporation", "Freezing", "Condensation", "Melting"], 3),
    ("Which animal is known as the 'King of the Jungle'? 👑", ["Tiger", "Elephant", "Lion", "Leopard"], 2),
    ("What does CPU stand for? 🧠", ["Central Processing Unit", "Computer Power Unit", "Control Process Unit", "Central Print Unit"], 0),
    ("Which planet has the most visible rings? 💫", ["Jupiter", "Uranus", "Neptune", "Saturn"], 3),
    ("Which is the smallest continent by land area? 🌏", ["Europe", "Australia", "Antarctica", "South America"], 1),
    ("Which sense is associated with the tongue? 👅", ["Sight", "Taste", "Touch", "Smell"], 1),
    ("What is the chemical symbol for water? 💦", ["H", "H2O", "HO", "O2"], 1),
    ("Who is the founder of Microsoft? 💼", ["Steve Jobs", "Bill Gates", "Mark Zuckerberg", "Elon Musk"], 1),
    ("What does Wi-Fi stand for? 📶", ["Wireless Fidelity", "Wide Frequency", "Wired Fiber", "Wave Internet"], 0),
    ("Which bone protects the brain? 🧠", ["Femur", "Skull", "Rib", "Spine"], 1),
    ("What is a young dog called? 🐶", ["Cub", "Kitten", "Pup", "Foal"], 2),
    ("Which is the closest star to Earth? ⭐", ["Polaris", "Sirius", "Sun", "Alpha Centauri"], 2),
    ("What is the name of the largest rainforest? 🌳", ["Amazon", "Congo", "Daintree", "Taiga"], 0),
    ("What is the term for animals that eat only plants? 🥬", ["Omnivore", "Herbivore", "Carnivore", "Frugivore"], 1),
    ("How many zeros are in one million? 0️⃣", ["4", "5", "6", "7"], 2),
    ("Which country is known as the Land of the Rising Sun? 🌅", ["China", "Japan", "South Korea", "Thailand"], 1),
    ("What type of blood cells help fight infections? 🦠", ["Red", "Platelets", "White", "Plasma"], 2),
    ("Which programming language is mainly used for web development? 💻", ["Python", "C", "JavaScript", "C++"], 2),
    ("Which gas do plants absorb from the air? 🌬️", ["Oxygen", "Carbon Dioxide", "Hydrogen", "Nitrogen"], 1),
    ("How many sides does a hexagon have? 🔷", ["5", "6", "7", "8"], 1),
    ("Which is the highest mountain in the world? 🏔️", ["Mount Everest", "K2", "Kangchenjunga", "Lhotse"], 0),
    ("How many days are there in a leap year? 📆", ["365", "366", "364", "367"], 1),
    ("Which element is used in pencils? ✏️", ["Graphite", "Charcoal", "Carbon", "Lead"], 0),
    ("What is the main ingredient in bread? 🍞", ["Rice", "Flour", "Corn", "Salt"], 1),
    ("Which is the largest internal organ in the human body? 🧍", ["Heart", "Liver", "Lungs", "Intestines"], 1),
    ("Which programming language is used in data analysis? 📊", ["HTML", "Python", "CSS", "Java"], 1),
    ("How many bytes are in a kilobyte? 🧾", ["512", "1000", "1024", "2048"], 2),
    ("What is the name for molten rock inside the Earth? 🌎", ["Lava", "Magma", "Slag", "Sediment"], 1),
    ("Which planet has the shortest day? ⏱️", ["Earth", "Mars", "Jupiter", "Venus"], 2),
    ("What’s the national sport of Japan? 🥋", ["Karate", "Sumo Wrestling", "Judo", "Baseball"], 1),
    ("What does HTTP stand for? 🌐", ["Hyper Transfer Text Protocol", "Hyper Text Transfer Protocol", "High Text Transfer Process", "Hyper Tag Transfer Protocol"], 1),
    ("Which continent is the coldest? 🧊", ["North America", "Europe", "Antarctica", "Asia"], 2),
    ("How many hearts does an octopus have? 🐙", ["1", "2", "3", "4"], 2),
    ("What do you call software that harms your computer? 🦠", ["Antivirus", "Malware", "Firewall", "Driver"], 1),
    ("What is the capital of South Korea? 🇰🇷", ["Busan", "Seoul", "Incheon", "Daegu"], 1),
    ("Which color is formed by mixing blue and yellow? 🎨", ["Orange", "Green", "Purple", "Brown"], 1),
    ("Which language is the most spoken worldwide? 🗣️", ["English", "Spanish", "Mandarin", "Hindi"], 2),
    ("What is the fastest land animal? 🐆", ["Lion", "Cheetah", "Horse", "Jaguar"], 1),
    ("Which gas is most abundant in Earth's atmosphere? 🌍", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Hydrogen"], 2),
    ("What instrument measures temperature? 🌡️", ["Barometer", "Thermometer", "Altimeter", "Compass"], 1),
    ("What does URL stand for? 🔗", ["Universal Resource Locator", "Uniform Resource Locator", "Unified Reference Line", "Universal Reference Line"], 1),
    ("Which part of the brain controls balance? 🧠", ["Cerebrum", "Medulla", "Cerebellum", "Hypothalamus"], 2),
    ("Which planet is known for its beautiful rings? 💍", ["Earth", "Venus", "Mars", "Saturn"], 3),
    ("Which organ is responsible for pumping blood? ❤️", ["Lungs", "Heart", "Liver", "Kidney"], 1),
    ("Which continent is the largest by area? 🌎", ["Africa", "Asia", "Europe", "North America"], 1),
    ("What is the boiling point of water in Celsius? 💧", ["90°C", "95°C", "100°C", "105°C"], 2),
    ("What is the currency of the United Kingdom? 💷", ["Euro", "Dollar", "Pound", "Franc"], 2),
    ("What does PDF stand for? 📄", ["Portable Data File", "Public Document Format", "Printable Document Format", "Portable Document Format"], 3),
    ("Which sense is responsible for detecting sound? 👂", ["Sight", "Taste", "Touch", "Hearing"], 3),
    ("What is the capital of Canada? 🇨🇦", ["Toronto", "Vancouver", "Ottawa", "Montreal"], 2),
    ("How many hours are there in a day? 🕒", ["12", "24", "18", "20"], 1),
    ("What is the term for a word that imitates a sound? 🔊", ["Simile", "Alliteration", "Onomatopoeia", "Hyperbole"], 2),
    ("Which animal is known for building dams? 🦫", ["Otter", "Beaver", "Raccoon", "Mole"], 1),
    ("Which country hosted the 2020 Summer Olympics? 🏅", ["China", "Japan", "Brazil", "USA"], 1),
    ("What is the main gas found in the air we breathe? 💨", ["Oxygen", "Carbon", "Nitrogen", "Hydrogen"], 2),
    ("Which element has the atomic number 1? 🧪", ["Oxygen", "Hydrogen", "Helium", "Carbon"], 1),
    ("What do you call a group of stars forming a pattern? ✨", ["Cluster", "Nebula", "Galaxy", "Constellation"], 3),
    ("What kind of animal is a Komodo dragon? 🐉", ["Mammal", "Reptile", "Amphibian", "Fish"], 1),
    ("Which human organ produces insulin? 🍬", ["Liver", "Pancreas", "Kidney", "Stomach"], 1),
    ("What is the most used social media platform globally (as of 2025)? 📱", ["Instagram", "Facebook", "TikTok", "WhatsApp"], 1),
    ("Which insect has a lifespan of only 24 hours? 🦟", ["Ant", "Butterfly", "Mayfly", "Bee"], 2),
    ("What is the currency of Japan? 💴", ["Yuan", "Won", "Yen", "Ringgit"], 2),
    ("What does RAM stand for in computing? 🧠", ["Read Access Memory", "Random Access Memory", "Read Allocation Memory", "Random Allocation Module"], 1),
    ("Which metal is liquid at room temperature? 🌡️", ["Gold", "Mercury", "Iron", "Aluminum"], 1),
    ("Which invention is Thomas Edison famous for? 💡", ["Telephone", "Computer", "Television", "Light Bulb"], 3),
    ("What is the main ingredient in sushi? 🍣", ["Bread", "Rice", "Fish", "Noodles"], 1),
    ("How many centimeters are there in a meter? 📏", ["10", "100", "1000", "10000"], 1),
    ("Which type of computer memory is non-volatile? 💾", ["RAM", "Cache", "ROM", "Register"], 2),
    ("Which is the smallest unit of matter? ⚛️", ["Molecule", "Atom", "Cell", "Electron"], 1),
    ("Who painted the Mona Lisa? 🖼️", ["Van Gogh", "Da Vinci", "Picasso", "Michelangelo"], 1),
    ("What does LAN stand for? 🌐", ["Long Area Network", "Local Access Network", "Local Area Network", "Large Area Network"], 2),
    ("What is a synonym for 'quick'? ⏩", ["Slow", "Rapid", "Hard", "Late"], 1),
    ("Which part of the cell contains genetic material? 🧬", ["Cytoplasm", "Mitochondria", "Nucleus", "Ribosome"], 2),
    ("What is the freezing point of water in Celsius? ❄️", ["0°C", "-10°C", "32°C", "4°C"], 0),
    ("Which country is famous for Eiffel Tower? 🗼", ["Germany", "Italy", "France", "Spain"], 2),
    ("Which app is primarily used for video meetings? 🎥", ["Slack", "Zoom", "Spotify", "Telegram"], 1),
    ("What is the plural form of 'mouse'? 🐭", ["Mouses", "Mice", "Mouse", "Mices"], 1),
    ("What kind of energy does a moving object have? 🔋", ["Potential", "Thermal", "Kinetic", "Nuclear"], 2),
    ("How many continents are there in the world? 🌍", ["5", "6", "7", "8"], 2),
    ("What is the capital of Australia? 🇦🇺", ["Sydney", "Melbourne", "Canberra", "Brisbane"], 2),
    ("Which shape has three sides? 🔺", ["Square", "Triangle", "Rectangle", "Pentagon"], 1),
    ("Which is the second largest planet in our solar system? 🪐", ["Earth", "Uranus", "Neptune", "Saturn"], 3),
    ("Which punctuation is used at the end of a question? ❓", ["!", ".", ",", "?"], 3),
    ("What is the name of the galaxy we live in? 🌌", ["Andromeda", "Milky Way", "Whirlpool", "Sombrero"], 1),
    ("What animal is known for its black and white stripes? 🦓", ["Zebra", "Tiger", "Cow", "Skunk"], 0),
    ("Which scientist developed the theory of relativity? 🧠", ["Isaac Newton", "Albert Einstein", "Nikola Tesla", "Galileo"], 1),
    ("How many planets are there in our solar system? 🪐", ["7", "8", "9", "10"], 1),
    ("Which bird is known for its colorful tail feathers? 🦚", ["Ostrich", "Peacock", "Parrot", "Swan"], 1),
    ("What part of the plant conducts photosynthesis? 🌿", ["Root", "Stem", "Leaf", "Flower"], 2),
    ("What is the square root of 64? ➗", ["6", "7", "8", "9"], 2),
    ("Which is the longest river in the world? 🌊", ["Amazon", "Nile", "Yangtze", "Mississippi"], 1),
    ("How many continents touch the Arctic Ocean? ❄️", ["1", "2", "3", "4"], 2),
    ("Which programming language is developed by Google? 🧑‍💻", ["Python", "Rust", "Go", "Ruby"], 2),
    ("How many minutes are in two hours? ⏰", ["60", "90", "100", "120"], 3),
    ("Which fruit is known to float in water? 🍏", ["Banana", "Apple", "Mango", "Pear"], 1),
    ("Which field of science studies forces and motion? 🧲", ["Chemistry", "Biology", "Physics", "Geology"], 2),
    ("What is the capital of Italy? 🇮🇹", ["Rome", "Venice", "Florence", "Milan"], 0),
    ("What is the freezing point of water in Fahrenheit? 🧊", ["32°F", "0°F", "100°F", "50°F"], 0),
    ("Which muscle pumps blood throughout the body? 💓", ["Lungs", "Brain", "Heart", "Kidney"], 2),
    ("Which shape has four equal sides and angles? 🔳", ["Rectangle", "Rhombus", "Trapezoid", "Square"], 3),
    ("What do bees collect from flowers? 🌼", ["Nectar", "Seeds", "Water", "Pollen"], 0),
    ("Which is the most commonly used search engine? 🔍", ["Bing", "Yahoo", "DuckDuckGo", "Google"], 3),
    ("How many digits are in the number 'one thousand'? 🔢", ["3", "4", "5", "6"], 1),
    ("Which ocean lies between Africa and Australia? 🌍", ["Atlantic", "Pacific", "Indian", "Southern"], 2),
    ("What planet is third from the Sun? ☀️", ["Mercury", "Venus", "Earth", "Mars"], 2),
    ("What is the tallest animal in the world? 🦒", ["Elephant", "Giraffe", "Horse", "Camel"], 1),
    ("What is the process of water changing to vapor? 💨", ["Condensation", "Evaporation", "Freezing", "Precipitation"], 1),
    ("What is the capital city of Egypt? 🏛️", ["Cairo", "Alexandria", "Luxor", "Giza"], 0),
    ("Which planet is closest to the Sun? 🔥", ["Venus", "Earth", "Mars", "Mercury"], 3),
    ("What part of the cell is known as the powerhouse? ⚡", ["Nucleus", "Mitochondria", "Ribosome", "Golgi Apparatus"], 1),
    ("Which country is home to the Great Wall? 🏯", ["Japan", "China", "India", "Korea"], 1),
    ("Which month has the fewest days? 📅", ["January", "February", "April", "June"], 1),
    ("What tool is used to measure weight? ⚖️", ["Thermometer", "Barometer", "Scale", "Compass"], 2),
    ("How many states are there in the United States? 🇺🇸", ["48", "49", "50", "52"], 2),
    ("Which animal is known for its slow movement? 🐢", ["Kangaroo", "Rabbit", "Sloth", "Deer"], 2),
    ("Which programming language is best for AI? 🧠", ["HTML", "Python", "CSS", "C"], 1),
    ("What is the main function of roots in plants? 🌱", ["Photosynthesis", "Support", "Reproduction", "Absorption"], 3),
    ("How many bones are in the adult human body? 🦴", ["202", "206", "210", "215"], 1),
    ("Which is the most populated country in the world? 🌏", ["USA", "India", "China", "Indonesia"], 1),
    ("What is the capital of Germany? 🇩🇪", ["Munich", "Hamburg", "Frankfurt", "Berlin"], 3),
    ("Which continent is known as the Dark Continent? 🌍", ["Asia", "Africa", "Europe", "Australia"], 1),
    ("Which part of the human eye controls light entry? 👁️", ["Lens", "Cornea", "Iris", "Retina"], 2),
    ("How many letters are in the English alphabet? 🔠", ["24", "25", "26", "27"], 2),
    ("Which blood type is considered the universal donor? 🩸", ["A", "B", "O-", "AB+"], 2),
    ("What is the official language of Brazil? 🇧🇷", ["Spanish", "English", "Portuguese", "French"], 2),
    ("Which type of energy comes from the sun? 🌞", ["Thermal", "Kinetic", "Solar", "Nuclear"], 2),
    ("What is the hardest natural substance? 💎", ["Gold", "Iron", "Diamond", "Steel"], 2),
    ("Which continent has the least population? 🧊", ["Europe", "Australia", "Antarctica", "South America"], 2),
    ("How many players are on a soccer team on the field? ⚽", ["9", "10", "11", "12"], 2),
    ("What is the largest mammal on Earth? 🐋", ["Elephant", "Blue Whale", "Giraffe", "Hippopotamus"], 1),
    ("Which country invented paper? 📜", ["Greece", "India", "China", "Egypt"], 2),
    ("How many hearts does a squid have? 🦑", ["1", "2", "3", "4"], 2),
    ("What does ATM stand for? 🏧", ["All Time Machine", "Any Time Money", "Automated Teller Machine", "Advanced Transaction Module"], 2),
    ("Which planet is known for its red appearance? 🔴", ["Mars", "Jupiter", "Venus", "Mercury"], 0),
    ("Which gas do plants absorb from the atmosphere? 🌿", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Helium"], 1),
    ("What does HTML stand for? 💻", ["HyperText Markup Language", "Hyper Transfer Machine Language", "HyperTabular Markup Language", "HighText Machine Language"], 0),
    ("How many planets have rings in our solar system? 🪐", ["2", "3", "4", "5"], 2),
    ("What is the chemical formula for water? 💧", ["H2O", "HO2", "OH2", "H2"], 0),
    ("Which country has the most official languages? 🌐", ["India", "Switzerland", "South Africa", "Canada"], 2),
    ("What is the capital of South Korea? 🇰🇷", ["Busan", "Incheon", "Seoul", "Daegu"], 2),
    ("Which computer key is used to cancel an operation? ⛔", ["Enter", "Shift", "Escape", "Ctrl"], 2),
    ("Which planet has the strongest gravity? 🧲", ["Earth", "Jupiter", "Saturn", "Neptune"], 1),
    ("What is the largest internal organ in the human body? 🧍", ["Liver", "Heart", "Lungs", "Stomach"], 0),
    ("What does USB stand for? 🔌", ["Universal Serial Bus", "Ultra Standard Block", "United Signal Base", "Universal Signal Board"], 0),
    ("Which vitamin is produced when exposed to sunlight? 🌞", ["Vitamin A", "Vitamin B", "Vitamin C", "Vitamin D"], 3),
    ("What type of animal is a dolphin? 🐬", ["Fish", "Mammal", "Reptile", "Bird"], 1),
    ("Which city is known as the City of Light? 🌆", ["London", "Rome", "Paris", "Berlin"], 2),
    ("Which continent is the Sahara Desert located in? 🏜️", ["Asia", "Africa", "Australia", "Europe"], 1),
    ("What tool is used to measure earthquakes? 🌍", ["Thermometer", "Barometer", "Seismograph", "Altimeter"], 2),
    ("What is the largest island in the world? 🏝️", ["Australia", "Greenland", "Madagascar", "Borneo"], 1),
    ("Which is the smallest prime number? 🔢", ["0", "1", "2", "3"], 2),
    ("What is the fastest marine animal? 🐠", ["Dolphin", "Tuna", "Marlin", "Sailfish"], 3),
    ("Which gas is used in balloons to make them float? 🎈", ["Oxygen", "Hydrogen", "Helium", "Carbon Dioxide"], 2),
    ("Which continent has no countries? ❄️", ["Antarctica", "Australia", "Africa", "Europe"], 0),
    ("What is the main language spoken in Argentina? 🇦🇷", ["Portuguese", "Spanish", "French", "Italian"], 1),
    ("Which country is famous for pyramids? 🏺", ["Mexico", "India", "Greece", "Egypt"], 3),
    ("What is the term for animals that eat only plants? 🌱", ["Carnivores", "Omnivores", "Herbivores", "Insectivores"], 2),
    ("Which is the longest bone in the human body? 🦴", ["Spine", "Humerus", "Femur", "Tibia"], 2),
    ("Which programming concept uses 'if' and 'else'? 🔁", ["Looping", "Conditionals", "Functions", "Recursion"], 1),
    ("Which unit measures electric current? ⚡", ["Volt", "Ohm", "Watt", "Ampere"], 3),
    ("Which is the only even prime number? 🔢", ["0", "2", "4", "6"], 1),
    ("Which bird can fly backwards? 🐦", ["Crow", "Hummingbird", "Sparrow", "Eagle"], 1),
    ("What year did the first man land on the moon? 🌕", ["1965", "1969", "1971", "1975"], 1),
    ("What is the main ingredient of bread? 🍞", ["Rice", "Flour", "Sugar", "Milk"], 1),
    ("What is the name of the longest river in Asia? 🏞️", ["Yangtze", "Ganges", "Mekong", "Indus"], 0),
    ("What is the name for animals active at night? 🌙", ["Diurnal", "Crepuscular", "Nocturnal", "Solar"], 2),
    ("Which shape has five sides? 🔷", ["Triangle", "Hexagon", "Pentagon", "Octagon"], 2),
    ("What is the opposite of 'expand'? 🔽", ["Compress", "Increase", "Widen", "Enlarge"], 0),
    ("What natural satellite orbits Earth? 🌕", ["Mars", "Sun", "Moon", "Venus"], 2),
    ("How many teeth does an adult human typically have? 🦷", ["28", "30", "32", "36"], 2),
    ("What do you call a baby cat? 🐱", ["Cub", "Kitten", "Pup", "Chick"], 1),
    ("What is the study of weather called? ⛅", ["Geology", "Meteorology", "Astronomy", "Ecology"], 1),
    ("Which element is needed for breathing? 🫁", ["Nitrogen", "Hydrogen", "Oxygen", "Carbon"], 2),
    ("Which fruit has its seeds on the outside? 🍓", ["Banana", "Strawberry", "Blueberry", "Mango"], 1),
    ("What device converts sound into electrical signals? 🎤", ["Speaker", "Microphone", "Amplifier", "Sensor"], 1),
    ("What is the opposite of 'artificial'? 🎨", ["Natural", "Fake", "Plastic", "Smart"], 0),
    ("Which instrument has 88 keys? 🎹", ["Guitar", "Piano", "Violin", "Flute"], 1),
    ("Which planet is famous for its big red spot? 🌪️", ["Mars", "Saturn", "Uranus", "Jupiter"], 3),
    ("What is the most common programming loop? 🔁", ["for", "switch", "if", "goto"], 0),
    ("What does Wi-Fi stand for? 📶", ["Wireless Fidelity", "Wired File", "Wide Filter", "Wireless File"], 0),
    ("Which month is known for Halloween? 🎃", ["September", "October", "November", "December"], 1),
    ("Which shape has no straight lines? 🟠", ["Square", "Circle", "Rectangle", "Triangle"], 1),
	],
}

# Build mixed quiz
QUIZ_DATA["aquiz"] = []
for quiz_questions in QUIZ_DATA.values():
    QUIZ_DATA["aquiz"].extend(quiz_questions)

# Runtime quiz management
shuffled_quizzes: Dict[str, List[Tuple[str, List[str], int]]] = {}

def reset_shuffled_quiz(quiz_type: str) -> None:
    """Reset and shuffle quiz questions for a category."""
    if quiz_type in QUIZ_DATA:
        shuffled_quizzes[quiz_type] = copy.deepcopy(QUIZ_DATA[quiz_type])
        random.shuffle(shuffled_quizzes[quiz_type])
        logger.info(f"Reset shuffled quiz for {quiz_type}")

# Initialize all quiz types
for quiz_type in QUIZ_DATA:
    reset_shuffled_quiz(quiz_type)

# ----------------------------
# Utility functions
# ----------------------------
def get_user_display_name(user: types.User) -> str:
    """Get a proper display name for a user."""
    if user.username:
        return f"@{user.username}"
    elif user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    elif user.first_name:
        return user.first_name
    else:
        return f"User{user.id}"

async def safe_delete_message(chat_id: int, message_id: int, delay: int = 0) -> None:
    """Safely delete a message after optional delay."""
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        if bot:
            await bot.delete_message(chat_id, message_id)
    except TelegramAPIError as e:
        logger.warning(f"Could not delete message {message_id}: {e}")

# ----------------------------
# Bot command handlers
# ----------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    """Handle /start command."""
    user = message.from_user
    if not user:
        return
    
    try:
        await ensure_user(user.id, user.username, user.first_name, user.last_name)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Updates", url="https://t.me/WorkGlows"),
                InlineKeyboardButton(text="Support", url="https://t.me/TheCryptoElders"),
            ],
            [
                InlineKeyboardButton(
                    text="Add Me To Your Group",
                    url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true"
                ) if bot else InlineKeyboardButton(text="Add Me", url="https://t.me/")
            ]
        ])

        welcome_text = (
            f"👋 Hey {user.mention_html()}!\n\n"
            "✨ <b>Welcome to the Ultimate Quiz Challenge Bot!</b> ✨\n\n"
            "🎯 <b>Available Quiz Categories:</b>\n"
            "🔥 /xquiz — Relationship Quiz\n"
            "😏 /hquiz — Attraction Quiz\n"
            "💕 /fquiz — Romance Quiz\n"
            "😂 /lolquiz — Comedy Quiz\n"
            "🤪 /cquiz — Crazy Quiz\n"
            "📚 /squiz — Study Quiz\n"
            "🎲 /aquiz — Mixed Random Quiz\n\n"
            "🏆 <b>How it works:</b>\n"
            "• Correct answers boost your leaderboard rank!\n"
            "• Wrong answers help you learn and improve!\n"
            "• Check your progress with /statistics\n\n"
            "💡 Use /help for detailed guidance\n\n"
            "🎉 <b>Ready to challenge your knowledge?</b>"
        )
        
        await message.answer(welcome_text, reply_markup=kb)
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """Handle /help command."""
    try:
        help_text = (
            "📚 <b>Quiz Bot Help Guide</b>\n\n"
            "🎯 <b>Available Quiz Categories:</b>\n\n"
            "🔥 <code>/xquiz</code> — Relationship Quiz\n"
            "😏 <code>/hquiz</code> — Attraction Quiz\n"
            "💕 <code>/fquiz</code> — Romance Quiz\n"
            "😂 <code>/lolquiz</code> — Comedy Quiz\n"
            "🤪 <code>/cquiz</code> — Crazy Quiz\n"
            "📚 <code>/squiz</code> — Educational Quiz\n"
            "🎲 <code>/aquiz</code> — Mixed Random Quiz\n\n"
            "📊 <b>Statistics & Leaderboard:</b>\n"
            "<code>/statistics</code> — View current leaderboard\n\n"
            "ℹ️ <b>How to Play:</b>\n"
            "1. Choose a quiz category\n"
            "2. Answer the poll questions\n"
            "3. Get points for correct answers\n"
            "4. Climb the leaderboard!\n\n"
            "🔄 <b>Quiz Management:</b>\n"
            "• Questions are shuffled randomly\n"
            "• Each category resets when empty\n"
            "• Mixed quiz includes all categories\n\n"
            "💡 <b>Tips:</b>\n"
            "• Read questions carefully\n"
            "• Answer quickly (60 second limit)\n"
            "• Practice makes perfect!\n\n"
            "🎯 <b>Start playing now with any quiz command!</b>"
        )
        
        await message.answer(help_text)
        
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

async def send_quiz(message: types.Message, quiz_type: str) -> None:
    """Send a quiz question for the specified category."""
    if quiz_type not in QUIZ_DATA:
        await message.answer("❌ Invalid quiz category!")
        return
    
    user = message.from_user
    if not user:
        return
    
    try:
        await ensure_user(user.id, user.username, user.first_name, user.last_name)
        
        # Check if we need to reset the shuffled quiz
        if not shuffled_quizzes.get(quiz_type):
            reset_shuffled_quiz(quiz_type)
        
        if not shuffled_quizzes[quiz_type]:
            await message.answer(
                f"🎉 Congratulations! You've completed all questions in this category!\n"
                f"🔄 Questions have been reshuffled. Try again!"
            )
            reset_shuffled_quiz(quiz_type)
            return
        
        # Get next question
        question_text, options, correct_id = shuffled_quizzes[quiz_type].pop()
        
        # Send poll
        poll_msg = await message.answer_poll(
            question=question_text,
            options=options,
            type=PollType.QUIZ,
            correct_option_id=correct_id,
            is_anonymous=False,
            open_period=POLL_TIMEOUT,
        )
        
        # Store poll session
        await store_poll_session(
            poll_msg.poll.id, 
            correct_id, 
            poll_msg.message_id, 
            message.chat.id, 
            quiz_type
        )
        
        logger.info(f"Sent {quiz_type} quiz to user {user.id} in chat {message.chat.id}")
        
    except TelegramBadRequest as e:
        logger.error(f"Telegram API error sending quiz: {e}")
        await message.answer("❌ Failed to send quiz. Please try again.")
    except Exception as e:
        logger.error(f"Error sending quiz {quiz_type}: {e}")
        await message.answer("❌ An error occurred. Please try again later.")

# Quiz command handlers
@dp.message(Command("xquiz"))
async def cmd_xquiz(message: types.Message) -> None:
    await send_quiz(message, "xquiz")

@dp.message(Command("hquiz"))
async def cmd_hquiz(message: types.Message) -> None:
    await send_quiz(message, "hquiz")

@dp.message(Command("fquiz"))
async def cmd_fquiz(message: types.Message) -> None:
    await send_quiz(message, "fquiz")

@dp.message(Command("lolquiz"))
async def cmd_lolquiz(message: types.Message) -> None:
    await send_quiz(message, "lolquiz")

@dp.message(Command("cquiz"))
async def cmd_cquiz(message: types.Message) -> None:
    await send_quiz(message, "cquiz")

@dp.message(Command("squiz"))
async def cmd_squiz(message: types.Message) -> None:
    await send_quiz(message, "squiz")

@dp.message(Command("aquiz"))
async def cmd_aquiz(message: types.Message) -> None:
    await send_quiz(message, "aquiz")

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer) -> None:
    """Handle poll answers and update user scores."""
    try:
        user_id = poll_answer.user.id
        selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else -1
        
        # Get poll session data
        session_data = await get_poll_session(poll_answer.poll_id)
        if not session_data:
            logger.warning(f"No session data found for poll {poll_answer.poll_id}")
            return
        
        correct_option_id = session_data["correct_option_id"]
        is_correct = selected_option == correct_option_id
        
        # Ensure user exists and update score
        await ensure_user(
            user_id, 
            poll_answer.user.username, 
            poll_answer.user.first_name, 
            poll_answer.user.last_name
        )
        await update_score(user_id, is_correct)
        
        logger.info(f"User {user_id} answered poll {poll_answer.poll_id}: {'correct' if is_correct else 'incorrect'}")
        
    except Exception as e:
        logger.error(f"Error handling poll answer: {e}")

@dp.message(Command("statistics"))
async def cmd_statistics(message: types.Message) -> None:
    """Show leaderboard statistics with proper user mentions."""
    if not db:
        await message.answer("❌ Database not available!")
        return
    
    try:
        cursor = await db.execute(
            """SELECT user_id, username, first_name, last_name, wins, losses 
               FROM users 
               WHERE wins > 0 OR losses > 0 
               ORDER BY wins DESC, losses ASC 
               LIMIT ?""",
            (LEADERBOARD_SIZE,)
        )
        rows = await cursor.fetchall()
        
        if not rows:
            temp_msg = await message.answer(
                "📊 <b>Quiz Global Leaderboard</b> 📊\n\n"
                "🎯 No players have participated yet!\n"
                "🚀 Be the first to play and claim the top spot!\n\n"
                "💡 Use any quiz command to start playing!"
            )
            await safe_delete_message(message.chat.id, temp_msg.message_id, MESSAGE_DELETE_DELAY)
            return

        # Build leaderboard text with href links for user mentions
        leaderboard_text = "🏆 <b>Quiz Global Leaderboard</b> 🏆\n\n"
        
        for rank, (user_id, username, first_name, last_name, wins, losses) in enumerate(rows, 1):
            # Medal emoji based on rank
            if rank == 1:
                medal = "🥇"
            elif rank == 2:
                medal = "🥈"
            elif rank == 3:
                medal = "🥉"
            else:
                medal = f"{rank}."
            
            # Determine display name
            if first_name and last_name:
                display_name = f"{first_name} {last_name}"
            elif first_name:
                display_name = first_name
            elif username:
                display_name = username
            else:
                display_name = f"User{user_id}"
            
            # Calculate win rate
            total_games = wins + losses
            win_rate = (wins / total_games * 100) if total_games > 0 else 0
            
            # Create href mention link with display name
            user_mention = f'<a href="tg://user?id={user_id}">{display_name}</a>'
            
            # Add rank line with href mention
            leaderboard_text += f"{medal} {user_mention} — ✅ {wins} | ❌ {losses} | 📈 {win_rate:.1f}%\n"

        leaderboard_text += (
            "\n🎯 <b>Keep playing to climb higher!</b>\n"
            "💡 Use any quiz command to earn more points!"
        )

        # Send leaderboard message with href mentions
        leaderboard_msg = await message.answer(leaderboard_text)
        
        # Auto-delete after delay
        await safe_delete_message(message.chat.id, leaderboard_msg.message_id, MESSAGE_DELETE_DELAY)
        
    except Exception as e:
        logger.error(f"Error in statistics command: {e}")
        await message.answer("❌ An error occurred while fetching statistics.")

# ----------------------------
# Bot setup and lifecycle
# ----------------------------
async def setup_bot() -> None:
    """Set up bot commands and configuration."""
    try:
        commands = [
            BotCommand(command="start", description="🚀 Start the quiz bot"),
            BotCommand(command="help", description="📚 Get help and instructions"),
            BotCommand(command="xquiz", description="🔥 Relationship Quiz"),
            BotCommand(command="hquiz", description="😏 Attraction Quiz"),
            BotCommand(command="fquiz", description="💕 Romance Quiz"),
            BotCommand(command="lolquiz", description="😂 Comedy Quiz"),
            BotCommand(command="cquiz", description="🤪 Crazy Quiz"),
            BotCommand(command="squiz", description="📚 Educational Quiz"),
            BotCommand(command="aquiz", description="🎲 Mixed Random Quiz"),
            BotCommand(command="statistics", description="📊 View leaderboard"),
        ]
        
        await bot.set_my_commands(commands)
        logger.info("Bot commands set successfully")
        
    except Exception as e:
        logger.error(f"Error setting up bot commands: {e}")

async def graceful_shutdown() -> None:
    """Handle graceful shutdown."""
    logger.info("Initiating graceful shutdown...")
    
    try:
        # Close database connection
        await close_db()
        
        # Close bot session
        if bot:
            await bot.session.close()
            
        logger.info("Graceful shutdown completed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    
    finally:
        # Force exit
        sys.exit(0)

# ─── Dummy HTTP Server to Keep Render Happy ─────────────────────────────────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))  # Render injects this
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Dummy server listening on port {port}")
    server.serve_forever()

async def main() -> None:
    """Main application entry point."""
    global bot
    
    try:
        # Initialize bot
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Initialize database
        await init_db()
        
        # Set up bot commands
        await setup_bot()
        
        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, 
                lambda: asyncio.create_task(graceful_shutdown())
            )
        
        logger.info("Bot starting up...")
        logger.info(f"Bot username: {(await bot.get_me()).username}")
        
        # Start polling
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        await graceful_shutdown()

if __name__ == "__main__":
    # Start dummy HTTP server (needed for Render health check)
    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Unexpected error")  # Better for full traceback
        sys.exit(1)
