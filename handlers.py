python
import logging
import os
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, ErrorEvent
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from states import (
    RegistrationStates, LoginStates, TopicQuizStates,
    PracticeExamStates, FinalExamStates
)
from keyboards import (
    main_menu_kb, auth_menu_kb, subgroup_kb, exam_menu_kb,
    statistics_menu_kb, topics_kb, question_options_kb, profile_kb, back_kb
)
from database import (
    get_user, create_user, check_user_password,
    get_all_topics, get_topic_by_id, get_exam_topic_ids,
    get_questions_by_topic, get_question_by_id,
    save_user_answer, get_questions_count,
    get_topic_statistics, get_overall_statistics, get_exam_statistics,
    get_all_users_stats, get_total_stats,
    TEACHERS, DATABASE_PATH
)
from utils import (
    build_question_text, exam_recommendation,
    get_teacher_by_subgroup, format_profile_text,
    get_time_limit, timer_task
)

# Для работы с БД в админке
import aiosqlite

router = Router()
# ========== ГЛОБАЛЬНЫЕ ХРАНИЛИЩА ==========

# Активные сессии (авторизованные пользователи)
active_sessions: Dict[int, bool] = {}

# Активные тесты: user_id -> данные теста
active_quizzes: Dict[int, Dict[str, Any]] = {}

# Кэш пользователей (чтобы не лезть в БД каждый раз)
user_cache: Dict[int, Dict] = {}

# Таймеры для каждого пользователя
active_timers: Dict[int, asyncio.Task] = {}

# ID администратора из окружения
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def is_authorized(user_id: int) -> bool:
    """Проверка авторизации (без БД)"""
    return active_sessions.get(user_id, False)


def is_admin(user_id: int) -> bool:
    """Проверка на администратора"""
    return user_id == ADMIN_ID


def is_in_quiz(user_id: int) -> bool:
    """Проверка, проходит ли пользователь тест"""
    return user_id in active_quizzes


async def get_cached_user(user_id: int) -> Optional[Dict]:
    """Получение пользователя из кэша или БД"""
    if user_id in user_cache:
        return user_cache[user_id]
    user = await get_user(user_id)
    if user:
        user_cache[user_id] = user
    return user


def invalidate_user_cache(user_id: int):
    """Очистка кэша пользователя"""
    user_cache.pop(user_id, None)


async def cancel_timer(user_id: int):
    """Отмена активного таймера"""
    if user_id in active_timers:
        active_timers[user_id].cancel()
        try:
            await active_timers[user_id]
        except asyncio.CancelledError:
            pass
        del active_timers[user_id]


async def force_finish_quiz(user_id: int, bot, state: FSMContext):
    """Принудительное завершение теста по таймеру"""
    if user_id not in active_quizzes:
        return

    quiz = active_quizzes[user_id]
    test_type = quiz.get("type", "topic")

    # Сохраняем результаты
    correct = quiz.get("correct", 0)
    total = len(quiz.get("questions", []))
    percent = (correct / total * 100.0) if total > 0 else 0.0

    if test_type == "topic":
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"📚 Тема завершена досрочно.\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)"
        )
    elif test_type == "practice_exam":
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"📝 Пробный экзамен завершён досрочно.\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)\n\n"
            f"{exam_recommendation(percent, is_final=False)}"
        )
    else:  # final_exam
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"🎓 Итоговый экзамен завершён досрочно.\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)\n\n"
            f"{exam_recommendation(percent, is_final=True)}"
        )

    try:
        await bot.send_message(user_id, text, reply_markup=main_menu_kb())
    except:
        pass

    # Очищаем данные
    active_quizzes.pop(user_id, None)
    await state.clear()
    await cancel_timer(user_id)


