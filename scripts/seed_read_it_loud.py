"""Seed 120 Read It Loud passages into `disfluency_phrase` (idempotent).

120 passages = 10 target phonemes x 4 difficulties (EASY / MEDIUM / HARD /
TONGUE_TWISTER) x 3 each. Every passage is ~120-200 characters, kid-friendly
(ages 5-15), and loaded with its target phoneme. Rows are inserted with
exercise_type='READ_IT_LOUD' and the matching target_phoneme + difficulty.

Prereq: migration b3c4d5e6f7a8 (adds disfluency_phrase.exercise_type) must be
applied first — deploy / restart the app, then run:

    python -m scripts.seed_read_it_loud

Idempotent: a passage is matched by (exercise_type, sentence); existing ones are
skipped. Set AILMENT_TYPE_ID to force which ailment type these attach to;
otherwise the script reuses the ailment_type_id of an existing phrase.
"""

import os

from sqlalchemy import select, text

from app.db.base import SessionLocal
from app.models.disfluency import Difficulty, DisfluencyPhrase

# (target_phoneme, difficulty, passage)
PASSAGES: list[tuple[str, str, str]] = [
    # ---- /s/ ----
    ("s", "EASY", "Sam sees the sun in the sky. The sun is so bright and sunny. Sam smiles and sits on the soft grass to sing a silly little song."),
    ("s", "EASY", "Sue has a small dog named Spot. Spot sleeps by the steps in the sunshine. Sue says Spot is the sweetest, silliest dog she has seen."),
    ("s", "EASY", "The sea is salty and sparkly. Seven small seals swim past the sand. They splash and slide and squeak as the sun sets slowly."),
    ("s", "MEDIUM", "On Saturday, Sofia sailed a small boat across the sparkling sea. She spotted seven silver fish and a slippery starfish resting on the soft sand below."),
    ("s", "MEDIUM", "Sam saved his coins to buy some seeds. He sprinkled them in the soil, sprayed a little water, and soon sweet strawberries started to sprout in the sunny spot."),
    ("s", "MEDIUM", "Sally sat on the steps sipping cold soda. She saw a squirrel scamper past, stuff its cheeks with seeds, and scurry swiftly up the tallest, strongest tree."),
    ("s", "HARD", "Last summer, Sasha and her sister set off on a special search for seashells along the sandy seashore. They discovered starfish, smooth stones, and a spiral shell that seemed to whisper like the sea."),
    ("s", "HARD", "The young scientist studied the strange substance closely, stirring it slowly in a small silver dish. Suddenly it started to sparkle and sizzle, sending a spray of tiny stars across the surface."),
    ("s", "HARD", "Simon sprinted across the soccer field as the sun sank slowly behind the stadium. With a swift, strong kick, he sent the ball soaring straight past the goalkeeper and scored for his squad."),
    ("s", "TONGUE_TWISTER", "She sells seashells by the seashore. The shells she sells are surely seashells, so if she sells shells on the shore, the shore shells are surely seashells."),
    ("s", "TONGUE_TWISTER", "Seven slippery snakes slid slowly down the steep, sandy slope, sliding and swishing side to side as the summer sun set softly over the silent sea."),
    ("s", "TONGUE_TWISTER", "Sixty-six sizzling sausages sat in a saucepan, spitting and sputtering, while Sam the silly seal slurped his super sweet strawberry soda."),

    # ---- /r/ ----
    ("r", "EASY", "The rabbit runs in the rain. It races round and round the rock. The red rabbit is ready to rest inside its round little burrow."),
    ("r", "EASY", "Rosa rides her red bike on the road. She rings the bell and races her friend. Rosa really loves to ride when the morning sun rises."),
    ("r", "EASY", "A robin sits on the roof. It ruffles its wings in the rain. The robin sings a rosy little song and rests near the round red barn."),
    ("r", "MEDIUM", "Ryan raced his remote car around the room, roaring like a real racer. It rolled over the rug, rounded the chair, and reached the ramp right before it ran out of room."),
    ("r", "MEDIUM", "In the rainforest, a bright red parrot rested on a branch. It ruffled its feathers, and then, with a sudden rush, it soared right over the roaring river far below."),
    ("r", "MEDIUM", "Rita ran to the garden to rescue her runaway rabbit. She reached through the reeds, found him resting near the roses, and carried him carefully back to his cozy run."),
    ("r", "HARD", "Every morning, Rory would race down to the river to watch the rushing water roar over the rocks. He dreamed of building a raft strong enough to ride all the way to the roaring waterfall."),
    ("r", "HARD", "The brave explorer trekked across the rugged, rocky ridge as rain rattled against her raincoat. Around every corner the trail grew rougher, but she refused to turn around before reaching the ruins."),
    ("r", "HARD", "The orchestra rehearsed for hours while the drummer rolled his sticks in a rapid rhythm. As the music rose and roared, the crowd rose to their feet, roaring with cheers for the performance."),
    ("r", "TONGUE_TWISTER", "Round and round the rugged rock the ragged rascal ran, racing the roaring river as red robins rested on the rough, rusty railing."),
    ("r", "TONGUE_TWISTER", "Really rural roads are rarely repaired, so a rickety red truck rumbled and rattled around the rough, rocky ruts right beside the river."),
    ("r", "TONGUE_TWISTER", "Ravens rarely rest on rickety roofs, but three ragged ravens raced round the roaring rooftop, ruffling and rattling their wings in the rushing rain."),

    # ---- /l/ ----
    ("l", "EASY", "Lily loves her little lamb. The lamb leaps in the long green grass. Lily laughs and lies in the sun as the lamb licks her hand."),
    ("l", "EASY", "Leo has a lovely blue balloon. It floats up, light and low. Leo holds the long string and looks up at his lucky little balloon."),
    ("l", "EASY", "The lake is calm and clear. A lily floats near the log. Little ladybugs land on the leaves as the light shines low on the lake."),
    ("l", "MEDIUM", "Last night, Lucy looked up at the lovely full moon glowing low in the sky. She lay on a soft blanket, listened to the leaves, and slowly closed her eyes to make a little wish."),
    ("l", "MEDIUM", "Liam loved playing in the leaves that piled along the lane. He leaped, rolled, and laughed as the yellow leaves fluttered lightly all around his little legs."),
    ("l", "MEDIUM", "The playful puppy licked Layla's hand and followed her all along the lane. Together they walked to the lake, where the puppy splashed happily in the shallow, cool water."),
    ("l", "HARD", "Late in the evening, Layla lit a little lantern and followed the winding trail along the lake. The glowing light danced lazily across the still water while the leaves rustled gently in the cool wind."),
    ("l", "HARD", "Leo longed to learn to play the violin, so he practiced daily until his fingers felt like lead. Slowly but surely the lovely melody flowed, filling the whole hall with a wonderful, lilting sound."),
    ("l", "HARD", "The little owl lived high in a tall, leafy elm at the edge of the lonely field. Each night it silently glided low over the meadow, listening carefully for the smallest rustle in the grass below."),
    ("l", "TONGUE_TWISTER", "Lucy likes lovely lemon lollipops, but little Lila loves large lime lollipops, so Lucy and Lila lick their lollipops loudly all along the leafy lane."),
    ("l", "TONGUE_TWISTER", "A lazy lion lay lolling on a low, leafy log, licking his lips as eleven little lambs leaped lightly along the long, lovely green hill."),
    ("l", "TONGUE_TWISTER", "Lucky Lola laughed and lined up all her little lemon lollipops along the long low shelf, while lazy Leo licked a lime lollipop by the lake."),

    # ---- /p/ ----
    ("p", "EASY", "Pip the puppy plays in the park. He pops up and pounces on the ball. Pip is a playful pup who loves to prance across the pretty park."),
    ("p", "EASY", "Pam picks purple plums. She puts them in a paper bag. Pam is happy to pack the plump purple plums for a picnic in the park."),
    ("p", "EASY", "The penguin plays on the ice. It flaps and hops and plops down. The plump little penguin peeks past the packed pile of powdery snow."),
    ("p", "MEDIUM", "Peter packed a picnic with plump peaches, purple grapes, and a piece of pumpkin pie. He put the basket in the park, spread a blanket, and popped open a bottle of apple juice."),
    ("p", "MEDIUM", "The playful parrot perched on a pole and repeated every word that people spoke. It puffed its purple feathers, hopped up and down, and squawked a proud, peppy little tune."),
    ("p", "MEDIUM", "Poppy painted a picture of a purple pony prancing past a pond. She was so proud that she pinned it up, showed it to her parents, and planned to paint another one tomorrow."),
    ("p", "HARD", "On a perfect spring morning, Priya planted pumpkin seeds in neat little rows and patted the soil in place. She promised to water them properly every day until plump orange pumpkins appeared."),
    ("p", "HARD", "The explorers paddled their small boat past the steep cliffs, peering up at the puffins perched on the rocky peaks. They planned to camp and photograph the peculiar birds before the storm approached."),
    ("p", "HARD", "The clever puppet maker spent the whole afternoon painting a pair of playful puppets. He popped them on his hands, put on a splendid show, and the delighted people clapped and cheered for more."),
    ("p", "TONGUE_TWISTER", "Peter Piper picked a peck of pickled peppers. A peck of pickled peppers Peter Piper picked, so where is the peck of pickled peppers Peter Piper picked?"),
    ("p", "TONGUE_TWISTER", "Plucky penguins pack plump purple plums in paper packs, then proudly parade past the pond, popping and prancing in the pale spring sunshine."),
    ("p", "TONGUE_TWISTER", "A proper cup of coffee from a proper copper pot pleases the pleasant princess, who happily plops it down and pours a perfect cup of purple punch."),

    # ---- /b/ ----
    ("b", "EASY", "Ben has a big blue ball. He bounces it by the big red barn. The ball bounces high and low as Ben boldly bats it back and forth."),
    ("b", "EASY", "The busy bee buzzes by the bush. It buzzes near the bright blue flower. The little bee is busy building a big, buzzing home."),
    ("b", "EASY", "Bella bakes a batch of buns. She butters them by the bowl. Bella brings the best warm buns to breakfast for her baby brother."),
    ("b", "MEDIUM", "Bobby built a big blanket fort beside his bunk bed. He brought his best books, a bright blue flashlight, and a bowl of berries to enjoy inside his cozy little base."),
    ("b", "MEDIUM", "By the babbling brook, a big brown bear balanced on a rock. It batted at the bubbles, then bounded back to the bushes to bring home a basket of ripe berries."),
    ("b", "MEDIUM", "The baby bird was too brave and bounced right out of its nest. Luckily, Ben found it below the branch, brought it back gently, and the busy mother bird buzzed with joy."),
    ("b", "HARD", "Before breakfast, Bianca and her brother built a bumpy sandcastle beside the bright blue bay. They gathered buckets of shells, balanced a bridge on top, and watched the waves break nearby."),
    ("b", "HARD", "The brave firefighter climbed the tall building as billows of black smoke burst from the windows. Bit by bit she brought everybody safely down the ladder, and the crowd below burst into big cheers."),
    ("b", "HARD", "Deep in the forest, a big brown bear discovered a beehive buzzing in the branches. Balancing carefully, it reached for the golden honey, but the busy bees began to buzz and it bounded away."),
    ("b", "TONGUE_TWISTER", "Betty bought a bit of better butter, but the butter Betty bought was bitter, so Betty bought a bit of better butter to make the bitter butter better."),
    ("b", "TONGUE_TWISTER", "Big black bugs bounced by the babbling brook, while brave brown bears balanced bright blue balls beside the bumpy, bubbling bay."),
    ("b", "TONGUE_TWISTER", "A busy baby bumblebee buzzed by the blooming bush, bumping and bouncing between the bright blue bells before it buzzed all the way back to bed."),

    # ---- /t/ ----
    ("t", "EASY", "Tom has two toy trucks. He takes them to the table. Tom taps the top and the trucks go tumbling toward the tidy little tent."),
    ("t", "EASY", "The tiny turtle takes a walk. It totters to the tall tree. The turtle tucks in its toes and takes a tiny nap in the warm afternoon sun."),
    ("t", "EASY", "Tina ties her teal shoes tight. She tiptoes to the tall gate. Tina taps the top twice and trots off toward the tidy little town."),
    ("t", "MEDIUM", "On Tuesday, Theo took his little train to the top of the tall track. He watched it tumble down, twist around the turn, and toot loudly as it traveled through the tiny tunnel."),
    ("t", "MEDIUM", "Tessa toasted two slices of bread and topped them with tomato and a tasty treat. Then she took her plate to the table, tucked in her chair, and ate every tiny bite."),
    ("t", "MEDIUM", "The tired tiger stretched out on the tall grass and twitched its tail in the heat. It took a long drink at the stream, then trotted back to rest beneath the tallest tree."),
    ("t", "HARD", "Every Tuesday, Timothy took the tiny train into town to visit the tremendous toy store. He tested the trucks, tried the trains, and took ages deciding which terrific treasure to take home."),
    ("t", "HARD", "The determined team trained together through the tough, twisting mountain trail. They tightened their tents at the top, toasted marshmallows, and told terrific tales late into the starry night."),
    ("t", "HARD", "The talented tap dancer tapped and twirled across the tall wooden stage. Her tidy little taps grew faster and tighter until the theater trembled with the thunder of a thousand tapping toes."),
    ("t", "TONGUE_TWISTER", "Two tiny tigers took ten toy trains to town, tugging and tooting them tightly together, till the two tired tigers tumbled onto the tidy tracks."),
    ("t", "TONGUE_TWISTER", "Ted's tall tent tilted, so ten tired tortoises tiptoed together to tie the tent tighter to the two tough trees at the top of the trail."),
    ("t", "TONGUE_TWISTER", "A tutor who tooted the tuba tried to teach two tooting tutors to toot, but the two tooting tutors kept tooting the tune totally out of time."),

    # ---- /k/ ----
    ("k", "EASY", "Kim has a cute little kitten. It curls up in a cozy cup. The kitten cuddles close and keeps calm as Kim counts all the way to ten."),
    ("k", "EASY", "The cat climbs on the counter. It knocks a cup and a cookie down. The clever cat then curls up and calmly cleans its cozy coat."),
    ("k", "EASY", "Kate keeps a kind kangaroo. It kicks and hops beside the creek. Kate calls the kangaroo and it comes racing across the cool green field."),
    ("k", "MEDIUM", "In the kitchen, Casey cracked eggs and mixed a big bowl of cake batter. She carefully poured it in a pan, popped it in the oven, and could not wait to taste the cooked chocolate cake."),
    ("k", "MEDIUM", "The curious cub crept close to the cool creek to catch a quick drink. It clawed at the cold water, caught a glimpse of a crab, and quickly scampered back to its cozy cave."),
    ("k", "MEDIUM", "Kevin kept his kite in the corner of the closet all winter long. On a clear, cool day he carried it to the park, caught the wind, and watched it climb high into the clear blue sky."),
    ("k", "HARD", "The clever king kept a collection of curious clocks locked inside his cold stone castle. Each one ticked a different tune, and the careful king would wind them every day at the crack of dawn."),
    ("k", "HARD", "Kayla cracked the code to the ancient locked box she discovered in the dark, cluttered attic. Inside were copper coins, a cracked compass, and a crinkled map leading to a hidden creek."),
    ("k", "HARD", "The kayakers carefully crossed the choppy current, keeping close together as the cold water crashed against the rocks. They cheered with courage as they conquered the last quick, curving bend."),
    ("k", "TONGUE_TWISTER", "How many cookies could a good cook cook if a good cook could cook cookies? A good cook could cook as many cookies as a good cook could cook if a cook could cook cookies."),
    ("k", "TONGUE_TWISTER", "Clean clams crammed in clean cans, while a quick clown carried a crate of crisp crackers across the cracked concrete corner of the crowded kitchen."),
    ("k", "TONGUE_TWISTER", "Kevin's clever kitten kept catching quick crickets in the cold, cluttered kitchen corner, curling and creeping close to the crackling copper kettle."),

    # ---- /sh/ ----
    ("sh", "EASY", "She shows her shiny shell. It shines on the sandy shore. She shakes off the sand and shares her shell with a shy little friend."),
    ("sh", "EASY", "The sheep shakes in the shade. It has thick, soft wool to share. The sheep shuffles past the shed and shelters from the bright sunshine."),
    ("sh", "EASY", "Shawn washes his ship in the tub. He shows it off to his mom. The ship is shiny and it shoots across the water with a big splash."),
    ("sh", "MEDIUM", "On the shore, Sheila searched for shiny shells and smooth stones in the shallow water. She showed the shells to her sister, and they shared them in the shade of a big beach umbrella."),
    ("sh", "MEDIUM", "The shy little fish darted through the shimmering shallows, flashing its shiny scales. It slipped past the seashells, dashed into the shadows, and hid beneath a shelf of coral."),
    ("sh", "MEDIUM", "Sharon shut the shop, shook the rain off her shawl, and rushed home through the splashing puddles. She was sure a warm shower and a bowl of soup would chase the shivers away."),
    ("sh", "HARD", "The shepherd led his flock of woolly sheep across the shadowy mountain slope as the sun began to sink. He sheltered them beside a shallow stream and shushed them softly until the stars shone."),
    ("sh", "HARD", "Shelly wished on a shooting star that flashed across the shimmering night sky. She was sure her wish to sail a ship across the shining ocean would surely, somehow, someday come true."),
    ("sh", "HARD", "The magnificent seashell shop stood on the sunny shore, its shelves stacked with shining shells of every shape. Shoppers wandered in to search for special treasures washed up by the crashing surf."),
    ("sh", "TONGUE_TWISTER", "She should share her shiny shells, so she showed the shy shepherd sixteen small seashells shimmering on the sandy shore in the shining afternoon sunshine."),
    ("sh", "TONGUE_TWISTER", "The sheep shop sells cheap sheep sheets, so a sharp shopper should shop for six sheer sheets and shove them all into a shiny shopping sack."),
    ("sh", "TONGUE_TWISTER", "Fresh shrimp shrank in the shallow ship's dish, so the shy chef shifted the shrimp, shook the dish, and shared the shrimp with his shivering shipmates."),

    # ---- /th/ ----
    ("th", "EASY", "The three thick frogs sit on the log. They think and thump all day. The three frogs thank the warm sun and then hop through the thin reeds."),
    ("th", "EASY", "Beth has a thin blue thread. She threads it through the cloth. Beth thinks it is fun to sew, and she thanks her mother for the thread."),
    ("th", "EASY", "The path goes through the thick woods. Theo thinks it is the right way. He thanks his friend and walks the path beneath the thin, tall trees."),
    ("th", "MEDIUM", "On Thursday, the three friends thought they would gather things for a thrilling treasure hunt. They searched through the thick bushes, thanked each other for every clue, and had a wonderful time."),
    ("th", "MEDIUM", "Beth thought the thunderstorm was thrilling as it rumbled through the thick clouds. She threw on a thick blanket, thanked her dad for the warm cocoa, and watched the lightning through the window."),
    ("th", "MEDIUM", "The mother bird gathered thin threads and thick twigs to build a warm nest. She thought carefully about each thing, weaving them together beneath the thick leaves of the tall oak tree."),
    ("th", "HARD", "The thoughtful author thanked the theater full of eager children who had gathered to hear her thrilling tales. She thought there was nothing better than sharing stories that made young minds think."),
    ("th", "HARD", "Through the thick morning fog, the three explorers threaded their way along the narrow mountain path. They thought about turning back, but they thanked their lucky stars and pushed onward together."),
    ("th", "HARD", "Nathan thought the science theory was thoroughly fascinating, though it took him three tries to understand it. With thick books piled high, he thought it through until at last everything made sense."),
    ("th", "TONGUE_TWISTER", "Three thin thieves thought a thousand thoughts, but if three thin thieves thought a thousand thoughts, how many thoughts did the three thin thieves think through?"),
    ("th", "TONGUE_TWISTER", "The thirty-three thankful thrushes thought the thick thorn thicket was the thing they thirsted for, so they thronged through it, thrashing their thin throats."),
    ("th", "TONGUE_TWISTER", "This thistle here, that thistle there, thousands of thick thistles thrive together, so I think this thorny thistle patch is thoroughly the thickest anywhere."),

    # ---- /st/ ----
    ("st", "EASY", "The star shines in the still sky. Stan stops to stare at the stars. He stands on the step and starts to count each stunning little star."),
    ("st", "EASY", "Stella has a stack of stones. She sets them on the step. Stella stacks them still and steady into a strong little stone tower."),
    ("st", "EASY", "The stork stands in the stream. It stays so still and straight. The stork steps slowly and stares at the stones beneath the steady water."),
    ("st", "MEDIUM", "Stevie stood at the start line, ready to sprint. As the whistle blew, he sped past the stump, stayed steady around the stones, and stopped, stunned, when he stepped across the line first."),
    ("st", "MEDIUM", "In the story, a strong little steam train started up the steep hill. It struggled and strained, but it stayed steady, and at last it steamed straight over the top of the stony mountain."),
    ("st", "MEDIUM", "Stacy stacked the storybooks on the shelf, then stopped to stare out at the storm. Streaks of lightning stretched across the sky as steady rain started to stream down the frosty window."),
    ("st", "HARD", "The stubborn little starfish stayed stuck to the stone as the strong storm stirred the sea. Step by step the steady waves strained against it, but the starfish simply would not stop holding on."),
    ("st", "HARD", "Stranded on the steep, stony steps of the old castle, the students studied the strange stars overhead. They stayed strong, started a fire, and told stories until the storm finally stopped."),
    ("st", "HARD", "The master storyteller stood on the stage and started a stunning tale about a stubborn stallion. The astonished students stayed still, stuck to every twist, until the story reached its stellar end."),
    ("st", "TONGUE_TWISTER", "Stan the strong stork stood still on the steep stone steps, staring at six stunning stars, while a steady stream splashed past a stack of smooth grey stones."),
    ("st", "TONGUE_TWISTER", "Strong Steve steadily stacked stiff steel sticks in straight stripes, still stacking steady stacks while the stubborn storm stirred the stormy street."),
    ("st", "TONGUE_TWISTER", "The stylish student stumbled on the steep stone stairs, startling a stately stork that stood stiff and still beside the strange, steaming stove."),
]


