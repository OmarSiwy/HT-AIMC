# sa_top: single clock, IO budgeted at 20% of the period (ASAP7 time unit: ps).
# Template: ../Makefile substitutes @PERIOD_PS@ (ORFS parses a literal clk_period).
current_design sa_top
set clk_period @PERIOD_PS@
set clk_port [get_ports clk_i]
create_clock -name core_clock -period $clk_period $clk_port
set non_clock_inputs [lsearch -inline -all -not -exact [all_inputs] $clk_port]
set_input_delay  [expr $clk_period * 0.2] -clock core_clock $non_clock_inputs
set_output_delay [expr $clk_period * 0.2] -clock core_clock [all_outputs]
