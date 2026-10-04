"""Registers the layer 2-5 checks on runner.LAYERS (layer 1 lives in runner.py)."""

from arp.checks import runner
from arp.checks.consistency import check_entity, check_period
from arp.checks.cross_source import check_cross_source
from arp.checks.numeric import check_caption_scale, check_number_in_span, check_row_label
from arp.checks.plausibility import (
    check_less_or_equal,
    check_part_of_whole,
    check_percentage,
    check_range,
    check_sign,
    check_sum_identity,
    check_sum_to_target,
)
from arp.checks.prior_period import check_comparative_jump, check_last_decided, check_last_rejected
from arp.checks.round_trip import check_round_trip

runner.LAYERS[2] = [check_number_in_span, check_caption_scale, check_row_label]
runner.LAYERS[3] = [check_range, check_sign, check_percentage, check_part_of_whole, check_sum_identity, check_less_or_equal, check_sum_to_target, check_round_trip]
runner.LAYERS[4] = [check_comparative_jump, check_last_decided, check_last_rejected, check_entity, check_period]
runner.LAYERS[5] = [check_cross_source]
