import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { StateBlock } from "../ui";

interface Props {
  /** Remounts the boundary when the view changes, so navigating away from
   *  a broken page clears the error instead of sticking to it. */
  resetKey: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
  resetKey: string;
}

/** Now that any URL can address any page, a page can be handed values it
 *  did not expect. A render that throws should cost the page, not the whole
 *  window: without this, React unmounts the root and the analyst is left
 *  looking at a blank screen with no way back. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey === state.resetKey ? null : { error: null, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page failed to render", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page">
          <StateBlock
            kind="error"
            title="This page could not be shown"
            message={`${this.state.error.message}. The link may point at something that no longer exists -- pick another destination from the sidebar, or reload.`}
            onRetry={() => window.location.reload()}
          />
        </div>
      );
    }
    return this.props.children;
  }
}
