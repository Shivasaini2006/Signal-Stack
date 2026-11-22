import re
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple, Set
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import feedparser
import trafilatura
from sqlmodel import Session, select

from app.core.config import settings
from app.core import db
from app.models.entities import Source, Document, CrawlRun, utcnow

logger = logging.getLogger("signal_stack.crawler")


# In-memory caches for robots.txt and domain rate limits
_robots_cache: Dict[str, Tuple[RobotFileParser, float]] = {}
_domain_last_request: Dict[str, float] = {}
ROBOTS_CACHE_TTL = 3600.0  # 1 hour


def compute_content_hash(text: str) -> str:
    """SHA-256 fingerprint of normalized text content."""
    clean = re.sub(r"\s+", " ", (text or "").strip())
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def compute_simhash(text: str) -> int:
    """
    Compute 64-bit SimHash fingerprint for near-duplicate detection.
    """
    clean_text = re.sub(r"[^\w\s]", "", (text or "").lower())
    words = clean_text.split()
    if not words:
        return 0

    v = [0] * 64
    for w in words:
        # 64-bit integer hash using MD5
        h = int(hashlib.md5(w.encode("utf-8")).hexdigest()[:16], 16)
        for i in range(64):
            bit = (h >> i) & 1
            if bit:
                v[i] += 1
            else:
                v[i] -= 1

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(h1: int, h2: int) -> int:
    """Count differing bits between two 64-bit hashes."""
    return bin(h1 ^ h2).count("1")


def is_robots_allowed_cached(target_url: str, user_agent: str = settings.CRAWLER_USER_AGENT) -> bool:
    """
    Check robots.txt compliance with in-memory caching.
    """
    parsed = urlparse(target_url)
    domain = parsed.netloc.lower()
    if not domain or target_url.startswith("internal://"):
        return True

    now = time.time()
    if domain in _robots_cache:
        rp, ts = _robots_cache[domain]
        if now - ts < ROBOTS_CACHE_TTL:
            try:
                return rp.can_fetch(user_agent, target_url)
            except Exception:
                return True

    robots_url = f"{parsed.scheme}://{domain}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        headers = {"User-Agent": user_agent}
        resp = httpx.get(robots_url, headers=headers, timeout=settings.ROBOTS_TXT_TIMEOUT_SECONDS, follow_redirects=True)
        if resp.status_code in (401, 403):
            return False
        elif resp.status_code == 404:
            can_fetch = True
        else:
            rp.parse(resp.text.splitlines())
            can_fetch = rp.can_fetch(user_agent, target_url)
    except Exception as e:
        logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
        can_fetch = True

    _robots_cache[domain] = (rp, now)
    return can_fetch


def enforce_domain_rate_limit(domain: str):
    """
    Enforce polite rate limiting per domain.
    """
    if not domain or domain.startswith("internal://"):
        return

    now = time.time()
    if domain in _domain_last_request:
        elapsed = now - _domain_last_request[domain]
        delay = settings.CRAWL_DELAY_SECONDS
        if elapsed < delay:
            sleep_needed = delay - elapsed
            logger.debug(f"Rate limiting domain {domain}, sleeping {sleep_needed:.2f}s...")
            time.sleep(sleep_needed)

    _domain_last_request[domain] = time.time()


def parse_feed_entries(feed_text: str, source_url: str) -> List[Dict[str, Any]]:
    """
    Parse RSS/Atom feed entries using feedparser.
    """
    parsed = feedparser.parse(feed_text)
    items: List[Dict[str, Any]] = []

    for entry in parsed.entries[:15]:
        link = entry.get("link") or source_url
        title = entry.get("title") or "Untitled Entry"
        
        # Extract body text
        body = ""
        if "content" in entry and entry.content:
            body = entry.content[0].get("value", "")
        elif "summary" in entry:
            body = entry.summary or ""
        elif "description" in entry:
            body = entry.description or ""

        # Clean HTML from feed entry text using trafilatura or regex
        clean_text = trafilatura.extract(body) if body and "<" in body else body

        # Extract published date
        pub_dt = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                pub_dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        if clean_text and len(clean_text.strip()) > 20:
            items.append({
                "url": link,
                "title": title.strip(),
                "text": clean_text.strip(),
                "published_at": pub_dt,
            })

    return items


