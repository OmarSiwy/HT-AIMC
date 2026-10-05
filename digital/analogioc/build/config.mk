# Digital Project Configuration
PROJECT = analogioc
DESIGN_TOP := analogioc_top
RTL_FILES := $(shell find ../../../ -name "*.v" -o -name "*.sv")
RTL_FILES_H := $(shell find ../../ -name "*.vh" -o -name "*.svh")
TB_FILES := $(shell find ../../test -name "*_tb.v" -o -name "tb_*.v")

# This is used with XSCHEM if in mixed-signal project
TB_TOP := $(CONFIG_DIR)../test/tb_tt_if.sv
TB_TOP_MODULE := tb_tt_if

COCOTB_TEST_FILES := $$(shell find ../../test -name "test_*.py")
# cocotb (build/verification): the toplevel is analogioc_top itself (it instantiates the
# macro, simulated by its behavioural model); icarus, the beh model needs full event control.
SIM ?= icarus
TOPLEVEL_TB_MODULES := analogioc_top
MODULE_TESTS := test_analogioc
PROJECT_TYPE = digital
