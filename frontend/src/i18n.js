const SUPPORTED = ['es', 'en'];
const DEFAULT_LANG = 'es';

const requested = String(import.meta.env.VITE_LANG || '').toLowerCase();
export const lang = SUPPORTED.includes(requested) ? requested : DEFAULT_LANG;

if (typeof document !== 'undefined') {
  document.documentElement.lang = lang;
}

const messages = {
  es: {
    'app.tagline': 'Descubre álbumes afines y encuentra el puente entre tus artistas.',

    'seeds.title': 'Semillas',
    'seeds.desc': 'Define los artistas y/o álbumes de referencia que alimentan el análisis.',
    'seeds.remove': 'Quitar semilla',
    'seeds.minError': 'Debes dejar al menos una semilla.',
    'seeds.maxHint': 'Máximo {max} semillas.',

    'recommend.title': 'Búsqueda por similitud coseno',
    'recommend.desc': 'Encuentra álbumes afines a tus semillas mediante la similitud coseno TF-IDF.',
    'recommend.results': 'Resultados: {n}',
    'recommend.fewer': 'Menos resultados',
    'recommend.more': 'Más resultados',
    'recommend.submit': 'Recomendar',
    'recommend.loading': 'Recomendando…',
    'recommend.hint': 'Se necesita tanto el artista como su álbum.',
    'recommend.noSeedError': 'Elige al menos un artista y uno de sus álbumes de la lista.',

    'results.title': 'Recomendaciones',
    'results.desc': 'Candidatos ordenados por su puntaje de similitud coseno TF-IDF.',
    'result.posibleTaste': 'Posible gusto:',
    'result.connects': 'Conecta con:',
    'result.separator': ' · ',

    'graph.title': 'Grafo de la conexión',
    'graph.desc': 'Visualiza la expansión del grafo de afinidad hasta encontrar el artista puente.',

    'connection.title': 'Búsqueda de conexión por grafo de artistas',
    'connection.desc': 'Localiza mediante BFS multiorigen el artista puente que une a todas las semillas.',
    'connection.starting': 'Iniciando búsqueda…',
    'connection.searching': 'Buscando conexión…',
    'connection.searchAgain': 'Buscar otra conexión',
    'connection.search': 'Buscar conexión',
    'connection.hint': 'Se necesita al menos 2 artistas.',
    'connection.found': 'Conexión encontrada',
    'connection.bridgePrefix': 'Artista puente: {name}',
    'connection.exhausted': 'Búsqueda agotada',
    'connection.exhaustedLimit': 'Se exploraron {count} artistas sin encontrar una conexión dentro del límite de seguridad. Prueba con artistas más cercanos entre sí.',
    'connection.exhaustedNone': 'No se encontró una conexión directa entre estos artistas dentro del límite de búsqueda',
    'connection.failed': 'Error en la búsqueda',
    'connection.unknownError': 'Error desconocido',
    'connection.stopped': 'Búsqueda detenida por el usuario.',
    'connection.paused': 'Búsqueda pausada. Reanudala o detenela cuando quieras.',
    'connection.exploring': 'Explorando nivel {depth} de {max}',
    'connection.artists': '· {count} artistas',
    'connection.pause': 'Pausar',
    'connection.resume': 'Reanudar',
    'connection.stop': 'Detener',

    'artist.placeholder': 'Artista',
    'artist.listeners': '{count} oyentes',
    'artist.empty': 'Sin resultados en Last.fm',

    'album.placeholder': 'Álbum',
    'album.pickArtistFirst': 'Primero elige un artista',
    'album.empty': 'Sin álbumes para «{album}»',

    'graph.kind.seed': 'Semilla — artista de origen',
    'graph.kind.bridge': 'Artista puente',
    'graph.kind.hop': 'Nodo intermedio (hop)',
    'graph.kind.recommendation': 'Álbum recomendado',
    'graph.kind.node': 'Nodo',
    'graph.loadingFull': 'Cargando grafo completo…',
    'graph.showFull': 'Ver grafo completo',
    'graph.showSimple': 'Ver grafo simplificado',
    'graph.zoomIn': 'Acercar',
    'graph.zoomOut': 'Alejar',
    'graph.fullscreenEnter': 'Agrandar (pantalla completa)',
    'graph.fullscreenExit': 'Salir de pantalla completa',
    'graph.fact.iteration': 'Iteración (nivel BFS)',
    'graph.fact.branch': 'Rama / semilla raíz',
    'graph.fact.center': 'centro del grafo',
    'graph.fact.degree': 'Vecinos directos (grado)',
    'graph.fact.children': 'Descubrió (descendientes)',
    'graph.fact.bfsStore': 'Almacén del BFS',
    'graph.fact.frontier': 'Frontera',
    'graph.fact.interior': 'Nodo interior',
    'graph.fact.discoverIndex': 'N.º de descubrimiento',
    'graph.fact.discovered': '#{index} de {total}',
    'graph.fact.id': 'Identificador',
    'graph.fact.color': 'Color (hex)',
    'graph.posibleTaste': 'Posible gusto: {score}%',
    'graph.close': 'Cerrar',
  },

  en: {
    'app.tagline': 'Discover related albums and find the bridge between your artists.',

    'seeds.title': 'Seeds',
    'seeds.desc': 'Set the reference artists and/or albums that feed the analysis.',
    'seeds.remove': 'Remove seed',
    'seeds.minError': 'You must keep at least one seed.',
    'seeds.maxHint': 'Maximum {max} seeds.',

    'recommend.title': 'Cosine similarity search',
    'recommend.desc': 'Find albums related to your seeds using TF-IDF cosine similarity.',
    'recommend.results': 'Results: {n}',
    'recommend.fewer': 'Fewer results',
    'recommend.more': 'More results',
    'recommend.submit': 'Recommend',
    'recommend.loading': 'Recommending…',
    'recommend.hint': 'You need both the artist and their album.',
    'recommend.noSeedError': 'Choose at least one artist and one of their albums from the list.',

    'results.title': 'Recommendations',
    'results.desc': 'Candidates ranked by their TF-IDF cosine similarity score.',
    'result.posibleTaste': 'Possible taste:',
    'result.connects': 'Connects with:',
    'result.separator': ' · ',

    'graph.title': 'Connection graph',
    'graph.desc': 'See how the affinity graph expands until the bridge artist is found.',

    'connection.title': 'Connection search on the artists graph',
    'connection.desc': 'Use multi-source BFS to find the bridge artist that connects all seeds.',
    'connection.starting': 'Starting search…',
    'connection.searching': 'Searching connection…',
    'connection.searchAgain': 'Search another connection',
    'connection.search': 'Find connection',
    'connection.hint': 'You need at least 2 artists.',
    'connection.found': 'Connection found',
    'connection.bridgePrefix': 'Bridge artist: {name}',
    'connection.exhausted': 'Search exhausted',
    'connection.exhaustedLimit': '{count} artists were explored without finding a connection within the safety limit. Try with artists that are closer together.',
    'connection.exhaustedNone': 'No direct connection was found between these artists within the search limit',
    'connection.failed': 'Search error',
    'connection.unknownError': 'Unknown error',
    'connection.stopped': 'Search stopped by the user.',
    'connection.paused': 'Search paused. Resume or stop it whenever you want.',
    'connection.exploring': 'Exploring level {depth} of {max}',
    'connection.artists': '· {count} artists',
    'connection.pause': 'Pause',
    'connection.resume': 'Resume',
    'connection.stop': 'Stop',

    'artist.placeholder': 'Artist',
    'artist.listeners': '{count} listeners',
    'artist.empty': 'No results on Last.fm',

    'album.placeholder': 'Album',
    'album.pickArtistFirst': 'Choose an artist first',
    'album.empty': 'No albums for «{album}»',

    'graph.kind.seed': 'Seed — source artist',
    'graph.kind.bridge': 'Bridge artist',
    'graph.kind.hop': 'Intermediate node (hop)',
    'graph.kind.recommendation': 'Recommended album',
    'graph.kind.node': 'Node',
    'graph.loadingFull': 'Loading full graph…',
    'graph.showFull': 'Show full graph',
    'graph.showSimple': 'Show simplified graph',
    'graph.zoomIn': 'Zoom in',
    'graph.zoomOut': 'Zoom out',
    'graph.fullscreenEnter': 'Enlarge (fullscreen)',
    'graph.fullscreenExit': 'Exit fullscreen',
    'graph.fact.iteration': 'Iteration (BFS level)',
    'graph.fact.branch': 'Branch / root seed',
    'graph.fact.center': 'graph center',
    'graph.fact.degree': 'Direct neighbors (degree)',
    'graph.fact.children': 'Discovered (descendants)',
    'graph.fact.bfsStore': 'BFS store',
    'graph.fact.frontier': 'Frontier',
    'graph.fact.interior': 'Interior node',
    'graph.fact.discoverIndex': 'Discovery no.',
    'graph.fact.discovered': '#{index} of {total}',
    'graph.fact.id': 'Identifier',
    'graph.fact.color': 'Color (hex)',
    'graph.posibleTaste': 'Possible taste: {score}%',
    'graph.close': 'Close',
  },
};

