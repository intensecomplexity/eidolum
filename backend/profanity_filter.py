"""
Profanity filter with leetspeak normalization, substring matching,
admin-managed custom words, and violation logging.
"""

import re
import time
import datetime
from collections import defaultdict

# ── Leetspeak normalization map ──────────────────────────────────────────────

_LEET_MAP = str.maketrans({
    "@": "a", "4": "a",
    "3": "e",
    "1": "i", "!": "i",
    "0": "o",
    "$": "s", "5": "s",
    "7": "t",
    "+": "t",
    "8": "b",
})


def _normalize(text: str) -> str:
    """Lowercase, translate leetspeak, strip non-alpha."""
    t = text.lower().translate(_LEET_MAP)
    # Remove all non-alphanumeric (keep letters only for matching)
    return re.sub(r"[^a-z]", "", t)


# ── Core word list ───────────────────────────────────────────────────────────
# Comprehensive English profanity, slurs, and hate speech.
# Words are stored normalized (lowercase, no special chars).

_BASE_WORDS = frozenset({
    # Common profanity
    "fuck", "fucking", "fucked", "fucker", "fuckers", "fucks", "fuckoff",
    "fuckface", "fuckhead", "fuckwit", "fucktard", "motherfucker",
    "motherfucking", "motherfuckers", "clusterfuck",
    "shit", "shitty", "shitting", "shithead", "shitface", "shithole",
    "shitbag", "bullshit", "horseshit", "dipshit", "shitass",
    "ass", "asshole", "assholes", "asswipe", "asshat", "assface",
    "dumbass", "fatass", "jackass", "smartass", "badass", "lardass",
    "bitch", "bitches", "bitchy", "bitching", "sonofabitch",
    "damn", "damnit", "goddamn", "goddamnit",
    "hell", "hellhole",
    "crap", "crappy",
    "dick", "dickhead", "dickface", "dickwad", "dickless", "dicks",
    "cock", "cocksucker", "cocksuckers", "cocks", "cockhead",
    "cunt", "cunts", "cunty",
    "piss", "pissed", "pissoff", "pissing",
    "bastard", "bastards",
    "whore", "whores", "whorehouse",
    "slut", "sluts", "slutty",
    "twat", "twats",
    "tit", "tits", "titty", "titties",
    "boob", "boobs", "boobies",
    "penis", "vagina", "anus",
    "dildo", "dildos",
    "jerkoff", "jackoff", "wank", "wanker", "wankers",
    "tosser", "tossers",
    "bollocks", "bellend", "knob", "knobhead",
    "prick", "pricks",
    "douche", "douchebag", "douchebags", "douchy",
    "skank", "skanky", "skanks",
    "hoe", "ho",
    "cum", "cumshot", "cumming", "cumstain",
    "blowjob", "blowjobs", "handjob",
    "rimjob", "circlejerk",
    "porn", "porno", "pornography",
    "orgasm", "orgy",
    "erection", "boner",

    # Racial slurs and hate speech
    "nigger", "niggers", "nigga", "niggas", "nigg",
    "negro", "negroid",
    "chink", "chinks", "chinky",
    "gook", "gooks",
    "spic", "spics", "spick",
    "wetback", "wetbacks",
    "beaner", "beaners",
    "kike", "kikes",
    "hymie", "hymies",
    "cracker", "crackers",
    "honky", "honkey", "honkies",
    "gringo", "gringos",
    "wop", "wops",
    "dago", "dagos",
    "polack", "polacks",
    "redskin", "redskins",
    "injun",
    "raghead", "ragheads",
    "towelhead", "towelheads",
    "sandnigger", "sandniggers",
    "camel jockey", "cameljockey",
    "zipperhead",
    "slant", "slanteye",
    "coon", "coons",
    "darky", "darkie",
    "jigaboo", "jiggaboo",
    "sambo",
    "pickaninny",
    "porch monkey", "porchmonkey",
    "uncle tom",

    # Homophobic / transphobic slurs
    "faggot", "faggots", "fag", "fags", "faggy",
    "dyke", "dykes",
    "homo", "homos",
    "queer",  # Note: context-dependent, but blocked for usernames
    "tranny", "trannies",
    "shemale", "shemales",
    "ladyboy",
    "lesbo", "lesbos",
    "sodomite", "sodomites",
    "butt pirate", "buttpirate",

    # Ableist slurs
    "retard", "retarded", "retards", "retardation",
    "spaz", "spazz", "spastic",
    "cripple", "crippled",
    "mongoloid",
    "tard", "tards",

    # Violence / threats
    "kill yourself", "killyourself", "kys",
    "die", "dieplease",
    "suicide",
    "rape", "raped", "raping", "rapist",
    "molest", "molester", "pedophile", "pedo", "pedos",
    "necrophilia",
    "bestiality",
    "genocide",
    "holocaust",
    "nazi", "nazis", "neonazi",
    "hitler", "heil",
    "white power", "whitepower",
    "white supremacy", "whitesupremacy",
    "sieg heil", "siegheil",

    # Drug references (username-inappropriate)
    "meth", "methhead",
    "crackhead",
    "heroin", "heroine",
    "cocaine",

    # Misc offensive
    "stfu", "gtfo", "lmfao",
    "thot", "thots",
    "simp", "simps",
    "incel", "incels",
    "cuck", "cucks", "cuckold",
    "creep", "creepy",
    "pervert", "perv", "pervs",
    "scumbag", "scumbags",
    "degenerate", "degenerates",
    "trash", "garbage", "filth",
    "loser", "losers",
    "idiot", "idiots", "idiotic",
    "moron", "morons", "moronic",
    "imbecile", "imbeciles",
    "stupid", "stupidity",

    # Sexual
    "anal", "analsex",
    "fellatio", "cunnilingus",
    "masturbate", "masturbation", "masturbating",
    "ejaculate", "ejaculation",
    "hentai", "milf",
    "gangbang",
    "bondage", "bdsm",
    "fetish",
    "hooker", "hookers",
    "prostitute", "prostitutes",
    "pimp", "pimps",
    "escort", "escorts",
    "stripper", "strippers",
})

