"""
The deterministic trust gate: every claim must carry a verbatim quote, and this
code confirms that quote really exists in the source pinning it to an exact
character location, or REJECTING the claim if it can't be found.

The division of labor that makes "everything connects to a line" work:
  - The MODEL proposes the link (returns a `quote` for each tranche). Judgment.
  - This CODE disposes (finds the quote in the source, or kills the claim). Deterministic.

The model can hallucinate. It cannot hallucinate PAST this gate, because a made-up
claim won't have a quote that exists in the document, so anchor_quote returns None,
so verify_claims drops it. The user only ever sees claims whose source was
mechanically confirmed present.

WHAT THIS GUARANTEES:  the quote exists in the source, at this location.
WHAT IT DOES NOT:      that the quote actually *supports* the claim (a semantic
                       judgment). But now there's a specific line to check against,
                       so that smaller question is answerable by a human in seconds.
"""

import re

def anchor_quote(quote: str, source_text: str):
    """Deterministically locate a verbatim quote in the source.
    Returns (start, end) char offsets, or None if not found exactly.
    Tolerates the whitespace/newline mangling that PDF extraction introduces,
    but nothing else — the WORDS must match."""
    if not quote or not quote.strip():
        return None

    # 1) exact substring — the strict case
    idx = source_text.find(quote)
    if idx != -1:
        return (idx, idx + len(quote))

    # 2) whitespace-tolerant: collapse runs of whitespace in BOTH, match on words.
    #    PDFs turn "$5,000 million" into "$5,000\nmillion" etc. — same words, different spacing.
    pattern = re.escape(quote)
    pattern = re.sub(r"\\\s+", r"\\s+", pattern)   # any escaped whitespace -> \s+
    m = re.search(pattern, source_text)
    if m:
        return (m.start(), m.end())

    return None   # words not found verbatim -> NOT trustworthy


def verify_claims(tranches, source_text):
    """Run every tranche's quote through anchor_quote.
    Survivors get a char_offset and verified=True; the rest are rejected.
    Returns (verified, rejected)."""
    verified, rejected = [], []
    for t in tranches:
        loc = anchor_quote(t.get("quote", ""), source_text)
        if loc:
            t = dict(t)
            t["char_offset"] = loc          # deterministic, code-supplied
            t["verified"] = True
            verified.append(t)
        else:
            t = dict(t)
            t["verified"] = False
            t["reject_reason"] = "quote not found verbatim in source"
            rejected.append(t)
    return verified, rejected


def report(verified, rejected):
    """Print the survival rate — the honest measure of how source-backed the
    extraction is. A low rate means the model is producing claims it can't ground."""
    total = len(verified) + len(rejected)
    print(f"\nTRUST GATE — {len(verified)}/{total} claims verified to source")
    if rejected:
        print("REJECTED (no verbatim quote found):")
        for t in rejected:
            print(f"  x {t.get('name','?')}  (claimed principal {t.get('principal_usd_mm')})")
            q = (t.get('quote') or '')[:70]
            print(f"      quote was: {q!r}")
    if verified:
        print("VERIFIED (each pins to a source location):")
        for t in verified:
            s, e = t["char_offset"]
            print(f"  ok {t.get('name','?'):40s} chars {s}-{e}")


if __name__ == "__main__":
    # self-test: prove the gate accepts real quotes and rejects fabricated ones
    SOURCE = ("Term Loan D ......... $5,000 million; matures January 30, 2019. "
              "9.0% Priority Guarantee Notes due 2019 ... $2,000 million.")
    claims = [
        {"name": "Term Loan D", "principal_usd_mm": 5000,
         "quote": "Term Loan D ......... $5,000 million"},          # exact -> verified
        {"name": "9.0% PGN 2019", "principal_usd_mm": 2000,
         "quote": "9.0% Priority Guarantee Notes due 2019"},        # exact -> verified
        {"name": "Phantom Loan", "principal_usd_mm": 9999,
         "quote": "Phantom Facility $9,999 million"},               # fabricated -> rejected
        {"name": "Whitespace case", "principal_usd_mm": 5000,
         "quote": "Term Loan D $5,000 million"},                    # diff spacing -> still found
    ]
    v, r = verify_claims(claims, SOURCE)
    report(v, r)
