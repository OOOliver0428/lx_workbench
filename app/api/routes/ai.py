from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.dependencies import (
    get_current_user,
    get_db,
    require_admin,
    require_admin_read,
    require_csrf,
)
from app.models import AIProviderConfig, User
from app.schemas import (
    AIChatOut,
    AIChatRequest,
    AIConfigurationOut,
    AIConfigurationSaveRequest,
    AIConfigurationTestOut,
    AIConfigurationTestRequest,
    AIProviderOptionOut,
    AIStatusOut,
)
from app.services import ai as ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AIStatusOut)
def ai_status(
    request: Request,
    _actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AIStatusOut:
    return ai_service.get_status(db, request.app.state.settings)


@router.get("/providers", response_model=list[AIProviderOptionOut])
def ai_providers(
    _actor: User = Depends(require_admin_read),
) -> list[AIProviderOptionOut]:
    return ai_service.list_providers()


@router.get("/configuration", response_model=AIConfigurationOut)
def ai_configuration(
    request: Request,
    _actor: User = Depends(require_admin_read),
    db: Session = Depends(get_db),
) -> AIConfigurationOut:
    return ai_service.get_configuration(db, request.app.state.settings)


@router.post("/configuration/test", response_model=AIConfigurationTestOut)
def test_ai_configuration(
    payload: AIConfigurationTestRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AIConfigurationTestOut:
    result = ai_service.test_configuration(request.app.state.settings, payload)
    record_audit(
        db,
        actor=actor,
        action="ai.configuration.test",
        entity_type="ai_configuration",
        entity_id=None,
        detail={
            "provider": result.provider,
            "access_mode": result.access_mode,
            "model": payload.model,
            "usage": result.usage,
        },
    )
    return result


@router.put("/configuration", response_model=AIConfigurationOut)
def save_ai_configuration(
    payload: AIConfigurationSaveRequest,
    request: Request,
    actor: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AIConfigurationOut:
    previous = db.get(AIProviderConfig, ai_service.PRIMARY_CONFIG_ID)
    before_data = (
        {
            "provider": previous.provider,
            "access_mode": previous.access_mode,
            "model": previous.model,
            "revision": previous.revision,
        }
        if previous
        else None
    )
    saved = ai_service.save_configuration(
        db,
        request.app.state.settings,
        payload,
        actor,
    )
    record_audit(
        db,
        actor=actor,
        action="ai.configuration.save",
        entity_type="ai_configuration",
        entity_id=saved.id,
        before_data=before_data,
        after_data={
            "provider": saved.provider,
            "access_mode": saved.access_mode,
            "model": saved.model,
            "revision": saved.revision,
        },
    )
    return ai_service.configuration_out(saved, request.app.state.settings)


@router.post("/chat", response_model=AIChatOut)
def ai_chat(
    payload: AIChatRequest,
    request: Request,
    actor: User = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> AIChatOut:
    result = ai_service.chat(db, request.app.state.settings, payload, actor)
    record_audit(
        db,
        actor=actor,
        action="ai.chat",
        entity_type="ai",
        entity_id=None,
        detail={"model": result.model, "usage": result.usage},
    )
    return result
