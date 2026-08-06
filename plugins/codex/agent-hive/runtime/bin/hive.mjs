#!/usr/bin/env node

import { runCli } from "../src/cli.mjs";

runCli(process.argv.slice(2))
  .then((result) => {
    if (!result?.state) return;
    const succeeded = result.state.status === "completed"
      || (result.state.status === "dry_run" && result.state.reason === "ready");
    if (!succeeded) process.exitCode = 2;
  })
  .catch((error) => {
    console.error(`hive: ${error.message}`);
    process.exitCode = 1;
  });
