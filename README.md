# Soundgraph

Soundgraph is a music recommendation system based on similarity between album tags. You provide between 1 and 5 favorite albums/artists as "seeds", and the system can do two things:

- **Recommend albums**: it builds a pool of candidate albums (top albums of each seed's similar artists), scores them with TF-IDF cosine similarity over their tags (Last.fm), and returns a list ordered by score. The higher the cosine with a seed, the higher the "possible taste" score (0–100). Each recommendation shows every seed it shares tags with and its per-seed score.
- **Find a bridge artist**: it runs a multi-source BFS over the Last.fm "similar artists" graph between 2 and 5 seed artists, searching for an artist that connects them all. The search is visualized live in an affinity graph while it expands, and the seed → bridge paths are shown once found.

The system also detects whether an album is "atypical" within its artist's discography (distance to the artist's TF-IDF tag centroid).

Tag data comes exclusively from Last.fm (`album.getinfo`, falling back to `album.gettoptags`).

## Stack

- Backend: Django + Django REST Framework (DRF), PostgreSQL, scikit-learn
- Frontend: React + react-force-graph (Vite)

## Project layout

```
.
├── catalog/               # Django app
│   ├── models.py          # Artist, Album, AlbumSimilarity, ConnectionSearch
│   ├── serializers.py     # Request/response serializers + range validation
│   ├── views.py           # REST endpoints (recommendations, search, connections)
│   ├── urls.py            # catalog routes
│   └── services/          # Last.fm client, cache, similarity, bridge search (BFS)
├── frontend/              # React frontend (Vite)
│   ├── vite.config.js     # proxies /api to the Django dev server
│   └── src/
│       ├── api/           # soundgraph.js, connections.js
│       └── components/    # SeedSelector, ResultCountSelector, RecommendationsList,
│                          # ConnectionSearchPanel, GraphView, comboboxes
├── manage.py
├── requirements.txt
└── .env.example
```

## Backend endpoints

- `GET /api/search/artists/?q=<query>`
  Artist autocomplete (Last.fm). Returns `{"results": [{"name", "mbid", "listeners"}]}`.
- `GET /api/search/albums/?artist=<name>`
  Album list for the chosen artist. Returns `{"results": [{"title", "mbid"}]}`.
- `POST /api/recommendations/`
  Body: `{"seeds": [{"artist": "Spiritbox", "album": "Eternal Blue"}, ...], "n_results": 5}`
  `seeds` must have between 1 and 5 items and `n_results` must be between 1 and 15.
  Returns a list of `{"artist", "album", "score", "matched_seed", "matched_seeds"}` where `score` is the maximum TF-IDF cosine against any seed expressed as a 0–100 percentage, `matched_seed` is the best-matching seed, and `matched_seeds` lists every seed the album shares tags with (each with its own 0–100 score). Candidates with no tag overlap are dropped.
- `GET /api/artists/{id}/atypical-albums/`
  Returns the albums of an artist ordered from most to least atypical, with the distance to the centroid.
- `POST /api/connections/`
  Body: `{"seed_artists": ["Eminem", "Opeth"]}` (between 2 and 5 artist names). Starts a multi-source BFS over the Last.fm similar-artists graph in a background thread looking for a bridge artist. Returns `202` with `{"search_id", "status"}`.
- `GET /api/connections/{search_id}/`
  Live progress of a search: `{status, current_depth, max_depth, bridge_artist, seed_artists, visited_per_seed, frontier_per_seed, came_from}`; adds `path` when `status="found"` or `error_message` when `status="failed"`. Statuses: `pending`, `running`, `found`, `exhausted`, `failed`. With `?graph=full` it returns the **complete** explored graph (full `visited_per_seed`/`frontier_per_seed`/`came_from`, unsampled) to visualize the whole search that led to the bridge; by default the payload is compact (sampled) and the GET supports ETag revalidation (`If-None-Match`): while the search state does not change it answers `304` without re-serializing the payload.
- `GET /api/connections/{search_id}/events`
  SSE stream (`text/event-stream`) of a search's progress. Emits a `data: {payload}` event on every state change (artist discovered, level boundary, pause, resume, stop, or a final status): one event per artist, so spheres appear one by one — artists returned together by a single API response are published back to back (they were discovered at once). Every event carries the graph samples so the frontend draws the exploration growing live. The stream closes when a final status arrives. The bus lives in memory, so with `runserver` the actual BFS thread publishes and the frontend renders the bridge "instantly"; the ETag/304 poll remains as fallback.

