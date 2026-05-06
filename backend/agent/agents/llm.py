from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from backend.agent.core.logging import get_logger
from backend.agent.settings import Settings, get_settings

log = get_logger(__name__)

_PRIMARY_MODEL = "gpt-4o-mini"
_FALLBACK_MODEL = "llama3-8b-8192"


def get_primary_llm(settings: Settings | None = None) -> BaseChatModel:
    s = settings or get_settings()
    return ChatOpenAI(
        model=_PRIMARY_MODEL,
        api_key=s.openai_api_key.get_secret_value(),
        temperature=0.3,
        max_tokens=512,
    )


def get_fallback_llm(settings: Settings | None = None) -> BaseChatModel | None:
    """Returns None if GROQ_API_KEY is not set."""
    s = settings or get_settings()
    if not s.groq_api_key:
        return None
    return ChatGroq(
        model=_FALLBACK_MODEL,
        api_key=s.groq_api_key.get_secret_value(),
        temperature=0.3,
        max_tokens=512,
    )


async def invoke_with_fallback(prompt: str, settings: Settings | None = None) -> str:
    """Try primary → Groq fallback → template string. Never raises.

    Fallback chain from brainstorm Decision #48:
      GPT-4o-mini → Groq Llama3-8b → template text
    """
    s = settings or get_settings()

    try:
        response = await get_primary_llm(s).ainvoke(prompt)
        return str(response.content)
    except Exception as exc:
        log.warning("primary_llm_failed", error=str(exc))

    fallback = get_fallback_llm(s)
    if fallback:
        try:
            response = await fallback.ainvoke(prompt)
            return str(response.content)
        except Exception as exc:
            log.warning("fallback_llm_failed", error=str(exc))

    log.error("all_llms_failed_using_template")
    return f"[automated] {prompt[:200]}"
