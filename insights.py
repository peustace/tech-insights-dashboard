"""Pure, dependency-free logic for the Tech Insights Dashboard.

Everything here is deterministic and unit-tested (see tests/test_insights.py):
text cleaning, link sanitising, de-duplication, ranking, top-story selection,
emerging-term detection, weekly-recap triggering and validation of model output.
Network and Claude calls live in fetch_data.py.
"""
import copy
import hashlib
import html
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def age_hours(item, now):
    ts = parse_iso(item.get("published")) or parse_iso(item.get("first_seen"))
    if ts is None:
        return 0.0
    return max((now - ts).total_seconds() / 3600.0, 0.0)


# --------------------------------------------------------------------------- #
# Text cleaning
# --------------------------------------------------------------------------- #

_TAG = re.compile(r"<[^>]*>")
_WS = re.compile(r"\s+")
_ARXIV_PREFIX = re.compile(r"^arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*", re.I)
_WP_FOOTER = re.compile(r"\s*The post .{0,200}? appeared first on .{0,100}$", re.I)
_TRAILING_MORE = re.compile(r"\s*(\[…\]|\[\.\.\.\]|…|Read more\.?|Continue reading.*)\s*$", re.I)


def clean_html(raw):
    """Strip tags/entities and boilerplate, returning plain text."""
    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text).strip()
    text = _ARXIV_PREFIX.sub("", text)
    text = _WP_FOOTER.sub("", text)
    text = _TRAILING_MORE.sub("", text)
    return text.strip()


def truncate(text, max_len):
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or text[:max_len]) + "…"


def sanitize_text(value, max_len):
    return truncate(clean_html(value), max_len)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def fallback_summary(text, title="", max_len=280):
    """Best-effort summary without AI: the first one or two sentences of the feed text.

    Returns "" when there is nothing useful (never a bare "...")."""
    cleaned = clean_html(text)
    if len(cleaned) < 40 or cleaned.lower().strip(" .") == (title or "").lower().strip(" ."):
        return ""
    out = ""
    for sentence in _SENTENCE_SPLIT.split(cleaned)[:2]:
        candidate = (out + " " + sentence).strip()
        if len(candidate) > max_len and out:
            break
        out = candidate
    return truncate(out, max_len)


# --------------------------------------------------------------------------- #
# Links and identity
# --------------------------------------------------------------------------- #

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|igshid|ref_src)$", re.I)


def safe_link(url):
    """Return a cleaned http(s) URL, or None for anything else (javascript:, data:, ...)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if len(url) > 2000:
        return None
    parts = urlparse(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    return urlunparse((parts.scheme.lower(), parts.netloc, parts.path, parts.params, query, ""))


def canonical_key(url):
    parts = urlparse(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{parts.path.rstrip('/')}?{parts.query}"


def item_id(url):
    return hashlib.sha1(canonical_key(url).encode("utf-8")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Similarity and de-duplication
# --------------------------------------------------------------------------- #

STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be been before being but by can could did do does
    for from get had has have how if in into is it its just more most new not of on one only or other our out
    over say says said than that the their them then there these they this to up us use used uses using via
    was we were what when where which while who why will with would you your vs""".split()
)

# Words that appear in nearly every tech headline and say nothing about a trend.
GENERIC_TERMS = frozenset(
    """announces announced announcing launches launched launch introduces introducing introduces unveils
    report reports reported study research paper papers company companies tech technology technologies data
    system systems model models based approach novel towards toward analysis new first latest year years
    week day today now million billion percent news update updates interview podcast episode
    show shows ask review guide using learning framework""".split()
)

_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.\+]*[a-z0-9\+]|[a-z0-9]")


def tokens(text, drop_generic=False):
    out = []
    for word in _WORD.findall((text or "").lower()):
        word = word.strip(".-")
        if not word or word in STOPWORDS:
            continue
        if drop_generic and word in GENERIC_TERMS:
            continue
        out.append(word)
    return out


def similar(title_a, title_b, threshold=0.6):
    a, b = set(tokens(title_a)), set(tokens(title_b))
    if len(a) < 3 or len(b) < 3:
        return bool(a) and a == b
    inter = len(a & b)
    jaccard = inter / len(a | b)
    containment = inter / min(len(a), len(b))
    return jaccard >= threshold or (min(len(a), len(b)) >= 4 and containment >= 0.85)


