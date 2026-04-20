# Documentation Refactor — Orchestrator Prompt

## Objective

Refactor the existing pipeline documentation file `real_time_aws_dbt_architecture/taxi_riders_full_aws_pipeline_setup.md` (2533 lines, 17 console steps + Terraform + resources) so that it fully conforms to the style guide in `pipeline_documentation_style_guide.md`.

This is NOT a rewrite from scratch. The content is correct and complete — your job is to restructure, reformat, and fill gaps according to the style guide while preserving every piece of existing content. Nothing should be deleted unless the style guide explicitly says it should be removed (e.g., duplicated troubleshooting, inlined SQL that belongs in a file).

---

## Architecture: Orchestrator + Specialized Subagents

You MUST operate as an **orchestrator agent** that delegates work to specialized subagents. You do NOT do the work yourself — you plan, delegate, collect results, integrate, and verify.

### Why subagents matter

Each subagent has access to a specific **skill** (invoked via `/skill-name`). These skills contain domain-specific knowledge, templates, validation logic, and tooling that plain LLM reasoning does not have. **The entire point of using subagents is to invoke these skills.** A subagent that writes Terraform without invoking `/terraform-skill` is just guessing — it must use the skill to get the validated patterns, testing frameworks, and structural conventions the skill provides.

**CRITICAL RULE:** Every subagent listed below MUST invoke its assigned skill(s) via the `/skill-name` slash command as its FIRST action before doing any work. The skill loads domain-specific instructions, templates, and validation rules that the subagent needs. A subagent that does not invoke its skill is doing the job wrong — stop it and re-run with the skill invoked.

---

## Subagent Roster

### 1. AWS Architecture Diagram Subagent
- **Skill:** `/aws-architecture-diagram`
- **When to spawn:** When the orchestrator needs to produce or regenerate AWS architecture diagrams
- **Responsibilities:**
  - Invoke `/aws-architecture-diagram` with mode "analyze" to scan the existing codebase and extract the actual architecture
  - Generate a proper draw.io XML diagram with official AWS4 icons following the skill's reference architecture style (teal step badges, numbered legend, 48x48 icons, category containers)
  - The current project has `resources/architecture.png` — this subagent produces a proper `.drawio` SVG replacement to go in `diagrams/` per the style guide
  - Also regenerate `resources/data_model.png` and `resources/stepfunctions_graph.png` as proper draw.io diagrams if they depict AWS services
  - Ensure alt text on every diagram summarizes the data flow (style guide requirement)

### 2. AWS Console & Architecture Subagent
- **Skills:** `/aws-stuff` and `/deploy-on-aws`
- **When to spawn:** For all AWS-specific documentation content — architecture descriptions, console step-by-step phases, service explanations, IAM policies, component walkthroughs
- **Responsibilities:**
  - Invoke `/aws-stuff` first to load AWS service knowledge, then `/deploy-on-aws` for deployment patterns and service selection rationale
  - Restructure the Architecture section: data flow (actors-first with triggers as sub-bullets), component walkthrough (data-flow order), services table (category order with Pricing Model column), S3 bucket layout
  - Restructure all 17 console steps into properly formatted phases: phase title → what it does → numbered steps → configuration → Terraform cross-reference
  - Move all IAM policy JSON OUT of console phases — replace with descriptions and cross-references to the Terraform section
  - Add `> **Why X instead of Y?**` callout blocks for non-obvious architectural choices (e.g., why MSK Serverless, why Firehose instead of a custom consumer, why Glue Visual ETL instead of a Lambda, why EMR Serverless over Glue for the star schema)
  - Add `> **Tutorial vs our approach:**` callouts wherever the guide deviates from the trainer's approach
  - Add the `> Terraform: [Block Name](#anchor)` cross-reference at the end of every console phase
  - Ensure inline troubleshooting (like the Security Group fix in Step 2) stays in the console phase but is NOT duplicated in the Troubleshooting section
  - Use this skill's knowledge to verify that console steps are accurate and complete for each AWS service