# ========== КОМАНДА /start ==========

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик /start"""
    user_id = message.from_user.id
    user = await get_cached_user(user_id)

    # Если пользователь сейчас проходит тест — не даём начать новый
    if is_in_quiz(user_id):
        await message.answer(
            "⚠️ Вы сейчас проходите тест! Сначала завершите его.",
            reply_markup=main_menu_kb()
        )
        return

    if user and is_authorized(user_id):
        await message.answer(
            f"👋 С возвращением, {user['first_name']}!",
            reply_markup=main_menu_kb()
        )
    elif user:
        await message.answer(
            "🔐 Вы уже зарегистрированы. Войдите:",
            reply_markup=auth_menu_kb()
        )
    else:
        await message.answer(
            "🔥 **Добро пожаловать в бот по термодинамике!**\n\n"
            "📚 Здесь вы можете проверить свои знания по курсу технической термодинамики.\n\n"
            "📝 Зарегистрируйтесь или войдите:",
            reply_markup=auth_menu_kb()
        )
    await state.clear()


# ========== РЕГИСТРАЦИЯ ==========

@router.message(F.text == "📝 Регистрация")
async def start_registration(message: Message, state: FSMContext) -> None:
    """Начало регистрации"""
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    await message.answer("📝 Введите ваше имя:")
    await state.set_state(RegistrationStates.waiting_for_first_name)


@router.message(RegistrationStates.waiting_for_first_name)
async def process_first_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ Имя не может быть пустым. Введите имя:")
        return
    await state.update_data(first_name=name)
    await message.answer("📝 Введите вашу фамилию:")
    await state.set_state(RegistrationStates.waiting_for_last_name)


@router.message(RegistrationStates.waiting_for_last_name)
async def process_last_name(message: Message, state: FSMContext) -> None:
    last = message.text.strip()
    if not last:
        await message.answer("❌ Фамилия не может быть пустой. Введите фамилию:")
        return
    await state.update_data(last_name=last)
    await message.answer("📚 Введите номер группы (например, ТД-101):")
    await state.set_state(RegistrationStates.waiting_for_group_number)


@router.message(RegistrationStates.waiting_for_group_number)
async def process_group_number(message: Message, state: FSMContext) -> None:
    group = message.text.strip()
    if not group:
        await message.answer("❌ Группа не может быть пустой. Введите группу:")
        return
    await state.update_data(group_number=group)
    await message.answer(
        "🔢 Выберите подгруппу:",
        reply_markup=subgroup_kb()
    )
    await state.set_state(RegistrationStates.waiting_for_subgroup)


@router.message(RegistrationStates.waiting_for_subgroup)
async def process_subgroup(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    subgroup_map = {
        "1️⃣ Подгруппа 1": 1,
        "2️⃣ Подгруппа 2": 2,
        "1": 1,
        "2": 2
    }
    subgroup = subgroup_map.get(text)
    if not subgroup:
        await message.answer("❌ Пожалуйста, выберите 1 или 2, используя кнопки.")
        return
    await state.update_data(subgroup=subgroup)
    await message.answer(
        "🔑 Придумайте пароль (минимум 4 символа):",
        reply_markup=None
    )
    await state.set_state(RegistrationStates.waiting_for_password)


@router.message(RegistrationStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext) -> None:
    password = message.text.strip()
    if len(password) < 4:
        await message.answer("❌ Пароль слишком короткий. Минимум 4 символа. Введите другой:")
        return

    data = await state.get_data()
    user_id = message.from_user.id

    try:
        await create_user(
            user_id=user_id,
            first_name=data["first_name"],
            last_name=data["last_name"],
            group_number=data["group_number"],
            subgroup=data["subgroup"],
            password=password
        )
        # Авторизуем
        active_sessions[user_id] = True
        invalidate_user_cache(user_id)

        teacher = get_teacher_by_subgroup(data["subgroup"])
        await message.answer(
            f"✅ **Регистрация завершена!**\n\n"
            f"👤 Имя: {data['first_name']}\n"
            f"👤 Фамилия: {data['last_name']}\n"
            f"📚 Группа: {data['group_number']}\n"
            f"🔢 Подгруппа: {data['subgroup']}\n"
            f"{teacher}\n\n"
            f"🚀 Вы автоматически вошли в систему.",
            reply_markup=main_menu_kb()
        )
    except Exception as e:
        logging.exception(f"Registration error: {e}")
        await message.answer("❌ Ошибка регистрации. Попробуйте позже.")
    finally:
        await state.clear()


# ========== ВХОД ==========

@router.message(F.text == "🔑 Вход")
async def start_login(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return

    user = await get_cached_user(user_id)
    if not user:
        await message.answer("❌ Сначала зарегистрируйтесь!")
        return

    await message.answer("🔑 Введите пароль:")
    await state.set_state(LoginStates.waiting_for_password)


@router.message(LoginStates.waiting_for_password)
async def process_login_password(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    password = message.text.strip()

    if await check_user_password(user_id, password):
        active_sessions[user_id] = True
        user = await get_cached_user(user_id)
        await message.answer(
            f"✅ **Вход выполнен!**\n"
            f"👋 Добро пожаловать, {user['first_name']}.",
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer("❌ Неверный пароль. Попробуйте ещё раз.")
    await state.clear()


# ========== ВЫХОД ==========

@router.message(F.text == "🚪 Выйти")
async def logout(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    active_sessions.pop(user_id, None)
    active_quizzes.pop(user_id, None)
    user_cache.pop(user_id, None)
    await cancel_timer(user_id)
    await state.clear()
    await message.answer(
        "👋 Вы вышли из системы. До свидания!",
        reply_markup=auth_menu_kb()
    )
    """
handlers.py – ЧАСТЬ 2/4
Личный кабинет, навигация, проверка авторизации, блокировка меню во время теста
"""

# ========== МИДЛВАРЬ ДЛЯ БЛОКИРОВКИ МЕНЮ ВО ВРЕМЯ ТЕСТА ==========

@router.message(F.text.in_(["📚 Темы", "🎓 Экзамен", "📊 Статистика", "👤 Личный кабинет"]))
async def check_quiz_block(message: Message, state: FSMContext) -> None:
    """
    Проверяет, не проходит ли пользователь тест.
    Если да — блокирует нажатие на кнопки меню.
    """
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        quiz = active_quizzes.get(user_id, {})
        test_type = quiz.get("type", "topic")
        
        # Определяем тип теста для информативного сообщения
        if test_type == "topic":
            msg = "📚 Вы сейчас проходите **тест по теме**! Сначала завершите его."
        elif test_type == "practice_exam":
            msg = "📝 Вы сейчас проходите **пробный экзамен**! Сначала завершите его."
        elif test_type == "final_exam":
            msg = "🎓 Вы сейчас проходите **итоговый экзамен**! Сначала завершите его."
        else:
            msg = "⚠️ Вы сейчас проходите тест! Сначала завершите его."
        
        await message.answer(msg)
        return

    # Если теста нет — передаём обработку дальше
    await handle_menu_navigation(message, state)


async def handle_menu_navigation(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает нажатия на кнопки главного меню
    """
    user_id = message.from_user.id
    text = message.text

    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.", reply_markup=auth_menu_kb())
        return

    if text == "📚 Темы":
        await show_topics_menu(message)
    elif text == "🎓 Экзамен":
        await message.answer("📝 Выберите тип экзамена:", reply_markup=exam_menu_kb())
    elif text == "📊 Статистика":
        await message.answer("📅 Выберите период:", reply_markup=statistics_menu_kb())
    elif text == "👤 Личный кабинет":
        await show_profile(message)


