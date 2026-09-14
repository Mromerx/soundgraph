import { useEffect, useMemo, useRef, useState } from 'react';
import { ForceGraph2D } from 'react-force-graph';
import { getConnectionStatus } from '../api/connections.js';

const REC_COLOR = '#ffffff';
const BRIDGE_COLOR = '#4ade80';
const BRANCH_COLORS = [
  '#d55e00',
  '#0072b2',
  '#e69f00',
  '#cc79a7',
  '#f0e442',
];
const MAX_CONNECTION_NODES = 400;
const MAX_FULL_NODES = 2000;

function rootOf(name, cameFrom) {
  const seen = new Set();
  let cur = name;
  while (cameFrom[cur] && !seen.has(cur)) {
    seen.add(cur);
    cur = cameFrom[cur];
  }
  return cur;
}

function depthOf(name, cameFrom) {
  const seen = new Set();
  let cur = name;
  let depth = 0;
  while (cameFrom[cur] && !seen.has(cur)) {
    seen.add(cur);
    cur = cameFrom[cur];
    depth += 1;
  }
  return depth;
}

function nodeKindLabel(kind) {
  switch (kind) {
    case 'seed':
      return 'Semilla — artista de origen';
    case 'bridge':
      return 'Artista puente';
    case 'hop':
      return 'Nodo intermedio (hop)';
    case 'recommendation':
      return 'Álbum recomendado';
    default:
      return 'Nodo';
  }
}

function branchForce(accessor, strength, settle = 1) {
  let nodes = [];
  function force(alpha) {
    for (const node of nodes) {
      if (!node) continue;
      const [tx, ty] = accessor(node);
      const k = strength(node) * settle;
      node.vx += (tx - node.x) * k * alpha;
      node.vy += (ty - node.y) * k * alpha;
    }
  }
  force.initialize = (n) => {
    nodes = n;
  };
  force.setNodes = (n) => {
    nodes = n;
  };
  return force;
}

function collideForce(getRadius, settle = 1) {
  let nodes = [];
  function force(alpha) {
    const n = nodes.length;
    if (n > 800 || n < 2) return;
    for (let i = 0; i < n; i += 1) {
      const a = nodes[i];
      if (!a) continue;
      for (let j = i + 1; j < n; j += 1) {
        const b = nodes[j];
        if (!b) continue;
        if (a.fx !== undefined || b.fx !== undefined) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const minDist = (getRadius(a) + getRadius(b)) * 1.4;
        const d2 = dx * dx + dy * dy;
        if (d2 === 0) {
          const ang = Math.random() * Math.PI * 2;
          dx = Math.cos(ang) * minDist;
          dy = Math.sin(ang) * minDist;
        } else if (d2 >= minDist * minDist) {
          continue;
        }
        const d = Math.sqrt(d2) || 1;
        const overlap = ((minDist - d) / d) * 0.4;
        const k = alpha * settle;
        a.vx -= dx * overlap * k;
        a.vy -= dy * overlap * k;
        b.vx += dx * overlap * k;
        b.vy += dy * overlap * k;
      }
    }
  }
  force.initialize = (n) => {
    nodes = n;
  };
  force.setNodes = (n) => {
    nodes = n;
  };
  return force;
}

function hierarchicalSeparate({ influence = 70, settle = 1 } = {}) {
  // Repulsión jerárquica entre pelotas: la colisión dura (no se tocan) la hace
  // ``collideForce``; esta fuerza ordena por afinidad repeliendo distinto:
  //   - misma semilla y mismo nivel -> se repelen POCO (viven juntas),
  //   - misma semilla, nivel distinto -> repulsión media,
  //   - semillas distintas -> se repelen MÁS (las ramas se separan).
  let nodes = [];
  const strengthOf = (a, b) => {
    if (!a.branch || a.branch !== b.branch) return 2.0; // semilla distinta
    if (a.depth === b.depth) return 0.5;                // mismo nivel
    return 1.0;                                         // misma semilla, otro nivel
  };
  function force(alpha) {
    const n = nodes.length;
    if (n > 800 || n < 2) return;
    for (let i = 0; i < n; i += 1) {
      const a = nodes[i];
      if (!a) continue;
      if (a.fx !== undefined && a.fy !== undefined) continue;
      for (let j = i + 1; j < n; j += 1) {
        const b = nodes[j];
        if (!b) continue;
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const d2 = dx * dx + dy * dy;
        if (d2 === 0) {
          const ang = Math.random() * Math.PI * 2;
          dx = Math.cos(ang) * 0.01;
          dy = Math.sin(ang) * 0.01;
        }
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        if (d >= influence) continue;
        const k = ((influence - d) / influence) * strengthOf(a, b) * alpha * settle;
        const nx = dx / d;
        const ny = dy / d;
        a.vx -= nx * k;
        a.vy -= ny * k;
        b.vx += nx * k;
        b.vy += ny * k;
      }
    }
  }
  force.initialize = (n) => {
    nodes = n;
  };
  force.setNodes = (n) => {
    nodes = n;
  };
  return force;
}

