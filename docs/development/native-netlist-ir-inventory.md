# Native KiCad netlist vs semantic IR inventory (#944)

The existing root-sheet semantic `IRCircuit` parser may discover sheet paths
without populating child-sheet components or nets. On the real KiCad 10.0.6
Jetson AGX Thor demo, independent Eeschema XML export reported 1,123 referenced
components and 1,355 nets, while the current IR exposed only 7 components and
29 nets. Those counts establish a known incomplete hierarchy; they **do not**
prove that PCB footprint count should equal schematic component count.

Run a read-only *inventory gate* before using a hierarchical IR as evidence for
Engineering Graph coverage. First make a disposable, complete copy of the
KiCad project and **all its hierarchical sheet files** outside the repository;
never publish its unredacted XML netlist. Export from that copy using the
installed native KiCad runtime:

```sh
kicad-cli sch export netlist --format kicadxml \
  -o /path/to/scratch/native.xml /path/to/scratch/root.kicad_sch
python scripts/compare_native_netlist_ir.py \
  --native-xml /path/to/scratch/native.xml \
  --schematic /path/to/scratch/root.kicad_sch
```

The command does not invoke a subprocess or modify the input. It uses the
existing semantic parser to load the same root file and compares **exact
non-power component references**, as well as net *counts*. Native power-library
symbols are excluded only from component identity comparison because the IR
models those as rails. A matching number of different references is a failure.
Missing/duplicate/native-XML parsing failures are hard errors.

Return codes: `0` = component identities and net counts match; `1` = inventory
mismatch; `2` = parsing/input/runtime failure. Every JSON result deliberately
includes `graph_equivalent: false`: net names and pin-level connectivity,
hierarchical UUID/path identities, Engineering Graph clean-rebuild equivalence,
incremental invalidation, native mutation read-back, p50/p95 and peak RSS **are
not verified** by this inventory gate. A `0` is never #944 acceptance.

The tool performs only local read-only comparison. A full #944 acceptance suite
still requires the maintained 1,000+ real source, a complete native↔IR identity
adapter, pin/net equivalence, correct external-edit invalidation and actual
bounded incremental update performance. Mock XML tests only validate this
comparator's fail-closed logic; they are not native KiCad success evidence.
