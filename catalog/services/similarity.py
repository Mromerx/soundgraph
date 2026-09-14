"""Motor de similitud musical basado en TF-IDF y similitud coseno.

Convierte los tags de Last.fm de cada álbum en un documento, lo vectoriza con
TF-IDF y calcula similitudes coseno para recomendar álbumes candidatos entre
las semillas del usuario.

El documento de tags tiene un builder ÚNICO y canónico (``build_tag_document``
sobre la lista cruda de tags): ``cache.py`` lo usa al persistir un álbum y este
módulo lo reutiliza cuando falta, de modo que no hay dos definiciones distintas
de "documento" según el camino de caché.

El ranking combina dos decisiones explícitas:

1. **Score de relevancia = mezcla max-promedio.** Cada candidato se puntúa
   contra TODAS las semillas: ``0.6 * max + 0.4 * mean`` sobre el vector de
   cosenos. Con una sola semilla la mezcla se reduce al coseno puro; con varias
   premia a los candidatos que conectan con varias semillas en vez de darle
   todo el peso a un único match exacto (que antes empataba con cualquiera que
   tuviera el mismo máximo).
2. **Diversidad máxima-marginal (MMR).** Los candidatos no se ordenan solo por
   score: se eligen greedy penalizando la redundancia con los ya elegidos
   (similitud coseno entre candidatos, forzada a 1 si comparten artista). Así
   los ``n_results`` no quedan llenos de 4 álbumes del mismo artista parecido.
"""
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from catalog.models import AlbumSimilarity

# --- Ranking ---------------------------------------------------------------
# Score de un candidato: 60% el mejor match contra una semilla, 40% el promedio
# del vector completo (los ceros diluyen). Con ``n_seeds == 1`` la mezcla es el
# coseno puro porque mean == max.
_SCORE_MAX_WEIGHT = 0.6
_SCORE_MEAN_WEIGHT = 0.4

# Peso del término de relevancia en MMR: lambda de la fórmula
# ``mmr = lambda * score - (1 - lambda) * redundancy``. Mas alto = menos
# diverso (solo relevancia), mas bajo = mas diverso.
_MAXIMAL_MARGINAL_DIVERSITY = 0.6