## Prerequisites

- Python 3.10 or later
- Node.js 18 or later and npm
- PostgreSQL running locally

## Dependencies

### Python

```bash
pip install -r requirements.txt
```

### Node.js

The `react-force-graph` package pulls in a dependency hosted on GitHub. npm 12 disables git dependencies by default, so the install must allow them:

```bash
cd frontend
npm install --allow-git=all
```

## Configuration

1. Copy the environment template:

   Linux:
   ```bash
   cp .env.example .env
   ```

   Windows (PowerShell):
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and fill in your values:

   - `DJANGO_SECRET_KEY`: any secret string.
   - `DEBUG`: `True` for development.
   - `DJANGO_ALLOWED_HOSTS`: `localhost,127.0.0.1`.
   - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: PostgreSQL connection settings. Adjust these to match the database you create in the next section.
   - `LASTFM_API_KEY`: your Last.fm API key (optional for development).

## Setting up PostgreSQL

Create the database and user used by the app. Adjust the commands to match the credentials in your `.env`.

Linux (psql):
```bash
sudo -u postgres psql -c "CREATE USER soundgraph WITH PASSWORD 'soundgraph';"
sudo -u postgres psql -c "CREATE DATABASE soundgraph OWNER soundgraph;"
```

Windows (psql):
```psql
CREATE USER soundgraph WITH PASSWORD 'soundgraph';
CREATE DATABASE soundgraph OWNER soundgraph;
```

## Running the program

### Linux

1. Backend

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py runserver
   # the API is available at http://127.0.0.1:8000/api/
   ```

2. Frontend (in a second terminal)

   ```bash
   cd frontend
   npm install --allow-git=all
   npm run dev
   # the app is available at http://localhost:5173/
   ```

### Windows

1. Backend

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py runserver
   # the API is available at http://127.0.0.1:8000/api/
   ```

2. Frontend (in a second terminal)

   ```powershell
   cd frontend
   npm install --allow-git=all
   npm run dev
   # the app is available at http://localhost:5173/
   ```

The Vite dev server proxies `/api` to the Django server at `http://127.0.0.1:8000`, so the frontend at `http://localhost:5173/` can call the backend transparently.

## Usage

### Recommendations

1. Add between 1 and 5 seed albums: type an artist (autocomplete against Last.fm) and pick one of its albums.
2. Choose how many results to request (1 to 5) with the slider.
3. Click "Recomendar".
4. A list of recommended albums appears, each with its **Posible gusto: N%** (max TF-IDF cosine against a seed) and the seeds it connects to (`Conecta con: Artist — Album (N%)`).

### Bridge search

1. Add at least 2 seed artists (the panel appears once there are 2+).
2. Click "Buscar conexión entre estos artistas".
3. The affinity graph shows the search expanding live (progress arrives over SSE and the fallback poll is ETag-backed): each seed's branches have its own color. Once found, the bridge artist is highlighted and the seed → bridge paths are listed below the graph.
4. When the connection is found, the graph defaults to the **simplified** view (only the seed → bridge paths). The **"Ver grafo completo"** button (top-left of the graph) requests the complete explored graph with `?graph=full` and renders it: every visited artist, the final frontier and the `came_from` edges, always keeping the bridge and its ancestor chain visible. The **"Ver grafo simplificado"** button switches back to the paths view.

## Configuration notes

- Vite proxies `/api` to the Django server. If your Django server runs on a different host/port, update `frontend/vite.config.js`.
- CORS is already configured in `soundgraph/settings.py` (`CORS_ALLOWED_ORIGINS`) for `localhost:3000` and `localhost:5173`.
- Albums cached without tags (e.g. before the `album.gettoptags` fallback existed) are refetched automatically on the next request.
- `GET /api/connections/{id}/` returns a compact payload (counts plus sampled `visited_per_seed`/`frontier_per_seed`/`came_from`) and supports ETag revalidation: within the same state the endpoint answers `304` (no re-serialization) and the frontend falls back to a slow poll (2s running, 5s paused). The complete explored graph is available on demand with `?graph=full` — the "Ver grafo completo" button requests it a single time, and the frontend caps rendering at a node budget so the browser stays responsive even if the search discovered tens of thousands of artists.
- **SSE progress**: `ConnectionSearch.payload_revision` advances on every state save (which is the ETag of the GET; heartbeats never touch it). The BFS thread publishes one event per discovered artist to an in-memory bus exposed at `/api/connections/{id}/events` with the graph samples (window of the most recent discoveries), so the frontend draws the search growing artist by artist instead of only at level boundaries; the ETag/304 poll remains as a cheap fallback.

