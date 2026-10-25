// Serves the repository's sample telemetry so "Try sample data" runs the real upload pipeline.
import { copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const source = fileURLToPath(new URL("../../sample_test_input.csv", import.meta.url));
const target = fileURLToPath(new URL("../public/sample_test_input.csv", import.meta.url));
copyFileSync(source, target);
