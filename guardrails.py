import re
import string
import jellyfish
from rapidfuzz.fuzz import ratio


MAX_EDIT_WORDS = 4
MIN_SOUND_SIMILARITY = 0.5

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
MULTIPLIERS = {"hundred": 100, "thousand": 1000, "lakh": 100000,
               "million": 1000000, "crore": 10000000}

NEGATION_WORDS = {"not", "no", "never", "none", "nobody", "nothing",
                  "neither", "nor", "cannot", "without"}

MODAL_WORDS = {"will", "would", "should", "must", "might", "may", "could",
               "can", "shall", "won't", "can't", "wouldn't", "shouldn't",
               "couldn't", "mustn't", "shan't"}

MODAL_PHRASES = ["going to", "gonna", "have to", "has to", "need to",
                 "needs to", "got to", "gotta"]

FLAG_RULES = {"negation_ambiguity", "commitment_change"}

TOKEN_PATTERN = r"\d+(?:\.\d+)?(?:st|nd|rd|th)?|\$|%|[a-z']+"


def normalize(text):
    text = text.lower()
    for ch in string.punctuation:
        text = text.replace(ch, "")
    return " ".join(text.split())


def split_numbers(text):
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    tokens = re.findall(TOKEN_PATTERN, text)

    values = []
    other = []
    last_was_tens = False

    for tok in tokens:
        if tok[0].isdigit():
            digits = re.match(r"\d+(?:\.\d+)?", tok).group()
            values.append(float(digits))
        elif tok in NUMBER_WORDS:
            value = NUMBER_WORDS[tok]
            if last_was_tens and value < 10:
                values[-1] += value
            else:
                values.append(value)
        elif tok in MULTIPLIERS and values:
            values[-1] *= MULTIPLIERS[tok]
        elif tok == "%":
            other.append("percent")
        elif tok == "$":
            other.append("dollars")
        else:
            other.append(tok)
        last_was_tens = tok in TENS

    return values, other


def check_numbers(original, replacement):
    orig_values, orig_other = split_numbers(original)
    rep_values, rep_other = split_numbers(replacement)

    if orig_values != rep_values:
        return "changes_number"

    if orig_values and orig_other == rep_other and normalize(original) != normalize(replacement):
        return "format_only"

    return None


def words_of(text):
    text = text.lower().replace("’", "'")
    return re.findall(r"[a-z']+", text)


def count_negations(text):
    count = 0
    for w in words_of(text):
        if w in NEGATION_WORDS or w.endswith("n't"):
            count += 1
    return count


def commitment_markers(text):
    words = words_of(text)
    markers = []
    for w in words:
        if w.endswith("'ll"):
            markers.append("'ll")
        elif w in MODAL_WORDS:
            markers.append(w)

    joined = " ".join(words)
    for phrase in MODAL_PHRASES:
        found = re.findall(rf"\b{phrase}\b", joined)
        markers += [phrase] * len(found)

    return sorted(markers)


def check_meaning(original, replacement):
    rule = check_numbers(original, replacement)
    if rule:
        return rule

    if count_negations(original) != count_negations(replacement):
        return "negation_ambiguity"

    if commitment_markers(original) != commitment_markers(replacement):
        return "commitment_change"

    return None

def sound_code(text):
    return "".join(jellyfish.metaphone(w) for w in normalize(text).split())


def sound_similarity(original, replacement):
    a = sound_code(original)
    b = sound_code(replacement)
    if not a and not b:
        return 1.0
    return ratio(a, b) / 100


def is_spelled_acronym(original, replacement):
    letters = normalize(original).split()
    if not letters or any(len(l) != 1 for l in letters):
        return False
    return "".join(letters) == normalize(replacement).replace(" ", "")


def check_sound(original, replacement):
    if is_spelled_acronym(original, replacement):
        return None
    if sound_similarity(original, replacement) < MIN_SOUND_SIMILARITY:
        return "not_phonetic"
    return None

COMMON_WORDS = set("""
a an the and or but if of to in on at by for with from as into about over under
is are was were be been am do does did have has had it its it's this that these those
there their they them we us our you your he she him her his i me my
what which who when where why how all any some no not more less up down out off
then than so too very just also only now here new old one two get got go make take
""".split())


