"""Deterministic text checks shared by eval verification and the judge."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s%.\-/]")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")

REFUSAL_PATTERNS = [
    r"\bcan'?t answer\b", r"\bcannot answer\b", r"\bunable to (?:answer|find|provide)\b",
    r"\bnot (?:covered|mentioned|specified|provided|available|found) in (?:the|these|my)\b",
    r"\bno (?:information|mention|details?) (?:about|on|regarding|in)\b",
    r"\bdo(?:es)?n'?t (?:contain|include|have|cover|specify)\b", r"\bdo not (?:contain|have|cover|know)\b",
    r"\boutside (?:the|my) (?:scope|documents)\b", r"\bnot able to (?:answer|help)\b",
    r"\bI (?:don'?t|do not) have (?:that|this|any|enough)\b",
    r"\bI(?:'m| am) (?:only|designed to|here to)\b", r"\bI can only (?:help|answer|assist)\b",
    r"\b(?:isn'?t|is not|aren'?t|are not) (?:covered|part of|something I)\b",
]
_REFUSAL_RE = re.compile("|".join(REFUSAL_PATTERNS), re.I)

_STOP = set(
    "a an the of to in on for and or is are was were be been by with as at from that this it its "
    "what which who how when where why do does did can i my me we you your they their there not no "
    "have has had will would should may must per if then than so such any all".split()
)


_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‚′"), "'") | dict.fromkeys(map(ord, "“”„"), '"')


def norm(s: str) -> str:
    s = s.translate(_DASHES).translate(_QUOTES).replace(" ", " ").replace(" ", " ").lower()
    if _NUM.search(s):
        s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def looks_like_refusal(text: str, refusal_phrase: str = "") -> bool:
    if not text.strip():
        return True
    if refusal_phrase and norm(refusal_phrase)[:40] in norm(text):
        return True
    return bool(_REFUSAL_RE.search(text))


def _canon_num(n: str) -> str:
    """'2,675.00' and '2675.0' are the same number: compare by value, not by spelling."""
    n = n.replace(",", "").rstrip(".")
    try:
        f = float(n)
    except ValueError:
        return n
    return str(int(f)) if f == int(f) else repr(round(f, 6))


def numbers(s: str) -> set[str]:
    return {_canon_num(n) for n in _NUM.findall(s)}


def fact_in(fact: str, text: str) -> bool:
    """Is a fact present in text? Exact normalised substring; numbers must match exactly."""
    f, t = norm(fact), norm(text)
    if not f:
        return True
    if f in t:
        return True
    fn = numbers(f)
    if fn and not fn <= numbers(t):
        return False
    if len(f.split()) >= 3:
        return fuzz.partial_ratio(f, t) >= 90
    return False


def content_tokens(s: str) -> set[str]:
    return {w for w in norm(s).split() if len(w) > 2 and w not in _STOP}


def support_ratio(answer: str, context: str, question: str = "") -> tuple[float, set[str]]:
    """Share of the answer's content tokens found in context/question; plus unsupported numbers."""
    ans_t = content_tokens(answer)
    ref = content_tokens(context) | content_tokens(question)
    ratio = (len(ans_t & ref) / len(ans_t)) if ans_t else 1.0
    bad = numbers(answer) - numbers(context) - numbers(question)
    return ratio, bad
