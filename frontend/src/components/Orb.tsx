import { useEffect, useRef, useState } from "react";
import stillUrl from "../assets/orb-still.webp";
import {
  COLOUR_HEX,
  OrbClock,
  PHASE_LABEL,
  QualityRule,
  MAX_STEP,
  pinnedLevel,
  type OrbColour,
  type OrbLevel,
  type OrbPhase,
  type OrbQuality,
} from "../lib/orbMotion";
import type { OrbScene } from "../orb/orbScene";

export type OrbPlace = "landing" | "start" | "workspace" | "agent";

interface Props {
  place: OrbPlace;
  /** Assemble from the core outwards when the page opens (landing page only). */
  intro?: boolean;
  /** Show the phase label; the surrounding stage positions it. */
  label?: boolean;
  /** The ring around the core pulses while the Orb is otherwise idle (landing: "Open ARP" hovered or focused). */
  speaking?: boolean;
  /** Agent screen: an ask is in flight. */
  working?: boolean;
}

interface Live {
  phase: OrbPhase;
  colour: OrbColour;
  quality: OrbQuality;
  paused: boolean;
}

const PIN_KEY = "arp.orb";
const SESSION_KEY = "arp.orb.level";
const read = (s: () => Storage, k: string) => { try { return s().getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { sessionStorage.setItem(k, v); } catch { /* storage blocked: this page only */ } };

/**
 * The ARP Orb (docs/superpowers/specs/2026-11-22-expressive-ui-orb.md): the agents' visual. Live in WebGL with
 * the three.js scene loaded on demand, or a still picture without WebGL, under reduced motion, on a slow GPU or
 * when the scene fails. Renders the Orb's box plus, as siblings, the phase label and the hover hint.
 */
export function Orb({ place, intro = false, label = false, speaking = false, working = false }: Props) {
  const root = useRef<HTMLDivElement>(null);
  const hint = useRef<HTMLSpanElement>(null);
  const [mode, setMode] = useState<"live" | "still" | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const clockRef = useRef<OrbClock | null>(null);
  const voice = useRef(false);

  useEffect(() => {
    const el = root.current!;
    const agent = place === "agent";
    const pin = pinnedLevel(read(() => localStorage, PIN_KEY));
    // With a pin the session level is neither read nor written.
    const stored = pin ?? pinnedLevel(read(() => sessionStorage, SESSION_KEY));
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (stored === "still" || reduce) {
      setMode("still");
      return;
    }
    const level: OrbLevel = agent ? "low" : (stored ?? "high");
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2", { antialias: false, alpha: false, depth: true, stencil: false, powerPreference: "high-performance" });
    if (!gl) {
      setMode("still");
      return;
    }

    let scene: OrbScene | null = null;
    let raf = 0;
    let done = false;
    let visible = true;
    let paused = false;
    let afterPause = true;
    let last = -1;
    let failed = 0;
    let logged = false;
    const rule = agent || pin ? null : new QualityRule(level);
    let quality = level as OrbQuality;
    const clock = new OrbClock(intro);
    clockRef.current = clock;
    let shown: Live | null = null;
    const show = (paused: boolean) => {
      const next = { phase: clock.phase, colour: clock.colour, quality, paused };
      if (shown && shown.phase === next.phase && shown.colour === next.colour && shown.quality === next.quality && shown.paused === next.paused) return;
      shown = next;
      setLive(next);
    };

    const dpr = () => window.devicePixelRatio || 1;
    const side = () => el.getBoundingClientRect().width;
    const stop = () => {
      done = true;
      cancelAnimationFrame(raf);
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      canvas.removeEventListener("webglcontextlost", toStill);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("click", onClick);
      clockRef.current = null;
      const s = scene;
      scene = null;
      try {
        if (s) s.dispose();
        else gl.getExtension("WEBGL_lose_context")?.loseContext();
      } catch {
        /* already gone */
      }
      canvas.remove();
    };
    function toStill() {
      if (done) return;
      stop();
      if (hint.current) hint.current.hidden = true;
      setLive(null);
      setMode("still");
    }

    const loop = (now: number) => {
      raf = 0;
      if (done || paused || !scene) return;
      const gap = last < 0 ? 0 : now - last;
      const first = afterPause;
      last = now;
      afterPause = false;
      if (rule) {
        const lv = rule.add(gap, first);
        if (lv === "still") {
          write(SESSION_KEY, "still");
          toStill();
          return;
        }
        if (lv !== quality) {
          quality = lv;
          write(SESSION_KEY, lv);
          scene.setQuality(lv, dpr());
        }
      }
      const dt = first ? 0 : gap / 1000;
      const ev = clock.tick(dt);
      if (ev.started) scene.transform();
      if (ev.committed) scene.commit();
      try {
        scene.frame(Math.min(dt, MAX_STEP), clock.phase, voice.current && (clock.phase === "speaking" || agent));
        failed = 0;
      } catch (error) {
        if (!logged) console.error("Orb frame failed", error);
        logged = true;
        if (++failed >= 3) {
          toStill();
          return;
        }
      }
      if (!canvas.isConnected) {
        el.appendChild(canvas);
        setMode("live");
      }
      show(false);
      // The hint shows only while the pointer is over the sphere and the Orb is idle, also when the phase changes under a still pointer.
      if (hint.current) hint.current.hidden = !(over && clock.phase === "idle");
      raf = requestAnimationFrame(loop);
    };
    const run = () => {
      const want = !visible || document.hidden;
      if (want === paused) return;
      paused = want;
      if (paused) {
        cancelAnimationFrame(raf);
        raf = 0;
        show(true);
      } else if (scene && !done) {
        afterPause = true;
        raf = requestAnimationFrame(loop);
      }
    };
    const onVisibility = () => run();
    const io = new IntersectionObserver((entries) => {
      visible = entries[entries.length - 1].isIntersecting;
      run();
    });
    const ro = new ResizeObserver(() => scene?.resize(side(), dpr()));

    let over = false;
    const local = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top] as const;
    };
    const onMove = (e: PointerEvent) => {
      if (!scene || agent) return;
      const [x, y] = local(e);
      over = scene.pointer(x, y, true);
      const h = hint.current;
      if (!h) return;
      h.hidden = !(over && clock.phase === "idle");
      h.style.left = `${el.offsetLeft + x}px`;
      h.style.top = `${el.offsetTop + y}px`;
    };
    const onLeave = () => {
      over = false;
      scene?.pointer(null, null, false);
      if (hint.current) hint.current.hidden = true;
    };
    const onClick = (e: MouseEvent) => {
      if (!scene || agent) return;
      const [x, y] = local(e as PointerEvent);
      scene.pointer(x, y, true);
      if (clock.click()) {
        scene.transform();
        if (hint.current) hint.current.hidden = true;
        show(paused);
      }
      if ((e as PointerEvent).pointerType && (e as PointerEvent).pointerType !== "mouse") onLeave();
    };

    canvas.addEventListener("webglcontextlost", toStill);
    import("../orb/orbScene")
      .then(({ createOrbScene }) => {
        if (done) return;
        scene = createOrbScene(canvas, gl, { quality, intro });
        scene.resize(side(), dpr());
        io.observe(el);
        ro.observe(el);
        document.addEventListener("visibilitychange", onVisibility);
        el.addEventListener("pointermove", onMove);
        el.addEventListener("pointerleave", onLeave);
        el.addEventListener("click", onClick);
        raf = requestAnimationFrame(loop);
      })
      .catch(() => toStill());
    return stop;
    // Set up once per mount: `speaking` and `working` reach the running Orb through the effect below.
  }, [place, intro]);

  // Declared after the set-up effect, so on mount it runs once the clock exists.
  useEffect(() => {
    voice.current = working || speaking;
    clockRef.current?.setSpeaking(speaking);
  }, [speaking, working]);

  const isLive = mode === "live" && live;
  return (
    <>
      <div
        ref={root}
        className="orb"
        data-orb={place}
        role="img"
        aria-label="ARP Orb"
        data-orb-mode={mode ?? undefined}
        data-orb-phase={isLive ? live.phase : undefined}
        data-orb-colour={mode === "still" ? "gold" : isLive ? live.colour : undefined}
        data-orb-quality={isLive ? live.quality : undefined}
        data-orb-state={working ? "working" : "idle"}
        data-orb-paused={isLive && live.paused ? "true" : undefined}
      >
        {mode === "still" && <img src={stillUrl} alt="" width={800} height={800} draggable={false} />}
      </div>
      {label && isLive && (
        <span className="orb-label" data-orb-label aria-hidden="true">
          <i style={{ background: COLOUR_HEX[live.colour] }} />
          {PHASE_LABEL[live.phase]}
        </span>
      )}
      {place !== "agent" && (
        <span ref={hint} className="orb-hint" aria-hidden="true" hidden>
          Click to transform
        </span>
      )}
    </>
  );
}
