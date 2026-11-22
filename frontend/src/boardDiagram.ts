// The diagram frame's page (board-diagram.html): Mermaid draws one diagram here, inside a sandboxed iframe whose
// Content-Security-Policy blocks every outside load (spec agent-board, Amendment 1d/1e: the frame is the security
// boundary). Plain TypeScript, no React. Mermaid and ELK load with a dynamic import() on the first draw (AC-55).
import { themedSource, type DiagramTheme, type FromFrame, type ToFrame } from "./lib/board";

type Mermaid = typeof import("mermaid").default;
let mermaid: Promise<Mermaid> | null = null;

function loadMermaid(): Promise<Mermaid> {
  mermaid ??= Promise.all([import("mermaid"), import("@mermaid-js/layout-elk")]).then(([m, elk]) => {
    m.default.registerLayoutLoaders(elk.default);
    return m.default;
  });
  return mermaid;
}

const root = document.getElementById("diagram")!;
const reply = (msg: FromFrame) => window.parent.postMessage(msg, location.origin);
let n = 0;

function config(t: DiagramTheme) {
  const g = t.groups;
  // Mind map section n (from 0) takes cScale n + 1, so the first branch gets the first group colour.
  const slot = (i: number) => g[(i + 3) % 4];
  const scale = (k: keyof (typeof g)[0]) => Object.fromEntries([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((i) => [i, slot(i)[k]]));
  const edges = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => `.section-edge-${i} { stroke: ${slot(i + 1).stroke}; }`).join(" ");
  const fill = scale("fill"), stroke = scale("stroke"), text = scale("text");
  return {
    startOnLoad: false,
    securityLevel: "strict" as const,
    theme: "base" as const,
    layout: "elk",
    look: "classic" as const,
    suppressErrorRendering: true,
    fontFamily: t.font,
    elk: { mergeEdges: false, nodePlacementStrategy: "NETWORK_SIMPLEX" as const },
    flowchart: { curve: "basis" as const, padding: 14, nodeSpacing: 36, rankSpacing: 52, htmlLabels: true },
    themeCSS: `.node rect, .node path.basic { rx: 8px; ry: 8px; } .edgeLabel, .edgeLabel p { color: ${t.muted}; background: ${t.panel} !important; }
      .mindmap-node line { display: none; } .mindmap-node rect, .mindmap-node path { rx: 8px; ry: 8px; } .actor { rx: 8px; ry: 8px; }
      .flowchart-link { stroke-width: 1.5px; } .mindmap-edges .edge { stroke-width: 2px !important; } ${edges}
      .section-root text, .section-root .nodeLabel { fill: ${t.panel} !important; color: ${t.panel} !important; font-weight: 600; }`,
    themeVariables: {
      darkMode: t.dark,
      fontFamily: t.font,
      fontSize: "14px",
      background: t.panel,
      primaryColor: t.well,
      primaryBorderColor: t.line,
      primaryTextColor: t.text,
      secondaryColor: g[0].fill,
      tertiaryColor: t.well,
      lineColor: t.muted,
      textColor: t.text,
      edgeLabelBackground: t.panel,
      clusterBkg: t.well,
      clusterBorder: t.hair,
      titleColor: t.text,
      actorBkg: g[0].fill,
      actorBorder: g[0].stroke,
      actorTextColor: g[0].text,
      actorLineColor: t.line,
      signalColor: t.muted,
      signalTextColor: t.text,
      labelBoxBkgColor: t.well,
      labelBoxBorderColor: t.line,
      labelTextColor: t.text,
      loopTextColor: t.text,
      noteBkgColor: t.well,
      noteBorderColor: t.line,
      noteTextColor: t.text,
      activationBkgColor: g[0].fill,
      activationBorderColor: g[0].stroke,
      sequenceNumberColor: t.panel,
      ...Object.fromEntries(Object.entries(fill).map(([i, v]) => [`cScale${i}`, v])),
      ...Object.fromEntries(Object.entries(stroke).map(([i, v]) => [`cScalePeer${i}`, v])),
      ...Object.fromEntries(Object.entries(text).map(([i, v]) => [`cScaleLabel${i}`, v])),
      git0: t.text,
      gitBranchLabel0: t.panel,
      quadrant1Fill: g[0].fill,
      quadrant2Fill: g[1].fill,
      quadrant3Fill: t.well,
      quadrant4Fill: g[2].fill,
      quadrant1TextFill: g[0].text,
      quadrant2TextFill: g[1].text,
      quadrant3TextFill: t.muted,
      quadrant4TextFill: g[2].text,
      quadrantPointFill: t.text,
      quadrantPointTextFill: t.text,
      quadrantXAxisTextFill: t.muted,
      quadrantYAxisTextFill: t.muted,
      quadrantTitleFill: t.text,
      quadrantInternalBorderStrokeFill: t.hair,
      quadrantExternalBorderStrokeFill: t.line,
    },
  };
}

/** Mermaid's SVG as nodes, with every `<a>` replaced by its children and every `href` and `xlink:href` removed
 * (Amendment 1b). A <template> parses without running anything or loading anything. */
function linkFree(svg: string): DocumentFragment {
  const t = document.createElement("template");
  t.innerHTML = svg;
  for (const a of [...t.content.querySelectorAll("a")]) a.replaceWith(...a.childNodes);
  for (const el of t.content.querySelectorAll("*")) {
    for (const attr of [...el.attributes]) if (attr.localName === "href") el.removeAttributeNode(attr);
  }
  return t.content;
}

const height = () => Math.ceil(root.getBoundingClientRect().height);

async function draw(source: string, theme: DiagramTheme) {
  document.documentElement.style.colorScheme = theme.dark ? "dark" : "light";
  document.body.style.background = theme.panel;
  document.body.style.color = theme.text;
  document.body.style.fontFamily = theme.font;
  try {
    const m = await loadMermaid();
    await document.fonts.ready;
    m.initialize(config(theme));
    const { svg } = await m.render(`d${++n}`, themedSource(source, theme));
    root.replaceChildren(linkFree(svg));
    reply({ type: "drawn", height: height() });
  } catch (e) {
    root.replaceChildren();
    reply({ type: "error", message: String((e as Error)?.message ?? e) });
  }
}

window.addEventListener("message", (e: MessageEvent<ToFrame>) => {
  if (e.source !== window.parent || e.origin !== location.origin) return;
  if (e.data?.type === "draw" && typeof e.data.source === "string") void draw(e.data.source, e.data.theme);
});

// The frame's width follows the board; tell the Board when the drawing's height changes.
new ResizeObserver(() => {
  if (root.firstChild) reply({ type: "drawn", height: height() });
}).observe(root);
