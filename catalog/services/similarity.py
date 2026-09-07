"""Motor de similitud musical basado en TF-IDF y similitud coseno.

Convierte la información textual de cada álbum (géneros/estilos de Discogs y
tags de Last.fm) en un documento, lo vectoriza con TF-IDF y calcula
similitudes coseno para recomendar álbumes candidatos entre las semillas del
usuario.
"""
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from catalog.models import Album, AlbumSimilarity


def build_tag_document(album):
    """Arma y cachea el documento de texto usado para vectorizar un álbum.

    Combina los géneros y estilos de Discogs (repitiendo cada tag 3 veces
    para darle más peso) con los tags de Last.fm que tengan ``count >= 5``
    (repitiendo cada uno ``max(1, count // 20)`` veces). Devuelve un único
    string en minúsculas con todo separado por espacios.

    El resultado se guarda en ``album.tag_document`` y se persiste con
    ``save()`` únicamente si el álbum ya existe en la base de datos, de modo
    que el documento no se recalcula en cada llamada.

    Args:
        album: objeto ``Album`` con ``genres``, ``styles`` y ``tags`` poblados.

    Returns:
        El documento de texto ya construido (string en minúsculas).
    """
    tokens = []
    for tag in (album.genres or []) + (album.styles or []):
        tokens.extend([tag] * 3)
    for entry in album.tags or []:
        name = entry.get("name", "")
        count = int(entry.get("count") or 0)
        if count >= 5:
            tokens.extend([name] * max(1, count // 20))

    document = " ".join(tokens).lower()
    album.tag_document = document
    if album.pk is not None:
        album.save(update_fields=["tag_document", "cached_at"])
    return document


def compute_similarity_matrix(albums):
    """Vectoriza todos los álbumes juntos y devuelve la matriz de similitud.

    Asegura que cada álbum tenga su ``tag_document`` (construyéndolo con
    ``build_tag_document`` si aún no está cacheado), vectoriza todos los
    documentos en un mismo vocabulario TF-IDF y calcula la matriz de similitud
    coseno entre todos los pares.

    Args:
        albums: lista de objetos ``Album``.

    Returns:
        Tupla ``(matriz, albums)``: la matriz de similitud coseno como numpy
        array ``(N, N)`` y la misma lista de álbumes en el mismo orden, para
        poder mapear filas/columnas a álbumes.
    """
    documents = []
    for album in albums:
        if not album.tag_document:
            build_tag_document(album)
        documents.append(album.tag_document)

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


def recommend(seed_albums, candidate_albums, n_results=5):
    """Recomienda hasta ``n_results`` álbumes candidatos.

    Cada candidato se puntúa contra TODAS las semillas con similitud coseno
    TF-IDF de las etiquetas de los álbumes: el ``score`` es la similitud MÁXIMA
    contra cualquier semilla (a mayor coseno, mayor score), y ``matched_seeds``
    lista TODAS las semillas con las que comparte etiquetas (score > 0) con su
    similitud individual, para que el grafo muestre la conexión entre artistas.
    Los resultados se ordenan por ese score en forma descendente. Los
    candidatos sin ninguna similitud (> 0) con las semillas se descartan.

    Cada par (semilla conectada, candidato) se persiste en ``AlbumSimilarity``.

    Args:
        seed_albums: entre 1 y 5 objetos ``Album`` semilla.
        candidate_albums: lista de objetos ``Album`` candidatos.
        n_results: cantidad de recomendaciones a devolver, entre 1 y 5.

    Raises:
        ValueError: si ``seed_albums`` no tiene entre 1 y 5 elementos o si
            ``n_results`` no está entre 1 y 5.

    Returns:
        Lista de hasta ``n_results`` dicts con las claves ``album``, ``score``
        (float, similitud coseno máxima 0-1), ``matched_seed`` (la semilla
        contra la que obtuvo el máximo) y ``matched_seeds`` (lista de
        ``{"album": Album, "score": float}`` con todas las semillas conectadas).
    """
    if not 1 <= len(seed_albums) <= 5:
        raise ValueError("seed_albums debe contener entre 1 y 5 álbumes.")
    if not 1 <= n_results <= 5:
        raise ValueError("n_results debe estar entre 1 y 5.")
    if not candidate_albums:
        return []

    all_albums = [*seed_albums, *candidate_albums]
    similarity_matrix, _ = compute_similarity_matrix(all_albums)

    n_seeds = len(seed_albums)
    results = []
    for offset, candidate in enumerate(candidate_albums):
        row = similarity_matrix[n_seeds + offset, :n_seeds]
        best_index = int(row.argmax())
        score = float(row[best_index])
        if score <= 0:
            continue
        matched_seeds = [
            {"album": seed_albums[i], "score": float(row[i])}
            for i in range(n_seeds)
            if row[i] > 0
        ]
        results.append(
            {
                "album": candidate,
                "score": score,
                "matched_seed": seed_albums[best_index],
                "matched_seeds": matched_seeds,
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    results = results[:n_results]

    for item in results:
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

    documents = []
    for album in albums:
        if not album.tag_document:
            build_tag_document(album)
        documents.append(album.tag_document)

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
    if not album.tag_document:
        build_tag_document(album)
    album_vector = vectorizer.transform([album.tag_document])
    centroid_vector = np.asarray(artist_centroid).reshape(1, -1)

    similarity = cosine_similarity(album_vector, centroid_vector)[0, 0]
    distance = 1.0 - float(similarity)
    return distance > threshold, distance