# DCMM Manual Audit Calibration

1. **Format Enforcement (v4.5 Base)**
   - The assessment agency name ("评估机构名称") must be added to the basic enterprise information but kept concise without over-explanation.
   - The "总体判定与问题摘要" (Verdict and Summary) section must have the verdict on a single line. Problem summaries should be categorized into "踩红线", "红线质疑", "其他改进", and "亮点描述（如有）". This summary should be highly condensed, strictly summarizing the detailed table below, and **MUST NOT** contain page numbers or figure numbers.
   - If a category in the summary has no issues, simply output "无" (None) without any explanation. All positive highlights should go into the "亮点描述（如有）" section.
   - The "判定详情表" (Verdict Details Table) **MUST** include page numbers. For text, it must specify the paragraph and line number. For charts/images, it must specify the figure number. The details table must fully support all issues mentioned in the summary section (it can have more details, but cannot have fewer issues than the summary).

2. **Audit Logic & Hallucination Prevention**
   - **No AI Preambles**: The output must be strictly the markdown report. Any introductory or conversational text (e.g., "基于您提供的海量评估材料...", "【审计排雷说明】") is strictly prohibited. The report must not show cross-contamination from other enterprise materials.
   - **Irrelevant Domain Questioning**: Do not question issues in irrelevant domains. For example, issues regarding the "Operation Metrics System" relying on Excel should not be a major violation in the Operation domain if it's not a standard domain issue. Metrics management belongs to the Data Standard domain. A single missing system feature cannot automatically result in a "Major Rectification" verdict.
   - **Reasonable Redaction**: Accept reasonable redaction/masking (virtualization) of evidence, especially for corporate emails and financial figures. Only question situations where large areas are blacked out making the content completely indistinguishable.
   - **Red Line Scope**: Red line queries should be derived primarily from `rules.md` and the "Entry Requirements" section of the Assessment Guidelines PDF. Do not nitpick on minor details (like "cannot see revenue").

3. **Summary Export Columns**
   - The generated `Summary_L4L5.md` and Excel files must maintain the following column order: `受评单位，底稿链接，目标等级，评估机构，判定结论，踩红线、红线质疑点、其他改进点、亮点描述（如有）`.

4. **Future Optimizations & Low Priority Tasks**
   - **Similarity/Plagiarism Check (Low Priority)**: For large batches (300+), implement a targeted similarity check by extracting system screenshots, captions, and their corresponding audit points (domain/clause). Perform embedding comparison on entries for the same audit point across different companies to identify reused/plagiarized evidence.

