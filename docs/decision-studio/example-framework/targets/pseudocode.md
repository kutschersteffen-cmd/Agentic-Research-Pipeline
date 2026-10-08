# Logic of targets (Q2.1): pseudo code

Generated from `framework.json`; same logic Decision Studio runs. Hit policy `first`: the first matching row wins; an empty input matches anything.

## Rules > normalise (expressions)
```
sbti_answer = (lower(string(sbti_near_term_status ?? '')) == 'targets set' and number(sbti_near_term_target_year ?? 0) >= 2029 and number(sbti_near_term_target_year ?? 0) <= 2035 ? 'Yes' : 'No info')
ca100_3_1_answer = ((ca100_3_1 == true or lower(string(ca100_3_1 ?? '')) == 'yes') ? 'Yes' : ((ca100_3_1 == false or lower(string(ca100_3_1 ?? '')) == 'no') ? 'No' : 'No info'))
ca100_3_2a_answer = ((ca100_3_2a == true or lower(string(ca100_3_2a ?? '')) == 'yes') ? 'Yes' : ((ca100_3_2a == false or lower(string(ca100_3_2a ?? '')) == 'no') ? 'No' : 'No info'))
cdp_q2_1_1_answer = ((cdp_q2_1_1 == true or lower(string(cdp_q2_1_1 ?? '')) == 'yes') ? 'Yes' : ((cdp_q2_1_1 == false or lower(string(cdp_q2_1_1 ?? '')) == 'no') ? 'No' : 'No info'))
cdp_q2_1_2_answer = ((cdp_q2_1_2 == true or lower(string(cdp_q2_1_2 ?? '')) == 'yes') ? 'Yes' : ((cdp_q2_1_2 == false or lower(string(cdp_q2_1_2 ?? '')) == 'no') ? 'No' : 'No info'))
cdp_q2_1_3_answer = ((cdp_q2_1_3 == true or lower(string(cdp_q2_1_3 ?? '')) == 'yes') ? 'Yes' : ((cdp_q2_1_3 == false or lower(string(cdp_q2_1_3 ?? '')) == 'no') ? 'No' : 'No info'))
cdp_q2_1_4_answer = ((cdp_q2_1_4 == true or lower(string(cdp_q2_1_4 ?? '')) == 'yes') ? 'Yes' : ((cdp_q2_1_4 == false or lower(string(cdp_q2_1_4 ?? '')) == 'no') ? 'No' : 'No info'))
msci_q2_1_1_answer = ((msci_q2_1_1 == true or lower(string(msci_q2_1_1 ?? '')) == 'yes') ? 'Yes' : ((msci_q2_1_1 == false or lower(string(msci_q2_1_1 ?? '')) == 'no') ? 'No' : 'No info'))
msci_q2_1_2_answer = ((msci_q2_1_2 == true or lower(string(msci_q2_1_2 ?? '')) == 'yes') ? 'Yes' : ((msci_q2_1_2 == false or lower(string(msci_q2_1_2 ?? '')) == 'no') ? 'No' : 'No info'))
msci_q2_1_3_answer = ((msci_q2_1_3 == true or lower(string(msci_q2_1_3 ?? '')) == 'yes') ? 'Yes' : ((msci_q2_1_3 == false or lower(string(msci_q2_1_3 ?? '')) == 'no') ? 'No' : 'No info'))
msci_q2_1_4_answer = ((msci_q2_1_4 == true or lower(string(msci_q2_1_4 ?? '')) == 'yes') ? 'Yes' : ((msci_q2_1_4 == false or lower(string(msci_q2_1_4 ?? '')) == 'no') ? 'No' : 'No info'))
tpi_q4l2_answer = ((tpi_q4l2 == true or lower(string(tpi_q4l2 ?? '')) == 'yes') ? 'Yes' : ((tpi_q4l2 == false or lower(string(tpi_q4l2 ?? '')) == 'no') ? 'No' : 'No info'))
wba_s12_covers_95_answer = ((wba_s12_covers_95 == true or lower(string(wba_s12_covers_95 ?? '')) == 'yes') ? 'Yes' : ((wba_s12_covers_95 == false or lower(string(wba_s12_covers_95 ?? '')) == 'no') ? 'No' : 'No info'))
wba_s12_near_term_aim_answer = ((wba_s12_near_term_aim == true or lower(string(wba_s12_near_term_aim ?? '')) == 'yes') ? 'Yes' : ((wba_s12_near_term_aim == false or lower(string(wba_s12_near_term_aim ?? '')) == 'no') ? 'No' : 'No info'))
wba_s3_material_categories_answer = ((wba_s3_material_categories == true or lower(string(wba_s3_material_categories ?? '')) == 'yes') ? 'Yes' : ((wba_s3_material_categories == false or lower(string(wba_s3_material_categories ?? '')) == 'no') ? 'No' : 'No info'))
wba_targets_answer = ((wba_targets == true or lower(string(wba_targets ?? '')) == 'yes') ? 'Yes' : ((wba_targets == false or lower(string(wba_targets ?? '')) == 'no') ? 'No' : 'No info'))
ca100_3_1_or_wba_s12_near_term_aim_answer = (((ca100_3_1 == true or lower(string(ca100_3_1 ?? '')) == 'yes') or (wba_s12_near_term_aim == true or lower(string(wba_s12_near_term_aim ?? '')) == 'yes')) ? 'Yes' : (((ca100_3_1 == false or lower(string(ca100_3_1 ?? '')) == 'no') or (wba_s12_near_term_aim == false or lower(string(wba_s12_near_term_aim ?? '')) == 'no')) ? 'No' : 'No info'))
tpi_alignment_answer = lower(string(tpi_cp_alignment_2030 ?? '')) == '1.5 degrees' or lower(string(tpi_cp_alignment_2030 ?? '')) == 'below 2 degrees' or lower(string(tpi_cp_alignment_2035 ?? '')) == '1.5 degrees' or lower(string(tpi_cp_alignment_2035 ?? '')) == 'below 2 degrees' ? 'Yes' : (string(tpi_cp_alignment_2030 ?? '') == '' and string(tpi_cp_alignment_2035 ?? '') == '' ? 'No info' : 'No')
```

