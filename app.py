from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
SAMPLE_PATH = APP_DIR / "data" / "sample_tenders.csv"

st.set_page_config(
    page_title="Smart Tender & Procurement Monitor",
    page_icon="📑",
    layout="wide",
)

st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2.5rem;}
[data-testid="stMetric"] {border:1px solid #2a3447;border-radius:14px;padding:12px 14px;background:#151d2e;}
.pill {border:1px solid #2a3447;border-radius:999px;padding:4px 9px;display:inline-block;margin:0 6px 6px 0;font-size:.78rem;}
</style>
""",
    unsafe_allow_html=True,
)

KEYWORDS = [
    "logistics", "supply chain", "warehouse", "inventory", "procurement",
    "aviation", "aircraft", "spares", "parts", "transport", "freight",
    "material", "stores", "fuel", "maintenance", "mro",
]

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

@st.cache_data
def load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_PATH)

@st.cache_data(ttl=1800)
def fetch_tenders_guru(country_code: str, page: int = 1) -> pd.DataFrame:
    """Fetch public procurement data from Tenders Guru.
    Country codes currently exposed in the UI: hu, pl.
    """
    url = f"https://tenders.guru/api/{country_code}/tenders"
    r = requests.get(url, params={"page": page}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    records = payload.get("data", payload if isinstance(payload, list) else [])
    rows = []
    for item in records:
        if not isinstance(item, dict):
            continue
        tender_id = item.get("id", "")
        title = item.get("title", "")
        desc = item.get("description", "")
        published = item.get("date", item.get("publication_date", ""))
        deadline = item.get("deadline", item.get("deadline_date", item.get("submission_deadline", "")))
        buyer = item.get("purchaser", item.get("buyer", item.get("contracting_authority", "")))
        if isinstance(buyer, dict):
            buyer = buyer.get("name", buyer.get("title", ""))
        amount = item.get("value", item.get("amount", item.get("estimated_value", "")))
        currency = item.get("currency", "")
        rows.append({
            "source": f"Tenders Guru ({country_code.upper()})",
            "source_id": tender_id,
            "title": clean_text(title),
            "description": clean_text(desc),
            "buyer": clean_text(buyer),
            "country": "Hungary" if country_code == "hu" else "Poland",
            "city": "",
            "published_date": clean_text(published),
            "deadline": clean_text(deadline),
            "estimated_value": amount,
            "currency": clean_text(currency),
            "category": "Public Procurement",
            "source_url": f"https://tenders.guru/{country_code}/tender/{tender_id}" if tender_id else f"https://tenders.guru/{country_code}/tenders",
        })
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600)
def fx_to_usd(currencies: tuple[str, ...]) -> dict[str, float]:
    fallback = {"USD":1.0,"EUR":1.17,"GBP":1.33,"HUF":0.0030,"PLN":0.275,"AED":0.2723,"QAR":0.2747,"SAR":0.2666}
    out = {}
    for cur in currencies:
        cur = cur.upper()
        if not cur:
            continue
        if cur == "USD":
            out[cur] = 1.0
            continue
        try:
            r = requests.get(
                "https://api.frankfurter.app/latest",
                params={"from":cur,"to":"USD"},
                timeout=8,
            )
            r.raise_for_status()
            out[cur] = float(r.json()["rates"]["USD"])
        except Exception:
            out[cur] = fallback.get(cur, 1.0)
    return out

def make_uid(row: pd.Series) -> str:
    raw = "|".join([
        clean_text(row.get("title")).lower(),
        clean_text(row.get("buyer")).lower(),
        clean_text(row.get("country")).lower(),
        clean_text(row.get("deadline")).lower(),
    ])
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:14]

def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in [
        "source","source_id","title","description","buyer","country","city",
        "published_date","deadline","estimated_value","currency","category","source_url"
    ]:
        if col not in out.columns:
            out[col] = ""
    out["title"] = out["title"].fillna("").astype(str)
    out["description"] = out["description"].fillna("").astype(str)
    out["buyer"] = out["buyer"].fillna("").astype(str)
    out["country"] = out["country"].fillna("").astype(str)
    out["currency"] = out["currency"].fillna("").astype(str).str.upper()
    out["estimated_value"] = pd.to_numeric(out["estimated_value"], errors="coerce")
    out["published_dt"] = pd.to_datetime(out["published_date"], errors="coerce")
    out["deadline_dt"] = pd.to_datetime(out["deadline"], errors="coerce")
    today = pd.Timestamp(date.today())
    out["days_left"] = (out["deadline_dt"] - today).dt.days
    out["urgency"] = pd.cut(
        out["days_left"],
        bins=[-10_000, -1, 3, 7, 14, 30, 10_000],
        labels=["Closed","Critical","Very soon","Soon","Upcoming","Later"],
    ).astype(str)
    text = (out["title"] + " " + out["description"] + " " + out["category"]).str.lower()
    out["keyword_hits"] = text.apply(lambda s: sum(1 for k in KEYWORDS if k in s))
    out["match_score"] = (out["keyword_hits"].clip(0, 8) / 8 * 100).round(0)
    currencies = tuple(sorted(c for c in out["currency"].dropna().unique() if c))
    rates = fx_to_usd(currencies)
    out["value_usd"] = out.apply(
        lambda r: round(float(r["estimated_value"]) * rates.get(r["currency"], 1.0), 2)
        if pd.notna(r["estimated_value"]) else None,
        axis=1,
    )
    out["uid"] = out.apply(make_uid, axis=1)
    out = out.drop_duplicates(subset=["uid"], keep="first")
    return out

def run_apify(actor_id: str, token: str, run_input: dict[str, Any], max_items: int) -> pd.DataFrame:
    actor = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type":"application/json"},
        params={"clean":"true","format":"json","maxItems":max_items,"timeout":120},
        json=run_input,
        timeout=135,
    )
    r.raise_for_status()
    payload = r.json()
    items = payload if isinstance(payload, list) else payload.get("items", [])
    return pd.json_normalize(items)

def get_secret(key: str) -> str:
    try:
        return str(st.secrets.get(key, ""))
    except Exception:
        return ""

st.title("📑 Smart Tender & Procurement Monitor")
st.caption("Tender discovery, logistics/procurement matching, deadline intelligence and sourcing export.")
st.markdown(
    '<span class="pill">Python</span><span class="pill">Streamlit</span>'
    '<span class="pill">Apify-ready</span><span class="pill">Public Procurement API</span>'
    '<span class="pill">Currency API</span>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Data source")
    use_sample = st.checkbox("Sample portfolio data", value=True)
    use_hu = st.checkbox("Live Hungary tenders", value=False)
    use_pl = st.checkbox("Live Poland tenders", value=False)
    pages = st.slider("Pages per live source", 1, 3, 1)
    st.divider()
    st.header("Filters")
    query = st.text_input("Keywords", value="logistics procurement aviation warehouse")
    only_open = st.toggle("Open tenders only", value=True)
    max_days = st.slider("Deadline within days", 1, 180, 60)
    min_score = st.slider("Minimum match score", 0, 100, 10, 5)

frames = []
if use_sample:
    frames.append(load_sample())

for code, enabled in [("hu", use_hu), ("pl", use_pl)]:
    if enabled:
        for p in range(1, pages + 1):
            try:
                frames.append(fetch_tenders_guru(code, p))
            except Exception as exc:
                st.warning(f"{code.upper()} live source page {p} unavailable: {exc}")
                break

if not frames:
    st.info("Select at least one data source in the sidebar.")
    st.stop()

df = prepare(pd.concat(frames, ignore_index=True, sort=False))

tokens = [t.strip().lower() for t in query.split() if t.strip()]
mask = pd.Series(True, index=df.index)
if tokens:
    haystack = (
        df["title"].fillna("") + " " + df["description"].fillna("") + " " +
        df["buyer"].fillna("") + " " + df["category"].fillna("")
    ).str.lower()
    mask &= haystack.apply(lambda s: any(t in s for t in tokens))
if only_open:
    mask &= df["days_left"].isna() | (df["days_left"] >= 0)
mask &= df["days_left"].isna() | (df["days_left"] <= max_days)
mask &= df["match_score"] >= min_score

view = df.loc[mask].sort_values(
    by=["match_score","days_left"],
    ascending=[False, True],
    na_position="last",
).reset_index(drop=True)

c1,c2,c3,c4 = st.columns(4)
c1.metric("Matching tenders", len(view))
c2.metric("Buyers", view["buyer"].replace("", pd.NA).nunique())
c3.metric("Countries", view["country"].replace("", pd.NA).nunique())
urgent = int(((view["days_left"] >= 0) & (view["days_left"] <= 7)).sum()) if len(view) else 0
c4.metric("Due ≤ 7 days", urgent)

tab1, tab2, tab3, tab4 = st.tabs(["Tender intelligence","Deadline board","Apify collector","About"])

with tab1:
    st.subheader("Ranked procurement opportunities")
    if view.empty:
        st.info("No tenders match the current filters.")
    else:
        cols = [
            "match_score","urgency","days_left","title","buyer","country",
            "published_date","deadline","estimated_value","currency","value_usd",
            "category","source","source_url"
        ]
        st.dataframe(
            view[cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "match_score": st.column_config.ProgressColumn("Match", min_value=0, max_value=100, format="%.0f"),
                "value_usd": st.column_config.NumberColumn("USD normalized", format="$%.2f"),
                "source_url": st.column_config.LinkColumn("Source"),
            },
        )
        st.download_button(
            "Download tender shortlist (CSV)",
            view[cols].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"tender_shortlist_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

with tab2:
    st.subheader("Deadline priority")
    board = view[view["days_left"].notna()].copy()
    if board.empty:
        st.info("No parsed deadlines are available for the current result set.")
    else:
        board["deadline"] = pd.to_datetime(board["deadline_dt"]).dt.date.astype(str)
        st.dataframe(
            board[["urgency","days_left","deadline","title","buyer","country","match_score"]],
            use_container_width=True,
            hide_index=True,
        )

with tab3:
    st.subheader("Optional Apify tender-page collector")
    st.write("Use an Apify Actor to collect tender pages not covered by the public API sources.")
    actor_id = st.text_input("Actor ID", value=get_secret("APIFY_ACTOR_ID"), placeholder="username/actor-name")
    token = st.text_input("Apify token", value=get_secret("APIFY_TOKEN"), type="password")
    urls = st.text_area("Tender/search URLs, one per line", height=110)
    max_items = st.number_input("Maximum returned items", 1, 200, 25)
    actor_input = {
        "startUrls":[{"url":u.strip()} for u in urls.splitlines() if u.strip()],
        "maxCrawlPages":int(max_items),
    }
    with st.expander("Actor input preview"):
        st.code(json.dumps(actor_input, indent=2), language="json")
    if st.button("Run Apify collector", type="primary"):
        if not actor_id or not token:
            st.error("Actor ID and token are required.")
        elif not actor_input["startUrls"]:
            st.error("Add at least one URL.")
        else:
            try:
                with st.spinner("Running Actor…"):
                    live = run_apify(actor_id, token, actor_input, int(max_items))
                st.success(f"Collected {len(live)} item(s).")
                st.dataframe(live, use_container_width=True, hide_index=True)
                if not live.empty:
                    st.download_button(
                        "Download raw Apify results",
                        live.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"apify_tender_results_{date.today().isoformat()}.csv",
                        mime="text/csv",
                    )
            except Exception as exc:
                st.error(f"Apify run failed: {exc}")

with tab4:
    st.subheader("Data-source design")
    st.markdown(
        """
- **Tenders Guru**: live public procurement JSON connector for Hungary and Poland.
- **Frankfurter**: public currency conversion used to normalize tender values where currency/value are available.
- **Apify**: optional collector for procurement portals or company tender pages that need web extraction.
- **Sample data**: fictional portfolio records for a reliable no-key demonstration.
        """
    )
    st.warning(
        "Tender data can change. Verify eligibility, deadlines, buyer identity, submission method, "
        "technical specifications and official source documents before acting."
    )

st.divider()
st.caption("Portfolio demo by Muhammad Naveed · Logistics · Procurement · Supply Chain")
