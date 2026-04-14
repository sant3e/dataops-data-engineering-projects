# Pipeline Documentation — Style Guide & Conventions

A reusable reference for writing step-by-step AWS/cloud pipeline documentation. Distilled from two completed pipeline documentation projects (CoinGecko ETL, Real-Time AQI).

---

## Document Structure

Every pipeline guide follows this section order:

| # | Section | Purpose |
|---|---|---|
| 1 | **Architecture** | What the pipeline does, data flow, component walkthrough, services table, storage layout |
| 2 | **Step-by-Step Console Guide** | Click-by-click phases for building each resource in the cloud console |
| 3 | **Terraform Configurations** | HCL blocks that reproduce the console steps as infrastructure-as-code |
| 4 | **Troubleshooting** | Common issues grouped by component — symptom → cause → fix |
| 5 | **Comparison / Key Differences** | Only for variant guides — how this pipeline differs from the primary one |

The Troubleshooting section may come before or after Terraform depending on the guide — what matters is that console phases, Terraform, and troubleshooting are each self-contained sections, not mixed together.

---

## Architecture Section

### Title & Intro
- Open with the architecture diagram immediately (SVG reference).
- Follow with 1–2 sentences describing what the pipeline does end-to-end.
- Add a `> **Note**` callout for anything the reader might assume incorrectly (e.g., "this pipeline does not include an API ingestion step" or "source data is pre-downloaded CSVs").

### Data Flow
- **Lead with the actors** (the things that do work), not the triggers.
- Triggers are secondary — show them as sub-bullets under each actor.
- Each step names the function/service, what it does, and where it writes.

```markdown
1. **Lambda** (`extract_fn`) fetches data from the API and saves raw JSON to S3
   - Trigger: EventBridge Scheduler every 5 minutes
2. **Lambda** (`transform_fn`) reads the JSON, transforms it, and writes 3 CSVs to S3
   - Trigger: S3 Event Notification monitoring `s3://bucket/raw_data/to_process/`
3. **Snowpipe** loads each CSV into landing tables in Snowflake (`DB.schema`)
   - Trigger: SQS messages via S3 Event Notification monitoring `s3://bucket/transformed_data/`
```

- When the pipeline splits into parallel workflows, label them explicitly (**Workflow A**, **Workflow B**) with a one-line summary of what each does and why both exist.
- No ASCII flow diagrams when the numbered list already covers the same information.

### Component-by-Component Walkthrough
- Each component gets its own bold-name paragraph: `**Service** (resource_name) — description`.
- Order follows how data touches each component, not alphabetical.
- **Triggers belong with the component they invoke**, not the component that produces the triggering event.
- S3 event notifications specify the full S3 prefix they monitor (`s3://bucket/prefix/`), not just the bucket name.
- When a component has a non-obvious design choice, add a `> **Why X instead of Y?**` callout block explaining the tradeoff (e.g., "Why Flink instead of Lambda for aggregations?", "Why EventBridge was not used for the transform trigger").
- When the guide deviates from a tutorial or reference, explain why: `> **Tutorial vs our approach:** The trainer does X. We do Y because...`

### Services Used Table
- One row per service, ordered following the data flow (Storage → Compute → Scheduling → Event routing → Ingestion → Destination → Monitoring).
- Columns: **Service** (with resource name in parentheses), **Role in Pipeline**.
- For the full-AWS guide, add a **Pricing Model** column.

### S3 Bucket Structure
- Show the folder tree using a code block with `←` annotations explaining what writes to each folder.
- If using a single bucket with prefixes instead of separate buckets, explain why.

---

## Console Guide Section

### General
- Opens with a scope note: what this section covers, what it doesn't, and where to find the rest.
- Each phase builds on the previous one — number them sequentially.
- Cross-reference the Terraform block at the end of each phase: `> Terraform: [Block Name](#anchor)`

### Phase Structure
Each phase follows this pattern:
1. **Phase title** — names the resource being created
2. **What it does** — 2-3 sentences (for compute resources like Lambda)
3. **Numbered steps** — click-by-click console instructions
4. **Runtime / Configuration** — key settings (timeout, memory, runtime)
5. **Terraform cross-reference** — link to the equivalent HCL block

### IAM Policies
- **No IAM policy JSON in console phases.** Describe what to do ("create inline policy with S3 read/write permissions") and cross-reference the Terraform section for the exact JSON.
- The Terraform section is the single source of truth for all IAM policy definitions.

### SQL and Scripts
- **No SQL in console phases when a standalone SQL file exists.** Replace with a single phase that references the file with a summary table of what each step creates.
- Reference Lambda source files by relative path with a link: `see [filename.py](resources/filename.py)`. Don't paste code into the guide.

