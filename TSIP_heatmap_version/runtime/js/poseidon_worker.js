"use strict";

const readline = require("readline");
const { buildPoseidon } = require("circomlibjs");

async function main() {
  const poseidon = await buildPoseidon();
  const field = poseidon.F;
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

  input.on("line", (line) => {
    let request;
    try {
      request = JSON.parse(line);
      if (request.op !== "hash" || !Array.isArray(request.values)) {
        throw new Error("expected hash request with values");
      }
      if (request.values.length < 1 || request.values.length > 16) {
        throw new Error("unsupported Poseidon arity");
      }
      const value = field.toObject(poseidon(request.values.map((item) => BigInt(item))));
      process.stdout.write(JSON.stringify({ ok: true, value: value.toString() }) + "\n");
    } catch (error) {
      process.stdout.write(JSON.stringify({ ok: false, error: String(error.message || error) }) + "\n");
    }
  });
}

main().catch((error) => {
  process.stderr.write(String(error.stack || error) + "\n");
  process.exit(1);
});
