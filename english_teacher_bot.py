#!/usr/bin/env python3
"""
Telegram-бот — интерактивный учитель американского английского.
Использует Claude Code CLI для генерации ответов.
"""

import os
import asyncio
import json
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ── Настройки ──────────────────────────────────────────────
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_IDS = {int(x) for x in os.environ["ALLOWED_CHAT_IDS"].split(",")}
TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "120"))

# Лимит сообщений в сессии — после этого сессия сбрасывается
SESSION_MSG_LIMIT = int(os.environ.get("SESSION_MSG_LIMIT", "40"))

# Модель для лёгких задач (перевод, фраза дня, quiz)
LIGHT_MODEL = os.environ.get("LIGHT_MODEL", "haiku")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Хранилище состояния пользователей ──────────────────────
user_state: dict[int, dict] = {}
# Структура:
# {
#     chat_id: {
#         "level": "beginner" | "intermediate" | "advanced",
#         "mode": "conversation" | "grammar" | "vocab" | "idioms" | "roleplay" | "correction",
#         "session_id": str | None,
#         "vocab_list": [...],       # слова для повторения
#         "mistakes": [...],         # частые ошибки
#         "streak": int,             # дней подряд
#     }
# }


def get_state(chat_id: int) -> dict:
    if chat_id not in user_state:
        user_state[chat_id] = {
            "level": "intermediate",
            "mode": "conversation",
            "session_id": None,
            "vocab_list": [],
            "mistakes": [],
            "streak": 0,
        }
    return user_state[chat_id]


def is_allowed(update: Update) -> bool:
    return update.effective_chat.id in ALLOWED_IDS


# ── Системный промпт для Claude ───────────────────────────

SYSTEM_PROMPT = """You are an interactive American English teacher in a Telegram chat.
The student communicates in Russian or broken English. Your job:

LEVEL: {level}
MODE: {mode}

## ALWAYS follow this response structure:

### 1. Translation Block (ALWAYS FIRST)
Start EVERY response with a section:
"🇺🇸 **How to say this in English:**"
Provide 2-3 natural American English ways to express what the student just wrote.
Mark the most natural/common one with ⭐.
If the student wrote in English, correct their version and show the natural way.

### 2. Main Response
Answer the student's actual question or continue the conversation — IN ENGLISH with Russian translation in parentheses for key phrases if the student is beginner/intermediate.

### 3. Learning Nugget (pick ONE per message, rotate between these)
Choose one mini-lesson relevant to what just came up:
- 🗣 **Natural phrase:** a common American expression related to the topic
- ⚠️ **Common mistake:** a typical Russian-speaker error relevant to this context
- 🔤 **Word of the moment:** a useful vocabulary word from the conversation
- 👂 **Pronunciation tip:** how Americans actually say something (with phonetic hint)
- 🇺🇸 **Culture note:** relevant American cultural context

### 4. Practice Prompt
End with a short practice task or question to keep the student engaged.
Vary these: sometimes a translation challenge, sometimes a fill-in-the-blank,
sometimes "how would you say X?", sometimes a roleplay prompt.

## Mode-specific behavior:

- **conversation**: Natural chat, teach through dialogue
- **grammar**: Focus on grammar explanations with examples
- **vocab**: Build vocabulary around themes, use spaced repetition
- **idioms**: Teach American idioms, slang, phrasal verbs
- **roleplay**: Act out scenarios (ordering coffee, job interview, small talk, etc.)
- **correction**: Student writes in English, you ONLY correct and explain errors

## Rules:
- Use American English (not British). "apartment" not "flat", "elevator" not "lift", etc.
- Be encouraging but honest about errors
- Use casual, friendly tone — like a cool American friend teaching you
- Keep responses concise for Telegram (not walls of text)
- If the student writes in English, praise the attempt before correcting
- Adapt complexity to the student's level
"""

MODE_DESCRIPTIONS = {
    "conversation": "💬 Свободный разговор — учимся через общение",
    "grammar": "📐 Грамматика — разбираем правила с примерами",
    "vocab": "📚 Словарный запас — учим слова по темам",
    "idioms": "🗽 Идиомы и сленг — говорим как американцы",
    "roleplay": "🎭 Ролевые сценарии — практика реальных ситуаций",
    "correction": "✏️ Режим коррекции — пишите на английском, я исправлю",
}

