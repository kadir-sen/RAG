"""FastAPI Depends() wrappers for existing src/ singletons."""

from src.router import get_router, QueryRouter
from src.data_analyzer_sql import get_data_analyzer, DataAnalyzerSQL
from src.conversation_store import ConversationStore


def get_query_router() -> QueryRouter:
    return get_router()


def get_sql_analyzer() -> DataAnalyzerSQL:
    return get_data_analyzer()


def get_conversation_store(username: str = "default") -> ConversationStore:
    return ConversationStore(username)
