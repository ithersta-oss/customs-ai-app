import streamlit as st
import pandas as pd
import pdfplumber
from openai import OpenAI
import json
import tempfile
import re

# ----------- API -----------
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

st.set_page_config(page_title="Customs AI", layout="wide")
st.title("AI Customs Assistant")

# ----------- UI -----------
col1, col2 = st.columns(2)

with col1:
    template_file = st.file_uploader("Upload your Excel template", type=["xlsx"])

with col2:
    docs = st.file_uploader(
        "Upload your documents (PDF, Excel)",
        type=["pdf", "xlsx"],
        accept_multiple_files=True
    )

process = st.button("Process")

# ----------- PDF -----------
def extract_pdf(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except:
        pass
    return text

# ----------- JSON SAFE -----------
def safe_json_parse(content):
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            return []
    return []

# ----------- AI PARSER (PDF ONLY) -----------
def parse_pdf_ai(text):
    prompt = f"""
Extract ALL products from this document.

IMPORTANT:
- There can be many items (10+)
- Return ALL rows, not one

Return JSON:
[
  {{
    "barcode": "",
    "article": "",
    "name": "",
    "invoice": "",
    "invoice_number": ""
  }}
]

{text[:8000]}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_parse(response.choices[0].message.content)

# ----------- EXCEL PARSER (ТОЧНЫЙ) -----------
def process_excel_invoice(df):
    items = []

    for _, row in df.iterrows():
        values = [str(v) for v in row.values]

        items.append({
            "barcode": "",
            "article": " ".join(values[:2]),
            "name": " ".join(values[:3]),
            "invoice": "",
            "invoice_number": ""
        })

    return items

# ----------- PACKING LIST (AI) -----------
def process_packing_list(df):
    text = df.astype(str).to_string()

    prompt = f"""
Packing list.

Find:
- product (barcode or article)
- net weight
- gross weight

Return JSON:
[
  {{
    "key": "",
    "net_weight": "",
    "gross_weight": ""
  }}
]

{text[:12000]}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        raw = safe_json_parse(response.choices[0].message.content)
    except:
        raw = []

    grouped = {}

    for r in raw:
        key = r.get("key")
        if not key:
            continue

        if key not in grouped:
            grouped[key] = {"barcode": key, "net_weight": 0, "gross_weight": 0}

        try:
            grouped[key]["net_weight"] += float(r.get("net_weight") or 0)
            grouped[key]["gross_weight"] += float(r.get("gross_weight") or 0)
        except:
            pass

    return list(grouped.values())

# ----------- MERGE -----------
def merge_data(ai_items, pl_items):
    merged = []

    for item in ai_items:
        best_match = None
        best_score = 0

        for p in pl_items:
            score = 0

            if item.get("article") and p.get("barcode"):
                if item["article"].lower()[:10] in p["barcode"].lower():
                    score += 2

            if item.get("name") and p.get("barcode"):
                if item["name"].lower()[:10] in p["barcode"].lower():
                    score += 1

            if score > best_score:
                best_score = score
                best_match = p

        if best_match:
            item["net_weight"] = best_match.get("net_weight")
            item["gross_weight"] = best_match.get("gross_weight")

        merged.append(item)

    return merged

# ----------- MAIN -----------
if process:

    if not template_file or not docs:
        st.warning("Upload template and documents")
        st.stop()

    st.info("Processing...")

    template_df = pd.read_excel(template_file)
    columns = list(template_df.columns)

    pdf_text = ""
    excel_items = []
    excel_tables = []

    for doc in docs:
        if doc.name.endswith(".pdf"):
            pdf_text += extract_pdf(doc)
        else:
            df = pd.read_excel(doc)
            excel_tables.append(df)

            # извлекаем напрямую
            excel_items.extend(process_excel_invoice(df))

    pdf_items = parse_pdf_ai(pdf_text) if pdf_text else []
    ai_items = pdf_items + excel_items

    # упаковочные
    pl_items = []
    for df in excel_tables:
        pl_items.extend(process_packing_list(df))

    items = merge_data(ai_items, pl_items)

    # ----------- OUTPUT -----------
    rows = []

    for i, item in enumerate(items):
        row = {}

        for idx, col in enumerate(columns):
            if idx == 0:
                row[col] = i + 1
            elif idx == 1:
                row[col] = item.get("invoice")
            elif idx == 2:
                row[col] = item.get("invoice_number")
            elif idx == 3:
                row[col] = item.get("barcode")
            elif idx == 4:
                row[col] = item.get("name")
            elif idx == 6:
                row[col] = item.get("net_weight")
            elif idx == 7:
                row[col] = item.get("gross_weight")
            elif idx == 9:
                row[col] = item.get("article")
            else:
                row[col] = ""

        rows.append(row)

    result_df = pd.DataFrame(rows)

    st.success("Done")
    st.dataframe(result_df)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        result_df.to_excel(tmp.name, index=False)

        with open(tmp.name, "rb") as f:
            st.download_button("Download Excel", f, "result.xlsx")
