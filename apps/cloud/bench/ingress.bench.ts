import { bench, describe } from "vitest";
import type { IncomingMessage } from "node:http";
import { inspectIngressTopology, type IngressTopology } from "../src/ingress-topology.js";
import { trustedCloudflareSource } from "../src/trusted-ingress.js";

const APP = "a".repeat(64), PROXY = "b".repeat(64), DB = "c".repeat(64);

function compliant(): IngressTopology {
  return {
    app: {
      Id: APP, Name: "/app", HostConfig: {
        NetworkMode: "bridge", PortBindings: {}, Privileged: false,
        CapAdd: null, CapDrop: ["ALL"], SecurityOpt: ["no-new-privileges:true"]
      },
      NetworkSettings: { Networks: {
        ingress: { IPAddress: "172.30.0.3", IPAMConfig: { IPv4Address: "172.30.0.3" } },
        database: { IPAddress: "172.31.0.3", IPAMConfig: { IPv4Address: "172.31.0.3" } }
      } }
    },
    proxy: {
      Id: PROXY, Name: "/proxy", HostConfig: {
        NetworkMode: "bridge", PortBindings: {}, Privileged: false, CapDrop: ["ALL"]
      },
      NetworkSettings: { Networks: {
        ingress: { IPAddress: "172.30.0.2", IPAMConfig: { IPv4Address: "172.30.0.2" } },
        outbound: { IPAddress: "172.32.0.5", IPAMConfig: null }
      } }
    },
    networks: [
      { Name: "ingress", Driver: "bridge", Internal: true, Attachable: false,
        Containers: { [APP]: { Name: "app" }, [PROXY]: { Name: "proxy" } } },
      { Name: "database", Driver: "bridge", Internal: true, Attachable: false,
        Containers: { [APP]: { Name: "app" }, [DB]: { Name: "db" } } }
    ],
    privateNetwork: "ingress", expectedProxyIp: "172.30.0.2"
  };
}

function misconfigured(): IngressTopology {
  const state = compliant();
  state.app.HostConfig = {
    NetworkMode: "bridge", PortBindings: { "8787/tcp": [{ HostPort: "8787" }] },
    Privileged: true, CapAdd: ["NET_ADMIN"], CapDrop: []
  };
  state.app.NetworkSettings.Networks.public = { IPAddress: "10.0.0.5" };
  state.networks.push({ Name: "public", Driver: "overlay", Internal: false, Attachable: true });
  state.networks[0].Attachable = true;
  state.networks[0].Containers = { ...state.networks[0].Containers, [DB]: { Name: "db" } };
  return state;
}

const okState = compliant();
const badState = misconfigured();

function incoming(peer: string, headers: Array<[string, string]>): IncomingMessage {
  return { socket: { remoteAddress: peer }, rawHeaders: headers.flat() } as unknown as IncomingMessage;
}
const resolve = trustedCloudflareSource("172.20.0.11,::ffff:172.20.0.12,fd00::11");
const ipv4Request = incoming("172.20.0.11", [
  ["Host", "cloud.example"], ["User-Agent", "bench"], ["CF-Connecting-IP", "198.51.100.70"]
]);
const ipv6Request = incoming("::ffff:ac14:000c", [
  ["Host", "cloud.example"], ["CF-Connecting-IP", "2001:db8:0:0:0:0:0:1"]
]);
const untrustedRequest = incoming("203.0.113.9", [["CF-Connecting-IP", "198.51.100.70"]]);

if (inspectIngressTopology(okState).verdict !== "PREREQUISITES_MET" || !resolve(ipv4Request) || !resolve(ipv6Request)) {
  throw new Error("ingress fixtures must be valid");
}

describe("ingress", () => {
  bench("inspectIngressTopology (compliant)", () => {
    inspectIngressTopology(okState);
  });

  bench("inspectIngressTopology (blocked, many findings)", () => {
    inspectIngressTopology(badState);
  });

  bench("trustedCloudflareSource (build resolver)", () => {
    trustedCloudflareSource("172.20.0.11,::ffff:172.20.0.12,fd00::11");
  });

  bench("resolve client IP (IPv4 peer)", () => {
    resolve(ipv4Request);
  });

  bench("resolve client IP (IPv4-mapped IPv6 peer)", () => {
    resolve(ipv6Request);
  });

  bench("resolve client IP (untrusted peer)", () => {
    resolve(untrustedRequest);
  });
});