def build_support(transcript, terms):
    # every word a replacement is allowed to use
    words = set(COMMON_WORDS)
    for seg in transcript["segments"]:
        words.update(normalize(seg["text"]).split())
    for term in terms:
        words.update(normalize(term["canonical"]).split())
    return words


def check_supported(original, replacement, support):
    if support is None:
        return None
    # "kuberneteslogs" -> "kubernetes logs" only moves a space
    if normalize(original).replace(" ", "") == normalize(replacement).replace(" ", ""):
        return None
    original_words = set(normalize(original).split())
    original_sounds = {jellyfish.metaphone(w) for w in original_words}
    for word in normalize(replacement).split():
        if word in original_words or word in support:
            continue
        # by -> buy, their -> there: same sound, so not an invented word
        if jellyfish.metaphone(word) in original_sounds:
            continue
        return "unsupported_term"
    return None


def check_edit(edit, segments_by_id, support=None):
    seg = segments_by_id.get(edit.get("seg_id"))
    if seg is None:
        return "unknown_segment"

    words = [w["w"] for w in seg["words"]]
    start = edit.get("start_word")
    end = edit.get("end_word")
    original = edit.get("original", "")
    replacement = edit.get("replacement", "")

    if not isinstance(start, int) or not isinstance(end, int):
        return "anchor_mismatch"
    if not (0 <= start < end <= len(words)):
        return "anchor_mismatch"
    if normalize(" ".join(words[start:end])) != normalize(original):
        return "anchor_mismatch"

    if len(original.split()) > MAX_EDIT_WORDS or len(replacement.split()) > MAX_EDIT_WORDS:
        return "too_large"

    rule = check_meaning(original, replacement)
    if rule:
        return rule

    rule = check_sound(original, replacement)
    if rule:
        return rule

    return check_supported(original, replacement, support)


def run_tests(check, tests):
    for original, replacement, expected in tests:
        got = check(original, replacement)
        mark = "PASS" if got == expected else "FAIL"
        print(f"{mark}  {original!r} -> {replacement!r}: got {got}, expected {expected}")


if __name__ == "__main__":
    print("Meaning checks")
    run_tests(check_meaning, [
        ("15th", "50th", "changes_number"),
        ("fifteen", "fifty", "changes_number"),
        ("fifteen", "15", "format_only"),
        ("twenty five", "25", "format_only"),
        ("two lakh", "200000", "format_only"),
        ("we can't ship", "we can ship", "negation_ambiguity"),
        ("we can ship", "we cannot ship", "negation_ambiguity"),
        ("never", "ever", "negation_ambiguity"),
        ("I'll send it", "I send it", "commitment_change"),
        ("we should", "we will", "commitment_change"),
        ("gonna", "going to", "commitment_change"),
        ("cube and eighties", "Kubernetes", None),
        ("move to launch", "move the launch", None),
        ("we'll deploy on cube", "we'll deploy on Kube", None),
    ])

    print("\nSound checks")
    run_tests(check_sound, [
        ("budget", "Jenkins", "not_phonetic"),
        ("priya", "maria", "not_phonetic"),
        ("cube and eighties", "Kubernetes", None),
        ("dock her", "Docker", None),
        ("get hub", "GitHub", None),
        ("a p i", "API", None),
        ("move to launch", "move the launch", None),
    ])

    print("\nSupported term checks")
    support = {"the", "budget", "review", "kubernetes", "priya"}
    run_tests(lambda a, b: check_supported(a, b, support), [
        ("cube and eighties", "Kubernetes", None),
        ("pria", "Priya", None),
        ("budget", "budgets", "unsupported_term"),
        ("by", "buy", None),
        ("their", "there", None),
        ("kuberneteslogs", "kubernetes logs", None),
    ])

    print("\nKnown weakness (passes but shouldn't):")
    for a, b in [("move to launch", "the launch"), ("react", "redux")]:
        print(f"  {a!r} -> {b!r}: similarity {sound_similarity(a, b):.2f}")