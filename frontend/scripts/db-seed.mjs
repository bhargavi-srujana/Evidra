// `npm run db:seed` — runs backend/scripts/seed.py with the backend as cwd
// so its .env is picked up. Prefers `uv` (the repo's runner), falls back
// to system Pythons. Propagates the seed script's exit code.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const backendDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "backend",
);
const seedScript = path.join("scripts", "seed.py");

const candidates =
  process.platform === "win32"
    ? [
        { cmd: "uv", args: ["run", "python", seedScript] },
        { cmd: "py", args: [seedScript] },
        { cmd: "python", args: [seedScript] },
        { cmd: "python3", args: [seedScript] },
      ]
    : [
        { cmd: "uv", args: ["run", "python", seedScript] },
        { cmd: "python3", args: [seedScript] },
        { cmd: "python", args: [seedScript] },
      ];

let ran = false;
for (const { cmd, args } of candidates) {
  const result = spawnSync(cmd, args, { cwd: backendDir, stdio: "inherit" });
  if (result.error?.code === "ENOENT") continue; // binary missing — try next
  ran = true;
  process.exit(result.status ?? 1);
}

if (!ran) {
  console.error(
    "db:seed failed: no Python runner found. Install uv (https://docs.astral.sh/uv/) " +
      "or Python 3.11+, then retry. You can also run directly: " +
      "`cd backend && uv run python scripts/seed.py`",
  );
  process.exit(1);
}
