from aiogram.fsm.state import State, StatesGroup

class RegistrationStates(StatesGroup):
    waiting_for_first_name = State()
    waiting_for_last_name = State()
    waiting_for_group_number = State()
    waiting_for_subgroup = State()
    waiting_for_password = State()

class LoginStates(StatesGroup):
    waiting_for_password = State()

class TopicQuizStates(StatesGroup):
    in_topic_quiz = State()

class PracticeExamStates(StatesGroup):
    in_practice_exam = State()

class FinalExamStates(StatesGroup):
    in_final_exam = State()

class ProfileStates(StatesGroup):
    waiting_for_new_password = State()