### 3. Terraform Subagent
- **Skill:** `/terraform-skill`
- **When to spawn:** For all Terraform/IaC content
- **Responsibilities:**
  - Invoke `/terraform-skill` to load Terraform best practices, module patterns, and naming conventions
  - Restructure the existing "Terraform — All Resources" section into properly formatted blocks: `### Terraform: Resource Name` headings, one-sentence description + console phase back-link (`> Console: [Phase Name](#anchor)`)
  - Ensure blocks appear in the same order as console phases
  - Replace ALL hardcoded values: account IDs → `<ACCOUNT_ID>`, regions → `var.region`, environment names → `var.environment`, bucket names → `var.bucket_name`
  - Add `var.` references with comments for values from external systems
  - Add notes after each block about auto-created resources (what the console does automatically that Terraform must declare explicitly)
  - Create the **Parameterization Note** table at the end listing every placeholder
  - Add the provider preamble with variable declarations
  - Add a Scope note that Terraform does not manage Glue Catalog database objects or dbt project files
  - Validate the HCL is copy-pasteable and follows the skill's structural conventions

### 4. Mermaid Diagram Subagent
- **Skill:** `/mermaid-creator`
- **When to spawn:** For non-AWS diagrams — data models (star schema), dbt DAG lineage, Step Functions workflow (if a flowchart representation is preferred over the AWS draw.io version)
- **Responsibilities:**
  - Invoke `/mermaid-creator` to load the theming and rendering capabilities
  - Create a star schema ER diagram showing the dimensional model (dim_vendor, dim_location, dim_payment, fact_trips) with relationships
  - Create a dbt model lineage diagram showing sources → models → tests
  - Apply a consistent professional theme across all Mermaid diagrams
  - Export as SVG to `diagrams/` folder
  - These diagrams complement the AWS architecture diagram — they cover the data model and transformation logic, not the infrastructure

