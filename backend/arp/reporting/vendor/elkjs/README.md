# elkjs (vendored)

- Package: `elkjs` (Eclipse Layout Kernel compiled to JavaScript), https://www.npmjs.com/package/elkjs
- Version: 0.12.1
- File: `elk.bundled.js` is the package's `lib/elk.bundled.js`, unchanged.
- sha256: `b1032b7cfd2a57c54c6f0e8369d7665e19a579954f7cd20a6dae28f1912ea0d7`
- Licence: EPL-2.0 (the package is `EPL-2.0 OR GPL-3.0-or-later`; ARP uses it under EPL-2.0). Full text in `LICENSE.md`.

`arp/reporting/flow_layout.py` loads it into the Chromium page ARP already launches; no Node.js is needed.
To update: `npm pack elkjs@<version>`, copy `lib/elk.bundled.js` and `LICENSE.md` here, and update the version
and sha256 above.
