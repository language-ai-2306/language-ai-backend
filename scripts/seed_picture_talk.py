"""Seed 100 Picture Talk prompts into `disfluency_phrase` (idempotent).

Picture Talk is open-ended: the child describes an image, so rows have NO
target_phoneme, and the difficulty reflects scene complexity / age:
  34 EASY   (ages 5-7)   — a single clear subject or action
  33 MEDIUM (ages 8-11)  — a scene with a few things going on
  33 HARD   (ages 12-15) — a busy, detailed scene

Storage in disfluency_phrase:
  * sentence   = the spoken describe-prompt shown to the child
  * image_url  = a real photo matching the scene (see IMAGES note below)
  * exercise_type = 'PICTURE_TALK', target_phoneme = NULL
  * ailment_type   = neutral 'Reading' bucket (same as Read It Loud / Story Teller)

IMAGES — auto-sourced via LoremFlickr:
  Each image_url is https://loremflickr.com/800/600/<tags>?lock=<n> — LoremFlickr
  returns a Creative-Commons Flickr photo matching <tags> (derived from the scene),
  and `lock=<n>` pins the SAME photo every time so the experience is stable.
  These are auto-matched CC images, great for dev/demo. For PRODUCTION with children,
  review each image and/or swap in your own vetted, licensed assets (just replace the
  URLs) — CC keyword matches are not guaranteed to be perfectly on-topic or curated.

Prereq: migrations b3c4d5e6f7a8 (exercise_type) + c4d5e6f7a8b9 (image_url) applied.
Run:    python -m scripts.seed_picture_talk
Idempotent: matched by (exercise_type, image_url). Set AILMENT_TYPE_ID to override.
"""

import os

from sqlalchemy import select, text

from app.db.base import SessionLocal
from app.models.disfluency import Difficulty, DisfluencyPhrase

PROMPT = {
    "EASY": "Look at the picture. Tell me what you see!",
    "MEDIUM": "Look at the picture. Tell me everything that is happening.",
    "HARD": "Look at the picture. Describe the scene in as much detail as you can — what is happening, and what might happen next?",
}

# Words dropped when turning a scene slug into LoremFlickr search tags.
_STOPWORDS = {"a", "an", "the", "with", "and", "of", "on", "in", "at", "to", "into", "by", "for", "up"}

# Scene slugs per difficulty — each becomes one image (keywords + a locked photo).
SCENES: dict[str, list[str]] = {
    "EASY": [
        "puppy-playing-with-ball", "red-apple-on-table", "cat-sleeping-on-mat",
        "yellow-school-bus", "birthday-cake-with-candles", "sunny-beach-with-bucket",
        "duck-in-a-pond", "rainbow-after-rain", "boy-on-a-swing", "girl-flying-a-kite",
        "bowl-of-fruit", "snowman-in-the-yard", "goldfish-in-a-bowl", "bird-in-a-nest",
        "teddy-bear-on-a-bed", "slice-of-pizza", "butterfly-on-a-flower",
        "dog-wearing-a-hat", "cup-of-hot-cocoa", "rain-boots-and-puddles",
        "mother-duck-and-ducklings", "red-fire-truck", "plate-of-cookies",
        "kitten-with-yarn", "sunflower-in-a-pot", "child-brushing-teeth",
        "bee-on-a-flower", "ice-cream-cone", "frog-on-a-lily-pad",
        "rabbit-eating-a-carrot", "toy-train-on-tracks", "balloon-floating-up",
        "boy-with-an-umbrella", "cat-and-dog-together",
    ],
    "MEDIUM": [
        "busy-playground", "farm-with-animals", "baking-in-the-kitchen",
        "family-picnic-in-park", "classroom-lesson", "pet-shop",
        "garden-with-gardener", "beach-with-swimmers", "birthday-party-with-balloons",
        "campsite-with-tent", "fruit-market-stall", "zoo-with-animals",
        "rainy-street-with-umbrellas", "library-with-readers", "soccer-game",
        "bakery-with-cakes", "snowy-park-sledding", "family-breakfast-table",
        "bus-stop-waiting", "fair-with-rides", "science-experiment-class",
        "family-cooking-dinner", "pond-with-ducks-and-fishing", "treehouse-with-kids",
        "aquarium-visit", "watering-vegetable-garden", "music-class-instruments",
        "autumn-pumpkin-patch", "swimming-pool", "campfire-with-marshmallows",
        "farmers-market", "snowball-fight", "restaurant-birthday",
    ],
    "HARD": [
        "busy-city-street", "crowded-train-station", "space-station-astronauts",
        "construction-site", "airport-terminal", "restaurant-kitchen",
        "coral-reef-sea-life", "festival-crowd-with-stalls", "science-museum-exhibits",
        "harbor-with-boats-and-cranes", "rainforest-wildlife", "stadium-during-a-game",
        "tv-news-studio", "factory-assembly-line", "farm-field-at-harvest",
        "ski-resort-slope", "mall-food-court", "fire-station-with-trucks",
        "airport-runway", "downtown-at-night", "subway-platform",
        "outdoor-street-market", "recycling-center", "wildlife-safari",
        "hotel-kitchen", "bridge-over-river-with-traffic", "carnival-at-night",
        "school-science-fair", "beach-boardwalk-with-shops", "mountain-hiking-trail",
        "garden-nursery", "bakery-at-dawn", "town-square-with-fountain",
    ],
}


