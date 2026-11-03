# Feature Specification: Solleciti mensili delle difformità

**Feature Branch**: `005-solleciti-mensili`

**Created**: 2026-10-29

**Status**: Implementata; verifica manuale pendente

**Input**: User request to add monthly tabs for anomalous published graduations and scrollings, reuse the existing acts table, and prepare a copyable follow-up message with the responsible contacts' email addresses.

## User Scenarios & Testing

### User Story 1 - Consult monthly graduation discrepancies (Priority: P1)

The user opens the acts dashboard and selects the tab for published graduations. The tab shows one monthly table of discrepant graduations, combining differences from Selezioni Online, URP, the secretariat file, and score checks. Each graduation row can expand to show its score and candidate details whenever the SOL verification data is available. The same row provides copy actions for RdP recipients and the complete follow-up message.

**Why this priority**: Published graduations are the first cases the user wants to review and follow up.

**Independent Test**: Select a month containing both consistent and inconsistent graduations. Confirm that the tab contains only inconsistent graduation rows, retains the existing table columns and source states, and shows an informative empty state when there are no discrepancies.

**Acceptance Scenarios**:

1. **Given** the dashboard with the overall acts table, **When** the user selects “Graduatorie del mese” and a month, **Then** the dashboard shows only graduation rows from that month that have one or more discrepancies.
2. **Given** a graduation whose public document is absent from a source, whose protocol is missing, or whose score checks disagree with the available sources, **When** the row is shown, **Then** the existing source cells and discrepancy notes explain what needs checking.
3. **Given** a source's latest collection failed or is in progress, **When** the user reviews a missing-source row, **Then** the page displays the collection state and does not present an unreachable source as confirmed missing.
4. **Given** no graduation discrepancies for the selected month, **When** the user opens the tab, **Then** the page says that there are no discrepancies for that month.

### User Story 2 - Consult monthly scrolling discrepancies (Priority: P1)

The user selects the scrolling tab and sees only anomalous scrolling rows for the selected month, using the same table columns and source indicators as the overall acts table.

**Why this priority**: The user needs to identify missing or inconsistent scrolling records and compare SOL with URP and the secretariat file.

**Independent Test**: Select a month containing consistent and inconsistent scrolling records. Confirm only rows flagged as discrepant are shown and their notes identify the missing or conflicting protocol, date, or SOL candidate status.

**Acceptance Scenarios**:

1. **Given** scrolling acts in the selected month, **When** the user opens “Scorrimenti del mese”, **Then** only rows with a discrepancy are listed.
2. **Given** a scrolling protocol present in some sources but not others, or a SOL score record that does not match the available act data, **When** the user reviews the row, **Then** the source cells and discrepancy notes identify the difference.
3. **Given** a SOL “Provvedimento di assunzione idoneo” attachment with no matching protocol for a candidate with outcome S in the score verification, **When** the user reviews the row, **Then** the discrepancy says the attachment exists and the mismatch is in the score data.
4. **Given** a candidate with outcome S and an assunzione idoneo protocol in the score verification but no corresponding SOL attachment, **When** the user reviews the row, **Then** the discrepancy says the attachment is not present in the available SOL data.
5. **Given** no scrolling discrepancies for the selected month, **When** the user opens the tab, **Then** the page displays an informative empty state.

### User Story 3 - Prepare and copy a follow-up message (Priority: P1)

For a discrepant call, the user prepares one Italian follow-up message that groups every monthly discrepancy across its codes/sedi. The page provides the RdP emails associated with those discrepancies as a separate copy action, plus a complete message with recipients, subject, Selezioni Online link, and body.

**Why this priority**: The dashboard should turn a detected issue into a usable, reviewable solicitation without sending an email on the user's behalf.

**Independent Test**: Open a discrepant bando with more than one code/sede and RdP emails; copy its addresses and complete grouped message. Confirm the message includes every monthly anomaly across its codes/sedi, the bando number and SOL link, contains no candidate names or tax codes, and has not been sent or stored.

**Acceptance Scenarios**:

1. **Given** one or more discrepant rows for a call with RdP contacts, **When** the user copies the email addresses or complete follow-up, **Then** the addresses can be pasted directly into the recipient field and the complete message lists all monthly discrepancies across the call's codes/sedi, its call number, subject, and SOL link.
2. **Given** a call without an RdP email, **When** the user prepares its follow-up, **Then** the page states that no RdP email is available and the message still includes the issue details.
3. **Given** a clipboard permission or browser failure, **When** copy is attempted, **Then** the draft remains visible and selectable for manual copying.
4. **Given** any generated draft, **When** it is copied, **Then** no email is sent, no draft is persisted on the server, and no candidate name, tax code, or score is included.

## Scope Boundaries