### 5. Documentation Structure Subagent
- **Skill:** `/read-large-doc` (to process the 2533-line source without context overflow)
- **When to spawn:** First — before any other subagent, to produce the refactoring plan
- **Responsibilities:**
  - Invoke `/read-large-doc` to ingest the full `taxi_riders_full_aws_pipeline_setup.md` and the `pipeline_documentation_style_guide.md`
  - Produce a detailed gap analysis: what the current doc has vs. what the style guide requires, section by section
  - Map current H2 headings to the style guide's section structure (Architecture / Console Guide / Terraform / Troubleshooting)
  - Identify content that needs to MOVE between sections (e.g., the Kafka Concepts section doesn't fit the style guide — decide where it belongs)
  - Identify missing elements: TOC, `> Last verified` date, comparison section (if needed), missing callouts, missing cross-references
  - Produce the master outline that the orchestrator uses to assign work to other subagents

---

## Orchestrator Workflow

### Phase 1: Analysis
1. Spawn the **Documentation Structure Subagent** to read both files and produce the gap analysis + master outline
2. Review the outline and confirm the section mapping before proceeding

### Phase 2: Parallel Content Work
Spawn these subagents in parallel — they work on independent sections:
- **AWS Architecture Diagram Subagent** — produce diagrams
- **Mermaid Diagram Subagent** — produce data model and dbt lineage diagrams
- **AWS Console & Architecture Subagent** — restructure Architecture section + all console phases
- **Terraform Subagent** — restructure the Terraform section

### Phase 3: Integration
1. Collect all subagent outputs
2. Assemble the restructured document in the style guide's section order:
   - Table of Contents
   - `> Last verified against source code: YYYY-MM-DD`
   - **Section 1: Architecture** (from AWS Console subagent + diagrams from diagram subagents)
   - **Section 2: Step-by-Step Console Guide** (from AWS Console subagent)
   - **Section 3: Terraform Configurations** (from Terraform subagent)
   - **Section 4: Troubleshooting** (extract from inline fixes in console phases, deduplicate, add frequency hints)
   - **Resources Reference** (keep existing, update paths to new diagram locations)
   - **Cleanup Note** (keep existing)
3. Verify cross-references: every console phase links to its Terraform block and vice versa; troubleshooting entries link back to relevant phases

### Phase 4: Verification
1. Check that NO content from the original document was lost
2. Check that IAM policy JSON appears ONLY in Terraform blocks, not console phases
3. Check that SQL/script content is referenced by path, not inlined
4. Check that all diagrams are in `diagrams/` and referenced with descriptive alt text
5. Check that all hardcoded account IDs, regions, and ARNs use placeholders
6. Check that `&nbsp;` is not used — use blank lines or `<br>` for spacing
7. Verify the document follows the folder layout from the style guide

---

## Current Document Structure (for reference)

The source file has these H2 sections that need to be remapped:

```
## Data Flow — How the Pipeline Works in Production  →  Section 1 (Architecture)
## Apache Kafka — Concepts                           →  Section 1 (Architecture) or standalone reference
## Step 1: Create the MSK Cluster                    →  Section 2 (Console Guide, Phase 1)
## Step 2: Create EC2 Instance (Kafka Client)        →  Section 2 (Console Guide, Phase 2)
## Step 3: Install Kafka Libraries on EC2            →  Section 2 (Console Guide, Phase 3)
## Step 4: IAM Policy and Role for EC2 → MSK Access  →  Section 2 (Console Guide, Phase 4)
## Step 5: Create Kafka Topic and Test               →  Section 2 (Console Guide, Phase 5)
## Step 6: Run the Kafka Producer Script             →  Section 2 (Console Guide, Phase 6)
## Step 7: Create S3 Bucket and Firehose Stream      →  Section 2 (Console Guide, Phase 7)
## Step 8: AWS Glue — Transform Raw Data             →  Section 2 (Console Guide, Phase 8)
## Step 9: EMR Serverless — Dimensional Modelling    →  Section 2 (Console Guide, Phase 9)
## Step 10: Glue Crawler and Athena                  →  Section 2 (Console Guide, Phase 10)
## Step 11: Step Functions — Automate EMR            →  Section 2 (Console Guide, Phase 11)
## Step 12: EventBridge — Automate Full Pipeline     →  Section 2 (Console Guide, Phase 12)
## Step 13: EC2 Instance for dbt                     →  Section 2 (Console Guide, Phase 13)
## Step 14: Install and Configure dbt on EC2         →  Section 2 (Console Guide, Phase 14)
## Step 15: dbt Project Setup                        →  Section 2 (Console Guide, Phase 15)
## Step 16: dbt Tests                                →  Section 2 (Console Guide, Phase 16)
## Step 17: dbt Documentation                        →  Section 2 (Console Guide, Phase 17)
## Resources Reference                               →  Keep as appendix
## Cleanup Note                                      →  Keep as appendix
## Terraform — All Resources                         →  Section 3 (Terraform Configurations)
```

---

## File Locations

- **Source document:** `real_time_aws_dbt_architecture/taxi_riders_full_aws_pipeline_setup.md`
- **Style guide:** `pipeline_documentation_style_guide.md`
- **Existing resources:** `real_time_aws_dbt_architecture/resources/` (scripts, diagrams, dbt files)
- **Output location:** `real_time_aws_dbt_architecture/` (restructured doc + new `diagrams/` folder)

---

## Constraints

- Do NOT invent content. Every fact, step, command, and configuration must come from the existing source document or from skill-validated knowledge.
- Do NOT delete the Kafka Concepts section — it may need to move (e.g., into a collapsible block within the Architecture section or a separate reference appendix), but the content stays.
- Do NOT create a Section 5 (Comparison/Key Differences) — this is not a variant guide.
- Do NOT deploy anything or run any AWS commands. The deploy-on-aws and aws-stuff skills are used purely for their documentation knowledge, not for actual deployment.
- Every subagent MUST invoke its skill(s) before producing output. If a subagent response does not show evidence of skill invocation, reject it and re-run.
