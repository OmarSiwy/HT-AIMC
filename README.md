# AnalogIOC

Analog in-memory-compute (IMC) transformer accelerator on sky130. Charge-domain
capacitive MVM tiles, event-rate + SAR column converters and a gain-cell LoRA sidecar,
plus a digital rail and a GGUF -> hardware compiler with bit-exact golden models.

| Dir | What |
|---|---|
| [`analog/`](./analog) | Analog blocks, one dir per block ([block diagram](./analog/README.md)) |
| [`digital/analogioc/`](./digital/analogioc) | RTL + iverilog testbenches |
| [`scripts/`](./scripts) | `compiler/`, `golden/`, `models/` |
| [`docs/`](./docs) | Docs site: research docs (`src/content/Project/`) + template flow docs |

Spec: [`CONTRACT.md`](./docs/src/content/Project/CONTRACT.md). Status: [`STATUS.md`](./docs/src/content/Project/STATUS.md).
Agents: [`AGENTS.md`](./AGENTS.md). Missing tools: [`REQUIRED_TOOLING.md`](./REQUIRED_TOOLING.md).

## Quick start

```bash
./env.sh                  # Nix shell with every tool (see AGENTS.md "Environment")
cd docs && bun install && bun run dev   # docs site locally
```
