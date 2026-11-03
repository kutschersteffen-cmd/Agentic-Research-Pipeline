# Samples

`xbrl_segment_revenue_sample200_2026-11-02.csv`: revenue by segment, product and geography from `arp xbrl fetch --market sec`
(no LLM) for a random sample of 200 NYSE/Nasdaq filers (SEC `company_tickers_exchange.json`, seed 42), latest
annual filing (10-K or 20-F). 126 companies have rows. Values are in full units of each filer's currency (`unit`). `segment` is the company's own label from the filing's label file where `segment_source` is `label`, otherwise derived from the XBRL member name.
Product rows with `level` `standard` and `company` are two views of the same revenue; do not add them together.
