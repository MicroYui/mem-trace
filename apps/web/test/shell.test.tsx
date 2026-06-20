import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/App";

describe("web app shell", () => {
  test("renders fixture-backed dashboard chrome without a live API or token leakage", () => {
    const html = renderToStaticMarkup(<App initialMode="fixture" initialApiKey="secret-token" />);

    expect(html).toContain("MemTrace");
    expect(html).toContain("Fixture mode");
    expect(html).toContain("ws_showcase");
    expect(html).toContain("State-aware + gate");
    expect(html).toContain("Workspace overview");
    expect(html).not.toContain("secret-token");
  });
});
