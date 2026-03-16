from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Tuple

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню с красивыми смайликами"""
    buttons = [
        [KeyboardButton(text="📚 Темы")],
        [KeyboardButton(text="🎓 Экзамен")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="🚪 Выйти")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def auth_menu_kb() -> ReplyKeyboardMarkup:
    """Меню для неавторизованных"""
    buttons = [
        [KeyboardButton(text="🔑 Вход")],
        [KeyboardButton(text="📝 Регистрация")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def subgroup_kb() -> ReplyKeyboardMarkup:
    """Выбор подгруппы"""
    buttons = [
        [KeyboardButton(text="1️⃣ Подгруппа 1")],
        [KeyboardButton(text="2️⃣ Подгруппа 2")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def exam_menu_kb() -> ReplyKeyboardMarkup:
    """Меню экзаменов"""
    buttons = [
        [KeyboardButton(text="📝 Пробный экзамен")],
        [KeyboardButton(text="🎓 Итоговый экзамен")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def statistics_menu_kb() -> ReplyKeyboardMarkup:
    """Меню статистики"""
    buttons = [
        [KeyboardButton(text="📅 За неделю")],
        [KeyboardButton(text="📆 За всё время")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def topics_kb(topics: List[Tuple[int, str, str]]) -> InlineKeyboardMarkup:
    """Клавиатура с темами"""
    buttons = []
    for tid, name, _ in topics:
        # Убираем смайлик из названия для чистоты, но можно оставить
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"topic_{tid}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def question_options_kb(question_id: int, question_num: int, total: int) -> InlineKeyboardMarkup:
    """Клавиатура с вариантами ответов и индикатором прогресса"""
    buttons = [
        [
            InlineKeyboardButton(text="1️⃣", callback_data=f"q_{question_id}_1"),
            InlineKeyboardButton(text="2️⃣", callback_data=f"q_{question_id}_2"),
            InlineKeyboardButton(text="3️⃣", callback_data=f"q_{question_id}_3"),
            InlineKeyboardButton(text="4️⃣", callback_data=f"q_{question_id}_4")
        ],
        [InlineKeyboardButton(text=f"📊 Вопрос {question_num}/{total}", callback_data="ignore")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def profile_kb() -> InlineKeyboardMarkup:
    """Кнопки в личном кабинете"""
    buttons = [
        [InlineKeyboardButton(text="🔐 Сменить пароль", callback_data="change_password")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_kb() -> InlineKeyboardMarkup:
    """Простая кнопка назад"""
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)