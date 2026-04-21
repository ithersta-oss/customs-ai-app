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

# ----------- UTILS -----------

def normalize(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower()).strip()

def safe_json_parse(content):
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            return []
    return []

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

# ----------- EXCEL PARSER (ТОЧНЫЙ) -----------

def process_excel(df):
    items = []

    df = df.fillna("")

    for _, row in df.iterrows():
        values = [str(v) for v in row.values]

        name = " ".join(values[:3])
        article = values[0] if values else ""

        items.append({
            "name": name,
            "article": article,
            "quantity": "",
            "net_weight": "",
            "gross_weight": "",
            "price": "",
            "currency": "",
            "invoice": "",
            "invoice_number": ""
        })

    return items

# ----------- PDF AI -----------

def parse_pdf_ai(text):
    prompt = f"""
Extract ALL products.

Return JSON:
[
  {{
    "name": "",
    "article": "",
    "quantity": "",
    "net_weight": "",
    "gross_weight": "",
    "price": "",
    "currency": "",
    "invoice": "",
    "invoice_number": ""
  }}
]

{text[:6000]}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_parse(response.choices[0].message.content)

# ----------- MERGE (БЕЗ ОШИБОК) -----------

def merge_items(excel_items, pdf_items):
    merged = []

    for e in excel_items:
        best = e.copy()

        for p in pdf_items:
            if normalize(e["name"])[:15] in normalize(p["name"]):
                for key in best:
                    if not best[key] and p.get(key):
                        best[key] = p[key]

        merged.append(best)

    return merged

# ----------- COLUMN MAP -----------

def map_columns(columns):
    mapping = {}

    for col in columns:
        c = col.lower()

        if "наимен" in c:
            mapping[col] = "name"
        elif "артик" in c or "style" in c:
            mapping[col] = "article"
        elif "колич" in c:
            mapping[col] = "quantity"
        elif "нетто" in c:
            mapping[col] = "net_weight"
        elif "брутто" in c:
            mapping[col] = "gross_weight"
        elif "цена" in c:
            mapping[col] = "price"
        elif "валюта" in c:
            mapping[col] = "currency"
        elif "инвойс" in c:
            mapping[col] = "invoice"
        else:
            mapping[col] = ""

    return mapping

# ----------- MAIN -----------

if process:

    if not template_file or not docs:
        st.warning("Upload template and documents")
        st.stop()

    template_df = pd.read_excel(template_file)
    columns = list(template_df.columns)

    pdf_text = ""
    excel_items = []

    for doc in docs:
        if doc.name.endswith(".pdf"):
            pdf_text += extract_pdf(doc)
        else:
            df = pd.read_excel(doc)
            excel_items.extend(process_excel(df))

    pdf_items = parse_pdf_ai(pdf_text) if pdf_text else []

    items = merge_items(excel_items, pdf_items)

    column_map = map_columns(columns)

    rows = []

    for i, item in enumerate(items):
        row = {}

        for col in columns:
            field = column_map.get(col, "")
            row[col] = item.get(field, "")

        rows.append(row)

    result_df = pd.DataFrame(rows)

    st.success("Done")
    st.dataframe(result_df)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        result_df.to_excel(tmp.name, index=False)

        with open(tmp.name, "rb") as f:
            st.download_button("Download Excel", f, "result.xlsx")
