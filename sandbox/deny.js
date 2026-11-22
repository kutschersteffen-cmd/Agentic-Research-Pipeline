// The isolate's global outbound: every fetch() or connect() from exploration code ends here and fails.
export default {
  async fetch() {
    throw new Error("network access is not allowed");
  },
  async connect() {
    throw new Error("network access is not allowed");
  },
};
