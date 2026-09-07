import { useEffect, useMemo, useRef, useState } from 'react';
import { ForceGraph2D } from 'react-force-graph';

const SEED_COLOR = '#58a6ff';
const REC_COLOR = '#f0a3ff';
const BRIDGE_COLOR = '#3fb950';
const BRANCH_COLORS = ['#f0a3ff', '#ffab70', '#ffe27a', '#a6e3ff', '#7cf7c4', '#c9b8ff'];
const MAX_CONNECTION_NODES = 400;
const CENTER_RADIUS = 160;

function rootOf(name, cameFrom) {
  const seen = new Set();
  let cur = name;
  while (cameFrom[cur] && !seen.has(cur)) {
    seen.add(cur);
    cur = cameFrom[cur];
  }
  return cur;
}

function layoutCenter(nodes, posCache) {
  const n = nodes.length;
  if (n === 0) return;
  const angleStep = (2 * Math.PI) / Math.max(n, 1);
  const placed = [];
  nodes.forEach((node, i) => {
    const cached = posCache && posCache.current[node.id];
    if (cached) {
      node.x = cached.x;
      node.y = cached.y;
      return;
    }
    const angle = i * angleStep;
    const r = n > 4 ? CENTER_RADIUS + (i % 5) * 12 : CENTER_RADIUS * (i + 1) * 0.6;
    node.x = Math.cos(angle) * r;
    node.y = Math.sin(angle) * r;
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

  function ensureNode(id, label, kind) {
    if (!byKey.has(id)) {
      const node = { id, label, kind };
      byKey.set(id, node);
      nodes.push(node);
    }
    return byKey.get(id);
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
      'recommendation'
    );
    recNode.score = rec.score;
    recNode.matchedSeeds = matches;

    for (const matched of matches) {
      const seedId = `seed:${matched.artist}|${matched.album}`;
      ensureNode(seedId, `${matched.artist} — ${matched.album}`, 'seed');
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
    ensureNode(`seed:${artist}|`, artist, 'seed');
  }

  layoutCenter(nodes, posCache);
  return { nodes, links };
}

function buildConnectionGraph(connection, posCache) {
  const {
    bridge_artist = null,
    seed_artists = [],
    visited_per_seed = {},
    frontier_per_seed = {},
    came_from = {},
    path = null,
  } = connection;

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

  if (path) {
    for (const [seed, chain] of Object.entries(path)) {
      for (let i = 0; i < chain.length; i += 1) {
        const name = chain[i];
        const kind = name === bridge_artist ? 'bridge' : i === 0 ? 'seed' : 'hop';
        ensureNode(name, kind, seed);
      }
      for (let i = 0; i < chain.length - 1; i += 1) {
        links.push({ source: chain[i], target: chain[i + 1] });
      }
    }
    layoutCenter(nodes, posCache);
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
    for (const name of visited_per_seed[seed] || []) {
      if (!seen.has(name)) {
        seen.add(name);
        discovered.push(name);
      }
    }
  }

  const included = discovered.slice(0, MAX_CONNECTION_NODES);
  const includedSet = new Set(included);

  for (const name of included) {
    const kind = seedSet.has(name) ? 'seed' : 'hop';
    const branch = seedSet.has(name) ? name : rootOf(name, came_from);
    const node = ensureNode(name, kind, branch);
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

  layoutCenter(nodes, posCache);
  return { nodes, links };
}

export default function GraphView({ recommendations, seeds, connection }) {
  const graphRef = useRef(null);
  const containerRef = useRef(null);
  const posCacheRef = useRef({});
  const [size, setSize] = useState({ width: 800, height: 480 });
  const [selected, setSelected] = useState(null);

  const graph = useMemo(
    () =>
      connection
        ? buildConnectionGraph(connection, posCacheRef)
        : buildGraph(recommendations || [], seeds || [], posCacheRef),
    [connection, recommendations, seeds]
  );

  const seedList = useMemo(() => {
    if (connection && connection.seed_artists) return connection.seed_artists;
    return seeds || [];
  }, [connection, seeds]);

  const branchById = useMemo(() => {
    const map = {};
    for (const node of graph.nodes) map[node.id] = node.branch || node.id;
    return map;
  }, [graph]);

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

  useEffect(() => {
    if (graphRef.current && graph.nodes.length) {
      graphRef.current.zoomToFit(400, 80);
    }
  }, [graph, size]);

  useEffect(() => {
    setSelected(null);
  }, [recommendations, connection, seeds]);

  function branchColor(branch) {
    const idx = seedList.indexOf(branch);
    return idx >= 0 ? BRANCH_COLORS[idx % BRANCH_COLORS.length] : REC_COLOR;
  }

  const nodeCanvasObject = (node, ctx, globalScale) => {
    const label = node.label;
    const fontSize = 12 / globalScale;
    const nodeSize = node.kind === 'bridge' ? 11 : node.kind === 'seed' ? 9 : 7;

    const branchValue = branchColor(node.branch);
    let fill;
    let stroke;
    if (node.kind === 'bridge') {
      fill = BRIDGE_COLOR;
      stroke = '#56d364';
    } else if (node.kind === 'seed') {
      fill = SEED_COLOR;
      stroke = node.branch ? branchValue : '#79c0ff';
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

    ctx.font = `${fontSize}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#e8e6e3';
    ctx.fillText(label, node.x, node.y + nodeSize + 2);
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
    return 'rgba(88, 166, 255, 0.45)';
  };

  const linkWidth = (link) => 1 + (link.score ?? 0) * 4;

  return (
    <div className="graph-container" ref={containerRef}>
      <ForceGraph2D
        ref={graphRef}
        graphData={graph}
        width={size.width}
        height={size.height}
        nodeRelSize={6}
        cooldownTicks={100}
        cooldownTime={3000}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkWidth={linkWidth}
        linkColor={linkColor}
        linkDirectionalParticles={(link) => (link.score ? 1 : 0)}
        linkDirectionalParticleWidth={(link) => (link.score ?? 0) * 2}
        linkDirectionalParticleColor={linkColor}
        onNodeClick={(node) => setSelected(node)}
      />
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