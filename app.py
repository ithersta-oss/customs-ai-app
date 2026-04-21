import streamlit as st
import pandas as pd
import pdfplumber
import re
import tempfile

# =========================
# UI
# =========================
st.set_page_config(page_title="AI Customs Assistant", layout="wide")
st.title("AI Customs Assistant")

col1, col2 = st.columns(2)

with col1:
    template_file = st.file_uploader("Upload TEMPLATE (Excel)", type=["xlsx"])

with col2:
    docs = st.file_uploader(
        "Upload DOCUMENTS (Specification / PDF)",
        type=["xlsx", "pdf"],
        accept_multiple_files=True
    )

process = st.button("Process")

# =========================
# UTILS
# =========================

def clean(text):
    return str(text).strip().lower()

def is_empty(val):
    return val is None or str(val).strip() == ""

# =========================
# STEP 1 — TEMPLATE ANALYSIS
# =========================

def analyze_template(df):
    mapping = {}
    debug = []

    for col in df.columns:
        c = clean(col)

        if "наимен" in c:
            mapping["name"] = col

        elif "артик" in c or "style" in c or "код" in c:
            mapping["article"] = col

        elif "колич" in c:
            mapping["quantity"] = col

        elif "нетто" in c:
            mapping["net_weight"] = col

        elif "брутто" in c:
            mapping["gross_weight"] = col

        elif "цена" in c:
            mapping["price"] = col

        elif "валюта" in c:
            mapping["currency"] = col

        elif "инвойс" in c:
            mapping["invoice"] = col

        elif "номер" in c:
            mapping["invoice_number"] = col

        debug.append(f"{col} -> {mapping.get(col, 'not mapped')}")

    return mapping, debug

# =========================
# STEP 2 — SPEC ANALYSIS
# =========================

def find_header_row(df):
    best_score = 0
    best_index = None

    for i in range(len(df)):
        row = [str(x).lower() for x in df.iloc[i].values]

        score = 0

        for cell in row:
            if "наимен" in cell or "description" in cell:
                score += 3
            if "колич" in cell or "qty" in cell:
                score += 2
            if "price" in cell or "цена" in cell:
                score += 1
            if "артик" in cell or "code" in cell:
                score += 1

        if score > best_score:
            best_score = score
            best_index = i

    return best_index


def extract_spec_items(df):
    df = df.fillna("")

    header_row = find_header_row(df)

    if header_row is None:
        st.error("❌ Header not found in Excel")
        return []

    st.write(f"📍 Header detected at row: {header_row}")

    df.columns = df.iloc[header_row]
    df = df.iloc[header_row + 1:]

    items = []

    for _, row in df.iterrows():
        row_dict = {str(k).lower(): str(v).strip() for k, v in row.items()}

        name = ""
        article = ""
        quantity = ""
        price = ""

        for col, val in row_dict.items():

            if "наимен" in col or "description" in col:
                name = val

            elif "артик" in col or "code" in col:
                article = val

            elif "колич" in col or "qty" in col:
                quantity = val

            elif "цен" in col or "price" in col:
                price = val

        # ❗ улучшенный фильтр
        if len(name) < 3:
            continue

        if name.lower() in ["nan", "none"]:
            continue

        items.append({
            "name": name,
            "article": article,
            "quantity": quantity,
            "price": price,
            "currency": "",
            "net_weight": "",
            "gross_weight": "",
            "invoice": "",
            "invoice_number": ""
        })

    return items

# =========================
# STEP 3 — PDF ANALYSIS
# =========================

def extract_pdf_text(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    except:
        pass
    return text

# =========================
# STEP 4 — MERGE LOGIC
# =========================

def merge_items(items):
    # пока просто возвращаем как есть (можно улучшить)
    return items

# =========================
# STEP 5 — BUILD RESULT
# =========================

def build_output(items, template_map, template_columns):

    rows = []

    for i, item in enumerate(items):
        row = {}

        for col in template_columns:

            if col in template_map.values():

                # находим ключ
                key = None
                for k, v in template_map.items():
                    if v == col:
                        key = k
                        break

                row[col] = item.get(key, "")

            else:
                row[col] = ""

        rows.append(row)

    return pd.DataFrame(rows)

# =========================
# MAIN
# =========================

if process:

    if not template_file:
        st.warning("Upload template")
        st.stop()

    if not docs:
        st.warning("Upload documents")
        st.stop()

    st.info("Processing...")

    # -------- TEMPLATE --------
    template_df = pd.read_excel(template_file)

    template_map, debug = analyze_template(template_df)

    st.write("🔍 Template mapping:")
    st.write(template_map)

    # -------- DOCUMENTS --------
    all_items = []

    for doc in docs:

        if doc.name.endswith(".xlsx"):
            df = pd.read_excel(doc)

            items = extract_spec_items(df)

            st.write(f"📄 {doc.name} → {len(items)} items")

            all_items.extend(items)

        elif doc.name.endswith(".pdf"):
            text = extract_pdf_text(doc)
            st.write(f"📄 PDF loaded ({len(text)} chars)")

    # -------- MERGE --------
    final_items = merge_items(all_items)

    # -------- OUTPUT --------
    result_df = build_output(
        final_items,
        template_map,
        template_df.columns
    )

    st.success("Done")
    st.dataframe(result_df)

    # download
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        result_df.to_excel(tmp.name, index=False)

        with open(tmp.name, "rb") as f:
            st.download_button("Download Excel", f, "result.xlsx")
