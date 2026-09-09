---
name: executive-update-oneslider
description: |
  Use when the user asks for an executive update, one-slider, single-slide briefing,
  C-suite status dashboard, or program overview covering: use case burndown rate,
  use case to data product mapping, distinct data products breakdown, BigQuery (BQ)
  compute & storage cost attribution/projections, and ongoing initiatives with executive
  updates. Generates a self-contained, widescreen 16:9 HTML executive update slide.
od:
  mode: oneslide
  output_path_template: "output/exec-updates/{slug}/index.html"
---

# Executive Update One-Slider Skill

You are designing a high-density, C-suite ready **Executive One-Slider Dashboard** (16:9 widescreen presentation slide).

An executive one-slider is not a long report or a multi-slide deck. It is an authoritative single-pane briefing designed for CIOs, CDOs, Enterprise Architects, and Program Steering Committees. Every pixel must carry signal: clear executive KPIs, progress velocity, architecture mappings, FinOps cost projections, and crisp initiative updates.

---

## How this skill is invoked

The user typed something like:
- *"Give me an executive update one-slider on our cloud migration"*
- *"Create a single slide briefing with use case burndown, data product mapping, BQ costs, and initiative status"*
- *"Generate an exec update slide for the steering committee"*

You have the standard wiki-read tools, plus `write_file` scoped to `output/**` and `wiki/explorations/**`.

Pick a kebab-case slug for the artifact (e.g. `gdw-cloud-exec-update`, `q3-migration-briefing`) and write the output to:
`output/exec-updates/<slug>/index.html`

---

## Required Output Contract

1. **Exactly one file**: `output/exec-updates/<slug>/index.html`.
2. **Self-contained**:
   - NO external `<link rel="stylesheet">` (no external CDNs or Google Fonts).
   - NO external `<script src="...">`.
   - NO remote `<img>`.
   - All CSS goes in a single inline `<style>` block in `<head>`.
   - Helper JS for keyboard shortcuts goes in an inline `<script>` at the end of `<body>`.
   - All charts, status badges, progress bars, and icons must be implemented using pure CSS or inline `<svg>`.
3. **Widescreen 16:9 Frame**:
   - The slide must be optimized for full-screen presentation:
     `aspect-ratio: 16 / 9; width: 100vw; max-width: 1920px; height: 100vh; max-height: 1080px; overflow: hidden;`
   - Content must fit on **one single slide without scrolling** at standard 1080p presentation resolution.
   - Include print CSS: `@media print { @page { size: landscape; margin: 0; } body { padding: 0; } }`
4. **Keyboard shortcuts**:
   - Press `F` to toggle full-screen mode.
   - Press `P` to trigger print/export to PDF.

---

## The 5 Mandatory Executive Content Modules

Your synthesized one-slider MUST incorporate the following five functional modules, drawing grounded data from the knowledge base:

```
+-------------------------------------------------------------------------------------------------------------+
| HEADER BAR: Title, Date, Scope, Program Health + 4 Hero KPI Cards                                           |
+------------------------------------+------------------------------------+-----------------------------------+
| MODULE 1: USE CASE BURNDOWN &      | MODULE 3: DISTINCT DATA PRODUCTS   | MODULE 5: ONGOING INITIATIVES     |
| MIGRATION VELOCITY                 | & GOVERNANCE HEALTH                | & EXECUTIVE STATUS UPDATES        |
| - Pipeline Stage Funnel            | - Layer Breakdown (FDP, ODP, CDP)  | - Program Workstream Cards        |
| - Burndown Rate & % Target         | - Subject Domain Distribution      | - RAG Status Badges (G/A/R/Done)  |
| - Active / Decommissioned Delta    | - Collibra Cataloging Status       | - Target Gate & Cutover Date      |
+------------------------------------+------------------------------------+ - Executive Briefing Note        |
| MODULE 2: USE CASE TO DATA PRODUCT | MODULE 4: BIGQUERY FINOPS COST     |   (Key progress, blockers &       |
| CONSUMPTION MAPPING                | ATTRIBUTION & PROJECTIONS          |    mitigation actions)            |
| - DP Consumption per Use Case      | - Compute Model (On-Demand/Slots)  |                                   |
| - Ratio & Distribution Breakdown   | - Storage Tiers (Active/Long-Term) |                                   |
| - Top Consumer Domains & Hotspots  | - Monthly Run-rate & FinOps Levers |                                   |
+------------------------------------+------------------------------------+-----------------------------------+
```

