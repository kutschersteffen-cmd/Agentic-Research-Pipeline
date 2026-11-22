# workerd config for one execution; server.mjs starts a fresh process per execution and sets the socket port and
# the ARP API address on the command line.
using Workerd = import "/workerd/workerd.capnp";

const config :Workerd.Config = (
  services = [
    (name = "host", worker = .host),
    (name = "deny", worker = .deny),
    (name = "arp", external = (address = "127.0.0.1:8000", http = ())),
  ],
  sockets = [(name = "http", address = "127.0.0.1:0", http = (), service = "host")],
);

const host :Workerd.Worker = (
  modules = [(name = "host.js", esModule = embed "dist/host.js")],
  compatibilityDate = "2025-06-01",
  bindings = [
    (name = "LOADER", workerLoader = ()),
    (name = "DENY", service = "deny"),
    (name = "ARP", service = "arp"),
  ],
  globalOutbound = "deny",
);

const deny :Workerd.Worker = (
  modules = [(name = "deny.js", esModule = embed "deny.js")],
  compatibilityDate = "2025-06-01",
);
