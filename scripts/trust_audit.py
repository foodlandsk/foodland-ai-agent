"""Automated audit for whether the bot's answers can be trusted - as
opposed to scripts/consistency_audit.py, which checks whether a query
gets ROUTED to the right place, this checks whether the bot ever ends up
in a state where what it SAYS doesn't match what it actually found.

Motivating incident: a replacement/alternative query ("alternativa ku
Kikkoman sojovej omacke") could end up with zero matching products after
excluding the named brand, yet the AI-generated answer for
intent="replacement_products" always claims "here are alternatives below"
per its system prompt - the prompt has no conditional for "unless there
are none". A safety net was added in alternative_products_for_subject()
so brand-exclusion can never return an empty list, but that fix was
verified against only 2 brands (Kikkoman, Squid Brand) by hand. This
script re-checks the same invariant across every brand in every
replacement category, entirely offline - it calls the routing/search
functions directly and never starts the FastAPI app or calls OpenAI, so
it is safe to run as often as needed without the cost/risk that comes
from testing this class of bug through live /chat requests (every
replacement_products reply is AI-generated - see should_use_fast_chat_
answer() - so hitting /chat repeatedly to test this exact thing is
exactly the kind of repeated-OpenAI-call loop this project's standing
rule warns against).

Checks:
    1. --empty-alternatives: for every (category, brand) pair reachable
       via the replacement/alternative flow, alternative_products_for_
       subject(..., exclude_brand=brand) must never return zero products.
    2. --pii-leak: redact_pii() must strip every email/phone pattern in a
       battery of synthetic customer-style messages before they'd reach
       an analytics log line.

Usage:
    python scripts/trust_audit.py                    # both checks
    python scripts/trust_audit.py --empty-alternatives
    python scripts/trust_audit.py --pii-leak
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import main as bot  # noqa: E402


def check_empty_alternatives() -> list[str]:
    findings = []
    for subject in bot.REPLACEMENT_SUBJECT_ALIASES:
        category_products = bot.cached_search_products(bot.products, subject, 30)
        brands = sorted({str(p.get("brand") or "").strip() for p in category_products if p.get("brand")})
        for brand in brands:
            recs = bot.alternative_products_for_subject(bot.products, bot.knowledge, subject, 6, exclude_brand=brand)
            if not recs:
                findings.append(
                    f'subject="{subject}" exclude_brand="{brand}": alternative_products_for_subject() '
                    f"returned ZERO products - a replacement_products reply for this pair would tell the "
                    f"customer alternatives are below with nothing under it"
                )
    return findings


_PII_SAMPLES = [
    "kontaktujte ma na jan.novak@gmail.com prosim",
    "moje cislo je +421 905 123 456",
    "email: zakaznik123@firma.sk, tel. 0905123456",
    "volajte na +420 777 888 999 kedykolvek",
    "bez kontaktnych udajov v tejto sprave",
]


def check_pii_leak() -> list[str]:
    findings = []
    for sample in _PII_SAMPLES:
        redacted = bot.redact_pii(sample)
        if "@" in redacted and "[email]" not in redacted:
            findings.append(f'redact_pii() left an email-like pattern in: "{sample}" -> "{redacted}"')
        digits_run = sum(1 for ch in redacted if ch.isdigit())
        if digits_run >= 7:
            findings.append(f'redact_pii() left a phone-like digit run in: "{sample}" -> "{redacted}"')
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--empty-alternatives", action="store_true", help="only run the empty-alternatives check")
    parser.add_argument("--pii-leak", action="store_true", help="only run the PII-redaction check")
    args = parser.parse_args()

    run_empty = args.empty_alternatives or not (args.empty_alternatives or args.pii_leak)
    run_pii = args.pii_leak or not (args.empty_alternatives or args.pii_leak)

    exit_code = 0

    if run_empty:
        print("=== Replacement/alternative queries that could return zero products ===")
        findings = check_empty_alternatives()
        if findings:
            exit_code = 1
            for line in findings:
                print(" -", line)
        else:
            print(" (none found)")
        print()

    if run_pii:
        print("=== PII redaction leaks ===")
        findings = check_pii_leak()
        if findings:
            exit_code = 1
            for line in findings:
                print(" -", line)
        else:
            print(" (none found)")
        print()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
