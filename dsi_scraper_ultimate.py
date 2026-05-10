#!/usr/bin/env python3
"""
DSI Ultimate Global Remote Engineering Hiring Collector

Purpose:
- Collect only real job posts from public APIs, RSS feeds, and public ATS boards.
- Output ONE usable CSV only: output/FINAL_USE_THIS_ONLY_YYYY-MM-DD.csv
- No rejected CSV, no debug CSV, no confusing extra artifacts.

Hard truth built into the code:
- 404, 403, and 429 cannot be prevented 100 percent. The scraper handles them quietly.
- Failed sources are skipped and never counted as data sources.
- Weak remote jobs do not enter final unless the full text proves global/worldwide remote.
- Unknown location does not enter final.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
import requests
import tldextract
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from rapidfuzz import fuzz

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
SOURCES_FILE = BASE_DIR / "sources.yml"
TODAY = datetime.now(timezone.utc)
DATE_STAMP = TODAY.strftime("%Y-%m-%d")

# One final file only. Keep the user clean and focused.
FINAL_FILE = OUTPUT_DIR / f"FINAL_USE_THIS_ONLY_{DATE_STAMP}.csv"

TARGET_MARKETS = {
    "United States", "USA", "Canada", "United Kingdom", "UK", "Ireland", "Australia",
    "New Zealand", "Singapore", "Netherlands", "Germany", "Switzerland", "Sweden",
    "Norway", "Denmark", "Finland", "UAE", "United Arab Emirates",
}
STRICT_HEADCOUNT = {"10 to 50", "51 to 100", "101 to 200"}
SECONDARY_HEADCOUNT = {"201 to 500", "unknown"}

FINAL_COLUMNS = [
    "quality_tier", "company", "company_domain", "company_website",
    "company_headcount_bucket", "company_hq_country", "job_title", "role_family",
    "seniority", "location", "dsi_icp_score", "posted_date", "days_old", "source",
    "source_type", "job_url", "global_remote_evidence", "restriction_evidence",
    "timezone_evidence", "score_reasons", "tech_stack_detected", "description_summary",
]

# Core DSI role families. Intentionally strict.
ROLE_FAMILY_PATTERNS: Dict[str, List[str]] = {
    "backend": ["backend", "back end", "back-end", "server engineer", "api engineer", "api developer"],
    "frontend": ["frontend", "front end", "front-end", "react", "javascript engineer", "typescript engineer", "web engineer"],
    "fullstack": ["full stack", "fullstack", "full-stack", "product engineer"],
    "mobile": ["mobile engineer", "mobile developer", "android", "ios", "flutter", "react native", "swift", "kotlin"],
    "devops": ["devops", "cloud engineer", "platform engineer", "infrastructure engineer", "site reliability", "sre", "kubernetes", "terraform"],
    "qa automation": ["qa automation", "automation engineer", "test automation", "sdet", "qa engineer", "quality engineer"],
    "data engineering": ["data engineer", "analytics engineer", "data platform", "etl", "pipeline engineer"],
    "ai ml": ["machine learning engineer", "ml engineer", "ai engineer", "llm engineer", "computer vision", "nlp engineer"],
    "security engineering": ["application security engineer", "cloud security engineer", "product security engineer", "security engineer"],
    "software": ["software engineer", "software developer", "python", "java developer", "java engineer", "node", "node.js", "php developer", "ruby", "rails", "golang", "go developer", "rust", "c++", "c#", ".net", "dotnet", "scala", "elixir", "application developer"],
    "technical lead": ["technical lead", "tech lead", "lead software engineer", "lead developer", "staff engineer", "principal engineer"],
}

NON_CORE_REJECT = [
    "customer support engineer", "technical support engineer", "support engineer", "help desk", "it support",
    "solutions engineer", "solution engineer", "solutions architect", "sales engineer", "pre sales", "presales",
    "engineering manager", "director of engineering", "vp engineering", "head of engineering",
    "product manager", "project manager", "program manager", "scrum master", "business analyst",
    "data analyst", "ux designer", "ui designer", "graphic designer", "product designer",
    "recruiter", "talent acquisition", "intern", "student", "trainee", "apprentice", "werkstudent", "praktikum",
    "business developer", "marketing", "sales", "account executive", "operations", "finance", "legal", "hr", "human resources", "technical writer",
]

STRONG_GLOBAL_PATTERNS = [
    r"\bworldwide\b", r"\bwork from anywhere\b", r"\banywhere in the world\b",
    r"\bremote anywhere\b", r"\bglobal remote\b", r"\bglobally remote\b", r"\bremote globally\b",
    r"\bopen globally\b", r"\bopen to candidates worldwide\b", r"\bno location restriction\b",
    r"\blocation independent\b", r"\bglobally distributed\b", r"\bfully distributed\b",
    r"\bhire from anywhere\b", r"\ball countries\b", r"\bany country\b", r"\bopen to all locations\b",
    r"\bworking remotely from anywhere\b",
]

# Standalone anywhere is strong only if it appears in the location field, not buried in unrelated text.
LOCATION_STRONG_WORDS = ["worldwide", "anywhere", "global", "remote anywhere", "work from anywhere"]

WEAK_REMOTE_PATTERNS = [
    r"\bremote\b", r"\bfully remote\b", r"\b100% remote\b", r"\bremote first\b", r"\bremote-first\b",
    r"\bdistributed\b", r"\basync\b", r"\bhome office\b", r"\bvirtual\b", r"\bflexible location\b",
]

HARD_REJECT_PATTERNS = [
    r"\bunited states only\b", r"\bus only\b", r"\busa only\b", r"\bus based only\b", r"\bus-based only\b",
    r"\bmust be in the us\b", r"\bmust be located in the us\b", r"\bmust reside in the us\b", r"\bus residents only\b",
    r"\bus citizen\b", r"\bus citizens only\b", r"\bremote\s*[-,(/]*\s*us\b", r"\bremote us only\b", r"\bnorth america only\b",
    r"\buk only\b", r"\buk-based only\b", r"\bunited kingdom only\b", r"\buk residents only\b", r"\bremote\s*[-,(/]*\s*uk\b",
    r"\bcanada only\b", r"\bcanada-based only\b", r"\bcanadian residents only\b", r"\bremote\s*[-,(/]*\s*canada\b",
    r"\beu only\b", r"\beurope only\b", r"\beuropean union only\b", r"\beu-based only\b", r"\bremote in europe\b", r"\bremote\s*[-,(/]*\s*europe\b",
    r"\bemea only\b", r"\bemea based\b", r"\bemea-only\b", r"\bapac only\b", r"\blatam only\b", r"\blatin america only\b", r"\bremote\s*[-,(/]*\s*latam\b",
    r"\baustralia only\b", r"\bnew zealand only\b", r"\bindia only\b", r"\bgermany only\b", r"\bfrance only\b", r"\bspain only\b", r"\bpoland only\b", r"\bportugal only\b", r"\bromania only\b", r"\bserbia only\b", r"\bukraine only\b",
    r"\bwork authorization required\b", r"\bauthorized to work in\b", r"\bmust be authorized to work\b", r"\blegally authorized to work\b", r"\bright to work in\b", r"\bwork permit required\b",
    r"\bno visa sponsorship\b", r"\bvisa sponsorship not available\b", r"\bvisa sponsorship is not available\b", r"\bnot able to sponsor\b", r"\bunable to sponsor\b", r"\bcannot sponsor\b", r"\bsponsorship not provided\b",
    r"\bmust have work authorization\b", r"\beligible to work in\b", r"\bmust be eligible to work in\b",
    r"\bmust be based in\b", r"\bmust live in\b", r"\bmust be located in\b", r"\bapplicants must be based in\b", r"\bapplicants must reside\b", r"\bmust reside in\b",
    r"\bmust be a citizen of\b", r"\bcitizenship required\b", r"\brestricted to residents of\b", r"\bonly open to residents\b", r"\bonly available in\b", r"\bhiring only in\b",
    r"\bhybrid\b", r"\bonsite\b", r"\bon-site\b", r"\boffice required\b", r"\bmust commute\b",
]

LOCATION_REJECT_COUNTRIES = [
    "united states", "usa", "canada", "united kingdom", "uk", "germany", "france", "spain", "poland", "portugal",
    "romania", "serbia", "ukraine", "india", "australia", "new zealand", "europe", "emea", "apac", "latam",
    "brazil", "mexico", "argentina", "colombia", "chile", "ireland", "netherlands", "sweden", "norway", "denmark", "finland",
    "singapore", "berlin", "london", "new york", "san francisco", "toronto", "austin", "dublin", "bengaluru", "bangalore",
]

AGENCY_TERMS = [
    "recruitment", "recruiting", "staffing", "headhunt", "placement agency", "talent marketplace", "talent solutions",
    "talent group", "talent agency", "hiring agency", "it staffing", "tech staffing", "staff augmentation", "body shop",
    "manpower", "randstad", "adecco", "hays", "michael page", "robert half", "kelly services", "insight global",
    "teksystems", "tek systems", "modis", "cybercoders", "cooper lomaz", "spectrum it", "lorien", "direct sourcing", "wing assistant",
]
ANON_TERMS = ["confidential", "undisclosed", "anonymous", "our client", "private client"]

TECH_TERMS = [
    "python", "javascript", "typescript", "react", "node", "node.js", "java", "php", "ruby", "rails", "golang", "go",
    "rust", "kotlin", "swift", "flutter", "aws", "gcp", "azure", "kubernetes", "docker", "terraform", "postgres",
    "postgresql", "mysql", "mongodb", "redis", "graphql", "rest api", "microservice", "ci/cd", "kafka", "spark", "llm",
    "machine learning", "ai", "data pipeline",
]

SENIORITY_MAP = [
    ("principal", ["principal"]),
    ("staff", ["staff"]),
    ("lead", ["lead", "technical lead", "tech lead"]),
    ("senior", ["senior", "sr.", "sr "]),
    ("mid_or_unspecified", ["engineer", "developer"]),
]

@dataclass
class RawJob:
    source: str
    source_type: str
    trust_score: int
    company: str
    title: str
    location: str
    url: str
    posted: Optional[datetime]
    description: str
    job_type: str = ""
    ats_job_id: str = ""
    company_meta: Dict[str, Any] = None

@dataclass
class SourceStats:
    attempted: int = 0
    ok: int = 0
    skipped: int = 0
    raw_jobs: int = 0
    final_jobs: int = 0
    hidden_errors: int = 0
    last_status: str = ""

class PatientHTTP:
    """Simple polite HTTP client. Avoids noisy 404/403/429 output."""
    def __init__(self, timeout: int = 18, debug: bool = False):
        self.session = requests.Session()
        self.timeout = timeout
        self.debug = debug
        self.last_request_by_domain: Dict[str, float] = {}
        self.session.headers.update({
            "User-Agent": "DSI-Global-Remote-Jobs-Collector/4.0 (+https://www.dsinnovators.com/)",
            "Accept": "application/json, application/xml, text/xml, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        })

    def get(self, url: str, min_delay: float = 0.5, retries: int = 2) -> Tuple[Optional[requests.Response], str]:
        domain = urlparse(url).netloc.lower()
        elapsed = time.time() - self.last_request_by_domain.get(domain, 0)
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed + random.uniform(0.05, 0.25))
        self.last_request_by_domain[domain] = time.time()

        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout)
                status = r.status_code
                if status == 200:
                    return r, "200"
                if status == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait_s = int(retry_after) if retry_after and retry_after.isdigit() else min(45, 5 * (attempt + 1))
                    time.sleep(wait_s + random.uniform(0, 1.0))
                    continue
                if status in (403, 404, 410):
                    return None, str(status)
                if 500 <= status < 600 and attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                return None, str(status)
            except Exception as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return None, f"exception:{type(e).__name__}"
        return None, "failed"

# ------------------------- text helpers -------------------------

def clean_text(x: Any) -> str:
    if x is None:
        return ""
    s = str(x)
    if "<" in s and ">" in s:
        s = BeautifulSoup(s, "html.parser").get_text(" ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def lower(x: Any) -> str:
    return clean_text(x).lower()

def parse_date(raw: Any) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            val = raw / 1000 if raw > 1e12 else raw
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    try:
        dt = dateparser.parse(str(raw))
        if not dt:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fmt_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""

def days_old(dt: Optional[datetime]) -> int:
    if not dt:
        return 999
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (TODAY - dt).days)

def domain_from_url(url: str) -> str:
    if not url:
        return ""
    ext = tldextract.extract(url)
    if not ext.domain or not ext.suffix:
        return ""
    return f"{ext.domain}.{ext.suffix}".lower()

def normalized_company(name: str) -> str:
    s = lower(name)
    s = re.sub(r"\b(inc|llc|ltd|limited|gmbh|bv|pty|co|company|corp|corporation)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def title_norm(title: str) -> str:
    s = lower(title)
    s = re.sub(r"\b(senior|sr|lead|principal|staff|junior|jr|mid|remote|worldwide|global|ii|iii|iv)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def evidence(patterns: Iterable[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            return m.group(0)[:120]
    return ""

# ------------------------- classifiers -------------------------

def role_family(title: str) -> str:
    t = lower(title)
    for bad in NON_CORE_REJECT:
        if bad in t:
            return "reject"
    for fam, pats in ROLE_FAMILY_PATTERNS.items():
        for p in pats:
            if p in t:
                return fam
    return "reject"

def seniority(title: str) -> str:
    t = lower(title)
    if any(x in t for x in ["principal"]): return "principal"
    if any(x in t for x in ["staff"]): return "staff"
    if any(x in t for x in ["lead", "tech lead", "technical lead"]): return "lead"
    if any(x in t for x in ["senior", "sr.", "sr "]): return "senior"
    if any(x in t for x in ["junior", "jr.", "intern", "trainee"]): return "reject"
    return "mid_or_unspecified"

def is_agency_or_anon(company: str) -> bool:
    c = lower(company)
    return any(x in c for x in AGENCY_TERMS) or any(x in c for x in ANON_TERMS) or not c

def restriction_status(title: str, location: str, desc: str) -> Tuple[bool, str]:
    # location gets stricter than full text because a city/country location almost always means restriction.
    loc = lower(location)
    combined = f"{lower(title)} {loc} {lower(desc[:3500])}"
    ev = evidence(HARD_REJECT_PATTERNS, combined)
    if ev:
        return True, ev

    if loc:
        # Reject specific locations unless strong global words are present in location itself.
        strong_in_loc = any(w in loc for w in LOCATION_STRONG_WORDS)
        if not strong_in_loc:
            for place in LOCATION_REJECT_COUNTRIES:
                if re.search(rf"\b{re.escape(place)}\b", loc):
                    return True, place
    return False, "no country restriction found"

def global_remote_status(location: str, desc: str) -> Tuple[str, str]:
    loc = lower(location)
    desc_l = lower(desc[:4000])
    # Strong location evidence first
    for w in LOCATION_STRONG_WORDS:
        if w in loc:
            return "proven_worldwide", w
    ev = evidence(STRONG_GLOBAL_PATTERNS, f"{loc} {desc_l}")
    if ev:
        return "proven_worldwide", ev
    if evidence(WEAK_REMOTE_PATTERNS, loc) or evidence(WEAK_REMOTE_PATTERNS, desc_l):
        return "weak_remote", evidence(WEAK_REMOTE_PATTERNS, f"{loc} {desc_l}") or "remote"
    return "reject_unknown_location", "no global remote proof"

def timezone_evidence(desc: str) -> str:
    d = lower(desc[:3000])
    for phrase in ["async", "asynchronous", "flexible hours", "work your own hours", "timezone flexible", "distributed team", "remote-first", "remote first"]:
        if phrase in d:
            return phrase
    return ""

def tech_stack(desc: str) -> str:
    d = lower(desc[:5000])
    found = []
    for term in TECH_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", d):
            found.append(term)
    return ", ".join(sorted(set(found))[:12])

def score_job(job: RawJob, fam: str, remote_class: str, global_ev: str, restriction_ev: str, tz_ev: str, tech: str, meta: Dict[str, Any]) -> Tuple[int, str, str]:
    score = 0
    reasons = []
    if remote_class == "proven_worldwide":
        score += 30; reasons.append("proven remote worldwide +30")
    if restriction_ev == "no country restriction found":
        score += 15; reasons.append("no country restriction found +15")
    if tz_ev:
        score += 5; reasons.append("timezone or async friendly +5")
    head_bucket = meta.get("headcount_bucket", "unknown")
    if head_bucket in STRICT_HEADCOUNT:
        score += 20; reasons.append("headcount 10-200 +20")
    elif head_bucket in SECONDARY_HEADCOUNT:
        score += 5; reasons.append("headcount not strict +5")
    hq = meta.get("hq_country", "")
    if hq in TARGET_MARKETS or meta.get("target_market_fit") == "yes":
        score += 10; reasons.append("target English market +10")
    if meta.get("company_type", "").lower() or "saas" in lower(job.description) or "software" in lower(job.description):
        score += 5; reasons.append("software or SaaS company +5")
    if fam != "reject":
        score += 15; reasons.append("core DSI engineering role +15")
    age = days_old(job.posted)
    if age <= 7:
        score += 10; reasons.append("posted within 7 days +10")
    elif age <= 14:
        score += 7; reasons.append("posted within 14 days +7")
    elif age <= 21:
        score += 5; reasons.append("posted within 21 days +5")
    elif age <= 30:
        score += 2; reasons.append("posted within 30 days +2")
    if job.trust_score >= 9:
        score += 10; reasons.append("official ATS or company career source +10")
    elif job.trust_score >= 6:
        score += 6; reasons.append("trusted remote board +6")
    if tech:
        score += 3; reasons.append("tech stack detected +3")
    # Quality tier in ONE file, so user knows what to use first.
    if score >= 80 and head_bucket in STRICT_HEADCOUNT and remote_class == "proven_worldwide":
        tier = "A_STRICT_DSI_ICP"
    elif score >= 72 and remote_class == "proven_worldwide":
        tier = "B_USE_IF_NEED_MORE_VOLUME"
    else:
        tier = "DROP"
    return min(score, 100), tier, " | ".join(reasons)

# ------------------------- fetchers -------------------------

def raw_meta(src: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(src.get("company_meta") or {})
    if src.get("company_domain") and not meta.get("company_domain"):
        meta["company_domain"] = src.get("company_domain")
    if src.get("company_website") and not meta.get("company_website"):
        meta["company_website"] = src.get("company_website")
    return meta

def make_job(src: Dict[str, Any], company: str, title: str, location: str, url: str, posted: Any, desc: str, job_type: str = "", ats_job_id: str = "") -> RawJob:
    return RawJob(
        source=src.get("name", ""), source_type=src.get("source_type_label", src.get("type", "")),
        trust_score=int(src.get("trust_score", 0)), company=clean_text(company), title=clean_text(title),
        location=clean_text(location), url=clean_text(url), posted=parse_date(posted), description=clean_text(desc),
        job_type=clean_text(job_type), ats_job_id=str(ats_job_id or ""), company_meta=raw_meta(src)
    )

def fetch_remotive(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for cat in src.get("categories", ["software-dev"]):
        url = f"https://remotive.com/api/remote-jobs?category={cat}&limit={src.get('limit', 500)}"
        r, _ = http.get(url, min_delay=src.get("delay_seconds", 1.0))
        if not r: continue
        try:
            data = r.json()
        except Exception:
            continue
        for j in data.get("jobs", []):
            out.append(make_job(src, j.get("company_name", ""), j.get("title", ""), j.get("candidate_required_location", ""), j.get("url", ""), j.get("publication_date"), j.get("description", ""), j.get("job_type", ""), j.get("id", "")))
    return out

def fetch_jobicy(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for ind in src.get("industries", ["engineering"]):
        url = f"https://jobicy.com/api/v2/remote-jobs?count={src.get('limit', 50)}&industry={ind}"
        r, _ = http.get(url, min_delay=src.get("delay_seconds", 1.0))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobs", []):
            out.append(make_job(src, j.get("companyName", ""), j.get("jobTitle", ""), j.get("jobGeo", ""), j.get("url", ""), j.get("pubDate"), j.get("jobDescription", ""), j.get("jobType", ""), j.get("id", "")))
    return out

def fetch_remoteok(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    r, _ = http.get("https://remoteok.com/api", min_delay=src.get("delay_seconds", 2.0), retries=3)
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data[1:] if isinstance(data, list) else []:
        out.append(make_job(src, j.get("company", ""), j.get("position", ""), j.get("location", ""), j.get("url", ""), j.get("epoch"), j.get("description", ""), "", j.get("id", "")))
    return out

def fetch_arbeitnow(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    max_pages = int(src.get("max_pages", 5))
    for page in range(1, max_pages + 1):
        r, _ = http.get(f"https://arbeitnow.com/api/job-board-api?page={page}", min_delay=src.get("delay_seconds", 1.0))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        items = data.get("data", [])
        if not items: break
        for j in items:
            if not j.get("remote"):
                continue
            out.append(make_job(src, j.get("company_name", ""), j.get("title", ""), j.get("location", ""), j.get("url", ""), j.get("created_at"), j.get("description", ""), ", ".join(j.get("job_types") or []), j.get("slug", "")))
    return out

def fetch_himalayas(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for q in src.get("queries", ["engineer"]):
        url = f"https://himalayas.app/jobs/api?q={requests.utils.quote(q)}&limit={src.get('limit', 100)}&remote=true"
        r, _ = http.get(url, min_delay=src.get("delay_seconds", 1.0))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobs", []):
            loc = j.get("locationRestrictions", "") or j.get("location", "") or ""
            if isinstance(loc, list): loc = ", ".join(loc)
            company = j.get("companyName", "") or (j.get("company") or {}).get("name", "")
            out.append(make_job(src, company, j.get("title", ""), loc, j.get("applicationLink", "") or j.get("jobUrl", ""), j.get("createdAt"), j.get("description", ""), j.get("employmentType", ""), j.get("id", "")))
    return out

def fetch_rss(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    r, _ = http.get(src["url"], min_delay=src.get("delay_seconds", 1.0))
    if not r: return []
    out = []
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(r.content)
    except Exception:
        return []
    for item in root.findall("./channel/item"):
        raw_title = clean_text(item.findtext("title", ""))
        link = clean_text(item.findtext("link", ""))
        desc = item.findtext("description", "") or ""
        posted = item.findtext("pubDate", "") or item.findtext("date", "") or ""
        company, title = "", raw_title
        if src.get("title_format") == "company_colon_title" and ":" in raw_title:
            company, title = [x.strip() for x in raw_title.split(":", 1)]
        company = company or src.get("default_company", "")
        loc = src.get("default_location", "Remote")
        out.append(make_job(src, company, title, loc, link, posted, desc, "", link))
    return out

def fetch_greenhouse(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    r, _ = http.get(url, min_delay=src.get("delay_seconds", 0.8))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data.get("jobs", []):
        loc_obj = j.get("location") or {}
        loc = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
        out.append(make_job(src, src.get("company_name", board), j.get("title", ""), loc, j.get("absolute_url", ""), j.get("updated_at"), j.get("content", ""), "", j.get("id", "")))
    return out

def fetch_lever(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    r, _ = http.get(f"https://api.lever.co/v0/postings/{board}?mode=json", min_delay=src.get("delay_seconds", 0.8))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    if not isinstance(data, list): return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or cats.get("allLocations") or ""
        if isinstance(loc, list): loc = ", ".join(loc)
        desc = j.get("descriptionPlain") or j.get("description") or ""
        out.append(make_job(src, src.get("company_name", board), j.get("text", ""), loc, j.get("hostedUrl", ""), j.get("createdAt"), desc, cats.get("commitment", ""), j.get("id", "")))
    return out

def fetch_ashby(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    url = f"https://jobs.ashbyhq.com/api/non-user-facing/job-board/{board}/posting-group/published"
    r, _ = http.get(url, min_delay=src.get("delay_seconds", 0.8))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data.get("jobPostings", []):
        out.append(make_job(src, src.get("company_name", board), j.get("title", ""), j.get("locationName", "") or j.get("location", ""), j.get("jobUrl", "") or j.get("applyUrl", ""), j.get("publishedAt"), j.get("descriptionHtml", "") or j.get("description", ""), j.get("employmentType", ""), j.get("id", "")))
    return out

FETCHERS = {
    "remotive_api": fetch_remotive,
    "jobicy_api": fetch_jobicy,
    "remoteok_api": fetch_remoteok,
    "arbeitnow_api": fetch_arbeitnow,
    "himalayas_api": fetch_himalayas,
    "rss": fetch_rss,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}

# ------------------------- pipeline -------------------------

def row_from_job(job: RawJob) -> Optional[Dict[str, Any]]:
    if not job.url:
        return None
    if is_agency_or_anon(job.company):
        return None
    fam = role_family(job.title)
    if fam == "reject":
        return None
    sen = seniority(job.title)
    if sen == "reject":
        return None
    # Freshness hard gate. Keep under 30 days. Unknown dates are allowed only for trusted ATS.
    age = days_old(job.posted)
    if age > 30 and job.trust_score < 9:
        return None
    restricted, restriction_ev = restriction_status(job.title, job.location, job.description)
    if restricted:
        return None
    remote_class, global_ev = global_remote_status(job.location, job.description)
    if remote_class != "proven_worldwide":
        return None
    meta = job.company_meta or {}
    domain = meta.get("company_domain") or domain_from_url(meta.get("company_website", "")) or domain_from_url(job.url)
    if not domain:
        domain = normalized_company(job.company).replace(" ", "")
    head_bucket = meta.get("headcount_bucket", "unknown")
    # Avoid 500+ and unknown low-confidence rows in the final. Unknown can only appear as B if score is very strong.
    if head_bucket in {"1 to 9", "501 plus"}:
        return None
    tz = timezone_evidence(job.description)
    tech = tech_stack(job.description)
    score, tier, reasons = score_job(job, fam, remote_class, global_ev, restriction_ev, tz, tech, meta)
    if tier == "DROP":
        return None
    # Strict job URLs only from trusted sources. Aggregators must score high and be remote proven.
    if job.trust_score < 5:
        return None
    summary = clean_text(job.description)[:220]
    return {
        "quality_tier": tier,
        "company": job.company,
        "company_domain": domain,
        "company_website": meta.get("company_website", f"https://{domain}" if domain and "." in domain else ""),
        "company_headcount_bucket": head_bucket,
        "company_hq_country": meta.get("hq_country", "unknown"),
        "job_title": job.title,
        "role_family": fam,
        "seniority": sen,
        "location": job.location,
        "dsi_icp_score": score,
        "posted_date": fmt_date(job.posted),
        "days_old": age,
        "source": job.source,
        "source_type": job.source_type,
        "job_url": job.url,
        "global_remote_evidence": global_ev,
        "restriction_evidence": restriction_ev,
        "timezone_evidence": tz,
        "score_reasons": reasons,
        "tech_stack_detected": tech,
        "description_summary": summary,
        "_dedup_url": normalize_url(job.url),
        "_company_key": domain or normalized_company(job.company),
        "_title_norm": title_norm(job.title),
        "_role_family": fam,
    }

def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return url.lower().strip()

def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_urls = set()
    for row in sorted(rows, key=lambda r: (-int(r.get("dsi_icp_score", 0)), r.get("company", ""))):
        u = row.get("_dedup_url", "")
        if u and u in seen_urls:
            continue
        duplicate = False
        for old in out:
            if row.get("_company_key") == old.get("_company_key") and row.get("_role_family") == old.get("_role_family"):
                if fuzz.ratio(row.get("_title_norm", ""), old.get("_title_norm", "")) >= 92:
                    duplicate = True
                    break
        if duplicate:
            continue
        seen_urls.add(u)
        out.append(row)
    for r in out:
        for k in ["_dedup_url", "_company_key", "_title_norm", "_role_family"]:
            r.pop(k, None)
    return out

def load_sources() -> List[Dict[str, Any]]:
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [s for s in data.get("sources", []) if s.get("enabled", True)]

def run_scraper(debug: bool = False) -> pd.DataFrame:
    OUTPUT_DIR.mkdir(exist_ok=True)
    http = PatientHTTP(debug=debug)
    sources = load_sources()
    stats: Dict[str, SourceStats] = {}
    raw_jobs: List[RawJob] = []
    for src in sources:
        name = src.get("name", src.get("type", "unknown"))
        st = stats.setdefault(name, SourceStats())
        st.attempted += 1
        fetcher = FETCHERS.get(src.get("type"))
        if not fetcher:
            st.skipped += 1
            st.last_status = "unsupported_type"
            continue
        try:
            jobs = fetcher(http, src)
            if jobs:
                st.ok += 1
                st.raw_jobs += len(jobs)
                raw_jobs.extend(jobs)
            else:
                st.skipped += 1
                st.last_status = "no_jobs_or_blocked"
        except Exception as e:
            st.hidden_errors += 1
            st.last_status = type(e).__name__
        # Short jitter prevents hammering shared domains.
        time.sleep(float(src.get("post_source_delay", 0.15)) + random.uniform(0.02, 0.12))

    rows = []
    for j in raw_jobs:
        row = row_from_job(j)
        if row:
            rows.append(row)
            if j.source in stats:
                stats[j.source].final_jobs += 1
    final_rows = dedupe_rows(rows)
    df = pd.DataFrame(final_rows, columns=FINAL_COLUMNS)
    if not df.empty:
        df = df.sort_values(["quality_tier", "dsi_icp_score", "posted_date"], ascending=[True, False, False])
    df.to_csv(FINAL_FILE, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    successful_sources = sum(1 for s in stats.values() if s.raw_jobs > 0)
    final_sources = len(set(df["source"])) if not df.empty else 0
    strict_count = len(df[df["quality_tier"] == "A_STRICT_DSI_ICP"]) if not df.empty else 0
    b_count = len(df[df["quality_tier"] == "B_USE_IF_NEED_MORE_VOLUME"]) if not df.empty else 0
    print("=" * 72)
    print("DSI ULTIMATE SCRAPE COMPLETE")
    print("=" * 72)
    print(f"Raw jobs collected        : {len(raw_jobs)}")
    print(f"Successful raw sources    : {successful_sources}")
    print(f"Sources in final CSV      : {final_sources}")
    print(f"A strict ICP rows         : {strict_count}")
    print(f"B backup rows             : {b_count}")
    print(f"Final usable rows         : {len(df)}")
    print(f"Output file               : {FINAL_FILE}")
    if final_sources < 10:
        print("WARNING: Final source diversity is low. Add more validated ICP company boards in sources.yml.")
    if strict_count == 0:
        print("WARNING: No strict A rows. This means headcount/global evidence is too weak from today's public data.")
    print("=" * 72)
    return df

# ------------------------- self-test -------------------------

def self_test() -> None:
    reject_locs = ["Remote, Germany", "Remote in Europe", "Remote US only", "United States", "Canada", "UK", "EMEA", "LATAM", "APAC", "Hybrid", "Onsite", "Must be based in Spain", "Must reside in Canada"]
    for loc in reject_locs:
        restricted, _ = restriction_status("Senior Backend Engineer", loc, "")
        assert restricted, f"Should reject location: {loc}"
    reject_descs = ["Work authorization required", "Visa sponsorship not available", "Legally authorized to work in the US"]
    for desc in reject_descs:
        restricted, _ = restriction_status("Senior Backend Engineer", "Remote", desc)
        assert restricted, f"Should reject desc: {desc}"
    accept_locs = ["Worldwide", "Remote Worldwide", "Anywhere", "Work from anywhere", "Anywhere in the world", "Global remote", "Open globally", "No location restriction", "Location independent", "Globally distributed"]
    for loc in accept_locs:
        restricted, _ = restriction_status("Senior Backend Engineer", loc, "")
        rc, ev = global_remote_status(loc, "")
        assert not restricted and rc == "proven_worldwide", f"Should accept strong global: {loc} got {rc} {ev}"
    weak_locs = ["Remote", "Fully remote", "Distributed", "Remote first", "Async"]
    for loc in weak_locs:
        rc, _ = global_remote_status(loc, "")
        assert rc == "weak_remote", f"Should be weak, not strict: {loc}"
    bad_titles = ["Customer Support Engineer", "Sales Engineer", "Engineering Manager", "Recruiter", "Intern"]
    for title in bad_titles:
        assert role_family(title) == "reject", f"Should reject title: {title}"
    good_titles = ["Senior Backend Engineer", "Full Stack Developer", "DevOps Engineer", "QA Automation Engineer", "Machine Learning Engineer"]
    for title in good_titles:
        assert role_family(title) != "reject", f"Should accept title: {title}"
    print("Self-test passed: filters are strict.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        run_scraper(debug=args.debug)