ROLEPLAY_SCENARIOS = [
    "ordering at Starbucks",
    "job interview for a tech position",
    "small talk with a neighbor",
    "calling to make a doctor's appointment",
    "checking in at a hotel",
    "returning an item at a store",
    "meeting someone at a party",
    "asking for directions in NYC",
    "negotiating a salary",
    "complaining about a meal at a restaurant",
]

VOCAB_THEMES = [
    "tech & startups",
    "food & restaurants",
    "travel & airports",
    "work & office",
    "health & fitness",
    "money & banking",
    "social media & internet",
    "weather & small talk",
    "shopping & retail",
    "emotions & feelings",
]

DAILY_CHALLENGES = [
    "Translate: 'Я не уверен, стоит ли мне менять работу'",
    "What's the difference: 'I used to' vs 'I'm used to'?",
    "Use 'get' in 5 different meanings",
    "Translate naturally: 'У меня руки не дошли'",
    "Explain the difference: 'say', 'tell', 'speak', 'talk'",
    "What does 'I could use a coffee' mean?",
    "Translate: 'Давай на ты' (hint: there's no direct translation!)",
    "Use these phrasal verbs in sentences: 'figure out', 'come up with', 'look into'",
    "What's wrong: 'I feel myself good today'?",
    "How do Americans answer the phone? (not 'Allo!')",
]


# ── Вызов Claude CLI ──────────────────────────────────────

async def init_session(state: dict, model: str | None = None) -> str | None:
    """Создать новую сессию с системным промптом. Возвращает session_id."""
    system = SYSTEM_PROMPT.format(level=state["level"], mode=state["mode"])
    init_prompt = (
        f"{system}\n\n---\n"
        "Respond with just 'Ready!' to confirm you understood the instructions."
    )
    cmd = ["claude", "-p", init_prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        data = json.loads(stdout.decode())
        return data.get("session_id")
    except Exception as e:
        log.error("Failed to init session: %s", e)
        return None


async def ask_claude(prompt: str, state: dict, model: str | None = None) -> str:
    """Отправить запрос в Claude Code CLI, переиспользуя сессию.

    Args:
        prompt: текст запроса
        state: состояние пользователя
        model: модель ("haiku" для лёгких задач, None для дефолтной)
    """

    # Автосброс сессии при достижении лимита сообщений
    msg_count = state.get("msg_count", 0)
    if msg_count >= SESSION_MSG_LIMIT:
        log.info("Session msg limit (%d) reached, resetting", SESSION_MSG_LIMIT)
        state["session_id"] = None
        state["msg_count"] = 0

    # Если нет сессии — создаём (системный промпт отправится один раз)
    if not state.get("session_id"):
        session_id = await init_session(state, model=model)
        if session_id:
            state["session_id"] = session_id
            state["msg_count"] = 0
            log.info("New session created: %s (model=%s)", session_id, model or "default")

    # Собираем команду
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    if state.get("session_id"):
        cmd += ["--resume", state["session_id"]]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=TIMEOUT
        )
        raw = stdout.decode().strip()

        # Парсим JSON-ответ
        try:
            data = json.loads(raw)
            # Обновляем session_id (на случай если создался новый)
            if data.get("session_id"):
                state["session_id"] = data["session_id"]
            reply = data.get("result", raw)
        except json.JSONDecodeError:
            reply = raw

        if not reply:
            reply = stderr.decode().strip() or "(пустой ответ от Claude)"

        # Увеличиваем счётчик сообщений в сессии
        state["msg_count"] = state.get("msg_count", 0) + 1

        return reply

    except asyncio.TimeoutError:
        return "⏱ Таймаут. Попробуйте задать вопрос короче."
    except FileNotFoundError:
        return "Claude CLI не найден в PATH."
    except Exception as e:
        return f"Ошибка: {e}"


