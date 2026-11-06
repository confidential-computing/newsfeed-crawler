import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup


__version__ = "2.11.0"

DEFAULT_KEYWORDS ="confidential computing,confidential compute,confidential AI,trusted execution environment,enclave,TEE,SGX,TDX,SEV,SEV-SNP,Arm CCA,remote attestation,confidential VM,confidential container"
CCC_PROJECT_UID = "54ec092e-cadd-49af-9edf-9a5c888cc283"
MEMBERS_TTL_SECONDS = 7 * 24 * 60 * 60  # one week

_FETCH_PROMPT = (
    'Call mcp__claude_ai_LFX__query_lfx_lens with project_slug "ccc" and '
    'input "List all current active member organization names". '
    "Extract every organization name from the result table. "
    "Respond with ONLY a JSON object on a single line — no prose, "
    'no markdown — in exactly this form: {"members": ["Name 1", "Name 2", ...]}'
)


# Outlets treated as UK for --webfeed-exclude-uk. Any host under a `.uk` TLD
# is UK automatically; this list covers UK outlets on other TLDs. Matched
# against the registrable suffix, so `www.` and subdomains are covered. Extend
# without code changes via a top-level `uk_outlets:` list in feeds.yaml.
# Deliberately omitted: Reuters (London newsroom, Canadian parent) and other
# outlets whose nationality is arguable — add them to feeds.yaml if wanted.
UK_OUTLET_DOMAINS = (
    "bbc.com", "bbci.co.uk", "theregister.com", "theguardian.com",
    "computerweekly.com", "ft.com", "economist.com", "techradar.com",
    "itpro.com", "techmonitor.ai", "infosecurity-magazine.com",
    "datacenterdynamics.com", "cityam.com", "thestack.technology",
    "uktech.news", "silicon.co.uk", "computing.co.uk",
)

# Outlets on generic TLDs whose region cannot be read from the hostname.
# Region codes are lower-case; UK_OUTLET_DOMAINS above are folded in as "uk".
# Extend without code changes via a top-level `outlet_regions:` mapping in
# feeds.yaml (domain: region).
OUTLET_REGIONS = {
    **{d: "uk" for d in UK_OUTLET_DOMAINS},
    # Asia
    "techwireasia.com": "asia", "itnews.asia": "asia", "opengovasia.com": "asia",
    "digitimes.com": "tw", "techinasia.com": "asia", "e27.co": "sg",
    "kr-asia.com": "asia", "asia.nikkei.com": "jp", "scmp.com": "hk",
    "analyticsindiamag.com": "in", "medianama.com": "in", "inc42.com": "in",
    "yourstory.com": "in", "cxotoday.com": "in", "thehackernews.com": "in",
    "thehindubusinessline.com": "in", "indiatimes.com": "in",
    "koreaherald.com": "kr", "pandaily.com": "cn", "straitstimes.com": "sg",
    "frontier-enterprise.com": "asia", "cdotrends.com": "asia",
    "securitybrief.asia": "asia", "itbrief.asia": "asia",
    "channelnewsasia.com": "sg", "livemint.com": "in", "indianexpress.com": "in",
    "digitalnewsasia.com": "my", "digiconasia.net": "asia", "thelec.net": "kr",
    "taipeitimes.com": "tw", "koreatimes.com": "kr",
    # Australia and New Zealand
    "itwire.com": "au", "innovationaus.com": "au", "capitalbrief.com": "au",
    # Africa ("cioafrica.co" would otherwise read as Colombia)
    "techcabal.com": "ng", "techpoint.africa": "ng", "ventureburn.com": "za",
    "techweez.com": "ke", "techlabari.com": "gh", "cioafrica.co": "africa",
    "connectingafrica.com": "africa",
    # Spanish and Portuguese
    "xataka.com": "es", "hipertextual.com": "es", "muycomputerpro.com": "es",
    "muyseguridad.net": "es", "redseguridad.com": "es", "itsitio.com": "latam",
    "dplnews.com": "latam", "infobae.com": "ar", "tynmagazine.com": "ar",
    "tecnoblog.net": "br",
}

# Country-code TLDs that identify an outlet's region. Second-level forms such
# as .com.au and .co.kr are covered because only the last label is checked.
_CCTLD_REGIONS = {
    "uk": "uk", "au": "au", "nz": "nz", "in": "in", "sg": "sg", "my": "my",
    "ph": "ph", "id": "id", "th": "th", "vn": "vn", "hk": "hk", "tw": "tw",
    "jp": "jp", "kr": "kr", "cn": "cn", "pk": "pk", "bd": "bd", "lk": "lk",
    "za": "za", "ng": "ng", "ke": "ke", "gh": "gh", "eg": "eg", "zw": "zw",
    "ug": "ug", "tz": "tz", "rw": "rw", "et": "et", "zm": "zm", "bw": "bw",
    "na": "na", "mu": "mu", "ma": "ma", "tn": "tn", "sn": "sn", "cm": "cm",
    "br": "br", "ar": "ar", "mx": "mx", "cl": "cl", "co": "co", "pe": "pe",
    "es": "es", "pt": "pt",
}

# Hosts that syndicate other publishers' articles: the real publisher must be
# read from the entry's <source> element rather than from the link.
_AGGREGATOR_HOSTS = ("news.google.com",)


def _host(url):
    try:
        host = urllib.parse.urlparse(url or "").hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def is_uk_host(host, extra_domains=()):
    """True if `host` belongs to a UK outlet: a .uk TLD or a listed domain."""
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    if host == "uk" or host.endswith(".uk"):
        return True
    return any(host == d or host.endswith("." + d)
               for d in (*UK_OUTLET_DOMAINS, *extra_domains))


def region_for_host(host, feed_region=None, extra=None):
    """
    Region code of the outlet at `host`: an explicit domain mapping first
    (`extra`, then OUTLET_REGIONS), then the country-code TLD, then the
    region declared on the feed. None when nothing is known.

    `.co` is Colombia only as a bare TLD; under another country (`.co.kr`)
    the last label decides.
    """
    host = (host or "").lower().rstrip(".")
    if host:
        for mapping in (extra or {}, OUTLET_REGIONS):
            for d, region in mapping.items():
                if host == d or host.endswith("." + d):
                    return region
        tld = host.rsplit(".", 1)[-1]
        if tld in _CCTLD_REGIONS and tld != "co":
            return _CCTLD_REGIONS[tld]
        if tld == "co" and host.count(".") == 1:
            return "co"
    return feed_region or None


def publisher_host(link, source_href="", feed_url=""):
    """
    Best guess at the host of the outlet that published an article.

    Google News links are redirects through news.google.com, so for those the
    <source href> is authoritative. Otherwise the article link wins, then the
    feed URL.
    """
    link_host = _host(link)
    if source_href and (not link_host or link_host in _AGGREGATOR_HOSTS):
        return _host(source_href)
    if link_host and link_host not in _AGGREGATOR_HOSTS:
        return link_host
    feed_host = _host(feed_url)
    return "" if feed_host in _AGGREGATOR_HOSTS else feed_host


def normalize_url(url):
    """
    Normalize URL by removing common tracking parameters and fragments.
    This helps detect when different URLs point to the same content.
    """
    if not url:
        return ""
    
    try:
        parsed = urllib.parse.urlparse(url)
        
        # Remove common tracking parameters
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
            'fbclid', 'gclid', 'msclkid', '_ga', '_gid', 'ref', 'source',
            'campaign', 'medium', 'content', 'term', 'partner', 'referrer'
        }
        
        query_params = urllib.parse.parse_qs(parsed.query)
        filtered_params = {k: v for k, v in query_params.items() 
                          if k.lower() not in tracking_params}
        
        new_query = urllib.parse.urlencode(filtered_params, doseq=True)
        
        # Rebuild URL without fragment and with filtered query
        normalized = urllib.parse.urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.lower(),  # Also normalize path case
            parsed.params,
            new_query,
            ""  # Remove fragment
        ))
        
        return normalized
    except Exception:
        # If URL parsing fails, return original
        return url.lower()


def compute_content_hash(title, content_text=""):
    """
    Compute a hash of the article's core content for duplicate detection.
    Uses title and optional full text content.
    """
    # Normalize text: lowercase, collapse whitespace, remove punctuation
    def normalize_text(text):
        if not text:
            return ""
        # Keep only alphanumeric and spaces, collapse whitespace
        normalized = re.sub(r'[^\w\s]', ' ', text.lower())
        return ' '.join(normalized.split())
    
    normalized_title = normalize_text(title)
    normalized_content = normalize_text(content_text)
    
    # Combine title and content for hashing
    combined = f"{normalized_title}|||{normalized_content}"
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


# Pairs of articles whose titles are at least this similar (Jaccard on title
# tokens) are compared by their text; less similar pairs never are.
DEDUP_TITLE_SIMILARITY = 0.6
# Share of 5-word phrases two texts must have in common, relative to the
# shorter one, to count as the same article. Syndicated copies score near 1;
# two outlets writing up the same press release score far lower.
DEDUP_TEXT_OVERLAP = 0.8
# Below this many phrases a text is a teaser, a paywall or a failed
# extraction, and too short to say two articles are the same.
DEDUP_MIN_SHINGLES = 40


def _shingles(text, n=5):
    words = re.findall(r"\w+", (text or "").lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def text_overlap(text_a, text_b):
    """Share of 5-word phrases two texts have in common, relative to the
    shorter text; 0.0 if either is too short to judge."""
    a, b = _shingles(text_a), _shingles(text_b)
    if min(len(a), len(b)) < DEDUP_MIN_SHINGLES:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _site(host):
    """The registrable part of a host, so an outlet's regional editions
    (ca.investing.com, in.investing.com) count as one outlet."""
    labels = (host or "").split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and \
        labels[-2] in ("co", "com", "net", "org", "gov", "ac", "edu") else 2
    return ".".join(labels[-keep:])


def _dedup_title(article):
    """Title without the " - Publisher" suffix Google News appends."""
    title = article.get("title", "")
    if _host(article.get("url")) in _AGGREGATOR_HOSTS:
        title = re.sub(r"\s+-\s+[^-]+$", "", title)
    return title


def deduplicate_articles(categorized, fetch_text=None):
    """
    Drop copies of the same article, but keep the same story when different
    outlets report it in their own words.

    A later article is a copy of one already kept when
    1. their URLs normalise to the same address, or
    2. their titles are similar and either
       a. the same outlet published both under the same title (one article
          reached through two feeds, e.g. two Google News editions, or an
          outlet's regional editions), or
       b. their texts are the same (syndication, e.g. IT Brief Australia
          republishing an IT Brief Asia story).

    Text is fetched lazily: only for pairs with similar titles, once per URL.
    If either text can't be read (Google News redirect links, paywalls) the
    articles are not judged copies, so both are kept.

    Returns (categorized, number of copies removed).
    """
    fetch_text = fetch_text or fetch_article_text
    texts = {}

    def text_of(article):
        url = article.get("url", "")
        if url not in texts:
            texts[url] = fetch_text(url) if url else ""
        return texts[url]

    seen_urls = set()
    kept = []  # (title tokens, normalised title, outlet host, article)
    removed = 0

    for category in ("by_member", "about_member", "dont"):
        if category not in categorized:
            continue
        unique = []
        for article in categorized[category]:
            url = normalize_url(article.get("url", ""))
            if url and url in seen_urls:
                removed += 1
                continue
            if url:
                seen_urls.add(url)

            title = _dedup_title(article)
            tokens = _title_tokens(title)
            norm_title = " ".join(re.findall(r"\w+", title.lower()))
            host = article.get("host") or _host(article.get("url"))
            # The outlet behind a Google News link without a host is unknown
            host = "" if host in _AGGREGATOR_HOSTS else _site(host)

            original = None
            for k_tokens, k_title, k_host, k_article in kept:
                if not tokens or not k_tokens:
                    continue
                if len(tokens & k_tokens) / len(tokens | k_tokens) < DEDUP_TITLE_SIMILARITY:
                    continue
                if (host and host == k_host and norm_title == k_title) or \
                        text_overlap(text_of(article), text_of(k_article)) >= DEDUP_TEXT_OVERLAP:
                    original = k_article
                    break

            if original is not None:
                removed += 1
                print(f"  copy: {article.get('title', '')[:70]!r} ({article.get('publisher')}) "
                      f"= {original.get('publisher')}", file=sys.stderr)
                continue
            kept.append((tokens, norm_title, host, article))
            unique.append(article)
        categorized[category] = unique

    return categorized, removed


def fetch_members(cache_path):
    result = subprocess.run(
        [
            "claude",
            "-p", _FETCH_PROMPT,
            "--output-format", "json",
            "--allowedTools", "mcp__claude_ai_LFX__query_lfx_lens",
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()}")

    envelope = json.loads(result.stdout)
    raw = envelope.get("result", "")
    # Strip accidental code fences if present
    raw = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", raw).strip()
    data = json.loads(raw)

    members = data.get("members")
    if not isinstance(members, list) or not members:
        raise ValueError(f"Unexpected members payload: {raw[:200]}")

    members = sorted(set(m for m in members if isinstance(m, str) and m))

    tmp = cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"members": members}, f, indent=2)
    os.replace(tmp, cache_path)

    return members


def load_members(cache_path):
    try:
        with open(cache_path) as f:
            return json.load(f).get("members", [])
    except FileNotFoundError:
        return None


_DESCRIPTOR_SUFFIX = re.compile(
    r"\s+(blockchain|tech|technology|technologies|systems|solutions|labs?"
    r"|research|group|software|hardware|computing|services|security"
    r"|networks?|cloud|platforms?|digital|global|international|ai)$",
    flags=re.IGNORECASE,
)


