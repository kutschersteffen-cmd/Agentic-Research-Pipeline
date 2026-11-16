"""`next_steps` (mockup 7): numbered rows with owner and a `when` pill; the emphasised action is set at weight 600."""

from arp.reporting.render_model import VISUALS
from arp.reporting.visuals._common import numbered_rows


def render(visual, box, ctx):
    a = visual.actions
    return numbered_rows([x.text for x in a], box, ctx, visual.emphasis, [(x.owner, x.when) for x in a])


VISUALS["next_steps"] = render
