# Telegram Quiz Bot
# This bot allows users to select a quiz category and difficulty, then play a 10-question multiple-choice quiz.
# Securely loads bot token from environment variables using python-dotenv.

import html
import random
import os
import logging
from dotenv import load_dotenv

import aiohttp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, MenuButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

# Load bot token securely from .env file
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise RuntimeError("Error: BOT_TOKEN environment variable not set. Please set it before running the bot.")

# Conversation states for ConversationHandler
SELECTING_CATEGORY, SELECTING_DIFFICULTY, QUIZ = range(3)

# In-memory storage of user quiz data keyed by user_id
user_data_store = {}

# Predefined quiz categories with OpenTDB IDs
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


async def fetch_questions_async(category_id: int, difficulty: str):
    """
    Asynchronously fetch 10 quiz questions from the Open Trivia Database API.
    Returns a list of tuples: (question, correct_answer, options).
    Uses aiohttp for non-blocking HTTP requests.
    """
    url = f"https://opentdb.com/api.php?amount=10&category={category_id}&difficulty={difficulty}&type=multiple"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as e:
            logging.error(f"Failed to fetch questions: {e}")
            return []

    questions = []
    for item in data.get('results', []):
        question = html.unescape(item['question'])
        correct = html.unescape(item['correct_answer'])
        options = [html.unescape(ans) for ans in item['incorrect_answers']]
        options.append(correct)
        random.shuffle(options)  # Shuffle answer options
        questions.append((question, correct, options))
    return questions


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Entry point for /start command or new quiz start.
    Sends welcome message with a "Start Quiz" button.
    """
    # Clear any ongoing quiz data for this user to reset quiz
    user_data_store.pop(update.effective_user.id, None)

    welcome_buttons = [[InlineKeyboardButton(text="🎮 Start Quiz!", callback_data="start_quiz")]]
    welcome_text = (
        "🎯 Welcome to the Quiz Game Bot!\n\n"
        "Test your knowledge across various categories.\n"
        "Press the button below to start your quiz adventure!"
    )
    if update.message:
        await update.message.reply_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(welcome_buttons)
        )
    elif update.callback_query:
        await update.callback_query.message.edit_text(
            welcome_text,
            reply_markup=InlineKeyboardMarkup(welcome_buttons)
        )
    return SELECTING_CATEGORY


async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays category options to the user after pressing "Start Quiz".
    """
    query = update.callback_query
    buttons = [[InlineKeyboardButton(text=cat, callback_data=cat)] for cat in list(CATEGORIES.keys())[:10]]
    await query.answer()
    await query.edit_message_text(
        "🎯 Choose a category:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SELECTING_CATEGORY


async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Stores selected category and asks user to choose difficulty.
    """
    query = update.callback_query
    category_name = query.data

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


async def difficulty_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    When difficulty is selected:
    - Fetch quiz questions asynchronously.
    - Store quiz state for the user.
    - Send the first question.
    """
    query = update.callback_query
    difficulty = query.data
    user_id = query.from_user.id

    category_id = context.user_data.get('category_id')
    if not category_id:
        await query.answer("Category not set. Please restart the quiz.")
        return ConversationHandler.END

    # Show typing indicator while fetching questions
    await query.message.chat.send_action(action="typing")

    questions = await fetch_questions_async(category_id, difficulty)
    if not questions:
        await query.answer("Failed to fetch questions. Please try again later.")
        return ConversationHandler.END

    # Initialize user quiz progress
    user_data_store[user_id] = {
        'questions': questions,
        'score': 0,
        'index': 0
    }

    await query.answer()
    await send_question(update, context, user_id)
    return QUIZ


async def send_question(update, context, user_id):
    """
    Sends a quiz question with multiple choice answers as inline buttons.
    Uses short callback_data keys and maps them to actual answers.
    """
    data = user_data_store[user_id]
    index = data['index']
    question, correct, options = data['questions'][index]

    callback_map = {}
    buttons = []
    for i, option_text in enumerate(options):
        callback_data = f"opt{i}"
        callback_map[callback_data] = option_text
        buttons.append([InlineKeyboardButton(text=option_text, callback_data=callback_data)])

    # Save callback_map for answer validation
    user_data_store[user_id]['callback_map'] = callback_map

    markup = InlineKeyboardMarkup(buttons)

    # Edit the existing message with the new question and answer buttons
    await update.callback_query.edit_message_text(
        text=f"❓ Question {index + 1}:\n{question}",
        reply_markup=markup
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles user's answer selection:
    - Checks correctness.
    - Updates score.
    - Moves to next question or finishes quiz.
    """
    query = update.callback_query
    user_id = query.from_user.id
    selected_callback = query.data
    data = user_data_store[user_id]

    callback_map = data.get('callback_map', {})
    answer = callback_map.get(selected_callback)
    if answer is None:
        # Invalid or expired selection
        await query.answer("Invalid selection, please try again.", show_alert=True)
        return QUIZ

    question, correct, _ = data['questions'][data['index']]

    if answer == correct:
        data['score'] += 1
        feedback = "✅ Correct!"
    else:
        feedback = f"❌ Wrong! Correct answer: {correct}"

    data['index'] += 1
    await query.answer()
    await query.edit_message_text(text=feedback)

    # If more questions remain, send next question
    if data['index'] < len(data['questions']):
        await send_question(update, context, user_id)
        return QUIZ
    else:
        # Quiz finished, show final score and options
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


async def play_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles user decision to replay or exit after quiz completion.
    """
    query = update.callback_query
    if query.data == "play_again":
        # Clear previous quiz data to start fresh
        user_data_store.pop(query.from_user.id, None)
        return await start(update, context)
    else:
        await query.message.reply_text("Thanks for playing! 👋")
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles cancellation of the quiz by user.
    """
    await update.message.reply_text("Quiz cancelled.")
    user_data_store.pop(update.effective_user.id, None)
    return ConversationHandler.END


# Conversation handler with states and callback patterns
conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('start', start),
        MessageHandler(filters.TEXT & ~filters.COMMAND, start)
    ],
    states={
        SELECTING_CATEGORY: [
            CallbackQueryHandler(show_categories, pattern="^start_quiz$"),
            CallbackQueryHandler(category_selected, pattern="^(?!start_quiz|play_again|exit).*$"),
            CallbackQueryHandler(play_again, pattern="^(play_again|exit)$")
        ],
        SELECTING_DIFFICULTY: [CallbackQueryHandler(difficulty_selected)],
        QUIZ: [CallbackQueryHandler(handle_answer)],
    },
    fallbacks=[
        CommandHandler('cancel', cancel),
        MessageHandler(filters.TEXT & ~filters.COMMAND, start)
    ],
    per_message=False
)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    async def setup_commands(app):
        # Set Telegram bot command menu for better UX
        await app.bot.set_my_commands([
            BotCommand("start", "Start the quiz game! 🎮"),
        ])
        await app.bot.set_chat_menu_button(
            menu_button=MenuButton(type=MenuButton.COMMANDS)
        )

    # Create application and add handler
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(setup_commands).build()
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()
# Note: The bot will run indefinitely until stopped manually.