function layoutCenter(nodes, posCache, seedList) {
  const n = nodes.length;
  if (n === 0) return;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const placed = [];
  const branchCount = Math.max((seedList && seedList.length) || 1, 1);
  nodes.forEach((node, i) => {
    if (node.fx !== undefined && node.fy !== undefined) return;
    const cached = posCache && posCache.current[node.id];
    if (cached) {
      node.x = cached.x;
      node.y = cached.y;
      return;
    }
    const branchIdx = seedList ? seedList.indexOf(node.branch) : -1;
    const sector = branchIdx >= 0 ? (2 * Math.PI * branchIdx) / branchCount : 0;
    const depth = node.depth ?? 0;
    const radius = node.kind === 'bridge' ? 30 : 50 + depth * 30 + (i % 8) * 8;
    const angle = sector + (Math.PI / 6) * depth + goldenAngle * (i % 10);
    node.x = Math.cos(angle) * radius;
    node.y = Math.sin(angle) * radius;
    placed.push({ id: node.id, x: node.x, y: node.y });
  });
  if (posCache) {
    for (const p of placed) posCache.current[p.id] = { x: p.x, y: p.y };
  }
}

function buildGraph(recommendations, seeds, posCache) {
  const nodes = [];
  const byKey = new Map();
  const seedArtistSet = new Set();

  function ensureNode(id, label, kind, branch) {
    if (!byKey.has(id)) {
      const node = { id, label, kind, branch: branch || null };
      byKey.set(id, node);
      nodes.push(node);
    }
    const node = byKey.get(id);
    if (branch && !node.branch) node.branch = branch;
    return node;
  }

  const links = [];

  for (const rec of recommendations) {
    const matches = rec.matched_seeds && rec.matched_seeds.length
      ? rec.matched_seeds
      : [rec.matched_seed];
    if (!matches || !matches[0] || !matches[0].artist || !matches[0].album) continue;

    const recId = `rec:${rec.artist}|${rec.album}`;
    const recNode = ensureNode(
      recId,
      `${rec.artist} — ${rec.album}`,
      'recommendation',
      matches[0].artist
    );
    recNode.score = rec.score;
    recNode.matchedSeeds = matches;
    recNode.depth = 1;

    for (const matched of matches) {
      const seedId = `seed:${matched.artist}|${matched.album}`;
      const seedNode = ensureNode(seedId, `${matched.artist} — ${matched.album}`, 'seed', matched.artist);
      seedNode.depth = 0;
      seedArtistSet.add(matched.artist);

      links.push({
        source: seedId,
        target: recId,
        score: (matched.score ?? 0) / 100,
      });
    }
  }

  for (const artist of seeds || []) {
    if (seedArtistSet.has(artist)) continue;
    const seedNode = ensureNode(`seed:${artist}|`, artist, 'seed', artist);
    seedNode.depth = 0;
  }

  layoutCenter(nodes, posCache, seeds);
  return { nodes, links };
}

