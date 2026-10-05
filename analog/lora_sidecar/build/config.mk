# Analog Block Configuration
BLOCK = lora_sidecar
PROJECT = lora_sidecar
TOP_SCHEMATIC = lora_sidecar
TOP_LAYOUT = lora_sidecar

# Sibling blocks this one is built from, space separated.
#
# A top-level block names the blocks it instantiates; a leaf names nothing. Listing a
# dependency puts its symbols and schematics on this block's xschem library path, so its
# symbol can be placed here, and makes `make deps` build it first.
#
# Set with: make AddAnalogBlock BLOCK_NAME=ota DEPENDS="bandgap diffpair"
DEPENDS = cmos_switch gain_cell_array ota write_dac

# Simulator for `make -C build/sim`: ESPice (VerA golden models run natively, no OSDI).
# Parity with ngspice 45 on sky130 is checked in ESPice docs/sky130.md.
BACKEND ?= espice
