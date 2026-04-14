# Manufacturing Export

1. Run `project_quality_gate()`.
2. If the gate is not `PASS`, stop and fix the reported blocking issues.
3. Run `pcb_transfer_quality_gate()` to confirm named schematic pad nets survived sync.
4. Run DRC and ERC for detailed reports.
5. Confirm the board stats and DFM summary.
6. Use low-level export tools for debugging artifacts when needed.
7. Treat `export_manufacturing_package()` as the final release step only after the
   project gate is clean.