## Bridge search engine

The bridge-search logic lives in `catalog/services/connection_search.py` as
three pure functions that mutate a `ConnectionSearch` object in memory (the
caller decides when to persist; `run_full_search` saves the state after every
level):

- `expand_one_level(search, on_progress=None)`: expands ONE BFS level for all seeds.
- `find_intersection(search)`: detects an artist present in ALL visited sets.
- `reconstruct_path(search, bridge)`: builds each seed's path to the bridge.

### expand_one_level

Multi-source BFS, one level at a time: each seed keeps its own frontier and its
own visited set.

1. **Per-seed initialization**: on the first level, `visited_per_seed[seed]`
   and `frontier_per_seed[seed]` start as `[seed]`. Seeds are roots: they are
   NEVER registered as keys in `came_from` (see `reconstruct_path`); if two
   seeds discovered each other, `came_from` would grow a `S1->S2->S1` cycle
   that would hang the path reconstruction.
2. **Frontier snapshot**: for each seed, the current frontier is copied to a
   fresh list (`frontier = list(...)`). Only the artists discovered in the
   previous level are expanded; if the frontier and the visited list shared the
   same list object, a single level would flood the entire reachable component
   of the Last.fm graph.
3. **Expansion**: every frontier artist's similar artists are fetched from
   Last.fm (`SIMILAR_LIMIT = 10`) ONCE per run (in-memory `_similar_cache`).
   Names the seed already visited are skipped; new ones are added to `visited`,
   to the new frontier, and recorded as `came_from[similar] = artist` without
   overwriting a parent registered by another seed (so `came_from` keeps the
   FIRST global discovery of each artist).
4. **Node budget**: if `node_limit` is set and `total_discovered` reaches it,
   `over_limit` is flagged in memory and expansion stops; the caller closes the
   search as `exhausted` with `stopped_reason="node_limit"`.
5. The seed's new frontier becomes exactly the newly discovered artists: what is
   already visited is never re-expanded.

### find_intersection

Intersects every seed's `visited_per_seed`. Visited sets are cached in
memory-only sets (`_visited_sets`), so it uses `&` (not `&=`), which leaves the
cached sets untouched and preserves the `expand_one_level` dedupe. Returns the
alphabetically-first artist present in all seeds, or `None`. It is the cut
condition between levels: as soon as a common artist exists, the search ends in
`found` with `bridge_artist`.

### reconstruct_path

Walks `came_from` backwards from the bridge to the root seed of its chain (the
seed that discovered it):

1. If the bridge IS a seed, every seed gets `[seed]` (the bridge seed itself) or
   `[seed, bridge]`.
2. `chain` starts at the bridge and hops from child to parent
   (`current = came_from[current]`) until it reaches a seed. Seeds never have a
   parent (the `expand_one_level` rule), and by the nature of BFS a parent always
   comes from an earlier level than its child, so the chain can never loop.
3. `chain.reverse()` orders it as seed → ... → bridge. The root seed gets the
   full chain; the other seeds get `[seed, bridge]` because `came_from` only
   keeps the first discovery.
4. **Anti-cycle guard**: in case old rows with corrupt `came_from` are still in
   the database, a `seen` set breaks the loop if a node repeats; if a cycle is
   detected or the chain ends in an orphan node (root is not a seed), it falls
   back to the two-hop approximation `{seed: [seed, bridge]}` for every seed
   instead of hanging the endpoint.

> **Fixed bug (MemoryError)**: artists that look like each other (50 Cent,
> Eminem and Lil Wayne share the rap neighborhood) made the BFS discover the
> seeds themselves as "similar" and register them as `came_from` keys:
> `{Eminem: 50 Cent, 50 Cent: Eminem}`. The `reconstruct_path` loop oscillated
> between the two seeds forever, `chain.append` grew unbounded and the process
> crashed against `SOUNDGRAPH_MEMORY_LIMIT_MB` (4 GB) with a `MemoryError` on
> every `GET /api/connections/{id}/`. The fix has three layers: seeds never
> become `came_from` keys (they are roots), the walk stops at the first seed,
> and a cycle guard degrades to two-hop paths when the persisted data is
> corrupt.