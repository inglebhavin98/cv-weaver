"""Text sanitization utilities for machine parsers.

ATS systems, YAML emitters, and LaTeX compilers are sensitive to Unicode
punctuation and decorative characters. This module normalizes text so it
survives mechanical processing without corruption.
"""

SMART_QUOTE_MAP: dict[str, str] = {
    "“": '"',   # left double quotation mark
    "”": '"',   # right double quotation mark
    "‘": "'",   # left single quotation mark
    "’": "'",   # right single quotation mark
    "‚": ",",   # single low-9 quotation mark
    "„": '"',   # double low-9 quotation mark
}

FANCY_BULLETS: set[str] = {
    "✓",  # ✓
    "→",  # →
    "•",  # •
    "◦",  # ◦
    "▸",  # ▸
    "▹",  # ▹
    "►",  # ►
    "▻",  # ▻
    "▪",  # ▪
    "▫",  # ▫
    "‣",  # ‣
    "›",  # ›
    "»",  # »
    "❖",  # ❖
    "◆",  # ◆
    "◇",  # ◇
    "✔",  # ✔
    "✗",  # ✗
    "✘",  # ✘
    "×",  # ×
    "☐",  # ☐
    "☑",  # ☑
    "☒",  # ☒
}


def sanitize_for_machine_parsers(text: str) -> str:
    """Sanitize text for machine parsers.

    Replacements applied in order:
    1. Smart quotes → straight quotes
    2. Em-dashes and en-dashes → hyphens
    3. Fancy unicode bullets → removed

    Args:
        text: Raw text, typically a rendered_bullet or result string.

    Returns:
        Cleaned text safe for ATS, YAML, and LaTeX consumption.
    """
    # 1. Smart quotes
    for smart, straight in SMART_QUOTE_MAP.items():
        text = text.replace(smart, straight)

    # 2. Dashes
    text = text.replace("—", "-")   # em dash
    text = text.replace("–", "-")   # en dash

    # 3. Fancy bullets
    for bullet in FANCY_BULLETS:
        text = text.replace(bullet, "")

    return text
