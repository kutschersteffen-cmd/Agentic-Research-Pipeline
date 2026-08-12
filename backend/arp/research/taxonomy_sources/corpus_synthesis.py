from __future__ import annotations

from pydantic import BaseModel, Field

from arp.llm.base import LLMClient, LLMUsage
from arp.schemas.taxonomy_sources import CorpusSnippet
from arp.schemas.thematic import ActivityDefinition

_SYSTEM_PROMPT = """\
You are a thematic-investment taxonomist doing bottom-up taxonomy \
construction. You are given a macro theme and a corpus of real snippets \
-- company business-activity descriptions, news excerpts, earnings-call \
passages, or thematic-fund holding metadata -- gathered because they \
relate to the theme. Identify the recurring, concrete business activities \
that actually appear in this material, and define each one as a MECE \
activity with plain in-scope/out-of-scope language and seed keywords, the \
same way you would for a top-down taxonomy.

Every activity you propose must be traceable to something that actually \
appears in the corpus -- do not add a plausible-sounding activity that \
isn't backed by the material you were given. If the corpus is too thin, \
repetitive, or off-topic to support a meaningful taxonomy, say so \
honestly in corpus_assessment rather than padding out activities to fill \
the usual 4-10 range."""


class _SynthesizedActivityDraft(BaseModel):
    name: str
    in_scope_description: str
    out_of_scope_description: str
    seed_keywords: list[str] = Field(default_factory=list)


class _SynthesizedActivityDraftList(BaseModel):
    activities: list[_SynthesizedActivityDraft]
    corpus_assessment: str = Field(description="Honest note on how well the corpus actually supports this taxonomy.")


def _format_corpus(corpus: list[CorpusSnippet]) -> str:
    return "\n\n---\n\n".join(f"[{s.source_type.value}:{s.source_ref}]\n{s.text}" for s in corpus)


async def synthesize_activities_from_corpus(
    theme_name: str,
    theme_description: str,
    corpus: list[CorpusSnippet],
    llm: LLMClient,
    max_snippets: int = 40,
) -> tuple[list[ActivityDefinition], str, LLMUsage]:
    """Shared bottom-up synthesis step used by the empirical, news/
    transcript-mining, and ETF-holdings derivation methods -- they differ
    only in how the corpus is gathered, not in how it's turned into
    activities.
    """
    snippets = corpus[:max_snippets]
    prompt = (
        f"Macro theme: {theme_name}\n"
        f"Theme description: {theme_description}\n\n"
        f"Corpus ({len(snippets)} snippets):\n{_format_corpus(snippets)}"
    )
    draft, usage = await llm.complete_structured(
        system=_SYSTEM_PROMPT, prompt=prompt, output_model=_SynthesizedActivityDraftList
    )
    activities = [
        ActivityDefinition(
            name=a.name,
            in_scope_description=a.in_scope_description,
            out_of_scope_description=a.out_of_scope_description,
            seed_keywords=a.seed_keywords,
        )
        for a in draft.activities
    ]
    return activities, draft.corpus_assessment, usage
