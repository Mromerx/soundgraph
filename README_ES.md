# SoundGraph

SoundGraph es una herramienta de descubrimiento musical que explora el **grafo de artistas de Last.fm**. Le das algunos álbumes o artistas que te gustan ("semillas") y encuentra música nueva y conexiones ocultas de dos maneras:

- **Recomendación de álbumes.** Arma un pool de álbumes candidatos (álbumes top de los artistas similares a cada semilla), los puntúa contra cada semilla con similitud coseno TF-IDF sobre los tags de Last.fm y devuelve la lista ordenada por un score de "posible gusto" de 0 a 100. Cada recomendación muestra todas las semillas con las que comparte tags y su score por semilla.
- **Búsqueda de artista puente.** Corre un BFS multi-fuente sobre el grafo de "artistas similares" de Last.fm entre 2 y 5 artistas semilla para encontrar un único **artista puente** que los conecte a todos. La exploración se visualiza en vivo como un grafo de afinidad y, al encontrarse, se muestran los caminos semilla → puente.

También detecta **álbumes atípicos**: cada álbum de un artista se ordena según su distancia coseno al centroide TF-IDF de los tags del artista.

Los tags provienen exclusivamente de la API de Last.fm.

## Stack

- **Backend:** Django + Django REST Framework, PostgreSQL, scikit-learn (TF-IDF / similitud coseno)
- **Frontend:** React + react-force-graph (Vite)

## Estructura del proyecto

```
.
├── catalog/               # App de Django
│   ├── models.py          # Artist, Album, AlbumSimilarity, ConnectionSearch
│   ├── serializers.py     # Serializers de entrada/salida + validación de rangos
│   ├── views.py           # Endpoints REST (recomendaciones, búsquedas, conexiones)
│   ├── urls.py            # Rutas de catalog
│   ├── memory_guard.py    # Tope de RAM a nivel proceso (POSIX)
│   └── services/          # Cliente de Last.fm, caché, similitud, BFS de puente, bus de SSE
├── frontend/              # Frontend React (Vite)
│   └── src/
│       ├── api/           # soundgraph.js, connections.js
│       └── components/    # SeedSelector, RecommendationsList, ConnectionSearchPanel,
│                          # GraphView, comboboxes
├── soundgraph/            # Proyecto Django (settings, URLs raíz)
├── manage.py
├── requirements.txt
└── .env.example
```

## Inicio rápido

### Requisitos previos

- Python 3.10+
- Node.js 18+ y npm
- **PostgreSQL corriendo.** La base se consulta en cada request, así que el servicio tiene que estar levantado **antes** de correr `migrate`, `runserver` o los tests. Verifica con `pg_isready -h localhost -p 5432`. Si el servicio está caído, levántalo en:

  - Linux: `sudo systemctl start postgresql` (o `sudo service postgresql start`)
  - Windows: abre el administrador de **Servicios** y arranca `postgresql-x64-<versión>`

### Backend

**Linux**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Crea la base de datos y el usuario (ajústalo a tu .env):
sudo -u postgres psql -c "CREATE USER soundgraph WITH PASSWORD 'soundgraph';"
sudo -u postgres psql -c "CREATE DATABASE soundgraph OWNER soundgraph;"

# Configura el entorno
cp .env.example .env   # después edita LASTFM_API_KEY y DB_* según tu setup

# Ejecútalo
python manage.py migrate
python manage.py runserver   # API en http://localhost:8000/api/
```

**Windows** (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Crea la base de datos y el usuario (ajústalo a tu .env):
psql -U postgres -c "CREATE USER soundgraph WITH PASSWORD 'soundgraph';"
psql -U postgres -c "CREATE DATABASE soundgraph OWNER soundgraph;"

# Configura el entorno
Copy-Item .env.example .env   # después edita LASTFM_API_KEY y DB_* según tu setup

# Ejecútalo
python manage.py migrate
python manage.py runserver   # API en http://localhost:8000/api/
```

Se requiere una **API key de Last.fm** (`LASTFM_API_KEY` en `.env`): todas las funciones obtienen sus datos de Last.fm. La consigues en https://www.last.fm/api.

### Frontend

En una segunda terminal:

```bash
cd frontend
npm install --allow-git=all   # react-force-graph trae una dependencia git; npm 12 las bloquea por defecto
npm run dev                   # app en http://localhost:5173/
```

El servidor de desarrollo de Vite hace proxy de `/api` al servidor de Django en `http://localhost:8000`, así el frontend llama al backend de forma transparente. CORS para `localhost:3000`/`localhost:5173` ya está configurado en `soundgraph/settings.py`.

## Configuración

Toda la configuración vive en `.env` (ver `.env.example`):

| Variable | Default | Descripción |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | — | Clave secreta de Django (cualquier cadena). |
| `DEBUG` | `False` | `True` para desarrollo. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts permitidos separados por coma. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | `soundgraph`, `5432` | Datos de conexión a PostgreSQL. |
| `LASTFM_API_KEY` | — | **Requerida.** API key de Last.fm. |
| `SOUNDGRAPH_NODE_LIMIT` | `50000` | Tope de artistas distintos que el BFS de puente puede descubrir en total. La frontera crece ~10x por nivel; esto acota memoria/CPU. Al alcanzarlo la búsqueda termina en `exhausted` (`stopped_reason="node_limit"`). |
| `SOUNDGRAPH_MAX_CONCURRENT_SEARCHES` | `1` | Máximo de búsquedas de puente en paralelo (cada BFS mantiene todo su estado en RAM). `0` lo desactiva. |
| `SOUNDGRAPH_MEMORY_LIMIT_MB` | `4096` | Tope duro de RAM para todo el proceso vía `resource.setrlimit` (POSIX). Si se excede, la búsqueda falla limpio con `status="failed"` en vez de tumbar el servidor. `0` lo desactiva. |
| `SOUNDGRAPH_STALE_SEARCH_SECONDS` | `60` | Una búsqueda `pending`/`running` sin actividad por este tiempo se considera zombi (ej. servidor reiniciado a mitad de corrida) y se expira con `status="failed"`. |
| `SOUNDGRAPH_LASTFM_RATE_PER_SECOND` | `3.8` | Requests por segundo hacia Last.fm (se mantiene ~5% por debajo del tope de 4/s del plan para evitar 429). Todos los flujos comparten este único limiter. |

