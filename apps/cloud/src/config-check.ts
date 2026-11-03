import { loadConfig } from "./config.js";
import { configuredIdentity } from "./identity.js";
// No values, URLs, token names or credential material are printed.
configuredIdentity(loadConfig());
process.stdout.write("Runtime configuration contract verified.\n");
