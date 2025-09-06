from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .colors import color_for


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>py2dag Plan</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif; margin: 0; padding: 0; }
    header { padding: 10px 16px; background: #111; color: #eee; font-size: 14px; }
    #container { padding: 12px; }
    svg { width: 100%; height: 80vh; border: 1px solid #ddd; margin: 10px; padding: 10px; }
    .node rect { stroke: #666; fill: #fff; rx: 4; ry: 4; }
    .node.note rect { fill: #fff8dc; }
    .edgePath path { stroke: #333; fill: none; stroke-width: 1.2px; }
  </style>
  <script src="https://d3js.org/d3.v5.min.js"></script>
  <script src="https://unpkg.com/dagre-d3@0.6.4/dist/dagre-d3.min.js"></script>
</head>
<body>
  <header>py2dag — Dagre graph</header>
  <div id="container">
    <svg><g/></svg>
  </div>
  <script>
    const plan = __PLAN_JSON__;
    const COLOR_MAP = __COLOR_MAP__;

    function showMessage(msg) {
      const el = document.getElementById('container');
      el.innerHTML = '<div style="padding:12px;color:#b00;background:#fff3f3;border-top:1px solid #f0caca;">' +
        msg + '</div>' +
        '<pre style="margin:0;padding:12px;white-space:pre-wrap;">' +
        (typeof plan === 'object' ? JSON.stringify(plan, null, 2) : '') + '</pre>';
    }

    if (typeof window.d3 === 'undefined' || typeof window.dagreD3 === 'undefined') {
      showMessage('Failed to load Dagre assets (d3/dagre-d3). Check internet connectivity or vendor the JS locally.');
    } else {
      try {
        const g = new dagreD3.graphlib.Graph({ multigraph: true })
          .setGraph({ rankdir: 'TB', nodesep: 30, ranksep: 40 });
        // Ensure edges have an object for labels/attrs to avoid TypeErrors
        g.setDefaultEdgeLabel(() => ({}));

        // Add op nodes with basic styling for control nodes
        (plan.ops || []).forEach(op => {
          let label = op.op;
          let klass = 'op';
          if (op.op === 'COND.eval') {
            const kind = (op.args && op.args.kind) || 'if';
            label = (kind.toUpperCase()) + ' ' + (op.args && op.args.expr ? op.args.expr : '');
            klass = 'note';
          } else if (op.op === 'ITER.eval') {
            label = 'FOR ' + (op.args && op.args.expr ? op.args.expr : '');
            klass = 'note';
          } else if (op.op === 'PHI') {
            label = 'PHI' + (op.args && op.args.var ? ` (${op.args.var})` : '');
            klass = 'note';
          }
          const color = COLOR_MAP[op.op] || '#fff';
          g.setNode(op.id, { label, class: klass, padding: 8, style: 'fill: ' + color });
        });

        // Add output nodes and edges from source to output
        (plan.outputs || []).forEach(out => {
          const outId = `out:${out.as}`;
          const ocolor = COLOR_MAP['output'] || '#fff';
          g.setNode(outId, { label: out.as, class: 'note', padding: 8, style: 'fill: ' + ocolor });
          g.setEdge(out.from, outId);
        });

        // Build index for source op lookup
        const opById = {};
        (plan.ops || []).forEach(op => { opById[op.id] = op; });

        // Add dependency edges between ops with labels
        (plan.ops || []).forEach(op => {
          const depLabels = op.dep_labels || [];
          const seen = new Set();
          (op.deps || []).forEach((dep, idx) => {
            const pair = dep + '->' + op.id;
            if (seen.has(pair)) return; seen.add(pair);
            const src = opById[dep];
            let edgeLabel = (depLabels[idx] || '').toString();
            // Special-cases override when no explicit label was provided
            if (!edgeLabel) {
              if (op.op === 'PACK.dict' && op.args && Array.isArray(op.args.keys)) {
                edgeLabel = (op.args.keys[idx] || '').toString();
              } else if (src && src.op === 'COND.eval') {
                // For IF, label branches as then/else based on dest id; for WHILE keep 'cond'
                const kind = src.args && src.args.kind;
                if (kind === 'if') {
                  if ((op.id || '').includes('@then')) edgeLabel = 'then';
                  else if ((op.id || '').includes('@else')) edgeLabel = 'else';
                  else edgeLabel = 'cond';
                } else {
                  edgeLabel = 'cond';
                }
              } else if (src && src.op === 'ITER.eval') {
                edgeLabel = (src.args && src.args.target) ? src.args.target : 'iter';
              } else {
                edgeLabel = dep; // fallback: SSA id
              }
            }
            g.setEdge(dep, op.id, { label: edgeLabel });
          });
        });

        const svg = d3.select('svg');
        const inner = svg.select('g');
        const render = new dagreD3.render();
        render(inner, g);

        // Centering
        const { width, height } = g.graph();
        const svgWidth = document.querySelector('svg').clientWidth;
        const xCenterOffset = (svgWidth - width) / 2;
        inner.attr('transform', 'translate(' + Math.max(10, xCenterOffset) + ', 20)');
        svg.attr('height', height + 40);
      } catch (e) {
        showMessage('Failed to render Dagre graph: ' + e);
      }
    }
  </script>
</body>
</html>
"""


def export(plan: Dict[str, Any], filename: str = "plan.html") -> str:
    """Export the plan as an interactive HTML using Dagre (via dagre-d3).

    Returns the written filename.
    """
    color_map = {op["op"]: color_for(op["op"]) for op in plan.get("ops", [])}
    color_map["output"] = color_for("output")
    html = HTML_TEMPLATE.replace("__PLAN_JSON__", json.dumps(plan))
    html = html.replace("__COLOR_MAP__", json.dumps(color_map))
    path = Path(filename)
    path.write_text(html, encoding="utf-8")
    return str(path)
