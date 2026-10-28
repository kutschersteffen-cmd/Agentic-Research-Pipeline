import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { cents, nodeHash, tonnes } from "../../lib/valueChain";
import type { VcMaterialTreeNode, VcTreeNode } from "../../types";
import { MaterialOptions } from "./MaterialOptions";
import { useVcQuery } from "./useVcQuery";

/** One box with its suppliers stacked to its left; levels line up because every box is the same width. */
type Box = VcTreeNode | VcMaterialTreeNode;
const extracted = (n: Box) => ("extracted_t" in n ? <span className="mono">{tonnes(n.extracted_t)}</span> : null);

function Branch({ node, level }: { node: Box; level: number }) {
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
        {extracted(node)}
      </a>
    </li>
  );
}

/** Upstream tree: the selected node on the right, its largest direct suppliers fanning out to the left. */
export function TreeView({ id, onTitle }: { id: string; onTitle: (title: string) => void }) {
  const [depth, setDepth] = useState(2);
  const [cutoff, setCutoff] = useState(1); // cents per €
  const [goodsOnly, setGoodsOnly] = useState(false);
  const [material, setMaterial] = useState("");
  const [amountText, setAmountText] = useState("1");
  const amount = Number(amountText);
  const valid = amountText.trim() !== "" && Number.isFinite(amount) && amount > 0;
  const picked = material !== "" && valid ? material : undefined;
  const { data: tree, error, loading } = useVcQuery(
    () => api.valueChainTree(id, { depth, cutoff: cutoff / 100, goodsOnly, material: picked, amount }),
    [id, depth, cutoff, goodsOnly, picked, amount],
  );
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!tree) return;
    onTitle(`${tree.sector} · ${tree.region_label}`);
    // Open scrolled to the right end, so a narrow screen starts at the selected node.
    scroller.current?.scrollTo({ left: scroller.current.scrollWidth });
  }, [tree, onTitle]);

  return (
    <>
      <section className="card" aria-labelledby="vc-tree">
        <h2 id="vc-tree">Upstream tree</h2>
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
          <label className="field-label">
            Show material
            <select value={material} onChange={(e) => setMaterial(e.target.value)}>
              <option value="">None</option>
              <MaterialOptions prefix="" />
            </select>
          </label>
          <label className="field-label vc-amount">
            Amount (€ million)
            <input type="number" min={0} step="any" value={amountText} onChange={(e) => setAmountText(e.target.value)} aria-invalid={!valid || undefined} />
            {!valid && <span className="error-text">Enter an amount above 0.</span>}
          </label>
        </div>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        {loading && !tree && (
          <p className="muted" role="status">
            Loading…
          </p>
        )}
        {tree && (
          <div className="table-wrap vc-tree-scroll" ref={scroller} aria-busy={loading}>
            {tree.children.length === 0 ? (
              <p className="muted" role="status">
                No supplier sells this node at least {cents(cutoff / 100)} per €.
              </p>
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
                    {extracted(tree)}
                  </div>
                </li>
              </ul>
            )}
          </div>
        )}
      </section>
      {tree && <p className="help-text vc-note">{tree.caveat}</p>}
      {tree && "material_note" in tree && <p className="help-text vc-note">{tree.material_note}</p>}
    </>
  );
}
