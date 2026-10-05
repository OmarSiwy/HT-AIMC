export const metadata = {
    title: "Mixed-Signal Flow",
    order: 4
}

export const content = `
# Mixed-Signal Flow

**Best of both worlds.**

## 1. Create Project
Initialize a workspace with both analog and digital capabilities.

\`\`\`bash
make CreateProject PROJECT_NAME=my_mixed_chip PROJECT_TYPE=mixed
\`\`\`

## 2. Structure
You get complete environments for both domains:

*   \`analog/\`: **Analog Core**. Schematics and Layouts.
*   \`digital/\`: **Digital Logic**. Verilog and Cocotb tests.

## 3. Workflow
1.  **Digital Design**: Build and verify your digital blocks in \`digital/\`.
2.  **Analog Design**: Build your analog circuits in \`analog/\`.
3.  **Integration**:
    *   Harden digital blocks to GDS.
    *   Import digital GDS into the analog layout (or vice-versa).
    *   Connect them at the top level.

## 4. Top-Level Strategy
TinyTapeout expects a top-level wrapper.

*   **Digital Top**: Instantiate analog macros as blackboxes in Verilog.
*   **Analog Top**: Use the analog wrapper and place digital blocks as macros.
*   **Pins**: Define your pinout in \`info.yaml\`. Ensure analog pins are correctly mapped.

## 5. Co-Simulation (RTL + SPICE)
The digital top runs as Verilog **inside** ESPice, so both domains share one transient.

*   **Mechanism**: ESPice loads the RTL with \`.hdl "design.v"\` and instantiates it with an \`N\` card. VerA's event engine runs it as one device.
*   **Bridge**: each device input is an A2D at \`vth\` (VDD/2). Each output is a D2A Thevenin driver (\`rout\`) with \`trise\`/\`tfall\` ramps (150 ps, sky130 std-cell class). All on the macro's \`vdd\` (1.8 V).
*   **Wiring** (\`cosim.py\`): one device pin per macro bit, in \`analogioc.ports\` order. A shell module with the macro's Verilog ports replaces the behavioural model.
*   **Results**: a device has no \`$display\`, so codes leave on observation pins (\`obs_d[7:0]\`, \`obs_v\`). \`cosim.py check\` decodes them from the rawfile and gates them against \`pass_vectors.py\` with ±CODE_TOL (8 LSB).

\`\`\`bash
cd digital/analogioc/build/cosim
make cosim-smoke                  # toy macro, seconds: the bridge end to end
make cosim-elab                   # generate + VerA elaboration only
make cosim                        # A9: pass_05 through the SPICE macro (long)
make cosim PASSES="00 05 09"      # A12: back to back (long)
\`\`\`

Run it inside \`./env.sh mixed\`. \`make cosim\` needs the real \`analog/analogioc/netlist/analogioc.spice\` and \`scripts/compiler/out\`. It also needs the VerA gaps in \`REQUIRED_TOOLING.md\` §4 closed: more than 256 pins, and \`output reg\` ports on part-selects.
`
