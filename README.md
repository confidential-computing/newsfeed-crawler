# CC-news-crawler

Crawls a curated list of tech-news RSS/Atom feeds for articles about Confidential Computing, then categorises them against the current list of [Confidential Computing Consortium](https://confidentialcomputing.io/) member companies.

Unlike `AG-CC-news`, this project does not depend on Google News — it fetches feeds directly.

**Matching logic:** articles are included only if they match a Confidential Computing keyword. All-uppercase acronyms (`TEE`, `SGX`, `TDX`, `SEV`, `SEV-SNP`) are matched case-sensitively with word boundaries; multi-word phrases (`confidential computing`, `remote attestation`, `Arm CCA`) and `enclave` are matched case-insensitively. This avoids false positives like `tee` inside "committee" or `sev` inside "several". Matched articles are then sub-categorised by CCC member affiliation.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Runtime dependency:** the `claude` CLI must be on your `$PATH` and authenticated with the LFX MCP integration. The crawler shells out to `claude -p` to refresh `members.json` from LFX at most once per week, and to cluster matched articles into same-story groups. If the `claude` CLI is unavailable or the call fails, a deterministic heuristic (shared company + date proximity + title-token overlap) is used automatically as a fallback.

## Usage

```bash
# Last 30 days, default keywords, write report-YYYY-MM-DD.md
python crawler.py

# Custom date range
python crawler.py --start 2026-04-01 --end 2026-05-01

# Custom keywords and output
python crawler.py --keywords "confidential computing,SGX,SEV,SEV-SNP,TDX,TEE,enclave,Arm CCA,remote attestation" --output my-report.md

# Skip full-article fetching (faster, less thorough)
python crawler.py --no-fetch-articles

# Force re-fetch of CCC members from LFX (bypasses the 7-day TTL)
python crawler.py --force-refresh

# Skip story clustering (render flat lists as before)
python crawler.py --no-cluster

# Use the deterministic heuristic for clustering (no claude CLI call)
python crawler.py --no-ai-cluster
```

## Output

Three-section Markdown report, with articles grouped by story within each section:
- **Articles BY Members** — publisher or author is a CCC member company
- **Articles ABOUT Members** — article text mentions a CCC member
- **Other Articles** — matched CC keywords but no member mention
- **Subject Companies** — summary of non-member companies that appeared most

When multiple outlets cover the same event, those articles are grouped under a bold story label. Standalone articles appear as plain bullets.

A `subjects-YYYY-MM-DD.json` file is also written alongside the report; each article entry includes a `_cluster` field with the story group id.

## Adding feeds

Edit `feeds.yaml` — no code changes needed.
