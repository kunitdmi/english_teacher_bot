# English Teacher Telegram Bot

Telegram-бот — интерактивный учитель американского английского. Работает как обёртка над [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code), установленным на VPS.

## Что умеет

**Главная фича:** на каждое сообщение бот сначала показывает, как это сказать на естественном американском английском, а затем отвечает на вопрос.

### 6 режимов обучения

| Режим | Описание |
|---|---|
| **conversation** | Свободный разговор — обучение через диалог |
| **grammar** | Грамматика — разбор правил с примерами |
| **vocab** | Словарный запас — слова по темам (10 тем) |
| **idioms** | Американские идиомы, сленг, phrasal verbs |
| **roleplay** | Ролевые сценарии (кофейня, собеседование, врач...) |
| **correction** | Пишите на английском — бот только исправляет ошибки |

### Команды

| Команда | Назначение |
|---|---|
| `/start` | Приветствие и инструкция |
| `/mode` | Выбрать режим обучения (inline-кнопки) |
| `/level` | Уровень: beginner / intermediate / advanced |
| `/roleplay` | Случайный ролевой сценарий |
| `/vocab` | Выбрать тему для изучения слов |
| `/challenge` | Задание дня |
| `/phrase` | Случайная полезная фраза |
| `/quiz` | Мини-тест на 3 вопроса |
| `/translate <текст>` | Только перевод с вариантами |
| `/mistakes` | Показать частые ошибки |
| `/id` | Узнать свой chat_id |

### Структура ответа

Каждый ответ бота содержит:

1. **Перевод запроса** — 2-3 варианта на естественном английском (лучший отмечен звездой)
2. **Основной ответ** — ответ на вопрос или продолжение диалога
3. **Мини-урок** — одна подсказка (фраза, ошибка, слово, произношение или культурная заметка)
4. **Практическое задание** — вопрос или упражнение для закрепления

## Оптимизация токенов

- **Сессии** (`--resume`) — системный промпт отправляется один раз, дальше Claude помнит контекст
- **Haiku для лёгких задач** — `/translate`, `/phrase`, `/quiz`, `/challenge`, `/vocab` используют дешёвую модель
- **Автосброс сессии** — после N сообщений (по умолчанию 40) сессия сбрасывается, чтобы контекст не разрастался

## Требования

- Ubuntu / Debian VPS
- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) установлен и авторизован
- Telegram Bot Token (от [@BotFather](https://t.me/BotFather))

## Установка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/YOUR_USER/claude-tg-bot.git
cd claude-tg-bot
```

### 2. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install python-telegram-bot
```

### 3. Настроить переменные окружения

```bash
cp english_teacher_bot.env.example english_teacher_bot.env
nano english_teacher_bot.env
```

Заполните:

| Переменная | Описание | Обязательно |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather | да |
| `ALLOWED_CHAT_IDS` | Ваш chat_id (через запятую, если несколько) | нет (120) |
| `CLAUDE_TIMEOUT` | Таймаут ответа в секундах | нет (120) |
| `SESSION_MSG_LIMIT` | Сообщений до сброса сессии | нет (40) |
| `LIGHT_MODEL` | Модель для лёгких задач | нет (haiku) |
| `PATH` | Путь, включающий директорию claude CLI | да |

Защитите файл:

```bash
chmod 600 english_teacher_bot.env
```

### 4. Узнать свой chat_id

Напишите боту `/start`, затем используйте команду `/id` или откройте:

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

### 5. Тестовый запуск

```bash
set -a; source english_teacher_bot.env; set +a
python english_teacher_bot.py
```

### 6. Автозапуск через systemd

```bash
sudo tee /etc/systemd/system/english-teacher-bot.service << 'EOF'
[Unit]
Description=English Teacher Telegram Bot
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/claude-tg-bot
EnvironmentFile=/home/admin/claude-tg-bot/english_teacher_bot.env
ExecStart=/home/admin/claude-tg-bot/venv/bin/python english_teacher_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now english-teacher-bot
```

### Управление сервисом

```bash
# Статус
sudo systemctl status english-teacher-bot

# Логи
sudo journalctl -u english-teacher-bot -f

# Перезапуск
sudo systemctl restart english-teacher-bot

# Остановка
sudo systemctl stop english-teacher-bot
```

### Запись на github

```bash
cd ~/claude-tg-bot

# Инициализация репо (уже есть .gitignore)
git init
git add english_teacher_bot.py english_teacher_bot.env.example .gitignore README.md
git commit -m "Initial commit: English Teacher Telegram Bot"

# Создайте репо на github.com, затем:
git remote add origin git@github.com:YOUR_USER/claude-tg-bot.git
git push -u origin main
```

Или установите gh и создайте репо одной командой:

```bash
# Установка gh
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list
sudo apt update && sudo apt install gh

# Авторизация и создание
gh auth login
gh repo create claude-tg-bot --public --source=. --push
```

## Структура проекта

```
claude-tg-bot/
├── english_teacher_bot.py          # основной код бота
├── english_teacher_bot.env.example # шаблон переменных окружения
├── english_teacher_bot.env         # ваши настройки (не в git)
├── .gitignore
├── README.md
└── venv/                           # виртуальное окружение (не в git)
```

## Безопасность

- `.env` файл с токенами **не попадает в git** (прописан в `.gitignore`)
- Доступ ограничен по `ALLOWED_CHAT_IDS` — посторонние получат "Access denied"
- Файл `.env` защищён правами `chmod 600`

## Пример диалога

**Пользователь:** Как спросить дорогу в Нью-Йорке?

**Бот:**

> **How to say this in English:**
> 1. ⭐ How do I ask for directions in New York?
> 2. What's the best way to ask for directions in NYC?
>
> Here are the key phrases you'll need...
> - "Excuse me, how do I get to...?"
> - "Do you know where ... is?"
>
> ⚠️ **Common mistake:** Russians often say "How to go to...?" — Americans say "How do I get to...?"
>
> **Practice:** How would you ask a stranger how to get to Times Square?
