# SoundGraph

SoundGraph is a music discovery tool that explores the **Last.fm artist graph**. You give it a few albums or artists you like ("seeds") and it finds new music and hidden connections in two ways:

- **Album recommendations.** It builds a pool of candidate albums (top albums of each seed's similar artists, plus the seed artist's own), scores them against every seed using TF-IDF cosine similarity over Last.fm tags, and returns them ordered by a 0–100 "posible gusto" (likely taste) score. The score blends the best single-seed match (60%) with the average overlap across all seeds (40%), and results are diversified with maximal marginal relevance (MMR) so the list doesn't end up full of N same-sounding or same-artist albums. Each recommendation shows every seed it shares tags with and its per-seed score.
- **Bridge artist search.** It runs a multi-source BFS over the Last.fm "similar artists" graph between 2 and 5 seed artists to find a single **bridge artist** that connects them all. The exploration is visualized live as an affinity graph, and the seed → bridge paths are shown once found.

It also detects **atypical albums**: each album of an artist is ranked by its cosine distance to that artist's TF-IDF tag centroid.

Tag data comes exclusively from the Last.fm API.

<img width="1259" height="813" alt="image" src="https://github.com/user-attachments/assets/9a78103c-3523-495e-aebe-6a3393c6445d" />


## Stack

- **Backend:** Django + Django REST Framework, PostgreSQL, scikit-learn (TF-IDF / cosine similarity)
- **Frontend:** React + react-force-graph (Vite)

## Project layout

```
.
├── catalog/               # Django app
│   ├── models.py          # Artist, Album, AlbumSimilarity, ConnectionSearch
│   ├── serializers.py     # Request/response serializers + range validation
│   ├── views.py           # REST endpoints (recommendations, search, connections)
│   ├── urls.py            # catalog routes
│   ├── memory_guard.py    # Process-wide RAM cap (POSIX)
│   └── services/          # Last.fm client, cache, similarity, bridge BFS, SSE bus
├── frontend/              # React frontend (Vite)
│   └── src/
│       ├── api/           # soundgraph.js, connections.js
│       └── components/    # SeedSelector, RecommendationsList, ConnectionSearchPanel,
│                          # GraphView, comboboxes
├── soundgraph/            # Django project (settings, root URLs)
├── manage.py
├── requirements.txt
└── .env.example
```

## Quick start

### Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- **PostgreSQL running.** The database is queried on every request, so the service must be up **before** running `migrate`, `runserver`, or the tests. Verify with `pg_isready -h localhost -p 5432`. If the service is down, start it on:

  - Linux: `sudo systemctl start postgresql` (or `sudo service postgresql start`)
  - Windows: open the **Services** manager and start `postgresql-x64-<version>`

### Backend

**Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create the database and user (adjust to match your .env):
sudo -u postgres psql -c "CREATE USER soundgraph WITH PASSWORD 'soundgraph';"
sudo -u postgres psql -c "CREATE DATABASE soundgraph OWNER soundgraph;"

# Configure environment
cp .env.example .env   # then edit LASTFM_API_KEY and DB_* to match your setup

# Run it
python manage.py migrate
python manage.py runserver   # API at http://localhost:8000/api/
```

**Windows** (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Create the database and user (adjust to match your .env):
psql -U postgres -c "CREATE USER soundgraph WITH PASSWORD 'soundgraph';"
psql -U postgres -c "CREATE DATABASE soundgraph OWNER soundgraph;"

# Configure environment
Copy-Item .env.example .env   # then edit LASTFM_API_KEY and DB_* to match your setup

# Run it
python manage.py migrate
python manage.py runserver   # API at http://localhost:8000/api/
```

A **Last.fm API key** is required (`LASTFM_API_KEY` in `.env`): every feature pulls its data from Last.fm. Get one at https://www.last.fm/api.

### Frontend

In a second terminal:

```bash
cd frontend
npm install --allow-git=all   # react-force-graph pulls a git dependency; npm 12 blocks git deps by default
npm run dev                   # app at http://localhost:5173/
```

The Vite dev server proxies `/api` to the Django server at `http://localhost:8000`, so the frontend can call the backend transparently. CORS for `localhost:3000`/`localhost:5173` is already configured in `soundgraph/settings.py`.

## Language

The frontend reads `VITE_LANG` from the root `.env` (Vite loads it through `envDir` in `frontend/vite.config.js`):

- `VITE_LANG=es` → interface in Spanish
- `VITE_LANG=en` → interface in English (default)

Anything else falls back to English. Pick one language for the whole UI; mixing isn't supported.

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | — | Django secret key (any random string). |
| `DEBUG` | `False` | `True` for development. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `soundgraph`, `5432` | PostgreSQL connection settings. |
| `LASTFM_API_KEY` | — | **Required.** Last.fm API key. |
| `VITE_LANG` | `en` | Language of the frontend UI: `es` (Spanish) or `en` (English). Read by Vite from the root `.env`. |
| `SOUNDGRAPH_NODE_LIMIT` | `50000` | Max distinct artists the bridge BFS may discover in total. The frontier grows ~10x per level; this caps memory/CPU. When reached the search ends as `exhausted` (`stopped_reason="node_limit"`). |
| `SOUNDGRAPH_MAX_CONCURRENT_SEARCHES` | `1` | Max bridge searches running in parallel (each BFS keeps its whole state in RAM). `0` disables the limit. |
| `SOUNDGRAPH_MEMORY_LIMIT_MB` | `4096` | Hard RAM cap for the whole process via `resource.setrlimit` (POSIX). If exceeded, the search fails cleanly with `status="failed"` instead of taking the server down. `0` disables it. |
| `SOUNDGRAPH_STALE_SEARCH_SECONDS` | `60` | A `pending`/`running` search with no activity for this long is considered a zombie (e.g. the server restarted mid-run) and is expired with `status="failed"`. |
| `SOUNDGRAPH_LASTFM_RATE_PER_SECOND` | `3.8` | Requests per second to Last.fm (kept ~5% under the 4/s plan cap to avoid 429s). All flows share this single rate limiter. |

