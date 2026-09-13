import { useEffect, useMemo, useRef, useState } from 'react';
import { ForceGraph2D } from 'react-force-graph';
import { getConnectionStatus } from '../api/connections.js';

const REC_COLOR = '#ffffff';
const BRIDGE_COLOR = '#4ade80';
const BRANCH_COLORS = [
  '#0072b2',
  '#e69f00',
  '#009e73',
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

function branchForce(accessor, strength) {
  let nodes = [];
  function force(alpha) {
    for (const node of nodes) {
      if (!node) continue;
      const [tx, ty] = accessor(node);
      const k = strength(node);
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

function collideForce(getRadius) {
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
        const k = alpha;
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

  for (const [name, parent] of Object.entries(came_from)) {
    if (includedSet.has(name) && includedSet.has(parent)) {
      links.push({ source: parent, target: name });
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
      const data = await getConnectionStatus(connection.search_id, { full: true });
      setFullConnection(data);
      setShowFull(true);
    } catch (err) {
      setFullError(err.message);
    } finally {
      setFullLoading(false);
    }
  }

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

  useEffect(() => {
    const fg = graphRef.current;
    if (!fg || !graph.nodes.length) return;
    const recKey = (seeds || []).join('|');
    const fitKey = `${activeConnection?.search_id || `recs:${recKey}`}:${showFull ? 'full' : 'simple'}:${size.width}x${size.height}`;
    if (fitKeyRef.current === fitKey) return;
    fitKeyRef.current = fitKey;
    // Ajusta la vista una vez por búsqueda (o por cambio de tamaño); las
    // actualizaciones del grafo en vivo NO reinician el zoom del usuario.
    fg.zoomToFit(400, 80);
  }, [graph, size, activeConnection, seeds, showFull]);

  useEffect(() => {
    if (!graphRef.current) return;
    if (paused) return;
    graphRef.current.d3ReheatSimulation();
  }, [graph, paused]);

  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-12);
    fg.d3Force('link')?.distance(26);
  }, []);

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
    const f = branchForce(
      (node) => {
        if (node.fx !== undefined || node.fy !== undefined) return [node.x, node.y];
        const a = anchorFor(node);
        return [a.x, a.y];
      },
      strengthFor
    );
    fg.d3Force('branch', f);
    f.setNodes(graph.nodes);

    const coll = collideForce(
      (node) => (node.kind === 'bridge' ? 12 : node.kind === 'seed' ? 10 : 8)
    );
    fg.d3Force('collide', coll);
    coll.setNodes(graph.nodes);

    if (!paused) fg.d3ReheatSimulation();
  }, [graph, branchAnchors, paused]);

  useEffect(() => {
    setSelected(null);
    setShowFull(false);
    setFullConnection(null);
    setFullLoading(false);
    setFullError('');
  }, [connection, seeds]);

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

  const nodePointerAreaPaint = (node, color, ctx) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, 12, 0, 2 * Math.PI);
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

  function zoomBy(factor) {
    const fg = graphRef.current;
    if (!fg) return;
    const current = fg.zoom();
    if (typeof current !== 'number' || !Number.isFinite(current)) return;
    fg.zoom(current * factor, 250);
  }

  return (
    <div className="graph-container" ref={containerRef}>
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
        cooldownTicks={400}
        cooldownTime={12000}
        d3VelocityDecay={0.8}
        d3AlphaDecay={0.01}
        onEngineStop={() => {
          if (discovering) graphRef.current?.d3ReheatSimulation();
        }}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkWidth={linkWidth}
        linkColor={linkColor}
        linkDirectionalParticles={(link) => (link.score ? 1 : 0)}
        linkDirectionalParticleWidth={(link) => (link.score ?? 0) * 2}
        linkDirectionalParticleColor={linkColor}
        onNodeClick={(node) => setSelected(node)}
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
      {selected && (
        <aside className="node-details">
          <h3>{selected.label}</h3>
          <p className={selected.kind}>
            {selected.kind === 'seed'
              ? 'Semilla'
              : selected.kind === 'bridge'
                ? 'Artista puente'
                : selected.kind === 'hop'
                  ? 'Nodo intermedio'
                  : 'Recomendación'}
          </p>
          {selected.depth !== undefined && (
            <p>Iteración: {selected.depth}</p>
          )}
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