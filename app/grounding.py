"""
app/grounding.py  -  Grounding Validator

Krok medzi Guardrails a Response Composer.
Overuje, ze LLM odpoved neobsahuje URL ani product ID, ktore neboli
v allowed_sources konkretnej requesty.

Princip: agent nesmie vymyslat. Toto nie je len prompt instrukcia -
je to strojova kontrola po generovani odpovede.

Pouzitie:
    from app.grounding import validate_answer, GroundingResult
    result = validate_answer(answer_text, allowed_urls, allowed_product_ids)
    if result.has_violations:
        answer_text = result.sanitized_answer
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class GroundingResult:
    sanitized_answer: str
    violations: list[str] = field(default_factory=list)
    removed_urls: list[str] = field(default_factory=list)
    removed_product_refs: list[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)


def _strip_disallowed_urls(answer: str, allowed_urls: set[str]) -> tuple[str, list[str]]:
    """
    Odstrani z odpovede URL ktore nie su v allowed_urls.
    Zachova markdown odkaz ako text bez URL: [Produkt](URL) -> Produkt
    Bare URL odstrani uplne.
    """
    removed: list[str] = []

    def md_replace(m: re.Match) -> str:
        label, url = m.group(1), m.group(2).rstrip(".,);>\"")
        if url in allowed_urls:
            return m.group(0)
        removed.append(url)
        return label

    sanitized = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", md_replace, answer)

    def bare_replace(m: re.Match) -> str:
        url = m.group(0).rstrip(".,);>\"")
        suffix = m.group(0)[len(url):]
        if url in allowed_urls:
            return m.group(0)
        removed.append(url)
        return suffix

    sanitized = re.sub(r"https?://[^\s)>\"]+", bare_replace, sanitized)
    return sanitized, removed


def _check_invented_prices(answer: str, allowed_prices: set[str]) -> list[str]:
    """
    Detekuje ceny v odpovedi ktore neboli v source datach.
    Hlade vzory ako "1,99 EUR", "2.50 EUR", "4 EUR" a pod.
    """
    suspicious: list[str] = []
    price_pattern = re.compile(
        r"\b(\d{1,4}[.,]\d{2})\s*(?:EUR|euro|eur)\b"
        r"|\b(\d{1,4})\s*(?:EUR|euro|eur)\b",
        re.IGNORECASE,
    )
    for m in price_pattern.finditer(answer):
        price_str = m.group(0).strip()
        digits = re.sub(r"[^0-9,.]", "", price_str).replace(",", ".")
        if digits and digits not in allowed_prices:
            suspicious.append(price_str)
    return suspicious


def validate_answer(
    answer: str,
    allowed_urls: set[str],
    allowed_product_ids: set[str] | None = None,
    allowed_prices: set[str] | None = None,
    *,
    strict_prices: bool = False,
) -> GroundingResult:
    """
    Overuje a cisti LLM odpoved.

    Args:
        answer: raw text od LLM
        allowed_urls: URL ktore su dokazane v source datach tejto requesty
        allowed_product_ids: product ID ktore su dokazane v source datach
        allowed_prices: ceny (format "X.XX") ktore su dokazane v source datach
        strict_prices: ak True, suspicious ceny sposobia varovanie (nie blokovanie)

    Returns:
        GroundingResult so sanitizovanou odpovedou a zoznamom naruseni
    """
    if strict_prices and allowed_prices is None and allowed_product_ids:
        looks_like_prices = all(re.fullmatch(r"\d+(?:\.\d{2})?", str(value)) for value in allowed_product_ids)
        if looks_like_prices:
            allowed_prices = {str(value) for value in allowed_product_ids}
            allowed_product_ids = None

    violations: list[str] = []
    removed_product_refs: list[str] = []

    sanitized, removed_urls = _strip_disallowed_urls(answer, allowed_urls)
    if removed_urls:
        violations.append(f"removed_ungrounded_urls: {removed_urls}")

    if strict_prices and allowed_prices is not None:
        suspicious_prices = _check_invented_prices(sanitized, allowed_prices)
        if suspicious_prices:
            violations.append(f"suspicious_prices_not_in_source: {suspicious_prices}")
            sanitized = sanitized.rstrip() + (
                "\n\n_(Ceny overte v detaile produktu - mozu sa lisit.)_"
            )

    return GroundingResult(
        sanitized_answer=sanitized,
        violations=violations,
        removed_urls=removed_urls,
        removed_product_refs=removed_product_refs,
    )


def collect_allowed_urls(
    products: list[dict],
    knowledge_matches: dict | None = None,
) -> set[str]:
    """Zbierka URL z produktov a knowledge matchov pre grounding check."""
    urls: set[str] = set()
    for p in products or []:
        for key in ("link", "url", "image_link"):
            v = str(p.get(key) or "").strip()
            if v.startswith(("http://", "https://")):
                urls.add(v)
    for hits in (knowledge_matches or {}).values():
        for hit in hits:
            for v in hit.get("record", {}).values():
                text = str(v or "").strip()
                if text.startswith(("http://", "https://")):
                    urls.add(text)
    return urls


def collect_allowed_prices(products: list[dict]) -> set[str]:
    """Zbierka cien z produktov pre grounding check."""
    prices: set[str] = set()
    for p in products or []:
        for key in ("price", "sale_price", "effective_price"):
            v = p.get(key)
            if v is not None:
                try:
                    prices.add(f"{float(v):.2f}")
                except (TypeError, ValueError):
                    pass
    return prices

