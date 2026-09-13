# Soundgraph

Soundgraph es un sistema de recomendacion musical basado en la similitud entre las etiquetas (tags) de los albumes. Cargas entre 1 y 5 albumes/artistas favoritos como "semilla", y el sistema puede hacer dos cosas:

- **Recomendar albumes**: arma un pool de albumes candidatos (albumes top de los artistas similares a cada semilla), los puntua con similitud coseno TF-IDF sobre sus tags (Last.fm) y devuelve una lista ordenada por score. A mayor coseno con una semilla, mayor es el score de "posible gusto" (0-100). Cada recomendacion muestra todas las semillas con las que comparte tags y su score por semilla.
- **Buscar artista puente**: corre un BFS multi-fuente sobre el grafo de "artistas similares" de Last.fm entre 2 y 5 artistas semilla, buscando un artista que los conecte a todos. La busqueda se visualiza en vivo en un grafo de afinidad mientras se expande, y al encontrarse se muestran los caminos semilla → puente.

El sistema tambien detecta si un album es "atipico" dentro de la discografia de su artista (distancia al centroide TF-IDF de sus tags).

Los tags provienen exclusivamente de Last.fm (`album.getinfo`, con respaldo a `album.gettoptags`).

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
  Progreso en vivo de una busqueda: `{status, current_depth, max_depth, bridge_artist, seed_artists, visited_per_seed, frontier_per_seed, came_from}`; agrega `path` cuando `status="found"` o `error_message` cuando `status="failed"`. Estados: `pending`, `running`, `found`, `exhausted`, `failed`. Con `?graph=full` devuelve el grafo explorado **completo** (visitados/frontera/came_from sin acotar) para visualizar toda la busqueda que llevo al puente; por defecto el payload viene compacto (muestras) porque el frontend lo consulta cada segundo.

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
4. Cuando la conexion aparece, el grafo muestra por defecto la vista **simplificada** (solo los caminos semilla → puente). El boton **"Ver grafo completo"** (arriba a la izquierda del grafo) pide al backend el grafo explorado completo con `?graph=full` y lo renderiza: todos los artistas visitados, la frontera final y las aristas de `came_from`, con el puente y su cadena siempre visibles. El boton **"Ver grafo simplificado"** vuelve a la vista de caminos.

## Motor de búsqueda de artista puente

La lógica de la búsqueda vive en `catalog/services/connection_search.py` y son
tres piezas puras que mutan el objeto `ConnectionSearch` en memoria (persistir
la decisión la toma el llamador; `run_full_search` guarda el estado nivel a
nivel):

- `expand_one_level(search, on_progress=None)`: expande UN nivel de BFS para
  todas las semillas.
- `find_intersection(search)`: detecta si un artista está en TODOS los visitados.
- `reconstruct_path(search, bridge)`: arma el camino de cada semilla al puente.

### expand_one_level

BFS multi-fuente "nivel por nivel": cada semilla mantiene su propia frontera y
su propio conjunto de visitados.

1. **Inicialización por semilla**: en el primer nivel, `visited_per_seed[seed]`
   y `frontier_per_seed[seed]` arrancan con `[seed]`. Las semillas son raíces:
   NUNCA se registran como clave de `came_from` (ver `reconstruct_path`); si se
   descubrieran mutuamente se formaría un ciclo `S1->S2->S1` que colgaría la
   reconstrucción.
2. **Snapshot de frontera**: para cada semilla, copia la frontera actual a una
   lista nueva (`frontier = list(...)`). Se recorre SOLO lo descubierto en el
   nivel anterior; si frontera y visitados compartieran el mismo objeto de
   lista, un solo nivel se convertiría en un flood de todo el componente
   alcanzable en Last.fm.
3. **Expansión**: por cada artista de la frontera, consulta sus similares en
   Last.fm (`SIMILAR_LIMIT = 10`) UNA sola vez por corrida (cache en memoria en
   `_similar_cache`). Los nombres que la semilla ya visitó se descartan; los
   nuevos se agregan a `visited`, a la nueva frontera y se registran en
   `came_from[similar] = artista` sin pisar un padre ya registrado por otra
   semilla (así `came_from` guarda el PRIMER descubrimiento global de cada
   artista).
4. **Tope de nodos**: si `node_limit` está seteado y `total_discovered` lo
   alcanza, marca `over_limit` en memoria y corta la expansión; el llamador
   cierra la búsqueda en `exhausted` con `stopped_reason="node_limit"`.
5. La nueva frontera de la semilla pasa a ser exactamente los artistas recién
   descubiertos: los ya visitados no se re-expanden.

### find_intersection

Intersecta los `visited_per_seed` de todas las semillas. Los visitados se
cachean en sets solo-memoria (`_visited_sets`), así que aplica `&` (no `&=`)
para no mutar esos sets y romper la dedupe de `expand_one_level`. Devuelve el
primer artista en orden alfabético presente en todas las semillas, o `None`.
Es la condición de corte entre niveles: apenas existe un artista común, la
búsqueda termina en `found` con `bridge_artist`.

### reconstruct_path

Recorre `came_from` hacia atrás desde el puente hasta la semilla raíz de su
cadena (la semilla que lo descubrió):

1. Si el puente ES una semilla, cada semilla recibe `[semilla]` (la propia) o
   `[semilla, puente]`.
