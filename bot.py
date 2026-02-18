import telebot
from telebot import types
import logging
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import functools
import time
import os
from flask import Flask, request
import threading

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Константы из переменных окружения (для безопасности)
BOT_TOKEN = os.getenv('BOT_TOKEN', '8467159055:AAHfaxhKryC3dXNOPAUYQrqzoRSk1jYbHc8')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '1399863475'))
PORT = int(os.getenv('PORT', 10000))  # Render автоматически дает порт

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)


@dataclass
class AuthorInfo:
    """Класс для хранения информации об авторе"""
    user_id: int
    first_name: str
    username: str
    revealed: bool = False


@dataclass
class MessageStore:
    """Хранилище сообщений"""
    authors: Dict[tuple, AuthorInfo] = field(default_factory=dict)
    reply_map: Dict[int, int] = field(default_factory=dict)

    def add_message(self, admin_msg_id: int, author: AuthorInfo) -> None:
        """Добавляет сообщение в хранилище"""
        key = (ADMIN_CHAT_ID, admin_msg_id)
        self.authors[key] = author
        self.reply_map[admin_msg_id] = author.user_id

    def get_author(self, admin_msg_id: int) -> Optional[AuthorInfo]:
        """Получает информацию об авторе"""
        return self.authors.get((ADMIN_CHAT_ID, admin_msg_id))

    def remove_message(self, admin_msg_id: int) -> None:
        """Удаляет сообщение из хранилища"""
        key = (ADMIN_CHAT_ID, admin_msg_id)
        self.authors.pop(key, None)
        self.reply_map.pop(admin_msg_id, None)


# Глобальное хранилище
store = MessageStore()


class MessageType(Enum):
    """Типы сообщений для удобной обработки"""
    TEXT = 'text'
    PHOTO = 'photo'
    VIDEO = 'video'
    VOICE = 'voice'
    AUDIO = 'audio'
    DOCUMENT = 'document'
    VIDEO_NOTE = 'video_note'
    STICKER = 'sticker'
    ANIMATION = 'animation'
    LOCATION = 'location'
    CONTACT = 'contact'


def create_keyboard(buttons: list, row_width: int = 2) -> types.InlineKeyboardMarkup:
    """Универсальная функция создания клавиатуры"""
    markup = types.InlineKeyboardMarkup(row_width=row_width)
    markup.add(*[types.InlineKeyboardButton(text, callback_data=data) for text, data in buttons])
    return markup


class Keyboards:
    """Класс для хранения всех клавиатур"""

    @staticmethod
    def main() -> types.InlineKeyboardMarkup:
        return create_keyboard([
            ("👁️ Узнать кто написал", "reveal_author"),
            ("📝 Ответить", "reply_to_author")
        ])

    @staticmethod
    def reply_only() -> types.InlineKeyboardMarkup:
        return create_keyboard([("📝 Ответить", "reply_to_author")], row_width=1)

    @staticmethod
    def cancel() -> types.InlineKeyboardMarkup:
        return create_keyboard([("❌ Отменить", "cancel_reply")], row_width=1)

    @staticmethod
    def admin_reply() -> types.InlineKeyboardMarkup:
        return create_keyboard([("ℹ️ Это ответ администратора", "admin_reply_info")], row_width=1)


def format_author_info(author: AuthorInfo) -> str:
    """Форматирует информацию об авторе"""
    return (f"\n\n━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Автор сообщения:**\n"
            f"🆔 **ID:** `{author.user_id}`\n"
            f"👤 **Имя:** {author.first_name}\n"
            f"📛 **Username:** @{author.username}\n"
            f"━━━━━━━━━━━━━━━━━━━")


