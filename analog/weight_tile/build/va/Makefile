include ../config.mk

# Enforce Nix Shell
ifndef IN_NIX_SHELL
  $(error This Makefile must be run inside the nix-shell environment. Run ./env.sh first to enter the nix-shell)
endif

# Verilog-A golden models: VerA -> ESPice.
#
# There is no build step. A testbench attaches a model with `top.veriloga("<block>.va")`.
# SpiceRack's espice backend emits a `.hdl` card, and ESPice compiles the model through VerA
# on first use (cache in ~/.cache/espice). No OSDI anywhere. `make lint` keeps every
# model VerA-clean. See the vera skill.

VA_DIR = ../../va
VA_SRCS = $(wildcard $(VA_DIR)/*.va)
VERA := $(shell command -v vera 2>/dev/null)

.PHONY: all lint list

all: lint

## lint - every model through `vera --lint`
lint:
	@[ -n "$(VERA)" ] || { echo "vera not on PATH — re-enter ./env.sh"; exit 1; }
	@if [ -z "$(VA_SRCS)" ]; then echo "No .va models in $(VA_DIR)/."; exit 0; fi
	@for f in $(VA_SRCS); do echo "vera --lint $$f"; $(VERA) $$f --lint --allow=W0650 || exit 1; done

## list - the models a testbench can attach
list:
	@for f in $(VA_SRCS); do echo "  $$(cd $$(dirname $$f) && pwd)/$$(basename $$f)"; done
