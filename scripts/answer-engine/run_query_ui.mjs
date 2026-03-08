import { existsSync } from "node:fs";
import { join } from "node:path";
import { spawn } from "node:child_process";

const root = process.cwd();
const base = join(root, "scripts", "answer-engine");
const candidates = process.platform === "win32"
  ? [join(base, ".venv", "Scripts", "python.exe"), join(base, ".venv", "Scripts", "python")]
  : [join(base, ".venv", "bin", "python3"), join(base, ".venv", "bin", "python")];

const python = candidates.find((p) => existsSync(p));

if (!python) {
  console.error("answer-engine UI launcher could not find the local venv Python under scripts/answer-engine/.venv/");
  process.exit(1);
}

const child = spawn(python, [join(base, "query_ui.py"), ...process.argv.slice(2)], {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    VOD_ANSWER_LLM_PROVIDER: process.env.VOD_ANSWER_LLM_PROVIDER || "openai",
  },
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
