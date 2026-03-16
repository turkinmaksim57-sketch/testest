import asyncio
from typing import Dict, Tuple

TEACHERS = {
    1: "👨‍🏫 Шишмарев Павел Викторович",
    2: "👨‍🔬 Карабарин Денис Игоревич"
}

def build_question_text(question: Dict, question_num: int, total: int) -> str:
    """Формирует текст вопроса с вариантами"""
    lines = [
        f"❓ Вопрос {question_num}/{total}",
        "",
        f"📌 {question['question_text']}",
        "",
        f"1️⃣ {question['option1']}",
        f"2️⃣ {question['option2']}",
        f"3️⃣ {question['option3']}",
        f"4️⃣ {question['option4']}",
        "",
        "⏱️ Выберите номер ответа:"
    ]
    return "\n".join(lines)

def exam_recommendation(percent: float, is_final: bool = False) -> str:
    """Рекомендация по результатам экзамена"""
    if is_final:
        if percent >= 90:
            return "🌟 Отлично! Вы готовы к экзамену!"
        elif percent >= 75:
            return "👍 Хорошо, но стоит повторить сложные темы"
        elif percent >= 60:
            return "📚 Удовлетворительно, нужно больше практики"
        else:
            return "❌ К сожалению, вы не сдали. Попробуйте ещё раз"
    else:
        if percent >= 80:
            return "🎉 Отличный результат! Можно переходить к итоговому"
        elif percent >= 60:
            return "📖 Хороший результат, но есть над чем работать"
        else:
            return "📝 Результат низкий. Повторите теорию"

def get_teacher_by_subgroup(subgroup: int) -> str:
    """Возвращает преподавателя по подгруппе"""
    return TEACHERS.get(subgroup, "👤 Неизвестный преподаватель")

def format_profile_text(user: Dict, stats: Tuple[int, int, float], teacher: str) -> str:
    """Форматирует текст личного кабинета"""
    total, correct, percent = stats
    lines = [
        "👤 **Личный кабинет**",
        "",
        f"👤 Имя: {user['first_name']}",
        f"👤 Фамилия: {user['last_name']}",
        f"📚 Группа: {user['group_number']}",
        f"🔢 Подгруппа: {user['subgroup']}",
        f"{teacher}",
        "",
        "📊 **Статистика:**",
        f"📋 Всего ответов: {total}",
        f"✅ Правильных: {correct}",
        f"📈 Успеваемость: {percent:.1f}%"
    ]
    return "\n".join(lines)

def get_time_limit(test_type: str, topic_type: str = None) -> int:
    """Возвращает лимит времени в минутах"""
    if test_type == "topic":
        return 10  # 10 минут на тему
    elif test_type == "practice_exam":
        return 20  # 20 минут на пробный
    elif test_type == "final_exam":
        return 30  # 30 минут на итоговый
    return 15  # по умолчанию

async def timer_task(user_id: int, minutes: int, callback_func):
    """Асинхронный таймер"""
    await asyncio.sleep(minutes * 60)
    await callback_func(user_id)