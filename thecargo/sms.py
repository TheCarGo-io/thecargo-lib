import re
import unicodedata
from dataclasses import dataclass

_ZERO_WIDTH_CPS = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x180E})
_PUNCT = {
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
    0x2013: "-",
    0x2014: "-",
    0x2015: "-",
    0x2212: "-",
    0x2026: "...",
    0x00A0: " ",
    0x202F: " ",
    0x2009: " ",
    0x200A: " ",
    0x2007: " ",
}
_FANCY_LOW = 0x1D400
_FANCY_HIGH = 0x1D7FF
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")

_GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅå"
    "Δ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXTENDED = set("^{}\\[~]|€")

_GSM_SINGLE = 160
_GSM_MULTI = 153
_UCS2_SINGLE = 70
_UCS2_MULTI = 67

_SPAM_TRIGGER_WORDS = (
    "free",
    "winner",
    "cash",
    "prize",
    "guaranteed",
    "act now",
    "buy now",
    "click here",
    "limited time",
    "risk free",
    "no cost",
    "save big",
    "% off",
    "instant quote",
    "congratulations",
    "urgent",
)
_OPTOUT_RE = re.compile(r"\b(?:stop|unsubscribe|opt[\s-]?out|cancel)\b", re.IGNORECASE)
_SHORTENER_RE = re.compile(
    r"\b(?:bit\.ly|tinyurl\.com|goo\.gl|t\.co|ow\.ly|is\.gd|buff\.ly|rebrand\.ly|cutt\.ly|shorturl\.at)\b",
    re.IGNORECASE,
)

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"


@dataclass(frozen=True)
class SmsSegments:
    encoding: str
    segments: int
    length: int


@dataclass(frozen=True)
class SmsFinding:
    code: str
    severity: str
    message: str


def _keep_char(cp: int) -> bool:
    if cp in _ZERO_WIDTH_CPS:
        return False
    if cp < 0x20 and cp not in (0x09, 0x0A, 0x0D):
        return False
    return not (0x7F <= cp <= 0x9F)


def sanitize_sms_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    out: list[str] = []
    for ch in normalized:
        cp = ord(ch)
        if cp in _PUNCT:
            out.append(_PUNCT[cp])
        elif _keep_char(cp):
            out.append(ch)
    s = "".join(out)
    s = _MULTISPACE.sub(" ", s)
    s = _MULTINEWLINE.sub("\n\n", s)
    return s.strip()


def has_fancy_font(text: str | None) -> bool:
    return any(_FANCY_LOW <= ord(ch) <= _FANCY_HIGH for ch in (text or ""))


def has_optout_language(text: str | None) -> bool:
    return bool(_OPTOUT_RE.search(text or ""))


def has_url_shortener(text: str | None) -> bool:
    return bool(_SHORTENER_RE.search(text or ""))


def analyze_sms_segments(text: str | None) -> SmsSegments:
    if not text:
        return SmsSegments("GSM-7", 0, 0)
    if all(ch in _GSM7_BASIC or ch in _GSM7_EXTENDED for ch in text):
        length = sum(2 if ch in _GSM7_EXTENDED else 1 for ch in text)
        limit, concat, encoding = _GSM_SINGLE, _GSM_MULTI, "GSM-7"
    else:
        length = sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)
        limit, concat, encoding = _UCS2_SINGLE, _UCS2_MULTI, "UCS-2"
    segments = 1 if length <= limit else -(-length // concat)
    return SmsSegments(encoding, segments, length)


def count_segments(text: str | None) -> int:
    return analyze_sms_segments(text).segments


def _spam_words(text: str) -> list[str]:
    low = text.lower()
    return [w for w in _SPAM_TRIGGER_WORDS if w in low]


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 10:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def lint_sms_text(text: str | None, *, is_marketing: bool = False) -> list[SmsFinding]:
    raw = text or ""
    clean = sanitize_sms_text(raw)
    if not clean:
        return [SmsFinding("EMPTY_BODY", SEVERITY_BLOCK, "Message is empty after cleaning")]
    findings: list[SmsFinding] = []
    if has_fancy_font(raw):
        findings.append(SmsFinding("FANCY_FONT", SEVERITY_WARN, "Stylized Unicode font converted to plain text"))
    elif clean != raw:
        findings.append(SmsFinding("NORMALIZED", SEVERITY_INFO, "Special characters normalized to plain text"))
    words = _spam_words(clean)
    if words:
        findings.append(SmsFinding("SPAM_WORDS", SEVERITY_WARN, "Spam-trigger words: " + ", ".join(words)))
    if has_url_shortener(clean):
        findings.append(
            SmsFinding("URL_SHORTENER", SEVERITY_WARN, "URL shorteners are often blocked by carriers; use a full link")
        )
    if _caps_ratio(clean) > 0.6:
        findings.append(SmsFinding("ALL_CAPS", SEVERITY_WARN, "Excessive capital letters look like spam"))
    if is_marketing and not has_optout_language(clean):
        findings.append(
            SmsFinding("NO_OPTOUT", SEVERITY_WARN, 'Marketing messages should include opt-out text ("Reply STOP")')
        )
    return findings
