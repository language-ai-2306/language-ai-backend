"""Kid-friendly feedback and session summary generation."""

from typing import Any


class FeedbackGenerator:
  TEMPLATES: dict[str, list[str]] = {
    "repetition": [
      "Great try! You said '{word}' a couple of times — let's try once more smoothly",
      "Nice work! Try saying '{word}' just once and keep going",
    ],
    "prolongation": [
      "You stretched that sound a little — try saying '{word}' in one smooth go",
      "Good effort! See if you can say '{word}' a bit quicker next time",
    ],
    "block": [
      "You got a little stuck before '{word}' — take a breath and try again",
      "Almost there! Try a big breath before '{word}' and then go",
    ],
    "interjection": [
      "You added an extra word '{word}' — try the phrase without it",
      "Good try! See if you can say it without '{word}' this time",
    ],
    "revision": [
      "You restarted partway through — that is okay, let us try the whole phrase",
      "Great effort! Try to keep going all the way to the end next time",
    ],
  }

  def _word_for_disfluency(self, disfluency: dict[str, Any]) -> str:
    return (
      disfluency.get("word")
      or disfluency.get("before_word")
      or disfluency.get("segment", "that part")
    )

  def generate_feedback(self, disfluencies: list[dict[str, Any]]) -> list[dict[str, str]]:
    feedback: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    type_counts: dict[str, int] = {}

    for disfluency in disfluencies:
      dtype = disfluency.get("type", "")
      templates = self.TEMPLATES.get(dtype, [])
      if not templates:
        continue

      word = self._word_for_disfluency(disfluency)
      # One tip per (type, word) — two events on the same word should not produce
      # two identical messages.
      key = (dtype, word)
      if key in seen:
        continue
      seen.add(key)

      # A held fricative is best coached on the specific sound, when we know it.
      sound = disfluency.get("sound")
      if dtype == "prolongation" and disfluency.get("character") == "fricative" and sound:
        message = (
          f"You held the '{sound}' sound in '{word}' — try saying it in one smooth go"
        )
      else:
        # Deterministic template choice (rotates per type), so identical input
        # always yields identical feedback — important for tests and for a child
        # seeing consistent coaching.
        idx = type_counts.get(dtype, 0) % len(templates)
        message = templates[idx].format(word=word)

      type_counts[dtype] = type_counts.get(dtype, 0) + 1
      feedback.append({"type": dtype, "message": message})

    return feedback

  def generate_summary(self, scores: dict[str, Any], child_age: int) -> str:
    fluency = scores.get("fluency_score", 0)
    clarity = scores.get("clarity_score", 0)
    confidence = scores.get("confidence_score", 0)

    if child_age <= 7:
      if fluency >= 80:
        return (
          "Wow, you did an amazing job today! "
          "Keep practising and you will get even better!"
        )
      if fluency >= 60:
        return (
          "Great job today! You tried really hard. "
          "Keep going — practise makes you stronger!"
        )
      return (
        "Nice try today! Every practise helps you grow. "
        "You are doing great — let us keep going together!"
      )

    if child_age <= 11:
      if fluency >= 80:
        return (
          f"You spoke really clearly today with a fluency score of {fluency}! "
          "Keep practising — you are building great skills!"
        )
      if fluency >= 60:
        return (
          f"Good effort today! Your fluency score was {fluency}. "
          "A little more practise and you will keep improving!"
        )
      return (
        "You showed real courage practising today! "
        "Every session helps — keep going and you will see progress!"
      )

    # Ages 12-14
    if fluency >= 80:
      return (
        f"Strong session! Fluency: {fluency}, clarity: {clarity}, "
        f"confidence: {confidence}. Keep building on this momentum!"
      )
    if fluency >= 60:
      return (
        f"Solid effort today — fluency {fluency}, clarity {clarity}. "
        "Focus on smooth starts next time and you will keep improving!"
      )
    return (
      f"Thanks for practising today. Scores: fluency {fluency}, "
      f"clarity {clarity}, confidence {confidence}. "
      "Consistent practice is how progress happens — you are on the right track!"
    )