# ── Команды бота ───────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("Access denied.")
        return

    state = get_state(update.effective_chat.id)

    await update.message.reply_text(
        "👋 **Hi there! Привет!**\n\n"
        "Я твой интерактивный учитель американского английского.\n\n"
        "**Как это работает:**\n"
        "1. Пиши мне на русском или английском\n"
        "2. Я покажу, как это сказать на natural American English\n"
        "3. Отвечу на твой вопрос\n"
        "4. Дам полезную мини-подсказку\n"
        "5. Предложу практическое задание\n\n"
        "**Команды:**\n"
        "/mode — выбрать режим обучения\n"
        "/level — установить уровень\n"
        "/roleplay — начать ролевой сценарий\n"
        "/vocab — учить слова по теме\n"
        "/challenge — задание дня\n"
        "/phrase — случайная полезная фраза\n"
        "/mistakes — мои частые ошибки\n"
        "/help — все команды\n\n"
        "Просто напиши что-нибудь, и мы начнём! 🚀",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "📖 **Все команды:**\n\n"
        "/mode — режим обучения (разговор, грамматика, идиомы...)\n"
        "/level — уровень (beginner / intermediate / advanced)\n"
        "/roleplay — случайный ролевой сценарий\n"
        "/vocab — выбрать тему для слов\n"
        "/challenge — задание дня\n"
        "/phrase — случайная полезная фраза\n"
        "/quiz — мини-тест\n"
        "/mistakes — показать мои частые ошибки\n"
        "/translate <текст> — только перевод\n"
        "/id — ваш chat_id\n\n"
        "Или просто пишите — я учитель, а не меню 😄",
        parse_mode="Markdown",
    )


