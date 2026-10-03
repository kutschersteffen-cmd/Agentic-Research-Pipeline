import type { ComponentType } from "react";
import { MeteorDodge } from "./arcade/MeteorDodge";

type Game = { id: string; title: string; blurb: string; Component: ComponentType };

/** Every cabinet in the arcade. To add a game: write its component in pages/arcade/ and add one line here. */
const GAMES: Game[] = [
  { id: "meteor-dodge", title: "Meteor Dodge", blurb: "Fly a pixel rocket, shoot the asteroids, and dodge the pieces.", Component: MeteorDodge },
];

/** The Arcade: a list of games, and `#/arcade/<id>` opens one. */
export function Arcade({ selected }: { selected: string | null }) {
  const game = GAMES.find((g) => g.id === selected);
  if (game) {
    return (
      <div className="page">
        <p className="arcade-back"><a href="#/arcade">← Arcade</a></p>
        <h1>{game.title}</h1>
        <game.Component />
      </div>
    );
  }
  return (
    <div className="page">
      <h1>Arcade</h1>
      <p className="muted">Short breaks between reviews. Scores stay on this device.</p>
      <ul className="arcade-list">
        {GAMES.map((g) => (
          <li key={g.id}>
            <a href={`#/arcade/${g.id}`}>
              <span className="arcade-title">{g.title}</span>
              <span className="muted">{g.blurb}</span>
              <span className="arcade-play">Play →</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
