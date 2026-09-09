# Channel3 Product Extraction Take-Home

This project converts raw product-detail-page HTML into validated product data and presents the resulting catalog in a small web application. The backend collects evidence without retailer-specific rules, uses structured AI responses to hydrate the supplied Pydantic schema, validates categories against Google's Product Taxonomy, and writes a JSON catalog. A read-only FastAPI service exposes that catalog to a React application with catalog and product-detail pages.

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

Source URLs are optional. When relative URLs in an HTML snapshot need an external base URL and the page does not provide a canonical URL, pass a JSON manifest that maps filenames to source URLs with `--manifest path/to/manifest.json`. The manifest supplies URL context only; it never changes how a page is parsed.

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

The deterministic pass reads common HTML structures such as metadata, JSON-LD, embedded JSON, visible text, `srcset`, image elements, and video fields. It deliberately gathers broad evidence without deciding which facts belong to the main product. The next stage recursively selects product-related records, removes duplicates, limits strings and collections, and enforces an overall serialized-character budget before any AI call.

The extraction model returns a typed draft containing media identifiers rather than CDN URLs. Application code maps those identifiers back to the exact URLs found in the HTML, preventing rewritten or invented media links. A local lexical search produces a bounded taxonomy shortlist, and a second structured call must select one of those exact categories before Pydantic validates it. Variants contain complete option configurations only when the evidence connects those values; the pipeline does not generate combinations from independent option lists.

The implementation remains generic: it uses standard markup and semantic field names, never branches on a retailer or domain, and includes no examples from the supplied pages in its prompts. Site-specific observations are kept out of runtime code. New HTML files can be processed without adding selectors, source manifests, or retailer rules.

## Known limitations

- Input is saved HTML. Pages that keep essential product state exclusively behind later browser requests may need a rendering or capture step before this pipeline.
- Structured AI extraction can vary between runs, even though its output shape and final values are validated. Production use would require extraction-version tracking and ongoing quality evaluation.
- Taxonomy retrieval uses an in-process lexical scan of the taxonomy. It is suitable for this dataset but would benefit from a prebuilt semantic index at larger scale.
- The checked-in catalog is a snapshot and does not provide live price or inventory. Conditional member and coupon prices are not substituted for an ordinary public selling price.
- The API loads the entire catalog into one process and does not provide search or pagination.

## System design

To grow from five snapshots to 50 million products, I would store raw HTML and fetch metadata in object storage, then submit idempotent jobs to a durable queue. Horizontally scaled stateless workers would handle fetching, deterministic parsing, AI extraction, validation, and indexing as separate stages, so each stage could scale and retry independently. A canonical URL and content hash would provide deduplication and let unchanged pages skip extraction; live crawlers would also enforce per-domain rate limits. Transient failures would receive bounded retries with backoff, while persistent failures would move to a dead-letter queue for inspection. Model routing could send simple, well-structured pages to cheaper models and reserve stronger models for sparse or conflicting evidence, with bounded prompts controlling both cost and latency. Every schema, prompt, model configuration, and extraction would be versioned, and quality monitoring would combine validation rates, field-level drift, source coverage, cost, and sampled human review. Updates would be incremental and prioritized by expected price or inventory volatility rather than repeatedly processing all 50 million pages. Validated products would be written to a transactional source of truth and a search index designed for catalog serving. The take-home's local files, single command, in-memory catalog, and synchronous full regeneration are convenient for five products but would not support that workload.

For agentic shopping clients, I would provide product search with structured filters and cursor pagination, product-detail lookup, and variant-level price, availability, and delivery lookups. Stable product and variant identifiers would accompany provenance, extraction version, and freshness timestamps so an agent could judge whether a value should be refreshed before acting. Batch lookup endpoints would reduce round trips, while webhooks or a change feed would notify clients about price and inventory changes. The API contract would be published as OpenAPI and used to generate typed Python and TypeScript clients. I would also publish small tool schemas designed for agent function calling, including search, compare, resolve-variant, and refresh-availability operations. A sandbox catalog, example applications, and request/response fixtures would let developers test shopping flows without touching live inventory or checkout systems.