def cluster_items(items, threshold=0.6):
    """Merge near-duplicate stories (same story from several feeds).

    Works on copies, so stored items are never mutated. The highest-weight, highest-importance
    item becomes the primary; others are listed under its "related" key."""
    pool = sorted(
        (copy.deepcopy(i) for i in items),
        key=lambda i: (-float(i.get("weight", 1.0)), -float(i.get("importance") or 0), i.get("first_seen") or ""),
    )
    primaries = []
    for item in pool:
        item["related"] = []
        for primary in primaries:
            if canonical_key(primary["link"]) == canonical_key(item["link"]) or similar(primary["title"], item["title"], threshold):
                if item.get("source") != primary.get("source") and all(r["link"] != item["link"] for r in primary["related"]):
                    primary["related"].append({"source": item.get("source", ""), "link": item["link"], "title": item["title"]})
                break
        else:
            primaries.append(item)
    return primaries


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #

DEFAULT_IMPORTANCE = 4.0  # used when the model could not rate an item


def recency_factor(hours, half_life=36.0):
    return 0.5 ** (hours / half_life)


def score_item(item, now):
    importance = float(item.get("importance") or DEFAULT_IMPORTANCE)
    base = importance * float(item.get("weight", 1.0)) * recency_factor(age_hours(item, now))
    corroboration = min(len(item.get("related", [])), 3) * 0.75
    return round(base + corroboration, 3)


def rank_items(items, now, limit=None):
    scored = []
    for item in items:
        item = dict(item)
        item["score"] = score_item(item, now)
        scored.append(item)
    # Newest first, then a stable sort by score so ties keep the newer item on top.
    scored.sort(key=lambda i: i.get("published") or i.get("first_seen") or "", reverse=True)
    scored.sort(key=lambda i: -i["score"])
    return scored[:limit] if limit else scored


def pick_top_stories(sectors, now, n=5, per_sector=2, max_age_hours=72):
    """Pick the n best stories across sectors: at most per_sector from each, no duplicates."""
    candidates = []
    for sector, items in sectors.items():
        for item in items:
            if age_hours(item, now) <= max_age_hours:
                candidates.append(item)
    candidates.sort(key=lambda i: -i.get("score", 0))
    chosen, per = [], Counter()
    for item in candidates:
        if per[item["sector"]] >= per_sector:
            continue
        if any(similar(item["title"], c["title"]) for c in chosen):
            continue
        chosen.append(item)
        per[item["sector"]] += 1
        if len(chosen) == n:
            break
    return chosen


# --------------------------------------------------------------------------- #
# Emerging terms
# --------------------------------------------------------------------------- #


def terms_in_item(item):
    """Unigrams (len >= 4) and bigrams from the title and summary of one item."""
    raw = [w.strip(".-") for w in _WORD.findall(f"{item.get('title', '')} {item.get('summary', '')}".lower())]
    skip = STOPWORDS | GENERIC_TERMS
    found = {w for w in raw if len(w) >= 4 and not w.isdigit() and w not in skip}
    # Bigrams only from words that are adjacent in the text (never across a dropped stopword).
    for a, b in zip(raw, raw[1:]):
        if a in skip or b in skip or len(a) < 3 or len(b) < 3 or a.isdigit() or b.isdigit():
            continue
        found.add(f"{a} {b}")
    return found


def build_baseline(snapshots):
    """Average number of items per day containing each term, from earlier daily snapshots."""
    if not snapshots:
        return {}
    totals = Counter()
    for snap in snapshots:
        seen_ids = set()
        for items in snap.get("sectors", {}).values():
            for item in items:
                if item.get("id") in seen_ids:
                    continue
                seen_ids.add(item.get("id"))
                totals.update(terms_in_item(item))
    return {term: count / len(snapshots) for term, count in totals.items()}


