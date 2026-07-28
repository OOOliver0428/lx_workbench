from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError, ConflictError
from app.models import AIProviderConfig, User
from app.schemas import (
    AIChatOut,
    AIChatRequest,
    AIConfigurationOut,
    AIConfigurationSaveRequest,
    AIConfigurationTestOut,
    AIConfigurationTestRequest,
    AIProviderAccessModeOut,
    AIProviderOptionOut,
    AIStatusOut,
)
from app.services.ai_context import build_chat_context

SYSTEM_PROMPT = """你是团队协作工作台中的通用 AI 助手。
你只能依据系统提供的当前用户业务上下文回答项目、任务和工作问题。
不要编造不存在的事实；信息不足时明确说明缺少什么。
你的输出仅供用户阅览，不得声称已经创建、修改、提交或删除系统中的任何数据。
使用准确、简洁、可执行的中文。"""
PRIMARY_CONFIG_ID = "primary"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessModeDefinition:
    id: str
    name: str
    description: str
    base_url: str
    protocol: str
    default_model: str
    models: tuple[str, ...]
    docs_url: str


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    default_access_mode: str
    access_modes: tuple[AccessModeDefinition, ...]
    api_key_url: str


@dataclass(frozen=True)
class ResolvedAIConfig:
    provider: ProviderDefinition
    access_mode: AccessModeDefinition
    model: str
    api_key: str
    source: str


PROVIDERS: dict[str, ProviderDefinition] = {
    "deepseek": ProviderDefinition(
        id="deepseek",
        name="DeepSeek",
        default_access_mode="standard",
        access_modes=(
            AccessModeDefinition(
                id="standard",
                name="标准 API",
                description="使用 DeepSeek 开放平台按量计费 API Key",
                base_url="https://api.deepseek.com",
                protocol="openai",
                default_model="deepseek-v4-flash",
                models=("deepseek-v4-flash", "deepseek-v4-pro"),
                docs_url="https://api-docs.deepseek.com/",
            ),
        ),
        api_key_url="https://platform.deepseek.com/",
    ),
    "glm": ProviderDefinition(
        id="glm",
        name="智谱 GLM",
        default_access_mode="standard",
        access_modes=(
            AccessModeDefinition(
                id="standard",
                name="标准 API",
                description="使用智谱开放平台按量计费 API Key",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                protocol="openai",
                default_model="glm-5.2",
                models=("glm-5.2", "glm-5.1", "glm-5", "glm-4.7", "glm-4.5-air"),
                docs_url="https://docs.bigmodel.cn/cn/guide/develop/openai/introduction",
            ),
        ),
        api_key_url="https://open.bigmodel.cn/",
    ),
    "kimi": ProviderDefinition(
        id="kimi",
        name="Kimi",
        default_access_mode="standard",
        access_modes=(
            AccessModeDefinition(
                id="standard",
                name="标准 API",
                description="使用 Kimi 开放平台按量计费 API Key",
                base_url="https://api.moonshot.cn/v1",
                protocol="openai",
                default_model="kimi-k2.6",
                models=("kimi-k2.6", "kimi-k2.5", "kimi-k2-thinking"),
                docs_url="https://platform.kimi.com/docs/api/overview",
            ),
        ),
        api_key_url="https://platform.moonshot.cn/",
    ),
    "minimax": ProviderDefinition(
        id="minimax",
        name="MiniMax",
        default_access_mode="token_plan",
        access_modes=(
            AccessModeDefinition(
                id="token_plan",
                name="Token Plan",
                description="订阅套餐或 Credits，使用 sk-cp- 开头的 Token Plan Key",
                base_url="https://api.minimaxi.com/anthropic",
                protocol="anthropic",
                default_model="MiniMax-M2.7",
                models=(
                    "MiniMax-M2.7",
                    "MiniMax-M2.7-highspeed",
                    "MiniMax-M2.5",
                    "MiniMax-M2.5-highspeed",
                    "MiniMax-M2.1",
                    "MiniMax-M2.1-highspeed",
                    "MiniMax-M2",
                ),
                docs_url="https://platform.minimaxi.com/docs/token-plan/quickstart",
            ),
            AccessModeDefinition(
                id="pay_as_you_go",
                name="按量计费",
                description="使用开放平台余额与普通 API Key，按实际 Token 扣费",
                base_url="https://api.minimaxi.com/v1",
                protocol="openai",
                default_model="MiniMax-M2.7",
                models=(
                    "MiniMax-M2.7",
                    "MiniMax-M2.7-highspeed",
                    "MiniMax-M2.5",
                    "MiniMax-M2.5-highspeed",
                    "MiniMax-M2.1",
                    "MiniMax-M2.1-highspeed",
                    "MiniMax-M2",
                ),
                docs_url="https://platform.minimaxi.com/docs/api-reference/api-overview",
            ),
        ),
        api_key_url="https://platform.minimaxi.com/",
    ),
}


