# AnalogIOC-mini near-tile digital rail (A4)
# Tools come from nix: nix-shell -p iverilog yosys --run 'make test synth'
RTL     := $(wildcard src/*.v)
TB_SRCS := $(wildcard test/tb_*.v)
TESTS   := $(patsubst test/%.v,%,$(TB_SRCS))
LIB     := $(HOME)/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

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