def clean_member_name(name):
    cleaned = re.sub(
        r"\s+(Inc\.|LLC|Corporation|Co\.\,?\s*Ltd\.|Limited|LP)$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip(" ,.")
    cleaned = re.sub(r"^The\s+", "", cleaned, flags=re.IGNORECASE).strip()
    while True:
        shorter = _DESCRIPTOR_SUFFIX.sub("", cleaned).strip()
        if shorter == cleaned or len(shorter) < 3:
            break
        # Do not over-clean generic prefixes that would reduce to extremely generic terms like "confidential" or "confident"
        if shorter.lower() in ["confidential", "confident", "common", "core", "secure"]:
            break
        cleaned = shorter
    return cleaned.lower()


def is_by_member(feed_name, author, members):
    # Exclude news aggregators and RSS feeds from being matched with members
    news_aggregators = [
        "google news", "news.google.com", "rss", "feed", "headlines", 
        "techcrunch", "the register", "venturebeat", "ars technica", 
        "zdnet", "infoq", "servethehome", "bbc", "mit technology review",
        "informationweek", "dark reading", "the new stack", "guardonline.com",
        "stock titan", "yahoo finance", "globenewswire", "marketscreener.com",
        "it voice media", "scanx.trade", "sahi", "quartr", "bitcoin foundation",
        "hpcwire", "network world", "digital journal", "pc perspective",
        "sns insider", "hackernoon", "trading view", "etenterpriseai.com",
        "business standard", "investing.com", "bitget"
    ]
    
    feed_lower = feed_name.lower()
    for aggregator in news_aggregators:
        if aggregator in feed_lower:
            return None
    
    check = f"{feed_name} {author}".lower()
    for m in members:
        cleaned = clean_member_name(m)
        if len(cleaned) > 2 and re.search(rf"\b{re.escape(cleaned)}\b", check):
            return m
    return None


# Members' names as non-English articles write them, keyed by
# clean_member_name(). Matched ignoring spaces and the katakana middle dot.
# Ambiguous transliterations are left out: アーム (Arm; also any robot
# "arm"), メタ (Meta; "meta-"), マーベル (Marvell; Marvel), アンペア
# (Ampere; the unit).
MEMBER_ALIASES = {
    "intel": ["インテル"],
    "microsoft": ["マイクロソフト"],
    "google": ["グーグル"],
    "nvidia": ["エヌビディア"],
    "qualcomm": ["クアルコム"],
    "samsung electronics": ["サムスン"],
    "huawei technologies co., ltd": ["ファーウェイ", "華為", "华为"],
    "cisco": ["シスコ"],
    "red hat": ["レッドハット"],
    "fujitsu": ["富士通"],
    "hewlett packard enterprise": ["ヒューレット・パッカード・エンタープライズ"],
    "canonical": ["カノニカル"],
    "linaro": ["リナロ"],
    "eaglys": ["イーグリス"],
    "tiktok": ["ティックトック"],
    "jpmorgan chase bank, national association": ["JPモルガン"],
    "volcano engine": ["火山引擎"],
    "shanghai jiao tong university": ["上海交通大学"],
}


def is_about_member(haystack, members):
    text = haystack.lower()
    
    # First check standard member names
    for m in members:
        cleaned = clean_member_name(m)
        if len(cleaned) > 2 and re.search(rf"\b{re.escape(cleaned)}\b", text):
            return m

    squeezed = None
    for m in members:
        for alias in MEMBER_ALIASES.get(clean_member_name(m), []):
            if squeezed is None:
                squeezed = re.sub(r"[\s・]+", "", unicodedata.normalize("NFKC", text))
            if re.sub(r"[\s・]+", "", alias).lower() in squeezed:
                return m
    
    # Special case: Check for Ubuntu if Canonical is a member
    canonical_members = [m for m in members if 'canonical' in m.lower()]
    if canonical_members and re.search(r'\bubuntu\b', text):
        return canonical_members[0]  # Return the first Canonical member found
        
    return None


# A date string that ends in a zone: "Z", "+09:00", "+0900", "GMT", "KST".
_HAS_ZONE_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2}|[A-Za-z]{2,5})\s*$")


def localise_naive_dates(entries, tzname):
    """
    Read zone-less entry dates as local time in *tzname*, not UTC.

    BusinessKorea and The Elec write "2026-10-29 21:48:48" in Korean time.
    feedparser takes that as UTC, which puts their newest items up to nine
    hours in the future, past the end of the edition window.
    """
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tzname)
    for entry in entries:
        # entry_datetime() prefers published over updated, so fix that one.
        for raw_key, parsed_key in (("published", "published_parsed"),
                                    ("updated", "updated_parsed")):
            raw, parsed = entry.get(raw_key), entry.get(parsed_key)
            if raw and parsed:
                if not _HAS_ZONE_RE.search(raw):
                    local = datetime(*parsed[:6], tzinfo=tz)
                    entry[parsed_key] = local.astimezone(timezone.utc).utctimetuple()
                break


def entry_datetime(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            import calendar
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


_REDIRECT_DOMAINS = {"google.com", "consent.google.com", "accounts.google.com"}


FEED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "application/rss+xml, application/atom+xml, "
        "application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_feed(url, attempts=2):
    """Fetch a feed with browser-like headers, retrying then falling back.

    Some publishers (Fastly/Akamai-fronted sites) reject feedparser's default
    user-agent with 403/429. Fetching the bytes ourselves with realistic
    headers fixes most of those cases.
    """
    # Special handle for SUSE's JSON Blog API
    if "/api/blogs" in url or ".json" in url:
        last_exc = None
        for attempt in range(attempts):
            try:
                resp = requests.get(url, timeout=20, headers=FEED_HEADERS)
                if resp.status_code == 200:
                    import dateutil.parser as dp
                    import calendar
                    from types import SimpleNamespace
                    data = resp.json()
                    
                    class MockFeed:
                        def __init__(self):
                            self.bozo = False
                            self.bozo_exception = None
                            self.entries = []

                    parsed = MockFeed()
                    for item in data.get("results", []):
                        # Convert SUSE's fields into FeedParser-like fields
                        entry = feedparser.FeedParserDict()
                        entry["title"] = item.get("title", "")
                        entry["link"] = item.get("url", "")
                        if entry["link"] and not entry["link"].startswith("http"):
                            entry["link"] = "https://www.suse.com" + entry["link"]
                        entry["summary"] = item.get("excerpt", "")
                        entry["author"] = item.get("author", "")
                        
                        # Set published dates so entry_datetime(entry) works seamlessly
                        date_str = item.get("date")
                        if date_str:
                            try:
                                dt = dp.parse(date_str).replace(tzinfo=timezone.utc)
                                entry["published_parsed"] = dt.timetuple()
                                # Also set standard fallback fields
                                entry["published"] = date_str
                            except Exception:
                                pass
                        parsed.entries.append(entry)
                    return parsed
                else:
                    last_exc = f"HTTP {resp.status_code}"
            except Exception as e:
                last_exc = e
            if attempt + 1 < attempts:
                time.sleep(2)
        raise ValueError(last_exc or "Failed to fetch JSON feed")

    last_exc = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, timeout=20, headers=FEED_HEADERS)
            if resp.status_code == 200:
                parsed = feedparser.parse(resp.content)
                if parsed.entries or not parsed.bozo:
                    return parsed
                last_exc = parsed.bozo_exception
            else:
                last_exc = f"HTTP {resp.status_code}"
        except Exception as e:
            last_exc = e
        if attempt + 1 < attempts:
            time.sleep(2)

    # Last resort: let feedparser fetch it itself
    parsed = feedparser.parse(url)
    if parsed.entries:
        return parsed
    if last_exc and not parsed.bozo:
        raise ValueError(last_exc)
    return parsed


# Busy feeds (Yonhap, Korea Herald, Taipei Times) only list about a day of
# items, so a weekly run sees a fraction of their week. `--store-only` runs
# several times a day and saves every entry here; every crawl then merges
# the stored entries for each feed with what the feed shows live.
ENTRY_STORE_KEEP_DAYS = 35
# Stop saving entries when the store's filesystem is fuller than this.
ENTRY_STORE_DISK_LIMIT = 80


def disk_percent_used(path):
    """Percentage of the filesystem holding *path* in use, as df reports it."""
    import shutil
    usage = shutil.disk_usage(path)
    # df's Use% leaves out root-reserved blocks: used / (used + available).
    return 100 * usage.used / (usage.used + usage.free)


def store_disk_full(args):
    """Log an error and return True if the entry store's disk is over the limit."""
    os.makedirs(args.entry_store, exist_ok=True)
    pct = disk_percent_used(args.entry_store)
    if pct <= args.entry_store_disk_limit:
        return False
    print(f"[store] ERROR: the filesystem holding {args.entry_store} is {pct:.0f}% full "
          f"(limit {args.entry_store_disk_limit}%). Not saving feed entries until "
          f"space is freed.", file=sys.stderr)
    return True


def _entry_key(entry):
    return entry.get("link") or entry.get("title") or ""


def _entry_record(feed_url, entry, seen):
    pub = entry_datetime(entry)
    return {
        "feed": feed_url,
        "seen": seen.isoformat(),
        "published": pub.isoformat() if pub else None,
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "summary": entry.get("summary", ""),
        "author": entry.get("author", ""),
        "tags": [t.get("term", "") for t in entry.get("tags", [])],
        "source_href": (entry.get("source") or {}).get("href", ""),
    }


def _record_entry(rec):
    """Rebuild a feedparser-like entry from a stored record."""
    entry = feedparser.FeedParserDict(
        title=rec["title"], link=rec["link"], summary=rec["summary"],
        author=rec["author"],
        tags=[feedparser.FeedParserDict(term=t) for t in rec["tags"]])
    if rec["source_href"]:
        entry["source"] = feedparser.FeedParserDict(href=rec["source_href"])
    if rec["published"]:
        entry["published_parsed"] = datetime.fromisoformat(rec["published"]).utctimetuple()
    return entry


