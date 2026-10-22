from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class LibraryEntryOut(BaseModel):
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


class LibraryEntryEdit(BaseModel):
    answer: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    owner: str | None = None
    review_by: date | None = None


class LibraryImportOut(BaseModel):
    imported: int
    dropped: list[str]


class SourceOut(BaseModel):
    entry_id: int
    entry_question: str
    quote: str
    source: str
    file: str | None
    location: str | None
    written_by: str | None


class QuestionOut(BaseModel):
    id: int
    location: str
    answer_location: str
    question: str
    answer: str
    status: str
    flags: list[str]
    assignee: str | None
    last_editor: str | None
    sources: list[SourceOut]


class ProjectSummary(BaseModel):
    id: int
    investor: str
    due_date: date | None
    filename: str
    run_status: str
    not_located: int
    question_count: int
    approved_count: int


class ProjectOut(ProjectSummary):
    questions: list[QuestionOut]


class AnswerIn(BaseModel):
    answer: str


class AssigneeIn(BaseModel):
    user_id: str | None


class ApproveIn(BaseModel):
    confirmed_flags: list[str] = Field(default_factory=list)