const table = messages[lang] || messages[DEFAULT_LANG];

export function t(key, vars = {}) {
  let str = table[key] ?? messages[DEFAULT_LANG][key] ?? key;
  for (const [name, value] of Object.entries(vars)) {
    str = str.split(`{${name}}`).join(String(value));
  }
  return str;
}

// Mensajes de error del backend (español) traducidos best-effort a inglés
// cuando la interfaz está en ``en``. Los mensajes con interpolación se
// traducen por prefijo para conservar la parte variable.
const backendErrorMap = {
  'Debes enviar entre 1 y 5 álbumes semilla.': 'You must send between 1 and 5 seed albums.',
  'Debes enviar entre 2 y 5 artistas semilla.': 'You must send between 2 and 5 seed artists.',
  "El parámetro 'q' es obligatorio.": "The 'q' parameter is required.",
  "El parámetro 'artist' es obligatorio.": "The 'artist' parameter is required.",
  'La búsqueda ya está pausada.': 'The search is already paused.',
  'Acción de control no válida.': 'Invalid control action.',
  'Reducí la cantidad de artistas semilla o el tope de nodos.':
    'Reduce the number of seed artists or the node limit.',
};

const backendErrorPrefixes = [
  ['No se pudieron obtener los datos de la API:', 'Could not fetch data from the API:'],
];

export function translateError(message) {
  if (typeof message !== 'string' || !message) return message;
  const trimmed = message.trim();
  if (lang === DEFAULT_LANG) return trimmed;
  if (backendErrorMap[trimmed]) return backendErrorMap[trimmed];
  for (const [prefix, replacement] of backendErrorPrefixes) {
    if (trimmed.startsWith(prefix)) return replacement + trimmed.slice(prefix.length);
  }
  return trimmed;
}