def _resolve_ailment_type_id(db) -> int:
    """Return the ailment_type_id to tag Read It Loud passages with.

    Read It Loud passages are targeted by phoneme, not by disfluency sub-type
    (Block/Repetition/…), so they get a neutral 'Reading' ailment_type rather than
    an arbitrary sub-type. Created once (under the same ailment as the existing
    types) if it doesn't exist. Set AILMENT_TYPE_ID to override.
    """
    override = os.environ.get("AILMENT_TYPE_ID")
    if override:
        return int(override)

    row = db.execute(
        text("SELECT id FROM ailment_type WHERE name = 'Reading' LIMIT 1")
    ).first()
    if row:
        return int(row[0])

    # Create 'Reading' under the same ailment as the existing sub-types (Stutter).
    parent = db.execute(text("SELECT ailment_id FROM ailment_type ORDER BY id LIMIT 1")).first()
    if not parent:
        raise SystemExit(
            "No ailment_type found. Create the Stutter ailment + its types first, "
            "or set AILMENT_TYPE_ID."
        )
    db.execute(
        text(
            "INSERT INTO ailment_type (guid, name, ailment_id, created_at, last_modified_at) "
            "VALUES (gen_random_uuid(), 'Reading', :aid, now(), now())"
        ).bindparams(aid=int(parent[0]))
    )
    db.commit()
    row = db.execute(
        text("SELECT id FROM ailment_type WHERE name = 'Reading' ORDER BY id DESC LIMIT 1")
    ).first()
    print(f"created ailment_type 'Reading' (id={row[0]}) under ailment_id={parent[0]}")
    return int(row[0])


def main() -> None:
    db = SessionLocal()
    try:
        ailment_type_id = _resolve_ailment_type_id(db)
        created = skipped = 0
        for phoneme, difficulty, sentence in PASSAGES:
            exists = db.scalar(
                select(DisfluencyPhrase).where(
                    DisfluencyPhrase.exercise_type == "READ_IT_LOUD",
                    DisfluencyPhrase.sentence == sentence,
                )
            )
            if exists is not None:
                skipped += 1
                continue
            db.add(
                DisfluencyPhrase(
                    sentence=sentence,
                    ailment_type_id=ailment_type_id,
                    target_phoneme=phoneme,
                    difficulty=Difficulty(difficulty),
                    exercise_type="READ_IT_LOUD",
                )
            )
            created += 1
        db.commit()
        print(
            f"Read It Loud seeded: {created} created, {skipped} skipped "
            f"(ailment_type_id={ailment_type_id}, total defined={len(PASSAGES)})"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
