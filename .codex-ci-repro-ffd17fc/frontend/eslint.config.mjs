import { defineConfig, globalIgnores } from "eslint/config";
import nextPlugin from "@next/eslint-plugin-next";
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const sourceFiles = ["**/*.{js,mjs,cjs,jsx,ts,tsx}"];

const eslintConfig = defineConfig([
  ...tseslint.configs.recommended,
  { ...react.configs.flat.recommended, files: sourceFiles },
  { ...react.configs.flat["jsx-runtime"], files: sourceFiles },
  { ...reactHooks.configs.flat.recommended, files: sourceFiles },
  { ...jsxA11y.flatConfigs.recommended, files: sourceFiles },
  { ...nextPlugin.configs["core-web-vitals"], files: sourceFiles },
  {
    files: sourceFiles,
    settings: { react: { version: "detect" } },
    rules: {
      "jsx-a11y/click-events-have-key-events": "off",
      "jsx-a11y/no-autofocus": "off",
      "jsx-a11y/no-noninteractive-element-interactions": "off",
      "jsx-a11y/no-static-element-interactions": "off",
    },
  },
  globalIgnores([
    ".next/**",
    "dist/**",
    "out/**",
    "build/**",
  ]),
]);

export default eslintConfig;
