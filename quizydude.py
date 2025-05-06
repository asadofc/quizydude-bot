import os
import logging
import random
import psycopg2
import copy
from telegram import (
    Update, Poll, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
conn = psycopg2.connect(
    host=os.environ.get("PGHOST"),
    port=os.environ.get("PGPORT"),
    database=os.environ.get("PGDATABASE"),
    user=os.environ.get("PGUSER"),
    password=os.environ.get("PGPASSWORD")
)
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

# --- QUIZ QUESTIONS SETUP ---
quizzes = {
    'xquiz': [
    ("What's the most sensitive erogenous zone? 🔥", ["Neck", "Fingers", "Toes", "Elbows"], 0),
    ("Which sense is strongest during intimacy? 👃", ["Sight", "Touch", "Smell", "Taste"], 2),
    ("What color is often linked with passion? ❤️", ["Blue", "Green", "Red", "Yellow"], 2),
    ("Which body part has the most nerve endings? ⚡", ["Fingertips", "Lips", "Back", "Ears"], 1),
    ("What chemical is called the 'cuddle hormone'? 🧸", ["Adrenaline", "Oxytocin", "Melatonin", "Serotonin"], 1),
    ("Which position is famously called '69'? 🔥", ["Doggy", "Cowgirl", "Sixty-nine", "Missionary"], 2),
    ("Foreplay should last at least how long? ⏱️", ["1 min", "5 mins", "10 mins", "20 mins"], 3),
    ("Where is the G-spot located? 🌸", ["Outer Labia", "Inner Thigh", "Vagina", "Clitoris"], 2),
    ("What boosts libido naturally? 🍫", ["Chocolate", "Rice", "Bread", "Potatoes"], 0),
    ("Which is NOT an aphrodisiac? ❌", ["Oysters", "Chocolate", "Watermelon", "Celery"], 3),
    ("Which fruit symbolizes fertility? 🍑", ["Banana", "Peach", "Mango", "Grapes"], 1),
    ("Where does pheromone production mainly occur? ✨", ["Armpits", "Knees", "Elbows", "Feet"], 0),
    ("Which zodiac sign is known as the sexiest? ♏", ["Leo", "Scorpio", "Aries", "Libra"], 1),
    ("Which food resembles a body part and is suggestive? 🍌", ["Apple", "Banana", "Pear", "Strawberry"], 1),
    ("Which sense can heighten orgasm? 🎶", ["Hearing", "Sight", "Smell", "Touch"], 0),
    ("What activity is best for building sexual stamina? ‍♂️", ["Running", "Swimming", "Yoga", "Boxing"], 2),
    ("Which part is most ticklish? 😂", ["Belly", "Armpits", "Back", "Knees"], 1),
    ("What is called the 'love hormone'? 💞", ["Dopamine", "Cortisol", "Oxytocin", "Adrenaline"], 2),
    ("How much of sex is mental? 🧠", ["20%", "40%", "60%", "90%"], 3),
    ("What’s a common fantasy location? ✈️", ["Beach", "Airport", "Car", "Shower"], 0),
    ("Which fabric feels most sensual? ✨", ["Silk", "Denim", "Cotton", "Wool"], 0),
	("What sound is most associated with arousal? 🔊", ["Whispering", "Laughing", "Shouting", "Snoring"], 0),
	("Which beverage is often called an aphrodisiac? 🍷", ["Coffee", "Wine", "Tea", "Soda"], 1),
	("Which season is considered the sexiest? ❄️", ["Winter", "Summer", "Spring", "Autumn"], 2),
	("Where is the male 'P-spot' located? ➡️", ["Penis", "Prostate", "Testicles", "Inner thigh"], 1),
	("Which scent is linked to attraction? 🌸", ["Lavender", "Pumpkin pie", "Citrus", "Peppermint"], 1),
	("Which lingerie color is most seductive? 🖤", ["White", "Pink", "Black", "Green"], 2),
	("Which dance is considered the most sensual? 💃", ["Waltz", "Salsa", "Tango", "Hip-hop"], 2),
	("Which emotion can kill libido fastest? ❌", ["Happiness", "Stress", "Excitement", "Calm"], 1),
	("Which hormone drives sexual desire? 🔥", ["Estrogen", "Progesterone", "Testosterone", "Insulin"], 2),
	("Which flavor is linked with passion? 🍓", ["Vanilla", "Strawberry", "Mint", "Lemon"], 1),
	("Which body part is often kissed first? 💋", ["Neck", "Forehead", "Hand", "Cheek"], 3),
	("Which part of the ear is most sensitive? 👂", ["Lobe", "Inner ear", "Helix", "Tragus"], 0),
	("Which movie genre is most likely to lead to intimacy? 🎥", ["Comedy", "Action", "Horror", "Romance"], 3),
	("What drink is called 'liquid courage'? 🥃", ["Whiskey", "Vodka", "Rum", "Beer"], 0),
	("Which element of a bedroom boosts desire most? 🛏️", ["Lighting", "Size", "Temperature", "Color"], 0),
	("Which muscle group is key for better sex? ‍♂️", ["Legs", "Core", "Arms", "Back"], 1),
	("Where is a common spot for love bites? ❤️", ["Neck", "Shoulder", "Wrist", "Cheek"], 0),
	("Which flower symbolizes love and passion? 🌹", ["Tulip", "Daisy", "Rose", "Sunflower"], 2),
	("What percentage of communication is nonverbal? ✋", ["30%", "55%", "70%", "90%"], 1),
	("What body part often reacts first to attraction? ✨", ["Hands", "Eyes", "Lips", "Feet"], 1),
	("Which type of touch is most arousing? ✋", ["Firm", "Light", "Rough", "Quick"], 1),
	("Which time of day do most people feel sexiest? ⏰", ["Morning", "Afternoon", "Evening", "Late night"], 2),
	("Which genre of music is most associated with intimacy? 🎶", ["Rock", "Jazz", "Hip-hop", "Classical"], 1),
	("Which dessert is considered sexy? 🍰", ["Cake", "Pie", "Chocolate fondue", "Ice cream"], 2),
	("Which country is famous for romantic culture? ✈️", ["Germany", "France", "Japan", "Australia"], 1),
	("What part of the female body is most sensitive? 🌸", ["Elbow", "Inner thigh", "Forehead", "Shin"], 1),
	("Which room in a house is the most common fantasy location? 🏡", ["Kitchen", "Living Room", "Bedroom", "Bathroom"], 2),
	("Which hormone rises during cuddling? 🤗", ["Cortisol", "Insulin", "Oxytocin", "Adrenaline"], 2),
	("Which fabric is considered least sexy? 🚫", ["Velvet", "Flannel", "Silk", "Leather"], 1),
	("Which month is linked to the highest birth rates? 📅", ["January", "September", "June", "December"], 1),
	("Which sense triggers the fastest memories? 🧠", ["Sight", "Sound", "Smell", "Touch"], 2),
	("Which kiss type is seen as most intimate? 💏", ["Peck", "French kiss", "Forehead kiss", "Hand kiss"], 1),
	("Which planet is associated with love? 🪐", ["Mars", "Venus", "Jupiter", "Mercury"], 1),
	("Which vegetable is seen as a phallic symbol? 🌶️", ["Carrot", "Potato", "Broccoli", "Cabbage"], 0),
	("What activity releases endorphins similar to sex? ‍♂️", ["Reading", "Singing", "Exercise", "Painting"], 2),
	("Which animal mates for life and symbolizes loyalty? ❤️", ["Lion", "Dolphin", "Swan", "Wolf"], 2),
	("What color light is most flattering for romance? ", ["Red", "Blue", "Green", "White"], 0),
	("Which beverage is linked to energy and desire? ☕", ["Tea", "Energy drinks", "Coffee", "Soda"], 2),
	("Which musical instrument is often called the most romantic? 🎻", ["Guitar", "Drums", "Violin", "Piano"], 3),
	("Which body part is most associated with sensual dancing? 💃", ["Hips", "Shoulders", "Hands", "Feet"], 0),
	("What percentage of people fantasize weekly? 📊", ["20%", "40%", "70%", "90%"], 2),
	("Which scent is considered the most calming? 🌿", ["Rose", "Sandalwood", "Vanilla", "Cinnamon"], 1),
	("What mood lighting color encourages relaxation? ", ["Red", "Blue", "Yellow", "Orange"], 1),
	("Which fabric is most associated with luxury? ✨", ["Cotton", "Linen", "Silk", "Polyester"], 2),
	("Which part of the male body is considered most sensitive? 🧔", ["Chest", "Inner thigh", "Feet", "Back"], 1),
	("What is the most common love language? ❤️", ["Physical Touch", "Words of Affirmation", "Gifts", "Acts of Service"], 0),
	("Which cocktail is often called romantic? 🍸", ["Margarita", "Mojito", "Champagne Cocktail", "Bloody Mary"], 2),
	("Which type of massage is considered most sensual? ✋", ["Deep tissue", "Swedish", "Tantric", "Sports"], 2),
	("Which visual element enhances attraction most? 👀", ["Eye contact", "Smile", "Posture", "Hair"], 0),
	("Which activity increases oxytocin naturally? ‍♂️", ["Running", "Hugging", "Driving", "Working"], 1),
	("What temperature is ideal for cuddling? 🌡️", ["Cold", "Hot", "Cool", "Warm"], 3),
	("Which holiday sees the biggest spike in romantic gestures? 🎁", ["Christmas", "Valentine's Day", "New Year", "Easter"], 1),
	("Which food is shaped like a heart? ❤️", ["Apple", "Strawberry", "Cherry", "Tomato"], 1),
	("What muscle controls orgasm contractions? 💪", ["Biceps", "Glutes", "Pelvic floor", "Hamstrings"], 2),
	("Which flower is most gifted on Valentine’s Day? 🌹", ["Lily", "Tulip", "Rose", "Orchid"], 2),
	("Which country invented the Kama Sutra? 📖", ["China", "Egypt", "India", "Greece"], 2),
	("Which essential oil is often used for romantic massage? 🧴", ["Tea Tree", "Lavender", "Peppermint", "Eucalyptus"], 1),
	("Which candy is traditionally shaped like hearts? 🍬", ["Lollipops", "Candy Canes", "Conversation Hearts", "Gum Drops"], 2),
	("Which pulse point is best for applying perfume for attraction? ✨", ["Wrist", "Elbow", "Ankle", "Back"], 0),
	("Which is often most sensitive during oral play? 👅", ["Neck", "Nipples", "Thighs", "Feet"], 1),
	("Which term refers to slow, teasing intercourse? 🐢", ["Quickie", "Edging", "Pounding", "Grinding"], 1),
	("Where is the perineum located? ⚡", ["Between the legs", "Under the arms", "Behind the ear", "On the back"], 0),
	("Which act stimulates both physical and emotional intimacy? ❤️‍🔥", ["Kissing", "Massaging", "Oral sex", "Cuddling"], 2),
	("Which part of the body responds fastest to kissing? 💋", ["Chest", "Brain", "Feet", "Stomach"], 1),
	("What is a common nickname for passionate kissing? 🔥", ["Butterfly kiss", "Eskimo kiss", "French kiss", "Peck"], 2),
	("Which action heightens anticipation most during intimacy? ⏳", ["Eye contact", "Verbal teasing", "Tickling", "Hand-holding"], 1),
	("Which lubricant base is safest for condoms? ✨", ["Oil-based", "Water-based", "Silicone-based", "Petroleum-based"], 1),
	("What bedroom accessory is used for light bondage? ⛓️", ["Blindfold", "Handcuffs", "Rope", "Candle"], 1),
	("Which body part is often used for a 'tease and deny' play? ❌", ["Lips", "Inner thighs", "Hands", "Forehead"], 1),
	("Which action is commonly part of foreplay? 🌶️", ["Wrestling", "Tickling", "Massage", "Running"], 2),
	("Which sexual position allows the most eye contact? 👀", ["Doggy Style", "Cowgirl", "Missionary", "Spooning"], 2),
	("Where are the nipples most sensitive? ⚡", ["At the center", "Outer edge", "Underneath", "Above the areola"], 0),
	("What is the term for prolonging pleasure by delaying orgasm? ⏳", ["Rimming", "Edging", "Pegging", "Climaxing"], 1),
	("What type of kiss involves light nibbling? 🦷", ["Butterfly", "Peck", "Bite kiss", "Eskimo kiss"], 2),
	("Which sex toy is primarily used for clitoral stimulation? ✨", ["Dildo", "Vibrator", "Butt plug", "Ring"], 1),
	("What is the largest sex organ? 🧠", ["Skin", "Brain", "Lips", "Tongue"], 1),
	("Which body oil enhances sensual massages? 🧴", ["Olive oil", "Coconut oil", "Baby oil", "Cooking oil"], 1),
	("What is the term for talking dirty during intimacy? ‍♂️", ["Sexting", "Dirty talk", "Roleplay", "Teaseplay"], 1),
	("Which body temperature change can heighten arousal? 🔥", ["Cooling down", "Warming up", "Freezing", "Overheating"], 1),
],
    'hquiz': [
    ("What hormone spikes during orgasm? ⚡", ["Adrenaline", "Oxytocin", "Cortisol", "Dopamine"], 1),
    ("Which body part is nicknamed 'love button'? ❤️", ["Neck", "G-spot", "Clitoris", "Lips"], 2),
    ("Best natural aphrodisiac drink? 🍷", ["Wine", "Tea", "Coffee", "Juice"], 0),
    ("Which food can spark sexual desire? 🍓", ["Strawberry", "Potato", "Broccoli", "Rice"], 0),
    ("How much water is released during ejaculation? 💦", ["1 tsp", "1 tbsp", "1/2 cup", "1 cup"], 0),
    ("Which sense is most linked to arousal? 🔥", ["Touch", "Sight", "Hearing", "Taste"], 1),
    ("Where do men release most testosterone? 💪", ["Brain", "Muscles", "Testicles", "Heart"], 2),
    ("Which color boosts attraction? ❤️", ["Red", "Blue", "Green", "Black"], 0),
    ("Average speed of sperm swim? 🏊", ["5mm/sec", "1cm/sec", "10cm/min", "100cm/min"], 0),
    ("Which vitamin improves libido? 💊", ["Vitamin A", "Vitamin D", "Vitamin C", "Vitamin B12"], 1),
    ("Which mood killer increases cortisol? ⚠️", ["Stress", "Joy", "Excitement", "Laughter"], 0),
    ("Which flower is tied to seduction? 🌹", ["Rose", "Lily", "Sunflower", "Orchid"], 0),
    ("Which position enhances intimacy most? ❤️‍🔥", ["Missionary", "Doggy", "Reverse Cowgirl", "Standing"], 0),
    ("Which fruit is called 'nature's Viagra'? 🍉", ["Watermelon", "Banana", "Pineapple", "Mango"], 0),
    ("Which sound triggers arousal quickly? 🎶", ["Music", "Moaning", "Whisper", "Breathing"], 1),
    ("Which essential oil boosts libido? 🌸", ["Lavender", "Peppermint", "Rose", "Eucalyptus"], 2),
    ("Best muscle to work for better sex stamina? ‍♂️", ["Arms", "Legs", "Core", "Chest"], 2),
    ("Which day is libido usually highest? 📆", ["Friday", "Saturday", "Monday", "Wednesday"], 1),
    ("What is a secret erogenous zone? 🤫", ["Ears", "Knees", "Hands", "Feet"], 0),
    ("Best scent to spark sexual attraction? ✨", ["Vanilla", "Rosemary", "Peppermint", "Sandalwood"], 0),
    ("Which neurotransmitter surges during orgasm? ⚡", ["Dopamine", "Serotonin", "Adrenaline", "Cortisol"], 0),
	("What body part swells the most during arousal? ❤️‍🔥", ["Lips", "Ears", "Clitoris", "Nipples"], 2),
	("Which fruit is packed with libido-boosting zinc? 🥝", ["Banana", "Kiwi", "Pineapple", "Mango"], 1),
	("What body fluid increases sensitivity during sex? 💦", ["Sweat", "Saliva", "Semen", "Tears"], 1),
	("Which hormone causes intense sexual cravings? 🔥", ["Estrogen", "Testosterone", "Progesterone", "Melatonin"], 1),
	("Which food is considered a sexy energy booster? ⚡", ["Oysters", "Steak", "Cheese", "Carrots"], 0),
	("Where do women store the most erotic nerve endings? ✨", ["Back", "Breasts", "Inner thighs", "Clitoris"], 3),
	("Which beverage increases blood flow for better sex? 🍷", ["Wine", "Beer", "Coffee", "Juice"], 0),
	("Which time of day are testosterone levels highest? ⏰", ["Morning", "Noon", "Evening", "Midnight"], 0),
	("Which mineral is crucial for a strong sex drive? ⚡", ["Zinc", "Iron", "Calcium", "Potassium"], 0),
	("Which mood ignites sexual arousal fastest? ❤️", ["Love", "Excitement", "Fear", "Curiosity"], 1),
	("Which sexual act stimulates both mind and body deeply? 🧠", ["Oral sex", "Kissing", "Massage", "Cuddling"], 0),
	("What skin area heightens pleasure when lightly touched? ✋", ["Shoulders", "Wrists", "Elbows", "Knees"], 1),
	("Which scent mimics natural human pheromones? ✨", ["Musk", "Lavender", "Lemon", "Mint"], 0),
	("Which orgasm type releases the most endorphins? ⚡", ["Clitoral", "G-spot", "Anal", "Nipple"], 1),
	("Which activity can double arousal after 20 minutes? ⏳", ["Workout", "Shower", "Nap", "Massage"], 0),
	("Which clothing texture is most arousing on skin? 🧵", ["Leather", "Silk", "Cotton", "Velvet"], 1),
	("Which part of a kiss triggers deepest emotional arousal? 💋", ["Lips", "Tongue", "Neck", "Teeth"], 1),
	("Which naughty act raises heart rate closest to exercise? ❤️‍🔥", ["Sexting", "Quickie", "Roleplay", "Dirty talk"], 1),
	("What scent has been shown to cause penile blood flow to rise? 🍩", ["Pumpkin pie", "Chocolate", "Peppermint", "Vanilla"], 0),
	("Which body part tingles first during foreplay? ⚡", ["Fingertips", "Neck", "Inner thighs", "Lips"], 3),
	("What boosts blood flow to erogenous zones fastest? ❤️", ["Cold shower", "Warmth", "Caffeine", "Spicy food"], 1),
	("Which hormone spikes libido before ovulation? ♀️", ["Estrogen", "Cortisol", "Progesterone", "Melatonin"], 0),
	("Which fruit's smell can increase arousal? 🍌", ["Banana", "Watermelon", "Mango", "Strawberry"], 0),
	("What kind of touch releases the most oxytocin? ✋", ["Soft strokes", "Firm grip", "Light taps", "Scratches"], 0),
	("Which pulse point is most sensitive to kisses? ❤️‍🔥", ["Neck", "Wrist", "Ankles", "Back of knee"], 0),
	("Which drink may heighten sensitivity during intimacy? 🍷", ["Red wine", "Coffee", "Energy drink", "Green tea"], 0),
	("Which male body part often throbs during peak arousal? ⚡", ["Chest", "Testicles", "Penis", "Thighs"], 2),
	("What scent combination is linked to sexual excitement? ✨", ["Vanilla + Lavender", "Pumpkin + Donut", "Cinnamon + Rose", "Peppermint + Chocolate"], 1),
	("What emotional state can supercharge physical desire? ❤️", ["Relaxation", "Excitement", "Stress", "Boredom"], 1),
	("Which female spot swells most noticeably during arousal? 🌸", ["G-spot", "Clitoris", "Labia", "Breasts"], 2),
	("What action deepens sexual chemistry fastest? ⚡", ["Eye gazing", "Whispering", "Teasing", "Touching"], 0),
	("Which sexy act naturally slows breathing for deeper pleasure? ", ["Kissing", "Grinding", "Licking", "Tickling"], 1),
	("Which skin zone becomes hypersensitive when blindfolded? ‍‍♀️", ["Forearms", "Inner arms", "Neck", "Cheeks"], 2),
	("Which sound alone can trigger immediate arousal? 🎶", ["Laughter", "Breathless moans", "Sighs", "Footsteps"], 1),
	("Which visual cue most triggers primal sexual attraction? ", ["Smile", "Eyes", "Lips", "Hips"], 3),
	("Which basic human instinct fuels horniness? 🔥", ["Hunger", "Thirst", "Reproduction", "Safety"], 2),
	("Which bedroom act often leads to faster orgasms? ⚡", ["Dirty talk", "Quickie", "Roleplay", "Cuddling"], 1),
	("Which kissing style heats up body temperature fastest? ❤️‍🔥", ["Peck", "French kiss", "Butterfly kiss", "Neck kiss"], 1),
	("Which erogenous zone responds best to featherlight teasing? ✨", ["Lower back", "Behind ear", "Elbow", "Forehead"], 1),
	("Which sound increases anticipation most in bed? 🎧", ["Whispering", "Laughing", "Moaning", "Crying"], 2),
	("Where do women usually feel first heat during arousal? ♨️", ["Breasts", "Thighs", "Face", "Neck"], 0),
	("What sensation intensifies orgasm build-up? ⚡", ["Heat", "Cold", "Pressure", "Light touches"], 3),
	("Which kiss location sends the strongest chill? ❄️", ["Collarbone", "Neck", "Spine", "Inner thigh"], 1),
	("Which sexual trigger is purely psychological? 🧠", ["Scent", "Visuals", "Memory", "Touch"], 2),
	("Which body movement hints high sexual interest? ❤️‍🔥", ["Hand fidgeting", "Lip biting", "Blinking fast", "Scratching head"], 1),
	("Which body part, when grazed, sends shivers instantly? ⚡", ["Fingers", "Inner wrist", "Toes", "Knees"], 1),
	("Which sex position offers deepest emotional connection? ❤️", ["Spooning", "Doggy", "Cowgirl", "Standing"], 0),
	("Which fruit’s shape is subconsciously erotic? 🍑", ["Peach", "Grapes", "Orange", "Apple"], 0),
	("Which visual is most likely to spark instant horniness? 🔥", ["Neck", "Eyes", "Waist", "Mouth"], 3),
	("Which body part is often kissed last during slow seduction? ‍♀️", ["Forehead", "Neck", "Inner thigh", "Chest"], 2),
	("Which simple action can instantly boost arousal during sex? ⚡", ["Hair pulling", "Foot massage", "Singing", "Telling jokes"], 0),
	("What kind of breath heightens sexual tension? 🌬️", ["Shallow", "Rapid", "Deep", "Silent"], 2),
	("What activity floods the body with feel-good sex chemicals? ❤️‍🔥", ["Workout", "Napping", "Eating", "Watching TV"], 0),
	("Which time of the week are people naturally the horniest? 📅", ["Friday night", "Sunday morning", "Monday evening", "Wednesday noon"], 1),
	("Which zone is most responsive to teasing during strip games? ✨", ["Ankles", "Ears", "Belly", "Wrist"], 1),
	("Which word whispered can spike instant sexual arousal? 🔥", ["Yes", "Please", "Now", "More"], 2),
	("Which type of massage most often leads to intimacy? ✋", ["Hand massage", "Foot massage", "Back massage", "Head massage"], 2),
	("Which natural element symbolizes burning desire? ♨️", ["Air", "Water", "Fire", "Earth"], 2),
	("What boosts sexual desire faster than alcohol? ⚡", ["Exercise", "Chocolate", "Coffee", "Dancing"], 0),
	("Which part of the body is most responsive to a gentle bite? 🦷", ["Neck", "Shoulders", "Wrist", "Ankle"], 0),
	("What touch is most likely to trigger an intense shiver? ⚡", ["Soft caress", "Firm grip", "Slow strokes", "Fingertip tracing"], 2),
	("Which body part becomes most sensitive during sexual excitement? 🔥", ["Clitoris", "Penis", "Nipples", "Inner thighs"], 3),
	("Which scent is most associated with instant arousal? ✨", ["Jasmine", "Cinnamon", "Rose", "Sandalwood"], 1),
	("What movement in bed leads to the most intense orgasms? ❤️‍🔥", ["Grinding", "Thrusting", "Teasing", "Slow strokes"], 0),
	("Which type of kiss is most likely to lead to heated passion? 💋", ["French kiss", "Bite kiss", "Peck", "Eskimo kiss"], 0),
	("Which visual is most likely to ignite immediate sexual tension? 👀", ["Lips", "Waist", "Legs", "Eyes"], 2),
	("What part of the body can drive someone wild when kissed softly? 😘", ["Neck", "Earlobe", "Back", "Inner thigh"], 0),
	("Which action builds sexual energy faster than anything? 💥", ["Dirty talk", "Teasing", "Eye contact", "Slow undressing"], 3),
	("What simple act often leads to spontaneous intimacy? 💋", ["Whispering", "Touching hands", "Cuddling", "Complimenting"], 1),
	("What is the hottest place to kiss during a passionate moment? ❤️‍🔥", ["Chest", "Neck", "Belly button", "Behind the ear"], 0),
	("Which part of the body can be most electric when touched? ⚡", ["Lips", "Ears", "Inner thigh", "Back of knee"], 2),
	("Which piece of clothing most enhances sexual appeal? 👗", ["Lingerie", "Leather", "Silk", "Cotton"], 0),
	("Which part of the body responds most to teasing with a feather? 🪶", ["Neck", "Armpits", "Inner wrist", "Lower back"], 1),
	("Which sensation can quickly enhance sexual pleasure? 💋", ["Gentle biting", "Tickling", "Light caressing", "Firm pressure"], 0),
	("Which gesture can escalate arousal in a partner? 🔥", ["Squeezing", "Whispering their name", "Slow dancing", "Nipple play"], 1),
	("Which type of touch gets most immediate reactions in intimate settings? ✋", ["Soft strokes", "Light pinching", "Gentle scratches", "Firm grabs"], 3),
	("Which body part does kissing stimulate the most? 💋", ["Lips", "Neck", "Chest", "Inner thigh"], 0),
	("What type of voice causes immediate arousal? 🎙️", ["Soft whisper", "Breathy moan", "Low growl", "High-pitched laugh"], 2),
	("What mood change dramatically intensifies sexual desire? 💥", ["Excitement", "Fear", "Confidence", "Curiosity"], 1),
],
    'fquiz': [
    ("Best body language sign of flirting? 😉", ["Crossed arms", "Eye contact", "Yawning", "Looking away"], 1),
    ("Best compliment starter? ✨", ["You look smart", "You're breathtaking", "Nice shoes", "Cool vibe"], 1),
    ("Which emoji screams flirting? 😘", ["Heart ❤️", "Wink 😉", "Thumbs up 👍", "Smile 😊"], 1),
    ("Which touch is flirtiest? ✋", ["Handshake", "High-five", "Light arm touch", "Back pat"], 2),
    ("Best conversation starter? 🗨️", ["What's your sign?", "What's up?", "Wanna fight?", "Do you like memes?"], 0),
    ("Flirting tone is usually? 🎵", ["Serious", "Playful", "Loud", "Flat"], 1),
    ("Best reaction to a compliment? ❤️", ["Blush and say thanks", "Ignore", "Argue", "Laugh"], 0),
    ("When flirting, your body should? 🕺", ["Lean away", "Lean in", "Turn back", "Cross arms"], 1),
    ("Which pickup line is smoother? 😏", ["Are you lost, baby girl?", "Did it hurt when you fell?", "What's up?", "Yo!"], 1),
    ("Biggest flirting mistake? ❌", ["Smiling", "Complimenting", "Being creepy", "Laughing"], 2),
    ("Flirting is mostly about? 💬", ["Looks", "Words", "Money", "Shoes"], 1),
    ("Flirting on text should be? 📱", ["Boring", "Fun", "Formal", "One-word replies"], 1),
    ("Most attractive flirty quality? 🔥", ["Confidence", "Wealth", "Seriousness", "Laziness"], 0),
    ("Best time to flirt? 🕒", ["Early morning", "Late night", "During lunch", "Mid-afternoon"], 1),
    ("Flirting eyes are usually? 👀", ["Wide open", "Soft & locked", "Closed", "Rolling"], 1),
    ("Which line is cheesy but cute? 🧀", ["I lost my phone number, can I have yours?", "You’re kinda okay", "Sup", "Wanna Netflix?"], 0),
    ("Best flirty pet name? 🐾", ["Dude", "Babe", "Chief", "Buddy"], 1),
    ("Flirty jokes are best when? 😂", ["Offensive", "Light-hearted", "Serious", "Sarcastic"], 1),
    ("First flirty move should be? ✋", ["Compliment", "Tease harshly", "Insult", "Stay silent"], 0),
    ("Which flower says 'I'm flirting with you'? 🌹", ["Sunflower", "Rose", "Tulip", "Daisy"], 1),
    ("What’s the most charming body gesture when flirting? 😉", ["Adjusting hair", "Folding arms", "Leaning back", "Touching face"], 0),
	("Which flirty emoji shows you're feeling mischievous? 😈", ["Wink 😉", "Heart ❤️", "Fire 🔥", "Eyes 👀"], 0),
	("What’s the best way to give a flirty compliment? 💬", ["Make it specific", "General praise", "Flattery", "Joke about appearance"], 0),
	("How do you know someone is flirting with you? 💘", ["Frequent eye contact", "Ignoring you", "Talking about work", "Looking at phone"], 0),
	("When flirting, which smile works best? 😊", ["Flirty grin", "Teeth-showing smile", "Nervous smile", "Big wide grin"], 0),
	("Which part of the body is the most flirtatious when exposed? 💃", ["Neck", "Wrists", "Chest", "Hands"], 0),
	("Best way to compliment someone’s looks? 🔥", ["You look stunning", "I can't take my eyes off you", "You look good today", "Nice outfit"], 1),
	("When texting, what makes flirting more fun? 📱", ["Playful teasing", "One-word responses", "Sending memes", "Being serious"], 0),
	("Which flirty question sparks the most interest? 🧐", ["What are you thinking?", "Do you believe in love at first sight?", "What’s your dream date?", "What’s your favorite movie?"], 0),
	("Which is the most common flirting sign? 👀", ["Holding eye contact", "Nervously looking around", "Winking", "Glancing away quickly"], 0),
	("What's a fun flirty conversation starter? 🗣️", ["Are you single?", "Do you like going on adventures?", "What’s the most romantic thing you’ve done?", "Are you always this charming?"], 1),
	("What is a classic flirty touch? ✋", ["Playfully brushing arm", "Pat on the back", "Hand on the shoulder", "Hand on the knee"], 0),
	("What’s the best way to keep flirting exciting? 🔥", ["Surprise them", "Be mysterious", "Ask deep questions", "Keep it lighthearted"], 0),
	("Which way of flirting works in a crowd? 🗣️", ["Subtle eye contact", "Blatant approach", "Making them laugh", "Flashing a smile"], 0),
	("Which flirty line shows confidence? 💪", ["I can’t stop thinking about you", "Are you always this gorgeous?", "What time should I pick you up?", "Do you like adventure?"], 0),
	("Best flirting tactic at a party? 🎉", ["Approach and ask a question", "Flirt from across the room", "Dance with them", "Stay silent and observe"], 0),
	("What’s the best way to keep someone intrigued while flirting? 😏", ["Tease a little", "Make them chase", "Give them compliments", "Be mysterious"], 0),
	("When flirting, a playful tone is best used with? 🎶", ["A casual conversation", "During awkward silences", "When trying to impress", "When you're angry"], 1),
	("Best way to keep a flirt conversation going? 🗨️", ["Ask open-ended questions", "Compliment them often", "Be mysterious", "Talk about yourself"], 0),
	("When flirting, the best reaction to a compliment is? 💞", ["Flirty reply", "Smile shyly", "Say thank you", "Brush it off"], 1),
	("What's the best way to keep the flirtation alive? 🔥", ["Keep teasing", "Flatter constantly", "Stay mysterious", "Be overly forward"], 2),
	("Which body part do you notice first when flirting? 👀", ["Eyes", "Smile", "Lips", "Hair"], 1),
	("What’s the ultimate flirty move in a crowded room? 😏", ["Eye contact across the room", "Slightly touching their arm", "Sending a playful text", "Grinning from a distance"], 0),
	("What’s the best response to someone saying, ‘You’re cute’? 😘", ["'I know, right?'","'You’re not so bad yourself'", "'You’re adorable too!'", "'Thanks, I try'"], 0),
	("What’s a flirty way to ask for their number? 📱", ["'Can I get your digits?'", "'I’d love to talk more, what's your number?'", "'We should hang out sometime, what's your number?'", "'Your phone or mine?'"], 1),
	("What type of compliment makes flirting even better? 💬", ["Compliment their smile", "Tell them how confident they are", "Admire their style", "Comment on their energy"], 0),
	("What's the best flirty emoji to send after a joke? 😉", ["Wink 😉", "Laughing 😂", "Heart ❤️", "Fire 🔥"], 0),
	("Which type of body touch sparks chemistry instantly? ✋", ["Gentle touch on the arm", "Playful poke", "A soft hand on their back", "A brush of the fingers"], 0),
	("How can you tell if someone’s flirting with you? 💘", ["They give you long, lingering looks", "They smile a lot", "They ask personal questions", "They avoid eye contact"], 0),
	("What’s the best type of flirty text to send? 📲", ["'Hey, I was thinking about you...'", "'What are you up to tonight?'", "'Can’t stop smiling after our convo'", "'Let’s do something fun soon'"], 1),
	("How do you react when they flirt back with you? 😏", ["Tease them back", "Laugh and smile", "Keep the conversation going", "Be shy and look away"], 0),
	("What's the most seductive thing you can do with your eyes? 👀", ["Give a slow, intense look", "Look them up and down", "Bite your lip", "Flash a quick smile"], 0),
	("What’s the flirtiest way to introduce yourself? 👋", ["'Hey, I'm [Name], and you're even more stunning in person'", "'I had to come over and say hi'", "'I couldn't help but notice you from across the room'", "'What’s your name? I’m [Name], but you can call me anything'"], 0),
	("Which playful gesture makes flirting more fun? 😈", ["Running your hand through your hair", "Brushing your lips with your finger", "Tilting your head to the side", "Biting your lip"], 0),
	("How do you know when someone is flirting back with you? 😜", ["They start mirroring your body language", "They give you compliments", "They touch their hair or lips", "They become more engaged in the conversation"], 0),
	("Which flirty pickup line is best used at a bar? 🍸", ["'Is this seat taken, or are you just waiting for me?'", "'Do you believe in love at first sight, or should I walk by again?'", "'Do you have a map? Because I keep getting lost in your eyes.'", "'You must be made of copper and tellurium, because you’re Cu-Te'"], 1),
	("How do you flirt without saying anything? 😏", ["Body language", "Eye contact", "A playful smile", "A suggestive look"], 0),
	("What’s the best kind of flirty touch during a conversation? ✋", ["Lightly tapping their shoulder", "Brushing their arm", "Playfully nudging them", "Touching their wrist briefly"], 0),
	("What’s the best way to make someone blush when flirting? 😊", ["Give them a compliment about their looks", "Whisper something sweet in their ear", "Call them by a cute nickname", "Ask them about their favorite date ideas"], 0),
	("What’s the best time to make a flirty move? ⏰", ["During a funny moment", "When they're alone", "After a compliment", "In a quiet setting"], 1),
	("What’s the best way to keep someone intrigued while flirting? 🧐", ["Keep them guessing", "Give them compliments", "Ask deep questions", "Playfully tease them"], 0),
	("Which look is most likely to attract attention when flirting? 👀", ["The smoldering gaze", "The playful wink", "The soft, sweet look", "The mysterious side glance"], 0),
	("How do you know if someone is flirting with you in a group setting? 💬", ["They keep making eye contact", "They laugh at your jokes", "They subtly mirror your actions", "They talk to you more than others"], 0),
	("What’s a good flirty question to ask at the start of a conversation? 🗨️", ["'What’s the best thing that’s happened to you today?'", "'Are you always this charming?'", "'Do you believe in fate?'", "'What’s the most romantic thing you’ve ever done?'"], 0),
	("What’s the best way to show you’re interested while flirting? 👀", ["Smile often", "Make playful remarks", "Keep the conversation going", "Show curiosity about them"], 0),
	("Which flirty move works best in a crowded place? 🎉", ["Making eye contact from a distance", "Leaning in while speaking", "Flashing a quick smile", "Sending a wink across the room"], 0),
	("When flirting, how should your body be positioned? 🕺", ["Facing them", "Leaning slightly forward", "Standing tall", "Turning to the side"], 0),
	("What’s the best way to compliment someone’s personality? 💬", ["'You have such a great sense of humor'", "'I love how confident you are'", "'Your energy is so magnetic'", "'You’re so easy to talk to'"], 0),
	("What’s the flirtiest response to a ‘How are you?’ 😘", ["'Better now that I’m talking to you'", "'I’m doing great, especially since you’re here'", "'I’m great, but I’d be even better if you joined me for coffee'", "'Living the dream, now that you’re here'"], 0),
	("What’s a smooth way to ask someone out after flirting? 💖", ["'Let’s grab coffee sometime'", "'How about we get together and have some fun soon?'", "'I’d love to continue this conversation over dinner'", "'What are you doing this weekend? Want to hang out?'"], 0),
	("How do you react when someone flirts with you? 😏", ["Flirt back", "Smile and enjoy the attention", "Play it cool", "Laugh and blush"], 0),
	("When should you give a compliment while flirting? 🗣️", ["After a funny moment", "When they least expect it", "When you’re both relaxed", "As soon as they catch your attention"], 0),
	("What’s the best kind of smile to use when flirting? 😊", ["The shy, flirty smile", "The wide, confident smile", "The mysterious half-smile", "The playful grin"], 0),
	("What’s a playful way to tease someone while flirting? 😈", ["Playfully call them out on something", "Lightly make fun of their favorite thing", "Ask them personal questions", "Challenge them to a silly bet"], 0),
	("Which type of flirty text should you send after meeting someone new? 📱", ["'I had a great time with you today'", "'I can’t stop thinking about our conversation'", "'You made my day better, we should hang out again'", "'What’s your idea of a perfect date?'"], 0),
	("What’s a flirty comment to make about someone’s outfit? 👗", ["'You look absolutely stunning in that'", "'That outfit is made for you'", "'I can’t take my eyes off of you'", "'You’re killing it with that style'"], 0),
	("What’s a good way to test if someone’s interested while flirting? 🤔", ["Playfully touch their arm", "Give them a compliment and watch their reaction", "Ask them if they want to hang out", "See if they keep the conversation going"], 0),
	("What’s the best way to show you’re playful during flirting? 🤭", ["Use humor to make them laugh", "Send them funny memes", "Give them a teasing compliment", "Make light of the situation"], 0),
	("What’s the best way to keep a conversation flirty over text? 📲", ["Ask them intriguing questions", "Send playful emojis", "Keep the tone light and fun", "Compliment them often"], 0),
	("When flirting, what’s the best body language to show interest? 💃", ["Leaning in slightly", "Facing them directly", "Smiling often", "Maintaining eye contact"], 0),
	("What’s the best way to flirt with someone without being obvious? 😉", ["Subtle compliments", "Making light-hearted jokes", "Playful eye contact", "Casual touch on the arm"], 0),
	("What’s the best way to subtly flirt without saying a word? 👀", ["Maintaining eye contact", "Giving a slight smile", "Lightly touching your hair", "Tilting your head slightly"], 0),
	("What’s the best compliment to give when flirting? ❤️", ["You have such a magnetic personality", "Your smile lights up the room", "You’re so intriguing", "You look absolutely stunning"], 0),
	("Which type of flirty text is best to send after meeting someone? 📲", ["'I had such a great time with you'", "'Can’t wait to see you again'", "'You looked amazing tonight'", "'What’s your favorite thing to do for fun?'"], 0),
	("What’s the best response to a compliment when flirting? 😏", ["'Thanks, I think you’re amazing too'", "'You’re not so bad yourself'", "'I’m glad you noticed'", "'You just made my day'"], 0),
	("How can you tell if someone is flirting with you? 👀", ["They maintain eye contact", "They smile often", "They give you compliments", "They find excuses to touch you"], 0),
	("What’s the best way to make someone blush while flirting? 😊", ["Give them a sweet, sincere compliment", "Playfully tease them", "Look at them with a knowing smile", "Make them feel special with your attention"], 0),
	("What’s a fun flirty question to ask someone? 🤔", ["'What’s the most romantic thing you’ve done?'", "'Do you believe in love at first sight?'", "'What’s your idea of the perfect date?'", "'What’s your guilty pleasure?'"], 0),
	("How do you flirt with someone without being obvious? 😏", ["Subtle compliments", "Casual touch", "Playful teasing", "Making them laugh"], 0),
	("When flirting, what’s the best posture to have? 🕺", ["Stand tall with confidence", "Lean in slightly", "Cross your arms", "Relaxed but engaging"], 0),
	("What’s the best way to flirt with someone over text? 📱", ["Send playful messages", "Ask personal questions", "Use fun emojis", "Keep the tone light and humorous"], 0),
	("What’s a good way to flirt when you’re nervous? 😊", ["Smile and keep the conversation light", "Give a compliment", "Ask them questions about themselves", "Stay relaxed and confident"], 0),
	("What’s the best flirty emoji to use? 😉", ["Wink 😉", "Fire 🔥", "Heart ❤️", "Kiss 😘"], 0),
	("How do you show you’re interested when flirting? 😘", ["Make eye contact", "Ask them questions about their life", "Give them compliments", "Find ways to casually touch them"], 0),
	("What’s the best time to make a flirty move? ⏰", ["When the conversation is flowing", "When they give you signals", "When you’ve been talking for a while", "When there’s a moment of quiet"], 0),
	("What’s a flirty comment to make about someone’s smile? 😁", ["'Your smile is contagious'", "'You have the most beautiful smile'", "'I can’t stop thinking about your smile'", "'You’ve got a smile that lights up the room'"], 0),
	("What’s the best way to keep a flirtatious conversation going? 🗣️", ["Ask interesting questions", "Compliment them often", "Keep it playful", "Make them laugh"], 0),
	("What’s a good way to test if someone’s flirting back? 🤨", ["See if they mirror your actions", "See if they continue the conversation", "Check if they touch you back", "See if they initiate contact"], 0),
	("What’s a cute flirty thing to say when you’re shy? 😊", ["'You make me nervous but in a good way'", "'I’m not usually this shy'", "'I’m glad we’re talking'", "'You’re making me blush'"], 0),
	("What’s the best way to flirt when you’re both in a group? 👫", ["Find moments to make eye contact", "Subtly compliment them", "Use humor to get their attention", "Casually lean in when talking to them"], 0),
	("What’s a good way to flirt without being too forward? 🧐", ["Compliment them indirectly", "Ask them fun questions", "Keep the conversation light", "Flirt with body language rather than words"], 0),
	("How do you flirt when you’re feeling shy? 😳", ["Give subtle compliments", "Ask lighthearted questions", "Smile often", "Make eye contact when you can"], 0),
],
    'lolquiz': [
    ("What gets wetter the more it dries? 🧻", ["Sponge", "Towel", "Rain", "Soap"], 1),
    ("Why don't skeletons fight? ☠️", ["Lazy", "No guts", "Cowards", "Busy"], 1),
    ("What do you call fake spaghetti? 🍝", ["Mock-aroni", "Faux-ssili", "Impasta", "Pretendini"], 2),
    ("Why was the math book sad? 📖", ["Too easy", "Too hard", "Full of problems", "Lonely"], 2),
    ("What's orange and sounds like a parrot? 🦜", ["Pumpkin", "Carrot", "Sun", "Banana"], 1),
    ("What can run but can't walk? 🏃‍♂️", ["Dog", "River", "Wind", "Clock"], 1),
    ("Why can't your nose be 12 inches long? 👃", ["It would look weird", "It'd be a foot", "Hard to breathe", "No reason"], 1),
    ("What's always coming but never arrives? ⏳", ["Tomorrow", "Rain", "Hope", "Money"], 0),
    ("What has hands but can't clap? ✋", ["Robot", "Clock", "Zombie", "Octopus"], 1),
    ("What has a face but no eyes, mouth, or nose? 🕰️", ["Mask", "Clock", "Pumpkin", "Robot"], 1),
    ("What's full of holes but still holds water? 🧽", ["Sponge", "Bucket", "Boat", "Sieve"], 0),
    ("What's something you break before using? 🥚", ["Promise", "Egg", "Glass", "Phone"], 1),
    ("Why did the scarecrow win an award? 🌾", ["Great looks", "Scared birds", "Outstanding in his field", "Funny jokes"], 2),
    ("What invention lets you look through walls? 🪟", ["X-ray", "Window", "Door", "Periscope"], 1),
    ("What has 4 wheels and flies? 🚛", ["Airplane", "Truck", "Garbage truck", "Train"], 2),
    ("What can travel around the world while staying in a corner? ✉️", ["Plane ticket", "Stamp", "Postcard", "Compass"], 1),
    ("What can you catch but not throw? 🤧", ["Cold", "Ball", "Knife", "Boomerang"], 0),
    ("Why did the golfer bring two pants? ⛳", ["Style", "In case he got a hole in one", "Weather", "Sponsor"], 1),
    ("What comes once in a minute, twice in a moment, but never in a thousand years? ⏲️", ["Love", "Letter M", "Luck", "Dream"], 1),
    ("What's easy to lift but hard to throw far? 🕊️", ["Balloon", "Feather", "Paper", "Pillow"], 0),
    ("What’s big, green, and sings? 🎤", ["Elvis Parsley", "Cucumber King", "Kale Jagger", "Broccoli Spears"], 0),
	("Why don’t oysters donate to charity? 🦪", ["They’re shellfish", "They’re poor", "They don’t trust banks", "They’re too salty"], 0),
	("What do you call cheese that isn’t yours? 🧀", ["Nacho cheese", "Stolen cheese", "Cheddar", "Feta on the run"], 0),
	("Why did the tomato turn red? 🍅", ["It saw the salad dressing", "It got embarrassed", "It was ripe", "It was a sunburn"], 0),
	("What’s a skeleton’s least favorite room in the house? 💀", ["The dining room", "The bedroom", "The living room", "The closet"], 0),
	("Why don’t eggs tell jokes? 🥚", ["They’d crack up", "They’re scrambled", "They’re too fried", "They’re overcooked"], 0),
	("What’s the best way to watch a fly fishing tournament? 🎣", ["Live stream", "Catch the highlights", "Hook in", "Catch it on TV"], 0),
	("Why did the bicycle fall over? 🚲", ["It was two-tired", "It was lost", "It was rusty", "It couldn’t stand up"], 0),
	("What’s brown and sticky? 🍯", ["A stick", "Chocolate syrup", "Caramel", "Mud"], 0),
	("What has a bottom at the top? ⛰️", ["A leg", "A mountain", "A cup", "A bottle"], 1),
	("Why can’t you give Elsa from Frozen a balloon? 🎈", ["She'll let it go", "She’s afraid of heights", "She hates parties", "She freezes it"], 0),
	("Why don’t skeletons ever use cell phones? 📱", ["They don’t have the guts", "They don’t need them", "They have no fingers", "They’re dead"], 0),
	("What did one hat say to the other hat? 🎩", ["Stay here, I'm going on ahead", "You’re looking sharp", "You’re cap-tivating", "We’re a great pair"], 0),
	("Why did the golfer bring extra socks? 🧦", ["In case he got a hole in one", "For style", "He had a foot problem", "He was ready for a fashion show"], 1),
	("What do you call a fake noodle? 🍝", ["An impasta", "A noodle imposter", "Faux-ssili", "Spaghetti counterfeit"], 0),
	("What do you call a bear with no teeth? 🐻", ["A gummy bear", "A softy", "A toothless wonder", "A cuddly bear"], 0),
	("Why was the math book always stressed? 📚", ["Too many problems", "It couldn’t solve itself", "It had too many pages", "It was just too calculated"], 0),
	("What do you call a group of musical whales? 🐋", ["An orca-stra", "A whale ensemble", "Sea-sonal performers", "A whale tune"], 0),
	("Why did the chicken go to the party? 🐔", ["To lay down some dance moves", "To crack some eggs", "To get to the other side", "To have a cluckin' good time"], 1),
	("What’s orange and sounds like a parrot? 🍊", ["A carrot", "A banana", "An orange", "A pineapple"], 1),
	("What do you get when you cross a snowman and a vampire? ☃️", ["Frostbite", "Cold blood", "A chill in the air", "A blood freeze"], 0),
	("Why did the scarecrow become a successful actor? 🎭", ["He was outstanding in his field", "He had a great script", "He knew how to stand out", "He had a lot of fans"], 0),
	("What did the pencil say to the paper? ✏️", ["I’m drawing a blank", "You’re so note-worthy", "Let’s make a point", "You’re so sketchy"], 0),
	("What do you call an alligator in a vest? 🐊", ["An investigator", "A stylish reptile", "An alligator with fashion sense", "A swamp detective"], 0),
	("Why did the computer go to the doctor? 💻", ["It had a virus", "It was feeling a bit byte", "It needed a reboot", "It had a hardware failure"], 0),
	("Why don’t skeletons fight each other? 💀", ["They don’t have the guts", "They’re too busy dancing", "They don’t want to get hurt", "They have no fight left in them"], 0),
	("What did one ocean say to the other ocean? 🌊", ["Nothing, they just waved", "I’m feeling salty", "See you on the other tide", "I’m shore you’ll be fine"], 0),
	("Why can’t your nose be 12 inches long? 👃", ["Because then it’d be a foot", "It would look ridiculous", "You wouldn’t be able to breathe", "It would ruin your sense of smell"], 0),
	("Why did the bicycle fall over? 🚴", ["Because it was two-tired", "It was having a rough ride", "It lost its balance", "It wasn’t feeling well"], 0),
	("What’s green and sings? 🎤", ["Elvis Parsley", "Kale Jagger", "Lettuce Presley", "Broccoli Spears"], 0),
	("What did one hat say to the other hat? 🎩", ["Stay here, I’m going on ahead", "You’re looking sharp", "You’re totally top hat material", "We make a great pair"], 0),
	("Why was the math book sad? 📖", ["It had too many problems", "It was full of issues", "It was struggling with its calculations", "It needed a solution"], 0),
	("What’s brown and sticky? 🍯", ["A stick", "Chocolate syrup", "Honey", "Tree sap"], 0),
	("Why don’t eggs tell jokes? 🥚", ["They’d crack each other up", "They’re too scrambled", "They’re too fried", "They might crack under pressure"], 0),
	("What do you call a dinosaur with an extensive vocabulary? 🦖", ["A thesaurus", "A word-a-saurus", "A knowledge rex", "A talkasaurus"], 0),
	("What’s the best way to watch a fly fishing tournament? 🎣", ["Live stream", "Catch the highlights", "Hook in", "Watch the reel action"], 0),
	("Why did the golfer bring extra socks? 🧦", ["In case he got a hole in one", "He was looking for a match", "For style", "Because of the weather"], 0),
	("What do you call a lazy kangaroo? 🦘", ["A pouch potato", "A jump slacker", "A hopless case", "A down-under sleeper"], 0),
	("What did the grape say when it got stepped on? 🍇", ["Nothing, it just let out a little wine", "It was crushed", "It got jammed", "It couldn’t raisin its voice"], 0),
	("Why did the tomato turn red? 🍅", ["Because it saw the salad dressing", "It was ripe for the picking", "It blushed", "It was embarrassed to be in the salad"], 0),
	("What do you call a dog magician? 🐕", ["A labracadabrador", "A poodle-prestidigitator", "A doggone illusionist", "A canine conjurer"], 0),
	("Why did the bicycle need a rest? 🚲", ["It was two-tired", "It needed to recharge", "It was worn out", "It was feeling flat"], 0),
	("Why did the coffee file a police report? ☕", ["It got mugged", "It spilled the beans", "It was brewed to perfection", "It had a bad day"], 0),
	("What did the janitor say when he jumped out of the closet? 🧹", ["Supplies!", "I’m here to clean up", "Watch out, I’m sweeping through", "Ready to scrub!"], 0),
	("Why did the computer go to the beach? 💻", ["To surf the web", "To get a byte", "It needed a reboot", "It had a virus"], 0),
	("What do you call an alligator in a vest? 🐊", ["An investigator", "A gator in style", "A fashionista reptile", "A crocodile detective"], 0),
	("What do you get when you cross a snowman and a dog? ☃️🐕", ["Frostbite", "A cold pup", "Chilly paws", "A snow dog"], 0),
	("Why don't skeletons ever fight? 💀", ["They don’t have the guts", "They’re too cool for that", "They’re dead inside", "They don’t want to get into bones of trouble"], 0),
	("Why can’t you trust stairs? 🪜", ["They’re always up to something", "They’re too steeped in drama", "They’re a step behind", "They’re too shady"], 0),
	("What did the baby corn say to the mama corn? 🌽", ["Where’s popcorn?", "I’m a-maize-ing!", "You’re ear-resistible!", "I’m feeling corny today"], 0),
	("Why did the golfer bring two pairs of pants? ⛳", ["In case he got a hole in one", "For extra style", "For the weather", "Because he’s a pro"], 0),
	("What’s a skeleton’s least favorite room? 🏠", ["The living room", "The dining room", "The closet", "The bathroom"], 0),
	("Why did the chicken join a band? 🐔", ["Because it had the drumsticks", "It loved egg-citing music", "To lay down some beats", "Because it was a cluckin' musician"], 0),
	("What’s the most efficient way to make a tissue dance? 💃", ["Put a little boogey in it", "Give it a fun tune", "Throw it in the air", "Add some rhythm and flow"], 0),
	("Why was the math book so unhappy? 📚", ["It had too many problems", "It was very square", "It was irrational", "It couldn’t solve its issues"], 0),
	("What kind of shoes do ninjas wear? 👟", ["Sneakers", "Stealth sandals", "Kicks", "Ninja boots"], 0),
	("What’s a cow’s favorite hobby? 🐄", ["Cow-llecting milk", "Moo-sic", "Bovine browsing", "Grass art"], 0),
	("Why don’t eggs ever fight? 🥚", ["They might crack up", "They scramble too much", "They get too hard-boiled", "They are too soft to argue"], 0),
	("What did the grape do when it got stepped on? 🍇", ["It let out a little wine", "It got crushed", "It got really jammed", "It was squeezed out of shape"], 0),
	("Why can’t you ever trust an atom? ⚛️", ["They make up everything", "They’re always splitting", "They’re unstable", "They’re always positive"], 0),
	("Why was the broom late? 🧹", ["It swept in", "It was caught in traffic", "It got stuck in the closet", "It was sweeping through town"], 0),
	("Why don’t skeletons like to fight each other? 💀", ["They don’t have the guts", "They prefer to dance", "They’re bone lazy", "They never have the muscle for it"], 0),
	("What do you call a fish with no eyes? 🐟", ["Fsh", "An eye-less fish", "A blind fish", "A no-see fish"], 0),
	("Why did the bicycle fall over? 🚲", ["It was two-tired", "It had a flat", "It was spinning out of control", "It couldn’t handle the ride"], 0),
	("What did one wall say to the other? 🧱", ["I’ll meet you at the corner", "We’ve got to stick together", "Let’s build a friendship", "Nothing, they just leaned on each other"], 0),
	("Why don’t skeletons fight each other? 💀", ["They don’t have the guts", "They don’t have the energy", "They’re afraid of getting into bone-breaking trouble", "They don’t want to be in a grave situation"], 0),
	("What do you call a pile of cats? 🐱", ["A meow-tain", "A cat-astrophe", "A purr-pile", "A feline stack"], 0),
	("What do you call fake noodles? 🍝", ["Impasta", "Faux-ssili", "Pretendini", "Not-your-ramen"], 0),
	("Why can’t you trust stairs? 🪜", ["They’re always up to something", "They’re too step-ful", "They can’t handle pressure", "They’ll always let you down"], 0),
	("What do you call a snowman in the summer? ☃️", ["A puddle", "A melted guy", "A cool dude", "A sunburned snowman"], 0),
	("Why was the math book sad? 📖", ["It had too many problems", "It couldn’t figure out its issues", "It was filled with equations", "It couldn’t find the solution"], 0),
	("Why don’t oysters share their pearls? 🦪", ["Because they’re shellfish", "They’re a bit snobby", "They like to keep things in the family", "They’re too clammed up"], 0),
	("What do you call a dinosaur with an extensive vocabulary? 🦖", ["A thesaurus", "A word-a-saurus", "A knowledge rex", "A talking-tops"], 0),
	("What’s orange and sounds like a parrot? 🦜", ["A carrot", "A pumpkin", "An orange", "A banana"], 0),
	("Why don’t skeletons ever go trick-or-treating? 🎃", ["They have no body to go with", "They’re too bony", "They’re afraid of getting too thin", "They don’t have the stomach for it"], 0),
	("What do you call a lazy kangaroo? 🦘", ["A pouch potato", "A hop-less jumper", "A down-under napper", "A sleepy roo"], 0),
	("Why did the golfer bring an extra pair of pants? ⛳", ["In case he got a hole in one", "For style", "For extra pockets", "To be prepared for the weather"], 0),
	("Why was the computer cold? 💻", ["Because it left its Windows open", "It didn’t have enough RAM", "It needed a reboot", "It was just too techy"], 0),
	("Why do cows wear bells? 🐄", ["Because their horns don’t work", "To make a moo-sic", "To make sure they’re heard", "Because it’s cow-chic"], 0),
	("Why don’t you ever see elephants hiding in trees? 🐘", ["Because they’re really good at it", "Because they’re too big to hide", "Because they’re never in the trees", "Because they like open spaces"], 0),
	("What did the grape do when it got stepped on? 🍇", ["Nothing, it just let out a little wine", "It squished", "It made a jam", "It got squeezed"], 0),
	("What did the fish say when it hit the wall? 🐟", ["Dam!", "Oh, no!", "That was a fishy situation", "Splash!"], 0),
	("Why can’t your nose be 12 inches long? 👃", ["Because then it would be a foot", "It would look funny", "It would be too hard to breathe", "Because that’s just how noses work"], 0),
	("Why don’t eggs tell jokes? 🥚", ["Because they might crack up", "They’re too scrambled", "They’re a little fried", "Because they’re too sunny-side up"], 0),
],
    'cquiz': [
    ("Can pigs actually fly? ✈️", ["Only in dreams", "Yes", "No", "Maybe"], 2),
    ("What color is a mirror? 🪞", ["Silver", "Clear", "Invisible", "Depends"], 0),
    ("If you punch yourself and it hurts, are you weak or strong? ✊", ["Strong", "Weak", "Both", "Confused"], 3),
    ("Can you cry underwater? 🌊", ["Yes", "No", "Only dolphins", "Maybe"], 0),
    ("Do fish get thirsty? 🐠", ["Yes", "No", "Sometimes", "At night"], 1),
    ("If you drop soap on the floor, is the soap dirty or the floor clean? 🧼", ["Soap dirty", "Floor clean", "Both", "Neither"], 2),
    ("Can you taste a dream? 🌙", ["Yes", "No", "Maybe", "Inception"], 2),
    ("If a tree falls in a forest and no one hears it, does it make a sound? 🌳", ["Yes", "No", "Maybe", "Depends who's asking"], 0),
    ("Can you lick your elbow? 👅", ["Yes", "No", "Some can", "Aliens only"], 1),
    ("Why do we press harder on a remote when it’s low on battery? 📺", ["More power", "Habit", "Magic", "Desperation"], 1),
    ("If two mind readers read each other’s minds, whose mind are they reading? 🧠", ["Each other", "Nobody's", "Paradox", "Alien signals"], 2),
    ("Is cereal soup? 🥣", ["Yes", "No", "Sometimes", "Brain explosion"], 0),
    ("Can you smell colors? 🎨", ["No", "Only artists", "Maybe", "In dreams"], 2),
    ("Can you yawn with your eyes closed? 🥱", ["Yes", "No", "Sometimes", "Impossible"], 0),
    ("Why isn’t 'phonetic' spelled the way it sounds? 🌀", ["English is weird", "Magic", "Because", "Who knows"], 0),
    ("If you try to fail and succeed, what did you just do? ❓", ["Fail", "Succeed", "Both", "Unlock a secret"], 2),
    ("Can you stand backwards on stairs? 🏛️", ["Yes", "No", "Depends", "Stairs are lies"], 0),
    ("If you eat yourself, do you get twice as big or disappear? 🍴", ["Bigger", "Vanish", "Mutate", "Cry"], 1),
    ("If a vampire bites a zombie, what happens? 🧛‍♂️🧟‍♂️", ["Super zombie", "Vampire zombie", "Nothing", "End of the world"], 1),
    ("If we can see water, can fish see air? 🐟", ["Yes", "No", "Maybe", "Depends on the fish"], 1),
    ("Can you sneeze with your eyes open? 🤧", ["Yes", "No", "Sometimes", "Only with superpowers"], 1),
	("Can you tickle yourself? 😂", ["Yes", "No", "Sometimes", "Only in dreams"], 1),
	("Is it possible to cry in space? 🚀", ["Yes", "No", "Maybe", "In zero gravity"], 0),
	("Can you be both awake and asleep at the same time? 😴", ["Yes", "No", "Maybe", "Depends on the time zone"], 2),
	("Why do we get hiccups? 🤭", ["Unknown", "Because of spicy food", "We’re allergic to air", "Aliens are messing with us"], 0),
	("Can you think with your mouth? 🧠", ["Yes", "No", "Only with a lot of pizza", "If you're a genius"], 1),
	("Do you age in space? 🌌", ["Yes", "No", "Depends on how fast you’re moving", "Time stands still"], 2),
	("What happens if you drop a clock in water? ⏰", ["It gets wet", "It keeps ticking", "It breaks", "Time stops"], 0),
	("Can you sneeze in slow motion? 🐢", ["Yes", "No", "Sometimes", "With enough practice"], 2),
	("If you speak in an empty room, does it echo? 🏠", ["Yes", "No", "Depends on the room", "Only if you're loud"], 2),
	("Can plants hear you? 🌱", ["Yes", "No", "Maybe", "They can feel vibrations"], 3),
	("Why does the sun make us feel warm? ☀️", ["Because of radiation", "Because it’s bright", "It’s a magic ball", "It loves us"], 0),
	("Can you run faster than a cheetah? 🐆", ["Yes, with the right shoes", "No, unless you're a superhero", "Maybe with a car", "Only if it’s sleeping"], 1),
	("Can you see the wind? 🌬️", ["Yes, sometimes", "No", "Only if you have x-ray vision", "Only if it’s blowing dust"], 1),
	("What’s heavier: a ton of feathers or a ton of bricks? 🪶", ["Both are the same", "Feathers", "Bricks", "Neither, it’s magic"], 0),
	("Can your thoughts be louder than sound? 🤯", ["Yes", "No", "Sometimes", "Only in your head"], 2),
	("Why can’t you eat soup with a fork? 🍲", ["It’s too chunky", "Forks are not for soup", "Soup is liquid", "Soup doesn’t want you to eat it"], 0),
	("Can you drown in a puddle? 🌧️", ["Yes", "No", "Maybe if you're really small", "Only if it’s a big puddle"], 2),
	("Why do we dream? 🌙", ["To process thoughts", "It’s our brains having fun", "Because sleep is boring", "To unlock mysteries"], 0),
	("If the moon is made of cheese, can we eat it? 🧀", ["Yes", "No", "Only in cartoons", "Moon cheese is expired"], 2),
	("If cats ruled the world, what would humans be? 🐱", ["Pets", "Servants", "Food", "Celebrities"], 1),
	("What shape is a rainbow? 🌈", ["Flat", "Circle", "Triangle", "Line"], 1),
	("If you dig a hole through the Earth, where do you come out? 🌍", ["China", "The sky", "Depends where you start", "Outer space"], 2),
	("Is a hotdog a sandwich? 🌭", ["Yes", "No", "Maybe", "Philosophy question"], 0),
	("Can you burp in space? 🚀", ["Yes", "No", "You explode", "Only backwards"], 0),
	("What happens if you microwave ice? 🧊", ["It melts", "It explodes", "It freezes more", "Turns invisible"], 0),
	("If you paint a car invisible, can you still drive it? 🚗", ["Yes", "No", "Only if you wear sunglasses", "Depends on the paint"], 0),
	("If chickens could talk, what would they say? 🐔", ["Feed me", "Where’s my egg?", "Cluck off", "Why the crossing jokes?"], 3),
	("Is it illegal to drive backwards forever? 🛻", ["Yes", "No", "Depends where", "Depends who's asking"], 2),
	("If you replace your blood with maple syrup, what happens? 🍁", ["Super speed", "Sticky death", "Sweet dreams", "Nothing"], 1),
	("Can you smell your own brain? 🧠", ["No", "Yes", "Only after thinking hard", "Smells like burnt toast"], 0),
	("If you shout in a vacuum, can you hear it? 🕳️", ["Yes", "No", "Only if you're loud enough", "Echo forever"], 1),
	("Can you actually touch a rainbow? 🌈", ["Yes", "No", "Only unicorns can", "With enough hope"], 1),
	("What’s faster: gossip or light? 🗣️", ["Light", "Gossip", "Equal", "Depends on who's talking"], 1),
	("Can you marry yourself legally? 💍", ["Yes", "No", "Depends on the country", "Only if you really love yourself"], 2),
	("If a donut has no hole, is it still a donut? 🍩", ["Yes", "No", "Now it's cake", "Depends on the flavor"], 0),
	("If you name your pet 'Dog' but it’s a cat, what is it? 🐕", ["Dog", "Cat", "Confused", "Bilingual"], 2),
	("What happens if you tickle a shark? 🦈", ["It laughs", "It bites", "It dances", "It swims away embarrassed"], 1),
	("If laughter is the best medicine, what’s the worst? 😂", ["Silence", "Sadness", "Tickling too hard", "Expired ice cream"], 3),
	("Can you outrun a fart? 💨", ["Yes", "No", "Only if you sprint", "It will always catch you"], 3),
	("If you scream into a jar and close the lid, does the scream stay inside? 🫙", ["Yes", "No", "Only if you whisper", "Depends on the jar"], 1),
	("Can you sneeze with your eyes open? 🤧", ["Yes", "No", "Only ninjas", "Only during a full moon"], 1),
	("What weighs more: a pound of feathers or a pound of bricks? ⚖️", ["Bricks", "Feathers", "Same", "Depends on gravity"], 2),
	("If you put sunglasses on a fish, what happens? 🐟🕶️", ["Cool fish", "Blind fish", "Nothing", "New species"], 0),
	("Can an ant carry a car if it was giant-sized? 🐜", ["Yes", "No", "Maybe", "It would drive it instead"], 0),
	("If you ate only carrots, what color might you turn? 🥕", ["Blue", "Orange", "Green", "Purple"], 1),
	("If your shadow disappears, what does it mean? 🌑", ["You’re a ghost", "You're invisible", "No light", "Bad omen"], 2),
	("What happens if you put a sweater on a snake? 🐍", ["It cuddles", "It panics", "It looks fabulous", "It slithers faster"], 2),
	("If you had wheels instead of feet, what would be your top speed? 🛞", ["50 km/h", "Depends on road", "Infinity", "5 km/h"], 1),
	("Can you hear silence? 🤫", ["Yes", "No", "Sometimes", "Only with special ears"], 0),
	("If you shave a tiger, what color is its skin? 🐯", ["Orange with stripes", "White", "Pink", "Spotted"], 0),
	("Is water wet? 💧", ["Yes", "No", "Only sometimes", "Depends who you ask"], 0),
	("If you spin in circles for 5 minutes, what happens? 🌀", ["Time travel", "You faint", "You fly", "You see colors"], 1),
	("If you plant a donut, what grows? 🍩", ["Donut tree", "Nothing", "Sugar cane", "Carrot"], 1),
	("Can a snowman survive in the desert with AC? ☃️", ["Yes", "No", "Depends how strong the AC is", "Only at night"], 2),
	("If dogs ruled the world, what would humans fetch? 🐕", ["Bones", "Pizza", "Tennis balls", "Dogs"], 2),
	("If a joke is so bad it’s good, what is it called? 🤪", ["Dad joke", "Fail", "Pun", "Brain twister"], 0),
	("If gravity took a coffee break, what would happen? ☕", ["We float", "We melt", "Nothing", "Earth explodes"], 0),
	("Can you bite your own teeth? 🦷", ["Yes", "No", "Only when dreaming", "If you chew fast"], 1),
	("If a chameleon looked into a mirror, what color would it be? 🦎", ["Clear", "Confused", "Mirror-colored", "Invisible"], 1),
	("If you cloned yourself, who would be older? 👯", ["You", "Clone", "Same age", "Depends on haircut"], 2),
	("Can you dig half a hole? 🕳️", ["Yes", "No", "Only in dreams", "Depends on the shovel"], 1),
	("If you microwave ice, what happens? ❄️", ["It melts", "It explodes", "It grows", "It sings"], 0),
	("If a cat barked, what animal would it be? 🐱", ["Dog", "Still a cat", "Hybrid", "Alien"], 1),
	("Is it possible to have a day with no night? ☀️", ["Yes", "No", "Only at poles", "Only on weekends"], 2),
	("Can plants hear music? 🎶", ["Yes", "No", "Maybe", "They dance secretly"], 2),
	("If you sleepwalk and win a marathon, do you get the medal? 🏅", ["Yes", "No", "Only half", "You get disqualified"], 0),
	("If you charge your phone during a thunderstorm, will it gain superpowers? ⚡", ["Yes", "No", "Maybe", "Only in cartoons"], 1),
	("If rain had flavors, which would be weirdest? ☔", ["Vanilla", "Pickle", "Strawberry", "Chocolate"], 1),
	("If you wore shoes on your hands, what would gloves be called? 🧤", ["Feet hats", "Hand shoes", "Toe warmers", "Confusing"], 1),
	("If you could only speak in rhymes, what would life feel like? 🎤", ["Poetry", "Chaos", "Opera", "A rap battle"], 3),
	("If you fart in a spaceship, where does it go? 🚀", ["Stays there", "Out the window", "Creates gravity", "Summons aliens"], 0),
	("Can you tickle yourself? 🤭", ["Yes", "No", "Only ninjas", "With great power"], 1),
	("If you paint a zebra pink, what is it? 🦓", ["Pink horse", "Still zebra", "Giant candy cane", "Confused animal"], 1),
	("Can you outrun your own shadow? ☄️", ["Yes", "No", "Only during sunset", "If you're The Flash"], 3),
	("If a ghost sneezes, does it make a sound? 👻", ["Yes", "No", "Only dogs hear it", "Depends on the ghost"], 3),
	("If Monday were a food, what would it taste like? 🥴", ["Chocolate", "Broccoli", "Burnt toast", "Rain"], 2),
	("If you laugh hard enough, can you lift off the ground? 🛫", ["Yes", "No", "Only with helium", "Only in cartoons"], 3),
	("Can you sneeze and cough at the same time? 😵", ["Yes", "No", "You explode", "You teleport"], 0),
	("If clouds were made of cotton candy, what would happen when it rained? ☁️", ["Stickiness everywhere", "Rainbow floods", "No rain", "Bubblegum tornado"], 0),
],
    'squiz': [
    ("What planet is known as the Red Planet? 🔴", ["Earth", "Mars", "Jupiter", "Venus"], 1),
    ("How many legs does a spider have? 🕷️", ["6", "8", "10", "12"], 1),
    ("What's the freezing point of water? ❄️", ["0°C", "32°C", "100°C", "10°C"], 0),
    ("Which gas do plants breathe in? 🌿", ["Oxygen", "Carbon Dioxide", "Hydrogen", "Helium"], 1),
    ("What's the tallest animal? 🦒", ["Elephant", "Giraffe", "Horse", "Kangaroo"], 1),
    ("What do bees make? 🍯", ["Milk", "Honey", "Wax", "Pollen"], 1),
    ("How many colors are there in a rainbow? 🌈", ["5", "6", "7", "8"], 2),
    ("What do you call baby cats? 🐱", ["Kittens", "Puppies", "Calves", "Chicks"], 0),
    ("What is the largest mammal? 🐋", ["Elephant", "Blue Whale", "Shark", "Hippo"], 1),
    ("Which organ pumps blood? ❤️", ["Lungs", "Heart", "Liver", "Kidney"], 1),
    ("What is the boiling point of water? ♨️", ["50°C", "80°C", "100°C", "120°C"], 2),
    ("Which planet is closest to the Sun? ☀️", ["Venus", "Earth", "Mercury", "Mars"], 2),
    ("How many days in a leap year? 🗓️", ["365", "366", "364", "367"], 1),
    ("What do cows drink? 🐄", ["Milk", "Water", "Juice", "Grass"], 1),
    ("Which bird is the fastest? 🦅", ["Owl", "Peregrine Falcon", "Eagle", "Hawk"], 1),
    ("How many sides does a triangle have? 🔺", ["2", "3", "4", "5"], 1),
    ("Which metal is liquid at room temperature? ⚗️", ["Gold", "Mercury", "Silver", "Iron"], 1),
    ("Which animal is known as 'King of the Jungle'? 🦁", ["Tiger", "Lion", "Leopard", "Bear"], 1),
    ("What is Earth's only natural satellite? 🌕", ["Sun", "Moon", "Mars", "Venus"], 1),
    ("What type of animal is a frog? 🐸", ["Mammal", "Bird", "Amphibian", "Reptile"], 2),
    ("What part of the plant conducts photosynthesis? 🌿", ["Root", "Stem", "Leaf", "Flower"], 2),
	("Which shape has four equal sides? ◻️", ["Rectangle", "Square", "Triangle", "Circle"], 1),
	("What gas do humans need to breathe? 🌬️", ["Oxygen", "Carbon Dioxide", "Nitrogen", "Helium"], 0),
	("What is the capital city of France? 🇫🇷", ["Berlin", "Paris", "Madrid", "Rome"], 1),
	("How many continents are there? 🌍", ["5", "6", "7", "8"], 2),
	("What is H2O commonly known as? 💧", ["Oxygen", "Salt", "Water", "Hydrogen"], 2),
	("Which planet is known for its rings? ", ["Mars", "Jupiter", "Saturn", "Uranus"], 2),
	("Who wrote 'Romeo and Juliet'? ✍️", ["Charles Dickens", "William Shakespeare", "Mark Twain", "Jane Austen"], 1),
	("How many bones are in the adult human body? 🦴", ["206", "208", "201", "212"], 0),
	("What is the largest continent by area? 🗺️", ["Africa", "Asia", "Europe", "South America"], 1),
	("Which month has 28 or 29 days? 📆", ["January", "February", "March", "April"], 1),
	("Which ocean is the largest? 🌊", ["Atlantic", "Pacific", "Indian", "Arctic"], 1),
	("What is the chemical symbol for gold? ⚡", ["Au", "Ag", "Gd", "Go"], 0),
	("Which language has the most native speakers? 🗣️", ["English", "Spanish", "Mandarin Chinese", "Hindi"], 2),
	("What is the square root of 81? 🧮", ["9", "8", "7", "6"], 0),
	("What type of animal is a shark? 🦈", ["Mammal", "Reptile", "Fish", "Amphibian"], 2),
	("How many planets are in our solar system? 🪐", ["7", "8", "9", "10"], 1),
	("Which country is famous for inventing pizza? 🍕", ["France", "Italy", "USA", "Spain"], 1),
	("Which blood type is known as the universal donor? 🩸", ["A", "O-", "B", "AB"], 1),
	("What organ is responsible for filtering blood? 🧽", ["Liver", "Kidney", "Heart", "Lung"], 1),
	("What is the largest planet in our solar system? ", ["Earth", "Saturn", "Jupiter", "Mars"], 2),
	("Who discovered gravity when he saw a falling apple? 🍎", ["Einstein", "Galileo", "Newton", "Tesla"], 2),
	("Which continent is the Sahara Desert located in? 🏜️", ["Asia", "Africa", "Australia", "Europe"], 1),
	("How many hours are there in two days? ⏰", ["24", "36", "48", "72"], 2),
	("What organ helps you digest food? 🍔", ["Liver", "Stomach", "Lungs", "Heart"], 1),
	("Which instrument has keys, pedals, and strings? 🎹", ["Guitar", "Flute", "Piano", "Violin"], 2),
	("What is the smallest prime number? 🔢", ["0", "1", "2", "3"], 2),
	("Who painted the Mona Lisa? 🎨", ["Picasso", "Leonardo da Vinci", "Van Gogh", "Michelangelo"], 1),
	("What is the fastest land animal? 🏃‍♂️", ["Lion", "Horse", "Cheetah", "Eagle"], 2),
	("Which part of the eye controls how much light enters? 👁️", ["Pupil", "Iris", "Lens", "Cornea"], 0),
	("Which country is known as the Land of the Rising Sun? ☀️", ["China", "Korea", "Japan", "India"], 2),
	("What is the process by which plants make food? 🌞", ["Digestion", "Photosynthesis", "Respiration", "Germination"], 1),
	("How many teeth does an adult human usually have? 🦷", ["28", "30", "32", "34"], 2),
	("What do you call molten rock after it has erupted from a volcano? 🌋", ["Magma", "Lava", "Ash", "Smoke"], 1),
	("What is the capital of Japan? 🇯🇵", ["Kyoto", "Osaka", "Tokyo", "Seoul"], 2),
	("Which metal is most commonly used for making wires? 🔌", ["Iron", "Copper", "Gold", "Aluminum"], 1),
	("Which planet is famous for its Great Red Spot? ", ["Mars", "Saturn", "Earth", "Jupiter"], 3),
	("Which human organ is able to regenerate itself? 🩺", ["Lung", "Kidney", "Liver", "Heart"], 2),
	("What is the chemical symbol for salt? 🧂", ["SO", "NaCl", "KCl", "H2O"], 1),
	("Which bird can mimic human speech? 🦜", ["Crow", "Parrot", "Sparrow", "Eagle"], 1),
	("What gas do humans need to breathe to survive? 🌬️", ["Nitrogen", "Oxygen", "Carbon Dioxide", "Hydrogen"], 1),
	("Which planet has the most moons? 🪐", ["Earth", "Saturn", "Venus", "Neptune"], 1),
	("Who wrote 'Romeo and Juliet'? ✍️", ["Shakespeare", "Dickens", "Homer", "Plato"], 0),
	("What is the main language spoken in Brazil? 🇧🇷", ["Spanish", "Portuguese", "French", "Italian"], 1),
	("How many continents are there on Earth? 🌎", ["5", "6", "7", "8"], 2),
	("What is the largest ocean on Earth? 🌊", ["Atlantic", "Pacific", "Indian", "Arctic"], 1),
	("What part of the plant conducts photosynthesis? 🌱", ["Roots", "Stem", "Leaves", "Flowers"], 2),
	("What is the chemical symbol for gold? 🥇", ["G", "Go", "Au", "Ag"], 2),
	("What is the hardest natural substance? 💎", ["Steel", "Diamond", "Granite", "Bone"], 1),
	("How many chambers are in the human heart? ❤️", ["2", "3", "4", "5"], 2),
	("Which scientist developed the theory of relativity? 🧠", ["Newton", "Darwin", "Einstein", "Hawking"], 2),
	("What type of celestial body is the Sun? ☀️", ["Planet", "Asteroid", "Star", "Moon"], 2),
	("What do we call animals that eat both plants and meat? 🐾", ["Carnivores", "Herbivores", "Omnivores", "Insectivores"], 2),
	("Which planet is famous for its beautiful rings? ", ["Mars", "Saturn", "Uranus", "Venus"], 1),
	("Which blood type is known as the universal donor? 🩸", ["O+", "A-", "O-", "AB+"], 2),
	("What is the main ingredient in bread? 🍞", ["Sugar", "Yeast", "Flour", "Salt"], 2),
	("Which country gifted the Statue of Liberty to the USA? 🗽", ["England", "Germany", "France", "Italy"], 2),
	("How many bones are in an adult human body? 🦴", ["206", "201", "210", "215"], 0),
	("What is the boiling point of water in Fahrenheit? ♨️", ["100°F", "180°F", "212°F", "300°F"], 2),
	("What is the largest internal organ in the human body? 🧍‍♂️", ["Brain", "Heart", "Liver", "Kidneys"], 2),
	("What instrument measures temperature? 🌡️", ["Barometer", "Thermometer", "Seismograph", "Altimeter"], 1),
	("Which planet is nicknamed the 'Morning Star'? 🌟", ["Mars", "Venus", "Jupiter", "Mercury"], 1),
	("Which country is the largest by land area? 🗺️", ["USA", "Russia", "China", "Canada"], 1),
	("What is H2O commonly known as? 💧", ["Salt", "Water", "Oxygen", "Hydrogen"], 1),
	("What shape has six sides? 🔷", ["Square", "Hexagon", "Pentagon", "Octagon"], 1),
	("What part of the cell contains DNA? 🧬", ["Cell wall", "Nucleus", "Mitochondria", "Cytoplasm"], 1),
	("How many teeth does an adult human have? 🦷", ["28", "30", "32", "34"], 2),
	("What is the fastest land animal? 🏃‍♂️", ["Lion", "Cheetah", "Leopard", "Horse"], 1),
	("What is the capital of France? 🇫🇷", ["London", "Berlin", "Paris", "Rome"], 2),
	("Which element is needed for breathing and burning? 🔥", ["Carbon", "Oxygen", "Nitrogen", "Helium"], 1),
	("Which is the smallest planet in our solar system? 🪐", ["Mars", "Venus", "Mercury", "Pluto"], 2),
	("What organ helps you digest food? 🍽️", ["Heart", "Brain", "Stomach", "Lungs"], 2),
	("Which month has the fewest days? 📅", ["January", "February", "March", "April"], 1),
	("How many strings does a standard guitar have? 🎸", ["4", "5", "6", "7"], 2),
	("What gas makes up most of Earth’s atmosphere? 🌍", ["Oxygen", "Nitrogen", "Carbon Dioxide", "Hydrogen"], 1),
	("What is the main ingredient in sushi? 🍣", ["Beef", "Rice", "Pasta", "Potato"], 1),
	("Who painted the Mona Lisa? 🖼️", ["Michelangelo", "Van Gogh", "Leonardo da Vinci", "Picasso"], 2),
	("Which ocean is the deepest? 🌊", ["Atlantic", "Pacific", "Indian", "Arctic"], 1),
	("Which scientist discovered gravity? 🍎", ["Einstein", "Newton", "Galileo", "Tesla"], 1),
	("What is the chemical formula for table salt? 🧂", ["NaCl", "CO2", "H2O", "O2"], 0),
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

# Initialize shuffle for all quizzes
for quiz_type in quizzes:
    reset_shuffled(quiz_type)

# --- USER MANAGEMENT ---
def ensure_user(connection, user_id, username):
    try:
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
        connection.commit()
    except Exception as e:
        connection.rollback()
        print("Database error in ensure_user:", e)

# In the start command, ensure you pass the connection
def start(update, context):
    user = update.message.from_user
    ensure_user(connection, user.id, user.username or user.first_name)
    # Continue with the rest of your code...

def update_score(user_id: int, correct: bool):
    if correct:
        cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id=?", (user_id,))
    else:
        cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id=?", (user_id,))
    conn.commit()

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username or user.first_name)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Updates", url="https://t.me/WorkGlows"),
            InlineKeyboardButton("Support", url="https://t.me/TheCryptoElders")
        ],
        [
            InlineKeyboardButton("Add Me To Your Group", url=f"https://t.me/quizydudebot?startgroup=true")
        ]
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
        allows_multiple_answers=False
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
async def xquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'xquiz')