# ========== ЛИЧНЫЙ КАБИНЕТ ==========

async def show_profile(message: Message) -> None:
    """Показывает личный кабинет"""
    user_id = message.from_user.id
    user = await get_cached_user(user_id)
    if not user:
        await message.answer("❌ Ошибка: пользователь не найден")
        return

    teacher = get_teacher_by_subgroup(user['subgroup'])
    stats = await get_overall_statistics(user_id)
    
    text = format_profile_text(user, stats, teacher)
    await message.answer(text, reply_markup=profile_kb())


@router.message(F.text == "👤 Личный кабинет")
async def profile_handler(message: Message) -> None:
    """Обработчик кнопки Личный кабинет"""
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    await show_profile(message)


# ========== КНОПКА НАЗАД ==========

@router.message(F.text == "🔙 Назад")
async def go_back(message: Message, state: FSMContext) -> None:
    """Возврат в главное меню"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return

    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.", reply_markup=auth_menu_kb())
        return

    await state.clear()
    await message.answer("🔙 Главное меню:", reply_markup=main_menu_kb())


# ========== ОБРАБОТКА INLINE-КНОПОК НАЗАД ==========

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_inline(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка инлайн-кнопки Назад"""
    await callback.answer()
    user_id = callback.from_user.id
    
    if is_in_quiz(user_id):
        await callback.message.answer("⚠️ Сначала завершите текущий тест!")
        return

    await callback.message.delete()
    if is_authorized(user_id):
        await callback.message.answer("🔙 Главное меню:", reply_markup=main_menu_kb())
    else:
        await callback.message.answer("🔙 Главное меню:", reply_markup=auth_menu_kb())
    await state.clear()


@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery) -> None:
    """Заглушка для неактивных кнопок"""
    await callback.answer()


# ========== СМЕНА ПАРОЛЯ (ЗАГЛУШКА) ==========

@router.callback_query(F.data == "change_password")
async def change_password(callback: CallbackQuery) -> None:
    """Смена пароля (в разработке)"""
    await callback.answer("🔧 Функция смены пароля в разработке", show_alert=True)


# ========== ПОКАЗ ТЕМ ==========

async def show_topics_menu(message: Message) -> None:
    """Показывает список доступных тем"""
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.")
        return

    topics = await get_all_topics(include_exams=False)
    if not topics:
        await message.answer("📚 Темы пока не добавлены.")
        return

    # Красивое сообщение со списком тем
    text = "📚 **Доступные темы:**\n\n"
    for i, (_, name, _) in enumerate(topics, 1):
        # Добавляем разные смайлики для разных тем
        emoji = ["🔹", "🔥", "⚡", "📊", "🔄", "💧", "🌊", "💨", "🏭", "✈️", "🚗"][i-1] if i <= 11 else "📌"
        text += f"{emoji} {name}\n"
    
    await message.answer(text, reply_markup=topics_kb(topics))


@router.message(F.text == "📚 Темы")
async def topics_menu_handler(message: Message) -> None:
    """Обработчик кнопки Темы"""
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    await show_topics_menu(message)


# ========== ЭКЗАМЕНЫ ==========

