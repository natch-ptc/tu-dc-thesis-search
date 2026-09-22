# TU Digital Collections Thesis Search

Searches Thai theses / research works from [TU Digital Collections](https://digital.library.tu.ac.th/tu_dc/frontend/Search/)
(Thammasat University Library) by keyword and turns each hit into a flat
record: title, creator, keyword, abstract, publisher, and date of issue.

The site's search page calls an internal (undocumented) JSON API when you
hit "search" — reverse-engineered from the network request — and each
result's detail page is server-rendered HTML with Dublin Core `<meta>` tags
embedded in it (`DC.title`, `DC.creator`, `DC.subject`, `DC.description`,
`DC.publisher`, `DC.date`). This pipeline calls the search API for the list,
then reads those meta tags off each detail page for the full record — no
HTML scraping of the rendered page body needed.

## Setup

Requires Python 3.8+.

```bash
pip install -r requirements.txt
```

## Usage

### Keyword search with full details (title/creator/keyword/abstract/publisher/date)

```bash
python tu_dc_thesis_search.py --keyword "การตลาด" --out result.csv
```

This is the main entry point — see [Output](#output-resultcsv--resultjson)
below for the fields it writes.

Useful options:

| Flag | Purpose |
|---|---|
| `--collection-id 20` | Restrict to "Thammasat University Theses" (actual master's/doctoral theses, excludes undergraduate special projects) |
| `--year-start` / `--year-end` | Limit by publication year |
| `--max-records` | Cap how many records to fetch (useful for testing) |
| `--delay` | Seconds to wait between requests (default `0.4`) |
| `--format json` | Write JSON instead of CSV |
| `--insecure` | Skip SSL certificate verification (only if your machine has a broken cert store) |

Note: this fetches one detail page per search hit, so a large result set
takes a while — use `--max-records` while testing, and keep `--delay` at a
sane value so you don't hammer the university's server.

### List-only search (faster, list-level fields only)

If you just need list-level metadata (title, authors, degree, faculty,
cover, link — no abstract/publisher) without the per-record detail fetch,
use the lighter original script instead:

```bash
python tu_dc_thesis_api.py --keyword "การตลาด" --out theses.csv
```

## Output: `result.csv` / `result.json`

| Field | Source |
|---|---|
| `title` | `DC.title` |
| `creator` | `DC.creator` (all authors, joined with `; `) |
| `keyword` | `DC.subject` (all subject/keyword tags, joined with `; `) |
| `abstract` | `DC.description` — not every record has one (older or undergraduate-project records often lack it) |
| `publisher` | `DC.publisher` |
| `date_of_issue` | `DC.date` |
| `link` | The record's detail page URL |

## Files

| File | Role |
|---|---|
| [tu_dc_thesis_search.py](tu_dc_thesis_search.py) | Main pipeline: search API → per-record detail page → DC meta tag extraction |
| [tu_dc_thesis_api.py](tu_dc_thesis_api.py) | Lighter, list-only search (no per-record detail fetch, no abstract/publisher) |

## Claude Code skill

This repo also ships a project skill at
[`.claude/skills/tu-dc-thesis-search/SKILL.md`](.claude/skills/tu-dc-thesis-search/SKILL.md).
Inside Claude Code, opened on this repo, just ask for what you want:

```
find theses about การตลาด from 2020-2023
```
```
search for theses on พฤติกรรมผู้บริโภค, only real master's/PhD theses, give me the top 20
```

Claude Code picks this up automatically, runs `tu_dc_thesis_search.py` with
the right flags, and reads back the results for you.

## Disclaimer

This calls an internal API that TU Digital Collections' own frontend uses,
not a documented public API — if the site changes its structure, this may
need to be updated. Be a good citizen: keep `--delay` reasonable and don't
run unbounded bulk jobs against the university's server.
