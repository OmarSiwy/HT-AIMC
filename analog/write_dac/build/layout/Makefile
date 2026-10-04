include ../config.mk

# Enforce Nix Shell
ifndef IN_NIX_SHELL
  $(error This Makefile must be run inside the nix-shell environment. Run ./env.sh first to enter the nix-shell)
endif
KLAYOUT = klayout
LAYOUT_DIR := $(shell cd ../../layout && pwd)
BUILD_DIR := $(shell pwd)

# Ensure PDK_ROOT is set
ifndef PDK_ROOT
$(error PDK_ROOT is not set. Please run from nix-shell)
endif

ifndef PDK
$(error PDK is not set. Please run from nix-shell)
endif

# === Automated place-and-route (Philis) ===
#
# Philis takes a SPICE deck plus a PDK rule deck and returns placed, routed GDS. It
# bundles GPurify for in-loop DRC, so it is checking as it places rather than handing
# you something to check afterwards.
#
# This is NOT a signoff path and should not be treated as one. On Philis's own suite a
# 2-device mirror converges in seconds while a 4-device chain has taken ~19 minutes and
# finished with DRC violations and an LVS mismatch. Use it to get a starting layout,
# then open it in magic/klayout — or write the layout by hand against macroMaster, which
# is the path that exists precisely because the automated one does not yet scale.
PHILIS ?= philis
NETLIST_DIR = ../../netlist
PNR_OUT = ../../output/pnr

# The rule deck Philis places against. Its nix package installs decks to
# share/philis/pdks next to the binary, so locate them from whatever is on PATH.
# The nix shell exports PHILIS_PDK_DIR; otherwise locate the decks next to the binary.
PHILIS_PDK_DIR ?= $(shell d=$$(command -v $(PHILIS) 2>/dev/null) && \
	echo "$$(dirname $$(dirname $$(readlink -f $$d)))/share/philis/pdks")
PHILIS_PDK ?= $(PHILIS_PDK_DIR)/sky130.json

# Run knobs. Every run gets its own directory (never share one between seeds — a stray
# kill pattern on a shared name takes out other runs). Philis converges with more
# iterations, but costs ~45-60 min PER ITERATION above ~30 FETs: the default budget is
# Philis's own 100 up to 30 FETs and 60 above (count of X/M cards in the P&R deck;
# pwm_driver, 34 FETs, found its best layouts at iterations 40 and 57).
NETLIST ?= $(BLOCK)
SEED ?= 1
SEEDS ?= 1 2
N_FETS = $(shell grep -ciE '^[XM][^ ]* ' $(PNR_DECK) 2>/dev/null || echo 0)
MAX_ITERS ?= $(shell [ $(N_FETS) -gt 30 ] && echo 60 || echo 100)
RUN ?= seed$(SEED)
INTERFACE = ../../layout/interface.json
PNR_DECK ?= $(NETLIST_DIR)/$(NETLIST).spice
PEX = ../../../common/pex.py
PHILIS_ARGS = --seed $(SEED) --max-iters $(MAX_ITERS) \
	$(if $(wildcard $(INTERFACE)),--interface $(INTERFACE))

.PHONY: layout mag2gds init_tinytapeout clean pnr pnr-seeds pex gen gen-drc gen-lvs gen-pex

init_tinytapeout:
	@echo "Initializing TinyTapeout template..."
	@echo "Note: This creates a Magic .mag file that will be converted to GDS for KLayout"
	cd ../../layout && export PDK_ROOT=$(PDK_ROOT) && export PDK=$(PDK) && ( \
		echo "set TOP_LEVEL_CELL_NAME $(TOP_LAYOUT)"; \
		cat ../build/layout/tinytapeout_template.tcl; \
	) | magic -dnull -noconsole -rcfile $(PDK_ROOT)/$(PDK)/libs.tech/magic/$(PDK).magicrc -T $(PDK)
	@echo "TinyTapeout template initialized: ../../layout/$(TOP_LAYOUT).mag"
	@echo "Converting to GDS for KLayout..."
	@$(MAKE) mag2gds
	@echo "Setup complete!"

