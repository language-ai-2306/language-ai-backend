"""Text normalisation and tokenisation helpers."""

import re
from collections import Counter

CONTRACTIONS = {
    "don't": "do not",
    "doesn't": "does not",
    "can't": "cannot",
    "won't": "will not",
    "i'm": "i am",
    "it's": "it is",
    "that's": "that is",
    "what's": "what is",
    "let's": "let us",
    "you're": "you are",
    "we're": "we are",
    "they're": "they are",
    "i've": "i have",
    "we've": "we have",
    "i'll": "i will",
    "we'll": "we will",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
}


def normalise_text(text: str) -> str:
    """Lowercase, expand contractions, strip punctuation, collapse whitespace."""
    if not text:
        return ""

    result = text.lower().strip()

    for contraction, expansion in CONTRACTIONS.items():
        result = re.sub(rf"\b{re.escape(contraction)}\b", expansion, result)

    result = re.sub(r"[^\w\s]", "", result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def tokenise(text: str) -> list[str]:
    """Split normalised text into lowercase word tokens."""
    normalised = normalise_text(text)
    if not normalised:
        return []
    return normalised.split()


def word_frequency(words: list[str]) -> dict[str, int]:
    """Count occurrences of each word."""
    return dict(Counter(w.lower() for w in words))
