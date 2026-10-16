import { parentPort, workerData } from "node:worker_threads";
import { runCheck } from "../dist/mod.js";
try {
  parentPort.postMessage({
    result: runCheck(workerData.files, workerData.check),
  });
} catch (error) {
  parentPort.postMessage({ error: String(error), name: error?.name });
}
