from aiogram.fsm.state import State, StatesGroup


class BindingStates(StatesGroup):
    waiting_chat_id = State()
    confirming = State()


class TemplateStates(StatesGroup):
    waiting_text = State()


class ButtonStates(StatesGroup):
    waiting_definition = State()


class ExportStates(StatesGroup):
    waiting_custom_range = State()
    waiting_format = State()


class AdministratorStates(StatesGroup):
    waiting_user_id = State()
