"""`points`: numbered ground rows, like next_steps without owner or time."""

from arp.reporting.render_model import VISUALS
from arp.reporting.visuals._common import numbered_rows


def render(visual, box, ctx):
    return numbered_rows(visual.points, box, ctx, visual.emphasis)


VISUALS["points"] = render
