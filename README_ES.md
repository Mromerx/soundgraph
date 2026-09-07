# Soundgraph

Soundgraph es un sistema de recomendacion musical basado en la similitud entre las etiquetas (tags) de los albumes. Cargas entre 1 y 5 albumes/artistas favoritos como "semilla", y el sistema puede hacer dos cosas:

- **Recomendar albumes**: arma un pool de albumes candidatos (albumes top de los artistas similares a cada semilla), los puntua con similitud coseno TF-IDF sobre sus tags (Last.fm) y devuelve una lista ordenada por score. A mayor coseno con una semilla, mayor es el score de "posible gusto" (0-100). Cada recomendacion muestra todas las semillas con las que comparte tags y su score por semilla.
- **Buscar artista puente**: corre un BFS multi-fuente sobre el grafo de "artistas similares" de Last.fm entre 2 y 5 artistas semilla, buscando un artista que los conecte a todos. La busqueda se visualiza en vivo en un grafo de afinidad mientras se expande, y al encontrarse se muestran los caminos semilla → puente.

El sistema tambien detecta si un album es "atipico" dentro de la discografia de su artista (distancia al centroide TF-IDF de sus tags).

Los tags provienen de Last.fm (`album.getinfo`, con respaldo a `album.gettoptags`). Los generos/estilos ya cacheados de Discogs se conservan pero ya no se vuelven a pedir.

## Stack

- Backend: Django + Django REST Framework (DRF), PostgreSQL, scikit-learn
- Frontend: React + react-force-graph (Vite)

## Estructura del proyecto

```
.
├── catalog/               # App de Django
│   ├── models.py          # Artist, Album, AlbumSimilarity, ConnectionSearch
│   ├── serializers.py     # Serializers de entrada/salida + validacion de rangos
│   ├── views.py           # Endpoints REST (recomendaciones, busquedas, conexiones)
│   ├── urls.py            # Rutas de catalog
│   └── services/          # Cliente de Last.fm, cache, similitud, busqueda de puente (BFS)
├── frontend/              # Frontend React (Vite)
│   ├── vite.config.js     # Proxya /api al servidor de desarrollo de Django
│   └── src/
│       ├── api/           # soundgraph.js, connections.js
│       └── components/    # SeedSelector, ResultCountSelector, RecommendationsList,
│                          # ConnectionSearchPanel, GraphView, comboboxes
├── manage.py
├── requirements.txt
└── .env.example
```

## Endpoints del backend

- `GET /api/search/artists/?q=<consulta>`
  Autocompletado de artistas (Last.fm). Devuelve `{"results": [{"name", "mbid", "listeners"}]}`.
- `GET /api/search/albums/?artist=<nombre>`
  Lista de albumes del artista elegido. Devuelve `{"results": [{"title", "mbid"}]}`.
- `POST /api/recommendations/`
  Body: `{"seeds": [{"artist": "Spiritbox", "album": "Eternal Blue"}, ...], "n_results": 5}`
  `seeds` debe tener entre 1 y 5 elementos y `n_results` debe estar entre 1 y 5.
  Devuelve una lista de `{"artist", "album", "score", "matched_seed", "matched_seeds"}` donde `score` es el maximo coseno TF-IDF contra cualquier semilla expresado como porcentaje 0-100, `matched_seed` es la semilla con mejor match, y `matched_seeds` lista todas las semillas con las que el album comparte tags (cada una con su score 0-100). Los candidatos sin solapamiento de tags se descartan.
- `GET /api/artists/{id}/atypical-albums/`
  Devuelve los albumes de un artista ordenados de mas a menos atipicos, con la distancia al centroide.
- `POST /api/connections/`
  Body: `{"seed_artists": ["Eminem", "Opeth"]}` (entre 2 y 5 nombres de artistas). Dispara un BFS multi-fuente sobre el grafo de artistas similares de Last.fm en un thread de background, buscando un artista puente. Devuelve `202` con `{"search_id", "status"}`.