# Convert .mag to .gds (if you have legacy Magic files)
mag2gds:
	@echo "Converting Magic .mag to GDS..."
	@if [ ! -f ../../layout/$(TOP_LAYOUT).mag ]; then \
		echo "Error: $(TOP_LAYOUT).mag not found"; \
		exit 1; \
	fi
	cd ../../layout && export PDK_ROOT=$(PDK_ROOT) && export PDK=$(PDK) && ( \
		echo "load $(TOP_LAYOUT)"; \
		echo "gds write $(TOP_LAYOUT).gds"; \
		echo "quit -noprompt"; \
	) | magic -dnull -noconsole -rcfile $(PDK_ROOT)/$(PDK)/libs.tech/magic/$(PDK).magicrc -T $(PDK)
	@mkdir -p ../../output/gds
	@cp ../../layout/$(TOP_LAYOUT).gds ../../output/gds/ 2>/dev/null || true
	@echo "GDS file created: ../../layout/$(TOP_LAYOUT).gds"

layout:
	@echo "Opening layout in KLayout for editing..."
	@if [ ! -f ../../layout/$(TOP_LAYOUT).gds ]; then \
		if [ -f ../../layout/$(TOP_LAYOUT).mag ]; then \
			echo "Found .mag file, converting to GDS first..."; \
			$(MAKE) mag2gds; \
		else \
			echo "No layout file found."; \
			echo "Would you like to initialize from TinyTapeout template?"; \
			read -p "Initialize template? (y/n): " choice; \
			if [ "$$choice" = "y" ] || [ "$$choice" = "Y" ]; then \
				$(MAKE) init_tinytapeout; \
			else \
				echo "Creating blank GDS file..."; \
				echo "You can start with an empty layout or import cells from PDK"; \
			fi; \
		fi; \
	fi
	@if [ -f ../../layout/$(TOP_LAYOUT).gds ]; then \
		$(KLAYOUT) -e ../../layout/$(TOP_LAYOUT).gds; \
	else \
		$(KLAYOUT) -e; \
	fi
	@echo "Layout editing session complete"
	@if [ -n "$(PARENT_OUTPUT_DIR)" ]; then \
		echo "Exporting to parent..."; \
		mkdir -p $(PARENT_OUTPUT_DIR); \
		cp ../../layout/$(TOP_LAYOUT).gds $(PARENT_OUTPUT_DIR)/ 2>/dev/null || true; \
		cp ../../layout/$(TOP_LAYOUT).mag $(PARENT_OUTPUT_DIR)/ 2>/dev/null || true; \
		echo "Layout exported to parent project: $(PARENT_OUTPUT_DIR)"; \
	else \
		echo "Layout saved locally"; \
	fi

## pnr - place and route with Philis: make pnr [SEED=1] [MAX_ITERS=...] [PNR_DECK=...]
##       -> output/pnr/seed<N>/. Without layout/interface.json the ports lose their names
##       in the extraction; with several MIM caps, P&R a cap-free PNR_DECK (Philis hangs)
##       and let `make pex` add the caps back from the full deck.
pnr:
	@command -v $(PHILIS) >/dev/null 2>&1 || { \
		echo "philis not found on PATH — it ships in the nix shell via EDA-Packaged."; \
		exit 1; }
	@[ -f "$(PNR_DECK)" ] || { \
		echo "No such deck: $(PNR_DECK)"; \
		echo "Generate it first: make -C ../schematic netlist"; exit 1; }
	@[ -f "$(PHILIS_PDK)" ] || { \
		echo "No Philis rule deck at: $(PHILIS_PDK)"; \
		echo "Set PHILIS_PDK=/path/to/deck.json (packaged: sky130, generic_finfet)."; \
		exit 1; }
	@[ -f "$(INTERFACE)" ] || echo "warning: no $(INTERFACE) — ports will come out as n<id>"
	@grep -qi "^\.subckt" $(PNR_DECK) || { \
		echo "Deck has no .subckt — Philis names the GDS after the subcircuit, so"; \
		echo "without one you get a hidden '.gds' with an empty filename."; \
		echo "Wrap the devices in '.subckt $(NETLIST) <ports>' / '.ends'."; \
		exit 1; }
	@grep -qiE "^[Mm][^ ]* +.*(nmos|pmos) *$$" $(PNR_DECK) && { \
		echo "Deck uses generic model names (nmos/pmos)."; \
		echo "Philis resolves models against the PDK device table and needs the"; \
		echo "qualified names, e.g. sky130_fd_pr__nfet_01v8."; \
		exit 1; } || true
	@mkdir -p $(PNR_OUT)/$(RUN)
	$(PHILIS) run $(PNR_DECK) $(PHILIS_PDK) -o $(PNR_OUT)/$(RUN) $(PHILIS_ARGS)
	@echo "P&R output in $(PNR_OUT)/$(RUN) — quick feedback, not signoff."

