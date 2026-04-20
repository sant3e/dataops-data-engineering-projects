# Gap Analysis — `taxi_riders_full_aws_pipeline_setup.md`

**Purpose:** This document is the primary reference for S03, S04, S05, and S06 executors. It maps every H2 section of the source guide to its target style guide section and enumerates every conformance gap that each downstream slice must close. Executors should work from this document without needing to re-read the 2533-line source guide.

**Source file:** `real_time_aws_dbt_architecture/taxi_riders_full_aws_pipeline_setup.md` (2533 lines, 22 H2 sections)  
**Style guide target:** 4-section structure (Architecture, Console Guide, Terraform, Resources Reference [superseded])  
**Produced by:** S01/T02  
**Consumed by:** S03 (Architecture), S04 (Console Guide), S05 (Terraform), S06 (final assembly)

---

## H2 Section Map

All 22 H2 sections of the source guide and their migration targets.

| Original H2 | Line Range | Target Section | Migration Notes |
|---|---|---|---|
| Data Flow — How the Pipeline Works in Production | 6–78 | Architecture (S03) | Contains data flow diagram (text), S3 bucket layout, and AWS services table — all Architecture content. Keep as-is but add Component-by-Component Walkthrough subsection label. |
| Apache Kafka — Concepts | 79–102 | Architecture (S03) inline | Standalone H2 must be dissolved and merged into the MSK component walkthrough sub-section. Cannot remain a separate top-level H2 per style guide. |
| Step 1: Create the MSK Cluster | 103–150 | Console Guide Phase 1 (S04) | Rename to Phase heading. Add `> Terraform: [1. VPC + Networking](#1-vpc--networking)` cross-reference at end. |
| Step 2: Create EC2 Instance (Kafka Client) | 151–211 | Console Guide Phase 2 (S04) | Rename to Phase heading. Add Terraform cross-reference. |
| Step 3: Install Kafka Libraries on EC2 | 212–260 | Console Guide Phase 3 (S04) | Rename to Phase heading. Add Terraform cross-reference. CLI-only step — no Terraform equivalent. |
| Step 4: IAM Policy and Role for EC2 → MSK Access | 261–333 | Console Guide Phase 4 (S04) | Rename to Phase heading. IAM JSON correctly in console phase per D001. Add Terraform cross-reference. |
| Step 5: Create Kafka Topic and Test | 334–396 | Console Guide Phase 5 (S04) | Rename to Phase heading. Inline Troubleshooting table (lines 387–396) must be extracted. Add Terraform cross-reference. |
| Step 6: Run the Kafka Producer Script | 397–474 | Console Guide Phase 6 (S04) | Rename to Phase heading. Update `resources/kafka_producer.py` path reference to `docs/resources/kafka_producer.py`. Add Terraform cross-reference. |
| Step 7: Create S3 Bucket and Firehose Stream (MSK → S3) | 475–573 | Console Guide Phase 7 (S04) | Rename to Phase heading. Add Terraform cross-reference. |
| Step 8: AWS Glue — Transform Raw Data to Refined | 574–708 | Console Guide Phase 8 (S04) | Rename to Phase heading. Add Terraform cross-reference. |
| Step 9: EMR Serverless — Dimensional Modelling (Star Schema) | 709–805 | Console Guide Phase 9 (S04) | Rename to Phase heading. Update `resources/emr_spark_job.py` path to `docs/resources/emr_spark_job.py`. Add Terraform cross-reference. |
| Step 10: Glue Crawler and Athena — Catalog and Query | 806–884 | Console Guide Phase 10 (S04) | Rename to Phase heading. Add Terraform cross-reference. |
| Step 11: Step Functions — Automate the EMR Spark Job | 885–1036 | Console Guide Phase 11 (S04) | Rename to Phase heading. Inline Troubleshooting table (lines 1027–1036) must be extracted. Add Terraform cross-reference. |
| Step 12: EventBridge — Automate the Full Pipeline | 1037–1182 | Console Guide Phase 12 (S04) | Rename to Phase heading. Hardcoded account ID at line 1078 → replace with `<ACCOUNT_ID>`. Add `> Why EventBridge?` callout. Add Terraform cross-reference. |
| Step 13: EC2 Instance for dbt | 1183–1355 | Console Guide Phase 13 (S04) | Rename to Phase heading. "Tutorial vs our approach" callout opportunity (context exists at ~line 1183). Add Terraform cross-reference. |
| Step 14: Install and Configure dbt on EC2 | 1356–1488 | Console Guide Phase 14 (S04) | Rename to Phase heading. No Terraform equivalent — dbt install is CLI-only (correct, log as note). |
| Step 15: dbt Project Setup — Sources and Models | 1489–1698 | Console Guide Phase 15 (S04) | Rename to Phase heading. Update `resources/dbt/` path refs to `docs/dbt/`. No Terraform equivalent. |
| Step 16: dbt Tests | 1699–1789 | Console Guide Phase 16 (S04) | Rename to Phase heading. Update `resources/dbt/` path refs to `docs/dbt/`. No Terraform equivalent. |
| Step 17: dbt Documentation | 1790–1874 | Console Guide Phase 17 (S04) | Rename to Phase heading. No Terraform equivalent. |
| Resources Reference | 1875–1909 | Remove from guide (S06) | Superseded by `docs/` layout. Replace entire H2 with a one-line note: "All resource files are in `docs/resources/` and `docs/dbt/` — see the docs/ folder." |
| Cleanup Note | 1910–1923 | TOC callout / keep inline (S06) | Not a style guide section. Convert from H2 to a `> **Note:**` callout block. Keep content. |
| Terraform — All Resources | 1924–2533 | Terraform Section (S05) | Already structured. Needs: provider parameterization, `variable "region"` declaration, `> Console:` back-links on each block, Parameterization Note table, provider preamble paragraph. |

