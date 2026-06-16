"""Conservative transcript post-processing without hallucinating content."""

from __future__ import annotations

import re

# Common STT / business acronyms (case-insensitive keys).
_ACRONYMS = {
    "api": "API",
    "apis": "APIs",
    "stt": "STT",
    "tts": "TTS",
    "ai": "AI",
    "ml": "ML",
    "kyc": "KYC",
    "otp": "OTP",
    "upi": "UPI",
    "crm": "CRM",
    "erp": "ERP",
    "hr": "HR",
    "qa": "QA",
    "ui": "UI",
    "ux": "UX",
    "id": "ID",
    "ids": "IDs",
    "url": "URL",
    "urls": "URLs",
    "http": "HTTP",
    "https": "HTTPS",
    "json": "JSON",
    "xml": "XML",
    "sql": "SQL",
    "aws": "AWS",
    "gcp": "GCP",
    "saas": "SaaS",
    "paas": "PaaS",
    "roi": "ROI",
    "kpi": "KPI",
    "kpis": "KPIs",
    "inr": "INR",
    "usd": "USD",
}

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}


def postprocess_transcript(text: str) -> str:
    """Apply punctuation, capitalization, acronym, and number normalization."""
    if not text or not text.strip():
        return ""

    cleaned = re.sub(r"\s+", " ", text.strip())

    # Sentence boundaries on common discourse markers (conservative).
    for marker in (" today ", " however ", " therefore ", " meanwhile "):
        cleaned = cleaned.replace(marker, marker.replace(" ", ". ", 1))

    tokens = cleaned.split(" ")
    out: list[str] = []
    for i, token in enumerate(tokens):
        bare = token.strip(".,!?;:")
        lower = bare.lower()
        if lower in _ACRONYMS:
            out.append(_attach_punct(_ACRONYMS[lower], token))
        elif lower in _NUMBER_WORDS and i > 0 and tokens[i - 1].lower() == "version":
            out.append(_attach_punct(f"Version {_NUMBER_WORDS[lower]}", token))
        elif re.fullmatch(r"v\d+", lower):
            out.append(_attach_punct(bare.upper(), token))
        elif re.fullmatch(r"\d+", bare):
            out.append(token)
        else:
            out.append(_capitalize_token(token, sentence_start=i == 0 or _ends_sentence(tokens[i - 1])))

    result = " ".join(out)
    if result and result[-1] not in ".!?":
        result += "."
    return result


def _attach_punct(replacement: str, original: str) -> str:
    trail = original[len(original.rstrip(".,!?;:")) :]
    return replacement + trail


def _capitalize_token(token: str, *, sentence_start: bool) -> str:
    if not sentence_start:
        return token
    m = re.match(r"^([^a-zA-Z]*)([a-zA-Z])(.*)$", token)
    if not m:
        return token
    return f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"


def _ends_sentence(token: str) -> bool:
    return bool(token) and token.rstrip()[-1] in ".!?"
