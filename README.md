# Smart Tender & Procurement Monitor

A Streamlit portfolio app for discovering and prioritizing procurement opportunities relevant to logistics, supply chain, aviation, warehouse, materials, transport and MRO work.

## Features

- Search and filter tender opportunities
- Logistics / procurement keyword matching score
- Deadline urgency board
- Duplicate detection
- Buyer and country visibility
- Tender-value normalization to USD when value/currency are available
- CSV shortlist export
- Optional Apify Actor integration
- Sample mode that works without any API key

## Public API sources

The MVP supports:

- **Tenders Guru** public JSON API for Hungary and Poland
- **Frankfurter** for currency conversion

Tenders Guru documents the list endpoint as:

- `GET https://tenders.guru/api/hu/tenders`
- `GET https://tenders.guru/api/pl/tenders`

## Optional Apify setup

For deployed live scraping, add to Streamlit Secrets:

```toml
APIFY_TOKEN = "your-token"
APIFY_ACTOR_ID = "username/actor-name"
```

Never commit tokens to GitHub.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Deploy `app.py` from the repository root on Streamlit Community Cloud.

## Demo-data notice

`data/sample_tenders.csv` contains fictional portfolio records. Always verify actual tender details and official documents before submission.
