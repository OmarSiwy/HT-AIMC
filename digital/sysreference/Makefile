# Digital systolic-array reference (baseline the analog IMC must beat).
#   make test    numpy golden -> cycle-exact schedule -> iverilog, bit-exact (+ SmolLM2 GEMM, sa_sys)
#   make lint    verilator -Wall over every configuration the PPA study uses
#   make synth   yosys -> ASAP7 RVT, area sweep (TT; s8/s16 also FF/SS)  -> build/ppa/synth
#   make place   OpenROAD place + CTS + STA (s8 TT/FF/SS, s16 TT)          -> build/ppa/place
#   make power   gate-level iverilog VCD -> OpenSTA report_power (s16 TT)  -> build/ppa/power
#   make ppa     all of the above + build/ppa.json
# Every target runs in its own nix-shell; NIX='sh -c' uses the tools already on PATH.
NIX ?= nix-shell -p 'python3.withPackages(p:[p.numpy])' iverilog verilator yosys openroad --run
SRC := $(wildcard src/*.sv)

.PHONY: test lint synth place power report ppa clean

test:
	$(NIX) 'python3 test/run_tests.py'

lint:
	$(NIX) 'set -e; \
	verilator --lint-only -Wall --top-module sa_top $(SRC); \
	verilator --lint-only -Wall --top-module sa_top -GPipeMul=0 $(SRC); \
	verilator --lint-only -Wall --top-module sa_top -GWW=4 $(SRC); \
	verilator --lint-only -Wall --top-module sa_top -GRows=128 -GCols=128 -GAccDepth=128 $(SRC); \
	verilator --lint-only -Wall -Wno-UNUSEDSIGNAL --top-module sa_sys $(SRC); \
	echo LINT CLEAN'

synth place power report:
	$(NIX) 'python3 scripts/ppa.py $@'

ppa:
	$(NIX) 'python3 scripts/ppa.py all'

clean:
	rm -rf build