def list_providers() -> list[AIProviderOptionOut]:
    return [
        AIProviderOptionOut(
            id=provider.id,
            name=provider.name,
            default_access_mode=provider.default_access_mode,
            access_modes=[
                AIProviderAccessModeOut(
                    id=mode.id,
                    name=mode.name,
                    description=mode.description,
                    base_url=mode.base_url,
                    protocol=mode.protocol,
                    default_model=mode.default_model,
                    models=list(mode.models),
                    docs_url=mode.docs_url,
                )
                for mode in provider.access_modes
            ],
            api_key_url=provider.api_key_url,
        )
        for provider in PROVIDERS.values()
    ]


def get_configuration(db: Session, settings: Settings) -> AIConfigurationOut:
    stored = db.get(AIProviderConfig, PRIMARY_CONFIG_ID)
    if stored:
        provider = PROVIDERS.get(stored.provider)
        access_mode = (
            _find_access_mode(provider, stored.access_mode) if provider else None
        )
        encryption_ready = _encryption_ready(settings)
        return AIConfigurationOut(
            configured=encryption_ready,
            source="database",
            provider=stored.provider,
            provider_name=provider.name if provider else stored.provider,
            access_mode=stored.access_mode,
            access_mode_name=(
                access_mode.name if access_mode else stored.access_mode
            ),
            protocol=access_mode.protocol if access_mode else None,
            base_url=stored.base_url,
            model=stored.model,
            api_key_hint=stored.api_key_hint,
            tested_at=stored.tested_at,
            updated_at=stored.updated_at,
            revision=stored.revision,
            encryption_ready=encryption_ready,
        )

    if settings.minimax_api_key:
        provider = PROVIDERS["minimax"]
        access_mode = _legacy_minimax_access_mode(settings)
        return AIConfigurationOut(
            configured=True,
            source="environment",
            provider="minimax",
            provider_name=provider.name,
            access_mode=access_mode.id,
            access_mode_name=access_mode.name,
            protocol=access_mode.protocol,
            base_url=access_mode.base_url,
            model=settings.minimax_model,
            api_key_hint=_key_hint(settings.minimax_api_key),
            tested_at=None,
            updated_at=None,
            revision=None,
            encryption_ready=_encryption_ready(settings),
        )

    return AIConfigurationOut(
        configured=False,
        source="none",
        provider=None,
        provider_name=None,
        access_mode=None,
        access_mode_name=None,
        protocol=None,
        base_url=None,
        model=None,
        api_key_hint=None,
        tested_at=None,
        updated_at=None,
        revision=None,
        encryption_ready=_encryption_ready(settings),
    )


def get_status(db: Session, settings: Settings) -> AIStatusOut:
    configuration = get_configuration(db, settings)
    return AIStatusOut(
        configured=configuration.configured,
        provider=configuration.provider_name or "未配置",
        model=configuration.model or "",
    )


