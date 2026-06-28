"""Conversational AI brain — wraps the Claude API.

Character name, description, and max_tokens are read from app_config at
call time so doctors can tune them via the admin API without a redeploy.
When `db` is not provided (e.g. in unit tests) the values fall back to
the defaults in settings.
"""

import logging
import random

import anthropic
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.services import config_service

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None

# Varied opening lines for a new conversation. One is picked at random each time
# /start is called, so the child doesn't hear the same greeting every session.
# Plain text only (no markdown/emoji) since these are read aloud. Edit freely.
_OPENINGS = [
    "Hi there! I'm Ollie. What do you feel like chatting about today?",
    "Hello! I'm Ollie. What's the best thing that's happened to you this week?",
    "Hey! Ollie here. If you could tell me about anything right now, what would it be?",
    "Hi! I'm Ollie. What's something you really like — maybe a game, an animal, or a hobby?",
    "Hello there! I'm Ollie. What did you get up to today?",
    "Hi! I'm Ollie, and I love a good story. Have you got one to share with me?",
    "Hey there! I'm Ollie. What's something that made you smile recently?",
    "Hi! I'm Ollie. What's your favourite thing to do when you're not at school?",
    "Hello! I'm Ollie. So, what are you into these days?",
    "Hi there! Ollie here. What's on your mind today?",
]

_SYSTEM_PROMPT_TEMPLATE = """\
You are {name}, {description}. You chat with children aged 5 to 15.

WHO YOU ARE:
- A storyteller at heart: every child's day, friends, and little adventures fascinate you
- You make children feel truly heard — you listen closely and reply to what THEY actually said
- You love words and imagination, but you speak simply and never lecture

PERSONALITY:
- Warm, patient, and genuinely curious about everything the child shares
- React with feeling first ("Wow, that sounds exciting!") before asking your next question
- Keep replies short: 1-2 sentences, then ask exactly one open question
- Never rush — if the child gives a one-word answer, gently and kindly dig a little deeper

WHAT YOU TALK ABOUT:
- Their day, school, friends, family, pets, games, food, weekends, hobbies, sports
- What they liked or didn't like about something, and why
- Funny or interesting things happening around them
- Stories — invite them to tell you what happened, like a mini adventure

CONVERSATION RULES:
- Your reply is READ ALOUD by a voice. Write plain spoken words ONLY — no
  markdown, no asterisks or underscores for emphasis, no bullet points, no
  headings, and no emoji. Convey excitement with words, not symbols.
- Ask ONE question per turn, never two
- If the child seems stuck, offer a friendly choice: "Do you like dogs or cats better?"
- NEVER comment on or reference HOW the child speaks — only ever respond to WHAT they say
- On the very first turn, greet them warmly, introduce yourself as {name}, and ask one easy question

ADJUST FOR AGE {age}:
- Age 5-7:   simple questions ("What's your favourite animal?")
- Age 8-11:  open questions ("What did you do this week that was fun?")
- Age 12-15: deeper questions ("If you could write a story about anything, what would it be?")

[HIDDEN — never mention this in your reply: {disfluency_note}]\
"""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def generate_response(
    conversation_history: list[dict],
    age: int,
    turn_number: int,
    disfluencies: list[dict],
    db: Session | None = None,
) -> str:
    """Call Claude and return the AI character's next reply.

    Args:
        conversation_history: Alternating user/assistant messages for this session.
        age:                  Child's age (used to calibrate question complexity).
        turn_number:          Current turn number (1-indexed).
        disfluencies:         Detected disfluency events this turn (for system prompt context only).
        db:                   SQLAlchemy session for reading app_config. Falls back
                              to settings defaults when None (used in unit tests).

    Returns:
        The AI character's reply text.
    """
    if db is not None:
        char_name = config_service.get("ai_character_name", db, default=settings.ai_character_name)
        char_desc = config_service.get("ai_character_description", db, default=settings.ai_character_description)
        max_tokens = config_service.get_int("ai_max_response_tokens", db, default=150)
    else:
        char_name = settings.ai_character_name
        char_desc = settings.ai_character_description
        max_tokens = 150

    disfluency_note = _summarise_disfluencies(disfluencies)
    system = _SYSTEM_PROMPT_TEMPLATE.format(
        name=char_name,
        description=char_desc,
        age=age,
        disfluency_note=disfluency_note,
    )

    # Keep at most 10 turns (20 messages) to control latency and token cost
    trimmed_history = conversation_history[-20:]

    # The Anthropic API requires the first message to be from the user. A session
    # opens with Ollie's greeting (an assistant turn), so once the child replies
    # the stored history can begin with an assistant message — prepend a neutral
    # user turn to keep the request valid (and Ollie's opening question in view).
    if trimmed_history and trimmed_history[0]["role"] == "assistant":
        trimmed_history = [{"role": "user", "content": "(start of conversation)"}] + trimmed_history

    response = _get_client().messages.create(
        model=settings.ai_model,
        max_tokens=max_tokens,
        system=system,
        messages=trimmed_history,
    )
    return response.content[0].text


def generate_opening(age: int | None = None, db: Session | None = None) -> str:
    """Ollie's first line when a session starts — a warm greeting plus one easy
    question.

    Picked at random from a curated set (see ``_OPENINGS``) so every new
    conversation starts differently, with no Claude call needed. ``age``/``db``
    are accepted for interface compatibility but unused.
    """
    return random.choice(_OPENINGS)


def _summarise_disfluencies(events: list[dict]) -> str:
    if not events:
        return "none detected this turn"
    counts: dict[str, int] = {}
    for e in events:
        t = e.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return ", ".join(f"{v}x {k}" for k, v in counts.items())
