# Channel3 Product Extraction Take-Home

This project turns raw HTML from product pages into structured, validated product data. It collects useful evidence from each page, asks an AI model to organize that evidence into the provided Pydantic schema, and checks the result against Google's Product Taxonomy. The extracted products are saved as JSON, served through a small FastAPI API, and displayed in a React catalog and product detail page.

The repository includes five HTML snapshots in `data/` and checked-in product output, so the API and frontend can be reviewed without making new AI calls.

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20.19+ or 22.12+ and npm
- An OpenRouter API key only when regenerating product data

## Setup

Install the Python dependencies:

```bash
uv sync
```

Create the local environment file:

```bash
cp .env.example .env
```

Add the provided key to `.env`:

```dotenv
OPEN_ROUTER_API_KEY=your-key-here
```

`.env` is ignored by Git and must not be committed.

Install the frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

## Generate the product catalog

From the repository root, process every `.html` file in `data/`:

```bash
uv run python main.py ingest
```

The command writes one validated file per product and a combined catalog to `output/products/`. It processes files concurrently, preserves successful results when another input fails, reports usage per product and model, and exits with a nonzero status if any extraction fails.

The defaults can be changed when evaluating other HTML files:

```bash
uv run python main.py ingest --input-dir data --output-dir output/products --concurrency 2
```

Source URLs are optional. If a snapshot contains relative URLs and does not include its own canonical URL, `--manifest path/to/manifest.json` can provide a JSON mapping from filenames to their original URLs. The manifest is only used to resolve URLs; it does not change the extraction logic.

Regenerating the catalog makes paid OpenRouter requests. The checked-in catalog can be served directly when regeneration is unnecessary.

## Run the application

Start the API from the repository root:

```bash
uv run uvicorn api:app --reload
```

The API is available at `http://127.0.0.1:8000`:

- `GET /api/health`
- `GET /api/products`
- `GET /api/products/{product_id}`

In another terminal, start the frontend:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` requests to the local FastAPI server. The catalog route is `/`, and each card links to `/products/{product_id}`.

## Tests and build

Run the backend tests from the repository root:

```bash
uv run pytest
```

Run the frontend tests and production build:

```bash
cd frontend
npm run test
npm run build
```

## Project structure

| Path | Purpose |
| --- | --- |
| `models.py` | Pydantic contracts for evidence, AI drafts, variants, products, and API responses |
| `extraction.py` | Deterministic collection of text, metadata, structured data, images, and videos from raw HTML |
| `evidence.py` | Selection and size-bounding of product evidence, including stable media identifiers |
| `hydrate.py` | Structured AI extraction, variant recovery, taxonomy resolution, and final product construction |
| `ai.py` | OpenRouter client wrapper and per-call and cumulative usage accounting |
| `ingestion.py` / `main.py` | Concurrent batch ingestion, atomic JSON output, and the command-line interface |
| `product_store.py` / `api.py` | Validated in-memory catalog and read-only FastAPI endpoints |
| `output/products/` | Checked-in individual products and the combined catalog |
| `frontend/` | React, TypeScript, and Vite catalog and product-detail application |
| `tests/` | Backend unit, integration, API, fixture, and regression tests |

## Extraction architecture

```text
raw HTML
  -> broad deterministic evidence collection
  -> bounded product evidence
  -> structured AI extraction
  -> taxonomy resolution and Pydantic validation
  -> JSON product catalog
  -> FastAPI
  -> React catalog and product detail page
```
<img width="658.5" height="991.5" alt="Extraction Architecture" src="https://github.com/user-attachments/assets/57bb074a-9dab-421b-9953-0a28634db00a" />

The first pass collects anything that might describe the product: metadata, JSON-LD, embedded JSON, visible text, images from `srcset` and other image attributes, and video URLs. It intentionally does not try to decide which candidate is correct yet. The next step keeps the records that look most useful for a product, removes duplicates, and limits both individual fields and the total payload. This keeps large application-state objects from making every AI request unnecessarily expensive.

The model returns a typed product draft. For media, it selects short identifiers such as `IMG_0001` instead of copying long CDN URLs. The application then maps those identifiers back to the exact URLs collected from the page, so a model cannot accidentally rewrite a URL. Category selection is handled separately: the application searches the taxonomy locally, sends a short list of plausible categories to a second AI call, and requires the model to choose one of them exactly. Pydantic performs the final validation.

Variants represent complete configurations only when the page connects the option values. For example, a color and size can be stored together when the evidence ties both to the same SKU. If a page only lists colors and sizes independently, the code does not assume that every possible combination exists.

The extractor is designed to work across sites. It relies on common HTML structures and product-related field names rather than retailer names, domains, or selectors written for these snapshots. The prompts also contain no examples or facts from the supplied pages. New HTML files can go through the same pipeline without adding a site-specific branch.

## Known limitations

- Input is saved HTML. Pages that keep essential product state exclusively behind later browser requests may need a rendering or capture step before this pipeline.
- Structured AI extraction can vary between runs, even though its output shape and final values are validated. Production use would require extraction-version tracking and ongoing quality evaluation.
- Taxonomy retrieval uses an in-process lexical scan of the taxonomy. It is suitable for this dataset but would benefit from a prebuilt semantic index at larger scale.
- The checked-in catalog is a snapshot and does not provide live price or inventory. Conditional member and coupon prices are not substituted for an ordinary public selling price.
- The API loads the entire catalog into one process and does not provide search or pagination.

## System design

At 50 million products, I would replace the local batch process with a pipeline built around object storage and a durable queue. A crawler would save the raw HTML and fetch metadata, then enqueue a job for a fleet of stateless workers. Fetching, parsing, AI extraction, validation, and search indexing would be separate stages so they could scale and retry independently. Jobs would be idempotent, and a hash of the page content would let us skip AI extraction when a page has not changed. Live crawlers would limit requests per domain, temporary failures would get a small number of retries with backoff, and repeated failures would move to a dead-letter queue for investigation. I would route clean, structured pages to cheaper models and reserve stronger models for sparse or conflicting pages, while continuing to cap prompt sizes. Schemas, prompts, model settings, and outputs would all be versioned so we could trace a bad result and reprocess only the affected products. I would monitor validation failures, field coverage, cost, and changes in output quality, with people reviewing a sample of results. Products would be refreshed based on how often their price or inventory changes instead of rerunning all 50 million at once, then stored in a durable database and search index. The local files, single process, in-memory API, and full batch regeneration used here are practical for five products, but none of them would be enough at that scale.

Product updates would be incremental, following this flow:
<img width="684.2" height="813" alt="system design diagram" src="https://github.com/user-attachments/assets/f33918b4-e292-40fc-a4d5-a162bcf2f083" />


For agentic shopping clients, I would provide product search with structured filters and cursor pagination, product-detail lookup, and variant-level price, availability, and delivery lookups. Stable product and variant identifiers would accompany provenance, extraction version, and freshness timestamps so an agent could judge whether a value should be refreshed before acting. Batch lookup endpoints would reduce round trips, while webhooks or a change feed would notify clients about price and inventory changes. The API contract would be published as OpenAPI and used to generate typed Python and TypeScript clients. I would also publish small tool schemas designed for agent function calling, including search, compare, resolve-variant, and refresh-availability operations. A sandbox catalog, example applications, and request/response fixtures would let developers test shopping flows without touching live inventory or checkout systems.