@router.message(F.text == "📝 Пробный экзамен")
async def start_practice_exam(message: Message, state: FSMContext) -> None:
    """Запуск пробного экзамена"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Вы уже проходите тест! Сначала завершите его.")
        return

    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.")
        return

    exam_ids = await get_exam_topic_ids()
    practice_id = exam_ids.get('practice')
    if not practice_id:
        await message.answer("❌ Пробный экзамен пока не настроен.")
        return

    questions = await get_questions_by_topic(practice_id)
    if not questions:
        await message.answer("❌ Вопросы для пробного экзамена не найдены.")
        return

    # Получаем количество вопросов (должно быть 30)
    total = len(questions)
    
    # Сохраняем данные экзамена
    q_ids = [q['id'] for q in questions]
    q_data = {q['id']: q for q in questions}
    
    active_quizzes[user_id] = {
        "type": "practice_exam",
        "topic_id": practice_id,
        "questions": q_ids,
        "questions_data": q_data,
        "current_index": 0,
        "correct": 0,
        "total": total
    }

    # Запускаем таймер (20 минут)
    await cancel_timer(user_id)
    timer_task_obj = asyncio.create_task(
        timer_task(user_id, 20, lambda uid: force_finish_quiz(uid, message.bot, state))
    )
    active_timers[user_id] = timer_task_obj

    await state.set_state(PracticeExamStates.in_practice_exam)
    
    await message.answer(
        f"📝 **Пробный экзамен**\n\n"
        f"⏱️ Время: **20 минут**\n"
        f"📋 Количество вопросов: {total}\n\n"
        f"🔥 Удачи!",
        reply_markup=None  # Убираем клавиатуру, чтобы нельзя было нажать другие кнопки
    )
    
    # Отправляем первый вопрос
    first_q_id = q_ids[0]
    first_q = q_data[first_q_id]
    text = build_question_text(first_q, 1, total)
    await message.answer(
        text,
        reply_markup=question_options_kb(first_q_id, 1, total)
    )


@router.message(F.text == "🎓 Итоговый экзамен")
async def start_final_exam(message: Message, state: FSMContext) -> None:
    """Запуск итогового экзамена (50 вопросов, 30 минут)"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Вы уже проходите тест! Сначала завершите его.")
        return

    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.")
        return

    exam_ids = await get_exam_topic_ids()
    final_id = exam_ids.get('final')
    if not final_id:
        await message.answer("❌ Итоговый экзамен пока не настроен.")
        return

    questions = await get_questions_by_topic(final_id)
    if not questions:
        await message.answer("❌ Вопросы для итогового экзамена не найдены.")
        return

    # Получаем количество вопросов (должно быть 50)
    total = len(questions)
    
    q_ids = [q['id'] for q in questions]
    q_data = {q['id']: q for q in questions}
    
    active_quizzes[user_id] = {
        "type": "final_exam",
        "topic_id": final_id,
        "questions": q_ids,
        "questions_data": q_data,
        "current_index": 0,
        "correct": 0,
        "total": total
    }

    # Запускаем таймер (30 минут)
    await cancel_timer(user_id)
    timer_task_obj = asyncio.create_task(
        timer_task(user_id, 30, lambda uid: force_finish_quiz(uid, message.bot, state))
    )
    active_timers[user_id] = timer_task_obj

    await state.set_state(FinalExamStates.in_final_exam)
    
    await message.answer(
        f"🎓 **ИТОГОВЫЙ ЭКЗАМЕН**\n\n"
        f"⏱️ Время: **30 минут**\n"
        f"📋 Количество вопросов: {total}\n\n"
        f"💪 Желаем успеха!",
        reply_markup=None
    )
    
    # Отправляем первый вопрос
    first_q_id = q_ids[0]
    first_q = q_data[first_q_id]
    text = build_question_text(first_q, 1, total)
    await message.answer(
        text,
        reply_markup=question_options_kb(first_q_id, 1, total)
    )


# ========== СТАТИСТИКА ==========

@router.message(F.text == "📅 За неделю")
async def show_weekly_stats(message: Message) -> None:
    """Статистика за последние 7 дней"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return

    if not is_authorized(user_id):
        return

    topic_stats = await get_topic_statistics(user_id, days=7)
    total, correct, percent = await get_overall_statistics(user_id, days=7)
    practice_total, practice_correct, practice_percent = await get_exam_statistics(user_id, 'practice_exam')
    final_total, final_correct, final_percent = await get_exam_statistics(user_id, 'final_exam')

    lines = ["📊 **Статистика за неделю:**\n"]
    
    if topic_stats:
        for topic_name, t, c, p in topic_stats:
            lines.append(f"📚 {topic_name}: {c}/{t} ({p:.1f}%)")
    else:
        lines.append("📭 Нет данных по темам за неделю")
    
    lines.append("")
    if practice_total > 0:
        lines.append(f"📝 Пробный экзамен: {practice_correct}/{practice_total} ({practice_percent:.1f}%)")
    if final_total > 0:
        lines.append(f"🎓 Итоговый экзамен: {final_correct}/{final_total} ({final_percent:.1f}%)")
    
    lines.append("")
    if total > 0:
        lines.append(f"📈 Всего: {correct}/{total} ({percent:.1f}%)")
    else:
        lines.append("📈 Нет данных за неделю")

    await message.answer("\n".join(lines), reply_markup=statistics_menu_kb())


@router.message(F.text == "📆 За всё время")
async def show_all_time_stats(message: Message) -> None:
    """Статистика за всё время"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return

    if not is_authorized(user_id):
        return

    topic_stats = await get_topic_statistics(user_id)
    total, correct, percent = await get_overall_statistics(user_id)
    practice_total, practice_correct, practice_percent = await get_exam_statistics(user_id, 'practice_exam')
    final_total, final_correct, final_percent = await get_exam_statistics(user_id, 'final_exam')

    lines = ["📊 **Статистика за всё время:**\n"]
    
    if topic_stats:
        for topic_name, t, c, p in topic_stats:
            lines.append(f"📚 {topic_name}: {c}/{t} ({p:.1f}%)")
    else:
        lines.append("📭 Нет данных по темам")
    
    lines.append("")
    if practice_total > 0:
        lines.append(f"📝 Пробный экзамен: {practice_correct}/{practice_total} ({practice_percent:.1f}%)")
    else:
        lines.append("📝 Пробный экзамен: не пройден")
    
    if final_total > 0:
        lines.append(f"🎓 Итоговый экзамен: {final_correct}/{final_total} ({final_percent:.1f}%)")
    else:
        lines.append("🎓 Итоговый экзамен: не пройден")
    
    lines.append("")
    if total > 0:
        lines.append(f"📈 Всего: {correct}/{total} ({percent:.1f}%)")
    else:
        lines.append("📈 Нет данных")

    await message.answer("\n".join(lines), reply_markup=statistics_menu_kb())


