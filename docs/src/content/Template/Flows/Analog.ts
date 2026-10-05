export const metadata = {
    title: "Analog Flow",
    order: 3
}

export const content = `
# Analog Flow

**Schematic. Layout. Simulate.**

## 1. Create Project
Initialize the analog workspace.

\`\`\`bash
make CreateProject PROJECT_NAME=my_amp PROJECT_TYPE=analog
\`\`\`

## 2. Structure
*   \`schematics/\`: **Circuit Design**. XSchem files (\`.sch\`).
*   \`layout/\`: **Physical Design**. KLayout/Magic files (\`.gds\`, \`.mag\`).
*   \`build/\`: **Work Area**. Makefiles for tools.

## 3. Schematic Design
Draw your circuit in XSchem.

\`\`\`bash
cd .flows/analog/build/schematic
make schematic
\`\`\`

*   **Simulate**: \`make spice\` (Runs Ngspice on your netlist).

## 4. Layout Design
Draw your layout in KLayout.

\`\`\`bash
cd .flows/analog/build/layout
make layout
\`\`\`

*   **Initialize**: \`make init_tinytapeout\` (Creates a TinyTapeout-compatible template).
*   **Convert**: \`make mag2gds\` (Converts Magic files to GDSII).

## 5. Validation
Run DRC and LVS to ensure your layout matches your schematic and rules.

\`\`\`bash
cd .flows/analog/build/validation
make drc
make lvs
\`\`\`

## 6. Hard Macro Views
A block that a parent block or a digital top places needs macro views. From \`analog/<block>/build/layout\`:

\`\`\`bash
make views                   # verified layout -> output/gds/<block>.gds + output/lef/<block>.lef
make deps                    # views of every block in DEPENDS (build/config.mk), deepest first
make pnr-verify RUN=seed1    # PDK klayout DRC + magic/netgen LVS on a Philis GDS
\`\`\`

*   **Route**: \`views\` takes the substrate2 generator (\`make gen gen-drc gen-lvs\`) when
    \`layout/<block>.rs\` exists or \`LAYOUT_ROUTE = gen\`, else the Philis run \`RUN\` after \`pnr-verify\`.
    Philis writes pin text on a non-layer (236/0), so its GDS gets no pins: in practice use the generator.
*   **Views**: \`analog/common/layout/macro_views.py\` renames bus bits \`name<i>\` to \`name[i]\`, checks every
    port has a pin (\`netlist/<block>.ports\` or the \`.subckt\`) and writes a LEF with bbox obstructions on li1..met4.
*   **Liberty** (analogioc): \`make -C analog/analogioc/build/lib lib [ACCURACY=spice]\` writes
    \`output/lib/analogioc__<corner>.lib\` with GPurify from the spec \`layout/liberty.py\` generates.
    \`make lib-interface\` is the no-simulation version (pins, supplies, area).
*   **Top level**: analogioc is hierarchical. Its blocks are laid out one by one, then its generator places them.
`