## pnr-seeds - one Philis run per seed in parallel: make pnr-seeds SEEDS="1 2"
pnr-seeds:
	@for s in $(SEEDS); do $(MAKE) --no-print-directory pnr SEED=$$s & done; wait
	@for s in $(SEEDS); do echo "seed $$s: $$(grep '^signoff' $(PNR_OUT)/seed$$s/signoff.txt 2>/dev/null)"; done

## pex - Philis extraction -> simulatable post-layout netlist (DUT=pex): make pex RUN=seed2
pex:
	@[ -f "$(PNR_OUT)/$(RUN)/extracted_pex.spice" ] || { \
		echo "No extraction in $(PNR_OUT)/$(RUN) — run make pnr first"; exit 1; }
	python3 $(PEX) $(BLOCK) $(PNR_OUT)/$(RUN)

# === Generated layout (substrate2) ===
#
# The signoff route next to Philis: a Rust generator analog/<block>/layout/<block>.rs (a
# [[bin]] of the analog/common/layout workspace; README.md there) writes
# output/gen/<block>.gds, checked with the PDK's own decks — klayout DRC, magic + netgen
# LVS against netlist/<block>.spice, magic PEX -> output/gen/<block>_pex.spice for
# DUT=pex PEX_FROM=gen. sky130 only: the substrate registry ships no other PDK crate.
GEN_CRATE = ../../../common/layout
VERIFY = python3 $(GEN_CRATE)/verify.py
# the registry's `cache` crate runs protoc at build time
export PROTOC ?= $(shell command -v protoc 2>/dev/null)

## gen - build and run the generator: make gen -> output/gen/<block>.gds
gen:
	@[ -f ../../layout/$(BLOCK).rs ] || { \
		echo "No generator: write layout/$(BLOCK).rs, add it as a [[bin]] to $(GEN_CRATE)/Cargo.toml"; \
		exit 1; }
	@[ -n "$(PROTOC)" ] || { echo "protoc not found (nix-shell -p protobuf, or set PROTOC=...)"; exit 1; }
	# cargo reads the registry from .cargo/config.toml of the cwd, so run it in the crate
	cd $(GEN_CRATE) && cargo run --quiet --bin $(BLOCK)

## gen-drc - klayout sky130A_mr.drc (+ magic DRC count) on output/gen/<block>.gds
gen-drc:
	$(VERIFY) drc $(BLOCK)

## gen-lvs - magic extraction + netgen LVS against netlist/<block>.spice
gen-lvs:
	$(VERIFY) lvs $(BLOCK)

## gen-pex - magic extraction with parasitic C -> output/gen/<block>_pex.spice
gen-pex:
	$(VERIFY) pex $(BLOCK)

clean:
	@echo "Cleaning generated files..."
	rm -rf ./netlist/*.spice
	rm -rf ./magic/*.ext ./magic/*.spice ./magic/*.sim
	rm -rf ./tinytapeout/
	rm -rf ./*_lvs.lyrdb ./*_drc.lyrdb ./*_netgen_lvs.out
	rm -rf ./openlane/runs/
	rm -rf ./gds_output ./reports ./magic
	rm -rf ../../layout/*.mag.bak
	rm -rf ../../output/gds/*.gds
	find . -name "*.log" -delete
	find . -name "*.bak" -delete
	@echo "Clean complete"
