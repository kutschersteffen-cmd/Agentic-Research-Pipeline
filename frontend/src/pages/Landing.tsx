import { useState } from "react";
import { Orb } from "../components/Orb";

const PROMISES = [
  ["The LLM plans, code computes", "Models draft the plan; deterministic code does the maths."],
  ["Every citation re-verified", "Each quote is checked against the source document, not trusted from the model."],
  ["Nothing flagged ships", "No flagged item reaches an export until a named person approves it."],
];

/** ARP's front door: the promise, one way in, and the Orb, which assembles when the page opens. */
export function Landing() {
  // The Orb speaks while "Open ARP" is hovered or focused.
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="landing-brand">
          <svg className="landing-mark" viewBox="0 0 206 62" role="img" aria-label="ARP">
            <path fill="currentColor" d="M14 2h10v10h-10zM38 2h10v10h-10zM2 14h10v10h-10zM50 14h10v10h-10zM2 26h10v10h-10zM14 26h10v10h-10zM26 26h10v10h-10zM38 26h10v10h-10zM50 26h10v10h-10zM2 38h10v10h-10zM50 38h10v10h-10zM2 50h10v10h-10zM50 50h10v10h-10zM74 2h10v10h-10zM86 2h10v10h-10zM98 2h10v10h-10zM110 2h10v10h-10zM74 14h10v10h-10zM122 14h10v10h-10zM74 26h10v10h-10zM86 26h10v10h-10zM98 26h10v10h-10zM110 26h10v10h-10zM74 38h10v10h-10zM110 38h10v10h-10zM74 50h10v10h-10zM122 50h10v10h-10zM146 2h10v10h-10zM158 2h10v10h-10zM170 2h10v10h-10zM182 2h10v10h-10zM146 14h10v10h-10zM194 14h10v10h-10zM146 26h10v10h-10zM158 26h10v10h-10zM170 26h10v10h-10zM182 26h10v10h-10zM146 38h10v10h-10zM146 50h10v10h-10z" />
            <rect x="26" y="2" width="10" height="10" fill="var(--brand-apex)" />
          </svg>
          <span className="landing-full">Agentic Research Platform</span>
        </span>
      </header>
      <main className="landing-main">
        <div className="landing-copy">
          <p className="landing-cap">
            <i aria-hidden="true" />
            Agents at work
          </p>
          <h1>Company research and stewardship at scale.</h1>
          <p>Leveraging expert judgement through Agents.</p>
          <a
            className="landing-open"
            href="#/home"
            onPointerEnter={() => setHover(true)}
            onPointerLeave={() => setHover(false)}
            onFocus={() => setFocus(true)}
            onBlur={() => setFocus(false)}
          >
            Open ARP <span>→</span>
          </a>
        </div>
        <div className="landing-stage">
          <Orb place="landing" intro label speaking={hover || focus} />
        </div>
      </main>
      <footer className="landing-promises">
        {PROMISES.map(([title, line]) => (
          <div key={title}>
            <b>{title}</b>
            <span>{line}</span>
          </div>
        ))}
      </footer>
    </div>
  );
}
