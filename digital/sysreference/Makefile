# Digital systolic-array reference (baseline the analog IMC must beat).
# Tools from nix:  nix-shell -p iverilog verilator yosys 'python3.withPackages(p:[p.numpy])'
#   make test    numpy golden -> cycle-exact schedule -> iverilog, bit-exact (+ SmolLM2 GEMM)
#   make lint    verilator -Wall over every configuration the PPA study uses
#   make synth   yosys + ASAP7 liberty area/cell sweep  -> build/synth/*.json
#   make ppa     ORFS asap7 harden + VCD power, then ppa.json (see build/Makefile)
SRC := $(wildcard src/*.sv)

.PHONY: test lint synth ppa clean

test:
	python3 test/run_tests.py

lint:
	verilator --lint-only -Wall --top-module sa_top $(SRC)
	verilator --lint-only -Wall --top-module sa_top -GPipeMul=0 $(SRC)
	verilator --lint-only -Wall --top-module sa_top -GWW=4 $(SRC)
	verilator --lint-only -Wall --top-module sa_top -GRows=128 -GCols=128 -GAccDepth=128 $(SRC)
	@echo "LINT CLEAN"

synth ppa:
	$(MAKE) -C build $@

clean:
	rm -rf build/test build/power build/synth build/orfs
