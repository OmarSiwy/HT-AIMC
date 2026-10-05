# ORFS (OpenROAD-flow-scripts 26Q2) design config: sa_top on ASAP7, RVT, TT corner.
# Driven by ../Makefile (`make harden SIZE=16 PERIOD_PS=...`), not used standalone.
SYSREF_DIR := $(abspath $(dir $(DESIGN_CONFIG))/../..)
SIZE       ?= 16

export PLATFORM           = asap7
export DESIGN_NAME        = sa_top
export DESIGN_NICKNAME    = sa_top_$(SIZE)
export VERILOG_FILES      = $(sort $(wildcard $(SYSREF_DIR)/src/*.sv))
export VERILOG_TOP_PARAMS = Rows $(SIZE) Cols $(SIZE) AccDepth $(SIZE)
export SDC_FILE           = $(WORK_HOME)/sa_top_$(SIZE).sdc

export CORE_UTILIZATION   = 55
export CORE_ASPECT_RATIO  = 1
export CORE_MARGIN        = 2
export PLACE_DENSITY      = 0.65