---

## Architecture Section Gaps (for S03)

These gaps exist between the source's `Data Flow` and `Apache Kafka — Concepts` content and what the style guide requires for the Architecture section.

- **Missing architecture diagram reference:** The Architecture section must open with a diagram reference. The draw.io diagram is being produced in S02 and does not exist yet — S03 must insert a placeholder callout: `> **Diagram:** See [docs/diagrams/architecture.drawio](../diagrams/architecture.drawio) — generated by S02.`
- **Apache Kafka — Concepts H2 must be dissolved:** The standalone `## Apache Kafka — Concepts` H2 (lines 79–102) is not a top-level section in the style guide. Its content (4 core components + Bootstrap Server) must be merged inline into the MSK component walkthrough under a `### What is MSK / Kafka?` subsection — it cannot remain a separate H2.
- **No Component-by-Component Walkthrough subsection label:** The services table in Data Flow (lines ~56–76) and the detailed content exist but are not grouped under a `### Component-by-Component Walkthrough` heading as the style guide requires. S03 must add this subsection label.
- **Missing "Last verified" date:** The style guide requires a `> **Last verified:** YYYY-MM-DD` front-matter line at the top of the Architecture section. This is absent from the source guide entirely.
- **Missing Table of Contents:** The source guide has no TOC. The style guide requires a TOC at the top of each major section. S03 must generate the Architecture section TOC.
- **"Tutorial vs our approach" callout absent:** Step 13 (line ~1183) explains that the trainer chose a dedicated EC2 instance for dbt rather than a local install — this is a deliberate tutorial choice, not the only valid approach. S03 (or S04) must add a `> **Tutorial vs our approach:**` callout documenting this decision so readers understand why EC2 was chosen.
- **No "Why EventBridge?" callout:** Step 12 (line 1037) chooses EventBridge over a direct S3 trigger lambda. The style guide requires a `> **Why X?**` callout justifying non-obvious service choices. S03 must add: `> **Why EventBridge over a direct Lambda trigger?** EventBridge decouples the trigger from the target, allowing multiple downstream targets and event filtering without modifying the S3 bucket configuration.`

---

## Console Guide Gaps (for S04)

These gaps exist between the 17 console Step H2 sections (lines 103–1874) and the style guide's Console Guide section requirements.

- **All 17 step titles must become Phase headings:** Every `## Step N: …` must be renamed to `## Phase N: …` per the style guide's Console Guide structure. This affects lines 103, 151, 212, 261, 334, 397, 475, 574, 709, 806, 885, 1037, 1183, 1356, 1489, 1699, and 1790.
- **Missing `> Terraform: [Block Name](#anchor)` cross-reference at end of every phase:** Each console Phase must end with a blockquote cross-reference pointing to the corresponding Terraform block in the Terraform section. Currently no phase has this link. S04 must add these cross-references for Phases 1–13 (Phases 14–17 have no Terraform equivalent and must include a note: `> **Terraform:** No Terraform equivalent — dbt is installed via CLI.`).
- **Inline Troubleshooting table in Phase 5 (lines 387–396) must be extracted:** The `### Troubleshooting` sub-section at the end of Step 5 (lines 387–396) is an inline table. Per the style guide, troubleshooting content belongs in a standalone Troubleshooting section. S04 must extract this table and leave a `> See [Troubleshooting → Phase 5](#phase-5-kafka-topic)` link in its place. S06 assembles the final Troubleshooting section.
- **Inline Troubleshooting table in Phase 11 (lines 1027–1036) must be extracted:** Same issue as Phase 5. S04 must extract lines 1027–1036, leave a cross-reference link, and pass the extracted content to S06.
- **`What is X?` blocks are correctly placed (no gap):** Several phases already include `### What is …?` sub-sections inline at the top of their phase (e.g. "What is dbt?" in Step 13, "What is a Glue Job?" in Step 8). These are correctly structured per the style guide — no change needed.
- **IAM JSON is correctly retained in console phases (no gap):** IAM policy JSON blocks are kept inline within their console phases per D001. This is correct — do not extract them.
- **Opening scope note for Console Guide section absent:** The style guide requires the Console Guide section to open with a scope note explaining what the section covers and its relationship to the Terraform section. This paragraph does not exist in the source. S04 must write it: approximately 2–3 sentences explaining that the Console Guide covers all 17 steps and that each phase ends with a Terraform cross-reference.
- **Hardcoded account ID at line 1078:** The ARN example in Step 12 reads `arn:aws:states:eu-north-1:946509368226:stateMachine:EMR_Automation`. The account ID `946509368226` must be replaced with `<ACCOUNT_ID>` to avoid leaking a real AWS account number. The region `eu-north-1` in this example is acceptable as an illustration but should ideally also become `<YOUR_REGION>` for consistency.
- **`resources/` path references throughout Steps 6, 9, 15, 16 must become `docs/resources/` and `docs/dbt/`:** After T01 moved all files, any inline path reference to `resources/kafka_producer.py`, `resources/emr_spark_job.py`, `resources/dbt/…` is broken. S04 must update all such references in the console phases it rewrites.