### Prerequisites for Variant Guides
- State prerequisites as prose, not checkbox lists: "This guide assumes you have already built X, Y, Z from the primary guide."
- Name the shared infrastructure explicitly so the reader knows what's already in place.
- End with what this guide adds: "With that infrastructure ready, this guide adds..."

---

## Terraform Section

### Title & Intro
- Title: **"Terraform Configurations"** (not "Reference" — be descriptive of what it contains).
- Open with a paragraph explaining how to use the section: copy-paste for self-service, or hand to DevOps for review.
- Include the provider preamble once at the top.
- State the ordering: "blocks appear in the same order as the console guide phases."
- Call out what's **not** covered (interactive steps, manual uploads, ad-hoc queries).

### Each Block
- Block heading: `## Terraform: Resource Name`
- Opens with a one-sentence description + which console phase it corresponds to.
- The HCL block is complete and copy-pasteable.
- After the block, add notes about auto-created resources (e.g., "AWS automatically creates a service role when you create the Firehose stream via console — in Terraform, you must declare it explicitly").

### Values & Placeholders
- **No hardcoded AWS account IDs** — use `<ACCOUNT_ID>` placeholders or Terraform variables.
- Values that come from other systems (e.g., Snowflake `DESC PIPE` output) use `var.` references with a comment explaining where the value comes from.
- Include a **Parameterization Note** table at the end listing every hardcoded value, where it appears, and what to replace it with.

### Scope
- Terraform covers only cloud provider infrastructure.
- Database objects provisioned via SQL (Snowflake, RDS, etc.) stay in their own SQL files — Terraform doesn't manage them.

---

## Troubleshooting Section

- **No duplicates.** If a problem and its fix are already documented in a console phase (e.g., a workaround step), don't repeat it in troubleshooting.
- Group by component or symptom category (Flink Issues, Firehose Issues, Lambda Issues, etc.).
- Each item follows: **heading** (symptom as title) → **Symptom** → **Cause** → **Fix** (numbered steps).

---

## Content Principles

| Principle | Rule |
|---|---|
| **Single source of truth** | If content exists in a dedicated file (SQL script, Lambda source), point to it — don't copy it into the guide. |
| **Verify against source code** | Schema documentation must match the code that produces the data. Never trust one doc to validate another. |
| **No fictional columns or fields** | If the code doesn't output a field, the docs don't list it. |
| **Placeholders over hardcoded values** | Account IDs, ARNs, and environment-specific values use `<PLACEHOLDER>` or Terraform variables. |
| **Descriptive names** | File names describe what they depict (`s3_to_snowflake_architecture`, not `pipeline_diagram`). Section titles describe what they contain ("Terraform Configurations", not "Terraform Reference"). |
| **Explain deviations** | When your approach differs from a tutorial or common practice, explain why in a callout. |
| **Callouts for non-obvious choices** | Use `> **Why X?**` blocks for architectural decisions that a reader might question. |

---

## Diagram Conventions

- All diagrams in a top-level `diagrams/` folder.
- Referenced via `![descriptive alt text](diagrams/filename.svg)`.
- No inline SVGs in markdown files.
- Diagram names describe what they depict: `s3_to_snowflake_architecture.svg`, not `diagram1.svg`.
- Architecture diagram appears at the very top of Section 1, before any prose.
- Topology must match the actual architecture — triggers beside targets, data sources at top, branching for parallel paths. Never draw linear waterfalls when the real topology branches.

---

## Formatting Conventions

- Use `&nbsp;` for visual spacing between major sections.
- Use `---` horizontal rules between phases in the console guide.
- Use `> Terraform: [Block Name](#anchor)` at the end of each console phase.
- Use `> **Note:**` for important callouts, `> **Tutorial vs our approach:**` for deviations.
- Tables for configuration fields: `| Field | Value | Why |`
- Code blocks specify the language: ` ```sql `, ` ```hcl `, ` ```bash `, ` ```yaml `
- Inline code for resource names, file paths, bucket names, role names, and CLI commands.

---

## What Not To Do

- Don't nest triggers under the component that produces the event — nest them under what they trigger.
- Don't duplicate SQL from a `.sql` file into the guide.
- Don't duplicate troubleshooting items already covered in setup phases.
- Don't paste IAM policy JSON into console walkthrough phases.
- Don't use line count as a quality metric — content coverage is what matters.
- Don't use generic names when descriptive ones are available.
- Don't use checkbox lists for prerequisites — write prose.
- Don't use ASCII flow diagrams when a numbered list covers the same information.
- Don't assume schema from documentation — verify against the source code that produces the data.
