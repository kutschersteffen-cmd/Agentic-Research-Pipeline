import type { ComponentType } from "react";
import { PhosphorConsole } from "./lab/PhosphorConsole";
import { ProvenanceLoupe } from "./lab/ProvenanceLoupe";
import { RankLadder } from "./lab/RankLadder";
import { RunHeat } from "./lab/RunHeat";
import { TapeReader } from "./lab/TapeReader";

type Screen = { id: string; title: string; blurb: string; Component: ComponentType };

/** Every Lab screen. To add one: write its component in pages/lab/ and add one line here. */
const SCREENS: Screen[] = [
  { id: "loupe", title: "Provenance Loupe", blurb: "Every number opens on the exact source span, with the grounding check as a diff.", Component: ProvenanceLoupe },
  { id: "tape", title: "Tape Reader", blurb: "The review queue as a keyboard-driven audit ledger.", Component: TapeReader },
  { id: "ladder", title: "Rank-Range Ladder", blurb: "Decision Studio ranks as ranges across four specifications, re-weighted live.", Component: RankLadder },
  { id: "heat", title: "Run Heat Map", blurb: "A 4,000-company run as one map, lit only where a person is the blocker.", Component: RunHeat },
  { id: "console", title: "Phosphor Console", blurb: "A night-mode console with a command palette and CLI parity.", Component: PhosphorConsole },
];

/** The Lab: experimental screens on sample data. `#/lab/<id>` opens one. */
export function Lab({ selected }: { selected: string | null }) {
  const screen = SCREENS.find((s) => s.id === selected);
  if (screen) {
    return (
      <div className="page lab-screen">
        <p className="arcade-back"><a href="#/lab">← Lab</a></p>
        <h1>{screen.title}</h1>
        <screen.Component />
      </div>
    );
  }
  return (
    <div className="page">
      <h1>Lab</h1>
      <p className="muted">Experimental screens. They run on sample data, not live runs.</p>
      <ul className="arcade-list">
        {SCREENS.map((s) => (
          <li key={s.id}>
            <a href={`#/lab/${s.id}`}>
              <span className="arcade-title">{s.title}</span>
              <span className="muted">{s.blurb}</span>
              <span className="arcade-play">Open →</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