@router.message(F.text == "📊 Статистика")
async def statistics_handler(message: Message) -> None:
    """Обработчик кнопки Статистика"""
    user_id = message.from_user.id
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    await message.answer("📅 Выберите период:", reply_markup=statistics_menu_kb())
    """
handlers.py – ЧАСТЬ 3/4
Обработка выбора темы, ответов на вопросы, завершение тестов
"""

# ========== ВЫБОР ТЕМЫ ==========

@router.callback_query(F.data.startswith("topic_"))
async def callback_select_topic(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора обычной темы"""
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверка на уже идущий тест
    if is_in_quiz(user_id):
        await callback.message.answer("⚠️ Вы уже проходите тест! Сначала завершите его.")
        return

    if not is_authorized(user_id):
        await callback.message.answer("🔐 Сначала войдите в систему.")
        return

    try:
        topic_id = int(callback.data.split("_")[1])
        topic = await get_topic_by_id(topic_id)
        if not topic:
            await callback.message.answer("❌ Тема не найдена.")
            return

        questions = await get_questions_by_topic(topic_id)
        if not questions:
            await callback.message.answer("❌ Вопросы для этой темы не найдены.")
            return

        # Получаем количество вопросов (должно быть 15)
        total = len(questions)
        
        # Сохраняем данные теста
        q_ids = [q['id'] for q in questions]
        q_data = {q['id']: q for q in questions}
        
        active_quizzes[user_id] = {
            "type": "topic",
            "topic_id": topic_id,
            "topic_name": topic['name'],
            "questions": q_ids,
            "questions_data": q_data,
            "current_index": 0,
            "correct": 0,
            "total": total
        }

        # Запускаем таймер (10 минут)
        await cancel_timer(user_id)
        timer_task_obj = asyncio.create_task(
            timer_task(user_id, 10, lambda uid: force_finish_quiz(uid, callback.message.bot, state))
        )
        active_timers[user_id] = timer_task_obj

        await state.set_state(TopicQuizStates.in_topic_quiz)
        
        await callback.message.delete()
        
        # Красивое сообщение о начале теста
        topic_emojis = {
            "📌 Основы термодинамики": "🔹",
            "🔥 Первый закон термодинамики": "🔥",
            "⚡ Второй закон термодинамики": "⚡",
            "📊 Газы и газовые смеси": "📊",
            "🔄 Газовые процессы": "🔄",
            "💧 Реальные газы и пары": "💧",
            "🌊 Вода и водяной пар": "🌊",
            "💨 Влажный воздух": "💨",
            "🏭 Циклы паротурбинных установок": "🏭",
            "✈️ Циклы газотурбинных установок": "✈️",
            "🚗 Циклы ДВС": "🚗"
        }
        emoji = topic_emojis.get(topic['name'], "📌")
        
        await callback.message.answer(
            f"{emoji} **{topic['name']}**\n\n"
            f"⏱️ Время: **10 минут**\n"
            f"📋 Количество вопросов: {total}\n\n"
            f"🚀 Начинаем тест!",
            reply_markup=None
        )
        
        # Отправляем первый вопрос
        first_q_id = q_ids[0]
        first_q = q_data[first_q_id]
        text = build_question_text(first_q, 1, total)
        await callback.message.answer(
            text,
            reply_markup=question_options_kb(first_q_id, 1, total)
        )

    except Exception as e:
        logging.exception(f"Topic selection error: {e}")
        await callback.message.answer("❌ Ошибка при выборе темы.")


# ========== ОБРАБОТКА ОТВЕТОВ НА ВОПРОСЫ ==========

@router.callback_query(F.data.startswith("q_"))
async def callback_answer_question(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Универсальный обработчик ответов для всех типов тестов
    """
    await callback.answer()
    
    user_id = callback.from_user.id
    
    # Проверяем, есть ли активный тест
    if user_id not in active_quizzes:
        await callback.message.answer(
            "❌ Тест не найден. Начните заново из меню.",
            reply_markup=main_menu_kb()
        )
        return

    quiz = active_quizzes[user_id]
    current_state = await state.get_state()
    
    # Проверяем соответствие состояния
    expected_state = None
    if quiz["type"] == "topic":
        expected_state = TopicQuizStates.in_topic_quiz.state
    elif quiz["type"] == "practice_exam":
        expected_state = PracticeExamStates.in_practice_exam.state
    elif quiz["type"] == "final_exam":
        expected_state = FinalExamStates.in_final_exam.state
    
    if current_state != expected_state:
        await callback.message.answer(
            "❌ Ошибка состояния теста. Начните заново.",
            reply_markup=main_menu_kb()
        )
        active_quizzes.pop(user_id, None)
        await state.clear()
        await cancel_timer(user_id)
        return

    try:
        parts = callback.data.split("_")
        if len(parts) != 3:
            await callback.message.answer("❌ Некорректные данные.")
            return

        question_id = int(parts[1])
        chosen = int(parts[2])

        # Проверяем, что отвечают на текущий вопрос
        current_index = quiz["current_index"]
        questions_list = quiz["questions"]
        total = quiz["total"]

        if current_index >= len(questions_list):
            await callback.message.answer(
                "❌ Тест уже завершён.",
                reply_markup=main_menu_kb()
            )
            active_quizzes.pop(user_id, None)
            await state.clear()
            await cancel_timer(user_id)
            return

        expected_id = questions_list[current_index]
        if question_id != expected_id:
            # Попытка ответить на другой вопрос — игнорируем
            await callback.message.answer(
                "⚠️ Пожалуйста, ответьте на текущий вопрос.",
                show_alert=True
            )
            return

        # Получаем вопрос (из кэша или БД)
        question = quiz["questions_data"].get(question_id)
        if not question:
            question = await get_question_by_id(question_id)
            if not question:
                await callback.message.answer("❌ Вопрос не найден.")
                return
            quiz["questions_data"][question_id] = question

        # Проверяем правильность ответа
        correct = (chosen == question["correct_option"])
        test_type = quiz["type"]

        # Сохраняем ответ
        await save_user_answer(user_id, question_id, chosen, correct, test_type)

        # Обновляем счётчик
        if correct:
            quiz["correct"] += 1

        # Удаляем сообщение с вопросом (чтобы не захламлять чат)
        try:
            await callback.message.delete()
        except:
            pass  # Если не удалось удалить — не страшно

        # Показываем результат ответа
        if correct:
            result_text = "✅ **Верно!**"
        else:
            correct_option = question["correct_option"]
            option_map = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣"}
            result_text = (
                f"❌ **Неверно.**\n"
                f"Правильный ответ: {option_map[correct_option]}"
            )
        
        # Добавляем пояснение, если есть
        if question.get("explanation"):
            result_text += f"\n\n📘 *Пояснение:* {question['explanation']}"

        await callback.message.answer(result_text)

        # Переходим к следующему вопросу
        quiz["current_index"] += 1
        current_index = quiz["current_index"]

        # Проверяем, есть ли ещё вопросы
        if current_index >= len(questions_list):
            # Тест завершён
            await finish_quiz(user_id, callback.message.bot, state)
            return

        # Отправляем следующий вопрос
        next_id = questions_list[current_index]
        next_q = quiz["questions_data"].get(next_id)
        if not next_q:
            next_q = await get_question_by_id(next_id)
            if next_q:
                quiz["questions_data"][next_id] = next_q

        if next_q:
            text = build_question_text(next_q, current_index + 1, total)
            await callback.message.answer(
                text,
                reply_markup=question_options_kb(next_id, current_index + 1, total)
            )
        else:
            await callback.message.answer("❌ Ошибка загрузки следующего вопроса.")
            active_quizzes.pop(user_id, None)
            await state.clear()
            await cancel_timer(user_id)

    except Exception as e:
        logging.exception(f"Answer error for user {user_id}: {e}")
        await callback.message.answer("❌ Ошибка при обработке ответа.")


# ========== ЗАВЕРШЕНИЕ ТЕСТА ==========

async def finish_quiz(user_id: int, bot, state: FSMContext) -> None:
    """Завершение теста и показ результатов"""
    if user_id not in active_quizzes:
        return

    quiz = active_quizzes[user_id]
    test_type = quiz["type"]
    correct = quiz["correct"]
    total = quiz["total"]
    percent = (correct / total * 100.0) if total > 0 else 0.0

    # Формируем сообщение в зависимости от типа теста
    if test_type == "topic":
        topic_name = quiz.get("topic_name", "Тема")
        # Выбираем смайлик для темы
        topic_emojis = {
            "📌 Основы термодинамики": "🔹",
            "🔥 Первый закон термодинамики": "🔥",
            "⚡ Второй закон термодинамики": "⚡",
            "📊 Газы и газовые смеси": "📊",
            "🔄 Газовые процессы": "🔄",
            "💧 Реальные газы и пары": "💧",
            "🌊 Вода и водяной пар": "🌊",
            "💨 Влажный воздух": "💨",
            "🏭 Циклы паротурбинных установок": "🏭",
            "✈️ Циклы газотурбинных установок": "✈️",
            "🚗 Циклы ДВС": "🚗"
        }
        emoji = topic_emojis.get(topic_name, "📌")
        
        text = (
            f"{emoji} **{topic_name} завершена!**\n\n"
            f"✅ Правильных ответов: **{correct}** из **{total}**\n"
            f"📊 Успеваемость: **{percent:.1f}%**\n"
        )
        
        # Добавляем рекомендацию
        if percent >= 80:
            text += "\n🌟 Отличный результат!"
        elif percent >= 60:
            text += "\n📚 Хороший результат, но есть над чем поработать."
        else:
            text += "\n📖 Нужно повторить тему."

    elif test_type == "practice_exam":
        text = (
            f"📝 **Пробный экзамен завершён!**\n\n"
            f"✅ Правильных ответов: **{correct}** из **{total}**\n"
            f"📊 Успеваемость: **{percent:.1f}%**\n\n"
            f"{exam_recommendation(percent, is_final=False)}"
        )
    else:  # final_exam
        # Определяем, сдан ли экзамен
        passed = percent >= 70
        status = "✅ **СДАНО**" if passed else "❌ **НЕ СДАНО**"
        
        text = (
            f"🎓 **ИТОГОВЫЙ ЭКЗАМЕН**\n\n"
            f"{status}\n\n"
            f"✅ Правильных ответов: **{correct}** из **{total}**\n"
            f"📊 Успеваемость: **{percent:.1f}%**\n\n"
            f"{exam_recommendation(percent, is_final=True)}"
        )
        
        # Если сдано — поздравляем
        if passed:
            text += "\n\n🏆 Поздравляем с успешной сдачей экзамена!"

    # Отправляем результат
    await bot.send_message(user_id, text, reply_markup=main_menu_kb())

    # Очищаем данные
    active_quizzes.pop(user_id, None)
    await state.clear()
    await cancel_timer(user_id)


# ========== ОБРАБОТКА ДОСРОЧНОГО ЗАВЕРШЕНИЯ ПО ТАЙМЕРУ ==========

async def force_finish_quiz(user_id: int, bot, state: FSMContext) -> None:
    """Принудительное завершение теста по таймеру"""
    if user_id not in active_quizzes:
        return

    quiz = active_quizzes[user_id]
    test_type = quiz["type"]
    correct = quiz["correct"]
    total = quiz["total"]
    percent = (correct / total * 100.0) if total > 0 else 0.0

    if test_type == "topic":
        topic_name = quiz.get("topic_name", "Тема")
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"📚 {topic_name} завершена досрочно.\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)"
        )
    elif test_type == "practice_exam":
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"📝 Пробный экзамен завершён досрочно.\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)\n\n"
            f"{exam_recommendation(percent, is_final=False)}"
        )
    else:
        passed = percent >= 70
        status = "✅ СДАНО" if passed else "❌ НЕ СДАНО"
        text = (
            f"⏱️ **Время вышло!**\n\n"
            f"🎓 Итоговый экзамен завершён досрочно.\n"
            f"{status}\n"
            f"✅ Правильных: {correct} из {total} ({percent:.1f}%)\n\n"
            f"{exam_recommendation(percent, is_final=True)}"
        )

    try:
        await bot.send_message(user_id, text, reply_markup=main_menu_kb())
    except:
        pass

    active_quizzes.pop(user_id, None)
    await state.clear()
    await cancel_timer(user_id)


