"""Metadata scout: leads for human review, never performance evidence."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

QUERIES = (
    "Maisotsenko cycle dew point evaporative cooling pressure drop",
    "indirect evaporative cooling humid climate experiment",
)


def scout():
    leads = []
    for query in QUERIES:
        params = urlencode({"query.bibliographic": query, "rows": 5,
                            "select": "DOI,title,published,URL,type"})
        request = Request("https://api.crossref.org/works?" + params,
                          headers={"User-Agent": "KissanShroom-RD/0.1 (metadata-only research)"})
        with urlopen(request, timeout=12) as response:
            records = json.load(response)["message"]["items"]
        for record in records:
            doi = record.get("DOI")
            if not doi or any(item["doi"] == doi for item in leads):
                continue
            leads.append({"doi": doi, "title": (record.get("title") or [""])[0][:240],
                          "url": record.get("URL", ""), "query": query,
                          "status": "METADATA LEAD ONLY; paper and conditions not reviewed"})
    return leads