---

## Terraform Section Gaps (for S05)

These gaps exist between the source's `## Terraform — All Resources` section (lines 1924–2533) and the style guide's Terraform section requirements.

- **Provider block `region` is hardcoded — must use `var.region`:** Line 1945 reads `region = "eu-north-1"  # Change to your region`. This must be parameterized to `region = var.region`. The comment can be removed once the variable is declared.
- **`variable "region" {}` block is never declared:** The Terraform section uses `${var.region}` in at least two places (subnet `availability_zone` strings at lines 1962 and 1969, and the EMR trust policy ARN at line 2394) but the `variable "region" {}` block does not appear anywhere in the section. S05 must add it to the provider preamble block:
  ```hcl
  variable "region" {
    description = "AWS region to deploy into"
    type        = string
    default     = "eu-north-1"
  }
  ```
- **No `> Console: [Phase Name](#anchor)` back-link on any Terraform block:** Every numbered Terraform block (1 through 13) must end with a blockquote back-link to its corresponding console Phase. Currently no Terraform block has this. S05 must add them.
- **No Parameterization Note table:** The style guide requires a Parameterization Note table near the top of the Terraform section listing every variable used and its purpose (variable name, type, default, description). This table is absent. S05 must create it covering at minimum: `region`, `unique_suffix` (if extracted from the bucket name), and any other variables added during parameterization.
- **No provider preamble intro paragraph:** The style guide requires a short prose paragraph before the first `terraform {}` block explaining what the Terraform section provides, who it is for, and how to use it alongside the Console Guide. The source jumps straight into the `terraform {}` block at line 1927. S05 must write this paragraph.
- **`ridestreamlakehouse-<UNIQUE_SUFFIX>` placeholder is already used (no gap):** The S3 bucket name in the Terraform blocks already uses `ridestreamlakehouse-<UNIQUE_SUFFIX>` as a placeholder. No change needed here.
- **`data.aws_caller_identity.current.account_id` used in trust policy (no gap):** The EMR trust policy at lines 2393–2394 correctly uses `data.aws_caller_identity.current.account_id` instead of a hardcoded account ID. This is correct per the style guide — no change needed.
- **dbt install steps (Phases 14–17) have no Terraform equivalent — this is correct:** dbt is a CLI tool installed on EC2 via the console. There is no Terraform resource for dbt installation. S05 should not add one. Each of these console phases should have a note: `> **Terraform:** No Terraform equivalent — dbt is installed via CLI.`

---

## Resources Reference Section

The `## Resources Reference` H2 (lines 1875–1909) lists every file in the old `resources/` directory. This section is **superseded by the `docs/` layout** established in S01 and is no longer accurate (the files have moved and the PNG diagrams have been deleted).

**S06 action:** Remove the entire `## Resources Reference` H2 and replace it with a single callout:

```markdown
> **Resource files** are in `docs/resources/` (Python scripts and configuration) and `docs/dbt/` (dbt models and tests). See the [docs/](../docs/) folder.
```

The three PNG diagram entries (`architecture.png`, `data_model.png`, `stepfunctions_graph.png`) must not be re-listed — these files were deleted in S01 and replaced by draw.io / Mermaid outputs produced in S02.

---

## Cross-Cutting Gaps

These gaps span multiple sections and must be coordinated across S04, S05, and S06.

- **All `resources/` path references in the guide must become `docs/resources/` and `docs/dbt/`:** After T01 moved all files, path references like `resources/kafka_producer.py`, `resources/emr_spark_job.py`, `resources/dbt/sources.yml`, etc. are broken. S04 owns the console phase updates; S05 owns any Terraform block comments that referenced old paths; S06 owns final assembly and must verify no `resources/` references remain in the output guide. Path updates are not S01 work.
- **Cleanup Note (lines 1910–1923) must become a `> Note:` callout:** The `## Cleanup Note` H2 is not a style guide section — it is operational guidance. S06 must convert it from an H2 section to a blockquote callout and relocate it (likely to an appendix or the end of the Console Guide section). The content (list of costly resources to delete) is correct and must be preserved.
- **Troubleshooting section does not currently exist as a standalone section:** The source guide has two inline troubleshooting tables (Phase 5 at lines 387–396 and Phase 11 at lines 1027–1036) but no dedicated `## Troubleshooting` section. S04 extracts the two tables; S06 assembles them into a standalone `## Troubleshooting` section at the end of the guide, with anchor links back to the phases they relate to.
