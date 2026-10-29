import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { nodeHash, portfolioHash, recipesHash, searchable, shockHash } from "../../lib/valueChain";
import type { VcNodeRef } from "../../types";
import { ExposureView } from "./ExposureView";
import { FootprintView } from "./FootprintView";
import { NodeView } from "./NodeView";
import { PortfolioView } from "./PortfolioView";
import { RecipeForm, RecipeList } from "./RecipesView";
import { ShockView } from "./ShockView";
import { TreeView } from "./TreeView";
import { useVcQuery } from "./useVcQuery";

const VIEWS = [
  [undefined, "Node page"],
  ["tree", "Upstream tree"],
  ["footprint", "Footprint"],
  ["exposure", "Revenue exposure"],
  ["shock", "Shocks"],
] as const;

/** Search box over sectors and regions; each hit links to its node page. */
function Picker({ onError }: { onError: (message: string | null) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<VcNodeRef[] | null>(null);

  useEffect(() => {
    if (!searchable(q)) {
      setHits(null);
      onError(null);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      api
        .valueChainSearch(q)
        .then((r) => {
          if (!live) return;
          setHits(r.items);
          onError(null);
        })
        .catch((err) => live && onError(apiMessage(err)));
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [q, onError]);

  return (
    <section className="card" aria-label="Pick a node">
      <label className="field-label">
        Sector or region
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. copper, DE, RoW Asia-Pacific" />
      </label>
      {hits !== null &&
        (hits.length === 0 ? (
          <p className="muted" role="status">
            No sector or region matches.
          </p>
        ) : (
          <ul className="vc-hits">
            {hits.map((h) => (
              <li key={h.node_id}>
                <a href={nodeHash(h.node_id)}>
                  {h.sector} <span className="muted">· {h.region_label}</span>
                </a>
              </li>
            ))}
          </ul>
        ))}
    </section>
  );
}

/** `#/valueChain[/<node id>[/tree|/footprint|/shock[/<portfolio id>]]]`: picker on top, then the chosen view; `#/valueChain/portfolio[/<id>]`: the
 * Portfolio view. App keys this on the route, so a new node or view mounts fresh: no title or data carries over. */
export function ValueChainExplorer({ params }: { params: string[] }) {
  if (params[0] === "portfolio") {
    return (
      <div className="page">
        <nav className="vc-crumb" aria-label="Breadcrumb">
          <a href="#/valueChain">Value Chain Explorer</a>
        </nav>
        <h1>Portfolio</h1>
        <p className="help-text">Which sectors and regions a portfolio's companies sit on, what their supply chains draw on, and what one million euro invested carries along the&nbsp;chain.</p>
        <PortfolioView id={params[1]} />
      </div>
    );
  }
  if (params[0] === "recipes") return <Recipes params={params.slice(1)} />;
  return <NodeExplorer params={params} />;
}

/** `#/valueChain/recipes`, `…/recipes/new`, `…/recipes/<rid>` and `…/recipes/<rid>/exposure[/<from id>]`. */
function Recipes({ params }: { params: string[] }) {
  const [rid, sub, from] = params;
  const [title, setTitle] = useState<string | null>(null);
  return (
    <div className="page">
      <nav className="vc-crumb" aria-label="Breadcrumb">
        <a href="#/valueChain">Value Chain Explorer</a> · <a href={recipesHash()}>Recipes</a>
      </nav>
      <h1>{rid ? (title ?? rid) : "Recipes"}</h1>
      <p className="help-text">A recipe describes one product more finely than its sector: what it buys, as shares of its&nbsp;cost.</p>
      {!rid ? (
        <RecipeList />
      ) : sub === "exposure" ? (
        <ExposureView target={`recipe:${rid}`} from={from} onTitle={setTitle} />
      ) : (
        <RecipeForm key={rid} rid={rid === "new" ? null : rid} onTitle={setTitle} />
      )}
    </div>
  );
}

function NodeExplorer({ params }: { params: string[] }) {
  const [id, sub, from] = params;
  const view = sub === "tree" || sub === "footprint" || sub === "shock" || sub === "exposure" ? sub : undefined;
  const [searchError, setSearchError] = useState<string | null>(null);
  // A node view names its node here once loaded; the id stands in until then.
  const [title, setTitle] = useState<string | null>(null);
  // The Shocks view's portfolio, so its tab links back to the lens the view shows (it updates the URL by replaceState).
  const [shockPortfolio, setShockPortfolio] = useState(view === "shock" ? (from ?? "") : "");
  // Before a node is picked, the status call says whether the data is built and gives the caveat.
  const status = useVcQuery(() => (id ? null : api.valueChainStatus()), [id]);
  const message = status.error ?? searchError;

  return (
    <div className="page">
      {id ? (
        <>
          <nav className="vc-crumb" aria-label="Breadcrumb">
            <a href="#/valueChain">Value Chain Explorer</a>
          </nav>
          <h1>{title ?? id}</h1>
        </>
      ) : (
        <h1>Value Chain Explorer</h1>
      )}
      <p className="help-text">Pick a sector in a region to see who it buys from, who it sells to, and what it takes to make one euro of its&nbsp;output.</p>
      {message && (
        <p className="error-text" role="alert">
          {message}
        </p>
      )}
      {/* A failed status call means the data is not there to search. */}
      {!(status.error && !id) && <Picker onError={setSearchError} />}
      {!id ? (
        <>
          {!status.error && <p className="muted">Pick a sector and region.</p>}
          <p>
            <a href={portfolioHash()}>Portfolio</a> <span className="muted">· see a portfolio's holdings on the value chain</span>
          </p>
          <p>
            <a href={recipesHash()}>Recipes</a> <span className="muted">· product recipes and who earns from them</span>
          </p>
          {status.data && <p className="help-text vc-note">{status.data.caveat}</p>}
        </>
      ) : (
        <>
          <nav className="sub-nav" aria-label="Views">
            {VIEWS.map(([v, label]) => (
              <a key={label} href={v === "shock" ? shockHash(id, shockPortfolio) : nodeHash(id, v)} className={v === view ? "nav-tab active" : "nav-tab"} aria-current={v === view ? "page" : undefined}>
                {label}
              </a>
            ))}
            <a href={portfolioHash()} className="nav-tab">
              Portfolio
            </a>
          </nav>
          {view === "tree" ? (
            <TreeView id={id} onTitle={setTitle} />
          ) : view === "exposure" ? (
            <ExposureView target={id} from={from} onTitle={setTitle} />
          ) : view === "footprint" ? (
            <FootprintView id={id} onTitle={setTitle} />
          ) : view === "shock" ? (
            <ShockView id={id} onTitle={setTitle} initialPortfolio={from} onPortfolio={setShockPortfolio} />
          ) : (
            <NodeView id={id} onTitle={setTitle} />
          )}
        </>
      )}
    </div>
  );
}