## Endpoints del backend

Todos los endpoints viven bajo `/api/`.

| Método y ruta | Descripción |
| --- | --- |
| `GET /api/search/artists/?q=` | Autocompletado de artistas contra Last.fm. Devuelve `{"results": [{"name", "mbid", "listeners"}]}`. |
| `GET /api/search/albums/?artist=` | Álbumes top de un artista. Devuelve `{"results": [{"title", "mbid"}]}`. |
| `POST /api/recommendations/` | Recomendación de álbumes. Body: `{"seeds": [{"artist": "...", "album": "..."}], "n_results": 5}` — 1 a 5 semillas, `n_results` de 1 a 15. Devuelve `[{"artist", "album", "score", "matched_seed", "matched_seeds"}]`; `score` es el máximo coseno TF-IDF contra cualquier semilla expresado como porcentaje 0-100, y `matched_seeds` lista todas las semillas con las que el álbum comparte tags. Los candidatos sin solapamiento de tags se descartan. |
| `GET /api/artists/{id}/atypical-albums/` | Álbumes de un artista ordenados de más a menos atípicos (distancia coseno al centroide de tags del artista). |
| `POST /api/connections/` | Inicia una búsqueda de puente. Body: `{"seed_artists": ["A", "B", ...]}` (2 a 5 nombres). Devuelve `202` con `{"search_id", "status"}`. |
| `GET /api/connections/{search_id}/` | Progreso en vivo: `{status, current_depth, max_depth, bridge_artist, total_discovered, ...}` con datos muestreados del grafo (`visited_per_seed`, `frontier_per_seed`, `came_from`). Agrega `path` cuando `status="found"`, `error_message` cuando `status="failed"`. Estados: `pending`, `running`, `paused`, `found`, `exhausted`, `failed`, `stopped`. `?graph=full` devuelve el grafo explorado completo en vez del payload muestreado. Soporta revalidación por ETag/304 mientras el estado no cambia. |
| `PATCH /api/connections/{search_id}/` | Controla una búsqueda en curso. Body: `{"action": "pause" \| "resume" \| "stop"}`. |
| `GET /api/connections/{search_id}/events` | Stream SSE del progreso de la búsqueda — un evento por artista descubierto, se cierra solo al llegar a un estado final. |

## Uso

**Recomendaciones:** agrega entre 1 y 5 álbumes semilla (escribe un artista para el autocompletado, elige uno de sus álbumes), indica cuántos resultados quieres y presiona "Recomendar". Cada resultado muestra su "Posible gusto: N%" y las semillas con las que conecta.

**Búsqueda de conexión:** agrega al menos 2 artistas semilla y presiona "Buscar conexión entre estos artistas". El grafo de afinidad se expande en vivo (cada rama lleva el color de su semilla); al encontrar el puente, se resalta el artista puente y se listan los caminos semilla → puente. El botón **"Ver grafo completo"** pide el grafo explorado completo (`?graph=full`) y renderiza todos los artistas visitados; **"Ver grafo simplificado"** vuelve a la vista de caminos.

## Cómo la búsqueda de puente se mantiene a salvo

El grafo de similitud de Last.fm crece exponencialmente, así que la búsqueda corre con varias salvaguardas para que nunca tumbe el servidor:

- **Tope de nodos** — la expansión corta en `SOUNDGRAPH_NODE_LIMIT` (default 50k) y cierra como `exhausted` en vez de explotar.
- **Guard de concurrencia** — a lo sumo `SOUNDGRAPH_MAX_CONCURRENT_SEARCHES` hilos de BFS corriendo a la vez (default 1).
- **Tope de RAM del proceso** — `resource.setrlimit` (POSIX) capa la memoria de todo el proceso (`SOUNDGRAPH_MEMORY_LIMIT_MB`); un `MemoryError` termina la búsqueda como `failed`, no al servidor.
- **Anti-zombis** — el BFS corre en un hilo daemon y emite un heartbeat mientras trabaja; si el servidor muere a mitad de corrida, la fila clavada se expira como `failed` la próxima vez que alguien interactúe con el backend (o al reiniciar), sin bloquear nunca el slot de concurrencia.
- **Rate limiting** — un único throttle global espacia cada llamada a Last.fm a ~`SOUNDGRAPH_LASTFM_RATE_PER_SECOND` req/s, con reintentos acotados en 429/502/503.
- **Progreso en vivo sin overhead de poll** — el estado se persiste por nivel y se versiona (`payload_revision`). El endpoint SSE publica cada artista nuevo apenas se descubre; el frontend cae en un poll barato con ETag/304 como respaldo. El payload muestreado mantiene chica cada respuesta de estado aunque se hayan descubierto decenas de miles de artistas.

La lógica central del BFS vive en `catalog/services/connection_search.py` (`expand_one_level`, `find_intersection`, `reconstruct_path`), el motor de recomendación en `catalog/services/similarity.py` y la capa cache-first de Last.fm en `catalog/services/cache.py` — todas con docstrings detallados.

## Tests

```bash
python manage.py test catalog
```

Los tests mockean el cliente de Last.fm y la capa de caché, así que corren sin conexión.