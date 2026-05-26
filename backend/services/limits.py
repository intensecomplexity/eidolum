"""Per-user caps for follows and saved predictions.

Used by the analyst-subscribe endpoint and the saved-predictions endpoint
to refuse new entries once a user is at the cap. The frontend turns a
409 with `code: "limit_reached"` into a popup that tells the user to
remove one to add another.
"""

MAX_FOLLOWS_PER_USER = 50
MAX_SAVED_PREDICTIONS_PER_USER = 100

FOLLOW_LIMIT_MESSAGE = (
    "You're following 50 forecasters — your current max. "
    "Unfollow one to add another."
)
SAVED_LIMIT_MESSAGE = (
    "You've saved 100 predictions — your current max. "
    "Remove one to save another."
)
