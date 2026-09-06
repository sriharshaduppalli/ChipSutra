@echo off
rem ChipSutra shim: run Verilator inside WSL Ubuntu.
rem Works because dv_verify invokes verilator with RELATIVE filenames from a
rem temp cwd, and WSL maps the Windows cwd to /mnt/... automatically.
wsl -d Ubuntu -e verilator %*
