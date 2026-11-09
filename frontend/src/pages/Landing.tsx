import { LandingCanvas } from "../components/LandingCanvas";

const PROMISES = [
  ["The LLM plans, code computes", "Models draft the plan; deterministic code does the maths."],
  ["Every citation re-verified", "Each quote is checked against the source document, not trusted from the model."],
  ["Nothing flagged ships", "No flagged item reaches an export until a named person approves it."],
];

/** ARP's front door: the dot animation, the promise and one way in. */
export function Landing() {
  return (
    <div className="landing">
      <LandingCanvas />
      <header className="landing-bar">
        <span className="landing-brand">
          <svg className="landing-mark" viewBox="0 0 62 62" aria-hidden="true">
            <path fill="currentColor" d="M14 2h10v10H14zM38 2h10v10H38zM2 14h10v10H2zM50 14h10v10H50zM2 26h10v10H2zM14 26h10v10H14zM26 26h10v10H26zM38 26h10v10H38zM50 26h10v10H50zM2 38h10v10H2zM50 38h10v10H50zM2 50h10v10H2zM50 50h10v10H50z" />
            <rect x="26" y="2" width="10" height="10" fill="var(--hi)" />
          </svg>
          ARP <span className="landing-full">Agentic Research Pipeline</span>
        </span>
      </header>
      <main className="landing-main">
        <h1>
          Agents propose.
          <br />
          People ratify.
        </h1>
        <p>Thematic universes, cited extraction, transition assessment and stewardship for up to 4,000 companies per run. Every number traces back to a verified source.</p>
        <a className="landing-open" href="#/home">
          Open ARP →
        </a>
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
