/**
 * Commands (the palette) and the welcome screen ask the mounted tour host to do something. A request made while no host
 * is mounted (nobody signed in) is dropped on purpose.
 */
export type TourRequest = "start" | "resume" | "welcome";

const listeners = new Set<(r: TourRequest) => void>();

export const requestTour = (r: TourRequest): void => {
  [...listeners].forEach((l) => l(r));
};

export const subscribeTourRequests = (l: (r: TourRequest) => void): (() => void) => {
  listeners.add(l);
  return () => void listeners.delete(l);
};
