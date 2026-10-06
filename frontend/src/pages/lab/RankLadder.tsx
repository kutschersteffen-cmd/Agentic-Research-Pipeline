import { useMemo, useState } from "react";
import "./RankLadder.css";
import {
  CRITERIA, DEFAULT_WEIGHTS, NAMES, TIER_ENDS, TIER_NAMES, rankRanges, sampleValues,
} from "./rankLadderData.ts";

const N = NAMES.length;
const AXIS = [1, 5, 10, 15, 20, 25];
const pct = (rank: number) => `${(rank / N) * 100}%`;

export function RankLadder() {
  const values = useMemo(() => sampleValues(), []);
  const [weights, setWeights] = useState<number[]>(DEFAULT_WEIGHTS);
  const ranked = useMemo(() => rankRanges(values, weights), [values, weights]);
  const rowOf = new Map(ranked.map((e, k) => [e.index, k]));
  const open = ranked.filter((e) => e.unstable).length;

  return (
    <div className="lab-ladder">
      <p className="lad-note">Sample data</p>
      <div className="lad-legend" aria-hidden="true">
        <span><i className="k-bar" />rank range, 4 specs</span>
        <span><i className="k-hatch" />edge set by inferred direction</span>
        <span><i className="k-hi" />tier unstable: you decide</span>
      </div>
      <div className="lad-main">
        <section className="lad-side" aria-label="Criteria weights">
          <h2>Criteria weights</h2>
          {CRITERIA.map((c, i) => (
            <label key={c.name}>
              <span className="lad-lbl">
                {c.name}
                <em>{c.inferred ? "inferred dir." : "stated dir."} · {weights[i]}</em>
              </span>
              <input
                type="range" min={0} max={10} step={1} value={weights[i]}
                aria-valuetext={`${weights[i]} of 10, ${c.inferred ? "inferred" : "stated"} direction`}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setWeights((w) => w.map((x, j) => (j === i ? v : x)));
                }}
              />
            </label>
          ))}
          <button type="button" onClick={() => setWeights(DEFAULT_WEIGHTS)}>Reset weights</button>
          <p className="lad-sum" role="status">
            <b className={open ? "act" : undefined}>{open} of {N}</b> entities straddle a tier boundary.
            <br />
            <span>{open ? "These need a human decision." : "Nothing waits on anyone."}</span>
          </p>
        </section>

        <div className="lad-chart">
          <div className="lad-axis" aria-hidden="true">
            {AXIS.map((r) => <span key={r} style={{ left: pct(r - 0.5) }}>{r}</span>)}
          </div>
          <div className="lad-body" style={{ height: N * 24 }} aria-hidden="true">
            {TIER_ENDS.map((end, i) => {
              const start = i ? TIER_ENDS[i - 1] : 0;
              return (
                <div key={end} className="band" style={{ left: pct(start), width: pct(end - start) }}>
                  <b>{TIER_NAMES[i].slice(0, 2)}<span> {TIER_NAMES[i].slice(3)}</span></b>
                </div>
              );
            })}
            {ranked.map((e) => (
              <div
                key={e.index} className={e.unstable ? "row u" : "row"}
                style={{ top: (rowOf.get(e.index) ?? 0) * 24 }}
              >
                <span className="nm">{NAMES[e.index]}</span>
                <div className="trk">
                  <i
                    className={`bar${e.hatchLo ? " hl" : ""}${e.hatchHi ? " hr" : ""}`}
                    style={{ left: pct(e.lo - 1), width: pct(e.hi - e.lo + 1) }}
                  />
                  <span className="tip" style={{ left: `calc(${pct(e.hi)} + 4px)` }}>
                    {e.lo === e.hi ? `#${e.lo}` : `${e.lo}–${e.hi}`}
                  </span>
                </div>
              </div>
            ))}
          </div>
          <ol className="sr">
            {ranked.map((e) => (
              <li key={e.index}>
                {NAMES[e.index]}, {e.lo === e.hi ? `rank ${e.lo}` : `rank ${e.lo} to ${e.hi}`}
                {e.unstable ? ", tier unstable, needs a decision" : ""}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