function buildConnectionGraph(connection, posCache, mode) {
  const {
    bridge_artist = null,
    seed_artists = [],
    visited_per_seed = {},
    frontier_per_seed = {},
    came_from = {},
    path = null,
  } = connection;

  const nodeCap = mode === 'full' ? MAX_FULL_NODES : MAX_CONNECTION_NODES;

  const byKey = new Map();
  const nodes = [];
  const links = [];

  function ensureNode(name, kind, branch) {
    if (!byKey.has(name)) {
      const node = { id: name, label: name, kind, branch: branch || null };
      byKey.set(name, node);
      nodes.push(node);
    }
    const node = byKey.get(name);
    if (node.kind === 'hop' && kind === 'bridge') node.kind = 'bridge';
    if (kind === 'seed') node.kind = 'seed';
    if (branch && !node.branch) node.branch = branch;
    return node;
  }

  // Modo simplificado (default al encontrar el puente): solo los caminos
  // semilla → puente. No se muestra cuando se pide el grafo completo.
  if (path && mode !== 'full') {
    for (const [seed, chain] of Object.entries(path)) {
      for (let i = 0; i < chain.length; i += 1) {
        const name = chain[i];
        const kind = name === bridge_artist ? 'bridge' : i === 0 ? 'seed' : 'hop';
        const node = ensureNode(name, kind, seed);
        node.depth = i;
      }
      for (let i = 0; i < chain.length - 1; i += 1) {
        links.push({ source: chain[i], target: chain[i + 1] });
      }
    }
    layoutCenter(nodes, posCache, seed_artists);
    return { nodes, links };
  }

  const seedSet = new Set(seed_artists);
  const frontierSet = new Set();
  for (const seed of seed_artists) {
    for (const name of frontier_per_seed[seed] || []) frontierSet.add(name);
  }

  const discovered = [];
  const seen = new Set();
  for (const seed of seed_artists) {
    if (!seen.has(seed)) {
      seen.add(seed);
      discovered.push(seed);
    }
    for (const name of (visited_per_seed[seed] || []).slice(0, nodeCap)) {
      if (!seen.has(name)) {
        seen.add(name);
        discovered.push(name);
      }
    }
  }

  // En modo completo el puente y toda su cadena en came_from son lo esencial:
  // se reserva presupuesto para ellos aunque la exploración sea profunda.
  let included;
  if (mode === 'full' && bridge_artist) {
    const essential = [];
    const essSeen = new Set();
    let cur = bridge_artist;
    while (cur && !essSeen.has(cur)) {
      essential.push(cur);
      essSeen.add(cur);
      cur = came_from[cur];
    }
    essential.reverse();

    const ordered = [];
    const includedSet = new Set();
    for (const name of [...essential, ...discovered]) {
      if (!includedSet.has(name)) {
        includedSet.add(name);
        ordered.push(name);
        if (ordered.length >= nodeCap) break;
      }
    }
    included = ordered;
  } else {
    included = discovered.slice(0, nodeCap);
  }
  const includedSet = new Set(included);

  for (const name of included) {
    const kind = seedSet.has(name) ? 'seed' : 'hop';
    const branch = seedSet.has(name) ? name : rootOf(name, came_from);
    const node = ensureNode(name, kind, branch);
    node.depth = depthOf(name, came_from);
    if (frontierSet.has(name)) node.frontier = true;
  }
  if (bridge_artist && includedSet.has(bridge_artist)) {
    byKey.get(bridge_artist).kind = 'bridge';
  }

  const linkKeys = new Set();
  for (const [name, parent] of Object.entries(came_from)) {
    if (includedSet.has(name) && includedSet.has(parent)) {
      const key = `${parent}|${name}`;
      if (linkKeys.has(key)) continue;
      linkKeys.add(key);
      links.push({ source: parent, target: name });
    }
  }

  // En modo completo, came_from solo conserva la cadena de la semilla que
  // descubrió el puente primero; las demás semillas (camino [semilla, puente])
  // quedarían flotando desconectadas. Se agregan los enlaces del path
  // reconstruido para que TODAS queden unidas al puente y el grafo muestre
  // la unión, no solo la primera semilla que encontró la coincidencia.
  if (path && bridge_artist) {
    for (const chain of Object.values(path)) {
      for (let i = 0; i < chain.length - 1; i += 1) {
        const src = chain[i];
        const dst = chain[i + 1];
        if (!includedSet.has(src) || !includedSet.has(dst)) continue;
        const key = `${src}|${dst}`;
        if (linkKeys.has(key)) continue;
        linkKeys.add(key);
        links.push({ source: src, target: dst });
      }
    }
  }

  layoutCenter(nodes, posCache, seed_artists);
  return { nodes, links };
}