class EntryStore:
    """
    Feed entries saved between runs: one JSON-lines file per UTC day of
    first sighting, holding each (feed, link) once. Files older than
    *keep_days* are deleted.
    """

    def __init__(self, directory, keep_days=ENTRY_STORE_KEEP_DAYS, read_only=False):
        self.directory = directory
        self.keep_days = keep_days
        self.read_only = read_only
        self.by_feed = {}  # feed url -> {entry key: record}
        os.makedirs(directory, exist_ok=True)

    def _files(self):
        for name in sorted(os.listdir(self.directory)):
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.jsonl", name)
            if m:
                yield m.group(1), os.path.join(self.directory, name)

    def _lock(self):
        import fcntl
        f = open(os.path.join(self.directory, ".lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    def load(self):
        with self._lock():
            for _, path in self._files():
                with open(path) as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue  # a line cut short by a crash
                        self.by_feed.setdefault(rec["feed"], {}).setdefault(_entry_key(rec), rec)
        return self

    def entries_for(self, feed_url):
        return list(self.by_feed.get(feed_url, {}).values())

    def add(self, feed_url, entries, now):
        """Save the entries not stored yet; return how many were new."""
        if self.read_only:
            return 0
        known = self.by_feed.setdefault(feed_url, {})
        new = []
        for entry in entries:
            key = _entry_key(entry)
            if key and key not in known:
                known[key] = rec = _entry_record(feed_url, entry, now)
                new.append(rec)
        if new:
            with self._lock(), open(os.path.join(
                    self.directory, f"{now:%Y-%m-%d}.jsonl"), "a") as f:
                for rec in new:
                    f.write(json.dumps(rec) + "\n")
        return len(new)

    def prune(self, now):
        oldest = (now - timedelta(days=self.keep_days)).strftime("%Y-%m-%d")
        with self._lock():
            for day, path in self._files():
                if day < oldest:
                    os.remove(path)


# Article text fetched by the hourly --store-only runs, so the weekly crawl
# doesn't fetch ~10,000 pages at once (the 2026-11-05 run did, and was killed
# mid-way by a reboot). Only text is cached; matching still runs at crawl
# time, so keyword changes apply to cached text too.
TEXT_STORE_KEEP_DAYS = 14
# Store runs fetch text for entries first seen this recently: an edition's
# week plus a day of slack.
TEXT_STORE_LOOKBACK_DAYS = 8
# Most new entries per hourly run is ~100; the cap spreads a backlog (first
# run, or after an outage) over several runs instead of one burst.
TEXT_FETCHES_PER_STORE_RUN = 1500


class TextStore:
    """
    Fetched article text by URL: one JSON-lines file per UTC day of
    fetching under *directory*, text zlib-compressed. The latest record for
    a URL wins. A failed fetch is saved as empty text and retried by later
    runs up to MAX_TRIES times in all; after that it counts as no text.
    """

    MAX_TRIES = 3

    def __init__(self, directory, keep_days=TEXT_STORE_KEEP_DAYS, read_only=False):
        self.directory = directory
        self.keep_days = keep_days
        self.read_only = read_only
        self.records = {}  # url -> {"url", "fetched", "tries", "z"}
        os.makedirs(directory, exist_ok=True)

    def _files(self):
        for name in sorted(os.listdir(self.directory)):
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.jsonl", name)
            if m:
                yield m.group(1), os.path.join(self.directory, name)

    def _lock(self):
        import fcntl
        f = open(os.path.join(self.directory, ".lock"), "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    def load(self):
        with self._lock():
            for _, path in self._files():
                with open(path) as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue  # a line cut short by a crash
                        self.records[rec["url"]] = rec
        return self

    @staticmethod
    def _text(rec):
        import base64
        import zlib
        return zlib.decompress(base64.b64decode(rec["z"])).decode("utf-8") if rec["z"] else ""

    def get(self, url):
        """The saved text, "" if every try failed, or None to fetch it now."""
        rec = self.records.get(url)
        if rec is None:
            return None
        if rec["z"] or rec["tries"] >= self.MAX_TRIES:
            return self._text(rec)
        return None

    def needs_fetch(self, url):
        return self.get(url) is None

    def save(self, texts, now):
        """Save {url: text}; empty text is a failed try."""
        import base64
        import zlib
        if self.read_only or not texts:
            return
        lines = []
        for url, text in texts.items():
            prev = self.records.get(url)
            rec = {"url": url, "fetched": now.isoformat(),
                   "tries": (prev["tries"] if prev else 0) + 1,
                   "z": base64.b64encode(zlib.compress(text.encode("utf-8"))).decode("ascii")
                        if text else ""}
            self.records[url] = rec
            lines.append(json.dumps(rec) + "\n")
        with self._lock(), open(os.path.join(
                self.directory, f"{now:%Y-%m-%d}.jsonl"), "a") as f:
            f.writelines(lines)

    def prune(self, now):
        oldest = (now - timedelta(days=self.keep_days)).strftime("%Y-%m-%d")
        with self._lock():
            for day, path in self._files():
                if day < oldest:
                    os.remove(path)


def text_store_dir(entry_store):
    return os.path.join(entry_store, "texts")


def polite_fetch_options(feed_config):
    """fetch_article_texts() keyword arguments from feeds.yaml."""
    return {"polite_hosts": [str(h).lower() for h in (feed_config.get("polite_hosts") or [])],
            "polite_delay": float(feed_config.get("polite_delay", 2))}


def store_article_texts(args, feed_config, store, now):
    """
    Fetch and save the article text of recently stored entries that don't
    match on title, summary or tags: the ones the weekly crawl would check
    against full text. Returns (fetched, still to fetch).
    """
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    language_keywords = feed_config.get("keywords") or {}
    texts = TextStore(text_store_dir(args.entry_store)).load()
    since = now - timedelta(days=TEXT_STORE_LOOKBACK_DAYS)
    todo = []  # (first seen, url)
    for feed_def in feed_config.get("feeds", []):
        lang = str(feed_def.get("lang") or "en").lower()
        feed_keywords = keywords_for_language(keywords, language_keywords, lang)
        for rec in store.entries_for(feed_def["url"]):
            link = rec["link"]
            # A newly added feed lists old articles as new: skip those too.
            if (not link or rec["seen"] < since.isoformat()
                    or (rec["published"] and rec["published"] < since.isoformat())
                    or _host(link) in _AGGREGATOR_HOSTS or not texts.needs_fetch(link)):
                continue
            haystack = f"{rec['title']} {rec['summary']} {' '.join(rec['tags'])}"
            if keyword_match(haystack, feed_keywords, lang):
                continue
            todo.append((rec["seen"], link))
    urls = list(dict.fromkeys(u for _, u in sorted(todo, reverse=True)))
    batch = urls[:TEXT_FETCHES_PER_STORE_RUN]
    if batch:
        texts.save(fetch_article_texts(batch, **polite_fetch_options(feed_config)), now)
    texts.prune(now)
    return len(batch), len(urls) - len(batch)


def merge_stored_entries(live, stored, start_dt):
    """
    Live entries plus the stored ones the feed no longer shows. An undated
    stored entry is kept only if first seen in the window: the window check
    can't place it, and it would otherwise reappear in every edition.
    """
    live_keys = {_entry_key(e) for e in live}
    merged = list(live)
    for rec in stored:
        if _entry_key(rec) in live_keys:
            continue
        if not rec["published"] and datetime.fromisoformat(rec["seen"]) < start_dt:
            continue
        merged.append(_record_entry(rec))
    return merged


def store_only(args, now):
    """Fetch every feed and save new entries; no matching or report."""
    with open(args.feeds) as f:
        feed_config = yaml.safe_load(f)
    feeds = feed_config.get("feeds", [])
    store = EntryStore(args.entry_store, args.entry_store_days)
    if store_disk_full(args):
        # Pruning only frees space, so still drop expired days.
        store.prune(now)
        return 2
    store.load()
    socket.setdefaulttimeout(60)
    failed = 0
    print(f"[store] {now:%Y-%m-%d %H:%M:%S} UTC: fetching {len(feeds)} feeds "
          f"into {args.entry_store}", file=sys.stderr)
    print(f"  {'Feed':<40} {'entries':>7} {'new':>5}  oldest entry", file=sys.stderr)
    for feed_def in feeds:
        name = feed_def.get("name", feed_def["url"])
        try:
            parsed = fetch_feed(feed_def["url"])
            if parsed.bozo and not parsed.entries:
                raise ValueError(parsed.bozo_exception)
            if feed_def.get("timezone"):
                localise_naive_dates(parsed.entries, feed_def["timezone"])
        except Exception as e:
            failed += 1
            print(f"  {name:<40} failed: {str(e)[:60]}", file=sys.stderr)
            continue
        new = store.add(feed_def["url"], parsed.entries, now)
        dates = [d for d in map(entry_datetime, parsed.entries) if d]
        # How far back the feed reaches tells us whether runs are frequent
        # enough: a feed whose oldest entry is newer than the last run has
        # dropped items we never saw.
        span = f"{(now - min(dates)).total_seconds() / 3600:.0f}h ago" if dates else "-"
        print(f"  {name:<40} {len(parsed.entries):>7} {new:>5}  {span}", file=sys.stderr)
    store.prune(now)
    print(f"[store] Done: {len(feeds) - failed} feeds fetched, {failed} failed.", file=sys.stderr)
    if not args.no_fetch_articles:
        started = time.time()
        fetched, left = store_article_texts(args, feed_config, store, now)
        print(f"[store] Article text: fetched {fetched} in {time.time() - started:.0f}s"
              + (f", {left} left for later runs" if left else "") + ".", file=sys.stderr)
    return 1 if failed == len(feeds) else 0


# Page furniture that carries *other* stories' headlines: navigation, sidebars,
# "related"/"trending"/"most read" blocks, newsletter promos, footers. Text from
# these is not part of the article and must not be matched against keywords, or
# an unrelated article on a site that happens to also cover CC will be reported
# under its own irrelevant headline and link.
_CHROME_TAGS = ("nav", "aside", "header", "footer", "form", "script", "style",
                "noscript", "iframe", "figure", "figcaption")
_CHROME_HINTS = re.compile(
    r"(related|recommend|trending|most[-_ ]?read|popular|latest|more[-_ ]?from|"
    r"read[-_ ]?(also|more|next)|you[-_ ]?may[-_ ]?(also[-_ ]?)?like|"
    r"sidebar|widget|promo|newsletter|subscribe|advert|sponsor|outbrain|taboola|"
    r"comment|share|social|breadcrumb|menu|nav|footer|header|tags?[-_ ]?list|"
    # Author bios list everything the writer covers, so a CC mention there is
    # about the author's beat, not this article. Observed live: a Red Hat
    # post-quantum article matched only via "He also covers confidential
    # computing" in the byline block.
    r"author|byline|contributor|about[-_ ]?(the[-_ ]?)?author|profile)",
    re.IGNORECASE,
)


def extract_article_text(html):
    """
    Return the text of the article body only, excluding page furniture.

    Falling back to <body> pulls in navigation and "related stories" blocks,
    whose text belongs to *different* articles. A keyword match there is a
    false positive that attributes an unrelated story's relevance to this one.
    """
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(list(_CHROME_TAGS)):
        tag.decompose()
    # Containers whose id/class names mark them as furniture
    for el in soup.find_all(attrs={"class": _CHROME_HINTS}):
        el.decompose()
    for el in soup.find_all(attrs={"id": _CHROME_HINTS}):
        el.decompose()

    # Prefer explicit article semantics; fall back progressively.
    node = (soup.find("article")
            or soup.find(attrs={"itemprop": "articleBody"})
            or soup.find(attrs={"class": re.compile(r"(article|entry|post|story)[-_]?(body|content|text)", re.I)})
            or soup.find("main"))
    if node is None:
        # No article container: use the densest block of <p> text rather than
        # the whole body, which would re-admit the chrome we just stripped.
        best, best_len = None, 0
        for cand in soup.find_all(["div", "section"]):
            paras = cand.find_all("p", recursive=False)
            if not paras:
                continue
            length = sum(len(x.get_text(" ", strip=True)) for x in paras)
            if length > best_len:
                best, best_len = cand, length
        node = best
    if node is None:
        return ""

    # Within the chosen container, keep paragraph text: headline lists in
    # related-story modules are usually <a>/<h*>/<li>, not <p>.
    paras = node.find_all("p")
    if paras:
        text = " ".join(x.get_text(" ", strip=True) for x in paras)
        if len(text) >= 200:
            return text
    return node.get_text(" ", strip=True)


def fetch_article_text(url):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # Bail out if we ended up on a Google consent/login page rather than the article
        from urllib.parse import urlparse
        final_host = urlparse(resp.url).netloc.lstrip("www.")
        if any(final_host == d or final_host.endswith("." + d) for d in _REDIRECT_DOMAINS):
            return ""
        # Without a declared charset requests assumes ISO-8859-1, which garbles
        # UTF-8 accents ("computaciÃ³n"); BeautifulSoup reads the page's own
        # <meta charset> from the raw bytes instead.
        declared = "charset" in resp.headers.get("content-type", "").lower()
        return extract_article_text(resp.text if declared else resp.content)
    except Exception:
        return ""


def fetch_article_texts(urls, workers=48, per_server=2, polite_hosts=(),
                        polite_delay=2.0):
    """
    {url: article text} for *urls*, fetched in parallel. At most *per_server*
    requests go to one server (IP address) at a time, so a big feed doesn't
    hammer its site. Hosts are grouped by address because outlets share
    servers: the six IT Brief / SecurityBrief sites are one machine, which
    started answering 403 when each hostname got its own allowance.
    The server of each host in *polite_hosts* gets one request at a time,
    with *polite_delay* seconds between them.
    Failed fetches give "", as with fetch_article_text().
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urlparse

    urls = list(dict.fromkeys(urls))
    # Google News links lead to a consent page, never the article.
    unfetchable = {u for u in urls if (urlparse(u).hostname or "") in _AGGREGATOR_HOSTS}
    urls = [u for u in urls if u not in unfetchable]

    def resolve(host):
        try:
            return socket.gethostbyname(host)
        except (OSError, UnicodeError):
            return host

    server_of = {h: resolve(h) for h in {urlparse(u).hostname or "" for u in urls}}
    polite = {resolve(h) for h in polite_hosts} | set(polite_hosts)

    def server(url):
        return server_of[urlparse(url).hostname or ""]

    locks = {s: threading.Semaphore(1 if s in polite else per_server)
             for s in set(server_of.values())}

    def one(url):
        s = server(url)
        with locks[s]:
            text = fetch_article_text(url)
            if s in polite:
                time.sleep(polite_delay)  # still holding the server's slot
            return url, text

    # Interleave servers so the workers don't all queue behind one site.
    by_server = {}
    for url in urls:
        by_server.setdefault(server(url), []).append(url)
    queues = list(by_server.values())
    order = [q[i] for i in range(max(map(len, queues), default=0))
             for q in queues if i < len(q)]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return {**dict.fromkeys(unfetchable, ""), **dict(pool.map(one, order))}


_TITLE_VERBS = {
    'rebrands', 'relaunches', 'launches', 'announces', 'introduces', 'reveals',
    'wins', 'hires', 'appoints', 'confirms', 'submits', 'makes', 'gets', 'adds',
    'targets', 'raises', 'drops', 'gains', 'loses', 'beats', 'reports',
    'releases', 'unveils', 'acquires', 'merges', 'cuts', 'expands', 'enters',
    'joins', 'names', 'signs', 'buys', 'sells', 'plans', 'says', 'warns',
    'claims', 'moves', 'funds', 'sets', 'builds', 'creates', 'develops',
    'achieves', 'receives', 'secures', 'files', 'provides', 'delivers',
    'begins', 'starts', 'updates', 'upgrades', 'has', 'is', 'are', 'was',
    'were', 'backs', 'puts', 'gives', 'shows', 'finds', 'offers', 'enters',
    'exits', 'closes', 'opens', 'completes', 'passes', 'approves', 'denies',
    'just', 'also', 'still', 'only', 'now',
}

_TITLE_SKIP_STARTS = {
    'the', 'a', 'an', 'new', 'latest', 'top', 'best', 'major', 'how',
    'why', 'what', 'ai', 'ceo', 'search', 'first',
}


def infer_subject(title):
    """Best-effort extraction of the most likely subject company from a title."""
    title = re.sub(r'\s*[-–]\s*[A-Z][^-]*$', '', title).strip()
    subject_words = []
    for raw_word in title.split():
        ends_comma = raw_word.endswith(',')
        word = re.sub(r"'s$", '', raw_word.rstrip('.,;:!?():'))
        if not word:
            continue
        if not subject_words and word.lower() in _TITLE_SKIP_STARTS:
            break
        if not word[0].isupper():
            break
        if word.lower() in _TITLE_VERBS:
            break
        subject_words.append(word)
        if ends_comma or len(subject_words) >= 4:
            break
    if not subject_words:
        return None
    result = ' '.join(subject_words)
    if len(subject_words) == 1 and result.lower() in {'it', 'he', 'she', 'we', 'i', 'this', 'that'}:
        return None
    return result


def normalize_company_name(name):
    """Normalize company name for intelligent duplicate detection."""
    if not name:
        return ""
    
    # Remove common business suffixes
    suffixes = [
        r'\s+(corp|corporation|inc|incorporated|ltd|limited|llc|llp|co|company)\b\.?',
        r'\s+(ceo|founder|exec|executive|president)\b.*',  # Remove executive titles
        r'\s+(review|analysis|report|news|update)\b.*',   # Remove article descriptors
        r'^(beyond|what\s+is|driving\s+innovation\s+in)\s+',  # Remove article prefixes
    ]
    
    normalized = name.lower().strip()
    for suffix_pattern in suffixes:
        normalized = re.sub(suffix_pattern, '', normalized, flags=re.IGNORECASE).strip()
    
    # Handle specific cases
    normalized = re.sub(r'\s+', ' ', normalized)  # Normalize whitespace
    
    # Extract core company name from complex titles
    # Example: "Beyond Privacy Coins Arcium's" -> "arcium"
    if 'arcium' in normalized:
        normalized = 'arcium'
    elif 'alpha compute' in normalized:
        normalized = 'alpha compute'
    elif 'l&t vyoma' in normalized:
        normalized = 'l&t vyoma'
    
    return normalized


def build_subject_index(dont_bucket, members):
    """Group 'Other' articles by inferred subject, with intelligent duplicate consolidation."""
    cleaned_members = [c for m in members for c in [clean_member_name(m)] if len(c) > 2]
    raw_index = {}
    
    # First pass: collect all subjects
    for article in dont_bucket:
        subject = infer_subject(article["title"])
        if not subject:
            continue
        subject_lower = subject.lower()
        if any(re.search(rf"\b{re.escape(c)}\b", subject_lower) for c in cleaned_members):
            continue
        raw_index.setdefault(subject, []).append(article)
    
    # Second pass: merge duplicates using normalized names
    normalized_to_canonical = {}  # normalized name -> best canonical name
    normalized_to_articles = {}   # normalized name -> list of articles
    
    for subject, articles in raw_index.items():
        normalized = normalize_company_name(subject)
        if not normalized:
            continue
            
        # Choose the shortest, cleanest name as canonical
        if normalized not in normalized_to_canonical:
            normalized_to_canonical[normalized] = subject
            normalized_to_articles[normalized] = articles
        else:
            # Prefer shorter, cleaner names over longer descriptive ones
            current_canonical = normalized_to_canonical[normalized]
            if len(subject) < len(current_canonical) and not re.search(r'\b(review|analysis|ceo|beyond)\b', subject.lower()):
                normalized_to_canonical[normalized] = subject
            
            # Merge articles
            normalized_to_articles[normalized].extend(articles)
    
    # Build final index with canonical names
    final_index = {}
    for normalized, canonical_name in normalized_to_canonical.items():
        articles = normalized_to_articles[normalized]
        final_index[canonical_name] = articles
    
    return final_index


# ---------------------------------------------------------------------------
# Story classification & categorization
# ---------------------------------------------------------------------------

STORY_CATEGORIES = {
    "Service/Product Announcement": [
        r"\blaunch(es)?\b", r"\bintroduce(s)?\b", r"\bunveil(s)?\b", r"\brelease(s)?\b", 
        r"\bplatform\b", r"\bproduct\b", r"\bservice\b", r"\bsolution\b", r"\bplugclaw\b", 
        r"\bvfpga\b", r"\bsystem architecture\b", r"\bmicroarchitecture\b", r"\bhardware\b", 
        r"\bprocessor(s)?\b", r"\bgpu(s)?\b", r"\bcpu(s)?\b", r"\bchip(s)?\b", r"\bserver\b", 
        r"\bvirtualization\b", r"\bvm\b", r"\bcontainer\b"
    ],
    "Sales/Commercial Win": [
        r"\bprocures?\b", r"\bsecured?\s+contract\b", r"\bwins?\s+contract\b", r"\bsecures?\s+\$\d+\b", 
        r"\bterm\s+sheet\b", r"\bsigns?\s+deal\b", r"\bsigns?\s+agreement\b", r"\bmulti-year\s+agreement\b", 
        r"\bcontracted\s+arr\b", r"\bto\s+buy\s+.*\s+for\s+\$\d+\b", r"\bdeal\s+for\s+.*\s+to\s+build\b"
    ],
    "Technical & Research Story": [
        r"\bresearch\b", r"\bdeep-dive\b", r"\barchitecture\b", r"\btechnical\s+blog\b", 
        r"\bvulnerabilit\w*\b", r"\bexploit\b", r"\battack\b", r"\bside-channel\b", r"\bcryptograph\w*\b", 
        r"\battestation\b", r"\bproof-of-concept\b", r"\bverification\b", r"\bverifiable\b"
    ],
    "Financial Results": [
        r"\bearnings\b", r"\bquarter\b", r"\bq[1-4]\b", r"\brevenue\b", r"\bfinancial\s+results\b", 
        r"\bnet\s+loss\b", r"\bnet\s+income\b", r"\bfiscal\b", r"\braises?\s+\$\d+\b", r"\bposts?\s+\$\d+\b", 
        r"\bassets\b", r"\bshares\s+outstanding\b", r"\bshare\s+count\b", r"\bmarket\s+cap\w*\b", 
        r"\btreasury\b", r"\bholdings\b", r"\bvaluation\b", r"\bcapitalization\b", r"\bfunding\b"
    ],
    "Technical Strategy & Opinion": [
        r"\bopinion\b", r"\btrends?\b", r"\bperspectives?\b", r"\bstrategy\b", r"\bwhy\s+ai\b", 
        r"\beconomics\b", r"\bthe\s+importance\s+of\b", r"\bgeography\s+trap\b", r"\bfuture\s+of\b", 
        r"\bguide\b", r"\bhow\s+to\b", r"\bwhat\s+is\b"
    ],
    "Corporate Governance & Team News": [
        r"\bappoint(s|ment|ments)?\b", r"\bboard\s+of\s+directors\b", r"\bleadership\b", r"\bceo\b", 
        r"\bpresident\b", r"\bteam\s+news\b", r"\bhires?\b", r"\bfellowship\b"
    ],
    "Ecosystem Integration & Partnership": [
        r"\bpartner(s|ed|ship)?\b", r"\bintegrat(es|ed|ion)?\b", r"\bcollaborat(es|ed|ion)?\b", 
        r"\bjoins\b", r"\balliances?\b", r"\bteams\s+with\b"
    ],
    "Sovereign Cloud & Compliance": [
        r"\bsovereign\s+cloud\b", r"\bsovereignty\b", r"\bcompliance\b", r"\bregulated\s+ai\b", 
        r"\bdata\s+ownership\b", r"\btrust\s+boundary\b", r"\bregains\b"
    ],
    "Standards, Benchmarks & Coalitions": [
        r"\bstandards\b", r"\bbenchmark\b", r"\bcoalition\b", r"\bmedperf\b", r"\bmlcommons\b", 
        r"\bopen\s+standards\b", r"\bappia\s+foundation\b", r"\bagentic\s+ai\s+foundations?\b", 
        r"\blinux\s+foundation\b"
    ]
}

STORY_STYLING = {
    "Service/Product Announcement": {"emoji": "🚀", "color": "#007acc"},
    "Sales/Commercial Win": {"emoji": "🏆", "color": "#28a745"},
    "Technical & Research Story": {"emoji": "🔬", "color": "#6f42c1"},
    "Financial Results": {"emoji": "💰", "color": "#fd7e14"},
    "Technical Strategy & Opinion": {"emoji": "💡", "color": "#e67e22"},
    "Corporate Governance & Team News": {"emoji": "👥", "color": "#17a2b8"},
    "Ecosystem Integration & Partnership": {"emoji": "🤝", "color": "#e83e8c"},
    "Sovereign Cloud & Compliance": {"emoji": "🛡️", "color": "#20c997"},
    "Standards, Benchmarks & Coalitions": {"emoji": "📋", "color": "#6c757d"},
    "General CC News": {"emoji": "📰", "color": "#5a6268"}
}

def format_story_type_tag(story_type, use_styling=True):
    """Format the story type tag with colored HTML span and emoji, or plain text if styling is disabled."""
    story_type = story_type or "General CC News"
    if not use_styling:
        return story_type
    style = STORY_STYLING.get(story_type, STORY_STYLING["General CC News"])
    color = style["color"]
    emoji = style["emoji"]
    return f'<span style="color: {color}; font-weight: bold;">{emoji} {story_type}</span>'

_CLASSIFY_PROMPT_TPL = (
    "You are a news editor specializing in Confidential Computing. Classify each of the "
    "following news articles into exactly ONE of the following categories:\n"
    "1. 'Service/Product Announcement'\n"
    "2. 'Sales/Commercial Win'\n"
    "3. 'Technical & Research Story'\n"
    "4. 'Financial Results'\n"
    "5. 'Technical Strategy & Opinion'\n"
    "6. 'Corporate Governance & Team News'\n"
    "7. 'Ecosystem Integration & Partnership'\n"
    "8. 'Sovereign Cloud & Compliance'\n"
    "9. 'Standards, Benchmarks & Coalitions'\n"
    "10. 'General CC News' (if none of the above match well)\n\n"
    "Respond with ONLY a JSON object mapping each article id to its single most fitting category name. "
    "Do not include any prose, markdown block, or other text outside the JSON block.\n"
    "Example format: {{\"categories\": {{\"0\": \"Service/Product Announcement\", \"1\": \"Financial Results\"}}}}\n\n"
    "Articles: {articles_json}"
)


def classify_stories_heuristic(articles):
    """Categorize articles using heuristic keyword matching rules."""
    for a in articles:
        matched = []
        for cat, regexes in STORY_CATEGORIES.items():
            for regex in regexes:
                if re.search(regex, a["title"], re.IGNORECASE):
                    matched.append(cat)
                    break
        a["story_type"] = matched[0] if matched else "General CC News"


def classify_stories_ai(articles):
    """Categorize articles using the claude CLI."""
    # First apply heuristic as baseline / fallback
    classify_stories_heuristic(articles)

    compact = []
    for a in articles:
        compact.append({
            "id": a["_id"],
            "title": a["title"],
            "publisher": a.get("publisher", ""),
            "description": a.get("summary", "")[:200]
        })

    prompt = _CLASSIFY_PROMPT_TPL.format(articles_json=json.dumps(compact, separators=(",", ":")))

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()[:200]}")

        envelope = json.loads(result.stdout)
        raw = envelope.get("result", "")
        raw = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", raw).strip()
        data = json.loads(raw)

        categories_map = data.get("categories")
        if isinstance(categories_map, dict):
            for a in articles:
                aid_str = str(a["_id"])
                if aid_str in categories_map:
                    a["story_type"] = categories_map[aid_str]
    except Exception as e:
        print(f"[warn] AI classification failed ({e}); keeping heuristic baseline classification.", file=sys.stderr)


WEBFEED_EDITION_RE = r"^(?:subjects-)?webfeed-{date}-(\d{{2,}})\.(?:md|json)$"


_TRANSLATE_PROMPT_TPL = (
    "Translate each news headline below into natural English. Keep company, "
    "product and person names as they are. If a headline ends with \" - \" "
    "and a publication name, keep that suffix unchanged. If a headline is "
    "already in English, return it unchanged. Reply with only a JSON object "
    "mapping each id to its English headline, and no other text.\n\n"
    "{titles_json}"
)
TRANSLATE_BATCH = 50


def _translate_with_claude(titles):
    """{title: English title} for *titles*, via the claude CLI."""
    out = {}
    for i in range(0, len(titles), TRANSLATE_BATCH):
        batch = titles[i:i + TRANSLATE_BATCH]
        prompt = _TRANSLATE_PROMPT_TPL.format(titles_json=json.dumps(
            {str(n): t for n, t in enumerate(batch)}, ensure_ascii=False))
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()[:200]}")
        raw = json.loads(result.stdout).get("result", "")
        raw = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", raw).strip()
        for n, english in json.loads(raw).items():
            if n.isdigit() and int(n) < len(batch) and isinstance(english, str):
                out[batch[int(n)]] = english.strip()
    return out


def translate_titles(articles, cache_path, translate=None):
    """
    Give each non-English article an English `title`, keeping the original
    in `title_original`. Translations are cached in *cache_path* by original
    title, so each headline is translated once. If translation fails the
    original title is kept and a warning printed.

    Returns the number of articles given an English title.
    """
    todo = [a for a in articles if a.get("lang", "en") != "en" and a.get("title")]
    if not todo:
        return 0
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (FileNotFoundError, ValueError):
        cache = {}

    missing = sorted({a["title"] for a in todo} - cache.keys())
    if missing:
        try:
            cache.update((translate or _translate_with_claude)(missing))
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, cache_path)
        except Exception as e:
            print(f"[warn] Could not translate {len(missing)} titles ({e}); "
                  f"showing them untranslated.", file=sys.stderr)

    translated = 0
    for a in todo:
        english = (cache.get(a["title"]) or "").strip()
        if english and english != a["title"].strip():
            a["title_original"] = a["title"]
            a["title"] = english
            translated += 1
    return translated


def next_webfeed_output(directory, date_str):
    """
    Return the default path for this run's webfeed edition:
    `webfeed-DATE-NN.md`, where NN starts at 00 and goes up by one for each
    edition written that UTC day.

    Before 2.9.0 every edition on a day shared `webfeed-DATE.md`, so a second
    run overwrote the first while the resume point still moved forward, and
    the first edition's articles were lost from the published files.

    NN is one more than the highest number already used by either the report
    or its subject index, not the first unused number. Filling a gap left by
    a deleted file would put a later edition before an earlier one when the
    files are sorted.
    """
    pattern = re.compile(WEBFEED_EDITION_RE.format(date=re.escape(date_str)))
    try:
        names = os.listdir(directory or ".")
    except OSError:
        names = []
    used = [int(m.group(1)) for m in map(pattern.match, names) if m]
    seq = max(used) + 1 if used else 0
    name = f"webfeed-{date_str}-{seq:02d}.md"
    return os.path.join(directory, name) if directory else name


def derive_subjects_json_path(md_output):
    directory = os.path.dirname(md_output)
    basename = os.path.basename(md_output)
    if basename.startswith("report-") and basename.endswith(".md"):
        json_name = "subjects-" + basename[len("report-"):-len(".md")] + ".json"
    elif basename.startswith("webfeed-") and basename.endswith(".md"):
        # `subjects-webfeed-DATE-NN.json`: still matches the `subjects-*.json`
        # glob that ccc-potentials consumes, so an edition contributes news
        # coverage signals — but does not overwrite a report's index, which
        # covers a wider period (30 days by default vs the edition's 7) and
        # would otherwise be silently narrowed.
        json_name = "subjects-webfeed-" + basename[len("webfeed-"):-len(".md")] + ".json"
    else:
        json_name = basename.rsplit(".", 1)[0] + ".subjects.json"
    return os.path.join(directory, json_name) if directory else json_name


# ---------------------------------------------------------------------------
# Story clustering
# ---------------------------------------------------------------------------

_CLUSTER_PROMPT_TPL = (
    "You are a news editor. Given a JSON array of news article metadata, group them "
    "into clusters where each cluster covers exactly ONE specific, distinct news story or event. "
    "\n\nSTRICT CLUSTERING RULES:\n"
    "- Only group articles covering the EXACT SAME specific incident, announcement, or event\n"
    "- Different vulnerabilities/flaws, even in similar technologies, MUST be separate clusters\n"
    "- Different company announcements MUST be separate clusters\n"
    "- General topics like 'confidential computing news' should NOT be clustered together\n"
    "- Articles about related but distinct events MUST be in different clusters\n"
    "- When in doubt, keep articles SEPARATE\\n"
    "- NEVER group articles about different vulnerabilities\\n"
    "- NEVER group articles about different companies\\n"
    "- NEVER group articles from different domains unless 100% identical\\n"
    "- NEVER group articles with different technical details\\n\\n"
    "EXAMPLES OF WHAT NOT TO CLUSTER:\n"
    "- 'Intel SGX vulnerability' + 'AMD SEV vulnerability' → SEPARATE (different flaws)\n"
    "- 'Microsoft AI announcement' + 'Google AI announcement' → SEPARATE (different companies)\n"
    "- 'Remote attestation flaw A' + 'Remote attestation flaw B' → SEPARATE (different flaws)\n\n"
    "Each cluster should represent one specific factual event, not a general topic. "
    "Every article id must appear in exactly one cluster. "
    "Standalone articles that do not match any other article should be singleton clusters. "
    "Respond with ONLY a JSON object on a single line — no prose, no markdown — in "
    'exactly this form: {{"clusters": [{{"label": "Specific event description", "ids": [1, 2]}}, ...]}}\n\n'
    "Articles: {articles_json}"
)


def cluster_stories(articles):
    """Cluster articles by same story using the claude CLI.

    Returns (id_to_cluster, cluster_labels) where:
      id_to_cluster:  {article _id -> cluster int}
      cluster_labels: {cluster int -> label string}

    Raises on any failure so the caller can fall back to heuristic_cluster().
    """
    compact = []
    for a in articles:
        company = a.get("member") or infer_subject(a["title"]) or ""
        compact.append({
            "id": a["_id"],
            "title": a["title"],
            "publisher": a.get("publisher", ""),
            "company": company,
            "date": a.get("published", ""),
        })

    prompt = _CLUSTER_PROMPT_TPL.format(articles_json=json.dumps(compact, separators=(",", ":")))

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()[:200]}")

    envelope = json.loads(result.stdout)
    raw = envelope.get("result", "")
    raw = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", raw).strip()
    data = json.loads(raw)

    clusters = data.get("clusters")
    if not isinstance(clusters, list):
        raise ValueError(f"Unexpected cluster payload: {raw[:200]}")

    # Validate that the result is a true partition of the input ids
    input_ids = {a["_id"] for a in articles}
    seen = set()
    id_to_cluster = {}
    cluster_labels = {}
    for cid, cluster in enumerate(clusters):
        label = cluster.get("label", f"Story {cid + 1}")
        for aid in cluster.get("ids", []):
            if aid in seen:
                raise ValueError(f"Article id {aid} appears in multiple clusters")
            if aid not in input_ids:
                raise ValueError(f"Unknown article id {aid} in cluster result")
            seen.add(aid)
            id_to_cluster[aid] = cid
        cluster_labels[cid] = label

    missing = input_ids - seen
    if missing:
        raise ValueError(f"Articles missing from clusters: {missing}")

    return id_to_cluster, cluster_labels


def _title_tokens(title):
    """Normalised token set for Jaccard title-similarity comparison."""
    _stop = {
        'the', 'a', 'an', 'in', 'on', 'at', 'to', 'of', 'for', 'and', 'or',
        'is', 'are', 'was', 'were', 'it', 'its', 'with', 'by', 'as', 'from',
        'that', 'this', 'be', 'has', 'have',
    }
    return {
        w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
        if w not in _stop and len(w) > 1
    }


def _parse_pub_date(pub_str):
    """Parse a published string to a UTC datetime; return None on failure."""
    if not pub_str:
        return None
    try:
        import email.utils as _eu
        return _eu.parsedate_to_datetime(pub_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.strptime(pub_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _story_label(titles):
    """
    Build a human-readable label for a group of articles about one story.

    The label must describe the *event*, not name a company: the old behaviour
    used the most common company across the group, which rendered as bare
    headers like "**Huawei**". Those read as a per-company section of the
    report, which is wrong — the report is not organised by company, and other
    articles about that company appear elsewhere.

    A real headline is used rather than a synthesised common-substring, because
    word-overlap fragments come out as truncated noise ("Embedded Intelligence
    And"). The shortest headline is preferred: it carries the fewest publisher
    suffixes and sub-clauses while still being a sentence someone wrote.
    """
    cleaned = []
    for t in titles:
        if not t or not t.strip():
            continue
        # Drop the trailing " - Publisher" that Google News appends
        t = re.sub(r"\s+[-\u2013|]\s+[^-\u2013|]{1,40}$", "", t).strip()
        if t:
            cleaned.append(t)
    if not cleaned:
        return "Related coverage"

    label = min(cleaned, key=len)
    if len(label) > 96:
        label = label[:93].rstrip() + "..."
    return label


def heuristic_cluster(articles, date_window_days=1, jaccard_threshold=0.4):
    """
    Deterministic same-story clustering (fallback when the claude CLI is unavailable).

    Two articles are merged when ALL three conditions hold:
      1. They share a non-empty, cleaned company key (member or inferred subject).
      2. Their publication dates are within date_window_days of each other.
      3. Their title token Jaccard similarity >= jaccard_threshold.

    Uses union-find for transitive grouping.
    Returns (id_to_cluster, cluster_labels).
    """
    n = len(articles)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    companies = []
    dates = []
    tokens = []
    for a in articles:
        raw_co = a.get("member", "") or (infer_subject(a["title"]) or "")
        companies.append(clean_member_name(raw_co) if raw_co else "")
        dates.append(_parse_pub_date(a.get("published", "")))
        tokens.append(_title_tokens(a["title"]))

    for i in range(n):
        if not companies[i]:
            continue
        for j in range(i + 1, n):
            if companies[i] != companies[j]:
                continue
            if dates[i] and dates[j]:
                delta = abs((dates[i] - dates[j]).total_seconds()) / 86400
                if delta > date_window_days:
                    continue
            t_i, t_j = tokens[i], tokens[j]
            union_size = len(t_i | t_j)
            if union_size == 0:
                continue
            if len(t_i & t_j) / union_size < jaccard_threshold:
                continue
            
            # Conservative cross-domain clustering: require higher similarity for different domains
            # This prevents over-clustering while allowing legitimate same-story grouping
            url1 = articles[i].get("url", "")
            url2 = articles[j].get("url", "")
            if url1 and url2:
                try:
                    from urllib.parse import urlparse
                    domain1 = urlparse(url1).netloc.lower()
                    domain2 = urlparse(url2).netloc.lower()
                    
                    if domain1 != domain2:
                        # Different domains require higher similarity (0.6 vs 0.4)
                        if len(t_i & t_j) / union_size < 0.6:
                            continue
                except:
                    pass
            
            union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    id_to_cluster = {}
    cluster_labels = {}
    for cid, indices in enumerate(groups.values()):
        # Label the *story*, not the company. Using the most common company
        # produced bare headers like "**Huawei**", which read as a per-company
        # section rather than one shared story — misleading, since other
        # articles about the same company sit elsewhere in the report and the
        # report is not organised by company.
        label = _story_label([articles[idx]["title"] for idx in indices])
        for idx in indices:
            id_to_cluster[articles[idx]["_id"]] = cid
        cluster_labels[cid] = label

    return id_to_cluster, cluster_labels


def group_articles_by_story(categorized, members, use_ai=True):
    """
    Assign ``_id`` and ``_cluster`` to every article dict in *categorized*.
    Returns cluster_labels {cluster_id: label_string}.

    When use_ai is True the claude CLI is tried first; on any failure the
    heuristic falls back gracefully (matching the stale-cache pattern used for
    members refresh).
    """
    all_articles = (
        categorized["by_member"] + categorized["about_member"] + categorized["dont"]
    )
    for i, a in enumerate(all_articles):
        a["_id"] = i

    if not all_articles:
        return {}

    id_to_cluster = None
    cluster_labels = None

    if use_ai:
        try:
            id_to_cluster, cluster_labels = cluster_stories(all_articles)
            print(
                f"  AI clustered {len(all_articles)} articles into "
                f"{len(cluster_labels)} stories.",
                file=sys.stderr,
            )
        except FileNotFoundError:
            print(
                "[warn] claude CLI not found; falling back to heuristic story clustering.",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"[warn] AI clustering failed ({e}); falling back to heuristic.",
                file=sys.stderr,
            )

    if id_to_cluster is None:
        id_to_cluster, cluster_labels = heuristic_cluster(all_articles)
        print(
            f"  Heuristic clustered {len(all_articles)} articles into "
            f"{len(cluster_labels)} stories.",
            file=sys.stderr,
        )

    for a in all_articles:
        a["_cluster"] = id_to_cluster[a["_id"]]

    return cluster_labels


def _article_link(a):
    """Markdown link to an article; a translated title is followed by the original."""
    link = f"[{a['title']}]({a['url']})"
    if a.get("title_original"):
        link += f" (original: {a['title_original']})"
    return link


def _write_section(f, articles, cluster_labels, detail_fn, no_cluster=False, webfeed=False):
    """
    Write one report section's article list.

    *detail_fn(article)* returns the parenthetical detail string, e.g.
    ``"(Publisher: X, Member: Y) - Mon, 09 Jun 2026 ..."``.

    When *no_cluster* is True (or *cluster_labels* is empty) articles are
    rendered as a flat bullet list, identical to pre-clustering behaviour.
    Multi-article clusters are rendered under a bold story label; singletons
    are rendered as plain bullets so the report stays readable. In *webfeed*
    mode clusters get no label: their articles are plain, adjacent bullets.
    """
    if not articles:
        if not webfeed:
            f.write("None found.\n\n")
        return

    if no_cluster or not cluster_labels:
        for a in articles:
            f.write(f"- {_article_link(a)} {detail_fn(a)}\n")
        return

    # Group by cluster
    groups = {}
    for a in articles:
        groups.setdefault(a.get("_cluster", -1), []).append(a)

    def _sort_key(item):
        cid, group = item
        size = len(group)
        return (0 if size > 1 else 1, -size, cluster_labels.get(cid, "").lower())

    for cid, group in sorted(groups.items(), key=_sort_key):
        if len(group) == 1:
            a = group[0]
            f.write(f"- {_article_link(a)} {detail_fn(a)}\n")
        elif webfeed:
            # Published editions are plain lists: keep the story's articles
            # together, but with no label line or indent.
            for a in group:
                f.write(f"- {_article_link(a)} {detail_fn(a)}\n")
        else:
            label = cluster_labels.get(cid, f"Story {cid}")
            f.write(f"\n**{label}**\n")
            for a in group:
                f.write(f"  - {_article_link(a)} {detail_fn(a)}\n")


# Word edges for keywords and the context patterns below. \b would also need
# an edge between "TDX" and Japanese or Korean text written straight after
# it ("TDXを", "SGX를"), where there is none: those letters count as word
# characters too. Only ASCII letters, digits and _ continue a word here.
_WB = r"(?<![A-Za-z0-9_])"
_WE = r"(?![A-Za-z0-9_])"

_ENCLAVE_RE = re.compile(rf"{_WB}enclaves?{_WE}", re.IGNORECASE)
_ENCLAVE_CONTEXT_CHARS = 80
# Computing context shared by 'enclave' and 'SGX'; each adds the other.
_CONTEXT_TERMS = (
    r"secure|Nitro|(?-i:TEEs?|TDX|SEV|CCA|Arm)|TrustZone|trusted|confidential|"
    r"attest\w*|encrypt\w*|cryptograph\w*|crypto|processors?|CPUs?|GPUs?|chips?|"
    r"silicon|firmware|hardware|software|memory|iPhones?|Apple|Intel|AMD|"
    r"Azure|AWS|cloud|comput\w*|technolog\w*|keys|isolat\w*|privacy|"
    r"workloads?|VMs?|virtual|kernel|Open\s?Enclave|Gramine|Occlum")
# The same in Japanese: Intel, enclave, encryption, confidential, secure,
# processor, memory, attestation, virtual(isation), cloud, vulnerability.
_CONTEXT_TERMS_JA = (
    r"インテル|エンクレーブ|暗号|機密|セキュア|プロセッサ|メモリ|アテステーション|"
    r"仮想|クラウド|脆弱性")
_ENCLAVE_CONTEXT_RE = re.compile(
    rf"{_WB}(?:{_CONTEXT_TERMS}|(?-i:SGX)){_WE}|{_CONTEXT_TERMS_JA}", re.IGNORECASE)
_SGX_RE = re.compile(rf"{_WB}SGX{_WE}")
_SGX_CONTEXT_RE = re.compile(
    rf"{_WB}(?:{_CONTEXT_TERMS}|enclaves?|Linux|drivers?|side[\s-]channel|"
    rf"vulnerab\w*|exploit\w*){_WE}|{_CONTEXT_TERMS_JA}", re.IGNORECASE)
# 'SEV' is also incident-severity jargon ("SEV1", "agent accelerated SEVs").
# Severity levels never count; bare SEV needs AMD/virtualisation context
# close by. The shared context list is too broad here: incident write-ups are
# full of "cloud", "AWS" and "software". SEV-SNP and SEV-ES always count.
_SEV_SEVERITY_RE = re.compile(rf"{_WB}SEV[\s-]?[0-4]{_WE}", re.IGNORECASE)
_SEV_RE = re.compile(rf"{_WB}SEV(?!-[A-Za-z])s?{_WE}")
_SEV_CONTEXT_RE = re.compile(
    rf"{_WB}(?:AMD|EPYC|SNP|(?-i:TEEs?|TDX|SGX|CCA)|confidential|encrypt\w*|"
    r"attest\w*|enclaves?|VMs?|guests?|hypervisors?|virtuali[sz]\w*|KVM|QEMU|"
    rf"memory|firmware|kernel|Linux|CPUs?|processors?|vulnerab\w*){_WE}|"
    r"機密|暗号|仮想|メモリ|プロセッサ|脆弱性",
    re.IGNORECASE)


# Package names in distribution advisory lists ("aws-nitro-enclaves-cli" in
# LWN's daily "Security updates for ..." tables) contain keywords without the
# page being about confidential computing. Lowercase tokens of three or more
# hyphen-joined parts are treated as package names and ignored; prose such as
# "Nitro Enclaves", "SGX-enabled" or "SEV-SNP" is unaffected.
_PACKAGE_NAME_RE = re.compile(r"(?<![\w/.-])[a-z0-9]+(?:-[a-z0-9]+){2,}(?![\w/-])")


def _drop_without_context(word_re, context_re, text):
    """Remove each *word_re* match that has no *context_re* match close by."""
    return word_re.sub(
        lambda m: m.group(0) if context_re.search(
            text, max(0, m.start() - _ENCLAVE_CONTEXT_CHARS),
            m.end() + _ENCLAVE_CONTEXT_CHARS) else "",
        text)


# English keywords that are ordinary words in another language. For feeds in
# that language they don't count on their own, only in the qualified forms
# listed under the language in feeds.yaml's `keywords:` ("enclave seguro").
# In Spanish and Portuguese "enclave" is the everyday word for a territorial
# enclave.
_ORDINARY_WORDS = {"es": {"enclave"}, "pt": {"enclave"}}


def keywords_for_language(english, extra, lang):
    """
    Keywords to match a feed in *lang* against: the English list (acronyms
    such as TEE, SGX and TDX appear untranslated everywhere) minus words that
    are ordinary in *lang*, plus *extra[lang]* from feeds.yaml.
    """
    if not lang or lang == "en":
        return english
    ordinary = _ORDINARY_WORDS.get(lang, set())
    return [k for k in english if k.lower() not in ordinary] + \
        [str(k).strip() for k in (extra or {}).get(lang) or [] if str(k).strip()]


# Languages written without spaces between words. Their keywords are matched
# ignoring spaces and the katakana middle dot, so "コンフィデンシャル・
# コンピューティング" and "コンフィデンシャル コンピューティング" both match
# a keyword written either way.
_SPACELESS_LANGS = {"ja", "zh"}
_SQUEEZE_RE = re.compile(r"[\s・]+")


def keyword_match(text, keywords, lang="en"):
    # Exclude non-Confidential Computing uses of 'enclave' or other terms
    exclude_patterns = [
        rf"{_WB}buick\s+enclave(s)?{_WE}",
        # 'SGX' is also the Singapore Exchange ticker/venue, not Intel SGX
        rf"{_WB}(?:on|listed\s+on)\s+(?:the\s+)?SGX{_WE}",
        rf"{_WB}SGX\s*[-:]\s*(?:listed|quoted|mainboard|catalist){_WE}",
        rf"{_WB}SGX\s+(?:mainboard|catalist|securities|listing|listed){_WE}",
        rf"{_WB}Singapore\s+Exchange\s*\(?\s*SGX\s*\)?",
        rf"{_WB}SGX\s*\(?\s*Singapore\s+Exchange\s*\)?",
        r"シンガポール取引所\s*[（(]?\s*SGX\s*[)）]?",
    ]
    # Full-width letters (ＳＧＸ) and half-width katakana become ordinary ones.
    text = unicodedata.normalize("NFKC", text)
    text = _PACKAGE_NAME_RE.sub(" ", text)
    cleaned_text = text
    for pattern in exclude_patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

    # If the text is clearly about the Singapore Exchange, drop bare 'SGX' too
    if re.search(r"singapore\s+exchange|シンガポール取引所", text, flags=re.IGNORECASE):
        cleaned_text = _SGX_RE.sub("", cleaned_text)

    # In general news 'enclave' is far more often a territory (Gaza, Ceuta,
    # Kaliningrad) than a TEE. Keep an occurrence only when computing context
    # sits close by: "secure enclave", "SGX enclave", "Nitro Enclaves",
    # "enclave memory".
    # The context terms are English. Other languages don't match bare
    # 'enclave' at all (see _ORDINARY_WORDS), and their qualified forms
    # ("enclave seguro") must not be stripped.
    if lang == "en":
        cleaned_text = _drop_without_context(_ENCLAVE_RE, _ENCLAVE_CONTEXT_RE, cleaned_text)

    # Bare 'SGX' in Asian business news is usually the Singapore Exchange
    # ("SGX hunts for new CEO", "SGX posted record revenue"), in phrasings
    # the patterns above can't anticipate. Intel SGX almost always has
    # computing context close by: "Intel SGX", "SGX enclave", "SGX driver".
    cleaned_text = _drop_without_context(_SGX_RE, _SGX_CONTEXT_RE, cleaned_text)
    cleaned_text = _SEV_SEVERITY_RE.sub("", cleaned_text)
    cleaned_text = _drop_without_context(_SEV_RE, _SEV_CONTEXT_RE, cleaned_text)

    squeezed = _SQUEEZE_RE.sub("", cleaned_text) if lang in _SPACELESS_LANGS else None
    for kw in keywords:
        kw = unicodedata.normalize("NFKC", kw.strip())
        if not kw:
            continue
        if squeezed is not None and not kw.isascii():
            if _SQUEEZE_RE.sub("", kw).lower() in squeezed.lower():
                return True
            continue
        # Plurals count too: "TEEs", "enclaves", "confidential containers".
        if re.fullmatch(r"[A-Z0-9-]+", kw):
            if re.search(rf"{_WB}{re.escape(kw)}s?{_WE}", cleaned_text):
                return True
        else:
            if re.search(rf"{_WB}{re.escape(kw)}s?{_WE}", cleaned_text, flags=re.IGNORECASE):
                return True
    return False


WEBFEED_DEFAULT_DAYS = 7

# Publication time for webfeed editions. The window is half-open —
# [start_cutoff, end_cutoff) — so consecutive weekly runs share a boundary
# instant without sharing any article. 00:01 UTC means an edition covers
# whole days and the boundary sits in the quietest part of the news cycle,
# rather than at midnight where a batch of feed timestamps tends to cluster.
WEBFEED_PUBLICATION_TIME = "00:01"


def _outside_window(pub, start_dt, end_dt, webfeed_end_cutoff):
    """
    True if `pub` falls outside the reporting window.

    Webfeed mode uses a half-open window [start, end) so that consecutive
    editions cannot both contain an article published on the boundary.
    Default mode keeps the original inclusive behaviour.
    """
    if webfeed_end_cutoff is not None:
        return pub < start_dt or pub >= webfeed_end_cutoff
    return pub < start_dt or pub > end_dt


def webfeed_cutoff(date_str, clock=WEBFEED_PUBLICATION_TIME):
    """Return the UTC instant at which a webfeed edition boundary falls."""
    hh, mm = (int(x) for x in clock.split(":"))
    return (datetime.strptime(date_str, "%Y-%m-%d")
            .replace(hour=hh, minute=mm, tzinfo=timezone.utc))


def load_webfeed_state(path):
    """
    Return (state_dict, problem). Exactly one is non-None.

    `problem` describes why an existing file was unusable, so the caller can
    distinguish "never run before" from "state file is damaged" — the latter
    otherwise looks like a first run and silently loses the resume point.
    """
    if not os.path.exists(path):
        return None, None
    try:
        with open(path) as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"exists but is not valid JSON ({e})"
    except OSError as e:
        return None, f"exists but could not be read ({e})"
    if not isinstance(state, dict):
        return None, "exists but does not contain a JSON object"
    if not state.get("last_run_end"):
        return None, "exists but has no 'last_run_end' field"
    try:
        datetime.strptime(state["last_run_end"], "%Y-%m-%d")
    except ValueError:
        return None, (f"has an unparseable last_run_end "
                      f"{state['last_run_end']!r}; expected YYYY-MM-DD")
    return state, None


def save_webfeed_state(path, start, end, output, matched, clock, cutoff, filters=()):
    """
    Record this run so the next webfeed run knows where to resume.

    `cutoff` is the exact instant this edition's coverage stopped — the moment
    of generation under the default `--webfeed-end-at now`, or the publication
    boundary otherwise. It is stored verbatim rather than recomputed from
    `end`, because a mid-day cutoff cannot be recovered from a date alone.
    """
    state = {
        "last_run_end": end,
        "last_run_start": start,
        # The exact instant this edition's coverage stopped. The next run uses
        # it as an exclusive lower bound, so no article can appear twice.
        "cutoff": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "publication_time": clock,
        "last_run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_output": os.path.abspath(output),
        "last_matched": matched,
        # Recorded for traceability only; resume logic ignores it. Filtered
        # articles are not carried forward to later editions.
        "last_filters": list(filters),
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def resolve_webfeed_window(args, state_path):
    """
    Work out the window for a webfeed run.

    Returns (start_date, end_date, start_exclusive) where start_exclusive is
    the precise instant the previous edition stopped, or None to derive it from
    start_date and the publication time. Carrying the instant forward means a
    change of publication time cannot open a gap or an overlap at the seam.

    Normal case: resume from the end of the previous run, so nothing is missed
    if a week is skipped. First ever run: default to the last 7 days, but offer
    a consolidated back-catalogue report instead.
    """
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # An explicit window on the command line wins: webfeed scoping is a
    # convenience, not a straitjacket, and this is also the documented escape
    # hatch when the state file is damaged.
    explicit = [a for a in ("--start", "--end")
                if any(arg == a or arg.startswith(a + "=") for arg in sys.argv[1:])]
    if explicit:
        print(f"[webfeed] Using the window given on the command line "
              f"({' and '.join(explicit)}): {args.start} to {args.end}. "
              f"State file not consulted and will not be updated.",
              file=sys.stderr)
        args.webfeed_adhoc = True
        return args.start, args.end, None

    state, problem = load_webfeed_state(state_path)

    if problem:
        # Don't silently treat a damaged state file as a first run: that would
        # overwrite it and quietly narrow the window to 7 days.
        print(f"[webfeed] WARNING: state file {state_path} {problem}.",
              file=sys.stderr)
        print("[webfeed] Cannot tell when the last run ended. Refusing to guess; "
              "the resume point would be lost. Fix or delete the file, or pass "
              "--start/--end explicitly.", file=sys.stderr)
        sys.exit(1)

    if state:
        start = state["last_run_end"]
        gap = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        # Prefer the recorded cutoff instant over recomputing it: state written
        # by an earlier version, or under a different publication time, still
        # resumes exactly where it stopped.
        start_exclusive = None
        recorded = state.get("cutoff")
        if recorded:
            try:
                start_exclusive = datetime.strptime(
                    recorded, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"[webfeed] WARNING: ignoring unparseable cutoff "
                      f"{recorded!r} in state file; deriving from "
                      f"{start} {args.webfeed_time} UTC.", file=sys.stderr)
        if start_exclusive is None:
            start_exclusive = webfeed_cutoff(start, args.webfeed_time)
            print(f"[webfeed] State file predates cutoff tracking; assuming "
                  f"the last edition stopped at {start} "
                  f"{args.webfeed_time} UTC.", file=sys.stderr)
        print(f"[webfeed] Last edition stopped at "
              f"{start_exclusive:%Y-%m-%d %H:%M:%S} UTC ({gap}d ago); "
              f"resuming from that instant (inclusive; it was excluded "
              f"from the last edition).", file=sys.stderr)
        return start, end, start_exclusive

    default_start = (datetime.now(timezone.utc) - timedelta(days=WEBFEED_DEFAULT_DAYS)).strftime("%Y-%m-%d")
    consolidate = args.webfeed_consolidate

    if consolidate is None:
        print(f"[webfeed] No previous run found ({state_path} does not exist).", file=sys.stderr)
        if sys.stdin.isatty():
            answer = input(
                f"Build a consolidated report covering the last "
                f"{args.webfeed_consolidate_days} days instead of just "
                f"{WEBFEED_DEFAULT_DAYS}? [y/N] "
            ).strip().lower()
            consolidate = answer in ("y", "yes")
        else:
            print("[webfeed] Non-interactive; defaulting to the 7-day window. "
                  "Use --webfeed-consolidate to build a back catalogue.", file=sys.stderr)
            consolidate = False

    if consolidate:
        start = (datetime.now(timezone.utc)
                 - timedelta(days=args.webfeed_consolidate_days)).strftime("%Y-%m-%d")
        print(f"[webfeed] Consolidated first run: {start} to {end} "
              f"({args.webfeed_time} UTC boundaries).", file=sys.stderr)
        return start, end, None

    print(f"[webfeed] First run: {default_start} to {end} "
          f"({args.webfeed_time} UTC boundaries).", file=sys.stderr)
    return default_start, end, None


def main():
    parser = argparse.ArgumentParser(description="Crawl RSS feeds for Confidential Computing news (clustering issues fixed)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # Defaults resolve beside this script so cron (which runs from $HOME) finds them.
    here = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--feeds", default=os.path.join(here, "feeds.yaml"), help="Path to feeds.yaml")
    parser.add_argument("--start", default=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS,
                        help="Comma-separated list of keywords (case-insensitive)")
    parser.add_argument("--output", default=None,
                        help="Output path. Defaults to report-YYYY-MM-DD.md, or "
                             "webfeed-YYYY-MM-DD-NN.md in --webfeed mode (NN = 00, 01, ... "
                             "per edition that UTC day) so editions are never confused "
                             "with ordinary reports or with each other")
    parser.add_argument("--members-cache", default=os.path.join(here, "members.json"))
    parser.add_argument("--translations-cache", default=os.path.join(here, "translations.json"),
                        help="Cache of English translations of non-English titles")
    parser.add_argument("--no-translate", action="store_true",
                        help="Show non-English titles untranslated (no claude CLI calls)")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-fetch CCC members from LFX even if the cache is fresh")
    parser.add_argument("--no-fetch-articles", action="store_true",
                        help="Skip HTTP fetching of full article text (faster, less thorough)")
    parser.add_argument("--gnews-query", default="Confidential Computing",
                        help="Google News search query. Set to empty string to disable.")
    parser.add_argument("--no-gnews", action="store_true",
                        help="Skip Google News search")
    parser.add_argument("--no-cluster", action="store_true",
                        help="Skip story clustering; render articles as flat lists (original behaviour)")
    parser.add_argument("--enable-ai-cluster", action="store_true",
                        help="Enable AI clustering (disabled by default due to over-clustering issues)")
    parser.add_argument("--enable-ai-classify", action="store_true",
                        help="Enable AI-based article classification (uses Claude CLI)")
    parser.add_argument("--no-styling", action="store_true",
                        help="Do not apply color styling and emojis to classification tags in output")
    parser.add_argument("--no-dedup", action="store_true",
                        help="Skip article deduplication (may result in duplicate articles in output)")
    parser.add_argument("--webfeed", action="store_true",
                        help="Webfeed mode: weekly scope since last run, no category headings "
                             "(machine-readable HTML comment tags instead), no icons, "
                             "no subject-company summary")
    parser.add_argument("--webfeed-state", default=None,
                        help="Path to the webfeed last-run state file "
                             "(default: .webfeed-state.json beside the output file)")
    parser.add_argument("--webfeed-consolidate", dest="webfeed_consolidate",
                        action="store_true", default=None,
                        help="On a first webfeed run, build a consolidated back-catalogue "
                             "report without prompting")
    parser.add_argument("--no-webfeed-consolidate", dest="webfeed_consolidate",
                        action="store_false",
                        help="On a first webfeed run, use the normal 7-day window without prompting")
    parser.add_argument("--webfeed-time", default=WEBFEED_PUBLICATION_TIME, metavar="HH:MM",
                        help=f"UTC publication time marking edition boundaries "
                             f"(default: {WEBFEED_PUBLICATION_TIME}). The window is "
                             f"half-open, so consecutive editions never share an article")
    parser.add_argument("--webfeed-min-window", type=int, default=3600, metavar="SECONDS",
                        help="Refuse to publish an edition covering less than this many "
                             "seconds (default: 3600). Guards against an accidental "
                             "re-run overwriting a good edition with a near-empty one. "
                             "Set to 0 to disable")
    parser.add_argument("--webfeed-end-at", choices=("now", "publication-time"),
                        default="now",
                        help="Where the current edition stops: 'now' (default) runs to the "
                             "moment of generation, so a midday run includes that morning's "
                             "news; 'publication-time' stops at the --webfeed-time boundary, "
                             "making editions whole-day. Either way the next edition resumes "
                             "from this edition's exact end instant, so articles are never "
                             "duplicated")
    parser.add_argument("--webfeed-exclude-uk", action="store_true",
                        help="Webfeed mode only: drop articles published by UK outlets "
                             "(any .uk domain, plus The Register, BBC, The Guardian, "
                             "Computer Weekly and others; extend with 'uk_outlets:' in "
                             "feeds.yaml). Native UK feeds are skipped entirely")
    parser.add_argument("--exclude-region", action="append", default=[], metavar="REGION",
                        help="Drop articles from outlets in REGION (e.g. uk, sg, in). "
                             "Repeatable. Regions come from 'region:' on each feed, "
                             "'outlet_regions:' in feeds.yaml, and country-code TLDs")
    parser.add_argument("--only-region", action="append", default=[], metavar="REGION",
                        help="Keep only articles from outlets in REGION. Repeatable. "
                             "Articles whose region is unknown are dropped")
    parser.add_argument("--webfeed-consolidate-days", type=int, default=90,
                        help="Look-back window in days for a consolidated first webfeed run (default: 90)")
    parser.add_argument("--entry-store", default=os.path.join(here, "feed-store"), metavar="DIR",
                        help="Directory of saved feed entries, merged into every crawl so feeds "
                             "that only list a day of items still cover the whole window "
                             "(default: feed-store beside this script)")
    parser.add_argument("--entry-store-days", type=int, default=ENTRY_STORE_KEEP_DAYS,
                        help=f"Days of saved entries to keep (default: {ENTRY_STORE_KEEP_DAYS})")
    parser.add_argument("--entry-store-disk-limit", type=int, default=ENTRY_STORE_DISK_LIMIT,
                        metavar="PERCENT",
                        help="Stop saving entries, and make --store-only skip fetching, when the "
                             "store's filesystem is more than PERCENT full; an error is logged "
                             f"(default: {ENTRY_STORE_DISK_LIMIT})")
    parser.add_argument("--no-entry-store", action="store_true",
                        help="Neither read nor save stored feed entries")
    parser.add_argument("--store-only", action="store_true",
                        help="Fetch every feed and save new entries to the entry store, then "
                             "exit. Run this from cron several times a day")
    args = parser.parse_args()

    if args.store_only:
        if args.no_entry_store:
            parser.error("--store-only and --no-entry-store contradict each other")
        sys.exit(store_only(args, datetime.now(timezone.utc).replace(microsecond=0)))

    if args.webfeed_exclude_uk and not args.webfeed:
        parser.error("--webfeed-exclude-uk requires --webfeed")

    webfeed_state_path = None
    webfeed_start_exclusive = None
    args.webfeed_adhoc = False

    if args.output is None:
        # Webfeed editions get their own filename stem. They differ from
        # ordinary reports in content (no category headings, no subject-company
        # summary, invisible tags), so sharing a name would make them easy to
        # mistake for one another — and an ordinary run would silently
        # overwrite the day's published edition.
        if args.webfeed:
            # UTC, matching the edition boundaries, so the filename agrees with
            # the Period header rather than drifting near local midnight.
            # Numbered per day so a second edition never overwrites the first.
            # Chosen before the early exits below, but those write nothing,
            # so they do not use up a number.
            # Beside the script, like the state file, so cron runs from
            # $HOME continue the same edition series.
            args.output = next_webfeed_output(
                here, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        else:
            # Local date, unchanged from previous versions.
            args.output = f"report-{datetime.now().strftime('%Y-%m-%d')}.md"

    if args.webfeed:
        try:
            hh, mm = (int(x) for x in args.webfeed_time.split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError
        except ValueError:
            parser.error(f"--webfeed-time must be HH:MM in 24-hour UTC, "
                         f"got {args.webfeed_time!r}")
        # Webfeed mode implies plain text tags (no coloured spans / emoji)
        args.no_styling = True
        webfeed_state_path = args.webfeed_state or os.path.join(
            os.path.dirname(os.path.abspath(args.output)) or ".", ".webfeed-state.json"
        )
        args.start, args.end, webfeed_start_exclusive = resolve_webfeed_window(
            args, webfeed_state_path)

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.webfeed:
        # Half-open window [start_cutoff, end_cutoff): the start instant is the
        # exact point the previous edition stopped, so the boundary day is not
        # reported twice. `webfeed_start_exclusive` carries a resumed cutoff
        # that may differ from 00:01 if the publication time was changed.
        start_dt = webfeed_start_exclusive or webfeed_cutoff(args.start, args.webfeed_time)

        now = datetime.now(timezone.utc).replace(microsecond=0)
        ends_today = args.end == now.strftime("%Y-%m-%d")
        if args.webfeed_end_at == "now" and ends_today and not args.webfeed_adhoc:
            # Run right up to the moment of generation, so an edition produced
            # at midday includes that morning's news. The no-duplicate
            # guarantee is unaffected: the next edition resumes from this exact
            # instant, which is recorded in the state file.
            end_dt = now
            print(f"[webfeed] Edition runs to the moment of generation "
                  f"({end_dt:%Y-%m-%d %H:%M:%S} UTC).", file=sys.stderr)
        else:
            end_dt = webfeed_cutoff(args.end, args.webfeed_time)

        if end_dt <= start_dt:
            print(f"[webfeed] Window is empty: start cutoff {start_dt:%Y-%m-%d %H:%M:%S} UTC "
                  f"is not before end cutoff {end_dt:%Y-%m-%d %H:%M:%S} UTC. "
                  f"Nothing new since the last edition; not writing a report.",
                  file=sys.stderr)
            sys.exit(0)

        span = (end_dt - start_dt).total_seconds()
        if args.webfeed_min_window and span < args.webfeed_min_window:
            # Almost certainly an accidental re-run: publishing would overwrite
            # the previous edition's output with a near-empty one and advance
            # the resume point past news that has not been reported.
            print(f"[webfeed] Only {int(span)}s since the last edition "
                  f"(minimum {args.webfeed_min_window}s). This looks like an "
                  f"accidental re-run; refusing to publish a near-empty "
                  f"edition and advance the resume point. Use "
                  f"--webfeed-min-window 0 to override, or --start/--end for "
                  f"an ad-hoc report.", file=sys.stderr)
            sys.exit(0)
        webfeed_end_cutoff = end_dt
    else:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        webfeed_end_cutoff = None

    socket.setdefaulttimeout(60)

    with open(args.feeds) as f:
        feed_config = yaml.safe_load(f)
    feeds = feed_config.get("feeds", [])
    language_keywords = feed_config.get("keywords") or {}
    extra_regions = {str(d).lower().lstrip("."): "uk"
                     for d in (feed_config.get("uk_outlets") or [])}
    extra_regions.update({str(d).lower().lstrip("."): str(r).lower()
                          for d, r in (feed_config.get("outlet_regions") or {}).items()})
    exclude_uk = args.webfeed and args.webfeed_exclude_uk
    exclude_regions = {r.lower() for r in args.exclude_region}
    if exclude_uk:
        exclude_regions.add("uk")
    only_regions = {r.lower() for r in args.only_region}
    region_excluded = {}  # host -> count of in-window entries dropped

    # Recorded in the state file and as an HTML comment in ordinary reports.
    # Excluding only UK keeps the historical "exclude-uk" label.
    if exclude_regions == {"uk"}:
        filter_labels = ["exclude-uk"]
    else:
        filter_labels = [f"exclude-region={r}" for r in sorted(exclude_regions)]
    filter_labels += [f"only-region={r}" for r in sorted(only_regions)]

    def _region_dropped(region):
        if region in exclude_regions:
            return True
        return bool(only_regions) and region not in only_regions

    def _drop_region(host, region):
        if _region_dropped(region):
            region_excluded[host] = region_excluded.get(host, 0) + 1
            return True
        return False

    print("Fetching CCC members...", file=sys.stderr)
    try:
        cache_age = time.time() - os.path.getmtime(args.members_cache)
    except FileNotFoundError:
        cache_age = None

    needs_refresh = cache_age is None or cache_age > MEMBERS_TTL_SECONDS or args.force_refresh
    if needs_refresh:
        try:
            members = fetch_members(args.members_cache)
            print(f"  Fetched {len(members)} members from LFX → {args.members_cache}", file=sys.stderr)
        except Exception as e:
            if cache_age is None:
                print(f"[error] Could not fetch members and no cache exists: {e}", file=sys.stderr)
                sys.exit(1)
            age_days = int(cache_age // 86400)
            print(f"[warn] LFX refresh failed ({e}); using stale cache ({age_days}d old)", file=sys.stderr)
            members = load_members(args.members_cache)
    else:
        members = load_members(args.members_cache)
        print(f"  Loaded {len(members)} members from cache ({args.members_cache})", file=sys.stderr)

    categorized = {"by_member": [], "about_member": [], "dont": []}
    total_entries = 0
    total_matched = 0
    feed_health = []
    feed_yield = []  # (name, entries, in-window, matched) per fetched feed
    # A full disk stops new entries being saved, but stored ones are still read.
    store = None if args.no_entry_store else EntryStore(
        args.entry_store, args.entry_store_days,
        read_only=store_disk_full(args)).load()
    crawl_time = datetime.now(timezone.utc).replace(microsecond=0)
    needs_text = []  # entries to check against their full article text

    def _record(item, haystack, author):
        """File a matched entry under by-member, about-member or neither."""
        by = is_by_member(item["publisher"], author, members)
        if by:
            categorized["by_member"].append({**item, "member": by})
            return
        about = is_about_member(haystack, members)
        if about:
            categorized["about_member"].append({**item, "member": about})
        else:
            categorized["dont"].append(item)

    for feed_def in feeds:
        feed_name = feed_def.get("name", feed_def["url"])
        url = feed_def["url"]
        feed_region = (str(feed_def["region"]).lower() if feed_def.get("region") else None)
        feed_lang = str(feed_def.get("lang") or "en").lower()
        feed_keywords = keywords_for_language(keywords, language_keywords, feed_lang)
        # A native feed can only yield its own outlet's articles: skip the
        # fetch outright when its region is filtered out. Aggregator feeds
        # (Google News) carry many outlets and are filtered per entry below.
        feed_host = _host(url)
        if feed_host not in _AGGREGATOR_HOSTS:
            native_region = region_for_host(feed_host, feed_region, extra_regions)
            if _region_dropped(native_region):
                print(f"Skipping feed: {feed_name} (region {native_region or 'unknown'} "
                      f"filtered out)", file=sys.stderr)
                region_excluded.setdefault(feed_host, 0)
                continue
        print(f"Crawling: {feed_name}", file=sys.stderr)
        feed_in_window = 0
        feed_matched = 0

        stored = store.entries_for(url) if store else []
        try:
            parsed = fetch_feed(url)
            if parsed.bozo and not parsed.entries:
                raise ValueError(parsed.bozo_exception)
            if not parsed.entries:
                print(f"  [warn] {feed_name}: feed parsed but returned 0 entries", file=sys.stderr)
                feed_health.append((feed_name, "0 entries"))
            if feed_def.get("timezone"):
                localise_naive_dates(parsed.entries, feed_def["timezone"])
            live = parsed.entries
        except Exception as e:
            # Entries stored before the failure are still worth reporting.
            print(f"  [skip] {feed_name}: {e}" + (
                f"; using {len(stored)} stored entries" if stored else ""), file=sys.stderr)
            feed_health.append((feed_name, f"failed: {str(e)[:60]}"))
            if not stored:
                continue
            live = []
        if store:
            store.add(url, live, crawl_time)
        entries = merge_stored_entries(live, stored, start_dt)

        for entry in entries:
            total_entries += 1

            pub = entry_datetime(entry)
            if pub and _outside_window(pub, start_dt, end_dt, webfeed_end_cutoff):
                continue

            title = entry.get("title", "")
            link = entry.get("link", "")
            source_href = (entry.get("source") or {}).get("href", "")
            host = publisher_host(link, source_href, url)
            # An aggregator's own region says nothing about the outlet behind
            # an entry, so only native feeds lend theirs as a fallback.
            region = region_for_host(
                host, None if feed_host in _AGGREGATOR_HOSTS else feed_region,
                extra_regions)
            if _drop_region(host, region):
                continue
            feed_in_window += 1
            summary = entry.get("summary", "")
            tags = " ".join(t.get("term", "") for t in entry.get("tags", []))
            author = entry.get("author", "")
            pub_str = pub.strftime("%a, %d %b %Y %H:%M:%S %Z") if pub else ""

            haystack = f"{title} {summary} {tags}"
            item = {"title": title, "url": link, "published": pub_str,
                    "publisher": feed_name, "region": region, "host": host,
                    "lang": feed_lang, "_seq": total_entries}

            if not keyword_match(haystack, feed_keywords, feed_lang):
                if not args.no_fetch_articles and link:
                    # Checked against the article text after the feed loop,
                    # when all such fetches run in parallel.
                    needs_text.append((item, haystack, author, feed_keywords,
                                       len(feed_yield)))
                continue

            total_matched += 1
            feed_matched += 1
            _record(item, haystack, author)

        feed_yield.append([feed_name, len(entries), feed_in_window, feed_matched])

    # Entries whose title, summary and tags don't match are checked against the
    # full article text. With a week of stored entries that is ~10,000 fetches,
    # which took hours one at a time (the 2026-11-05 run was still going when
    # a reboot killed it), so they run in parallel.
    if needs_text:
        print(f"Checking full text of {len(needs_text)} articles...", file=sys.stderr)
        started = time.time()
        # Most of the text was fetched by the hourly store runs.
        text_store = None if args.no_entry_store else TextStore(
            text_store_dir(args.entry_store), read_only=store.read_only).load()
        urls = [item["url"] for item, *_ in needs_text]
        texts = {}
        if text_store:
            texts = {u: t for u in urls if (t := text_store.get(u)) is not None}
        missing = [u for u in urls if u not in texts]
        print(f"  {len(texts)} from the text store, fetching {len(missing)}", file=sys.stderr)
        fetched = fetch_article_texts(missing, **polite_fetch_options(feed_config))
        if text_store:
            text_store.save(fetched, crawl_time)
        texts.update(fetched)
        for item, haystack, author, feed_keywords, yield_index in needs_text:
            full_text = texts.get(item["url"], "")
            if not keyword_match(full_text, feed_keywords, item["lang"]):
                continue
            total_matched += 1
            feed_yield[yield_index][3] += 1
            _record(item, f"{haystack} {full_text}", author)
        print(f"  done in {time.time() - started:.0f}s", file=sys.stderr)
    # Back into feed order, as when each entry was checked in turn: duplicate
    # removal keeps the first copy it sees.
    for bucket in categorized.values():
        bucket.sort(key=lambda a: a["_seq"])
        for article in bucket:
            del article["_seq"]

    # Google News search
    if not args.no_gnews and args.gnews_query:
        try:
            from gnews import GNews
            import email.utils
        except ImportError:
            print("[warn] gnews not installed; skipping (pip install gnews)", file=sys.stderr)
            GNews = None

        if GNews is not None:
            print(f"\nSearching Google News: {args.gnews_query!r}", file=sys.stderr)
            # Google News truncates results when `before:` is today's date
            # (26 instead of 99 for the same query), so ask for one extra day.
            # Entries outside the window are dropped below either way.
            gn_end = end_dt + timedelta(days=1)
            try:
                gn = GNews(language='en', country='US',
                           start_date=(start_dt.year, start_dt.month, start_dt.day),
                           end_date=(gn_end.year, gn_end.month, gn_end.day))
                gnews_articles = gn.get_news(args.gnews_query)
                print(f"  {len(gnews_articles)} articles returned", file=sys.stderr)
            except Exception as e:
                print(f"  [skip] gnews: {e}", file=sys.stderr)
                gnews_articles = []

            seen_urls = {normalize_url(a["url"]) for bucket in categorized.values() for a in bucket}
            gnews_matched = 0

            for article in gnews_articles:
                total_entries += 1
                title = article.get("title", "")
                url = article.get("url", "")
                description = article.get("description", "")
                publisher = article.get("publisher", {}).get("title", "Google News")
                pub_str = article.get("published date", "")

                if normalize_url(url) in seen_urls:
                    continue
                host = publisher_host(url, (article.get("publisher") or {}).get("href", ""))
                region = region_for_host(host, None, extra_regions)
                if _drop_region(host, region):
                    continue

                pub = None
                try:
                    pub = email.utils.parsedate_to_datetime(pub_str).astimezone(timezone.utc)
                except Exception:
                    pass
                if pub and _outside_window(pub, start_dt, end_dt, webfeed_end_cutoff):
                    continue
                pub_fmt = pub.strftime("%a, %d %b %Y %H:%M:%S %Z") if pub else pub_str

                # Google News results were previously trusted without any
                # keyword check, so anything its query surfaced was reported —
                # including travel and book-fair stories from publishers that
                # merely also cover CC. Verify like any other source.
                haystack = f"{title} {description}"
                if not keyword_match(haystack, keywords):
                    if args.no_fetch_articles or not url:
                        continue
                    full_text = fetch_article_text(url)
                    if not keyword_match(full_text, keywords):
                        continue
                    haystack = f"{haystack} {full_text}"

                total_matched += 1
                gnews_matched += 1
                seen_urls.add(normalize_url(url))

                by = is_by_member(publisher, "", members)
                if by:
                    categorized["by_member"].append({
                        "title": title, "url": url, "published": pub_fmt,
                        "publisher": publisher, "region": region, "host": host, "member": by,
                    })
                    continue

                about = is_about_member(haystack, members)
                if about:
                    categorized["about_member"].append({
                        "title": title, "url": url, "published": pub_fmt,
                        "publisher": publisher, "region": region, "host": host, "member": about,
                    })
                else:
                    categorized["dont"].append({
                        "title": title, "url": url, "published": pub_fmt,
                        "publisher": publisher, "region": region, "host": host,
                    })

            print(f"  Matched {gnews_matched} from Google News.", file=sys.stderr)

    print(f"\nScanned {total_entries} entries total.", file=sys.stderr)
    if exclude_regions or only_regions:
        # Counted before keyword filtering, so this is how much material from
        # filtered regions was in the window, not how many CC articles were lost.
        dropped = sum(region_excluded.values())
        detail = ", ".join(f"{h or '(unknown host)'} {n}" if n else f"{h} (feed skipped)"
                           for h, n in sorted(region_excluded.items(), key=lambda kv: (-kv[1], kv[0])))
        print(f"Excluded {dropped} in-window entries by region before keyword "
              f"filtering ({', '.join(filter_labels)}){': ' + detail if detail else ''}.",
              file=sys.stderr)
    print(f"Matched {total_matched} Confidential Computing articles.", file=sys.stderr)

    # English titles first, so dedup and clustering compare like with like
    if not args.no_translate:
        n = translate_titles([a for bucket in categorized.values() for a in bucket],
                             args.translations_cache)
        if n:
            print(f"Translated {n} titles into English.", file=sys.stderr)

    # Deduplicate articles before clustering
    if not args.no_dedup:
        print("Deduplicating articles...", file=sys.stderr)
        categorized, duplicates_removed = deduplicate_articles(categorized)
        if duplicates_removed > 0:
            print(f"  Removed {duplicates_removed} copies of articles already listed.", file=sys.stderr)
            # Update total matched count
            final_matched = sum(len(articles) for articles in categorized.values())
            print(f"  {final_matched} unique articles remaining.", file=sys.stderr)
        else:
            print("  No duplicates found.", file=sys.stderr)
    else:
        print("Skipping deduplication (--no-dedup specified).", file=sys.stderr)

    # Classify articles into story types
    all_articles = categorized["by_member"] + categorized["about_member"] + categorized["dont"]
    # Assign unique temporary IDs if they are not already set
    for i, a in enumerate(all_articles):
        a["_id"] = i

    if args.enable_ai_classify:
        print("Classifying articles with AI (Claude)...", file=sys.stderr)
        classify_stories_ai(all_articles)
    else:
        print("Classifying articles with Heuristics...", file=sys.stderr)
        classify_stories_heuristic(all_articles)

    cluster_labels = {}
    if not args.no_cluster:
        print("Clustering articles by story...", file=sys.stderr)
        use_ai = args.enable_ai_cluster
        cluster_labels = group_articles_by_story(categorized, members, use_ai=use_ai)

    print(f"Writing report to {args.output}...", file=sys.stderr)

    subject_index = build_subject_index(categorized["dont"], members)
    sorted_subjects = sorted(subject_index.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))

    with open(args.output, "w") as f:
        if args.webfeed:
            f.write("---\n")
            f.write(f"title: Confidential Computing News Report - {args.end}\n")
            f.write("post_status: publish\n")
            f.write(f"post_date: {end_dt:%Y-%m-%d %H:%M:%S}\n")
            f.write("taxonomy:\n")
            f.write("  category:\n")
            f.write("    - newsfeed\n")
            f.write("---\n\n")
            f.write(f"**Period:** {start_dt:%Y-%m-%d %H:%M:%S} UTC to "
                    f"{end_dt:%Y-%m-%d %H:%M:%S} UTC\n")
        else:
            f.write("# Confidential Computing News Report\n\n")
            f.write(f"**Period:** {args.start} to {args.end}\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"**Keywords:** {args.keywords}\n")
            f.write(f"**Total matched:** {total_matched}\n\n")
        if not args.webfeed and filter_labels:
            # Invisible, like the other webfeed tags, but lets a consumer tell
            # a filtered report from an unfiltered one.
            f.write(f"<!-- cc-news filter={','.join(filter_labels)} -->\n\n")

        no_cluster = args.no_cluster
        webfeed = args.webfeed

        def _tag(category, a):
            """Invisible (HTML comment) category tag for webfeed mode."""
            if not webfeed:
                return ""
            # Returning empty to remove the HTML comment tag from each article in webfeed mode
            return ""

        if not webfeed:
            f.write("## Articles BY Members\n\n")
        _write_section(
            f, categorized["by_member"], cluster_labels,
            lambda a: f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}{', Member: ' + a['member'] if not webfeed else ''}) - {a['published']}{_tag('by-member', a)}",
            no_cluster=no_cluster,
            webfeed=webfeed,
        )

        if not webfeed:
            f.write("## Articles ABOUT Members (or mentioning them)\n\n")
        _write_section(
            f, categorized["about_member"], cluster_labels,
            lambda a: f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}{', Mentions: ' + a['member'] if not webfeed else ''}) - {a['published']}{_tag('about-member', a)}",
            no_cluster=no_cluster,
            webfeed=webfeed,
        )

        if not webfeed:
            f.write("## Other Articles (Don't mention members)\n\n")

        def _other_detail(a):
            subject = infer_subject(a["title"])
            mention = f", Subject: {subject}" if subject and not webfeed else ""
            return f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}{mention}) - {a['published']}{_tag('other', a)}"

        _write_section(
            f, categorized["dont"], cluster_labels,
            _other_detail,
            no_cluster=no_cluster,
            webfeed=webfeed,
        )

        if not webfeed:
            f.write("\n## Subject Companies (Non-Member Articles)\n\n")
            if not sorted_subjects:
                f.write("None found.\n\n")
            for subject, articles in sorted_subjects:
                count = len(articles)
                f.write(f"- {subject} — {count} {'article' if count == 1 else 'articles'}\n")

    json_path = derive_subjects_json_path(args.output)
    def _serialise_article(a):
        """Return article dict suitable for JSON output (strip internal _id key)."""
        return {k: v for k, v in a.items() if k != "_id"}

    subjects_payload = {
        "period": {"start": args.start, "end": args.end},
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subjects": [
            {
                "name": subject,
                "count": len(articles),
                "articles": [_serialise_article(a) for a in articles],
            }
            for subject, articles in sorted_subjects
        ],
    }
    tmp = json_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(subjects_payload, f, indent=2)
    os.replace(tmp, json_path)
    print(f"Wrote subject index to {json_path}", file=sys.stderr)

    if args.webfeed and webfeed_state_path and not args.webfeed_adhoc:
        save_webfeed_state(webfeed_state_path, args.start, args.end,
                           args.output, total_matched, args.webfeed_time,
                           webfeed_end_cutoff,
                           filters=filter_labels)
        print(f"Recorded webfeed run state in {webfeed_state_path}", file=sys.stderr)
    elif args.webfeed and args.webfeed_adhoc:
        # A one-off backfill must not rewind the weekly resume point.
        print("Ad-hoc window: webfeed run state left unchanged.", file=sys.stderr)

    if feed_yield:
        print("\nFeed yield (entries live+stored / in window / matched):", file=sys.stderr)
        width = max(len(n) for n, *_ in feed_yield)
        for name, entries, in_window, matched in feed_yield:
            print(f"  {name:<{width}}  {entries:4d} {in_window:4d} {matched:4d}", file=sys.stderr)

    if feed_health:
        print("\nFeed health warnings:", file=sys.stderr)
        for name, issue in feed_health:
            print(f"  - {name}: {issue}", file=sys.stderr)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
