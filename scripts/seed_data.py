"""
Seed reference data so you can test the game in Postman.

Creates two ailments (Stutter, Lisp) and a batch of practice phrases across all
three difficulties. Safe to run more than once: it skips ailments that already
exist and only tops up phrases if there are very few.

Run from the backend folder:
    .\.venv\Scripts\python.exe scripts\seed_data.py
"""

from sqlalchemy import func, select

from app.db.base import SessionLocal
from app.models.ailment import Ailment
from app.models.disfluency import Difficulty, DisfluencyPhrase

# A few sample sentences per difficulty. Add your real content later.
PHRASES = {
    Difficulty.EASY: [
        "The cat sat on the mat.",
        "I like to play.",
        "We go to the park.",
        "She has a red ball.",
        "The sun is bright.",
        "He runs very fast.",
        "My dog is big.",
        "Birds can fly high.",
    ],
    Difficulty.MEDIUM: [
        "Peter packed a picnic for the afternoon.",
        "The slippery seal slid across the rocks.",
        "Sally sells seashells by the seashore.",
        "Brisk breezes blew by the bright beach.",
        "Twelve tired travellers took the train.",
        "Greg's grey goose grazed in the garden.",
    ],
    Difficulty.HARD: [
        "The thirty-three thieves thought they thrilled the throne.",
        "Six slippery snails slid slowly seaward.",
        "Round the rugged rocks the ragged rascal ran.",
        "She stood on the balcony inexplicably mimicking him.",
        "Freshly fried fish, freshly fried flesh.",
    ],
}


def seed() -> None:
    db = SessionLocal()
    try:
        for ailment_name in ("Stutter", "Lisp"):
            ailment = db.scalar(select(Ailment).where(Ailment.name == ailment_name))
            if ailment is None:
                ailment = Ailment(name=ailment_name)
                db.add(ailment)
                db.flush()
                print(f"Created ailment: {ailment_name} (id={ailment.id})")
            else:
                print(f"Ailment already exists: {ailment_name} (id={ailment.id})")

            existing_count = db.scalar(
                select(func.count())
                .select_from(DisfluencyPhrase)
                .where(DisfluencyPhrase.ailment_type_id == ailment.id)
            )
            if existing_count and existing_count >= 10:
                print(f"  {ailment_name} already has {existing_count} phrases — skipping.")
                continue

            added = 0
            for difficulty, sentences in PHRASES.items():
                for sentence in sentences:
                    db.add(
                        DisfluencyPhrase(
                            sentence=sentence,
                            ailment_type_id=ailment.id,
                            difficulty=difficulty,
                        )
                    )
                    added += 1
            print(f"  Added {added} phrases to {ailment_name}.")

        db.commit()
        print("\nDone seeding.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