export default function GraphView({ recommendations, seeds, connection }) {
  const graphRef = useRef(null);
  const containerRef = useRef(null);
  const posCacheRef = useRef({});
  const [size, setSize] = useState({ width: 800, height: 480 });
  const [selected, setSelected] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showFull, setShowFull] = useState(false);
  const [fullConnection, setFullConnection] = useState(null);
  const [fullLoading, setFullLoading] = useState(false);
  const [fullError, setFullError] = useState('');
  const nodeBirthRef = useRef({});

  const isFound = !!(connection && connection.status === 'found');

  // En modo completo se usa el payload ?graph=full (visitados/came_from sin
  // acotar); el poll periódico trae muestras y no alcanza para el grafo.
  const activeConnection = showFull && fullConnection ? fullConnection : connection;

  const discovering =
    !!activeConnection && ['pending', 'running'].includes(activeConnection.status);

  // Al pausar la búsqueda el frontend congela el layout de la simulación.
  const paused = activeConnection?.status === 'paused';

  const ZOOM_STEP = 1.25;
  // Vista por defecto "alejada": margen alrededor del grafo y zoom máximo de
  // encuadre limitado (no se pega a la pantalla con pocos nodos).
  const FIT_PADDING_RATIO = 0.22;
  const FIT_MAX_ZOOM = 1.5;

  const graph = useMemo(
    () =>
      activeConnection
        ? buildConnectionGraph(activeConnection, posCacheRef, showFull ? 'full' : null)
        : buildGraph(recommendations || [], seeds || [], posCacheRef),
    [activeConnection, recommendations, seeds, showFull]
  );

  const seedList = useMemo(() => {
    if (activeConnection && activeConnection.seed_artists) {
      return activeConnection.seed_artists;
    }
    return seeds || [];
  }, [activeConnection, seeds]);

  const branchById = useMemo(() => {
    const map = {};
    for (const node of graph.nodes) map[node.id] = node.branch || node.id;
    return map;
  }, [graph]);

  const degreeById = useMemo(() => {
    const counts = {};
    for (const link of graph.links) {
      const a = typeof link.source === 'string' ? link.source : link.source.id;
      const b = typeof link.target === 'string' ? link.target : link.target.id;
      counts[a] = (counts[a] || 0) + 1;
      counts[b] = (counts[b] || 0) + 1;
    }
    return counts;
  }, [graph]);

  const childrenById = useMemo(() => {
    const counts = {};
    for (const link of graph.links) {
      const src = typeof link.source === 'string' ? link.source : link.source.id;
      counts[src] = (counts[src] || 0) + 1;
    }
    return counts;
  }, [graph]);

  const selectedFacts = useMemo(() => {
    if (!selected) return null;

    const hex = selected.branch
      ? branchColor(selected.branch)
      : BRIDGE_COLOR;

    const visited = activeConnection?.visited_per_seed?.[selected.branch || ''] || [];
    const discoverIndex = visited.indexOf(selected.id);

    return {
      kindLabel: nodeKindLabel(selected.kind),
      hex: hex,
      degree: degreeById[selected.id] ?? 0,
      children: childrenById[selected.id] ?? 0,
      frontier: !!selected.frontier,
      discoverIndex: discoverIndex >= 0 ? discoverIndex + 1 : null,
      totalVisited: visited.length,
      isExploration:
        !!activeConnection && selected.kind !== 'recommendation',
    };
  }, [selected, graph, activeConnection]);

  const branchAnchors = useMemo(() => {
    const anchors = { center: { x: 0, y: 0 } };
    const r = Math.min(size.width, size.height) * 0.33;
    seedList.forEach((seed, i) => {
      const angle = (2 * Math.PI * i) / Math.max(seedList.length, 1) - Math.PI / 2;
      anchors[seed] = {
        x: Math.cos(angle) * r,
        y: Math.sin(angle) * r,
      };
    });
    return anchors;
  }, [seedList, size]);

  async function toggleFullGraph() {
    if (showFull) {
      setShowFull(false);
      return;
    }
    if (!connection || !connection.search_id) return;
    setFullLoading(true);
    setFullError('');
    try {
      const { data } = await getConnectionStatus(connection.search_id, { full: true });
      setFullConnection(data);
      setShowFull(true);
    } catch (err) {
      setFullError(err.message);
    } finally {
      setFullLoading(false);
    }
  }

  async function toggleFullscreen() {
    const el = containerRef.current;
    if (!el) return;
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await el.requestFullscreen();
      }
    } catch (err) {
      console.error('No se pudo alternar pantalla completa:', err);
    }
  }

  useEffect(() => {
    function onFullscreenChange() {
      const active = !!document.fullscreenElement;
      setIsFullscreen(active);
      // Al cambiar a/desde pantalla completa el contenedor cambia de tamaño;
      // forzar una medición para que el canvas y el zoom se ajusten.
      requestAnimationFrame(() => {
        const node = containerRef.current;
        if (!node) return;
        const rect = node.getBoundingClientRect();
        if (rect.width > 0 || rect.height > 0) {
          setSize({ width: rect.width || 800, height: rect.height || 480 });
        }
      });
    }
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, []);

  useEffect(() => {
    function measure() {
      const node = containerRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      if (rect.width > 0 || rect.height > 0) {
        setSize({ width: rect.width || 800, height: rect.height || 480 });
      }
    }
    measure();
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const fitKeyRef = useRef(null);

  // El ajuste por defecto deja el grafo "alejado": bastante margen alrededor
  // (FIT_PADDING_RATIO) y nunca se acerca más de FIT_MAX_ZOOM, aunque al
  // inicio hayan pocos nodos (si no, la lupa se pega a un par de esferas).
  function fitGraph(transitionMs = 400) {
    const fg = graphRef.current;
    if (!fg || !graph.nodes.length) return;
    const bbox = fg.getGraphBbox();
    if (!bbox) return;
    const center = {
      x: (bbox.x[0] + bbox.x[1]) / 2,
      y: (bbox.y[0] + bbox.y[1]) / 2,
    };
    const spanX = Math.max(1e-9, bbox.x[1] - bbox.x[0]);
    const spanY = Math.max(1e-9, bbox.y[1] - bbox.y[0]);
    const pad = Math.min(size.width, size.height) * FIT_PADDING_RATIO;
    const zoom = Math.max(
      1e-12,
      Math.min((size.width - pad * 2) / spanX, (size.height - pad * 2) / spanY, FIT_MAX_ZOOM)
    );
    fg.centerAt(center.x, center.y, transitionMs);
    fg.zoom(zoom, transitionMs);
  }

  useEffect(() => {
    const fg = graphRef.current;
    if (!fg || !graph.nodes.length) return;
    const recKey = (seeds || []).join('|');
    const fitKey = `${activeConnection?.search_id || `recs:${recKey}`}:${showFull ? 'full' : 'simple'}:${size.width}x${size.height}`;
    if (fitKeyRef.current === fitKey) return;
    fitKeyRef.current = fitKey;
    // Ajusta la vista una vez por búsqueda (o por cambio de tamaño); las
    // actualizaciones del grafo en vivo NO reinician el zoom del usuario.
    fitGraph();
  }, [graph, size, activeConnection, seeds, showFull]);

  const wasDiscoveringRef = useRef(null);

  // Al terminar la búsqueda el grafo ya está completo: reencuadra la vista
  // por defecto con margen, en vez de quedarse pegado al par de nodos con que
  // arrancó la exploración.
  useEffect(() => {
    const was = wasDiscoveringRef.current;
    wasDiscoveringRef.current = discovering;
    if (was && !discovering) fitGraph(500);
  }, [discovering]);

  useEffect(() => {
    if (!graphRef.current) return;
    if (paused) return;
    graphRef.current.d3ReheatSimulation();
  }, [graph, paused]);

  // La simulación siempre se mantiene cálida (nunca se congela del todo: los
  // nodos siguen siendo arrastrables y la red fluye). La lib hace
  // d3ReheatSimulation() = alpha 1, así que la energía extra no fue el
  // problema; las fuerzas de colisión/repulsión sí: por eso tras terminar se
  // atenúan con el factor ``settle`` y los nodos ya no se repelen ni rebotan,
  // solo fluyen suavemente en su posición final. Al pausar sí se congela.
  useEffect(() => {
    if (paused) return undefined;
    const id = window.setInterval(() => {
      const fg = graphRef.current;
      if (fg) fg.d3ReheatSimulation();
    }, 1500);
    return () => window.clearInterval(id);
  }, [paused]);

  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    // La carga (repulsión eléctrica) también provoca el "rebote" constante al
    // recalentizar; una vez terminada la búsqueda se baja a lo mínimo para que
    // los nodos se queden en su lugar y solo fluyan.
    fg.d3Force('charge')?.strength(-50);
    fg.d3Force('link')?.distance(26);
  }, [discovering]);

  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    const anchorFor = (node) => {
      if (node.kind === 'bridge') return branchAnchors.center;
      return branchAnchors[node.branch] || branchAnchors.center;
    };
    const strengthFor = (node) => {
      if (node.kind === 'bridge') return 0.4;
      if (node.kind === 'seed') return 0.3;
      return 0.06;
    };
    const settle = discovering ? 1 : 0.06;
    const f = branchForce(
      (node) => {
        if (node.fx !== undefined || node.fy !== undefined) return [node.x, node.y];
        const a = anchorFor(node);
        return [a.x, a.y];
      },
      strengthFor,
      settle
    );
    fg.d3Force('branch', f);
    f.setNodes(graph.nodes);

    const coll = collideForce(
      (node) => (node.kind === 'bridge' ? 14 : node.kind === 'seed' ? 13 : 11),
      settle
    );
    fg.d3Force('collide', coll);
    coll.setNodes(graph.nodes);

    const sep = hierarchicalSeparate({ influence: 70, settle });
    fg.d3Force('hsep', sep);
    sep.setNodes(graph.nodes);

    if (!paused) fg.d3ReheatSimulation();
  }, [graph, branchAnchors, paused, discovering]);

  useEffect(() => {
    // Resetear el estado de vista solo cuando cambia la BÚSQUEDA (search_id)
    // o las semillas, no ante cada actualización de progreso por SSE (que llega
    // artista por artista y no debe descartar la selección ni el modo
    // completo/simplificado en vivo).
    setSelected(null);
    setShowFull(false);
    setFullConnection(null);
    setFullLoading(false);
    setFullError('');
  }, [connection?.search_id, seeds]);

  function branchColor(branch) {
    const idx = seedList.indexOf(branch);
    return idx >= 0 ? BRANCH_COLORS[idx % BRANCH_COLORS.length] : REC_COLOR;
  }

  const nodeCanvasObject = (node, ctx, globalScale) => {
    const label = node.label;
    const fontSize = 12 / globalScale;
    const nodeSize = node.kind === 'bridge' ? 11 : node.kind === 'seed' ? 9 : 7;

    if (!(node.id in nodeBirthRef.current)) {
      nodeBirthRef.current[node.id] = performance.now();
    }
    const ageMs = performance.now() - nodeBirthRef.current[node.id];
    const t = Math.min(1, ageMs / 350);
    const appearAlpha = 1 - Math.pow(1 - t, 3);
    ctx.globalAlpha = appearAlpha;

    const branchValue = branchColor(node.branch);
    let fill;
    let stroke;
    if (node.kind === 'bridge') {
      fill = BRIDGE_COLOR;
      stroke = '#ffffff';
    } else if (node.kind === 'seed') {
      fill = branchValue;
      stroke = '#ffffff';
    } else {
      fill = branchValue;
      stroke = branchValue;
    }

    if (node.frontier) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, nodeSize + 4, 0, 2 * Math.PI);
      ctx.strokeStyle = fill;
      ctx.lineWidth = 2 / globalScale;
      ctx.setLineDash([4 / globalScale, 3 / globalScale]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    ctx.beginPath();
    ctx.arc(node.x, node.y, nodeSize, 0, 2 * Math.PI);
    ctx.fillStyle = fill;
    ctx.fill();
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();

    ctx.font = `${fontSize}px 'Sora', sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, node.x, node.y + nodeSize + 2);

    ctx.globalAlpha = 1;
  };

  const measureCtxRef = useRef(null);

  function labelBox(node, globalScale) {
    const nodeSize = node.kind === 'bridge' ? 11 : node.kind === 'seed' ? 9 : 7;
    const fontSize = 12 / globalScale;
    if (!measureCtxRef.current) {
      measureCtxRef.current = document.createElement('canvas').getContext('2d');
    }
    measureCtxRef.current.font = `${fontSize}px 'Sora', sans-serif`;
    const halfW = Math.max(
      nodeSize + 3,
      measureCtxRef.current.measureText(node.label || '').width / 2 + 3
    );
    return {
      left: node.x - halfW,
      top: node.y - nodeSize - 3,
      right: node.x + halfW,
      bottom: node.y + nodeSize + 2 + fontSize + 3,
    };
  }

  function hitGlyph(node, wx, wy, globalScale) {
    const b = labelBox(node, globalScale);
    return wx >= b.left && wx <= b.right && wy >= b.top && wy <= b.bottom;
  }

  const nodePointerAreaPaint = (node, color, ctx, globalScale) => {
    ctx.fillStyle = color;
    const b = labelBox(node, globalScale);
    ctx.beginPath();
    ctx.roundRect(
      b.left,
      b.top,
      b.right - b.left,
      b.bottom - b.top,
      Math.min(6 / globalScale, (b.bottom - b.top) / 2)
    );
    ctx.fill();
  };

  const linkColor = (link) => {
    const targetId = typeof link.target === 'string' ? link.target : link.target.id;
    const branch = branchById[targetId];
    if (branch && seedList.includes(branch)) {
      return branchColor(branch);
    }
    return 'rgba(74, 222, 128, 0.45)';
  };

  const linkWidth = (link) => 1 + (link.score ?? 0) * 4;

  // Selección por proximidad real, no por el canvas de color oculto de la
  // librería: con nodos superpuestos ese canvas deja ocultas las esferas que
  // están debajo (solo la última pintada por píxel acepta el click). Acá se
  // calcula la distancia del click a TODAS las esferas y se elige la más
  // cercana dentro de la silueta de cada una (círculo + etiqueta), así cada
  // artista es clickeable por más solapado que esté.
  function selectNearestNode(event) {
    const fg = graphRef.current;
    if (!fg || !event || !graph.nodes.length) return;
    const world = clientToWorld(event.clientX, event.clientY);
    if (!world) return;
    const globalScale = fg.zoom();
    let best = null;
    let bestDist = Infinity;
    for (const node of graph.nodes) {
      if (!hitGlyph(node, world.x, world.y, globalScale)) continue;
      const dist = Math.hypot(node.x - world.x, node.y - world.y);
      if (dist < bestDist) {
        bestDist = dist;
        best = node;
      }
    }
    if (best) setSelected(best);
  }

  function clientToWorld(clientX, clientY) {
    const fg = graphRef.current;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!fg || !rect) return null;
    const world = fg.screen2GraphCoords(clientX - rect.left, clientY - rect.top);
    return world && Number.isFinite(world.x) && Number.isFinite(world.y) ? world : null;
  }

  function findNodeAt(clientX, clientY) {
    const fg = graphRef.current;
    if (!fg || !graph.nodes.length) return null;
    const world = clientToWorld(clientX, clientY);
    if (!world) return null;
    const globalScale = fg.zoom();
    let best = null;
    let bestDist = Infinity;
    for (const node of graph.nodes) {
      if (!hitGlyph(node, world.x, world.y, globalScale)) continue;
      const dist = Math.hypot(node.x - world.x, node.y - world.y);
      if (dist < bestDist) {
        bestDist = dist;
        best = node;
      }
    }
    return best;
  }

  // El arrastre por defecto de la librería usa el lienzo oculto de colores
  // (solo el nodo pintado encima por píxel responde) y el lienzo solo pinta
  // lo que nodePointerAreaPaint dibuja. Eso es lo que hacía que algunas
  // esferas no agarraran. Acá se detecta la esfera por geometría (círculo +
  // etiqueta) y se arrastra solo esa esfera: la simulación queda activa y las
  // fuerzas de enlace estiran la red alrededor, como una red neuronal.
  const dragStateRef = useRef(null);

  function handleDragStartCaptured(e) {
    if (dragStateRef.current || e.button !== 0) return;
    const canvas = containerRef.current?.querySelector('canvas');
    if (!canvas || e.target !== canvas) return;
    const node = findNodeAt(e.clientX, e.clientY);
    if (!node) return;
    const world = clientToWorld(e.clientX, e.clientY);
    if (!world) return;
    e.preventDefault();
    e.stopPropagation();
    dragStateRef.current = { pointerId: e.pointerId, node, world, moved: false };
    node.fx = world.x;
    node.fy = world.y;
    graphRef.current?.d3AlphaTarget(0.3);
    graphRef.current?.resetCountdown?.();
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
  }

  function handleDragMoveCaptured(e) {
    const st = dragStateRef.current;
    if (!st || e.pointerId !== st.pointerId) return;
    const fg = graphRef.current;
    if (!fg) return;
    const world = clientToWorld(e.clientX, e.clientY);
    if (!world) return;
    const dx = world.x - st.world.x;
    const dy = world.y - st.world.y;
    st.world = world;
    if (Math.hypot(dx, dy) > 0.0001) st.moved = true;
    if (graph.nodes.includes(st.node)) {
      st.node.fx = world.x;
      st.node.fy = world.y;
    }
    fg.d3AlphaTarget(0.3);
    fg.resetCountdown?.();
    e.preventDefault();
    e.stopPropagation();
  }

  function endDrag(pointerId, selectOnClick) {
    const st = dragStateRef.current;
    if (!st || st.pointerId !== pointerId) return;
    dragStateRef.current = null;
    const fg = graphRef.current;
    const canvas = containerRef.current?.querySelector('canvas');
    if (canvas && canvas.hasPointerCapture?.(st.pointerId)) {
      try { canvas.releasePointerCapture(st.pointerId); } catch (err) { /* ignore */ }
    }
    if (fg) {
      fg.d3AlphaTarget(0);
      fg.resetCountdown?.();
    }
    // Mientras se explora la red sigue viva: al soltar el nodo se libera y
    // las fuerzas lo recuperan. Cuando la búsqueda ya terminó, en cambio, se
    // PINNEA en el punto donde quedó (fx/fy fijos): la fuerza de rama lo deja
    // quieto donde lo dejó el usuario y el grafo se asienta una sola vez.
    // Sin esto, al terminar, la rama lo arrastra de vuelta a su ancla y el
    // grafo parece "no soltar" el nodo.
    if (discovering) {
      st.node.fx = undefined;
      st.node.fy = undefined;
    } else {
      st.node.fx = st.node.x;
      st.node.fy = st.node.y;
    }
    if (selectOnClick && !st.moved && graph.nodes.includes(st.node)) setSelected(st.node);
  }

  function handleDragEndCaptured(e) {
    endDrag(e.pointerId, true);
  }

  function handleDragCancelCaptured(e) {
    endDrag(e.pointerId, false);
  }

  function zoomBy(factor) {
    const fg = graphRef.current;
    if (!fg) return;
    const current = fg.zoom();
    if (typeof current !== 'number' || !Number.isFinite(current)) return;
    fg.zoom(current * factor, 250);
  }

  return (
    <div
      className="graph-container"
      ref={containerRef}
      onPointerDownCapture={handleDragStartCaptured}
      onPointerMoveCapture={handleDragMoveCaptured}
      onPointerUpCapture={handleDragEndCaptured}
      onPointerCancelCapture={handleDragCancelCaptured}
      onContextMenuCapture={(e) => {
        const node = findNodeAt(e.clientX, e.clientY);
        if (node) {
          e.preventDefault();
          setSelected(node);
        }
      }}
    >
      {isFound && (
        <div className="graph-toggle">
          <button
            type="button"
            onClick={toggleFullGraph}
            disabled={fullLoading}
          >
            {fullLoading
              ? 'Cargando grafo completo…'
              : showFull
                ? 'Ver grafo simplificado'
                : 'Ver grafo completo'}
          </button>
          {fullError && <p className="graph-toggle-error">{fullError}</p>}
        </div>
      )}
      <ForceGraph2D
        ref={graphRef}
        graphData={graph}
        width={size.width}
        height={size.height}
        nodeRelSize={6}
        enableNodeDrag={false}
        cooldownTicks={400}
        cooldownTime={12000}
        d3VelocityDecay={0.8}
        d3AlphaDecay={0.01}
        onEngineStop={() => {
          if (!paused) graphRef.current?.d3ReheatSimulation();
        }}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkWidth={linkWidth}
        linkColor={linkColor}
        linkDirectionalParticles={(link) => (link.score ? 1 : 0)}
        linkDirectionalParticleWidth={(link) => (link.score ?? 0) * 2}
        linkDirectionalParticleColor={linkColor}
        onNodeClick={(node, ev) => selectNearestNode(ev)}
        onBackgroundClick={(ev) => selectNearestNode(ev)}
      />
      <div className="graph-zoom">
        <button
          type="button"
          className="graph-zoom-btn"
          onClick={() => zoomBy(ZOOM_STEP)}
          aria-label="Acercar"
          title="Acercar"
        >
          +
        </button>
        <button
          type="button"
          className="graph-zoom-btn"
          onClick={() => zoomBy(1 / ZOOM_STEP)}
          aria-label="Alejar"
          title="Alejar"
        >
          −
        </button>
      </div>
      <div className="graph-fullscreen">
        <button
          type="button"
          className="graph-zoom-btn"
          onClick={toggleFullscreen}
          aria-label={isFullscreen ? 'Salir de pantalla completa' : 'Agrandar (pantalla completa)'}
          title={isFullscreen ? 'Salir de pantalla completa' : 'Agrandar (pantalla completa)'}
        >
          {isFullscreen ? '✕' : '⛶'}
        </button>
      </div>
      {selected && selectedFacts && (
        <aside className="node-details">
          <h3>{selected.label}</h3>

          <div className="node-details-badge">
            <span
              className="node-details-swatch"
              style={{ backgroundColor: selectedFacts.hex }}
            />
            <p className={selected.kind}>{selectedFacts.kindLabel}</p>
          </div>

          <dl className="node-facts">
            <div className="node-fact">
              <dt>Iteración (nivel BFS)</dt>
              <dd>{selected.depth !== undefined ? selected.depth : '—'}</dd>
            </div>
            <div className="node-fact">
              <dt>Rama / semilla raíz</dt>
              <dd>{selected.branch || 'centro del grafo'}</dd>
            </div>
            <div className="node-fact">
              <dt>Vecinos directos (grado)</dt>
              <dd>{selectedFacts.degree}</dd>
            </div>
            {selectedFacts.isExploration && (
              <>
                <div className="node-fact">
                  <dt>Descubrió (descendientes)</dt>
                  <dd>{selectedFacts.children}</dd>
                </div>
                <div className="node-fact">
                  <dt>Almacén del BFS</dt>
                  <dd>{selectedFacts.frontier ? 'Frontera' : 'Nodo interior'}</dd>
                </div>
                {selectedFacts.discoverIndex !== null && (
                  <div className="node-fact">
                    <dt>N.º de descubrimiento</dt>
                    <dd>
                      #{selectedFacts.discoverIndex} de {selectedFacts.totalVisited}
                    </dd>
                  </div>
                )}
              </>
            )}
            <div className="node-fact">
              <dt>Identificador</dt>
              <dd>
                <code>{selected.id}</code>
              </dd>
            </div>
            <div className="node-fact">
              <dt>Color (hex)</dt>
              <dd>
                <code>{selectedFacts.hex}</code>
              </dd>
            </div>
          </dl>

          {selected.kind === 'recommendation' && (
            <>
              <p>
                Posible gusto: <strong>{selected.score}%</strong>
              </p>
              <p>Conecta con:</p>
              <ul>
                {selected.matchedSeeds.map(
                  (m) =>
                    m && m.artist && m.album && (
                      <li key={`${m.artist}|${m.album}`}>
                        {`${m.artist} — ${m.album} (${m.score}%)`}
                      </li>
                    )
                )}
              </ul>
            </>
          )}
          <button type="button" onClick={() => setSelected(null)}>
            Cerrar
          </button>
        </aside>
      )}
    </div>
  );
}