async def hquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'hquiz')

async def fquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'fquiz')

async def lolquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'lolquiz')

async def cquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'cquiz')

async def squiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'squiz')

async def aquiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_quiz(update, context, 'aquiz')

async def receive_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user_id = answer.user.id
    selected = answer.option_ids[0]
    
    poll_id = answer.poll_id
    correct_option_id = context.bot_data.get(poll_id, {}).get("correct_option_id")

    ensure_user(user_id, answer.user.username or answer.user.first_name)
    
    if selected == correct_option_id:
        update_score(user_id, correct=True)
    else:
        update_score(user_id, correct=False)

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    cursor.execute("SELECT * FROM users ORDER BY wins DESC, losses ASC")
    top_users = cursor.fetchall()

    if not top_users:
        await update.message.reply_text("No players yet!")
        return

    text = "<b>🏆 Quizy Dude Leaderboard 🏆</b>\n\n"
    for i, (uid, username, wins, losses) in enumerate(top_users, start=1):
        try:
            user = await context.bot.get_chat(uid)
            mention = f"{user.mention_html()}"  # Explicitly using user.mention_html()
        except Exception:
            mention = f"<i>{username or 'Unknown'}</i>"

        if i == 1:
            rank_icon = "🥇"
        elif i == 2:
            rank_icon = "🥈"
        elif i == 3:
            rank_icon = "🥉"
        else:
            rank_icon = f"{i}"

        text += f"{rank_icon} {mention} — W: {wins} & L: {losses}\n"

    await update.message.reply_html(text)

# --- MAIN ---
def main():
    TOKEN = os.environ.get("BOT_TOKEN")
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
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

    # Set commands menu
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
    async def set_commands(application):
        await application.bot.set_my_commands(commands)
    
    app.post_init = set_commands

    app.run_polling()

if __name__ == '__main__':
    main()
