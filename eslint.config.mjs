import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Two heuristic rules added by the Next 16 preset flag the standard "load data when the page opens"
    // pattern (an effect that calls an async loader which sets state), which this app uses throughout.
    // They are advisory (about avoiding an extra render), not correctness problems, so they warn rather
    // than fail the build. Migrate those hooks to a data-fetching library before making them errors.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "next-env.d.ts", "backend/**", "public/**", "screenshots/**"]),
]);
