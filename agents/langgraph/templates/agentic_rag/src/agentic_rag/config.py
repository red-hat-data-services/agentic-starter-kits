import base64
from dataclasses import dataclass
from os import getenv


def _decode_template(name: str) -> str:
    """Decode a base64-encoded multiline template from the environment."""
    encoded = getenv(name, "")
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(
            f"{name} must contain valid base64-encoded UTF-8 text"
        ) from exc


def get_chat_base_url() -> str | None:
    """Return the shared OpenAI-compatible MaaS endpoint.

    MaaS serves foundation and embedding models through the same ``/v1``
    endpoint. The model identifier belongs in the request body, so it must not
    be rewritten into a model-specific URL.
    """
    explicit_url = getenv("CHAT_BASE_URL", "").strip()
    if explicit_url:
        return explicit_url

    maas_url = getenv("MAAS_BASE_URL", "").strip().rstrip("/")
    if not maas_url:
        return getenv("BASE_URL") or None
    return maas_url


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for the optimized RAG pattern."""

    model_id: str
    temperature: float
    max_completion_tokens: int
    system_message: str
    user_message_template: str
    context_template: str
    language_name: str

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load and validate agent configuration from environment variables."""
        try:
            temperature = float(getenv("TEMPERATURE", "0.0"))
            max_completion_tokens = int(getenv("MAX_COMPLETION_TOKENS", "1024"))
        except ValueError as exc:
            raise ValueError(
                "TEMPERATURE and MAX_COMPLETION_TOKENS must be numeric"
            ) from exc

        return cls(
            model_id=getenv("MODEL_ID", ""),
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            system_message=_decode_template("SYSTEM_MESSAGE_B64")
            or getenv("SYSTEM_MESSAGE", ""),
            user_message_template=_decode_template("USER_MESSAGE_B64")
            or "Context:\n{reference_documents}\n\nQuestion: {question}",
            context_template=_decode_template("CONTEXT_TEMPLATE_B64") or "{document}",
            language_name=getenv("LANGUAGE_NAME", "auto"),
        )
