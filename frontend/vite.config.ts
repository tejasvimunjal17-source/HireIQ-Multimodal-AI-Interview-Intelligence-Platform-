import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // host: true lets a phone on the same Wi-Fi open the dev server.
  // NOTE: browsers only allow the microphone on https:// or localhost (see README).
  server: { host: true, port: 5173 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
