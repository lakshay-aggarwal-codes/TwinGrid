import { useEffect } from "react";

/** Sets document.title for the page (screen readers announce it on navigation). */
export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = title;
  }, [title]);
}
