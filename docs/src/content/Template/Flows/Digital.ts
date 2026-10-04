export const metadata = {
    title: "Digital Flow",
    order: 2
}

export const content = `
# Digital Flow

**Design. Verify. Harden.**

## 1. Create Module
Add a new digital block to your project.

\`\`\`bash
make AddDigitalModule MODULE_NAME=my_counter
\`\`\`

## 2. Structure
Your module lives in \`.flows/digital/my_counter/\`:

*   \`src/\`: **Verilog Source**. Put your \`.v\` files here.
*   \`test/\`: **Verification**. Cocotb Python tests and Verilog testbenches.
*   \`build/\`: **Work Area**. Makefiles for simulation, linting, and synthesis.

## 3. Verify
Run your tests using Verilator and Cocotb.

\`\`\`bash
cd .flows/digital/my_counter/build/verification
make verification
\`\`\`

*   **Run All**: \`make verification\`
*   **Run Single**: \`make test TOPLEVEL=tb_my_counter MODULE=test_my_counter\`
*   **Debug**: Waveforms are saved to \`sim_build/rtl/dump.vcd\`.

## 4. Top-Level Integration
The project top-level is created automatically with your project name.

1.  **Instantiate**: Add your sub-modules to \`src/<project_name>.v\`.
2.  **Test**: Write top-level tests in \`test/test_<project_name>.py\`.
3.  **Run**: Execute top-level verification just like any other module.

## 5. Analog Macros
A digital top can contain analog hard macros (blocks from \`analog/<block>/\`).
Declare each one once in \`build/macros.toml\`:

*   \`block\`: the analog block name. Its views default to
    \`analog/<block>/output/{gds,lef,lib,verilog}/<block>.*\`,
    \`analog/<block>/va/<block>_beh.v\` (behavioural model) and
    \`analog/<block>/netlist/<block>.spice\`. Override any of them under \`[macro.views]\`.
*   \`instances\`: instance name as in the RTL, \`location\` (µm) and \`orientation\`.
*   \`halo\`: keep-out (µm) with no std-cell rows and no core power straps.
*   \`pg\`: the macro's **digital** supply pins and the top nets they join (\`VPWR\`/\`VGND\`).
*   \`analog_supplies\`: supply pins kept **off** the digital power grid.
*   \`analog_nets\`: top-level nets (regexes) the flow must never buffer or resize.

The same declaration feeds both sides:

*   **Simulation**: \`build/verification\` and \`build/des_tb\` add each macro's behavioural model.
*   **Hardening**: \`make config\` writes the \`MACROS\` block of the LibreLane config from it.
*   **Check**: \`python3 build/macros.py check build/macros.toml\` fails if the blackbox,
    the behavioural model and the \`.subckt\` disagree on ports. \`make config\` runs it first.

Behavioural models are hand-written Verilog for now. Entries with \`todo = "..."\` are skipped.

## 6. Harden (LibreLane)
\`build/librelane/\` hardens the top with [LibreLane](https://github.com/librelane/librelane)
(the OpenLane 2 successor), which comes from the nix shell.

\`\`\`bash
cd digital/my_counter/build/librelane
make harden-smoke   # toolchain check: counter + dummy macro, sim + harden + DRC/LVS
make harden         # this module: config.yaml -> runs/harden/, views in ../../output/
\`\`\`

*   **Config**: \`config.yaml\` (die area, clock, PDN). Edit it, except the generated block at the bottom.
*   **Output**: \`output/gds\`, \`output/lef\`, \`output/nl\`, ... (LibreLane \`--save-views-to\`),
    the layout TinyTapeout expects.
*   **PDK**: LibreLane 3.0.14 needs the sky130 build it pins, which is newer than the
    \`shell.nix\` volare pin. It fetches that into \`~/.ciel\` on the first run.
`
