# AI Opinion Map

An evidence-backed map of how the people shaping AI have publicly described it,
2017–2026, and how those expressed positions moved over time.

**Status: work in progress.** The visualisation currently renders a clearly
labelled *synthetic fixture* so the UI could be built while extraction was still
being validated. Real coordinates land as claim extraction runs across the corpus.

## The rule the project runs on

> Map expressed positions, not presumed ones.

No coordinate exists without a dated, linkable source containing the words that
justify it. Concretely, enforced in code rather than in prompts:

- A claim cannot be written without `supporting_text`, and that text must appear
  **verbatim** in the stored source document. Quotes that fail a substring check
  are discarded, whether a model or a human produced them.
- A document whose date is not high or medium confidence cannot produce claims.
  A wrong date is worse than a missing one: it silently moves someone to the
  wrong point in history.
- Axes are human-defined rubrics with written anchors, **not** embedding
  dimensions. Embeddings capture what text is *about*, not what position it
  takes, and projected axes cannot be labelled or defended.
- Where evidence is thin the map says so. An under-evidenced axis renders no
  coordinate at all, and the UI reports who is hidden and why.
- Events are context. Nothing in the pipeline or the generated text may claim an
  event caused a person's change of view.

## Axes

| Axis | Low (−3) | High (+3) |
| --- | --- | --- |
| X | Open model access | Closed / controlled |
| Y | Accelerate | Precaution |
| Z | Incremental | Civilization-scale ("how AGI-pilled") |
| W | Catastrophe | Abundance |
| S | Scale-maximalist | Architecture-skeptic |

Politicians are scored on X and Y only; public-opinion nodes carry no X, because
no pollster asks the public about open weights. An axis that does not apply
renders as a bar through that dimension, never as a point.

## Pipeline

```
registry -> collectors -> raw cache -> documents -> date gate
         -> claims (verbatim-checked) -> axis scores -> aggregation -> positions.json -> web
```

Collectors are sharded by host, one worker per host, with a single writer.
Raw fetches are content-addressed and never edited, so extractors can be fixed
and re-run without refetching.

## Running it

```bash
uv venv && uv pip install -r <(sed -n '/dependencies/,/]/p' pyproject.toml)
python -m pipeline.db                 # create the store
python -m collectors.probe            # check seeds resolve before trusting them
python -m collectors.crawl            # parallel crawl, host-sharded
python -m collectors.podcasts         # interviews, guest speech only
python -m pipeline.feeds              # harvest dates from RSS
python -m pipeline.redate             # date confidence gate
python -m pipeline.positions          # build positions.json
cd web && npm install && npm run dev
```

`python -m pipeline.explain --person <id> --axis <X|Y|Z|W|S> --at YYYY-MM`
prints how a single coordinate was derived, quote by quote.

## Data that is not in this repo

The fetched corpus is excluded on purpose — see `.gitignore`. The registries
list every source, so the corpus is reproducible by running the collectors.

## Portraits

Fetched from Wikimedia Commons, accepted only when the API reports a CC BY,
CC BY-SA, CC0 or public-domain licence. NC and ND licences are refused.
Attribution is stored in `data/registry/portrait_credits.json` and shown in the UI.
