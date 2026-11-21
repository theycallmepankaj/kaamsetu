"""RAG assistant: retrieve knowledge sections, then let Claude answer from them.

Without an API key it runs in offline mode and replies with the best matching
sections directly, so the app is fully usable during development.
"""

import logging
from collections.abc import AsyncIterator

import anthropic

from ..config import get_settings
from .llm import get_client
from .retriever import search

log = logging.getLogger("kaamsetu.assistant")
settings = get_settings()

SYSTEM_PROMPT = """You are KaamSetu Sahayak, the helper inside KaamSetu, a job platform that connects blue-collar workers in India (electricians, plumbers, masons, painters, drivers, house help and others) with people who need work done.

Who you talk to: workers, many of whom have little formal education and use cheap phones, and employers such as households, shops and small contractors.

How to answer:
- Answer using the reference sections given with the question. They come from official government sources and KaamSetu's help pages. If they do not contain the answer, say that you are not sure and point the person to the right office or helpline mentioned in the sections, or to the official website. Do not invent amounts, dates, phone numbers or rules.
- Mark facts with the reference number in square brackets, like [1].
- Reply in the language the user writes in. If they write Hindi or Hinglish, reply in simple Hindi (Devanagari). Otherwise reply in simple English.
- Use short sentences and everyday words. Keep most answers under 120 words; use a short numbered list for steps.
- Never ask for an OTP, UPI PIN, bank password or Aadhaar number, and warn the user if someone else asks for them.
- If someone is in danger, tell them to call 112 first."""


def _format_context(hits) -> str:
    parts = []
    for i, (c, _) in enumerate(hits, 1):
        src = f" (source: {c.source_url})" if c.source_url.startswith("http") else ""
        parts.append(f"[{i}] {c.doc_title} / {c.section}{src}\n{c.text}")
    return "\n\n".join(parts)


def _sources(hits) -> list[dict]:
    return [{"n": i, "title": c.doc_title, "section": c.section, "url": c.source_url} for i, (c, _) in enumerate(hits, 1)]


def _offline_answer(hits, lang: str) -> str:
    if not hits:
        return (
            "मुझे इसका पक्का जवाब नहीं मिला। कृपया अपने ज़िले के श्रम कार्यालय से संपर्क करें, या मुफ्त कानूनी मदद के लिए 15100 पर कॉल करें।"
            if lang == "hi"
            else "I could not find a reliable answer to that. Please contact your district labour office, or call 15100 for free legal help."
        )
    c, _ = hits[0]
    body = "\n".join(line for line in c.text.splitlines() if not line.startswith("Keywords:")).strip()
    note = "(ऑफ़लाइन मोड: सीधे जानकारी से)" if lang == "hi" else "(Offline mode: quoted from the knowledge base)"
    return f"{c.section} [1]\n\n{body}\n\n{note}"


async def answer_stream(question: str, history: list[dict], lang: str, role: str) -> AsyncIterator[tuple[str, object]]:
    """Yields ("token", str) pieces and finally ("sources", list)."""
    hits = search(" ".join([question] + [h["content"] for h in history[-2:] if h["role"] == "user"]), k=4, audience=role)
    client = get_client()

    if client is None:
        text = _offline_answer(hits, lang)
        for i in range(0, len(text), 24):
            yield "token", text[i : i + 24]
        yield "sources", _sources(hits[:1])
        return

    user_content = (
        f"<references>\n{_format_context(hits) or 'No matching references found.'}\n</references>\n\n"
        f"User role: {role}. Interface language: {'Hindi' if lang == 'hi' else 'English'}.\n\n"
        f"Question: {question}"
    )
    messages = [*history, {"role": "user", "content": user_content}]

    try:
        async with client.beta.messages.stream(
            model=settings.claude_model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": "low"},  # chat answers from given context; low effort keeps it fast and cheap
            # If a safety classifier declines, the API retries on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            async for text in stream.text_stream:
                yield "token", text
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            yield "token", (
                "माफ़ कीजिए, मैं इसमें मदद नहीं कर सकता।" if lang == "hi" else "Sorry, I can't help with that request."
            )
    except anthropic.RateLimitError:
        log.warning("Claude rate limited; using offline answer")
        yield "token", _offline_answer(hits, lang)
    except anthropic.APIStatusError as e:
        log.error("Claude API error %s", e.status_code)
        yield "token", _offline_answer(hits, lang)
    except anthropic.APIConnectionError:
        log.error("Cannot reach Claude API; using offline answer")
        yield "token", _offline_answer(hits, lang)

    yield "sources", _sources(hits)
