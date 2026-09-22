---
name: tu-dc-thesis-search
description: Search Thai theses / research works from TU Digital Collections (digital.library.tu.ac.th) by keyword using the pipeline in this repo, and return title, creator, keyword, abstract, publisher, and date of issue for each match. Use this whenever the user asks to find, search, or look up theses/papers/research from Thammasat University, TU Digital Collections, or digital.library.tu.ac.th, or asks to run tu_dc_thesis_search.py.
---

# TU Digital Collections thesis search

This skill drives `tu_dc_thesis_search.py` in this repo, which searches TU
Digital Collections by keyword and fetches title/creator/keyword/abstract/
publisher/date-of-issue for each result.

## Precondition

No authentication needed — the target API is public. `pip install -r
requirements.txt` (just `requests`) if not already installed.

## Step 1: Run the search

```bash
python tu_dc_thesis_search.py --keyword "<keyword>" --out data/result.csv
```

- `<keyword>` — the user's search term, Thai or English, as given (or your
  best extraction from their request). Quote it.
- Add `--collection-id 20` when the user wants only real master's/doctoral
  theses (excludes undergraduate special projects, which is collection 13).
  Default (no `--collection-id`) covers the whole "Research & Thesis" group.
- Add `--year-start` / `--year-end` if the user specifies a year range.
- Add `--max-records N` for a quick/bounded look, or when the user asks for
  "the top N" results — this also keeps the run fast, since one HTTP
  request is made per result to fetch its detail page.
- Use `--format json` if the user wants JSON instead of CSV.
- If a run fails with an SSL error, retry with `--insecure`.

Write output under `data/` (gitignored) unless the user names a different
path.

## Step 2: Read the results back

Read the output file and present it back to the user — as a table, list, or
whatever fits the request. Each record has: `title`, `creator`, `keyword`,
`abstract`, `publisher`, `date_of_issue`, `link`.

Note: not every record has an `abstract` — older records or some
collections don't have one populated. Don't treat a blank abstract as an
error.

## Notes

- This calls TU Digital Collections' internal search API plus its
  server-rendered detail pages (Dublin Core meta tags), not a documented
  public API. If a run starts failing outright (not just missing fields),
  the site may have changed structure — flag this to the user rather than
  guessing at a fix.
- Keep the default `--delay` (0.4s) for anything but small/test runs — this
  hits a university server, not a CDN.