### Module 1: Use Case Burndown Rate & Migration Velocity
- **Grounded Data**: Query use case readiness tracking in the KB (e.g. `summaries/GDWT-Use-Case-Readiness*`, `concepts/enterprise-cloud-migration`, `concepts/legacy-modernization`).
- **Visual Presentation**:
  - A horizontal or vertical multi-stage migration pipeline funnel showing use cases transitioning through gates:
    *(e.g., Identified → Scoped / Migrate → Data Req Understood → FDP Provisioned → In Build → Prod / Dual Run → Decommissioned / Live)*.
  - Burndown Metrics: Total in-scope use cases, number active/retired, current burndown completion rate (`% completed/retired`), and remaining work backlog.
  - Run-rate / velocity indicator (e.g. monthly burndown trajectory towards legacy warehouse exit deadline).

### Module 2: Use Case to Data Product Mapping
- **Grounded Data**: Synthesize relationships between Use Cases and Data Products (Foundational Data Products / Operational Data Products).
- **Visual Presentation**:
  - Consumption Distribution: How many data products each use case relies upon (e.g. average DPs per use case, distribution buckets: 1–2 DPs, 3–5 DPs, >5 DPs).
  - High-dependency Use Cases: Highlight top consuming use cases or business units (e.g. Consumer Relationships, Risk, Finance) that drive data product consumption.
  - Dependency Concentration: Key metrics indicating reuse efficiency (e.g., reuse multiplier: total use-case consumption links vs unique data products).

### Module 3: Distinct Data Products Inventory & Governance Health
- **Grounded Data**: Query data mesh taxonomy and catalog assets (e.g. `concepts/data-mesh-products`, `summaries/GDW-Transformation*`, Collibra entities).
- **Visual Presentation**:
  - Distinct count of unique Data Products segmented by architectural layer:
    - **Foundation Data Products (FDPs)** (cleansed, conformed enterprise models).
    - **Origin/Operational Data Products (ODPs)** (source landing mirrors).
    - **Consumption Data Products (CDPs)** (curated views / analytical models).
  - Domain breakdown: Counts across Party, Portfolio/Account, Event/Transactions, and Reference domains.
  - Cataloging & Governance Health: Breakdown of published data products, products in design/build stage gates, and legacy uncataloged datasets ("Not on Collibra") presenting cutover risk.

### Module 4: BigQuery Compute & Storage Cost Attribution
- **Grounded Data**: Query BigQuery pricing and serverless compute models (e.g. `concepts/serverless-compute-pricing`, `summaries/BigQuery*`).
- **Visual Presentation**:
  - **Compute Cost Model**:
    - On-Demand ($/TiB scanned) vs Capacity Editions (Standard/Enterprise slot-hours, reservations, and CUD commitments).
    - Estimated monthly compute expenditure attributed to migrated use cases and query workloads.
  - **Storage Cost Model**:
    - Active Storage ($0.020/GiB standard) vs Long-Term Cold Storage ($0.010/GiB for tables unedited for 90 days).
    - Logical vs Physical compressed billing attribution.
  - **FinOps Optimization Levers**:
    - Concrete efficiency gains: BI Engine in-memory acceleration, partition/cluster optimization, and auto-archival policies.

### Module 5: Ongoing Initiatives & Executive Updates
- **Grounded Data**: Identify major ongoing migration workstreams and platforms (e.g. Stratos Platform Landing Zone, Core Banking Platform migration, Collibra Cataloging & Governance, Automated Data Validation & Reconciliation / DVT, Legacy Teradata Decommissioning).
- **Visual Presentation**:
  - Structured card or table layout featuring 4–5 core strategic initiatives.
  - For each initiative, display:
    1. **Initiative Title & Domain / Lead Platform**
    2. **RAG Status Badge**: `ON TRACK` (emerald), `AT RISK` (amber), `DELAYED` (rose), or `COMPLETE` (sky blue).
    3. **Target Milestone / Delivery Gate**: E.g., Stage Gate 2, Dual-Run Cutover, Q4 2026 exit.
    4. **Executive Briefing Narrative**: Exactly 1–2 crisp, impactful sentences highlighting latest delivery progress, critical-path dependency/blocker, and mitigation action.

---

## Design System: Executive Obsidian & Slate

Use this polished, modern C-suite design system. It balances dark slate readability with vibrant, accessible status accents.

### Color Palette

