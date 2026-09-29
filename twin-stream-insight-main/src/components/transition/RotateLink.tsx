import type { ComponentProps, MouseEvent } from "react";
import { Link } from "react-router-dom";
import { useRotateNavigate } from "./rotateContext";

interface RotateLinkProps extends Omit<ComponentProps<typeof Link>, "to"> {
  to: string;
  /** 1 swings the page out to the right, -1 to the left. */
  direction?: 1 | -1;
}

/** A normal <a href> (middle-click, copy-link, screen readers all work) that
 * plays the rotation on a plain left-click. */
export function RotateLink({ to, direction = 1, onClick, ...rest }: RotateLinkProps) {
  const rotateNavigate = useRotateNavigate();
  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    rotateNavigate(to, direction);
  };
  return <Link to={to} onClick={handleClick} {...rest} />;
}
