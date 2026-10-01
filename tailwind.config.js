/**
 * Système de design du marché HyperMarché — jetons (docs/26-design-system-marche.md).
 *
 * Deux étages de couleur, et c'est voulu :
 *
 *  1. les **palettes** (primary, secondary, success, warning, error, neutral, de 50 à 950) sont
 *     des valeurs fixes : elles servent à documenter, à illustrer, à composer un dégradé ;
 *  2. les **rôles** (bg, surface, ink, line, brand…) sont des variables CSS qui changent de valeur
 *     en mode sombre. Les composants n'utilisent **que** les rôles : c'est ce qui rend le mode
 *     sombre complet sans écrire `dark:` sur chaque classe.
 *
 * Les rôles sont déclarés en triplets RVB (`0 128 106`) pour que l'opacité de Tailwind
 * (`bg-brand/10`) fonctionne.
 *
 * Compilation : `npm run css` (minifiée, purgée) → static/css/marche.css, versionnée dans le dépôt :
 * la construction de production n'a pas Node, et n'en a pas besoin.
 */

/* Échelle typographique modulaire, rapport 1,25 (tierce majeure), base 16 px. */
const RAPPORT = 1.25;
const pas = (n) => `${+(RAPPORT ** n).toFixed(3)}rem`;

const role = (nom) => `rgb(var(--hm-${nom}) / <alpha-value>)`;

