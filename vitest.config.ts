import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts", "components/**/*.test.tsx", "tests/**/*.test.ts"],
    coverage: {
      provider: "v8",
      include: ["lib/**/*.ts", "components/ui/safe-markdown.tsx"],
      exclude: ["lib/api-client/**", "lib/**/*.test.ts"],
      reporter: ["text-summary", "lcov"],
    },
  },
});