## API endpoints

All endpoints live under `/api/`.

| Method & path | Description |
| --- | --- |
| `GET /api/search/artists/?q=` | Artist autocomplete against Last.fm. Returns `{"results": [{"name", "mbid", "listeners"}]}`. |
| `GET /api/search/albums/?artist=` | Top albums of an artist. Returns `{"results": [{"title", "mbid"}]}`. |
| `POST /api/recommendations/` | Album recommendations. Body: `{"seeds": [{"artist": "...", "album": "..."}], "n_results": 5}` — 1–5 seeds, `n_results` 1–15. Returns `[{"artist", "album", "score", "matched_seed", "matched_seeds"}]`; `score` is the max-mean blend of TF-IDF cosine against the seeds (60% best match, 40% average across all) as a 0–100 percentage, `matched_seeds` lists every seed the album shares tags with. The candidate pool includes top albums of similar artists plus the seed artist's own; results are ranked by maximal marginal relevance (diversifying sound and artist). Candidates with no tag overlap are dropped. |
| `GET /api/artists/{id}/atypical-albums/` | An artist's albums ordered from most to least atypical (cosine distance to the artist's tag centroid). |
| `POST /api/connections/` | Start a bridge search. Body: `{"seed_artists": ["A", "B", ...]}` (2–5 names). Returns `202` with `{"search_id", "status"}`. |
| `GET /api/connections/{search_id}/` | Live progress: `{status, current_depth, max_depth, bridge_artist, total_discovered, ...}` with sampled graph data (`visited_per_seed`, `frontier_per_seed`, `came_from`). Adds `path` when `status="found"`, `error_message` when `status="failed"`. Statuses: `pending`, `running`, `paused`, `found`, `exhausted`, `failed`, `stopped`. `?graph=full` returns the complete explored graph instead of the sampled payload. Supports ETag/304 revalidation while the state hasn't changed. |
| `PATCH /api/connections/{search_id}/` | Control a running search. Body: `{"action": "pause" \| "resume" \| "stop"}`. |
| `GET /api/connections/{search_id}/events` | SSE stream (Server-Sent Events) of the search's progress — one event per discovered artist, closing automatically on a final status. |

## Usage

**Recommendations:** add 1–5 seed albums (type an artist for autocomplete, pick one of its albums), choose how many results to request, and press "Recomendar". Each result shows its "Posible gusto: N%" score and the seeds it connects with.

**Bridge search:** add at least 2 seed artists and press "Buscar conexión entre estos artistas". The affinity graph expands live (each seed's branches share its color); once found, the bridge artist is highlighted and the seed → bridge paths are listed. The **"Ver grafo completo"** button requests the full explored graph (`?graph=full`) and renders every visited artist; **"Ver grafo simplificado"** returns to the paths-only view.

## How the bridge search is kept safe

The Last.fm similarity graph grows exponentially, so the search runs inside several safeguards so it can never take the server down:

- **Node budget** — expansion stops at `SOUNDGRAPH_NODE_LIMIT` (default 50k) and closes as `exhausted` instead of exploding.
- **Concurrency guard** — at most `SOUNDGRAPH_MAX_CONCURRENT_SEARCHES` BFS threads run at once (default 1).
- **Process RAM cap** — `resource.setrlimit` (POSIX) hard-caps the whole process (`SOUNDGRAPH_MEMORY_LIMIT_MB`); a `MemoryError` terminates the search as `failed`, not the server.
- **Anti-zombie** — the BFS runs in a daemon thread and emits a heartbeat while it works; if the server dies mid-run, the stuck row is expired as `failed` the next time someone interacts with the backend (or on restart), so it never blocks the concurrency slot.
- **Rate limiting** — a single global throttle paces every Last.fm call at ~`SOUNDGRAPH_LASTFM_RATE_PER_SECOND` req/s, with bounded retries on 429/502/503.
- **Live progress without poll overhead** — state is persisted per level and versioned (`payload_revision`). The SSE endpoint pushes each new artist as it is discovered; the frontend falls back to a cheap ETag/304 poll. The sampled payload keeps every status response small even after discovering tens of thousands of artists.

The core BFS logic lives in `catalog/services/connection_search.py` (`expand_one_level`, `find_intersection`, `reconstruct_path`), the recommendation engine in `catalog/services/similarity.py`, and the cache-first Last.fm layer in `catalog/services/cache.py` — each with detailed docstrings.

## Testing

```bash
python manage.py test catalog
```

Tests mock the Last.fm client and cache layer, so they run offline.
