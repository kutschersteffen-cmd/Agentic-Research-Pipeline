from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class LeontiefModel:
    """The indirect-exposure tier's view of one `arp io build-full` output
    (see factory.load_model): the build's nodes with output (x > 0), and the
    ICIO code list that labels companies and core sectors, each code mapped
    to the nodes whose EXIOBASE sector it covers.
    """

    codes: list[str]
    labels: dict[str, str]
    edition_label: str
    leontief_inverse: np.ndarray  # (n, n) over the nodes below
    output: np.ndarray  # x per node, M EUR
    regions: np.ndarray  # EXIOBASE region per node
    code_nodes: dict[str, np.ndarray]  # code -> node indices
    ghg_t_per_meur: np.ndarray  # per node, 0 where the build has none
    final_demand: np.ndarray | None = None  # (n, 4), arp.research.indirect_exposure.io_import.FD_GROUPS
    isic_divisions: dict[str, list[str]] = field(default_factory=dict)
    nace_classes: dict[str, list[str]] = field(default_factory=dict)
    prompt_codes: list[str] | None = None  # codes offered to the LLM; None = all of `codes`

    def index_of(self, code: str) -> int | None:
        try:
            return self.codes.index(code)
        except ValueError:
            return None

    def industry_reference_list(self) -> list[tuple[str, str]]:
        """(code, label) pairs the LLM may pick from -- the reference list
        for industry-anchored taxonomy drafting (see
        arp/research/activity_generator.py) and for the core-sector /
        company-industry classification prompts.
        """
        return [(code, self.labels.get(code, "")) for code in (self.prompt_codes or self.codes)]

    def industry_prompt_list(self) -> str:
        """The same reference list rendered as the "code: label" block the
        classification prompts tell the model to pick from. Lives here, with
        codes and labels, because core_sectors.py and company_mapper.py each
        had their own character-identical copy -- two agents classifying
        against the same closed list must see it rendered the same way.
        """
        return "\n".join(f"{code}: {label}" for code, label in self.industry_reference_list())
