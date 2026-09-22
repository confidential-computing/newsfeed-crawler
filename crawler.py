import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup


DEFAULT_KEYWORDS = "confidential computing,confidential compute,enclave,TEE,SGX,TDX,SEV,SEV-SNP,Arm CCA,remote attestation,confidential VM,confidential container"
CCC_PROJECT_UID = "54ec092e-cadd-49af-9edf-9a5c888cc283"
MEMBERS_TTL_SECONDS = 7 * 24 * 60 * 60  # one week

_FETCH_PROMPT = (
    'Call mcp__claude_ai_LFX__query_lfx_lens with project_slug "ccc" and '
    'input "List all current active member organization names". '
    "Extract every organization name from the result table. "
    "Respond with ONLY a JSON object on a single line — no prose, "
    'no markdown — in exactly this form: {"members": ["Name 1", "Name 2", ...]}'
)


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


def deduplicate_articles(categorized, similarity_threshold=0.7):
    """
    Remove duplicate articles from categorized buckets using multiple strategies:
    1. Exact URL matches (after normalization)
    2. Title similarity using Jaccard coefficient
    3. Content hash when available
    
    Returns updated categorized dict and duplicate count.
    """
    seen_urls = set()
    seen_hashes = set()
    seen_titles = []  # List of (tokens, original_article) for similarity comparison
    duplicates_removed = 0
    
    def is_duplicate(article, full_text=""):
        nonlocal duplicates_removed
        
        # Strategy 1: URL normalization
        normalized_url = normalize_url(article.get("url", ""))
        if normalized_url and normalized_url in seen_urls:
            duplicates_removed += 1
            return True
        
        # Strategy 2: Content hash (when full text is available)
        if full_text:
            content_hash = compute_content_hash(article.get("title", ""), full_text)
            if content_hash in seen_hashes:
                duplicates_removed += 1
                return True
            seen_hashes.add(content_hash)
        
        # Strategy 3: Title similarity using existing _title_tokens function
        title = article.get("title", "")
        if title:
            current_tokens = _title_tokens(title)
            
            for seen_tokens, seen_article in seen_titles:
                if not current_tokens or not seen_tokens:
                    continue
                    
                # Calculate Jaccard similarity
                intersection = len(current_tokens & seen_tokens)
                union = len(current_tokens | seen_tokens)
                
                if union > 0:
                    jaccard = intersection / union
                    if jaccard >= similarity_threshold:
                        # Additional check: if URLs are different but very similar titles,
                        # require higher similarity to avoid false positives
                        url1 = normalize_url(article.get("url", ""))
                        url2 = normalize_url(seen_article.get("url", ""))
                        
                        if url1 != url2:
                            # Extract domains for comparison
                            try:
                                domain1 = urllib.parse.urlparse(url1).netloc.lower()
                                domain2 = urllib.parse.urlparse(url2).netloc.lower()
                                
                                # If completely different domains and identical titles,
                                # be very conservative to avoid false positives
                                if domain1 != domain2 and jaccard >= 1.0:
                                    # Identical titles from different domains are likely different stories
                                    # unless they're news aggregators or syndication
                                    aggregator_domains = {'news.google.com', 'news.yahoo.com', 'msn.com', 'reddit.com'}
                                    if not (domain1 in aggregator_domains or domain2 in aggregator_domains):
                                        continue  # Skip - likely different stories with same generic title
                                
                                # For different domains, require very high similarity
                                if jaccard < 0.85:
                                    continue  # Different URLs need very high title similarity
                            except:
                                # If URL parsing fails, fall back to conservative approach
                                if jaccard < 0.85:
                                    continue
                            
                        duplicates_removed += 1
                        return True
            
            # Add to seen titles for future comparisons
            seen_titles.append((current_tokens, article))
        
        # Not a duplicate - record URL
        if normalized_url:
            seen_urls.add(normalized_url)
        
        return False
    
    # Process each category
    for category in ["by_member", "about_member", "dont"]:
        if category not in categorized:
            continue
            
        original_articles = categorized[category]
        deduplicated = []
        
        for article in original_articles:
            # For deduplication, we don't have access to full text here
            # since that was fetched during collection. We could re-fetch
            # but that would be expensive. For now, rely on URL and title.
            if not is_duplicate(article):
                deduplicated.append(article)
        
        categorized[category] = deduplicated
    
    return categorized, duplicates_removed


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


def is_about_member(haystack, members):
    text = haystack.lower()
    
    # First check standard member names
    for m in members:
        cleaned = clean_member_name(m)
        if len(cleaned) > 2 and re.search(rf"\b{re.escape(cleaned)}\b", text):
            return m
    
    # Special case: Check for Ubuntu if Canonical is a member
    canonical_members = [m for m in members if 'canonical' in m.lower()]
    if canonical_members and re.search(r'\bubuntu\b', text):
        return canonical_members[0]  # Return the first Canonical member found
        
    return None


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
        return extract_article_text(resp.text)
    except Exception:
        return ""


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


