# Analog Block Configuration
BLOCK = analogioc
PROJECT = analogioc
TOP_SCHEMATIC = analogioc
TOP_LAYOUT = analogioc

# Sibling blocks this one is built from, space separated.
#
# A top-level block names the blocks it instantiates; a leaf names nothing. Listing a
# dependency puts its symbols and schematics on this block's xschem library path, so its
# symbol can be placed here, and makes `make deps` build it first.
#
# Set with: make AddAnalogBlock BLOCK_NAME=ota DEPENDS="bandgap diffpair"
DEPENDS = async_ctrl integrator_conv lora_sidecar ota rstring_ladder weight_tile

# Simulator for `make -C build/sim`: ESPice (VerA golden models run natively, no OSDI).
# Parity with ngspice 45 on sky130 is checked in ESPice docs/sky130.md.
BACKEND ?= espice

# Layout route: hierarchical. Every block in DEPENDS gets its own verified layout and macro
# views (`make -C build/layout deps`), then the substrate2 generator layout/analogioc.rs
# places and routes them. Flat Philis is refused: the flattened top is >20k devices
# (2176 6T bitcells alone), and Philis costs ~45-60 min per iteration above 30 FETs.
LAYOUT_ROUTE = gen