def test_configuration(
    settings: Settings,
    payload: AIConfigurationTestRequest,
) -> AIConfigurationTestOut:
    _fernet(settings)
    provider, access_mode = _validate_selection(
        payload.provider,
        payload.access_mode,
        payload.model,
    )
    api_key = _validated_api_key(
        payload.api_key.get_secret_value(),
        provider=provider,
        access_mode=access_mode,
    )
    result = _chat_completion(
        settings=settings,
        access_mode=access_mode,
        model=payload.model,
        api_key=api_key,
        messages=[{"role": "user", "content": "这是连接测试，请只回复“连接成功”。"}],
        max_tokens=128,
    )
    tested_at = datetime.now(UTC)
    expires_at = tested_at + timedelta(seconds=settings.llm_test_token_ttl_seconds)
    verification_token = _create_verification_token(
        settings,
        provider=provider.id,
        access_mode=access_mode.id,
        model=payload.model,
        api_key=api_key,
        tested_at=tested_at,
    )
    return AIConfigurationTestOut(
        success=True,
        provider=provider.id,
        access_mode=access_mode.id,
        model=payload.model,
        message="连接测试成功，可以保存为系统配置。",
        usage=result.usage,
        verification_token=verification_token,
        expires_at=expires_at,
    )


def save_configuration(
    db: Session,
    settings: Settings,
    payload: AIConfigurationSaveRequest,
    actor: User,
) -> AIProviderConfig:
    provider, access_mode = _validate_selection(
        payload.provider,
        payload.access_mode,
        payload.model,
    )
    api_key = _validated_api_key(
        payload.api_key.get_secret_value(),
        provider=provider,
        access_mode=access_mode,
    )
    tested_at = _verify_test_token(
        settings,
        token=payload.verification_token,
        provider=provider.id,
        access_mode=access_mode.id,
        model=payload.model,
        api_key=api_key,
    )
    current = db.get(AIProviderConfig, PRIMARY_CONFIG_ID)
    if current:
        if payload.revision != current.revision:
            raise ConflictError(
                "REVISION_CONFLICT",
                "大模型配置已被其他管理员修改，请刷新后重试",
                {
                    "expected_revision": payload.revision,
                    "current_revision": current.revision,
                },
            )
        current.provider = provider.id
        current.access_mode = access_mode.id
        current.base_url = access_mode.base_url
        current.model = payload.model
        current.encrypted_api_key = _encrypt_api_key(settings, api_key)
        current.api_key_hint = _key_hint(api_key)
        current.tested_at = tested_at
        current.tested_by = actor.id
        current.updated_by = actor.id
        current.revision += 1
        db.flush()
        return current

    if payload.revision is not None:
        raise ConflictError(
            "REVISION_CONFLICT",
            "大模型配置状态已经变化，请刷新后重试",
            {"expected_revision": payload.revision, "current_revision": None},
        )
    current = AIProviderConfig(
        id=PRIMARY_CONFIG_ID,
        provider=provider.id,
        access_mode=access_mode.id,
        base_url=access_mode.base_url,
        model=payload.model,
        encrypted_api_key=_encrypt_api_key(settings, api_key),
        api_key_hint=_key_hint(api_key),
        tested_at=tested_at,
        tested_by=actor.id,
        updated_by=actor.id,
    )
    db.add(current)
    db.flush()
    return current


def configuration_out(config: AIProviderConfig, settings: Settings) -> AIConfigurationOut:
    provider = PROVIDERS.get(config.provider)
    access_mode = _find_access_mode(provider, config.access_mode) if provider else None
    return AIConfigurationOut(
        configured=_encryption_ready(settings),
        source="database",
        provider=config.provider,
        provider_name=provider.name if provider else config.provider,
        access_mode=config.access_mode,
        access_mode_name=access_mode.name if access_mode else config.access_mode,
        protocol=access_mode.protocol if access_mode else None,
        base_url=config.base_url,
        model=config.model,
        api_key_hint=config.api_key_hint,
        tested_at=config.tested_at,
        updated_at=config.updated_at,
        revision=config.revision,
        encryption_ready=_encryption_ready(settings),
    )