module.exports = {
  content: [
    "./templates/vitrine/**/*.html",
    "./templates/marche/**/*.html",
    "./static/js/marche.js",
    "./apps/vitrine/**/*.py",
  ],
  // Classes composées dans les gabarits (`btn-{{ variante }}`) : invisibles au balayage, donc
  // déclarées ici pour ne pas être purgées.
  safelist: [
    { pattern: /^btn-(primary|secondary|outline|ghost|accent|sm|md|lg)$/ },
    { pattern: /^badge-(neutre|marque|accent|succes|alerte|erreur)$/ },
    { pattern: /^bandeau-(info|succes|alerte|erreur)$/ },
  ],
  darkMode: [
    "variant",
    [
      "@media (prefers-color-scheme: dark) { &:where(html:not([data-theme=light]) *) }",
      "&:where(html[data-theme=dark] *)",
    ],
  ],
  theme: {
    /* Espacement : base 4 px, en rem pour suivre le zoom du navigateur. */
    spacing: {
      0: "0",
      px: "1px",
      0.5: "0.125rem", // 2
      1: "0.25rem", // 4
      1.5: "0.375rem", // 6
      2: "0.5rem", // 8
      2.5: "0.625rem", // 10
      3: "0.75rem", // 12
      3.5: "0.875rem", // 14
      4: "1rem", // 16
      5: "1.25rem", // 20
      6: "1.5rem", // 24
      7: "1.75rem", // 28
      8: "2rem", // 32
      9: "2.25rem", // 36
      10: "2.5rem", // 40
      11: "2.75rem", // 44 — cible tactile minimale
      12: "3rem", // 48
      14: "3.5rem", // 56
      16: "4rem", // 64
      20: "5rem", // 80
      24: "6rem", // 96
      32: "8rem", // 128
      40: "10rem", // 160
      48: "12rem", // 192
      64: "16rem", // 256
    },
    fontSize: {
      // [taille, { interligne, approche }] — l'interligne se resserre quand la taille monte.
      "2xs": [pas(-2), { lineHeight: "1rem", letterSpacing: "0.04em" }], // 10,24 px — sur-titres
      xs: [pas(-1), { lineHeight: "1.125rem" }], // 12,8 px — légendes
      sm: ["0.875rem", { lineHeight: "1.25rem" }], // 14 px — hors échelle : texte d'interface dense
      base: [pas(0), { lineHeight: "1.5rem" }], // 16 px — corps
      lg: [pas(1), { lineHeight: "1.75rem" }], // 20 px
      xl: [pas(2), { lineHeight: "2rem", letterSpacing: "-0.01em" }], // 25 px
      "2xl": [pas(3), { lineHeight: "2.375rem", letterSpacing: "-0.015em" }], // 31,25 px
      "3xl": [pas(4), { lineHeight: "2.875rem", letterSpacing: "-0.02em" }], // 39 px
      "4xl": [pas(5), { lineHeight: "3.375rem", letterSpacing: "-0.025em" }], // 48,8 px
      "5xl": [pas(6), { lineHeight: "1.05", letterSpacing: "-0.03em" }], // 61 px
    },
    fontFamily: {
      sans: [
        '"Plus Jakarta Sans"',
        "system-ui",
        "-apple-system",
        '"Segoe UI"',
        "Roboto",
        "sans-serif",
      ],
      mono: ["ui-monospace", '"SF Mono"', '"Cascadia Mono"', "Menlo", "monospace"],
    },
    borderRadius: {
      none: "0",
      sm: "0.25rem", // 4
      DEFAULT: "0.5rem", // 8
      md: "0.5rem", // 8
      lg: "0.75rem", // 12
      xl: "1rem", // 16
      "2xl": "1.5rem", // 24
      full: "9999px",
    },
    boxShadow: {
      none: "none",
      xs: "0 1px 2px rgb(var(--hm-ombre) / 0.06)",
      sm: "0 1px 3px rgb(var(--hm-ombre) / 0.08), 0 1px 2px rgb(var(--hm-ombre) / 0.04)",
      md: "0 4px 12px -2px rgb(var(--hm-ombre) / 0.10), 0 2px 4px -2px rgb(var(--hm-ombre) / 0.06)",
      lg: "0 12px 28px -6px rgb(var(--hm-ombre) / 0.16), 0 4px 8px -4px rgb(var(--hm-ombre) / 0.08)",
      xl: "0 24px 56px -12px rgb(var(--hm-ombre) / 0.26)",
      inner: "inset 0 1px 2px rgb(var(--hm-ombre) / 0.08)",
    },
    extend: {
      colors: {
        primary: {
          50: "#EDFAF6", 100: "#D2F2E9", 200: "#A7E4D4", 300: "#6FD0BA", 400: "#36B49B",
          500: "#129A81", 600: "#00806A", 700: "#006656", 800: "#0A5146", 900: "#0C433B",
          950: "#032722",
        },
        secondary: {
          50: "#FDF8EC", 100: "#F9EDCB", 200: "#F2D993", 300: "#EBC05A", 400: "#E3A72E",
          500: "#CC8A14", 600: "#A96D0E", 700: "#8A5410", 800: "#714414", 900: "#5E3915",
          950: "#361D07",
        },
        success: {
          50: "#EEFBEE", 100: "#D6F5D6", 200: "#AFE9AF", 300: "#7AD77A", 400: "#45BE45",
          500: "#16A316", 600: "#0E870E", 700: "#0B6B0E", 800: "#0E5512", 900: "#0D4612",
          950: "#032706",
          soft: role("succes-doux"), ink: role("succes-encre"),
        },
        warning: {
          50: "#FFF9EB", 100: "#FEEFC7", 200: "#FDDD8A", 300: "#FCC64D", 400: "#FAB219",
          500: "#F4950B", 600: "#D87006", 700: "#B34F09", 800: "#913D0E", 900: "#77330F",
          950: "#451903",
          soft: role("alerte-doux"), ink: role("alerte-encre"),
        },
        error: {
          50: "#FDF3F3", 100: "#FBE4E4", 200: "#F8CDCD", 300: "#F2A8A8", 400: "#E87676",
          500: "#DB4C4C", 600: "#C73535", 700: "#A72929", 800: "#8A2626", 900: "#742525",
          950: "#3F0F0F",
          soft: role("erreur-doux"), ink: role("erreur-encre"),
        },
        neutral: {
          50: "#FAFAF7", 100: "#F4F3EE", 200: "#E7E5DD", 300: "#D3D0C5", 400: "#A8A498",
          500: "#7D796E", 600: "#605D54", 700: "#4A4841", 800: "#2F2E29", 900: "#1C1C18",
          950: "#0F0F0C",
        },
        // Rôles — ce que les composants emploient.
        bg: role("fond"),
        surface: { DEFAULT: role("surface"), raised: role("surface-haute"), sunken: role("surface-creuse") },
        ink: { DEFAULT: role("encre"), muted: role("encre-muette"), inverse: role("encre-inverse") },
        line: { DEFAULT: role("filet"), strong: role("filet-fort") },
        brand: {
          DEFAULT: role("marque"), hover: role("marque-survol"), soft: role("marque-douce"),
          ink: role("marque-encre"), on: role("sur-marque"),
        },
        accent: { DEFAULT: role("accent"), soft: role("accent-doux"), ink: role("accent-encre"), on: role("sur-accent") },
        focus: role("focus"),
      },
      maxWidth: { contenu: "80rem", lecture: "42rem" },
      transitionTimingFunction: { sortie: "cubic-bezier(0.16, 1, 0.3, 1)" },
      keyframes: {
        miroiter: { "100%": { transform: "translateX(100%)" } },
        apparaitre: { from: { opacity: "0", transform: "translateY(8px) scale(0.98)" }, to: { opacity: "1", transform: "none" } },
        tourner: { to: { transform: "rotate(360deg)" } },
      },
      animation: {
        miroiter: "miroiter 1.4s ease-in-out infinite",
        apparaitre: "apparaitre 220ms cubic-bezier(0.16, 1, 0.3, 1)",
        tourner: "tourner 0.8s linear infinite",
      },
    },
  },
  corePlugins: { container: false },
  plugins: [],
};
