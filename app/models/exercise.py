"""Exercise game types.

`ExerciseType` is the catalogue of practice games. The three content-driven games
(Picture Talk, Read It Loud, Story Teller) read their prompts from a JSON data
file at request time (see `app/services/exercise_content.py`) — there is no
`exercise_content` DB table. Attempts are not persisted in a dedicated table
either; the disfluency profile is still fed via `disfluency_tracker`.
"""

import enum


class ExerciseType(str, enum.Enum):
    TALK_WITH_OLLIE = "TALK_WITH_OLLIE"    # live — conversation feature
    REPEAT_AFTER_ME = "REPEAT_AFTER_ME"    # live — phrase repetition
    PICTURE_TALK = "PICTURE_TALK"          # describe an image (file-backed prompts)
    READ_IT_LOUD = "READ_IT_LOUD"          # read a passage (file-backed prompts)
    STORY_TELLER = "STORY_TELLER"          # retell a story (file-backed prompts)
