# OpenShell Code Mode prototype

The opt-in CLI compares the original synthetic holdings benchmark on a local
Cloudflare Dynamic Worker and on OpenShell. The voting demo composes read-only
sector aggregation calls in JavaScript and runs a second, fixed Python job on
issuer aggregates. Run the CLI from an environment with ARP installed.

## Local checks

From the repository root:

```sh
python -m pip install -e ./backend pyarrow==23.0.1 PyYAML==6.0.3
npm ci --prefix scripts/openshell-code-mode
npm test --prefix scripts/openshell-code-mode
```

These checks use a real local Dynamic Worker, the QuickJS executor used inside
the OpenShell image, and a loopback tool gateway. OpenShell lifecycle and
network policy verification require a configured host.

## OpenShell host

Use an approved OpenShell gateway with Docker-based sandboxes and the CLI
configured to select it. Build the two images from the repository root:

```sh
docker build -f scripts/openshell-code-mode/Dockerfile.javascript -t arp-openshell-js scripts/openshell-code-mode
docker build -f scripts/openshell-code-mode/Dockerfile.python -t arp-openshell-python .
```

Publish them to an approved registry, then set the corresponding `ARP_OPENSHELL_JAVASCRIPT_IMAGE` and
`ARP_OPENSHELL_PYTHON_IMAGE` to the image references ending in
`@sha256:<digest>`.

Set `ARP_OPENSHELL_JAVASCRIPT_POLICY` and `ARP_OPENSHELL_PYTHON_POLICY` to the
absolute paths to approved OpenShell policies. Use a fresh sandbox per job.
Give the JavaScript policy one enforced REST endpoint at the private HTTPS
gateway host and port, with the explicit `POST /tool` allow rule and the single
binary `/usr/local/bin/node`. Grant the Python job read-only access to
`/inputs` and an empty network policy. Both jobs read `/opt/arp-code-mode` and
write under `/workspace`. The host checks the effective policy before staging
inputs. Configure the Node runner to trust the gateway's CA if required.

Set `ARP_OPENSHELL_TOOL_GATEWAY_URL` to the HTTPS endpoint ending in `/tool`.
The trusted private proxy forwards that endpoint to the local Node listener at
`127.0.0.1:8788` by default. The listener can be configured through
`ARP_OPENSHELL_TOOL_GATEWAY_BIND_HOST` and
`ARP_OPENSHELL_TOOL_GATEWAY_BIND_PORT`. Preserve the Authorization header in
the proxy and omit it from request logs. Start one invocation at a time.

```sh
python -m arp.prototypes.openshell_code_mode benchmark --executor compare --output-dir /tmp/arp-benchmark
python -m arp.prototypes.openshell_code_mode voting --script fixed --output-dir /tmp/arp-voting
```

Use a fresh output path for each invocation. To generate the voting script with
ARP's configured model, select `--script model`. The model runs in the ARP host
process and the sandbox receives the generated script and scoped tool credential.

For independent real-host checks, start the test-only
`python scripts/openshell-code-mode/probe-receiver.py` service. Set
`ARP_OPENSHELL_PROBE_URL` to the service origin on a private address reachable
from the verifier. Keep the test service outside both sandbox network
allowlists. Set `ARP_OPENSHELL_VERIFY_MODEL=1` to exercise the explicitly
configured ARP model in slice 2. Run:

```sh
scripts/openshell-code-mode/verify-host.sh --slice 1 --evidence-dir /tmp/arp-slice-1
scripts/openshell-code-mode/verify-host.sh --slice 2 --evidence-dir /tmp/arp-slice-2
```

The verifier records missing OpenShell or configured-model evidence as pending.

A real-host pass requires the OpenShell CLI and access to a gateway, both pinned
images, the private tool gateway, and the effective policies. The chart also
requires a visual inspection.
