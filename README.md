# Soundgraph

Soundgraph is a music recommendation system based on similarity between album tags. You provide between 1 and 5 favorite albums/artists as "seeds", and the system can do two things:

- **Recommend albums**: it builds a pool of candidate albums (top albums of each seed's similar artists), scores them with TF-IDF cosine similarity over their tags (Last.fm), and returns a list ordered by score. The higher the cosine with a seed, the higher the "possible taste" score (0–100). Each recommendation shows every seed it shares tags with and its per-seed score.
- **Find a bridge artist**: it runs a multi-source BFS over the Last.fm "similar artists" graph between 2 and 5 seed artists, searching for an artist that connects them all. The search is visualized live in an affinity graph while it expands, and the seed → bridge paths are shown once found.

The system also detects whether an album is "atypical" within its artist's discography (distance to the artist's TF-IDF tag centroid).

Tag data comes from Last.fm (`album.getinfo`, falling back to `album.gettoptags`). Genres/styles already cached from Discogs are kept but are no longer fetched.

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
  `seeds` must have between 1 and 5 items and `n_results` must be between 1 and 5.
  Returns a list of `{"artist", "album", "score", "matched_seed", "matched_seeds"}` where `score` is the maximum TF-IDF cosine against any seed expressed as a 0–100 percentage, `matched_seed` is the best-matching seed, and `matched_seeds` lists every seed the album shares tags with (each with its own 0–100 score). Candidates with no tag overlap are dropped.
- `GET /api/artists/{id}/atypical-albums/`
  Returns the albums of an artist ordered from most to least atypical, with the distance to the centroid.
- `POST /api/connections/`
  Body: `{"seed_artists": ["Eminem", "Opeth"]}` (between 2 and 5 artist names). Starts a multi-source BFS over the Last.fm similar-artists graph in a background thread looking for a bridge artist. Returns `202` with `{"search_id", "status"}`.
- `GET /api/connections/{search_id}/`
  Live progress of a search: `{status, current_depth, max_depth, bridge_artist, seed_artists, visited_per_seed, frontier_per_seed, came_from}`; adds `path` when `status="found"` or `error_message` when `status="failed"`. Statuses: `pending`, `running`, `found`, `exhausted`, `failed`.

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
   - `DISCOGS_TOKEN`: your Discogs API token (optional; Discogs is currently disabled).
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
3. The affinity graph shows the search expanding live (the frontier is polled every second): each seed's branches have its own color. Once found, the bridge artist is highlighted and the seed → bridge paths are listed below the graph.

## Configuration notes

- Vite proxies `/api` to the Django server. If your Django server runs on a different host/port, update `frontend/vite.config.js`.
- CORS is already configured in `soundgraph/settings.py` (`CORS_ALLOWED_ORIGINS`) for `localhost:3000` and `localhost:5173`.
- Albums cached without tags (e.g. before the `album.gettoptags` fallback existed) are refetched automatically on the next request.