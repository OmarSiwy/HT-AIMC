#!/bin/sh
# Sparse clone of OpenROAD-flow-scripts: only the asap7 platform + flow scripts (~250 MB).
# usage: fetch_orfs.sh <tag> <dest>   (tag 26Q2 matches nixpkgs openroad 26Q2)
set -e
git clone --depth 1 --branch "$1" --filter=blob:none --sparse \
  https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git "$2"
git -C "$2" sparse-checkout set --no-cone /flow/platforms/asap7/ /flow/platforms/common/ \
  /flow/scripts/ /flow/util/ /flow/Makefile
