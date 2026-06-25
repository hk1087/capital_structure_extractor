import pdfplumber, json, os, re
from dotenv import load_dotenv
load_dotenv()

# import verification function
from anchor import verify_claims, report

# model for extraction
MODEL = "claude-sonnet-4-6" 

# file path for iHeart first day filings
PDF_PATH = r"FILE_PATH_PDF" 

# PDF to text
def load_pdf_text(path):
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)

# find the capital-structure section
SECTION_ANCHORS = [
    r"Capital Structure",
    r"Total Funded Debt",
    r"Senior Debt Obligations",
    r"Debt Held by Debtor Affiliates",   # page 27 — the intercompany figures
    r"Cash Management Note",
    r"Legacy Notes",
    r"Priority Guarantee Notes",
]

def locate_sections(text, window=4000):
    spans, hits = [], []
    for anchor in SECTION_ANCHORS:
        for m in re.finditer(anchor, text, flags=re.IGNORECASE):
            start = max(0, m.start() - 200)
            spans.append((start, start + window))
            hits.append((anchor, m.start()))

    if not spans:
        return text[:window], []

    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    combined = "\n...\n".join(text[s:e] for s, e in merged)
    return combined, sorted(set(a for a, _ in hits))

#judgement layer or SKILL file
def load_skill(path="SKILL_capital_structure.md"):
    with open(path, encoding="utf-8") as f:
        return f.read()

def extract(section_text, skill_text):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=8192, system=skill_text,
        messages=[{"role": "user",
            "content": ("Extract the capital structure from the filing section below. "
                        "Return JSON only, conforming to the OUTPUT CONTRACT.\n\n"
                        "<filing_section>\n" + section_text + "\n</filing_section>")}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)

# run
if __name__ == "__main__":
    text = load_pdf_text(PDF_PATH)
    print("extracted chars:", len(text))

    section, hits = locate_sections(text)
    print("anchors matched:", hits)
    print("combined section length:", len(section))
    if not hits:
        print("No anchors — refusing to extract."); raise SystemExit

    extraction = extract(section, load_skill())    
    print("tranches extracted:", len(extraction.get("tranches", [])))

    verified, rejected = verify_claims(extraction["tranches"], section)
    report(verified, rejected)
    extraction["tranches"] = verified        # only source-verified claims continue

    json.dump(extraction, open("iheart.json", "w"), indent=2)
    print("wrote iheart.json")
