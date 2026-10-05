# AnalogIOC-mini near-tile digital rail (A4)
# Tools come from nix: nix-shell -p iverilog yosys --run 'make test synth'
RTL     := $(wildcard src/*.v)
# + behavioural models of the analog macros declared in build/macros.toml
RTL     += $(shell python3 build/macros.py sim build/macros.toml)
TB_SRCS := $(wildcard test/tb_*.v)
TESTS   := $(patsubst test/%.v,%,$(TB_SRCS))
LIB     := $(HOME)/.ciel/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

.PHONY: test synth clean $(TESTS)

test: $(TESTS)
	@echo "ALL DIGITAL TESTS PASS"

$(TESTS): %: test/%.v $(RTL) | build
	iverilog -g2012 -Wall -o build/$@.vvp $< $(RTL)
	vvp build/$@.vvp

synth: | build
	yosys -l build/synth.log synth.ys
	@grep -q "Executing" build/synth.log && echo "SYNTH OK: see build/synth.log, netlist build/rail_top_syn.v"

build:
	mkdir -p build

clean:
	rm -rf build

# === Harden path: analog blocks -> analogioc macro -> analogioc_top (wired 2026-10-05, not run) ===
# Run from ./env.sh mixed (the analog Makefiles need the nix shell). Each step runs alone,
# in this order; `make flow` runs 1-5. Step 6 is blocked (INTERFACE.md §8.3, Q3).
#   1 flow-netlists  every block's VerA lint + netlist (DeSpice scripts), then analogioc's
#   2 flow-blocks    each block's layout by its route + PDK DRC/LVS -> its output/{gds,lef}
#   3 flow-top       analogioc: layout/analogioc.rs places the blocks; DRC/LVS; macro views
#   4 flow-lib       gpurify lib -> analogioc__<corner>.lib [ACCURACY=spice]
#   5 flow-harden    macros.toml -> LibreLane config, harden analogioc_top, macro signoff
#   6 flow-package   TinyTapeout package: needs tt_um_analogioc first
A := ../../analog/analogioc/build
.PHONY: flow flow-netlists flow-blocks flow-top flow-lib flow-harden flow-package

flow: flow-netlists flow-blocks flow-top flow-lib flow-harden

flow-netlists:
	$(MAKE) -C $(A)/schematic deps netlist

flow-blocks:
	$(MAKE) -C $(A)/layout deps

flow-top:
	$(MAKE) -C $(A)/layout views

flow-lib:
	$(MAKE) -C $(A)/lib lib

flow-harden:
	$(MAKE) -C build/librelane harden

flow-package:
	@echo "blocked: TinyTapeout needs tt_um_analogioc (INTERFACE.md §8.3; Q3: 13 analog pins + 5"
	@echo "supplies exceed TT's analog pins; Q12 weight stream). Then:"
	@echo "  make -C ../../.flows CreateCaravel PROJECT_NAME=tt_um_analogioc"
	@exit 1
