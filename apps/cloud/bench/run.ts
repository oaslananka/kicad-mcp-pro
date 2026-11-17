import "./config.bench.js";
import "./connector-protocol.bench.js";
import "./device-pairing.bench.js";
import "./ingress.bench.js";
import "./ui.bench.js";
import {runBenchmarks} from "./bench-api.js";

await runBenchmarks();
