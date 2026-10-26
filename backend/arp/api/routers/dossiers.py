from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, get_taxonomy_store
from arp.schemas.common import RunManifest
from arp.schemas.emerging_themes import ContextBrief
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore
from arp.themes.dossiers import (
    Dossier,
    DossierStep,
    DossierStore,
    TaxonomyTaken,
    context_brief,
    current_step,
    derive_steps,
    get_dossier_store,
)
from arp.themes.research import ResearchStore, get_research_store

router = APIRouter(prefix="/api/dossiers", tags=["dossiers"])


class DossierView(Dossier):
    steps: list[DossierStep]
    context_brief: ContextBrief | None = None


class DossierItem(BaseModel):
    dossier_id: str
    name: str
    status: str
    origin: str
    run_id: str | None
    theme_id: str | None
    current_step: int | None
    created_at: str


class DossierList(BaseModel):
    items: list[DossierItem]


class DossierCreate(BaseModel):
    name: str
    taxonomy_id: str | None = None

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()


class DossierPatch(BaseModel):
    taxonomy_id: str | None = None
    status: Literal["shelved"] | None = None
    reason: str | None = None


def _known_taxonomy(taxonomy_store: TaxonomyStore, taxonomy_id: str) -> None:
    if taxonomy_store.get(taxonomy_id) is None:
        raise HTTPException(404, f"unknown taxonomy '{taxonomy_id}'")


def _unknown(dossier_id: str) -> HTTPException:
    return HTTPException(404, f"unknown dossier '{dossier_id}'")


class Viewer:
    """Turns a dossier into its view: the record plus its five steps, derived fresh from the stores."""

    def __init__(self, run_store: RunStore = Depends(get_run_store), taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
                 research_store: ResearchStore = Depends(get_research_store)) -> None:
        self.run_store, self.taxonomy_store, self.research_store = run_store, taxonomy_store, research_store

    def steps(self, dossier: Dossier, theme_runs: list[RunManifest] | None = None) -> list[DossierStep]:
        return derive_steps(dossier, self.run_store, self.taxonomy_store, self.research_store.get(dossier.dossier_id), theme_runs)

    def __call__(self, dossier: Dossier) -> DossierView:
        return DossierView(**dossier.model_dump(), steps=self.steps(dossier),
                           context_brief=context_brief(dossier, self.run_store))


@router.get("", response_model=DossierList)
def list_dossiers(store: DossierStore = Depends(get_dossier_store), view: Viewer = Depends()) -> DossierList:
    theme_runs = view.run_store.list_runs("theme")
    return DossierList(items=[
        DossierItem(
            **d.model_dump(include={"dossier_id", "name", "status", "origin", "run_id", "theme_id", "created_at"}),
            current_step=current_step(view.steps(d, theme_runs)),
        )
        for d in store.list()
    ])


@router.post("", response_model=DossierView)
def create_dossier(
    req: DossierCreate, store: DossierStore = Depends(get_dossier_store), view: Viewer = Depends(),
    principal: Principal = Depends(current_user),
) -> DossierView:
    if req.taxonomy_id:
        _known_taxonomy(view.taxonomy_store, req.taxonomy_id)
    try:
        return view(store.create(req.name, principal.name, taxonomy_id=req.taxonomy_id))
    except TaxonomyTaken as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{dossier_id}", response_model=DossierView)
def get_dossier(dossier_id: str, store: DossierStore = Depends(get_dossier_store), view: Viewer = Depends()) -> DossierView:
    dossier = store.get(dossier_id)
    if dossier is None:
        raise _unknown(dossier_id)
    return view(dossier)


@router.patch("/{dossier_id}", response_model=DossierView)
def patch_dossier(
    dossier_id: str, req: DossierPatch, store: DossierStore = Depends(get_dossier_store), view: Viewer = Depends(),
    principal: Principal = Depends(current_user),
) -> DossierView:
    dossier = store.get(dossier_id)
    if dossier is None:
        raise _unknown(dossier_id)
    if req.status == "shelved" and not (req.reason or "").strip():
        raise HTTPException(422, "a reason is required to shelve a dossier")
    if req.taxonomy_id:
        _known_taxonomy(view.taxonomy_store, req.taxonomy_id)
        try:
            dossier = store.attach(dossier_id, req.taxonomy_id)
        except TaxonomyTaken as exc:
            raise HTTPException(409, str(exc)) from exc
    if req.status == "shelved":
        dossier = store.shelve(dossier_id, principal.name, req.reason.strip())
    if dossier is None:
        raise _unknown(dossier_id)
    return view(dossier)