# ========== ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ ==========

@router.message()
async def handle_unknown(message: Message) -> None:
    """Обработка любых других сообщений"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        # Если пользователь проходит тест — игнорируем любые текстовые сообщения
        await message.answer(
            "⚠️ Вы сейчас проходите тест! Используйте кнопки с вариантами ответов.",
            show_alert=True
        )
        return
    
    if is_authorized(user_id):
        await message.answer(
            "❓ Неизвестная команда. Используйте кнопки меню.",
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer(
            "❓ Неизвестная команда. Используйте /start для начала работы.",
            reply_markup=auth_menu_kb()
        )
        """
handlers.py – ЧАСТЬ 4/4
Админ-панель, команда /admin, статистика по всем пользователям, финальные обработчики
"""

# ========== КОМАНДА /ADMIN (ТОЛЬКО ДЛЯ АДМИНА) ==========

@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    """Панель администратора (только для ADMIN_ID)"""
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ **Доступ запрещён!**\n\nЭта команда только для администратора.")
        return
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return

    total_stats = await get_total_stats()
    
    # Получаем список всех пользователей с краткой статистикой
    users_stats = await get_all_users_stats()
    
    # Формируем красивое сообщение
    text = (
        f"👑 **ПАНЕЛЬ АДМИНИСТРАТОРА**\n\n"
        f"📊 **Общая статистика:**\n"
        f"👥 Всего пользователей: **{total_stats['users_count']}**\n"
        f"📋 Всего ответов: **{total_stats['total_answers']}**\n"
        f"✅ Правильных ответов: **{total_stats['correct_answers']}**\n"
        f"📈 Средний процент: **{total_stats['avg_percent']:.1f}%**\n\n"
        f"📋 **Статистика по пользователям:**\n"
    )
    
    if users_stats:
        for user in users_stats[:10]:  # Показываем первых 10, чтобы не перегружать
            name = f"{user['first_name']} {user['last_name']}"
            if len(name) > 20:
                name = name[:18] + "…"
            text += (
                f"👤 {name} | {user['group_number']} | П:{user['subgroup']}\n"
                f"   📊 {user['total_answers']} отв. | ✅ {user['correct_answers']} | "
                f"📈 {user['success_percent']}%\n"
            )
        
        if len(users_stats) > 10:
            text += f"\n... и ещё {len(users_stats) - 10} пользователей"
    else:
        text += "📭 Нет данных о пользователях"
    
    # Добавляем инлайн-кнопки для админа
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Полная статистика", callback_data="admin_full_stats")],
        [InlineKeyboardButton(text="🗑️ Очистить всё", callback_data="admin_clear_all")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])
    
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "admin_full_stats")
async def admin_full_stats(callback: CallbackQuery) -> None:
    """Показать полную статистику по всем пользователям"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.answer()
    users_stats = await get_all_users_stats()
    
    if not users_stats:
        await callback.message.answer("📭 Нет данных о пользователях.")
        return
    
    # Формируем подробную статистику
    lines = ["📋 **ПОЛНАЯ СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ**\n"]
    
    for user in users_stats:
        reg_date = user.get('registered_at', 'неизв.')[:10] if user.get('registered_at') else 'неизв.'
        teacher = TEACHERS.get(user['subgroup'], "Неизв.")
        
        lines.append(
            f"\n👤 **{user['first_name']} {user['last_name']}**\n"
            f"📚 Группа: {user['group_number']} | Подгр: {user['subgroup']}\n"
            f"👨‍🏫 Преподаватель: {teacher}\n"
            f"📅 Регистрация: {reg_date}\n"
            f"📊 Всего ответов: {user['total_answers']}\n"
            f"✅ Правильных: {user['correct_answers']} ({user['success_percent']}%)\n"
            f"🆔 ID: {user['user_id']}"
        )
        lines.append("─" * 30)
    
    # Разбиваем на части, если слишком длинно
    text = "\n".join(lines)
    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            await callback.message.answer(text[i:i+4096])
    else:
        await callback.message.answer(text)


