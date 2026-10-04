# Analog Block Configuration
BLOCK = write_dac
PROJECT = write_dac
TOP_SCHEMATIC = write_dac
TOP_LAYOUT = write_dac

# Sibling blocks this one is built from, space separated.
#
# A top-level block names the blocks it instantiates; a leaf names nothing. Listing a
# dependency puts its symbols and schematics on this block's xschem library path, so its
# symbol can be placed here, and makes `make deps` build it first.
#
# Set with: make AddAnalogBlock BLOCK_NAME=ota DEPENDS="bandgap diffpair"
DEPENDS = cmos_switch

# Simulator for `make -C build/sim`. ngspice is the one to trust for anything headed
# to silicon; vacask is the other SpiceRack backend. ESPice (ARPice) and EGSpice are not
# SpiceRack backends yet (see the analog-design-flow skill).
BACKEND ?= ngspice
