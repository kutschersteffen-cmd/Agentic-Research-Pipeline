# Agentic Research Pipeline

Research runs extract values about companies from documents and data sources; people review them, and the accepted values become the facts that get published.

## Language

### From run to fact

**Observation**:
One value a run or source reports for a company, field, period and basis, with its citations.
_Avoid_: datapoint, extracted value

**Review item**:
A question queued for a person about one observation, or about a whole record.
_Avoid_: queue entry, task

**Whole-record item**:
A review item about a company's entire result in a run rather than one value; its decision covers every observation of that result routed to review.

**Decision**:
A reviewer's answer to a review item: approve, edit, correct, reject, escalate or hold.
_Avoid_: verdict, ruling

**Item state**:
Where a review item stands: pending, first done, second done, disagreed or final. Only a final item changes facts.

**Fact**:
The current accepted value for a company, field, period and basis, kept as a history of versions.
_Avoid_: current value, golden record

**Fact ledger**:
The rules that turn a run's observations, review items, decisions and cosigns into item states and fact versions.
_Avoid_: fact engine, review applier
