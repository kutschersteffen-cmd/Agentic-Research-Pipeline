import type { ReactNode } from "react";

interface PageHeaderProps {
  title: ReactNode;
  /** One or two sentences on what this page is for and what it does not do. */
  description?: ReactNode;
  /** The page's committing action, kept in the same place on every page. */
  actions?: ReactNode;
}

/** Every page opens the same way: what this is, what it is for, and the one
 *  action that matters, in that order and in that place. The title is the
 *  document's <h1> -- with the page rendered inside a shell, nothing else
 *  is. */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {description && <p className="page-header-description">{description}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
