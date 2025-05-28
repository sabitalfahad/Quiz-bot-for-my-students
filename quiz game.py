# This bot allows users to choose a category and difficulty, then play a 10-question quiz.
# I learned to use environment variables to hide my bot token when uploading to GitHub.
from dotenv import load_dotenv
import requests
import html
import random
import os  # I use this to get the token securely from environment variables
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)

# Instead of putting my token directly, I store it in an environment variable.
# I created a file named .env with BOT_TOKEN=your_real_token and used python-dotenv to load it.
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')  # This keeps my token secret 💡

# These numbers help track what stage of the conversation we're in.
SELECTING_CATEGORY, SELECTING_DIFFICULTY, QUIZ = range(3)

# I use this to store users' progress through the quiz.
user_data_store = {}

# The quiz categories and their OpenTDB category IDs
CATEGORIES = {
    "General Knowledge": 9,
    "Books": 10,
    "Film": 11,
    "Music": 12,
    "Science & Nature": 17,
    "Computers": 18,
    "Mathematics": 19,
    "Mythology": 20,
    "Sports": 21,
    "Geography": 22,
    "History": 23,
    "Politics": 24,
    "Art": 25
}

# I fetch 10 quiz questions using the OpenTDB API
def fetch_questions(category_id, difficulty):
    url = f"https://opentdb.com/api.php?amount=10&category={category_id}&difficulty={difficulty}&type=multiple"
    data = requests.get(url).json()
    questions = []
    for item in data['results']:
        question = html.unescape(item['question'])
        correct = html.unescape(item['correct_answer'])
        options = [html.unescape(ans) for ans in item['incorrect_answers']]
        options.append(correct)
        random.shuffle(options)  # I mix up the options randomly
        questions.append((question, correct, options))
    return questions

# When the user starts the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[InlineKeyboardButton(text=cat, callback_data=cat)] for cat in list(CATEGORIES.keys())[:10]]
    if update.message:
        await update.message.reply_text("🎯 Choose a category:", reply_markup=InlineKeyboardMarkup(buttons))
    return SELECTING_CATEGORY

# When a category is selected
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    category_name = query.data
    user_id = query.from_user.id

    context.user_data['category_name'] = category_name
    context.user_data['category_id'] = CATEGORIES[category_name]

    buttons = [
        [InlineKeyboardButton("Easy", callback_data="easy")],
        [InlineKeyboardButton("Medium", callback_data="medium")],
        [InlineKeyboardButton("Hard", callback_data="hard")]
    ]
    await query.answer()
    await query.edit_message_text(
        text=f"📚 You chose *{category_name}*\nNow choose a difficulty:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )
    return SELECTING_DIFFICULTY

# When a difficulty is selected
async def difficulty_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    difficulty = query.data
    user_id = query.from_user.id

    category_id = context.user_data['category_id']
    questions = fetch_questions(category_id, difficulty)

    user_data_store[user_id] = {
        'questions': questions,
        'score': 0,
        'index': 0
    }

    await query.answer()
    await send_question(update, context, user_id)
    return QUIZ

# This sends a question to the user
async def send_question(update, context, user_id):
    data = user_data_store[user_id]
    index = data['index']
    question, _, options = data['questions'][index]

    buttons = [[InlineKeyboardButton(text=opt, callback_data=opt)] for opt in options]
    markup = InlineKeyboardMarkup(buttons)

    await update.callback_query.message.reply_text(
        text=f"❓ Question {index + 1}:\n{question}",
        reply_markup=markup
    )

# Handles user answers
async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answer = query.data
    data = user_data_store[user_id]

    question, correct, _ = data['questions'][data['index']]

    if answer == correct:
        data['score'] += 1
        feedback = "✅ Correct!"
    else:
        feedback = f"❌ Wrong! Correct answer: {correct}"

    data['index'] += 1
    await query.answer()
    await query.edit_message_text(text=feedback)

    if data['index'] < len(data['questions']):
        await send_question(update, context, user_id)
        return QUIZ
    else:
        score = data['score']
        total = len(data['questions'])
        buttons = [
            [InlineKeyboardButton("🔁 Play Again", callback_data="play_again")],
            [InlineKeyboardButton("❌ Exit", callback_data="exit")]
        ]
        await query.message.reply_text(
            f"🎉 Quiz Finished!\nYou scored {score}/{total}.\n\nWant to play again?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return SELECTING_CATEGORY

# User selects play again or exit
async def play_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "play_again":
        await start(update, context)
        return SELECTING_CATEGORY
    else:
        await query.message.reply_text("Thanks for playing! 👋")
        return ConversationHandler.END

# In case user cancels
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Quiz cancelled.")
    return ConversationHandler.END

# This is where the bot starts running
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECTING_CATEGORY: [
                CallbackQueryHandler(category_selected, pattern="^(?!play_again|exit).*$"),
                CallbackQueryHandler(play_again, pattern="^(play_again|exit)$")
            ],
            SELECTING_DIFFICULTY: [CallbackQueryHandler(difficulty_selected)],
            QUIZ: [CallbackQueryHandler(handle_answer)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv_handler)
    print("🤖 Bot is running...")
    app.run_polling()