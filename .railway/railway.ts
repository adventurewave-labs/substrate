import { defineRailway, image, postgres, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const Postgres = postgres("Postgres", { region: "us-west2" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "us-west2", sizeMB: 50000 });
  const substrateApp = service("substrate-app", {
    source: image("python:3.12-slim"),
    build: { buildEnvironment: "V3", builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "sh -c 'substrate migrate && sleep infinity'",
    replicas: { "us-west2": 1 },
    env: { DATABASE_URL: preserve(), SUBSTRATE_SEC_CONTACT: preserve() },
  });

  return project("substrate", {
    resources: [Postgres, substrateApp, postgresVolume],
  });
});
