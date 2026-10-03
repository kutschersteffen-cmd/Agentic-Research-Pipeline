"""Shared fake for dashboard export/import tests."""

from __future__ import annotations

import io
import zipfile

from arp.bi.superset_client import SupersetError
from tests.test_bi_service import FakeClient

PW = "s3cret-reader-pw"


def make_bundle(*names: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names or ("databases/x.yaml",):
            z.writestr(f"dashboard_export_1/{n}", "x")
    return buf.getvalue()


class ExportClient(FakeClient):
    fail_import = False
    import_published = False
    fail_unpublish = False
    bundle = make_bundle()

    def export_dashboard(self, dashboard_id):
        self.calls.append(("export_dashboard", dashboard_id))
        return self.bundle

    def import_dashboard(self, bundle, db_passwords):
        self.calls.append(("import_dashboard", db_passwords))
        if self.fail_import:
            raise SupersetError(500, f"body with {PW}")
        self.dashboards["arp-hand"] = {
            "id": 900, "published": self.import_published, "charts": [], "position": {}, "meta": None,
        }  # fmt: skip

    def unpublish_dashboard(self, dashboard_id):
        self.calls.append(("unpublish_dashboard", dashboard_id))
        if self.fail_unpublish:
            raise SupersetError(500, "nope")
        next(d for d in self.dashboards.values() if d["id"] == dashboard_id)["published"] = False