# Admin-managed additional words (mutable at runtime)
_custom_words: set[str] = set()
# Admin-managed removed words (overrides base list)
_removed_words: set[str] = set()


def _get_active_words() -> set[str]:
    """Return the current effective word list."""
    return (_BASE_WORDS | _custom_words) - _removed_words


# ── Public API ───────────────────────────────────────────────────────────────


def is_profane(text: str) -> bool:
    """Check if text contains profanity. Uses substring matching on normalized text."""
    if not text:
        return False
    normalized = _normalize(text)
    words = _get_active_words()
    for word in words:
        if len(word) >= 3 and word in normalized:
            return True
    # Also check original lowercase for multi-word phrases
    lower = text.lower()
    for word in words:
        if " " in word and word in lower:
            return True
    return False


def get_profane_words(text: str) -> list[str]:
    """Return list of profane words found in text."""
    if not text:
        return []
    normalized = _normalize(text)
    found = []
    words = _get_active_words()
    for word in words:
        if len(word) >= 3 and word in normalized:
            found.append(word)
    lower = text.lower()
    for word in words:
        if " " in word and word in lower:
            found.append(word)
    return list(set(found))


# ── Admin word management ────────────────────────────────────────────────────


def add_custom_word(word: str):
    """Add a word to the custom list."""
    _custom_words.add(_normalize(word) or word.lower().strip())


def remove_word(word: str):
    """Remove a word (add to exclusion list)."""
    normalized = _normalize(word) or word.lower().strip()
    _removed_words.add(normalized)
    _custom_words.discard(normalized)


def get_word_list() -> dict:
    """Return the current word list stats for admin view."""
    return {
        "base_count": len(_BASE_WORDS),
        "custom_added": sorted(_custom_words),
        "removed": sorted(_removed_words),
        "total_active": len(_get_active_words()),
    }


# ── Violation tracking ───────────────────────────────────────────────────────

# user_id -> list of violation timestamps today
_violations: dict[int, list[float]] = defaultdict(list)
VIOLATION_FLAG_THRESHOLD = 5  # flag after 5 violations in a day
_VIOLATION_WINDOW = 86400  # 24 hours

# Audit log (in-memory, last 200 entries)
_audit_log: list[dict] = []


def record_violation(user_id: int, attempted_text: str, context: str = ""):
    """Record a profanity violation. Returns True if account should be flagged."""
    now = time.time()
    cutoff = now - _VIOLATION_WINDOW
    _violations[user_id] = [t for t in _violations[user_id] if t > cutoff]
    _violations[user_id].append(now)

    _audit_log.append({
        "user_id": user_id,
        "text": attempted_text[:200],  # Truncate for storage
        "context": context,
        "time": datetime.datetime.utcnow().isoformat(),
        "violation_count_today": len(_violations[user_id]),
    })
    if len(_audit_log) > 200:
        _audit_log.pop(0)

    return len(_violations[user_id]) >= VIOLATION_FLAG_THRESHOLD


def get_flagged_users() -> list[dict]:
    """Return users who have hit the violation threshold today."""
    now = time.time()
    cutoff = now - _VIOLATION_WINDOW
    flagged = []
    for uid, times in _violations.items():
        recent = [t for t in times if t > cutoff]
        if len(recent) >= VIOLATION_FLAG_THRESHOLD:
            flagged.append({"user_id": uid, "violations_today": len(recent)})
    return flagged


def get_audit_log(limit: int = 50) -> list[dict]:
    """Return recent profanity audit log entries."""
    return _audit_log[-limit:]
