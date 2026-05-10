# DSI Ultimate Global Remote Engineering Jobs Collector

This package creates **one final CSV only** for DSI outreach research:

`output/FINAL_USE_THIS_ONLY_YYYY-MM-DD.csv`

No rejected CSV is uploaded. No needs-verification CSV is uploaded. No source report CSV is uploaded. The goal is to remove confusion and give one file to use.

## What it collects

Fresh public job posts from:

- Public remote job APIs
- Trusted RSS feeds
- Public Greenhouse boards
- Public Lever boards
- Public Ashby boards

## What it rejects

- Country restricted remote roles
- US only, UK only, Europe only, LATAM only, APAC only
- Work authorization or visa restricted jobs
- Hybrid, onsite, office required roles
- Agencies, recruiters, anonymous clients
- Non-core DSI roles like Sales Engineer, Support Engineer, PM, Designer, Recruiter, Intern
- Unknown remote jobs with no worldwide/global proof
- Duplicates

## Important truth

You cannot prevent 100% of 404, 403, or 429 on public websites. That is impossible.

This version reduces the damage:

- Failed sources are skipped quietly
- 429 rate limits are retried with waiting
- 403/404 sources are not counted as usable
- Only rows that pass the DSI filter enter the final CSV
- GitHub artifact uploads only the final file

## How to use

1. Create or open your GitHub repo.
2. Upload these files exactly:
   - `dsi_scraper_ultimate.py`
   - `sources.yml`
   - `requirements.txt`
   - `.github/workflows/daily_scrape.yml`
3. Go to **Actions**.
4. Run **DSI Ultimate Global Remote Jobs** manually first.
5. Download the artifact called `FINAL_USE_THIS_ONLY_<run_id>`.

## The only CSV you use

Use:

`FINAL_USE_THIS_ONLY_YYYY-MM-DD.csv`

Start with `quality_tier = A_STRICT_DSI_ICP`.

Use `quality_tier = B_USE_IF_NEED_MORE_VOLUME` only when you want more volume.

## How to increase volume

Open `sources.yml` and add more **validated** small or mid-size remote-first SaaS companies.

Best source types:

- Ashby company boards
- Greenhouse company boards
- Lever company boards

Avoid adding giant companies. Avoid staffing agencies. Avoid broad local job boards.

## How to test filters locally

```bash
pip install -r requirements.txt
python dsi_scraper_ultimate.py --self-test
```

## How to run locally

```bash
python dsi_scraper_ultimate.py
```