def derive_subjects_json_path(md_output):
    directory = os.path.dirname(md_output)
    basename = os.path.basename(md_output)
    if basename.startswith("report-") and basename.endswith(".md"):
        json_name = "subjects-" + basename[len("report-"):-len(".md")] + ".json"
    elif basename.startswith("webfeed-") and basename.endswith(".md"):
        # `subjects-webfeed-DATE.json`: still matches the `subjects-*.json`
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


def _write_section(f, articles, cluster_labels, detail_fn, no_cluster=False):
    """
    Write one report section's article list.

    *detail_fn(article)* returns the parenthetical detail string, e.g.
    ``"(Publisher: X, Member: Y) - Mon, 09 Jun 2026 ..."``.

    When *no_cluster* is True (or *cluster_labels* is empty) articles are
    rendered as a flat bullet list, identical to pre-clustering behaviour.
    Multi-article clusters are rendered under a bold story label; singletons
    are rendered as plain bullets so the report stays readable.
    """
    if not articles:
        f.write("None found.\n\n")
        return

    if no_cluster or not cluster_labels:
        for a in articles:
            f.write(f"- [{a['title']}]({a['url']}) {detail_fn(a)}\n")
        f.write("\n")
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
            f.write(f"- [{a['title']}]({a['url']}) {detail_fn(a)}\n")
        else:
            label = cluster_labels.get(cid, f"Story {cid}")
            f.write(f"\n**{label}**\n")
            for a in group:
                f.write(f"  - [{a['title']}]({a['url']}) {detail_fn(a)}\n")

    f.write("\n")


def keyword_match(text, keywords):
    # Exclude non-Confidential Computing uses of 'enclave' or other terms
    exclude_patterns = [
        r"\bbuick\s+enclave(s)?\b",
        # 'SGX' is also the Singapore Exchange ticker/venue, not Intel SGX
        r"\b(?:on|listed\s+on|the)\s+SGX\b",
        r"\bSGX\s*[-:]\s*(?:listed|quoted|mainboard|catalist)\b",
        r"\bSGX\s+(?:mainboard|catalist|securities|listing|listed)\b",
        r"\bSingapore\s+Exchange\s*\(?\s*SGX\s*\)?",
        r"\bSGX\s*\(?\s*Singapore\s+Exchange\s*\)?",
    ]
    cleaned_text = text
    for pattern in exclude_patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

    # If the text is clearly about the Singapore Exchange, drop bare 'SGX' too
    if re.search(r"singapore\s+exchange", text, flags=re.IGNORECASE):
        cleaned_text = re.sub(r"\bSGX\b", "", cleaned_text)

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if re.fullmatch(r"[A-Z0-9-]+", kw):
            if re.search(rf"\b{re.escape(kw)}\b", cleaned_text):
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", cleaned_text, flags=re.IGNORECASE):
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


