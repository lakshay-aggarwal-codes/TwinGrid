import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type SkeletonVariant = "lines" | "card" | "table" | "chart";

interface StateSkeletonProps {
  variant?: SkeletonVariant;
  /** Spoken label for assistive tech. */
  label?: string;
  className?: string;
}

const bar = "motion-reduce:animate-none";

/**
 * A placeholder with the rough shape of what is loading. One polite status announcement ("Loading..."), the shapes
 * themselves are hidden from assistive tech, and the pulse stops under prefers-reduced-motion.
 */
export function StateSkeleton({ variant = "lines", label = "Loading…", className }: StateSkeletonProps) {
  return (
    <div role="status" aria-busy="true" data-state="loading" data-skeleton={variant} className={cn("w-full", className)}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="space-y-2">
        {variant === "lines" && (
          <>
            <Skeleton className={cn("h-3 w-3/4", bar)} />
            <Skeleton className={cn("h-3 w-full", bar)} />
            <Skeleton className={cn("h-3 w-5/6", bar)} />
          </>
        )}
        {variant === "card" && (
          <>
            <Skeleton className={cn("h-4 w-1/3", bar)} />
            <Skeleton className={cn("h-16 w-full", bar)} />
            <Skeleton className={cn("h-3 w-2/3", bar)} />
          </>
        )}
        {variant === "table" &&
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className={cn("h-6 w-full", bar)} />)}
        {variant === "chart" && <Skeleton className={cn("h-40 w-full", bar)} />}
      </div>
    </div>
  );
}
