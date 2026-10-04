{ pkgs, librelane }:
{
  packages = with pkgs; [
    # Simulation & Verification
    verilator
    iverilog
    yosys
    gtkwave
    python312Packages.cocotb

    # LibreLane (OpenLane 2 successor) from its own flake, pinned in shell.nix. Its
    # wrapper carries its own openroad/opensta/magic/netgen/klayout on PATH, so the
    # hardening flow does not depend on the nixpkgs versions below.
    librelane.packages.${pkgs.system}.librelane

    # Old OpenLane deps, kept for the synthesis/ Makefile's xschem helpers
    tcl
    tk
    tclPackages.tcllib
    ruby
    stdenv.cc.cc.lib
    expat
    swig
    zlib
    gcc.cc.lib
  ];
  shellHook = ''
    # Point Python to find tkinter from Nix
    export PYTHONPATH="${pkgs.python312Packages.tkinter}/lib/python3.12/site-packages:$PYTHONPATH"
    export TCL_LIBRARY="${pkgs.tcl}/lib/tcl${pkgs.tcl.version}"
    export TK_LIBRARY="${pkgs.tk}/lib/tk${pkgs.tk.version}"
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.gcc.cc.lib}/lib:${pkgs.tk}/lib:${pkgs.tcl}/lib:${pkgs.expat}/lib:${pkgs.zlib}/lib:$LD_LIBRARY_PATH"
  '';
}
