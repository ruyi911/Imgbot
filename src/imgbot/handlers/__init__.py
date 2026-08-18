from imgbot.handlers.admin import router as admin_router
from imgbot.handlers.assistant import router as assistant_router
from imgbot.handlers.group import router as group_router
from imgbot.handlers.utility import router as utility_router

__all__ = [
    "admin_router",
    "assistant_router",
    "group_router",
    "utility_router",
]
