import { ETHEN_FOUNDATION } from "@hermes/shared/ethen-foundation";

import type { DesktopTheme, DesktopThemeColors } from "./types";

type FoundationPalette =
  typeof ETHEN_FOUNDATION.light | typeof ETHEN_FOUNDATION.dark;

/** Map the shared Foundation palette onto the existing shadcn theme contract.
 * Terminal/editor transports and native capabilities remain owned by Hermes.
 */
function foundationColors(p: FoundationPalette): DesktopThemeColors {
  return {
    background: p["ethen-canvas"],
    foreground: p["ethen-ink"],
    card: p["ethen-surface"],
    cardForeground: p["ethen-ink"],
    muted: p["ethen-surface"],
    mutedForeground: p["ethen-muted"],
    popover: p["ethen-raised"],
    popoverForeground: p["ethen-ink"],
    primary: p["ethen-structural-accent"],
    primaryForeground: p["ethen-on-accent"],
    secondary: p["ethen-surface"],
    secondaryForeground: p["ethen-ink"],
    accent: p["ethen-surface"],
    accentForeground: p["ethen-ink"],
    border: p["ethen-rule"],
    input: p["ethen-rule-strong"],
    ring: p["ethen-focus"],
    midground: p["ethen-structural-accent"],
    midgroundForeground: p["ethen-on-accent"],
    destructive: p["ethen-error"],
    destructiveForeground: p["ethen-canvas"],
    sidebarBackground: p["ethen-surface"],
    sidebarBorder: p["ethen-rule"],
  };
}

const radius = ETHEN_FOUNDATION.non_color.radius_px.control;
const motion = ETHEN_FOUNDATION.non_color.motion_ms.control;

/** One preset is consumed by both native Desktop and its actual Webapp build.
 * Keep special icon/grip shapes and reduced-motion preferences intact.
 */
export const ethenTheme: DesktopTheme = {
  name: "ethen",
  label: "Ethen",
  description: "Warm light and muted dark with clear indigo controls",
  colors: foundationColors(ETHEN_FOUNDATION.light),
  darkColors: foundationColors(ETHEN_FOUNDATION.dark),
  typography: {
    fontSans:
      'system-ui, "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", emoji',
    fontUrl: undefined,
  },
  customCSS: `
:root[data-hermes-theme="ethen"] [data-slot="button"]:not([data-variant="grip"]):not([data-size^="icon"]),
:root[data-hermes-theme="ethen"] [data-slot="input"],
:root[data-hermes-theme="ethen"] [data-slot="input-group"] { border-radius: ${radius}px; }
@media (prefers-reduced-motion: no-preference) {
  :root[data-hermes-theme="ethen"] [data-slot="button"] { transition-duration: ${motion}ms; }
}`,
};