- `GET /api/connections/{search_id}/`
  Progreso en vivo de una busqueda: `{status, current_depth, max_depth, bridge_artist, seed_artists, visited_per_seed, frontier_per_seed, came_from}`; agrega `path` cuando `status="found"` o `error_message` cuando `status="failed"`. Estados: `pending`, `running`, `found`, `exhausted`, `failed`.

## Requisitos previos

- Python 3.10 o posterior
- Node.js 18 o posterior y npm
- PostgreSQL corriendo en el sistema

## Dependencias

### Python

```bash
pip install -r requirements.txt
```

### Node.js

El paquete `react-force-graph` trae una dependencia alojada en GitHub. npm 12 deshabilita las dependencias git por defecto, por lo que la instalacion debe permitirlas:

```bash
cd frontend
npm install --allow-git=all
```

## Configuracion

1. Copia la plantilla de variables de entorno:

   Linux:
   ```bash
   cp .env.example .env
   ```

   Windows (PowerShell):
   ```powershell
   Copy-Item .env.example .env
   ```

2. Edita `.env` y completa tus valores:

   - `DJANGO_SECRET_KEY`: cualquier cadena secreta.
   - `DEBUG`: `True` para desarrollo.
   - `DJANGO_ALLOWED_HOSTS`: `localhost,127.0.0.1`.
   - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: datos de conexion de PostgreSQL. Ajustalos para que coincidan con la base de datos que crees en la siguiente seccion.
   - `DISCOGS_TOKEN`: tu token de la API de Discogs (opcional; Discogs esta desactivado por el momento).
   - `LASTFM_API_KEY`: tu clave de la API de Last.fm (opcional para desarrollo).

## Configuracion de PostgreSQL

Crea la base de datos y el usuario que usa la aplicacion. Ajusta los comandos para que coincidan con las credenciales de tu `.env`.

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

## Ejecutar el programa

### Linux

1. Backend

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py runserver
   # la API esta disponible en http://127.0.0.1:8000/api/
   ```

2. Frontend (en una segunda terminal)

   ```bash
   cd frontend
   npm install --allow-git=all
   npm run dev
   # la aplicacion esta disponible en http://localhost:5173/
   ```

### Windows

1. Backend

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py runserver
   # la API esta disponible en http://127.0.0.1:8000/api/
   ```

2. Frontend (en una segunda terminal)

   ```powershell
   cd frontend
   npm install --allow-git=all
   npm run dev
   # la aplicacion esta disponible en http://localhost:5173/
   ```

El servidor de desarrollo de Vite proxyya `/api` al servidor de Django en `http://127.0.0.1:8000`, de modo que el frontend en `http://localhost:5173/` puede llamar al backend de forma transparente.

## Uso

### Recomendaciones

1. Agrega entre 1 y 5 albumes semilla: escribi un artista (autocompletado contra Last.fm) y elegi uno de sus albumes.
2. Elige cuantos resultados pedir (de 1 a 5) con el control deslizante.
3. Presiona "Recomendar".
4. Aparece una lista de albumes recomendados, cada uno con su **Posible gusto: N%** (maximo coseno TF-IDF contra una semilla) y las semillas con las que conecta (`Conecta con: Artista — Album (N%)`).

### Busqueda de conexion

1. Agrega al menos 2 artistas semilla (el panel aparece al haber 2 o mas).
2. Presiona "Buscar conexion entre estos artistas".
3. El grafo de afinidad muestra la busqueda expandiendose en vivo (la frontera se consulta cada segundo): cada rama tiene el color de su semilla. Al encontrar un puente, el artista puente se resalta y los caminos semilla → puente se listan debajo del grafo.

## Notas de configuracion

- Vite proxyya `/api` al servidor de Django. Si tu servidor de Django corre en otro host/puerto, actualiza `frontend/vite.config.js`.
- CORS ya esta configurado en `soundgraph/settings.py` (`CORS_ALLOWED_ORIGINS`) para `localhost:3000` y `localhost:5173`.
- Los albumes cacheados sin tags (por ejemplo, antes de existir el respaldo a `album.gettoptags`) se vuelven a pedir automaticamente en el proximo request.