class MessageSender:
    """Класс для отправки сообщений разных типов"""

    @staticmethod
    def send_admin(message: types.Message, reply_markup: types.InlineKeyboardMarkup) -> Optional[types.Message]:
        """Отправляет сообщение админу"""
        handlers = {
            MessageType.TEXT: lambda: bot.send_message(ADMIN_CHAT_ID, message.text, reply_markup=reply_markup),
            MessageType.PHOTO: lambda: bot.send_photo(ADMIN_CHAT_ID, message.photo[-1].file_id,
                                                      caption=message.caption or "", reply_markup=reply_markup),
            MessageType.VIDEO: lambda: bot.send_video(ADMIN_CHAT_ID, message.video.file_id,
                                                      caption=message.caption or "", reply_markup=reply_markup),
            MessageType.VOICE: lambda: bot.send_voice(ADMIN_CHAT_ID, message.voice.file_id, reply_markup=reply_markup),
            MessageType.AUDIO: lambda: bot.send_audio(ADMIN_CHAT_ID, message.audio.file_id,
                                                      title=getattr(message.audio, 'title', ''),
                                                      performer=getattr(message.audio, 'performer', ''),
                                                      reply_markup=reply_markup),
            MessageType.DOCUMENT: lambda: bot.send_document(ADMIN_CHAT_ID, message.document.file_id,
                                                            caption=message.caption or "", reply_markup=reply_markup),
            MessageType.VIDEO_NOTE: lambda: bot.send_video_note(ADMIN_CHAT_ID, message.video_note.file_id,
                                                                reply_markup=reply_markup),
            MessageType.STICKER: lambda: bot.send_sticker(ADMIN_CHAT_ID, message.sticker.file_id,
                                                          reply_markup=reply_markup),
            MessageType.ANIMATION: lambda: bot.send_animation(ADMIN_CHAT_ID, message.animation.file_id,
                                                              caption=message.caption or "", reply_markup=reply_markup),
            MessageType.LOCATION: lambda: bot.send_location(ADMIN_CHAT_ID, message.location.latitude,
                                                            message.location.longitude, reply_markup=reply_markup),
            MessageType.CONTACT: lambda: bot.send_contact(ADMIN_CHAT_ID, message.contact.phone_number,
                                                          message.contact.first_name, reply_markup=reply_markup)
        }

        for msg_type, handler in handlers.items():
            if getattr(message, msg_type.value, None):
                return handler()

        return bot.send_message(ADMIN_CHAT_ID, "📎 Анонимное сообщение", reply_markup=reply_markup)

    @staticmethod
    def send_to_user(message: types.Message, user_id: int) -> bool:
        """Отправляет сообщение пользователю"""
        try:
            reply_markup = Keyboards.admin_reply()

            handlers = {
                MessageType.TEXT: lambda: bot.send_message(user_id, f"📨 **Ответ:**\n\n{message.text}",
                                                           parse_mode='Markdown', reply_markup=reply_markup),
                MessageType.PHOTO: lambda: bot.send_photo(user_id, message.photo[-1].file_id,
                                                          caption=f"📨 **Ответ:**\n\n{message.caption or ''}",
                                                          parse_mode='Markdown', reply_markup=reply_markup),
                MessageType.VIDEO: lambda: bot.send_video(user_id, message.video.file_id,
                                                          caption=f"📨 **Ответ:**\n\n{message.caption or ''}",
                                                          parse_mode='Markdown', reply_markup=reply_markup),
                MessageType.VOICE: lambda: bot.send_voice(user_id, message.voice.file_id,
                                                          caption="📨 **Ответ**", parse_mode='Markdown',
                                                          reply_markup=reply_markup),
                MessageType.DOCUMENT: lambda: bot.send_document(user_id, message.document.file_id,
                                                                caption=f"📨 **Ответ:**\n\n{message.caption or ''}",
                                                                parse_mode='Markdown', reply_markup=reply_markup),
                MessageType.STICKER: lambda: [bot.send_sticker(user_id, message.sticker.file_id),
                                              bot.send_message(user_id, "📨 **Ответ**", parse_mode='Markdown',
                                                               reply_markup=reply_markup)]
            }

            for msg_type, handler in handlers.items():
                if getattr(message, msg_type.value, None):
                    result = handler()
                    return bool(result)

            bot.send_message(user_id, "📨 **Ответ**", parse_mode='Markdown', reply_markup=reply_markup)
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            return False


def admin_only(func: Callable) -> Callable:
    """Декоратор для проверки прав администратора"""

    @functools.wraps(func)
    def wrapper(call: types.CallbackQuery, *args, **kwargs):
        if call.message.chat.id != ADMIN_CHAT_ID:
            bot.answer_callback_query(call.id, "❌ Нет прав!")
            return
        return func(call, *args, **kwargs)

    return wrapper


