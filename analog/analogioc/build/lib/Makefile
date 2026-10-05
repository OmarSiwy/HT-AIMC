# Liberty for the analogioc hard macro: `gpurify lib` on the macro views.
#
#   make spec   output/lib/liberty.json from netlist/analogioc.ports (layout/liberty.py), cheap
#   make lib    + gpurify lib -> output/lib/analogioc__<corner>.lib (tt, ss, ff) and min/
#               [ACCURACY=spice] interface|analytical|field|spice|statistical (GPurify levels)
#   make lib-interface   ACCURACY=interface: pins, supplies and area only, no simulation.
#                        Enough for floorplanning and `make -C digital/analogioc/build/librelane config`.
#
# Needs output/gds/analogioc.gds + output/lef/analogioc.lef (`make -C ../layout views`).
# Tools: gpurify (GPURIFY, not in the nix shell yet: REQUIRED_TOOLING.md) and its rule deck
# (GPURIFY_DECK). Above `interface` GPurify drives ngspice in pipe mode (GPURIFY_SIM, set
# into the spec; the analog shell has ESPice only, so: nix-shell -p ngspice).
# Cost: `spice` simulates the whole extracted macro per arc x slew x load x corner
# (53 arcs, 2 x 2 tables, 3 corners). Start it in the background and expect hours to days.
include ../config.mk

GPURIFY ?= gpurify
GPURIFY_DECK ?=
ACCURACY ?= spice
OUT = ../../output
LIB = $(OUT)/lib
SPEC = $(LIB)/liberty.json
GDS = $(OUT)/gds/$(BLOCK).gds
LEF = $(OUT)/lef/$(BLOCK).lef
# the .subckt with Verilog bit names, as the spec and the LEF spell them
REF = $(LIB)/$(BLOCK)_ref.spice

.PHONY: spec lib lib-interface clean

spec:
	python3 ../../layout/liberty.py $(SPEC)

lib: spec
	@[ -f $(GDS) ] && [ -f $(LEF) ] || { echo "No $(GDS) / $(LEF): make -C ../layout views first"; exit 1; }
	@command -v $(GPURIFY) >/dev/null || { echo "gpurify not on PATH (GPURIFY=/path/to/gpurify)"; exit 1; }
	@[ -f "$(GPURIFY_DECK)" ] || { echo "No GPurify rule deck at '$(GPURIFY_DECK)': set GPURIFY_DECK=.../pdks/sky130.deck"; exit 1; }
	sed -e 's/<\([0-9]*\)>/[\1]/g' ../../netlist/$(BLOCK).spice > $(REF)
	$(GPURIFY) lib $(GDS) --deck $(GPURIFY_DECK) --grid 1000 --spec $(SPEC) \
		--accuracy $(ACCURACY) --output-dir $(LIB) --reference $(REF) --lef $(LEF)

lib-interface:
	$(MAKE) lib ACCURACY=interface

clean:
	rm -rf $(LIB)
