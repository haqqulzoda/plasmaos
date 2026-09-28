# P0 UI trust states

P0 changes only the trust-critical parts of the existing pursuit workspace.

The analysis summary gives extraction quality visual priority over technical completion. A completed anomalous run is shown as needing attention, with Review analysis and Rerun analysis actions. The pipeline identifier is confined to technical details.

The requirements view never shows “No unresolved current-stage gaps” unless quality is `READY_FOR_REVIEW` and meaningful extraction exists. Empty or suspicious coverage instead explains that the gap assessment is not reliable.

The Next Action card derives from loaded workflow state:

- active processing: analysis is in progress;
- no analysis: choose documents to analyze;
- anomalous extraction: review or rerun analysis;
- ready extraction with unresolved candidate gaps: review partner and expert options;
- viable approved scenario: prepare the proposal evidence pack;
- otherwise: review extracted requirements and gaps.

Context conflicts show the user-confirmed value alongside the source-detected value and a review affordance. Historical source deadlines are marked as passed. Mandatory, preferred, and desired role criteria remain visibly distinct.

The changes do not add a tab/navigation redesign, alter W5-W8 authorities, or broaden the pursuit workspace redesign scope reserved for P1.