@router.callback_query(F.data == "admin_clear_all")
async def admin_clear_all(callback: CallbackQuery) -> None:
    """Подтверждение очистки всех данных"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.answer()
    
    # Клавиатура подтверждения
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, ОЧИСТИТЬ ВСЁ", callback_data="admin_confirm_clear")],
        [InlineKeyboardButton(text="❌ ОТМЕНА", callback_data="back_to_menu")]
    ])
    
    await callback.message.answer(
        "⚠️ **ВНИМАНИЕ!**\n\n"
        "Это действие **безвозвратно удалит**:\n"
        "• Всех пользователей\n"
        "• Все ответы\n"
        "• Всю статистику\n\n"
        "База данных будет очищена полностью!\n\n"
        "Вы уверены?",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin_confirm_clear")
async def admin_confirm_clear(callback: CallbackQuery) -> None:
    """Очистка всей базы данных (только для админа)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.answer()
    
    try:
        # Очищаем таблицы
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM user_answers")
            await db.execute("DELETE FROM users")
            # Не удаляем вопросы и темы, только ответы и пользователей
            await db.commit()
        
        # Очищаем кэши
        active_sessions.clear()
        active_quizzes.clear()
        user_cache.clear()
        
        # Отменяем все таймеры
        for uid in list(active_timers.keys()):
            await cancel_timer(uid)
        
        await callback.message.answer(
            "✅ **База данных очищена!**\n\n"
            "Все пользователи и их ответы удалены.\n"
            "Вопросы и темы сохранены.",
            reply_markup=main_menu_kb()
        )
        
        # Логируем действие
        logging.info(f"Admin {callback.from_user.id} cleared all data")
        
    except Exception as e:
        logging.exception(f"Error clearing database: {e}")
        await callback.message.answer("❌ Ошибка при очистке базы данных.")


