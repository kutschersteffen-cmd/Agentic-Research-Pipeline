from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class RfpLibraryEntryOut(BaseModel):
    id: int
    question: str
    answer: str
    tags: list[str]
    source: str  # "<file> <location>", "project <id>" or "written by <user>"
    source_file: str | None
    source_location: str | None
    source_project_id: int | None
    written_by: str | None
    approved_on: date
    review_by: date
    owner: str | None
    has_figures: bool
    status: str


class RfpLibraryEntryEdit(BaseModel):
    answer: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    owner: str | None = None
    review_by: date | None = None


class RfpLibraryImportOut(BaseModel):
    imported: int
    dropped: list[str]


class RfpSourceOut(BaseModel):
    kind: Literal["entry", "document"]  # a source stored before kinds existed is an entry
    entry_id: int | None = None
    entry_question: str | None = None
    quote: str
    source: str | None = None
    file: str | None
    location: str | None = None
    written_by: str | None = None


class RfpSegment(BaseModel):
    text: str
    change: Literal["kept", "added", "removed"]


class RfpQuestionOut(BaseModel):
    id: int
    location: str
    answer_location: str
    question: str
    answer: str
    status: str
    flags: list[str]
    assignee: str | None
    last_editor: str | None
    sources: list[RfpSourceOut]
    document_priority: int | None  # 0: drafted from approved answers only; null: nothing drafted
    base_entry_id: int | None
    kept_share: int | None  # kept words as a whole percentage of kept, added and removed words
    segments: list[RfpSegment]  # the answer compared with the base entry's answer; empty without a base entry


class RfpProjectSummary(BaseModel):
    id: int
    investor: str
    due_date: date | None
    filename: str
    run_status: str
    not_located: int
    question_count: int
    approved_count: int


class RfpProjectOut(RfpProjectSummary):
    questions: list[RfpQuestionOut]


class RfpAnswerIn(BaseModel):
    answer: str


class RfpAssigneeIn(BaseModel):
    user_id: str | None


class RfpApproveIn(BaseModel):
    confirmed_flags: list[str] = Field(default_factory=list)
