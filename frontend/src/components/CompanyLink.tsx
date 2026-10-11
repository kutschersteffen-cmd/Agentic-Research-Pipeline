import type { ReactNode } from "react";
import { companyHref } from "../pages/company/companyQuery";

/** A universe company's name, linking to its company page. The click stays
 * out of a clickable row it sits in, so following it does not also expand the row. */
export function CompanyLink({ companyId, children }: { companyId: string; children: ReactNode }) {
  return (
    <a href={companyHref(companyId)} onClick={(e) => e.stopPropagation()}>
      {children}
    </a>
  );
}