## Rules > Q2.1.1 (decision table, hit policy first)
```
IF SBTi = 'Yes' THEN q2_1_1 = 'Yes', q2_1_1_source = 'SBTi'
ELSE IF MSCI has info THEN q2_1_1 = msci_q2_1_1_answer, q2_1_1_source = 'MSCI'
ELSE IF TPI has info THEN q2_1_1 = tpi_q4l2_answer, q2_1_1_source = 'TPI'
ELSE IF WBA has info THEN q2_1_1 = wba_targets_answer, q2_1_1_source = 'WBA'
ELSE IF CDP has info THEN q2_1_1 = cdp_q2_1_1_answer, q2_1_1_source = 'CDP'
ELSE q2_1_1 = 'No info', q2_1_1_source = 'none'
```

## Rules > Q2.1.2 (decision table, hit policy first)
```
IF SBTi = 'Yes' THEN q2_1_2 = 'Yes', q2_1_2_source = 'SBTi'
ELSE IF MSCI has info THEN q2_1_2 = msci_q2_1_2_answer, q2_1_2_source = 'MSCI'
ELSE IF CA100+ has info THEN q2_1_2 = ca100_3_1_answer, q2_1_2_source = 'CA100+'
ELSE IF WBA has info THEN q2_1_2 = wba_s12_near_term_aim_answer, q2_1_2_source = 'WBA'
ELSE IF CDP has info THEN q2_1_2 = cdp_q2_1_2_answer, q2_1_2_source = 'CDP'
ELSE q2_1_2 = 'No info', q2_1_2_source = 'none'
```

## Rules > Q2.1.3 (decision table, hit policy first)
```
IF SBTi = 'Yes' THEN q2_1_3 = 'Yes', q2_1_3_source = 'SBTi'
ELSE IF MSCI has info THEN q2_1_3 = msci_q2_1_3_answer, q2_1_3_source = 'MSCI'
ELSE IF CA100+ has info THEN q2_1_3 = ca100_3_2a_answer, q2_1_3_source = 'CA100+'
ELSE IF WBA has info THEN q2_1_3 = wba_s12_covers_95_answer, q2_1_3_source = 'WBA'
ELSE IF CDP has info THEN q2_1_3 = cdp_q2_1_3_answer, q2_1_3_source = 'CDP'
ELSE q2_1_3 = 'No info', q2_1_3_source = 'none'
```

