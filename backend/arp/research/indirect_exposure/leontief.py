from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class LeontiefModel:
    """The indirect-exposure tier's view of one `arp io build-full` output
    (see factory.load_model): the build's nodes with output (x > 0), and the
    EXIOBASE sector names that label companies and core sectors, each mapped
    to its nodes.
    """

    codes: list[str]  # the EXIOBASE sector names, factory.sectors()
    edition_label: str
    leontief_inverse: np.ndarray  # (n, n) over the nodes below
    output: np.ndarray  # x per node, M EUR
    regions: np.ndarray  # EXIOBASE region per node
    code_nodes: dict[str, np.ndarray]  # sector name -> node indices
    ghg_t_per_meur: np.ndarray  # per node, 0 where the build has none
    final_demand: np.ndarray | None = None  # (n, 4), arp.research.indirect_exposure.io_import.FD_GROUPS
    sectors: np.ndarray | None = None  # EXIOBASE sector name per node (no " (31)" suffix); for the NACE route

    def index_of(self, code: str) -> int | None:
        try:
            return self.codes.index(code)
        except ValueError:
            return None

    def industry_reference_list(self) -> list[str]:
        """The sector names the LLM may pick from -- the reference list for
        industry-anchored taxonomy drafting (see
        arp/research/activity_generator.py) and for the core-sector /
        company-sector classification prompts.
        """
        return list(self.codes)

    def industry_prompt_list(self) -> str:
        """The same reference list rendered one name per line, as the
        classification prompts show it. Lives here because core_sectors.py
        and company_mapper.py classify against the same closed list and must
        see it rendered the same way.
        """
        return "\n".join(self.industry_reference_list())
