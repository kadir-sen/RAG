"""FastAPI Depends() wrappers for existing src/ singletons."""

from fastapi import Depends

from src.router import get_router, QueryRouter
from src.data_analyzer_sql import get_data_analyzer, DataAnalyzerSQL
from src.conversation_store import ConversationStore
from backend.core.security import UserContext, get_current_user
from backend.core.projects import ProjectContext, get_current_project


def get_query_router() -> QueryRouter:
    return get_router()


def get_sql_analyzer() -> DataAnalyzerSQL:
    return get_data_analyzer()


def get_conversation_store(
    user: UserContext = Depends(get_current_user),
    project: ProjectContext = Depends(get_current_project),
) -> ConversationStore:
    """Per-user conversation store. The username comes from the auth token."""
    return ConversationStore(user.username, project.project_id)