def _image_url(slug: str, lock: int) -> str:
    """LoremFlickr URL: real CC photo for the scene keywords, pinned by `lock`."""
    tags = ",".join(t for t in slug.split("-") if t not in _STOPWORDS)
    return f"https://loremflickr.com/800/600/{tags}?lock={lock}"


def _resolve_ailment_type_id(db) -> int:
    """Neutral 'Reading' ailment_type (created once) — same bucket the other content
    games use. Picture Talk isn't a disfluency sub-type. Set AILMENT_TYPE_ID to override.
    """
    override = os.environ.get("AILMENT_TYPE_ID")
    if override:
        return int(override)
    row = db.execute(text("SELECT id FROM ailment_type WHERE name = 'Reading' LIMIT 1")).first()
    if row:
        return int(row[0])
    parent = db.execute(text("SELECT ailment_id FROM ailment_type ORDER BY id LIMIT 1")).first()
    if not parent:
        raise SystemExit("No ailment_type found. Create the Stutter ailment first, or set AILMENT_TYPE_ID.")
    db.execute(
        text(
            "INSERT INTO ailment_type (guid, name, ailment_id, created_at, last_modified_at) "
            "VALUES (gen_random_uuid(), 'Reading', :aid, now(), now())"
        ).bindparams(aid=int(parent[0]))
    )
    db.commit()
    row = db.execute(text("SELECT id FROM ailment_type WHERE name = 'Reading' ORDER BY id DESC LIMIT 1")).first()
    print(f"created ailment_type 'Reading' (id={row[0]}) under ailment_id={parent[0]}")
    return int(row[0])


def main() -> None:
    db = SessionLocal()
    try:
        ailment_type_id = _resolve_ailment_type_id(db)
        created = skipped = 0
        lock = 0  # sequential across EASY → MEDIUM → HARD, so each scene has a stable photo
        for difficulty in ("EASY", "MEDIUM", "HARD"):
            for slug in SCENES[difficulty]:
                lock += 1
                image_url = _image_url(slug, lock)
                exists = db.scalar(
                    select(DisfluencyPhrase).where(
                        DisfluencyPhrase.exercise_type == "PICTURE_TALK",
                        DisfluencyPhrase.image_url == image_url,
                    )
                )
                if exists is not None:
                    skipped += 1
                    continue
                db.add(
                    DisfluencyPhrase(
                        sentence=PROMPT[difficulty],
                        ailment_type_id=ailment_type_id,
                        target_phoneme=None,
                        difficulty=Difficulty(difficulty),
                        exercise_type="PICTURE_TALK",
                        image_url=image_url,
                    )
                )
                created += 1
        db.commit()
        print(
            f"Picture Talk seeded: {created} created, {skipped} skipped "
            f"(ailment_type_id={ailment_type_id}, total defined={lock})"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