def chat(
    db: Session,
    settings: Settings,
    payload: AIChatRequest,
    actor: User,
) -> AIChatOut:
    context = build_chat_context(db, actor)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"以下业务上下文由系统按当前用户权限生成，仅作为回答依据：\n{context}",
        },
        {"role": "user", "content": payload.prompt},
    ]
    return complete(
        db,
        settings,
        messages=messages,
        max_tokens=2048,
    )


def complete(
    db: Session,
    settings: Settings,
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> AIChatOut:
    resolved = _resolve_configuration(db, settings)
    return _chat_completion(
        settings=settings,
        access_mode=resolved.access_mode,
        model=resolved.model,
        api_key=resolved.api_key,
        messages=messages,
        max_tokens=max_tokens,
    )


def _resolve_configuration(db: Session, settings: Settings) -> ResolvedAIConfig:
    stored = db.get(AIProviderConfig, PRIMARY_CONFIG_ID)
    if stored:
        provider = PROVIDERS.get(stored.provider)
        if not provider:
            raise AppError(
                "AI_PROVIDER_UNSUPPORTED",
                "当前大模型供应商已不受支持，请由管理员重新配置",
                status_code=503,
            )
        access_mode = _find_access_mode(provider, stored.access_mode)
        if not access_mode:
            raise AppError(
                "AI_ACCESS_MODE_UNSUPPORTED",
                "当前大模型接入方式已不受支持，请由管理员重新配置",
                status_code=503,
            )
        return ResolvedAIConfig(
            provider=provider,
            access_mode=access_mode,
            model=stored.model,
            api_key=_decrypt_api_key(settings, stored.encrypted_api_key),
            source="database",
        )
    if settings.minimax_api_key:
        provider = PROVIDERS["minimax"]
        access_mode = _legacy_minimax_access_mode(settings)
        return ResolvedAIConfig(
            provider=provider,
            access_mode=access_mode,
            model=settings.minimax_model,
            api_key=_validated_api_key(
                settings.minimax_api_key,
                provider=provider,
                access_mode=access_mode,
            ),
            source="environment",
        )
    raise AppError("AI_NOT_CONFIGURED", "大模型服务尚未配置", status_code=503)


def _chat_completion(
    *,
    settings: Settings,
    access_mode: AccessModeDefinition,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> AIChatOut:
    if access_mode.protocol == "anthropic":
        return _anthropic_chat_completion(
            settings=settings,
            access_mode=access_mode,
            model=model,
            api_key=api_key,
            messages=messages,
            max_tokens=max_tokens,
        )
    return _openai_chat_completion(
        settings=settings,
        access_mode=access_mode,
        model=model,
        api_key=api_key,
        messages=messages,
        max_tokens=max_tokens,
    )


def _openai_chat_completion(
    *,
    settings: Settings,
    access_mode: AccessModeDefinition,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> AIChatOut:
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                f"{access_mode.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                },
            )
    except httpx.RequestError as error:
        logger.warning(
            "OpenAI-compatible provider request failed: %s",
            error,
        )
        raise AppError(
            "AI_PROVIDER_UNAVAILABLE",
            "暂时无法连接大模型服务",
            status_code=502,
        ) from error

    _raise_for_provider_status(response)

    try:
        data: dict[str, Any] = response.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise AppError(
            "AI_INVALID_RESPONSE",
            "大模型服务返回了无法识别的结果",
            status_code=502,
        ) from error

    answer = _clean_answer(str(content))
    if not answer:
        raise AppError(
            "AI_EMPTY_RESPONSE",
            "大模型没有返回有效内容",
            status_code=502,
        )
    raw_usage = data.get("usage") or {}
    usage = {
        key: int(raw_usage.get(key) or 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return AIChatOut(
        answer=answer,
        model=str(data.get("model") or model),
        usage=usage,
    )


def _anthropic_chat_completion(
    *,
    settings: Settings,
    access_mode: AccessModeDefinition,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> AIChatOut:
    system = "\n\n".join(
        message["content"] for message in messages if message["role"] == "system"
    )
    conversation = [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            response = client.post(
                f"{access_mode.base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "system": system,
                    "messages": conversation,
                    "max_tokens": max_tokens,
                },
            )
    except httpx.RequestError as error:
        logger.warning(
            "Anthropic-compatible provider request failed: %s",
            error,
        )
        raise AppError(
            "AI_PROVIDER_UNAVAILABLE",
            "暂时无法连接大模型服务",
            status_code=502,
        ) from error

    _raise_for_provider_status(response)

    try:
        data: dict[str, Any] = response.json()
        content_blocks = data["content"]
        text_parts = [
            str(block["text"])
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise AppError(
            "AI_INVALID_RESPONSE",
            "大模型服务返回了无法识别的结果",
            status_code=502,
        ) from error

    answer = _clean_answer("\n".join(text_parts))
    if not answer:
        raise AppError(
            "AI_EMPTY_RESPONSE",
            "大模型没有返回有效内容",
            status_code=502,
        )
    raw_usage = data.get("usage") or {}
    input_tokens = int(raw_usage.get("input_tokens") or 0)
    output_tokens = int(raw_usage.get("output_tokens") or 0)
    return AIChatOut(
        answer=answer,
        model=str(data.get("model") or model),
        usage={
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )


def _raise_for_provider_status(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise AppError(
            "AI_AUTHENTICATION_FAILED",
            "API Key 无效、已过期或无权使用当前模型",
            status_code=502,
        )
    if response.status_code == 429:
        raise AppError(
            "AI_RATE_LIMITED",
            "大模型额度或频率限制暂时不可用，请稍后重试",
            status_code=429,
        )
    if response.is_error:
        raise AppError(
            "AI_PROVIDER_ERROR",
            "大模型服务拒绝了本次请求，请检查模型和账户额度",
            status_code=502,
            details={"provider_status": response.status_code},
        )


def _clean_answer(content: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()


def _find_access_mode(
    provider: ProviderDefinition | None,
    access_mode_id: str,
) -> AccessModeDefinition | None:
    if not provider:
        return None
    return next(
        (mode for mode in provider.access_modes if mode.id == access_mode_id),
        None,
    )


def _validate_selection(
    provider_id: str,
    access_mode_id: str,
    model: str,
) -> tuple[ProviderDefinition, AccessModeDefinition]:
    provider = PROVIDERS.get(provider_id)
    if not provider:
        raise AppError("AI_PROVIDER_UNSUPPORTED", "不支持的大模型供应商", status_code=400)
    access_mode = _find_access_mode(provider, access_mode_id)
    if not access_mode:
        raise AppError(
            "AI_ACCESS_MODE_UNSUPPORTED",
            "当前厂商不支持所选接入方式",
            status_code=400,
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}", model):
        raise AppError("AI_MODEL_INVALID", "模型 ID 格式不正确", status_code=400)
    return provider, access_mode


def _validated_api_key(
    value: str,
    *,
    provider: ProviderDefinition,
    access_mode: AccessModeDefinition,
) -> str:
    api_key = value.strip()
    if len(api_key) < 8 or len(api_key) > 2048:
        raise AppError("AI_API_KEY_INVALID", "API Key 格式不正确", status_code=400)
    is_token_plan_key = api_key.startswith("sk-cp-")
    if provider.id == "minimax" and access_mode.id == "token_plan":
        if not is_token_plan_key:
            raise AppError(
                "AI_API_KEY_MODE_MISMATCH",
                "MiniMax Token Plan 必须使用 sk-cp- 开头的 Token Plan Key",
                status_code=400,
            )
    elif provider.id == "minimax" and is_token_plan_key:
        raise AppError(
            "AI_API_KEY_MODE_MISMATCH",
            "该 Key 属于 MiniMax Token Plan，请将接入方式切换为 Token Plan",
            status_code=400,
        )
    return api_key


def _legacy_minimax_access_mode(settings: Settings) -> AccessModeDefinition:
    provider = PROVIDERS["minimax"]
    configured_mode = settings.minimax_access_mode.strip().casefold()
    if configured_mode == "auto":
        configured_mode = (
            "token_plan"
            if settings.minimax_api_key.strip().startswith("sk-cp-")
            else "pay_as_you_go"
        )
    access_mode = _find_access_mode(provider, configured_mode)
    if not access_mode:
        raise AppError(
            "AI_ACCESS_MODE_UNSUPPORTED",
            "服务器中的 MiniMax 接入方式配置不正确",
            status_code=503,
        )
    return access_mode


def _key_hint(api_key: str) -> str:
    return f"••••{api_key[-4:]}"


def _encryption_ready(settings: Settings) -> bool:
    return len(settings.llm_config_secret) >= 32


def _fernet(settings: Settings) -> Fernet:
    if not _encryption_ready(settings):
        raise AppError(
            "AI_CONFIG_SECRET_MISSING",
            "服务器尚未配置大模型密钥加密主密钥",
            status_code=503,
        )
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.llm_config_secret.encode("utf-8")).digest()
    )
    return Fernet(key)


def _encrypt_api_key(settings: Settings, api_key: str) -> str:
    return _fernet(settings).encrypt(api_key.encode("utf-8")).decode("ascii")


def _decrypt_api_key(settings: Settings, encrypted_api_key: str) -> str:
    try:
        return _fernet(settings).decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise AppError(
            "AI_CONFIG_DECRYPTION_FAILED",
            "已保存的大模型密钥无法解密，请由管理员重新配置",
            status_code=503,
        ) from error


def _create_verification_token(
    settings: Settings,
    *,
    provider: str,
    access_mode: str,
    model: str,
    api_key: str,
    tested_at: datetime,
) -> str:
    body = json.dumps(
        {
            "provider": provider,
            "access_mode": access_mode,
            "model": model,
            "api_key_sha256": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
            "tested_at": tested_at.isoformat(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _fernet(settings).encrypt(body).decode("ascii")


def _verify_test_token(
    settings: Settings,
    *,
    token: str,
    provider: str,
    access_mode: str,
    model: str,
    api_key: str,
) -> datetime:
    try:
        body = _fernet(settings).decrypt(
            token.encode("ascii"),
            ttl=settings.llm_test_token_ttl_seconds,
        )
        data = json.loads(body.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AppError(
            "AI_TEST_VERIFICATION_EXPIRED",
            "连接测试凭据无效或已过期，请重新测试",
            status_code=400,
        ) from error
    expected_key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    if (
        data.get("provider") != provider
        or data.get("access_mode") != access_mode
        or data.get("model") != model
        or data.get("api_key_sha256") != expected_key_hash
    ):
        raise AppError(
            "AI_TEST_VERIFICATION_MISMATCH",
            "厂商、接入方式、模型或 API Key 已发生变化，请重新测试",
            status_code=400,
        )
    try:
        tested_at = datetime.fromisoformat(str(data["tested_at"]))
    except (KeyError, ValueError) as error:
        raise AppError(
            "AI_TEST_VERIFICATION_INVALID",
            "连接测试凭据无法识别，请重新测试",
            status_code=400,
        ) from error
    return tested_at if tested_at.tzinfo else tested_at.replace(tzinfo=UTC)
