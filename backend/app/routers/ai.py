"""
AI Audit Chat — the real LLM layer behind the chat drawer's text Q&A.

Design principle (carried over from the deterministic ASK engine on the
frontend): the model is NEVER allowed to invent a number, name, date, or ID.
It only ever explains / phrases / summarizes facts the frontend already
computed from the tenant's own real data (drivers, statements, audit runs,
policy) and sent along as `context`. The system prompt enforces this, and if
the question can't be answered from context, the model is told to say so
instead of guessing.

This keeps the "zero fabrication" rule intact even once a real LLM is in the
loop — the LLM is a language layer on top of already-computed truth, not a
second source of truth.

Two providers, one code path: Groq is OpenAI-API-compatible, so both are
called through the same `openai` client — only `base_url`, the API key, and
the model name differ. Either or both may be configured; if the preferred
provider's call fails for any reason, the other configured one is tried
automatically before giving up, so a single provider outage/rate-limit
doesn't take the whole chat down.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import models, auth
from app.config import settings

router = APIRouter(prefix="/api/ai", tags=["ai"])

SYSTEM_PROMPT = (
    "You are Jeff, an AI assistant inside a trucking-company accounting/audit platform "
    "called Jeff Accountant. You must answer ONLY using the facts given to you below under "
    "CONTEXT — real, already-computed data pulled from this company's own records "
    "(statements, drivers, audit findings, accounting policy). "
    "Never invent a number, amount, date, driver name, statement ID, or work order ID that "
    "is not present in CONTEXT. If the question cannot be answered from CONTEXT, say plainly "
    "that you don't have that information in the records rather than guessing or estimating. "
    "If CONTEXT includes a file the user attached in this chat, you may read, summarize, and "
    "answer questions about its contents — but that file is for discussion only. Never say or "
    "imply that any driver, statement, or other record has been created, saved, imported, or "
    "approved just because it was discussed here; creating real records only ever happens "
    "through the app's Upload Center with an admin's explicit approval, not through this chat. "
    "Reply in the same language the user writes in (Uzbek or English, matching their script). "
    "Be concise, professional, and numbers-first."
)


class ChatRequest(BaseModel):
    message: str
    context: str = ""


def _providers():
    """Returns an ordered list of (label, client_kwargs, model) for every
    provider that has a key configured, in the order they should be tried.
    AI_PROVIDER forces one; otherwise Groq is preferred (it's free)."""
    groq_key = settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY")
    openai_key = settings.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
    groq = ("groq", dict(api_key=groq_key, base_url="https://api.groq.com/openai/v1"), settings.GROQ_MODEL) if groq_key else None
    openai_ = ("openai", dict(api_key=openai_key), settings.OPENAI_MODEL) if openai_key else None

    forced = (settings.AI_PROVIDER or "").strip().lower()
    if forced == "groq":
        return [p for p in [groq] if p]
    if forced == "openai":
        return [p for p in [openai_] if p]
    return [p for p in [groq, openai_] if p]


@router.post("/chat")
def ai_chat(req: ChatRequest, user: models.User = Depends(auth.get_current_user)):
    providers = _providers()
    if not providers:
        raise HTTPException(503, "AI is not configured yet. Set GROQ_API_KEY or OPENAI_API_KEY in Render → Environment.")
    if not req.message or not req.message.strip():
        raise HTTPException(400, "Empty message")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\nCONTEXT:\n" + (req.context.strip() or "(no data context was provided for this question)")},
        {"role": "user", "content": req.message.strip()},
    ]

    from openai import OpenAI
    last_error = None
    for label, client_kwargs, model in providers:
        try:
            client = OpenAI(**client_kwargs)
            resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2, max_tokens=600)
            answer = (resp.choices[0].message.content or "").strip()
            if answer:
                return {"answer": answer, "provider": label}
            last_error = f"{label}: empty response"
        except Exception as e:
            last_error = f"{label}: {e}"
            continue  # try the next configured provider, if any

    raise HTTPException(502, f"AI request failed on every configured provider ({last_error})")