async def cmd_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    keyboard = [
        [InlineKeyboardButton(f"💬 Разговор", callback_data="mode_conversation")],
        [InlineKeyboardButton(f"📐 Грамматика", callback_data="mode_grammar")],
        [InlineKeyboardButton(f"📚 Словарный запас", callback_data="mode_vocab")],
        [InlineKeyboardButton(f"🗽 Идиомы и сленг", callback_data="mode_idioms")],
        [InlineKeyboardButton(f"🎭 Ролевые сценарии", callback_data="mode_roleplay")],
        [InlineKeyboardButton(f"✏️ Коррекция", callback_data="mode_correction")],
    ]
    await update.message.reply_text(
        "Выберите режим обучения:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_level(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    keyboard = [
        [InlineKeyboardButton("🟢 Beginner (начинающий)", callback_data="level_beginner")],
        [InlineKeyboardButton("🟡 Intermediate (средний)", callback_data="level_intermediate")],
        [InlineKeyboardButton("🔴 Advanced (продвинутый)", callback_data="level_advanced")],
    ]
    await update.message.reply_text(
        "Выберите ваш уровень:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_roleplay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    state = get_state(update.effective_chat.id)
    state["mode"] = "roleplay"
    scenario = random.choice(ROLEPLAY_SCENARIOS)

    await update.effective_chat.send_action("typing")
    reply = await ask_claude(
        f"Start a roleplay scenario: '{scenario}'. "
        f"Set the scene briefly, then play your character and let the student respond. "
        f"Give the student a hint about what they might say first.",
        state,
    )
    await send_long_message(update, reply)


async def cmd_vocab(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    keyboard = [
        [InlineKeyboardButton(theme, callback_data=f"vocab_{i}")]
        for i, theme in enumerate(VOCAB_THEMES)
    ]
    await update.message.reply_text(
        "📚 Выберите тему для изучения слов:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_challenge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    state = get_state(update.effective_chat.id)
    challenge = random.choice(DAILY_CHALLENGES)

    await update.effective_chat.send_action("typing")
    reply = await ask_claude(
        f"Give the student this challenge and help them work through it step by step: '{challenge}'",
        state,
        model=LIGHT_MODEL,
    )
    await send_long_message(update, reply)


async def cmd_phrase(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    state = get_state(update.effective_chat.id)
    await update.effective_chat.send_action("typing")
    reply = await ask_claude(
        "Teach the student ONE useful American English phrase/expression "
        "that Russian speakers often don't know. Include: the phrase, meaning, "
        "2 example sentences, a common situation where it's used, "
        "and how a Russian speaker might incorrectly say the same thing.",
        state,
        model=LIGHT_MODEL,
    )
    await send_long_message(update, reply)


async def cmd_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    state = get_state(update.effective_chat.id)
    await update.effective_chat.send_action("typing")
    reply = await ask_claude(
        "Create a quick 3-question mini-quiz appropriate for the student's level. "
        "Mix question types: multiple choice, fill-in-the-blank, and translation. "
        "Focus on common American English patterns that Russian speakers struggle with. "
        "Number the questions and tell the student to reply with their answers.",
        state,
        model=LIGHT_MODEL,
    )
    await send_long_message(update, reply)


async def cmd_mistakes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    state = get_state(update.effective_chat.id)
    if not state["mistakes"]:
        await update.message.reply_text(
            "Пока ошибок не записано. Пишите больше на английском в режиме /mode ✏️ Коррекция!"
        )
        return

    mistakes_text = "\n".join(f"• {m}" for m in state["mistakes"][-10:])
    await update.message.reply_text(
        f"📝 **Ваши частые ошибки (последние 10):**\n\n{mistakes_text}\n\n"
        "Попробуйте написать предложения, используя правильные варианты!",
        parse_mode="Markdown",
    )


async def cmd_translate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return

    text = update.message.text.replace("/translate", "", 1).strip()
    if not text:
        await update.message.reply_text("Использование: /translate <текст для перевода>")
        return

    state = get_state(update.effective_chat.id)
    await update.effective_chat.send_action("typing")
    reply = await ask_claude(
        f"Translate this to natural American English. Give 2-3 variants from most casual "
        f"to most formal. Briefly explain the nuance of each:\n\n{text}",
        state,
        model=LIGHT_MODEL,
    )
    await send_long_message(update, reply)


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш chat_id: `{update.effective_chat.id}`",
                                     parse_mode="Markdown")


# ── Обработка inline-кнопок ───────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    if chat_id not in ALLOWED_IDS:
        return

    state = get_state(chat_id)
    data = query.data

    if data.startswith("mode_"):
        mode = data.replace("mode_", "")
        state["mode"] = mode
        state["session_id"] = None  # сброс сессии — новый промпт
        desc = MODE_DESCRIPTIONS.get(mode, mode)
        await query.edit_message_text(f"Режим изменён: {desc}\n\nПишите — начнём!")

    elif data.startswith("level_"):
        level = data.replace("level_", "")
        state["level"] = level
        state["session_id"] = None  # сброс сессии — новый промпт
        labels = {"beginner": "🟢 Beginner", "intermediate": "🟡 Intermediate", "advanced": "🔴 Advanced"}
        await query.edit_message_text(f"Уровень установлен: {labels.get(level, level)}")

    elif data.startswith("vocab_"):
        idx = int(data.replace("vocab_", ""))
        theme = VOCAB_THEMES[idx]
        state["mode"] = "vocab"
        await query.edit_message_text(f"📚 Тема: {theme}\nГенерирую слова...")
        reply = await ask_claude(
            f"Teach 7-10 essential American English words/phrases on the topic '{theme}'. "
            f"For each word: the word, transcription, Russian translation, "
            f"one natural example sentence, and one common mistake Russians make with it. "
            f"Then give a practice exercise using these words.",
            state,
            model=LIGHT_MODEL,
        )
        for i in range(0, len(reply), 4096):
            await query.message.reply_text(reply[i : i + 4096])


# ── Основной обработчик сообщений ─────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        log.warning("Denied chat_id=%s", update.effective_chat.id)
        await update.message.reply_text("Access denied.")
        return

    prompt = update.message.text
    if not prompt:
        return

    state = get_state(update.effective_chat.id)

    log.info("chat_id=%s mode=%s: %s", update.effective_chat.id, state["mode"], prompt[:80])

    await update.effective_chat.send_action("typing")

    reply = await ask_claude(prompt, state)

    await send_long_message(update, reply)


# ── Утилита для длинных сообщений ─────────────────────────

async def send_long_message(update: Update, text: str):
    """Отправка длинного сообщения частями по 4096 символов."""
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i : i + 4096])


# ── Запуск ─────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("level", cmd_level))
    app.add_handler(CommandHandler("roleplay", cmd_roleplay))
    app.add_handler(CommandHandler("vocab", cmd_vocab))
    app.add_handler(CommandHandler("challenge", cmd_challenge))
    app.add_handler(CommandHandler("phrase", cmd_phrase))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CommandHandler("mistakes", cmd_mistakes))
    app.add_handler(CommandHandler("translate", cmd_translate))
    app.add_handler(CommandHandler("id", cmd_id))

    # Inline-кнопки
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("English Teacher Bot started. Allowed IDs: %s", ALLOWED_IDS)
    app.run_polling()


if __name__ == "__main__":
    main()