## Rules > Q2.1.4 (decision table, hit policy first)
```
IF SBTi = 'Yes' THEN q2_1_4 = 'Yes', q2_1_4_source = 'SBTi'
ELSE IF MSCI has info THEN q2_1_4 = msci_q2_1_4_answer, q2_1_4_source = 'MSCI'
ELSE IF CA100+/WBA has info THEN q2_1_4 = ca100_3_1_or_wba_s12_near_term_aim_answer, q2_1_4_source = 'CA100+/WBA'
ELSE IF WBA has info THEN q2_1_4 = wba_s3_material_categories_answer, q2_1_4_source = 'WBA'
ELSE IF CDP has info THEN q2_1_4 = cdp_q2_1_4_answer, q2_1_4_source = 'CDP'
ELSE q2_1_4 = 'No info', q2_1_4_source = 'none'
```

## Rules > Q2.1.5 (decision table, hit policy first)
```
IF SBTi = 'Yes' THEN q2_1_5 = 'Yes', q2_1_5_source = 'SBTi'
ELSE IF Q2.1.1 = 'No' THEN q2_1_5 = 'No', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.2 = 'No' THEN q2_1_5 = 'No', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.3 = 'No' THEN q2_1_5 = 'No', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.4 = 'No' THEN q2_1_5 = 'No', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.1 = 'No info' THEN q2_1_5 = 'No info', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.2 = 'No info' THEN q2_1_5 = 'No info', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.3 = 'No info' THEN q2_1_5 = 'No info', q2_1_5_source = 'Q2.1.1-4'
ELSE IF Q2.1.4 = 'No info' THEN q2_1_5 = 'No info', q2_1_5_source = 'Q2.1.1-4'
ELSE IF TPI alignment has info THEN q2_1_5 = tpi_alignment_answer, q2_1_5_source = 'TPI'
ELSE q2_1_5 = 'No info', q2_1_5_source = 'none'
```

## Rules > counts (expressions)
```
yes_count = len(filter([q2_1_1, q2_1_2, q2_1_3, q2_1_4, q2_1_5], # == 'Yes'))
no_info_count = len(filter([q2_1_1, q2_1_2, q2_1_3, q2_1_4, q2_1_5], # == 'No info'))
note = string($.yes_count) + '/5 Yes' + ' · Q2.1.1 ' + q2_1_1 + ' (' + q2_1_1_source + ')' + ' · Q2.1.2 ' + q2_1_2 + ' (' + q2_1_2_source + ')' + ' · Q2.1.3 ' + q2_1_3 + ' (' + q2_1_3_source + ')' + ' · Q2.1.4 ' + q2_1_4 + ' (' + q2_1_4_source + ')' + ' · Q2.1.5 ' + q2_1_5 + ' (' + q2_1_5_source + ')'
```

## Rules > Outcome (decision table, hit policy first)
```
IF Yes answers = 5 THEN outcome = 'aligned'
ELSE IF Q2.1.1 = 'Yes' and Q2.1.2 = 'Yes' and Q2.1.3 = 'Yes' and Q2.1.4 = 'Yes' THEN outcome = 'not_aligned'
ELSE IF Yes answers > 0 THEN outcome = 'partial'
ELSE IF No info answers = 5 THEN outcome = 'no_info'
ELSE outcome = 'none'
```

## Decision tree > Tier (decision table, hit policy first)
```
IF Outcome = 'aligned' THEN tier = 1, note = note
ELSE IF Outcome = 'not_aligned' THEN tier = 2, note = note
ELSE IF Outcome = 'partial' THEN tier = 3, note = note
ELSE IF Outcome = 'none' THEN tier = 4, note = note
ELSE IF Outcome = 'no_info' THEN tier = 5, note = note
```