def build_tag_document(tags):
    """Arma el documento de texto canónico de un álbum a partir de sus tags.

    Función pura y única fuente de verdad del texto que alimenta el TF-IDF.
    Combina los tags de Last.fm que tengan ``count >= 5`` (repitiendo cada
    uno ``max(1, count // 20)`` veces) en un único string en minúsculas.

    Args:
        tags: lista de dicts ``[{"name": str, "count": int}, ...]`` cruda
            (el contenido de ``Album.tags``).

    Returns:
        El documento de texto a vectorizar (string en minúsculas).
    """
    tokens = []
    for entry in tags or []:
        name = entry.get("name", "")
        count = int(entry.get("count") or 0)
        if count >= 5:
            tokens.extend([name] * max(1, count // 20))

    return " ".join(tokens).lower()


def ensure_tag_document(album):
    """Devuelve ``album.tag_document`` y asegura que exista.

    Si el álbum aún no tiene documento, lo arma con ``build_tag_document``
    (el builder canónico, el mismo que usa ``cache.py`` al persistir) y lo
    persiste únicamente si el álbum ya está en la base, de modo que no se
    recalcula en cada llamada.

    Args:
        album: objeto ``Album`` con ``tags`` poblados.

    Returns:
        El documento de texto del álbum (string en minúsculas).
    """
    if not album.tag_document:
        album.tag_document = build_tag_document(album.tags or [])
        if album.pk is not None:
            album.save(update_fields=["tag_document", "cached_at"])
    return album.tag_document


def compute_similarity_matrix(albums):
    """Vectoriza todos los álbumes juntos y devuelve la matriz de similitud.

    Asegura que cada álbum tenga su ``tag_document`` (construyéndolo con
    ``ensure_tag_document`` si aún no está cacheado), vectoriza todos los
    documentos en un mismo vocabulario TF-IDF y calcula la matriz de similitud
    coseno entre todos los pares.

    Args:
        albums: lista de objetos ``Album``.

    Returns:
        Tupla ``(matriz, albums)``: la matriz de similitud coseno como numpy
        array ``(N, N)`` y la misma lista de álbumes en el mismo orden, para
        poder mapear filas/columnas a álbumes.
    """
    documents = [ensure_tag_document(album) for album in albums]

    n = len(documents)
    non_empty = [(row, doc) for row, doc in enumerate(documents) if doc.strip()]
    if not non_empty:
        return np.zeros((n, n)), albums

    vectorizer = TfidfVectorizer()
    reduced = vectorizer.fit_transform([doc for _, doc in non_empty]).toarray()
    full_matrix = np.zeros((n, reduced.shape[1]))
    for position, (row, _) in enumerate(non_empty):
        full_matrix[row] = reduced[position]

    similarity_matrix = cosine_similarity(full_matrix)
    return similarity_matrix, albums


def _blend_score(row):
    """Score de relevancia de un candidato contra todas las semillas.

    Mezcla del mejor match (``row.max()``) y del promedio del vector completo
    (``row.mean()``, ceros incluidos): ``0.6 * max + 0.4 * mean``.

    Args:
        row: numpy array con los cosenos del candidato contra cada semilla.

    Returns:
        El score como float en ``[0, 1]``.
    """
    best = float(row.max())
    mean_all = float(row.mean())
    return _SCORE_MAX_WEIGHT * best + _SCORE_MEAN_WEIGHT * mean_all


def _rank_with_diversity(items, similarity_matrix, diversity=_MAXIMAL_MARGINAL_DIVERSITY):
    """Ordena candidatos con relevancia máxima-marginal (MMR).

    Selección greedy: en cada paso se elige el candidato pendiente con mayor
    ``mmr = diversity * score - (1 - diversity) * redundancy``, donde
    ``redundancy`` es el máximo coseno contra los candidatos ya elegidos
    (forzado a 1 en los pares que comparten artista, para garantizar que los
    resultados finales no sean N álbumes del mismo artista).

    Args:
        items: lista de dicts con las claves ``album``, ``mat_index`` (fila del
            candidato en la matriz de similitud) y ``score``.
        similarity_matrix: matriz coseno ``(N, N)`` (semillas + candidatos).
        diversity: lambda de MMR.

    Returns:
        La misma lista de dicts, en orden de selección.
    """
    selected = []
    pending = list(items)

    while pending:
        best_item = None
        best_mmr = None
        for item in pending:
            redundancy = 0.0
            for chosen in selected:
                similarity = similarity_matrix[item["mat_index"], chosen["mat_index"]]
                if item["album"].artist_id == chosen["album"].artist_id:
                    similarity = 1.0
                redundancy = max(redundancy, similarity)
            mmr = diversity * item["score"] - (1.0 - diversity) * redundancy
            if best_mmr is None or mmr > best_mmr:
                best_mmr, best_item = mmr, item
        selected.append(best_item)
        pending.remove(best_item)

    return selected


def recommend(seed_albums, candidate_albums, n_results=5):
    """Recomienda hasta ``n_results`` álbumes candidatos.

    Cada candidato se puntúa contra TODAS las semillas con similitud coseno
    TF-IDF de las etiquetas de los álbumes. El ``score`` es la mezcla
    max-promedio del vector de cosenos (con una sola semilla equivale al coseno
    puro; con varias premia conectar con varias semillas). ``matched_seeds``
    lista TODAS las semillas con las que comparte etiquetas (score > 0) con su
    similitud individual, para que el grafo muestre la conexión entre artistas.

    Los resultados se ordenan con MMR (relevancia + diversidad entre
    candidatos, penalizando álbumes redundantes y del mismo artista), en lugar
    de un sort plano por score. Los candidatos sin ninguna similitud (> 0) con
    las semillas se descartan.

    Cada par (semilla conectada, candidato) se persiste en ``AlbumSimilarity``.

    Args:
        seed_albums: entre 1 y 5 objetos ``Album`` semilla.
        candidate_albums: lista de objetos ``Album`` candidatos.
        n_results: cantidad de recomendaciones a devolver, entre 1 y 15.

    Raises:
        ValueError: si ``seed_albums`` no tiene entre 1 y 5 elementos o si
            ``n_results`` no está entre 1 y 15.

    Returns:
        Lista de hasta ``n_results`` dicts con las claves ``album``, ``score``
        (float, mezcla max-promedio 0-1), ``matched_seed`` (la semilla contra
        la que obtuvo el máximo coseno) y ``matched_seeds`` (lista de
        ``{"album": Album, "score": float}`` con todas las semillas conectadas).
    """
    if not 1 <= len(seed_albums) <= 5:
        raise ValueError("seed_albums debe contener entre 1 y 5 álbumes.")
    if not 1 <= n_results <= 15:
        raise ValueError("n_results debe estar entre 1 y 15.")
    if not candidate_albums:
        return []

    all_albums = [*seed_albums, *candidate_albums]
    similarity_matrix, _ = compute_similarity_matrix(all_albums)

    n_seeds = len(seed_albums)
    scored = []
    for offset, candidate in enumerate(candidate_albums):
        row = similarity_matrix[n_seeds + offset, :n_seeds]
        score = _blend_score(row)
        if score <= 0:
            continue
        best_index = int(row.argmax())
        matched_seeds = [
            {"album": seed_albums[i], "score": float(row[i])}
            for i in range(n_seeds)
            if row[i] > 0
        ]
        scored.append(
            {
                "album": candidate,
                "mat_index": n_seeds + offset,
                "score": score,
                "matched_seed": seed_albums[best_index],
                "matched_seeds": matched_seeds,
            }
        )

    results = _rank_with_diversity(scored, similarity_matrix)[:n_results]

    for item in results:
        item.pop("mat_index", None)
        for connected in item["matched_seeds"]:
            AlbumSimilarity.objects.update_or_create(
                album_a=connected["album"],
                album_b=item["album"],
                defaults={"score": connected["score"]},
            )

    return results


def compute_artist_centroid(artist):
    """Calcula el centroide TF-IDF de todos los álbumes de un artista.

    Arma el ``tag_document`` de cada álbum de ``artist.albums.all()``, ajusta
    un vectorizador TF-IDF sobre todos ellos y promedia los vectores
    resultantes para obtener el "sonido promedio" del artista.

    Args:
        artist: objeto ``Artist``.

    Raises:
        ValueError: si el artista no tiene álbumes.

    Returns:
        Tupla ``(centroid, vectorizer)``: el centroide como numpy array denso,
        junto con el vectorizador ajustado (necesario para vectorizar álbumes
        nuevos con el mismo vocabulario).
    """
    albums = list(artist.albums.all())
    if not albums:
        raise ValueError(f"{artist.name} no tiene álbumes; no se puede calcular el centroide.")

    documents = [ensure_tag_document(album) for album in albums]

    non_empty = [doc for doc in documents if doc.strip()]
    if not non_empty:
        vectorizer = TfidfVectorizer()
        vectorizer.fit(["unknown"])
        return np.zeros(len(vectorizer.get_feature_names_out())), vectorizer

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(non_empty)
    centroid = np.asarray(tfidf_matrix.mean(axis=0)).flatten()
    return centroid, vectorizer


def is_atypical_album(album, artist_centroid, vectorizer, threshold=0.5):
    """Detecta si un álbum es atípico dentro de la discografía de su artista.

    Vectoriza el ``tag_document`` del álbum con el mismo vectorizador usado
    para el centroide y calcula la distancia coseno (1 - similitud coseno)
    entre el álbum y el centroide.

    Args:
        album: objeto ``Album`` a evaluar.
        artist_centroid: numpy array con el centroide del artista.
        vectorizer: ``TfidfVectorizer`` ajustado con el mismo vocabulario.
        threshold: distancia coseno a partir de la cual se considera atípico.

    Returns:
        Tupla ``(es_atipico, distancia)``: ``True`` si la distancia supera el
        ``threshold``, junto con el valor exacto de la distancia.
    """
    ensure_tag_document(album)
    album_vector = vectorizer.transform([album.tag_document])
    centroid_vector = np.asarray(artist_centroid).reshape(1, -1)

    similarity = cosine_similarity(album_vector, centroid_vector)[0, 0]
    distance = 1.0 - float(similarity)
    return distance > threshold, distance