- The dashboard adds tabs for the existing overall acts table, monthly graduation discrepancies with score checks in the same table, and monthly scrolling discrepancies. Score summaries and candidate detail are displayed on the graduation rows rather than in a separate monthly table.
- The two monthly discrepancy tabs default to the current month and let the user choose another month.
- Each call with monthly discrepancies has one locally generated follow-up grouping its anomalous rows across codes/sedi; RdP emails and the complete message can be copied separately.
- Sending email from the dashboard, logging into Outlook, and creating Outlook drafts are out of scope for this version. Options will be documented for a later decision.

## Edge Cases

- The selected month has no acts or no discrepant acts.
- RdP contacts are absent, have no email address, or differ across codes/sedi of the same bando.
- One or more source collections are in progress, failed, or stale while discrepancies are displayed.
- The row has several discrepancy notes; all relevant notes should be included once in the draft.
- Clipboard access is unavailable or denied.
- A call has sub-codes; the message must list the affected codes/sedi and use the RdP contacts associated with its discrepant rows.

## Requirements

### Functional Requirements

- **FR-001**: The existing overall acts view MUST remain available as a tab and keep its current filters and columns.
- **FR-002**: The dashboard MUST provide separate tabs for monthly graduations and monthly scrollings, positioned immediately before the existing overall-acts section.
- **FR-003**: The monthly tabs MUST share one month selector, default to the current month, and filter acts by their recorded act date.
- **FR-004**: The graduation tab MUST show one row per discrepant graduation and merge graduation source checks with related score discrepancies by bando, date, and code when available; the scrolling tab MUST show anomalous scrolling rows. A graduation row MUST retain its associated score record even if that score check has no discrepancy, so the candidate detail can be expanded whenever available.
- **FR-005**: The monthly tables MUST reuse the overall acts table's columns, source status cells, links, and notes, including source collection state so that an inaccessible source is not confused with a confirmed absence. Each graduation row MUST show a score summary and an expandable candidate detail control; if score data is unavailable, the expanded row MUST explain how to load it.
- **FR-006**: Each call with monthly discrepancies MUST offer a draft grouping all its monthly discrepancy notes across codes/sedi, act dates, protocols, source status, call number, and link to its Selezioni Online page when available, with a greeting and a request to check and report corrections.
- **FR-007**: The interface MUST offer available RdP email addresses associated with the discrepant rows of the call in a separate copy action; the complete draft MUST also include them, and state explicitly when none are available.
- **FR-008**: The draft MUST be copied only at the user's request and remain available for manual selection if clipboard access fails. The application MUST NOT send or persist it.
- **FR-009**: The draft MUST NOT include candidates' names, tax codes, contact details, or scores; it MAY include RdP email addresses as required by FR-007.
- **FR-010**: The dashboard MUST show a success or failure status after a copy attempt.
- **FR-011**: The new views and their RdP addresses MUST be available only through the existing protected dashboard endpoints in production.
- **FR-012**: Direct email sending and Outlook integration MUST remain disabled in this release.
- **FR-013**: Scrolling discrepancies MUST distinguish SOL attachment presence (“Provvedimento di assunzione idoneo”) from a missing or mismatched protocol in score verification data.

### Key Entities

- **Monthly discrepancy row**: An existing acts row whose act category, month, source states, notes, protocols, and RdP contacts make it eligible for the graduation or scrolling discrepancy view.
- **Follow-up draft**: A transient, user-requested text containing a recipient line, subject, SOL link, and neutral description of all monthly discrepancies for a bando; it is not stored or sent.
- **Collection freshness**: The latest in-progress, successful, or failed collection state for URP and Selezioni Online, used to qualify missing-source observations.

## Success Criteria

### Measurable Outcomes

- **SC-001**: For a selected month, each monthly tab shows all discrepant acts of its category and zero acts without a discrepancy.
- **SC-002**: The three tabs preserve the same act columns and source states as the existing overview.
- **SC-003**: A user can copy RdP addresses or the complete grouped message in one action after opening the row's tab.
- **SC-004**: Every copied message contains all monthly discrepancy notes across the selected call's codes/sedi and no candidate personal data.
- **SC-005**: Copying a draft produces no email send and no server-side draft record.

## Assumptions

- The existing `atti.elenco_atti` rows already provide the required discrepancy notes, source cells, and row-specific RdP email addresses; the feature reuses that comparison rather than introducing a second comparison rule.
- “Tutte le cose che non vanno bene” means rows already marked discrepant by the existing acts and score comparison logic, including missing acts, missing protocols, and detected differences.
- The user wants one follow-up per call number and month, grouping every anomalous graduation and scrolling row across its codes/sedi. The user reviews and sends it manually.
- The dashboard date range uses calendar months in the local Italian timezone.
- Outlook integration will be decided after the copy-and-manual-send workflow has been used.
