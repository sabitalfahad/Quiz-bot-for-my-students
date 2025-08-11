# Telegram Quiz Bot
# This bot allows users to select a quiz category and difficulty, then play a 10-question multiple-choice quiz.
# Securely loads bot token from environment variables using python-dotenv.

import html
import random
import os
import logging
import asyncio
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
        random.shuffle(options)
        questions.append((question, correct, options))
    return questions


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    buttons = [[InlineKeyboardButton(text=cat, callback_data=cat)] for cat in list(CATEGORIES.keys())[:10]]
    await query.answer()
    await query.edit_message_text(
        "🎯 Choose a category:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return SELECTING_CATEGORY


async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    difficulty = query.data
    user_id = query.from_user.id

    category_id = context.user_data.get('category_id')
    if not category_id:
        await query.answer("Category not set. Please restart the quiz.")
        return ConversationHandler.END

    await query.message.chat.send_action(action="typing")

    questions = await fetch_questions_async(category_id, difficulty)
    if not questions:
        await query.answer("Failed to fetch questions. Please try again later.")
        return ConversationHandler.END

    user_data_store[user_id] = {
        'questions': questions,
        'score': 0,
        'index': 0
    }

    await query.answer()
    # Delete the difficulty selection message
    try:
        await query.message.delete()
    except Exception as e:
        logging.warning(f"Failed to delete message: {e}")

    await send_question(update, context, user_id)
    return QUIZ


async def send_question(update, context, user_id):
    data = user_data_store[user_id]
    index = data['index']
    question, correct, options = data['questions'][index]

    callback_map = {}
    buttons = []
    for i, option_text in enumerate(options):
        callback_data = f"opt{i}"
        callback_map[callback_data] = option_text
        buttons.append([InlineKeyboardButton(text=option_text, callback_data=callback_data)])

    user_data_store[user_id]['callback_map'] = callback_map

    markup = InlineKeyboardMarkup(buttons)

    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"❓ Question {index + 1}:\n{question}",
        reply_markup=markup
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    selected_callback = query.data
    data = user_data_store[user_id]

    callback_map = data.get('callback_map', {})
    answer = callback_map.get(selected_callback)
    if answer is None:
        await query.answer("Invalid selection, please try again.", show_alert=True)
        return QUIZ

    question, correct, options = data['questions'][data['index']]

    # Disable buttons on the original question message
    buttons_disabled = [
        [InlineKeyboardButton(text=opt, callback_data="disabled")] for opt in options
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons_disabled))

    feedback_lines = [f"❓ *Question:* {question}\n"]

    if answer == correct:
        data['score'] += 1
        feedback_lines.append(f"✅ Your answer: *{answer}* (Correct!)")
    else:
        feedback_lines.append(f"❌ Your answer: *{answer}* (Wrong!)")
        feedback_lines.append(f"✅ Correct answer: *{correct}*")

    feedback_text = "\n".join(feedback_lines)

    # Send feedback as a new message so it stays visible
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=feedback_text,
        parse_mode="Markdown"
    )

    # Delete the original question message (optional, for cleaner chat)
    try:
        await query.message.delete()
    except Exception as e:
        logging.warning(f"Failed to delete message: {e}")

    data['index'] += 1

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
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎉 Quiz Finished!\nYou scored {score}/{total}.\n\nWant to play again?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return SELECTING_CATEGORY


async def play_again(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "play_again":
        user_data_store.pop(query.from_user.id, None)
        return await start(update, context)
    else:
        await query.message.reply_text("Thanks for playing! 👋")
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Quiz cancelled.")
    user_data_store.pop(update.effective_user.id, None)
    return ConversationHandler.END


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
        await app.bot.set_my_commands([
            BotCommand("start", "Start the quiz game! 🎮"),
        ])
        await app.bot.set_chat_menu_button(
            menu_button=MenuButton(type=MenuButton.COMMANDS)
        )

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(setup_commands).build()
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()
