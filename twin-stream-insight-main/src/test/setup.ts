import "@testing-library/jest-dom/vitest"; // vitest entry: registers the matchers AND augments vitest's Assertion types (the bare import no longer types them under vitest 5)

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => {},
  }),
});
