from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from arp.schemas.common import DocType, now_iso, new_id


class DocumentEventType(StrEnum):
    NEW_DOCUMENT = "new_document"
    UPDATED_DOCUMENT = "updated_document"


class DiscoveredDocument(BaseModel):
    company_id: str
    doc_type: DocType
    url: str
    local_path: str | None = None
    sha256: str | None = None
    http_last_modified: str | None = None
    http_etag: str | None = None
    discovered_at: str = Field(default_factory=now_iso)


class DocumentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: DocumentEventType
    company_id: str
    company_name: str | None = None
    document: DiscoveredDocument
    created_at: str = Field(default_factory=now_iso)


class DiscoveryRunParams(BaseModel):
    universe_source: str = Field(description="Path or identifier of the company universe used for this run.")
    doc_types: list[DocType] = Field(default_factory=list, description="Empty = all supported types.")
    triggered_by: str = Field(default="manual", description="'manual' or 'schedule'.")


class DiscoveryCompanyResult(BaseModel):
    company_id: str
    name: str
    homepage_used: str | None = None
    documents_found: list[DiscoveredDocument] = Field(default_factory=list)
    new_events: list[DocumentEvent] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)


class DiscoveryScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: float = 24.0
    universe_path: str | None = None
    doc_types: list[DocType] = Field(default_factory=list)
    last_run_id: str | None = None
    next_run_at: str | None = None
