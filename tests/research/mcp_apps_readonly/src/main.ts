import { startFixtureServer } from "./server.js";
const port = Number(process.env.PORT ?? "3001");
startFixtureServer(port).catch(() => {
  console.error("Unable to start isolated synthetic fixture server");
  process.exitCode = 1;
});
