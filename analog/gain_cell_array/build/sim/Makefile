include ../config.mk

# Enforce Nix Shell
ifndef IN_NIX_SHELL
  $(error This Makefile must be run inside the nix-shell environment. Run ./env.sh first to enter the nix-shell)
endif

# Run the block's SpiceRack testbenches.
#
# A testbench here is just a Python script under ../../test/ that builds a circuit and
# runs an analysis. Same convention as the netlist scripts one stage over: the script is
# the interface, so a plain sweep and a full DesignBench with corners are the same kind
# of thing to this Makefile and neither needs a plugin API.
#
# Sizing lives in those scripts too. SpiceRack has sweeps, corners and metric extraction
# but no gm/Id or optimiser, so a sizing loop is Python you write — sweep, extract,
# adjust. There is deliberately no target here pretending otherwise.

TEST_DIR = ../../test
CORNERS = ../../../common/corners.py
# Which DUT the testbenches drive: va (golden model), sch (netlist), pex (post-layout).
DUT ?= sch
export DUT

.PHONY: all sim test corners mc list clean

all: sim

## sim - run every nominal testbench (tb_*.py, not *_mc.py) in ../../test/
sim: test

test:
	@found=0; failed=""; for f in $(TEST_DIR)/tb_*.py; do \
		[ -f "$$f" ] || continue; case "$$f" in *_mc.py) continue;; esac; found=1; \
		echo "=== $$f (DUT=$(DUT), backend: $(BACKEND)) ==="; \
		SPICERACK_BACKEND=$(BACKEND) python3 "$$f" || failed="$$failed $$(basename $$f)"; \
	done; \
	if [ $$found -eq 0 ]; then echo "No tb_*.py testbenches in $(TEST_DIR)/."; fi; \
	if [ -n "$$failed" ]; then echo "FAILED:$$failed"; exit 1; fi

## corners - every nominal testbench across PDK corners x temperatures
corners:
	@for f in $(TEST_DIR)/tb_*.py; do \
		[ -f "$$f" ] || continue; case "$$f" in *_mc.py) continue;; esac; \
		python3 $(CORNERS) "$$f" || exit 1; \
	done

## mc - Monte Carlo testbenches (*_mc.py); MC_N sets the sample count
mc:
	@for f in $(TEST_DIR)/*_mc.py; do \
		[ -f "$$f" ] || continue; python3 "$$f" || exit 1; \
	done

## list - which simulators this environment can actually reach
list:
	@echo "BACKEND = $(BACKEND)"
	@for s in ngspice vacask espice; do \
		if command -v $$s >/dev/null 2>&1; then echo "  $$s: available"; \
		else echo "  $$s: not on PATH"; fi; \
	done
	@python3 -c 'import spicerack; print("  spicerack:", spicerack.__name__, "ok")' 2>/dev/null \
		|| echo "  spicerack: not importable — re-enter ./env.sh"

clean:
	@rm -rf __pycache__ $(TEST_DIR)/__pycache__ *.raw *.log
	@echo "Clean complete"