def fetch_and_extract_content(url: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """
    Fetch URL via httpx:
    1. Prefer RSS/Atom via feedparser.
    2. Fallback to trafilatura extraction.
    """
    headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    # Handle internal upload placeholder URLs
    if url.startswith("internal://"):
        return [{
            "url": url,
            "title": f"Internal Upload: {url.split('/')[-1].replace('_', ' ').title()}",
            "text": "Internal document placeholder active and ready for ingestion.",
            "published_at": utcnow(),
        }]

    enforce_domain_rate_limit(domain)

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP fetch failed with status {resp.status_code}")

        content_type = resp.headers.get("content-type", "").lower()
        text_content = resp.text

        # 1. Prefer RSS/Atom feed if XML/feed content
        is_feed = (
            "xml" in content_type
            or "rss" in content_type
            or "atom" in content_type
            or url.endswith((".rss", ".xml", "/feed", "/atom"))
            or "<rss" in text_content[:500].lower()
            or "<feed" in text_content[:500].lower()
        )

        if is_feed:
            feed_items = parse_feed_entries(text_content, url)
            if feed_items:
                return feed_items

        # 2. Webpage HTML: Trafilatura extraction
        extracted_text = trafilatura.extract(text_content, include_comments=False) or ""
        
        # Fallback to simple paragraph extraction if trafilatura stripped too aggressively
        if len(extracted_text.strip()) < 50:
            try:
                import lxml.html
                tree = lxml.html.fromstring(resp.content)
                paragraphs = tree.xpath("//p//text()")
                extracted_text = " ".join([p.strip() for p in paragraphs if p.strip()])
            except Exception:
                extracted_text = text_content[:500]

        # Extract title and date
        title = ""
        pub_dt = None
        try:
            import lxml.html
            tree = lxml.html.fromstring(resp.content)
            titles = tree.xpath("//title/text()")
            if titles:
                title = titles[0].strip()
        except Exception:
            title = domain

        try:
            import htmldate
            date_str = htmldate.find_date(text_content)
            if date_str:
                pub_dt = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except Exception:
            pass

        return [{
            "url": str(resp.url),
            "title": title or domain,
            "text": extracted_text.strip(),
            "published_at": pub_dt,
        }]


def run_crawler_pipeline(company_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Executes autonomous crawl run over approved sources:
    - Robots.txt cached checks
    - Per-domain rate limiting
    - Content hash change detection (new vs changed vs unchanged)
    - Near-duplicate deduplication via SimHash
    - CrawlRun logging with per-source status and error isolation
    - Source health metrics update (consecutive_failures, last_success)
    """
    logger.info("Starting autonomous crawl run...")
    with Session(db.engine) as session:
        # Create CrawlRun record
        crawl_run = CrawlRun(
            status="running",
            started_at=utcnow(),
        )
        session.add(crawl_run)
        session.commit()
        session.refresh(crawl_run)

        # Query approved sources
        query = select(Source).where(Source.status == "approved")
        if company_id:
            query = query.where(Source.company_id == company_id)

        sources = session.exec(query).all()
        logger.info(f"Crawl run #{crawl_run.id}: Found {len(sources)} approved sources to crawl.")

        sources_crawled = 0
        docs_found = 0
        docs_new = 0
        docs_changed = 0
        docs_unchanged = 0
        per_source_report = []

        # Load existing documents memory for near-duplicate and hash detection
        existing_docs = session.exec(select(Document)).all()
        # Map: url -> latest Document
        url_to_latest_doc: Dict[str, Document] = {}
        # List of existing simhashes
        existing_simhashes: List[Tuple[int, str]] = []

        for doc in existing_docs:
            url_to_latest_doc[doc.url] = doc
            if doc.simhash:
                try:
                    existing_simhashes.append((int(doc.simhash), doc.title or ""))
                except Exception:
                    pass

        for source in sources:
            sources_crawled += 1
            source_start = time.time()
            source_report: Dict[str, Any] = {
                "source_id": source.id,
                "name": source.name,
                "url": source.url,
                "status": "success",
                "items_processed": 0,
                "items_new": 0,
                "items_changed": 0,
                "items_unchanged": 0,
                "error": None,
            }

            try:
                # 1. Robots.txt check
                if not is_robots_allowed_cached(source.url):
                    logger.warning(f"Robots.txt disallows crawling {source.url}")
                    source_report["status"] = "skipped_robots"
                    source.last_checked = utcnow()
                    session.add(source)
                    per_source_report.append(source_report)
                    continue

                # 2. Fetch and Extract
                items = fetch_and_extract_content(source.url)
                source_report["items_processed"] = len(items)
                docs_found += len(items)

                for item in items:
                    item_url = item["url"]
                    text = item["text"]
                    if not text or len(text.strip()) < 15:
                        continue

                    chash = compute_content_hash(text)
                    shash_int = compute_simhash(text)
                    shash_str = str(shash_int)
                    title = item.get("title") or source.name
                    pub_at = item.get("published_at")

                    # Check against existing document by URL
                    if item_url in url_to_latest_doc:
                        existing = url_to_latest_doc[item_url]
                        if existing.content_hash == chash:
                            # Unchanged
                            docs_unchanged += 1
                            source_report["items_unchanged"] += 1
                        else:
                            # Changed content! Keep full history by inserting new version
                            new_version_doc = Document(
                                url=item_url,
                                content_hash=chash,
                                title=title,
                                text=text,
                                simhash=shash_str,
                                published_at=pub_at,
                                fetched_at=utcnow(),
                                source_id=source.id,
                                crawl_run_id=crawl_run.id,
                            )
                            session.add(new_version_doc)
                            url_to_latest_doc[item_url] = new_version_doc
                            docs_changed += 1
                            source_report["items_changed"] += 1
                    else:
                        # Near-duplicate check via SimHash (Hamming distance <= 3)
                        is_near_dup = False
                        norm_title = re.sub(r"\W+", " ", title.lower()).strip()
                        for prev_shash, prev_title in existing_simhashes:
                            norm_prev = re.sub(r"\W+", " ", prev_title.lower()).strip()
                            if norm_title and norm_prev and (norm_title == norm_prev or norm_title in norm_prev):
                                if hamming_distance(prev_shash, shash_int) <= 3:
                                    is_near_dup = True
                                    break

                        if is_near_dup:
                            docs_unchanged += 1
                            source_report["items_unchanged"] += 1
                        else:
                            # Completely new document
                            new_doc = Document(
                                url=item_url,
                                content_hash=chash,
                                title=title,
                                text=text,
                                simhash=shash_str,
                                published_at=pub_at,
                                fetched_at=utcnow(),
                                source_id=source.id,
                                crawl_run_id=crawl_run.id,
                            )
                            session.add(new_doc)
                            url_to_latest_doc[item_url] = new_doc
                            existing_simhashes.append((shash_int, title))
                            docs_new += 1
                            source_report["items_new"] += 1

                # Update source health on success
                source.health = "ok"
                source.consecutive_failures = 0
                source.last_success = utcnow()
                source.last_error = None
                source.last_checked = utcnow()
                session.add(source)

            except Exception as e:
                # Failure logged without crashing!
                error_msg = str(e)
                logger.error(f"Error crawling source #{source.id} ({source.url}): {error_msg}")
                source_report["status"] = "failed"
                source_report["error"] = error_msg

                source.consecutive_failures += 1
                source.last_error = error_msg
                source.last_checked = utcnow()
                source.health = "failing" if source.consecutive_failures >= 3 else "warning"
                session.add(source)

            source_report["duration_seconds"] = round(time.time() - source_start, 2)
            per_source_report.append(source_report)

        # Update crawl_run statistics
        crawl_run.status = "completed"
        crawl_run.finished_at = utcnow()
        crawl_run.sources_crawled = sources_crawled
        crawl_run.documents_found = docs_found
        crawl_run.documents_new = docs_new
        crawl_run.documents_changed = docs_changed
        crawl_run.documents_unchanged = docs_unchanged
        session.add(crawl_run)
        session.commit()
        session.refresh(crawl_run)

        return {
            "crawl_run_id": crawl_run.id,
            "status": crawl_run.status,
            "started_at": crawl_run.started_at.isoformat() if crawl_run.started_at else None,
            "finished_at": crawl_run.finished_at.isoformat() if crawl_run.finished_at else None,
            "sources_crawled": sources_crawled,
            "documents_found": docs_found,
            "documents_new": docs_new,
            "documents_changed": docs_changed,
            "documents_unchanged": docs_unchanged,
            "per_source_report": per_source_report,
        }
