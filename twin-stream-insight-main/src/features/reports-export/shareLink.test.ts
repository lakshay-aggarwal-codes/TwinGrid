import { describe, expect, it } from "vitest";
import { shareUrl } from "./shareLink";

describe("shareUrl", () => {
  it("keeps the view state in the query string", () => {
    expect(shareUrl("https://twin.example/alerts?alert=42")).toBe("https://twin.example/alerts?alert=42");
  });
  it("drops credential-like parameters, user info and the fragment", () => {
    expect(shareUrl("https://u:p@twin.example/x?alert=1&token=abc&Ticket=t&password=p&a=b#access_token=zzz")).toBe("https://twin.example/x?alert=1&a=b");
  });
  it("refuses non-http links and garbage", () => {
    expect(shareUrl("javascript:alert(1)")).toBe("");
    expect(shareUrl("nonsense")).toBe("");
  });
});