def save_webfeed_state(path, start, end, output, matched, clock, cutoff):
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
    parser.add_argument("--feeds", default="feeds.yaml", help="Path to feeds.yaml")
    parser.add_argument("--start", default=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--keywords", default=DEFAULT_KEYWORDS,
                        help="Comma-separated list of keywords (case-insensitive)")
    parser.add_argument("--output", default=None,
                        help="Output path. Defaults to report-YYYY-MM-DD.md, or "
                             "webfeed-YYYY-MM-DD.md in --webfeed mode so editions are "
                             "never confused with ordinary reports")
    parser.add_argument("--members-cache", default="members.json")
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
    parser.add_argument("--webfeed-consolidate-days", type=int, default=90,
                        help="Look-back window in days for a consolidated first webfeed run (default: 90)")
    args = parser.parse_args()

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
            args.output = f"webfeed-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
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
                  f"accidental re-run; refusing to overwrite "
                  f"{args.output} with a near-empty edition. Use "
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

    for feed_def in feeds:
        feed_name = feed_def.get("name", feed_def["url"])
        url = feed_def["url"]
        print(f"Crawling: {feed_name}", file=sys.stderr)

        try:
            parsed = fetch_feed(url)
            if parsed.bozo and not parsed.entries:
                raise ValueError(parsed.bozo_exception)
            if not parsed.entries:
                print(f"  [warn] {feed_name}: feed parsed but returned 0 entries", file=sys.stderr)
                feed_health.append((feed_name, "0 entries"))
        except Exception as e:
            print(f"  [skip] {feed_name}: {e}", file=sys.stderr)
            feed_health.append((feed_name, f"failed: {str(e)[:60]}"))
            continue

        for entry in parsed.entries:
            total_entries += 1

            pub = entry_datetime(entry)
            if pub and _outside_window(pub, start_dt, end_dt, webfeed_end_cutoff):
                continue

            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")
            tags = " ".join(t.get("term", "") for t in entry.get("tags", []))
            author = entry.get("author", "")
            pub_str = pub.strftime("%a, %d %b %Y %H:%M:%S %Z") if pub else ""

            haystack = f"{title} {summary} {tags}"

            if not keyword_match(haystack, keywords):
                if not args.no_fetch_articles and link:
                    full_text = fetch_article_text(link)
                    if not keyword_match(full_text, keywords):
                        continue
                    haystack = f"{haystack} {full_text}"
                else:
                    continue

            total_matched += 1

            by = is_by_member(feed_name, author, members)
            if by:
                categorized["by_member"].append({
                    "title": title, "url": link, "published": pub_str,
                    "publisher": feed_name, "member": by,
                })
                continue

            about = is_about_member(haystack, members)
            if about:
                categorized["about_member"].append({
                    "title": title, "url": link, "published": pub_str,
                    "publisher": feed_name, "member": about,
                })
            else:
                categorized["dont"].append({
                    "title": title, "url": link, "published": pub_str,
                    "publisher": feed_name,
                })

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
            try:
                gn = GNews(language='en', country='US',
                           start_date=(start_dt.year, start_dt.month, start_dt.day),
                           end_date=(end_dt.year, end_dt.month, end_dt.day))
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
                        "publisher": publisher, "member": by,
                    })
                    continue

                about = is_about_member(haystack, members)
                if about:
                    categorized["about_member"].append({
                        "title": title, "url": url, "published": pub_fmt,
                        "publisher": publisher, "member": about,
                    })
                else:
                    categorized["dont"].append({
                        "title": title, "url": url, "published": pub_fmt,
                        "publisher": publisher,
                    })

            print(f"  Matched {gnews_matched} from Google News.", file=sys.stderr)

    print(f"\nScanned {total_entries} entries total.", file=sys.stderr)
    print(f"Matched {total_matched} Confidential Computing articles.", file=sys.stderr)

    # Deduplicate articles before clustering
    if not args.no_dedup:
        print("Deduplicating articles...", file=sys.stderr)
        categorized, duplicates_removed = deduplicate_articles(categorized)
        if duplicates_removed > 0:
            print(f"  Removed {duplicates_removed} duplicate articles.", file=sys.stderr)
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
        f.write("# Confidential Computing News Report\n\n")
        if args.webfeed:
            # Show the true half-open boundaries, so it is unambiguous which
            # edition a boundary-day article belongs to.
            f.write(f"**Period:** {start_dt:%Y-%m-%d %H:%M:%S} UTC (inclusive) to "
                    f"{end_dt:%Y-%m-%d %H:%M:%S} UTC (exclusive)\n")
        else:
            f.write(f"**Period:** {args.start} to {args.end}\n")
        f.write(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"**Keywords:** {args.keywords}\n")
        f.write(f"**Total matched:** {total_matched}\n\n")

        no_cluster = args.no_cluster
        webfeed = args.webfeed

        def _tag(category, a):
            """Invisible (HTML comment) category tag for webfeed mode."""
            if not webfeed:
                return ""
            bits = [f"category={category}"]
            story_type = a.get("story_type") or "General CC News"
            bits.append(f"story-type={story_type}")
            if a.get("member"):
                bits.append(f"member={a['member']}")
            return "<!-- cc-news " + "; ".join(bits) + " -->"

        if webfeed:
            f.write("<!-- cc-news section=by-member -->\n\n")
        else:
            f.write("## Articles BY Members\n\n")
        _write_section(
            f, categorized["by_member"], cluster_labels,
            lambda a: f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}, Member: {a['member']}) - {a['published']}{_tag('by-member', a)}",
            no_cluster=no_cluster,
        )

        if webfeed:
            f.write("<!-- cc-news section=about-member -->\n\n")
        else:
            f.write("## Articles ABOUT Members (or mentioning them)\n\n")
        _write_section(
            f, categorized["about_member"], cluster_labels,
            lambda a: f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}, Mentions: {a['member']}) - {a['published']}{_tag('about-member', a)}",
            no_cluster=no_cluster,
        )

        if webfeed:
            f.write("<!-- cc-news section=other -->\n\n")
        else:
            f.write("## Other Articles (Don't mention members)\n\n")

        def _other_detail(a):
            subject = infer_subject(a["title"])
            mention = f", Subject: {subject}" if subject else ""
            return f"({format_story_type_tag(a.get('story_type'), use_styling=not args.no_styling)}) (Publisher: {a['publisher']}{mention}) - {a['published']}{_tag('other', a)}"

        _write_section(
            f, categorized["dont"], cluster_labels,
            _other_detail,
            no_cluster=no_cluster,
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
                           webfeed_end_cutoff)
        print(f"Recorded webfeed run state in {webfeed_state_path}", file=sys.stderr)
    elif args.webfeed and args.webfeed_adhoc:
        # A one-off backfill must not rewind the weekly resume point.
        print("Ad-hoc window: webfeed run state left unchanged.", file=sys.stderr)

    if feed_health:
        print("\nFeed health warnings:", file=sys.stderr)
        for name, issue in feed_health:
            print(f"  - {name}: {issue}", file=sys.stderr)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    main()
