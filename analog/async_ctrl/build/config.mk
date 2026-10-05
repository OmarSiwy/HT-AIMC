# Analog Block Configuration
BLOCK = async_ctrl
PROJECT = async_ctrl
TOP_SCHEMATIC = async_ctrl
TOP_LAYOUT = async_ctrl

# Sibling blocks this one is built from, space separated.
#
# A top-level block names the blocks it instantiates; a leaf names nothing. Listing a
# dependency puts its symbols and schematics on this block's xschem library path, so its
# symbol can be placed here, and makes `make deps` build it first.
#
# Set with: make AddAnalogBlock BLOCK_NAME=ota DEPENDS="bandgap diffpair"
DEPENDS = 

# Simulator for `make -C build/sim`: ESPice (VerA golden models run natively, no OSDI).
# Parity with ngspice 45 on sky130 is checked in ESPice docs/sky130.md.
BACKEND ?= espice
