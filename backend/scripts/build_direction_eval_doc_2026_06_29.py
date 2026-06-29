"""Render the BLIND direction_eval_120 CSV into a readable doc for labeling.
One block per row: #num, ticker, id (for mapping back), full untruncated quote, blank TRUE: line.
HIDES stored_direction. Emits plain text (-> Google Doc) and, if python-docx is present, a .docx.
"""
import os, csv

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "direction_eval_120_2026-06-29.csv")
TXT = os.path.join(HERE, "direction_eval_120_doc.txt")
DOCX = os.path.join(HERE, "Direction Eval — label here (full 120).docx")

TITLE = "Direction Eval — label here (full 120)"
NOTE = [
    "HOW TO LABEL",
    "For each row, write the speaker's TRUE forward direction ON THAT TICKER on the TRUE: line "
    "— bullish, bearish, or neutral.",
    "• Judge the direction for the TICKER shown, not the market overall.",
    "• Inverse / short ETFs (SH, SOXS, SQQQ, TBT, UUP): a market-crash or rates-up view = "
    "BULLISH on the ETF (it goes UP when the market / bonds fall). Label the ETF, not the market.",
    "• If you genuinely cannot tell, write neutral.",
]

rows = list(csv.DictReader(open(CSV, newline="")))
assert len(rows) == 120, f"expected 120 rows, got {len(rows)}"

# ---- plain text ----
lines = [TITLE, ""]
lines += NOTE
lines += ["", "=" * 60, ""]
for i, r in enumerate(rows, 1):
    lines.append(f"#{i}  ${r['ticker']}   (id {r['id']})")
    lines.append(r["full_quote"])
    lines.append("TRUE: ")
    lines += ["", "-" * 40, ""]
open(TXT, "w").write("\n".join(lines))
print(f"txt -> {TXT}  ({os.path.getsize(TXT)} bytes, {len(rows)} rows)")

# ---- docx (hand-built via stdlib zipfile; no python-docx needed) ----
import zipfile
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def para(text, bold=False, size=None):
    rpr = ""
    if bold or size:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + \
              (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "") + "</w:rPr>"
    return (f'<w:p>{("<w:pPr>"+rpr+"</w:pPr>") if rpr else ""}'
            f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')


body = [para(TITLE, bold=True, size=36)]
for n in NOTE:
    body.append(para(n))
body.append("<w:p/>")
for i, r in enumerate(rows, 1):
    body.append(para(f"#{i}   ${r['ticker']}   (id {r['id']})", bold=True))
    body.append(para(r["full_quote"]))
    body.append(para("TRUE: "))
    body.append(para("—" * 30))
document_xml = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:document xmlns:w="{W}"><w:body>' + "".join(body) +
    '<w:sectPr/></w:body></w:document>')

content_types = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>')
root_rels = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
doc_rels = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')

with zipfile.ZipFile(DOCX, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", content_types)
    z.writestr("_rels/.rels", root_rels)
    z.writestr("word/_rels/document.xml.rels", doc_rels)
    z.writestr("word/document.xml", document_xml)
print(f"docx -> {DOCX}  ({os.path.getsize(DOCX)} bytes)")