# Команды
@bot.message_handler(commands=['start'])
def start_handler(message: types.Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    is_admin = user_id == ADMIN_CHAT_ID

    text = ("🤖 **Бот запущен!**\n\n" +
            ("✅ Панель администратора" if is_admin else
             "👻 Отправьте любое сообщение анонимно"))

    bot.send_message(user_id, text, parse_mode='Markdown')


# Обработка анонимных сообщений
@bot.message_handler(func=lambda m: m.chat.id != ADMIN_CHAT_ID,
                     content_types=[t.value for t in MessageType])
def handle_anon_message(message: types.Message):
    """Обработчик анонимных сообщений"""
    author = AuthorInfo(
        user_id=message.from_user.id,
        first_name=message.from_user.first_name or "без имени",
        username=message.from_user.username or "без username"
    )

    sent_msg = MessageSender.send_admin(message, Keyboards.main())

    if sent_msg:
        store.add_message(sent_msg.message_id, author)
        bot.send_message(message.chat.id, "✅ Отправлено!", parse_mode='Markdown')
        logger.info(f"Сообщение #{sent_msg.message_id} от {author.user_id}")
    else:
        bot.send_message(message.chat.id, "❌ Ошибка", parse_mode='Markdown')


# Callback handlers
@bot.callback_query_handler(func=lambda call: call.data == "reveal_author")
@admin_only
def reveal_author(call: types.CallbackQuery):
    """Раскрытие автора"""
    author = store.get_author(call.message.message_id)

    if not author:
        bot.answer_callback_query(call.id, "❌ Автор не найден")
        return

    author_text = format_author_info(author)

    try:
        if call.message.content_type == 'text':
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"{call.message.text}{author_text}",
                parse_mode='Markdown',
                reply_markup=Keyboards.reply_only()
            )
        elif call.message.content_type in ['photo', 'video', 'document', 'animation']:
            bot.edit_message_caption(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                caption=f"{call.message.caption or ''}{author_text}",
                parse_mode='Markdown',
                reply_markup=Keyboards.reply_only()
            )
        else:
            bot.send_message(
                chat_id=call.message.chat.id,
                text=f"👤 **Автор**\n{author_text}",
                parse_mode='Markdown',
                reply_to_message_id=call.message.message_id
            )
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=Keyboards.reply_only()
            )

        author.revealed = True
        bot.answer_callback_query(call.id, "✅ Автор раскрыт")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "❌ Ошибка")


@bot.callback_query_handler(func=lambda call: call.data == "reply_to_author")
@admin_only
def reply_to_author(call: types.CallbackQuery):
    """Ответ автору"""
    user_id = store.reply_map.get(call.message.message_id)

    if not user_id:
        bot.answer_callback_query(call.id, "❌ Нельзя ответить")
        return

    author = store.get_author(call.message.message_id)
    name = author.first_name if author else "пользователь"

    bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"✏️ **Напишите ответ для пользователя** (ID: `{user_id}`)",
        parse_mode='Markdown',
        reply_markup=Keyboards.cancel()
    )

    bot.register_next_step_handler_by_chat_id(
        ADMIN_CHAT_ID,
        process_admin_reply,
        user_id,
        call.message.message_id
    )

    bot.answer_callback_query(call.id, "📝 Введите ответ")


@bot.callback_query_handler(func=lambda call: call.data == "cancel_reply")
@admin_only
def cancel_reply(call: types.CallbackQuery):
    """Отмена ответа"""
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id, "❌ Отменено")


@bot.callback_query_handler(func=lambda call: call.data == "admin_reply_info")
def admin_reply_info(call: types.CallbackQuery):
    """Информация об ответе админа"""
    bot.answer_callback_query(call.id, "Это ответ администратора")


def process_admin_reply(message: types.Message, user_id: int, original_msg_id: int):
    """Обработка ответа админа"""
    if message.text and message.text.startswith('/'):
        return

    if MessageSender.send_to_user(message, user_id):
        bot.send_message(ADMIN_CHAT_ID, "✅ Доставлено!", parse_mode='Markdown')
        try:
            bot.delete_message(ADMIN_CHAT_ID, message.message_id - 1)
        except:
            pass
    else:
        bot.send_message(ADMIN_CHAT_ID, "❌ Ошибка доставки", parse_mode='Markdown')


# Найдите в конце файла эту часть:

if __name__ == '__main__':
    logger.info(f"🤖 Бот запускается...")
    logger.info(f"👤 Admin ID: {ADMIN_CHAT_ID}")
    
    # Настраиваем бота (удаляем webhook)
    setup_bot()
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Бот запущен в фоновом потоке")
    
    # Запускаем Flask сервер - ИСПРАВЛЕНО!
    port = int(os.environ.get("PORT", 10000))  # Берем порт из окружения или 10000
    logger.info(f"🌐 Запускаем веб-сервер на порту {port}")
    app.run(host='0.0.0.0', port=port)  # ВАЖНО: host='0.0.0.0', а не '127.0.0.1'
