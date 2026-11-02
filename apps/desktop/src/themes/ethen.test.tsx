import { ETHEN_FOUNDATION } from "@hermes/shared/ethen-foundation";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { __resetBackendSkinSync } from "./backend-sync";
import { ThemeProvider, useTheme } from "./context";

let api: ReturnType<typeof useTheme>;

function Controls({
  onRun,
  onQuery,
}: {
  onRun: () => void;
  onQuery: (value: string) => void;
}) {
  api = useTheme();

  return (
    <>
      <Button onClick={onRun}>Run tests</Button>
      <Input
        aria-label="Repository search"
        onChange={(event) => onQuery(event.target.value)}
      />
    </>
  );
}

function launch(onRun = vi.fn(), onQuery = vi.fn()) {
  render(
    <ThemeProvider>
      <Controls onQuery={onQuery} onRun={onRun} />
    </ThemeProvider>,
  );

  return { onRun, onQuery };
}

const css = (key: string) =>
  window.document.documentElement.style.getPropertyValue(key);

describe("Ethen Foundation on real shared Desktop/Webapp controls", () => {
  beforeEach(() => {
    localStorage.clear();
    __resetBackendSkinSync();
  });
  afterEach(() => {
    cleanup();
    localStorage.clear();
    __resetBackendSkinSync();
  });

  it("selects the shared preset, paints light/dark Foundation tokens and preserves control actions", () => {
    const { onRun, onQuery } = launch();
    expect(api.availableThemes.some((theme) => theme.name === "ethen")).toBe(
      true,
    );
    act(() => {
      api.setTheme("ethen");
      api.setMode("light");
    });
    expect(css("--theme-background-seed")).toBe(
      ETHEN_FOUNDATION.light["ethen-canvas"],
    );
    expect(css("--theme-primary")).toBe(
      ETHEN_FOUNDATION.light["ethen-structural-accent"],
    );
    fireEvent.click(screen.getByRole("button", { name: "Run tests" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Repository search" }),
      { target: { value: "src/example.ts" } },
    );
    expect(onRun).toHaveBeenCalledOnce();
    expect(onQuery).toHaveBeenCalledWith("src/example.ts");
    act(() => api.setMode("dark"));
    expect(css("--theme-background-seed")).toBe(
      ETHEN_FOUNDATION.dark["ethen-canvas"],
    );
    expect(css("--theme-primary")).toBe(
      ETHEN_FOUNDATION.dark["ethen-structural-accent"],
    );
    expect(window.document.documentElement.classList.contains("dark")).toBe(
      true,
    );
  });

  it("retains the selected preset on renderer remount and removes its control overrides when switching", () => {
    launch();
    act(() => api.setTheme("ethen"));
    cleanup();
    launch();
    expect(api.themeName).toBe("ethen");

    const cssText = () =>
      window.document.getElementById("hermes-desktop-custom-css")
        ?.textContent ?? "";

    expect(cssText()).toContain("border-radius: 3px");
    act(() => api.setTheme("nous"));
    expect(api.themeName).toBe("nous");
    expect(cssText()).not.toContain('data-hermes-theme="ethen"');
  });
});
