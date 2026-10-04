"""Registers the layer 2-4 checks on runner.LAYERS (layer 1 lives in runner.py)."""

from arp.checks import runner
from arp.checks.consistency import check_entity, check_period
from arp.checks.numeric import check_caption_scale, check_number_in_span, check_row_label
from arp.checks.plausibility import (
    check_part_of_whole,
    check_percentage,
    check_range,
    check_sign,
    check_sum_identity,
)
from arp.checks.prior_period import check_comparative_jump, check_last_decided

runner.LAYERS[2] = [check_number_in_span, check_caption_scale, check_row_label]
runner.LAYERS[3] = [check_range, check_sign, check_percentage, check_part_of_whole, check_sum_identity]
runner.LAYERS[4] = [check_comparative_jump, check_last_decided, check_entity, check_period]
