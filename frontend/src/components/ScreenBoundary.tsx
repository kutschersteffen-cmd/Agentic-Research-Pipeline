import { Component, type ReactNode } from "react";

/** Catches a render error in one screen so the sidebar and every other screen
 * keep working. Without it, a single malformed response blanked the whole app
 * mid-meeting. App keys it by screen, so moving to another screen resets it. */
export class ScreenBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("Screen failed to render:", error);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="page" role="alert">
        <h2>This screen failed to render</h2>
        <p className="error-text">
          {error.message || "Unknown error"}. Nothing was changed. Other screens still work: pick one from the menu, or try this one again.
        </p>
        <button onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
