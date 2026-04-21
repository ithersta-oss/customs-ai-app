import streamlit as st
import pandas as pd
import pdfplumber
from openai import OpenAI
import json
import tempfile
import re

# ----------- API -----------
try:
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except:
    st.error("❌ API key not found. Add it in Streamlit Secrets.")
    st.stop()

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

# ----------- AI PARSER -----------
def safe_json_parse(content):
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            return []
    return []

def parse_pdf_ai(text):
   prompt = f"""
Ты работаешь с таможенными документами.

Колонки шаблона:
{columns}

Извлеки данные товаров максимально точно.

Если нет штрихкода — используй артикул или название.

Верни JSON:
[
  {{
    "barcode": "",
    "article": "",
    "name": "",
    "invoice": "",
    "invoice_number": ""
  }}
]

Текст:
{text[:8000]}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.choices[0].message.content
    return safe_json_parse(content)

# ----------- PACKING LIST -----------
def process_packing_list(df):
    df = df.copy()

    # всё приводим к строкам
    df = df.astype(str)

    text = df.to_string()

    # ---------- AI анализ ----------
    prompt = f"""
    Это упаковочный лист (packing list).
    Данные могут быть разбросаны.

    Найди для каждого товара:
    - штрихкод (или артикул)
    - вес нетто
    - вес брутто

    Важно:
    - вес может быть в разных строках
    - могут быть повторы → их нужно суммировать

    Верни JSON:
    [
      {{
        "key": "",  # barcode или article
        "net_weight": "",
        "gross_weight": ""
      }}
    ]

    Таблица:
    {text[:12000]}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.choices[0].message.content

        import re
        match = re.search(r'\[.*\]', content, re.DOTALL)

        if match:
            raw = json.loads(match.group())
        else:
            raw = []

    except:
        raw = []

    # ---------- агрегация ----------
    grouped = {}

    for r in raw:
        key = r.get("key")

        if not key:
            continue

        if key not in grouped:
            grouped[key] = {
                "barcode": key,
                "net_weight": 0,
                "gross_weight": 0
            }

        try:
            grouped[key]["net_weight"] += float(r.get("net_weight") or 0)
            grouped[key]["gross_weight"] += float(r.get("gross_weight") or 0)
        except:
            pass

    return list(grouped.values())

    # агрегируем
    grouped = {}

    for r in results:
        key = r.get("barcode") or r.get("article")

        if not key:
            continue

        if key not in grouped:
            grouped[key] = {
                "barcode": key,
                "net_weight": 0,
                "gross_weight": 0
            }

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

            # совпадение по barcode
            if item.get("barcode") and p.get("barcode"):
                if item["barcode"] == p["barcode"]:
                    score += 3

            # совпадение по артикулу
            if item.get("article") and p.get("article"):
                if str(item["article"]).lower() in str(p["article"]).lower():
                    score += 2

            # совпадение по названию
            if item.get("name") and p.get("barcode"):
                if str(item["name"]).lower()[:10] in str(p["barcode"]).lower():
                    score += 1

            if score > best_score:
                best_score = score
                best_match = p

        if best_match:
            item["net_weight"] = best_match.get("net_weight")
            item["gross_weight"] = best_match.get("gross_weight")

        merged.append(item)

    return merged

    for item in ai_items:
        key = item.get("barcode")

        match = next(
            (p for p in pl_items if p["barcode"] == key),
            None
        )

        if match:
            item["net_weight"] = match["net_weight"]
            item["gross_weight"] = match["gross_weight"]

        merged.append(item)

    return merged

# ----------- VALIDATION -----------
def validate(items):
    errors = []

    for item in items:

        net = item.get("net_weight")
        gross = item.get("gross_weight")

        try:
            if net and gross:
                if float(net) > float(gross):
                    errors.append(f"❌ Net > Gross ({item.get('name')})")
        except:
            pass

        if not item.get("net_weight"):
            errors.append(f"⚠️ Missing net weight ({item.get('name')})")

        if not item.get("gross_weight"):
            errors.append(f"⚠️ Missing gross weight ({item.get('name')})")

    return errors
# ----------- MAIN -----------
if process:

    if not template_file:
        st.warning("Upload template first")
        st.stop()

    if not docs:
        st.warning("Upload documents")
        st.stop()

    st.info("Processing...")

    try:
        template_df = pd.read_excel(template_file)
    except:
        st.error("Template read error")
        st.stop()

    columns = list(template_df.columns)

    # безопасно проверяем колонки
    if len(columns) < 5:
        st.error("Template has too few columns")
        st.stop()

    pdf_text = ""
    excel_tables = []

    for doc in docs:
        if doc.name.endswith(".pdf"):
            pdf_text += extract_pdf(doc)
        else:
            try:
                excel_tables.append(pd.read_excel(doc))
            except:
                pass

    # AI
    ai_items = parse_pdf_ai(pdf_text)

    # PL
    pl_items = []
    for df in excel_tables:
        pl_items.extend(process_packing_list(df))

    # Merge
    items = merge_data(ai_items, pl_items)

    # Validation
    errors = validate(items)

    if errors:
        st.warning(errors)

    # Build result
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
            elif idx == 5:
                row[col] = ""
            elif idx == 6:
                row[col] = item.get("net_weight")
            elif idx == 7:
                row[col] = item.get("gross_weight")
            elif idx == 8:
                row[col] = item.get("volume")
            elif idx == 9:
                row[col] = item.get("article")
            elif idx == 10:
                row[col] = item.get("certificate")
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
