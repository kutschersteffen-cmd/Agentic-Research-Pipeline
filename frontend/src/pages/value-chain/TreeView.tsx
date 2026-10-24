import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { apiMessage } from "../../lib/projects";
import { cents, nodeHash } from "../../lib/valueChain";
import type { VcTree, VcTreeNode } from "../../types";

/** One box with its suppliers stacked to its left; levels line up because every box is the same width. */
function Branch({ node, level }: { node: VcTreeNode; level: number }) {
  return (
    <li className="vc-branch">
      {node.children.length > 0 && (
        <ul className="vc-children">
          {node.children.map((c) => (
            <Branch key={c.node_id} node={c} level={level + 1} />
          ))}
        </ul>
      )}
      <a className="vc-box" href={nodeHash(node.node_id, "tree")}>
        <span>
          <b>{node.sector}</b> · {node.region_label}
        </span>
        <span className="mono">
          {cents(node.coef)} per €{level >= 2 && ` · chain ${cents(node.chain, 2)}`}
        </span>
      </a>
    </li>
  );
}

/** Upstream tree: the selected node on the right, its largest direct suppliers fanning out to the left. */
export function TreeView({ id }: { id: string }) {
  const [depth, setDepth] = useState(2);
  const [cutoff, setCutoff] = useState(1); // cents per €
  const [goodsOnly, setGoodsOnly] = useState(false);
  const [tree, setTree] = useState<VcTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .valueChainTree(id, { depth, cutoff: cutoff / 100, goodsOnly })
      .then((t) => {
        if (!live) return;
        setTree(t);
        setError(null);
      })
      .catch((err) => live && setError(apiMessage(err)));
    return () => {
      live = false;
    };
  }, [id, depth, cutoff, goodsOnly]);

  if (error)
    return (
      <p className="error-text" role="alert">
        {error}
      </p>
    );
  if (!tree) return <p className="muted">Loading…</p>;
  return (
    <>
      <section className="card" aria-labelledby="vc-tree">
        <h2 id="vc-tree">
          Upstream tree · {tree.sector} · {tree.region_label}
        </h2>
        <p className="help-text vc-note">
          Each box is a supplier of the box on its right. The first number is what it sells to that box per € of that box's output; "chain" is the same flow per € of
          the selected node. Showing the 3 largest suppliers per box.
        </p>
        <div className="toolbar vc-tree-controls">
          <label className="field-label">
            Levels
            <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
              {[2, 3, 4].map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
          </label>
          <label className="field-label">
            Hide links below {cents(cutoff / 100)} per €
            <input type="range" min={0} max={10} value={cutoff} onChange={(e) => setCutoff(Number(e.target.value))} />
          </label>
          <label className="checkbox-label">
            <input type="checkbox" checked={goodsOnly} onChange={(e) => setGoodsOnly(e.target.checked)} /> Goods only
          </label>
        </div>
        {/* Open scrolled to the right end, so a narrow screen starts at the selected node. */}
        <div className="table-wrap vc-tree-scroll" ref={(el) => el?.scrollTo({ left: el.scrollWidth })}>
          {tree.children.length === 0 ? (
            <p className="muted">No supplier sells this node at least {cents(cutoff / 100)} per €.</p>
          ) : (
            <ul className="vc-tree">
              <li className="vc-branch">
                <ul className="vc-children">
                  {tree.children.map((c) => (
                    <Branch key={c.node_id} node={c} level={1} />
                  ))}
                </ul>
                <div className="vc-box vc-root">
                  <span>
                    <b>{tree.sector}</b> · {tree.region_label}
                  </span>
                  <span className="mono">Selected</span>
                </div>
              </li>
            </ul>
          )}
        </div>
      </section>
      <p className="help-text vc-note">{tree.caveat}</p>
    </>
  );
}