2. `chain` arranca en el puente y salta de hijo a padre
   (`current = came_from[current]`) hasta llegar a una semilla. Las semillas
   jamás tienen padre (regla de `expand_one_level`), y por la naturaleza de BFS
   un padre siempre es de un nivel anterior que su hijo, así que la cadena
   nunca puede dar vueltas.
3. `chain.reverse()` ordena la cadena como semilla → ... → puente. La semilla
   raíz recibe la cadena completa; las demás reciben `[semilla, puente]`
   porque `came_from` solo conserva el primer hallazgo.
4. **Defensa anti-ciclo**: por si quedaron filas viejas con `came_from`
   corrupto en la base, un `seen` corta el bucle si un nodo se repite; si se
   detectó un ciclo o el camino terminó en un nodo huérfano (sin semilla como
   raíz), se devuelve la aproximación de dos saltos
   `{semilla: [semilla, puente]}` para todas las semillas en vez de colgar el
   endpoint.

> **Bug corregido (MemoryError)**: artistas que se parecen entre sí (50 Cent,
> Eminem y Lil Wayne comparten el vecindario del rap) hacían que el BFS
> descubriera a las propias semillas como "similares" y las registrara en
> `came_from` como claves: `{Eminem: 50 Cent, 50 Cent: Eminem}`. El `while` de
> `reconstruct_path` oscilaba entre ambas semillas sin terminar, `chain.append`
> crecía sin límite y el proceso reventaba contra
> `SOUNDGRAPH_MEMORY_LIMIT_MB` (4 GB) con `MemoryError` en cada
> `GET /api/connections/{id}/`. El fix tiene tres capas: las semillas nunca
> entran como clave de `came_from` (son raíces), el recorrido corta en la
> primera semilla, y un guard de ciclo degrada a caminos de dos saltos si el
> dato persistido está corrupto.

- Vite proxyya `/api` al servidor de Django. Si tu servidor de Django corre en otro host/puerto, actualiza `frontend/vite.config.js`.
- CORS ya esta configurado en `soundgraph/settings.py` (`CORS_ALLOWED_ORIGINS`) para `localhost:3000` y `localhost:5173`.
- Los albumes cacheados sin tags (por ejemplo, antes de existir el respaldo a `album.gettoptags`) se vuelven a pedir automaticamente en el proximo request.
- La busqueda de conexion esta **acotada en memoria** para que nunca tumbe el servidor aunque las semillas sean artistas muy populares:
  - **`SOUNDGRAPH_NODE_LIMIT`** (default `50000`): tope de artistas distintos explorados en total por el BFS. Al alcanzarlo la busqueda termina en `exhausted` con `stopped_reason="node_limit"`. La frontera crece ~10x por nivel; sin este tope el estado del grafo (y su JSON en la base) explotaria.
  - **`SOUNDGRAPH_MAX_CONCURRENT_SEARCHES`** (default `1`): maximo de busquedas de conexion en paralelo. Cada BFS mantiene todo su estado en RAM; sin limite, varios hilos paralelos multiplican el consumo.
  - **`SOUNDGRAPH_MEMORY_LIMIT_MB`** (default `4096`): capa la RAM del proceso entero con `resource.setrlimit` (Linux/macOS). Si el proceso intenta superar el tope, la busqueda falla con `status="failed"` en vez de dejar el servidor sin memoria. `0` desactiva el tope.
- El endpoint `GET /api/connections/{id}/` devuelve un payload **compacto**: cuentas (`visited_count_per_seed`, `total_discovered`), la frontera y una muestra acotada del grafo (`visited_per_seed`, `came_from`) que alcanza para la visualizacion. Antes devolvia el grafo completo explorado con cada poll de 1 segundo (decenas de MB). El grafo completo sigue disponible bajo demanda con `?graph=full` (el boton "Ver grafo completo" del frontend lo pide una sola vez, no en cada poll); el frontend ademas lo renderiza con un tope de nodos para no congelar el browser incluso si la busqueda descubrio decenas de miles.
- Se corrigio un bug critico de memoria: `frontier_per_seed` y `visited_per_seed` compartian los mismos objetos de lista, lo que hacia que el primer nivel del BFS se convirtiera en un flood de todo el componente de artistas alcanzable en Last.fm. Ahora se iteran con un snapshot y las estructuras se crean independientes.
- El cliente de Last.fm reintenta con backoff las respuestas 429/502/503 (limitacion de la API) y reporta un error claro si se agota; los codigos de error 15/29 en el body ya no se silencian como "sin datos". El BFS ademas cachea los similares de cada artista para consultarlos UNA sola vez, reduciendo el volumen de llamadas.
- **Anti-zombis**: el BFS corre en un hilo daemon; si el servidor se cae a mitad de una busqueda, el hilo muere y la fila quedaria clavada en `running` (bloqueando nuevas busquedas). Para evitarlo, mientras trabaja el hilo emite un heartbeat (actualiza `updated_at` cada 10s) y toda busqueda `pending/running` sin actividad por mas de `SOUNDGRAPH_STALE_SEARCH_SECONDS` (default 60) se expira sola con estado `failed` ("el servidor puede haberse reiniciado") desde el POST/GET de conexiones y al arrancar Django. Un `finally` en el hilo ademas retira la fila si termino sin estado final.
- **Importante**: si el servidor ya estaba levantado y la base no tiene las migraciones nuevas, verifica aplicarlas (`python manage.py migrate`). Un `ProgrammingError` por columnas faltantes en `ConnectionSearch` se veia como error 500 en `GET /api/connections/{id}/`.