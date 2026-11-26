// portable-docker-images AC-5 / AC-6: the API base the app is built with. Vite fills in
// import.meta.env, so client.ts is loaded through Vite with the env set as a build would.
import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

async function apiBase(env: string | undefined): Promise<unknown> {
  const saved = process.env.VITE_API_BASE;
  if (env === undefined) delete process.env.VITE_API_BASE;
  else process.env.VITE_API_BASE = env;
  const server = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    configFile: false,
    envDir: false, // only the process env, never a developer's frontend/.env
    logLevel: "silent",
    appType: "custom",
    server: { middlewareMode: true, hmr: false },
  });
  try {
    return (await server.ssrLoadModule("/src/api/client.ts")).api.base;
  } finally {
    await server.close();
    if (saved === undefined) delete process.env.VITE_API_BASE;
    else process.env.VITE_API_BASE = saved;
  }
}

test("VITE_API_BASE unset (npm run dev): the API is http://localhost:8000", async () => {
  assert.equal(await apiBase(undefined), "http://localhost:8000");
});

test('VITE_API_BASE="" (the Docker image): the API is on the page\'s own origin', async () => {
  assert.equal(await apiBase(""), "");
});
