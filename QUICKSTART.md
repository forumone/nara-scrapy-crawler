# Quickstart

Minimal commands to confirm the crawler works on your machine. Two of the
simplest sites: `open_obama_whitehouse` (no sitemap, single fused spider)
and `clintonwhitehouse1` (sitemap-based, single fused spider).

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## open_obama_whitehouse

Single spider, harvests + scrapes in one pass, a few hundred pages.

```bash
scrapy crawl open_obama_whitehouse
```

Writes `data/open.obamawhitehouse/open.obamawhitehouse_harvest.csv` and
`data/open.obamawhitehouse/open.obamawhitehouse.csv`.

## clintonwhitehouse1

Sitemap-based, one command — fetches the sitemap and scrapes every page in
the same run.

```bash
scrapy crawl clintonwhitehouse1
```

Writes `data/clintonwhitehouse1/clintonwhitehouse1_harvest.csv` and
`data/clintonwhitehouse1/clintonwhitehouse1.csv`.

If both produce a non-empty `.csv` with real title/body content, the
environment is set up correctly. See README.md and HARVESTING.md for the
full picture.

## Indexing pipeline

Once a site has a `.csv`, try the interactive wrapper around the
validate/filter/convert/reconcile pipeline — prompts for site, mode
(`index`/`crawl`/`crawl-and-index`), and any overrides (CSV/JSONL paths,
crawl throttle, log file), then shows and confirms the command before
running it:

```bash
./scrape_index_pipeline_interactive
```

See README.md's "Indexing Pipeline" section for the non-interactive
`scrape_index_pipeline` CLI and what each mode/flag does.
