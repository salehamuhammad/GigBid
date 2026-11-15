"""Skill lexicon: canonical skill names + aliases. Used for requirement extraction, the skill
graph and claim verification. Extended at ingestion with skills found in portfolio metadata."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from agent.settings import get_settings


@lru_cache
def lexicon() -> dict[str, list[str]]:
    p = get_settings().data_dir / "skills_lexicon.json"
    raw = json.loads(p.read_text()) if p.exists() else {}
    return {k: v.get("aliases", []) for k, v in raw.items()}


@lru_cache
def _patterns() -> list[tuple[str, re.Pattern]]:
    out = []
    for skill, aliases in lexicon().items():
        names = sorted([skill, *aliases], key=len, reverse=True)
        out.append((skill, re.compile(r"(?<![\w])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.I)))
    return out


def extract_skills(text: str) -> list[str]:
    """Canonical skills named (by name or alias) in `text`, in order of first mention."""
    found = []
    for skill, pat in _patterns():
        m = pat.search(text or "")
        if m: found.append((m.start(), skill))
    return [s for _, s in sorted(found)]


@lru_cache(maxsize=20000)
def expand_aliases(text: str) -> str:
    """Append canonical names and aliases for every skill mentioned (query expansion)."""
    extra = []
    for s in extract_skills(text):
        extra += [s, *lexicon().get(s, [])]
    return (text + " " + " ".join(dict.fromkeys(extra))).strip()


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Za-z]")
STOP = set("a an the and or of to in on for with by is are was were be been it this that as at from we you i our your my will can have has had do does not no but if so than then they them he she his her its about into over more most such very who what when which how all any each per via using use used need needs needed please must should would could work working like also etc including include looking someone experience strong hands required essential responsible following company help".split())


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in STOP and len(t) > 1]