```css
:root {
  --canvas:        #0a0f1d; /* Deep executive navy/slate canvas */
  --panel-bg:      #111827; /* Primary card background */
  --panel-card:    #1e293b; /* Elevated container card */
  --panel-border:  #334155; /* Subtle card border */
  --panel-hover:   #273549; /* Interactive element border */
  
  --ink-primary:   #f8fafc; /* Crisp white for primary headings & numbers */
  --ink-secondary: #cbd5e1; /* Soft slate for body text */
  --ink-muted:     #94a3b8; /* Muted slate for metadata and labels */
  --ink-faint:     #64748b; /* Low-priority microcopy */

  --accent-cyan:   #38bdf8; /* Brand highlight / BigQuery primary */
  --accent-indigo: #818cf8; /* Architecture & Data Mesh highlight */
  --accent-emerald:#34d399; /* Green / On Track */
  --accent-amber:  #fbbf24; /* Yellow / At Risk */
  --accent-rose:   #f87171; /* Red / Delayed / Blocker */
  --accent-purple: #c084fc; /* Data Product / Consumption layer */
}
```

### Typography

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
```
- Titles & KPIs: Bold, clean, tabular numbers (`font-variant-numeric: tabular-nums`).
- Section Labels: Uppercase, tracking `0.08em`, small font size (`11px - 12px`), bold.
- Executive Update Body: `12px - 13px`, line-height `1.45`, high-contrast legible slate.

### Layout Geometry (16:9 Presentation Frame)

```css
body {
  margin: 0;
  padding: 0;
  background-color: var(--canvas);
  color: var(--ink-primary);
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  overflow: hidden;
}

.slide {
  width: 100vw;
  max-width: 1920px;
  height: 100vh;
  max-height: 1080px;
  aspect-ratio: 16 / 9;
  box-sizing: border-box;
  padding: 24px 32px 18px 32px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
```

---

## Step-by-Step Generation Workflow

1. **Scan Knowledge Base First**:
   - Read `wiki/index.md` and list relevant documents and concepts.
   - Read specific status and readiness summaries (e.g. `summaries/GDWT-Use-Case-Readiness*`).
   - Read taxonomy blueprints (e.g. `summaries/GDW-Transformation*`, `concepts/data-mesh-products*`).
   - Read pricing and compute architecture (e.g. `concepts/serverless-compute-pricing`, `summaries/BigQuery*`).
2. **Synthesize Quantitative Metrics**:
   - Collect exact counts: total use cases, in-scope count, provisioned count, production count, total FDPs, ODPs, CDPs, uncataloged datasets, and pricing tiers.
   - Avoid fabricating numbers when the KB contains explicit data; cite or ground figures directly in KB assets.
3. **Formulate Executive Briefings for Initiatives**:
   - Summarize real workstreams (e.g., Stratos Landing Zone, Collibra Stage Gates, Core Banking FDPs, DVT Automated Reconciliation, Teradata Decommissioning).
   - Craft executive-grade sentences that state what is progressing, what is blocked, and what the milestone target is.
4. **Build the Self-Contained HTML**:
   - Construct the single-page HTML file with all CSS inline.
   - Use CSS Grid (`grid-template-columns: 1.15fr 1.1fr 1.35fr`) for the 3 columns underneath the top header.
   - Implement data visualizations with SVG bars, progress funnels, and KPI pills.
   - Add the keyboard navigation script (`F` for fullscreen, `P` for print).
5. **Write File**:
   - Write to `output/exec-updates/<slug>/index.html` using the `write_file` tool.
6. **Verify and Report**:
   - Ensure the file is completely self-contained and free of external script/link tags.
   - Report the output path and a 3-bullet executive summary to the user.

---

## Negative Checklist (Failure Modes to Avoid)

1. **Scrolling or Overflowing Slide**: The slide MUST fit entirely within a 16:9 viewport without requiring vertical or horizontal scrollbars. Keep margins and text compact.
2. **Generic Placeholder Text**: Never output `[Insert Use Case Here]` or `Lorem Ipsum`. Always ground entities and data in the KB.
3. **Missing Cost Breakdown**: Compute and Storage costs must have explicit estimations, models, or unit economics, not just a vague sentence.
4. **Cluttered Wall of Text**: Keep initiative updates concise (1–2 sentences each). Use visual tags, badges, and meters instead of paragraphs.
5. **External Dependencies**: Never include `<link href="https://fonts.googleapis.com/...">` or CDN scripts. Self-containment is strictly required.