def emerging_terms(items, baseline, top_n=8):
    """Terms that suddenly appear across several independent sources."""
    sources, sectors, ids = defaultdict(set), defaultdict(set), defaultdict(list)
    for item in items:
        group = {item.get("source", "")} | {r.get("source", "") for r in item.get("related", [])}
        for term in terms_in_item(item):
            sources[term].update(group)
            sectors[term].add(item.get("sector", ""))
            ids[term].append(item.get("id"))
    results = []
    for term, srcs in sources.items():
        n_sources, n_sectors = len(srcs), len(sectors[term])
        # Phrases are specific, so two independent sources suffice; single words need three.
        if n_sources < (2 if " " in term else 3):
            continue
        usual = baseline.get(term, 0.0)
        if usual > 1.5:  # already a staple term, not emerging
            continue
        results.append({
            "term": term,
            "sources": n_sources,
            "sectors": n_sectors,
            "ids": ids[term][:3],
            "score": round(n_sources * (1 + 0.5 * n_sectors) / (1 + usual) * (1.25 if " " in term else 1.0), 2),
        })
    results.sort(key=lambda r: (-r["score"], r["term"]))
    chosen = []
    for r in results:
        # Drop a unigram when a chosen phrase already contains it.
        if " " not in r["term"] and any(r["term"] in c["term"].split() for c in chosen):
            continue
        # Drop a phrase when a stronger phrase already covers the same words.
        if " " in r["term"] and any(set(r["term"].split()) & set(c["term"].split()) and " " in c["term"] for c in chosen):
            continue
        chosen.append(r)
        if len(chosen) == top_n:
            break
    return chosen


# --------------------------------------------------------------------------- #
# Weekly recap, state, model-output validation
# --------------------------------------------------------------------------- #


def should_generate_weekly(now, previous_recap, force=False):
    if force:
        return True
    if now.weekday() != 6:
        return False
    return not previous_recap or previous_recap.get("week_ending") != now.date().isoformat()


def prune_state(items_by_id, now, max_age_hours=96, max_items=500):
    kept = {}
    for key, item in items_by_id.items():
        last_seen = parse_iso(item.get("last_seen")) or parse_iso(item.get("first_seen"))
        if last_seen and (now - last_seen).total_seconds() / 3600.0 <= max_age_hours:
            kept[key] = item
    if len(kept) > max_items:
        newest = sorted(kept.values(), key=lambda i: i.get("last_seen") or "", reverse=True)[:max_items]
        kept = {i.get("key") or i["id"]: i for i in newest}
    return kept


def parse_json_loose(text):
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except ValueError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


def parse_ai_batch(text, expected_ids):
    """Validate a batched summary reply: {id: {summary, why, importance}} for known ids only."""
    data = parse_json_loose(text)
    if isinstance(data, dict):
        data = data.get("items", [])
    out = {}
    if not isinstance(data, list):
        return out
    for row in data:
        if not isinstance(row, dict) or row.get("id") not in expected_ids:
            continue
        summary = sanitize_text(row.get("summary", ""), 320)
        if len(summary) < 15 or summary.strip(". ") == "":
            continue
        try:
            importance = min(max(float(row.get("importance")), 1.0), 10.0)
        except (TypeError, ValueError):
            importance = None
        out[row["id"]] = {
            "summary": summary,
            "why_it_matters": sanitize_text(row.get("why_it_matters", ""), 200),
            "importance": importance,
        }
    return out


_TICKER = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def validate_stocks(data, max_items=3):
    if isinstance(data, dict):
        data = data.get("stocks") or data.get("items") or []
    out = []
    if not isinstance(data, list):
        return out
    for row in data:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker", "")).strip().upper()
        blurb = sanitize_text(row.get("impact_blurb", ""), 400)
        if not _TICKER.match(ticker) or not blurb:
            continue
        out.append({
            "ticker": ticker,
            "company": sanitize_text(row.get("company", ""), 60) or ticker,
            "impact_blurb": blurb,
        })
        if len(out) == max_items:
            break
    return out


def snapshot_top_items(snapshot):
    return list(snapshot.get("top_stories", []))


def recap_lines(snapshots):
    """Compact text lines for the weekly-recap prompt, oldest day first."""
    lines = []
    for snap in sorted(snapshots, key=lambda s: s.get("date", "")):
        for item in snapshot_top_items(snap):
            why = f" - {item['why_it_matters']}" if item.get("why_it_matters") else ""
            lines.append(f"{snap.get('date', '')} | {item.get('sector', '')} | {item.get('title', '')}{why}")
    return lines


def stale_hours(generated_at, now):
    ts = parse_iso(generated_at)
    return math.inf if ts is None else (now - ts).total_seconds() / 3600.0