# ========== ИНФОРМАЦИОННЫЕ КОМАНДЫ ==========

@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Команда /help"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    
    help_text = (
        "🔍 **Справка по боту**\n\n"
        "📚 **Темы** — тесты по разделам термодинамики (по 15 вопросов, 10 минут)\n"
        "📝 **Пробный экзамен** — 30 вопросов, 20 минут\n"
        "🎓 **Итоговый экзамен** — 50 вопросов, 30 минут (проходной балл: 70%)\n"
        "📊 **Статистика** — ваши результаты за неделю и за всё время\n"
        "👤 **Личный кабинет** — информация о вас и вашем преподавателе\n\n"
        "⏱️ **Важно:** Во время теста другие кнопки блокируются!\n"
        "❓ При ответе используйте кнопки 1️⃣-4️⃣\n\n"
        "👨‍🏫 Преподаватели:\n"
        "• Подгруппа 1 — Шишмарев Павел Викторович\n"
        "• Подгруппа 2 — Карабарин Денис Игоревич"
    )
    
    await message.answer(help_text)


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    """Информация о боте"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    
    info_text = (
        "ℹ️ **О боте**\n\n"
        "🔥 **Термодинамика Тест Бот**\n"
        "Версия: 2.0\n\n"
        "📚 Основан на учебном пособии:\n"
        "Карабарин Д.И. «Техническая термодинамика»\n"
        "Сибирский федеральный университет, 2022\n\n"
        "⚙️ Функционал:\n"
        "• 11 тем по термодинамике\n"
        "• Пробный и итоговый экзамены\n"
        "• Таймеры на каждый тест\n"
        "• Подробная статистика\n"
        "• Личный кабинет с преподавателем\n\n"
        "👨‍💻 Разработано для студентов кафедры ТЭС"
    )
    
    await message.answer(info_text)


# ========== КОМАНДА /STATS (ДЛЯ АДМИНА) ==========

@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Краткая статистика (для всех авторизованных)"""
    user_id = message.from_user.id
    
    if is_in_quiz(user_id):
        await message.answer("⚠️ Сначала завершите текущий тест!")
        return
    
    if not is_authorized(user_id):
        await message.answer("🔐 Сначала войдите в систему.")
        return
    
    # Для обычных пользователей показываем их личную статистику
    await show_all_time_stats(message)


# ========== ОБРАБОТКА НЕИЗВЕСТНЫХ CALLBACK ==========

@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Обработка неизвестных callback-запросов"""
    await callback.answer("❓ Неизвестная команда", show_alert=True)


# ========== ОБРАБОТКА ОШИБОК ==========

@router.errors()
async def error_handler(event: ErrorEvent) -> None:
    """Глобальный обработчик ошибок"""
    logging.error(f"Critical error: {event.exception}")
    
    try:
        if event.update.message:
            await event.update.message.answer(
                "❌ Произошла внутренняя ошибка. Администратор уже уведомлён."
            )
        elif event.update.callback_query:
            await event.update.callback_query.answer(
                "❌ Произошла ошибка", show_alert=True
            )
    except:
        pass
