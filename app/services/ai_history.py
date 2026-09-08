from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import AIChatMessage

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


def _snippet(content: str, max_chars: int) -> str:
    return content if len(content) <= max_chars else content[:max_chars]


def recent_messages(
    db: Session,
    user_id: str,
    *,
    max_messages: int,
    max_chars: int,
) -> list[AIChatMessage]:
    """Return the newest messages within the message and character budgets.

    Walks from the newest message backwards and drops the oldest rows first;
    the current turn is never part of this selection (it is appended after the
    reply is produced).
    """

    rows = list(
        db.scalars(
            select(AIChatMessage)
            .where(AIChatMessage.user_id == user_id)
            .order_by(AIChatMessage.seq.asc())
        ).all()
    )
    kept: list[AIChatMessage] = []
    total_chars = 0
    for row in reversed(rows):
        if len(kept) >= max_messages or total_chars + len(row.content) > max_chars:
            break
        kept.append(row)
        total_chars += len(row.content)
    kept.reverse()
    return kept


def clear_history(db: Session, user_id: str) -> int:
    result = db.execute(
        delete(AIChatMessage).where(AIChatMessage.user_id == user_id)
    )
    return result.rowcount or 0


def append_turn(
    db: Session,
    user_id: str,
    *,
    user_prompt: str,
    assistant_answer: str,
    message_max_chars: int,
    max_messages: int,
    max_chars: int,
) -> None:
    """Persist one completed turn and trim the oldest rows to the budgets."""

    max_seq = db.scalar(
        select(func.max(AIChatMessage.seq)).where(
            AIChatMessage.user_id == user_id
        )
    )
    next_seq = (max_seq + 1) if max_seq is not None else 1
    db.add(
        AIChatMessage(
            user_id=user_id,
            seq=next_seq,
            role=ROLE_USER,
            content=_snippet(user_prompt, message_max_chars),
        )
    )
    db.add(
        AIChatMessage(
            user_id=user_id,
            seq=next_seq + 1,
            role=ROLE_ASSISTANT,
            content=_snippet(assistant_answer, message_max_chars),
        )
    )
    db.flush()

    rows = list(
        db.scalars(
            select(AIChatMessage)
            .where(AIChatMessage.user_id == user_id)
            .order_by(AIChatMessage.seq.desc())
        ).all()
    )
    kept_chars = 0
    cutoff_seq: int | None = None
    for kept_count, row in enumerate(rows):
        if kept_count >= max_messages or kept_chars + len(row.content) > max_chars:
            cutoff_seq = row.seq
            break
        kept_chars += len(row.content)
    if cutoff_seq is not None:
        db.execute(
            delete(AIChatMessage).where(
                AIChatMessage.user_id == user_id,
                AIChatMessage.seq <= cutoff_seq,
            )
        )
    db.flush()
