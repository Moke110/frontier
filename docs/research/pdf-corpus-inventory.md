# PDF corpus inventory and extractability study

Wayfinder research ticket: [issue #8](https://github.com/Moke110/frontier/issues/8) — 「PDF 语料清单与可提取性研究」.
Status: **research complete**, artifacts produced, issue left open for main-agent verification.
Date: 2026-10-21. Scope: `~/arc`, `~/_research`, `~/library` on this WSL host.

## 摘要（中文）

- 三个目录下共有 **362 个 PDF**；剔除 22 个 venv/matplotlib 内置 PDF、8 个 `scvidr` 出图、2 份补充材料、1 份 GEO README 后，有 **329 个论文文件**，按 md5 去重后是 **174 篇唯一论文**（154 个 `_research/AICM/reference/PDFs` 文件与 `arc/reference/PDFs` 逐字节相同，另有 1 份 `Circulation 2020` 重复）。
- 全部 174 篇都是**原生电子版**（born-digital）：无扫描件、无加密、无纯非英文正文、无零文本页；共 3332 页、1470 万字符，中位数 17 页 / 77578 字符。正文抽取没有硬性障碍。
- PDF 自身能稳定给出 **DOI（94%）** 和 **标题（96%）**；**作者 88%**、**页码锚点 71%**；但 **年份只有 56%**、**摘要标题命中 53%**、**PMID 只有 6%**。PDF 内嵌元数据（`/Title`、`/Author`、`/CreationDate`）**不可信**，28/174 的 `CreationDate` 年份是错的。
- 结论：**正文用 PyMuPDF，书目字段用 DOI → Crossref/Europe PMC 回填**，不要试图从版式里硬抠所有字段。DOI 必须做防误抓（Zenodo/数据集 DOI、预印本 DOI、截断 DOI 都在样本里出现，共 8 篇需要纠正）。
- 推荐工具链：PyMuPDF（已装，151 ms/篇）+ Crossref REST + Europe PMC REST。系统无 `pdftotext`/poppler、无 GROBID、无 tesseract；在本语料上也不需要 OCR 或 GROBID。

## 1. Method

1. `find` all `*.pdf` under the three roots; hash every file (md5) to separate real duplicates from distinct files.
2. Remove non-paper classes by path/filename and by content check: `.venv`/`site-packages`/`mpl-data`, `scvidr/figures`, `*_Supplementary.pdf`, `*_MOESM*.pdf`, GEO `*README.pdf`.
3. Extract per-page text and layout with PyMuPDF; measure page count, character count, text-free pages, printed folio presence.
4. Extract DOI / title / authors / year / abstract from the PDF with layout-aware heuristics (page-1 only for DOI; font-size blocks for title; block-after-title for authors; `Abstract` heading for abstract).
5. Independently resolve each DOI through Crossref (`api.crossref.org/works/{doi}`) and Europe PMC (`search?query=DOI:"..."`), then compare PDF-derived values against those records. Where the PDF's DOI is missing or contradicted, recover via Europe PMC title search (strict title similarity ≥ 0.90).
6. Audit 32 papers (24 from `arc/reference/PDFs`, 6 cardiac-omics including 1 liver paper, 1 AIP, 1 pharmacology) by hand against the resolved metadata.

Reproduction scripts were run from `/tmp/opencode/pdfwork/` (throwaway, not committed); the only persisted outputs are the two artifacts listed in §10.

## 2. Corpus counts

### 2.1 Raw files

| Root / directory | PDFs |
|---|---:|
| `~/arc/reference/PDFs` | 161 |
| `~/arc/pert_model/cmonge/.venv/.../matplotlib/mpl-data/images` | 11 |
| `~/arc/pert_model/scvidr/figures` | 8 |
| `~/arc/stage2/01_setup/biolord/.venv/.../matplotlib/mpl-data/images` | 11 |
| `~/_research/AICM/reference/PDFs` | 154 |
| `~/_research/HMBS-MIRI` (omics + archive + 1 supplement) | 7 |
| `~/_research/HMBS-hypertrophy` (omics + GWAS supplement) | 4 |
| `~/_research/HMBS-liver` (3 GSE reference dirs) | 3 |
| `~/_research/AIP/GSE146212_mAIP` | 1 |
| `~/_research/MT/reference` | 1 |
| `~/library/matierials/GSE92742` | 1 |
| **Total** | **362** |

### 2.2 Exclusion funnel

| Step | Removed | Remaining |
|---|---:|---:|
| All PDFs | — | 362 |
| − venv / `site-packages` / matplotlib `mpl-data` | 22 | 340 |
| − `arc/pert_model/scvidr/figures/*.pdf` (8 regression-scatter plots, no bibliographic content) | 8 | 332 |
| − supplements (`41586_2024_8008_MOESM1_ESM.pdf`, `Henry2025_Supplementary.pdf`) | 2 | 330 |
| − `GSE92742_Broad_LINCS_README.pdf` (one-paragraph GEO pointer) | 1 | 329 |
| − byte-identical mirrors (see §3) | 155 | **174 unique papers** |

The ticket's rough estimate (~329 plausible paper PDFs) matches the file-level count exactly; the *document* count is 174.

### 2.3 Unique documents by category

| Category | Count | Definition |
|---|---:|---|
| `method` | 138 | perturbation / virtual-cell modelling & benchmark papers in `arc/reference/PDFs` |
| `application` | 12 | `*_App_*.pdf` — application papers that use DLEPS / DeepCE / GPAR / scGPT / TranSiGen |
| `data-resource` | 11 | `*_Data_*.pdf` — CCLE, GDSC, TCGA, LINCS, L1000, DepMap, PRISM, Perturb-seq atlases, scPerturb |
| `cardiac-omics` | 11 | HMBS-MIRI (6), HMBS-hypertrophy (2), HMBS-liver (3) |
| `aip` | 1 | `s40478-020-00910-z.pdf` (HMBS / acute intermittent porphyria mouse model) |
| `pharmacology-misc` | 1 | Gurkan 2018 mirtazapine QTc study (`_research/MT`) |

Volume: **3332 PDF pages**, **14.7 M characters**, median 17 pages and 77,578 characters per paper; 52 papers exceed 100 k characters. Medians are high enough for section-level chunking without fallback to abstracts.

## 3. Duplicates, mirrors, preprints, mislabels

**Byte-identical mirrors (155 files).** 154 files in `~/_research/AICM/reference/PDFs` are md5-identical to their `~/arc/reference/PDFs` namesakes (the two directories share 154 names; `arc` has 7 extra: `2020_GSE146097_DToxS`, `2022_GSE247541_Antivirals`, `2024_GSE217424_DToxS-iPSC`, `2024_GSE244740_ScreenSeq`, `2024_GSE262419_TempO-Seq`, `2026_Heijman_T-World`, `2026_Leskovec_PerturbHD`). One further duplicate is intra-tree: `HMBS-hypertrophy/omics/GSE120064_mTAC_scRNA/Circulation 2020.pdf` == `.../original/Circulation 2020.pdf`. Every manifest row carries `mirrored_paths` so the ingestion job can skip the copies.

**No content duplicates remain.** After mirror collapse, all 174 titles and all 167 DOIs are distinct (0 near-duplicate title pairs at similarity > 0.85).

**Preprints / non-journal identifiers (7 without a resolvable DOI).**

| Path | Identifier in file | Note |
|---|---|---|
| `arc/.../2022_Theis_chemCPA.pdf` | arXiv:2204.13545 | preprint only in corpus |
| `arc/.../2023_Karaletsos_SAMS-VAE.pdf` | arXiv:2311.02794 | preprint |
| `arc/.../2025_Graepel_PerturBench.pdf` | arXiv:2408.10609 | preprint |
| `arc/.../2026_Zhang_Stable-Shift.pdf` | arXiv:2606.24940 | preprint |
| `arc/.../2025_Kang_CRADLE-VAE.pdf` | none in PDF | arXiv paper by content, ID not recoverable from the file |
| `arc/.../2026_Ng_AROMA.pdf` | ACL 2026 Findings, pp. 31855–31881 | ACL Anthology, no DOI |
| `arc/.../2025_Jin_CrossDomain.pdf` | none | no DOI/arXiv anywhere in text |

Two further PDFs **print a preprint DOI for the published article**: `2020_Trapnell_sci-Plex.pdf` (prints `10.1101/315333`, published version `10.1126/science.aax6234`) and `2026_Tian_SysCompPert.pdf` (prints a bioRxiv DOI, published `10.1126/sciadv.aed3414`). Both are corrected in the manifest.

**Filename mislabel (1).** `arc/reference/PDFs/2025_App_scGPT_x_15.pdf` is not an scGPT application paper: its content is "A rationally designed injury kidney targeting peptide library…", *Science Advances* `10.1126/sciadv.adt3943`. Its page 1 carries only a Zenodo code DOI (`10.5281/zenodo.14632926`), which a naive extractor adopts as the article DOI. Filename taxonomy must not be trusted as ground truth.

## 4. Tooling: what is installed and what works

### 4.1 Availability (checked on this host)

| Tool | Status |
|---|---|
| PyMuPDF (`fitz`) 1.27.2.3 (system py3.13) / 1.28.2 (`biomni_e1` py3.11) | **available** |
| pdfplumber 0.11.10 | available |
| pypdf 6.13.1 / 6.14.2, PyPDF2 3.0.1, pdfminer.six 20260107 | available |
| `pdftotext` / `pdfinfo` (poppler) | **absent** (`/usr/bin/pdftotext` does not exist) |
| GROBID (binary or service) | **absent** — not on `PATH`, no installation found under `/` to depth 4 |
| `tesseract`, `ocrmypdf`, `mutool`, `qpdf`, `ghostscript` | absent |
| Docker | binary present, but daemon socket is not accessible (`permission denied`), so a GROBID container is not an option without sudo |
| Crossref REST, Europe PMC REST | reachable; Crossref returns `429` under sustained load (observed after ~350 requests) — needs a polite delay/backoff |

### 4.2 Extraction speed / quality benchmark (5 representative papers)

| Paper | Size | PyMuPDF | pypdf | pdfplumber (first 10 pp) |
|---|---:|---:|---:|---:|
| `2012_Data_CCLE.pdf` | 2.3 MB | 0.09 s / 48,408 ch | 1.57 s / 48,472 ch | 3.61 s / 44,935 ch |
| `2024_Ding_ManateeVAE.pdf` | 3.3 MB | 0.05 s / 25,253 ch | 0.95 s / 25,264 ch | 1.91 s / 24,958 ch |
| `2026_Leskovec_PerturbHD.pdf` | 3.1 MB | 0.08 s / 34,436 ch | 1.33 s / 58,613 ch | 2.05 s / 20,028 ch |
| `2026_Roohani_State.pdf` | 28 MB | 0.77 s / 197,411 ch | 11.26 s / 201,430 ch | 15.50 s / 49,303 ch |
| `Nature 2022.pdf` | 110 MB | 0.30 s / 182,276 ch | 6.92 s / 182,412 ch | 2.06 s / 66,634 ch |

Full-corpus text pass: **26.3 s for 174 papers / 3332 pages (151 ms per paper)** with PyMuPDF.

PyMuPDF wins decisively on speed. pypdf sometimes returns more characters (`PerturbHD`: 58.6 k vs 34.4 k) — likely annotation or hidden-layer text; extra characters are not automatically better for retrieval. pdfplumber is 20–40× slower and is only justified for table extraction.

### 4.3 GROBID verdict

GROBID is not installed and cannot be installed here without touching system packages (explicitly out of scope). Given 100 % born-digital text and 94 % page-1 DOI coverage, GROBID's marginal value is header disambiguation — which Crossref already solves more reliably. **Do not add GROBID.** Revisit only if the corpus later acquires scanned or two-column-heavy PDFs that fail the current checks.

## 5. Field-level extraction quality

Measured on all 174 unique papers. “PDF-only” = no network. “Enriched” = DOI → Crossref/Europe PMC.

| Field | PDF-only | Enriched | Comment |
|---|---:|---:|---|
| Page count | 174/174 | — | always available |
| Body text | 174/174 (100 %) | — | all ≥ 2000 chars; no encrypted/scanned files |
| DOI | 164/174 (94.3 %) on page 1; **157 usable as-is (90.2 %)** | 167/174 (96.0 %) | 5 are Zenodo/preprint DOIs, 2 truncated |
| Title | 174/174 non-empty; **167/174 (96.0 %) usable** (157 exactly match the Crossref title at ≥0.85) | 174/174 | 7 unusable: 5 with Crossref similarity < 0.6, 2 truncated arXiv titles |
| Authors | 153/174 (87.9 %) | 174/174 | PDF `/Author` alone covers only 111 and often just the first author |
| Year | text+`/CreationDate`: **96/171 (56.1 %)**; filename prefix: 146/161 (90.7 %) | 174/174 | `CreationDate` is the file-render date; wrong for 28/174 |
| Abstract | 92/174 (52.9 %) found via heading; ~4 of those are the wrong block | 162/174 (93.1 %) | Nature/Cell/Elsevier PDFs often have **no** “Abstract” label |
| PMID | 11/174 (6.3 %) printed in the PDF | 159/174 (91.4 %) | must come from Europe PMC, never from regex |
| Journal | — | 164/174 (94.3 %) | missing mainly for preprints |
| Printed folio (page anchor) | 123/174 (70.7 %) | — | 51 papers print no page number at all |

Two systematic traps confirmed by the audit:

1. **PDF `/Title` and `/Author` are production artifacts.** Examples: `2026_Fan_WAVE.pdf` → `/Title = "SpringerNature_NatCommun_77645_AIP 1..13"`; `2022_Xie_MultiDCP.pdf` → `"PLOS COMPUTATIONAL BIOLOGY"`; `2024_Quake_VirtualCellAI.pdf` → `"HHS Public Access"`. Never trust `/Title`.
2. **The first DOI-looking string on page 1 is not always the article DOI.** It can be a Zenodo dataset DOI (3 papers), a bioRxiv preprint DOI (2), or a truncated DOI cut by a line break (2). Guard with: require a `doi:` / `doi.org/` anchor, reject `10.5281/zenodo*` as article identity, and cross-check the candidate DOI's Crossref title against the extracted title.

## 6. 32-paper audit (PDF-only signals vs resolved metadata)

`Y` = correct, `~` = partial/degraded, `N` = failed. `DOI✓`: `Y` = page-1 DOI equals resolved DOI, `C` = corrected, `N` = none. `year` is scored against the PDF text only (`Received/Accepted/Published … YYYY` on page 1): `Y` = matches the resolved year, `~` = a year was found but differs (usually online-first vs issue year), `N` = no date on page 1. `abs`: E = Europe PMC, C = Crossref, P = PDF label only, N = none.

| # | file | cat | pp | DOI printed on p1 | DOI✓ | title | auth | year | abs | folio |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | s40478-020-00910-z.pdf | aip | 17 | 10.1186/s40478-020-00910-z | Y | Y | Y | N | E | Y |
| 2 | 2025_App_scGPT_x_15.pdf | application | 15 | 10.5281/zenodo.14632926 | C | Y | Y | N | E | N |
| 3 | 2026_App_DeepCE_x_12.pdf | application | 34 | 10.1038/s41551-026-01667-x | Y | Y | Y | ~ | E | N |
| 4 | Peizo1-MIRI-mitochondria.pdf | cardiac-omics | 16 | 10.1016/j.redox.2024.103471 | Y | Y | Y | ~ | E | Y |
| 5 | Cardiovasc Res 2023.pdf | cardiac-omics | 12 | – | C | Y | Y | N | E | Y |
| 6 | Nature 2022.pdf | cardiac-omics | 47 | 10.1038/s41586-022-05060-x | Y | Y | Y | ~ | E | N |
| 7 | Circulation 2020.pdf | cardiac-omics | 16 | 10.1161/CIRCULATIONAHA.119.043053 | Y | Y | Y | N | E | N |
| 8 | GSE183852.pdf | cardiac-omics | 48 | 10.1038/s44161-022-00028-6 | Y | Y | Y | N | E | N |
| 9 | s41586-024-07376-2.pdf | cardiac-omics | 32 | 10.1038/s41586-024-07376-2 | Y | ~ | Y | ~ | E | Y |
| 10 | 2012_Data_CCLE.pdf | data-resource | 8 | 10.1038/nature11003 | Y | Y | Y | N | E | N |
| 11 | 2017_Hahn_DepMap.pdf | method | 30 | 10.1016/j.cell.2017.06.010 | Y | Y | Y | N | E | Y |
| 12 | 2019_Weissman_Norman2019.pdf | method | 9 | 10.1126/science.aax4438 | Y | Y | Y | N | E | N |
| 13 | 2020_Lu_S-VQ-VAE.pdf | method | 11 | 10.1038/s41540-020-00158-2 | Y | Y | Y | N | E | Y |
| 14 | 2021_Stuart_VEGA.pdf | method | 9 | 10.1038/s41467-021-26017-0 | Y | Y | Y | N | E | Y |
| 15 | 2021_Xie_DLEPS.pdf | method | 21 | 10.1038/s41587-021-00946-z | Y | Y | Y | N | E | Y |
| 16 | 2022_GSE247541_Antivirals.pdf | method | 13 | 10.1002/advs.202203388 | Y | Y | Y | N | E | N |
| 17 | 2022_Zhang_CIGER.pdf | method | 13 | 10.1016/j.patter.2022.100441 | Y | Y | Y | N | E | Y |
| 18 | 2023_Herrmann_BioInfoVAE.pdf | method | 12 | 10.1093/bioinformatics/btad387 | Y | Y | Y | ~ | E | Y |
| 19 | 2023_Zhou_DLEPS.pdf | method | 13 | 10.1016/j.biopha.2023.115332 | Y | Y | Y | Y | E | Y |
| 20 | 2024_Li_GeneCompass.pdf | method | 16 | 10.1038/s41422-024-01034-y | Y | Y | Y | Y | E | Y |
| 21 | 2024_Nitzan_biolord.pdf | method | 18 | 10.1038/s41587-023-02079-x | Y | Y | Y | ~ | E | Y |
| 22 | 2024_Singh_scNODE.pdf | method | 9 | 10.1093/bioinformatics/btae393 | Y | Y | Y | N | E | N |
| 23 | 2024_Zhang_BioDSNN.pdf | method | 10 | 10.1093/bib/bbae617 | Y | Y | Y | Y | E | Y |
| 24 | 2025_Jin_CrossDomain.pdf | method | 9 | – | N | Y | Y | N | P | N |
| 25 | 2025_Liu_BenchGenPert.pdf | method | 26 | 10.1038/s41592-025-02980-0 | Y | Y | Y | ~ | E | Y |
| 26 | 2025_Song_scPerb.pdf | method | 10 | 10.1016/j.jare.2024.10.035 | Y | Y | Y | ~ | E | N |
| 27 | 2026_Fan_WAVE.pdf | method | 13 | 10.1038/s41467-026-77645-3 | Y | Y | Y | ~ | N | N |
| 28 | 2026_Leskovec_PerturbHD.pdf | method | 18 | 10.64898/2026.04.23.719015 | Y | ~ | Y | N | E | Y |
| 29 | 2026_Li_HerbTransfer.pdf | method | 19 | 10.20892/j.issn.2095-3941.2026.003 | Y | Y | Y | Y | E | Y |
| 30 | 2026_Roohani_State.pdf | method | 39 | 10.1016/j.cell.2026.07.052 | Y | Y | Y | N | E | N |
| 31 | 2026_Wang_scDPR.pdf | method | 17 | 10.1016/j.neunet.2026.109005 | Y | ~ | Y | ~ | E | Y |
| 32 | Clinical Pharm in Drug Dev - 2018 - Gurkan - | pharmacology-m | 10 | 10.1002/cpdd.605 | Y | Y | Y | ~ | E | Y |

Reading of the table: title and DOI are effectively solved; the year column is the dominant weakness — only 4/32 papers print a page-1 date matching the resolved year, 11 print a conflicting one (online-first vs issue), and 17 print none, which is why year must come from Crossref; `abs = E` in 30/32 shows that abstract recovery is an enrichment problem, not a parsing problem; `folio = N` in 12/32 is harmless because the PDF page index is the better anchor.

## 7. Failure inventory

### 7.1 DOI missing (7)

`2022_Theis_chemCPA.pdf`, `2023_Karaletsos_SAMS-VAE.pdf`, `2025_Graepel_PerturBench.pdf`, `2025_Jin_CrossDomain.pdf`, `2025_Kang_CRADLE-VAE.pdf`, `2026_Ng_AROMA.pdf`, `2026_Zhang_Stable-Shift.pdf` (all under `~/arc/reference/PDFs/`). Mitigation: keep `arxiv` where known, otherwise index by title + file hash; these 7 cannot be enriched and will have no PMID/abstract.

### 7.2 DOI printed in the PDF is wrong (8)

| File | DOI in PDF | Resolved DOI |
|---|---|---|
| `2025_App_scGPT_x_15.pdf` | `10.5281/zenodo.14632926` (code archive) | `10.1126/sciadv.adt3943` |
| `2024_Jiang_scPRAM.pdf` | `10.5281/zenodo.10935038` | `10.1093/bioinformatics/btae265` |
| `2026_Yoo_LDM-Drug.pdf` | `10.5281/zenodo.18871024` | `10.1093/bioinformatics/btag173` |
| `2023_Rubio_MoA-SEN.pdf` | `10.1101/2022.01.07.475326` (preprint) | `10.1016/j.ebiom.2023.104767` |
| `2026_Tian_SysCompPert.pdf` | `10.1101/2024.10.17.612997` (preprint) | `10.1126/sciadv.aed3414` |
| `2025_Roeder_DiffDebias.pdf` | `10.1073/pnas` (truncated) | `10.1073/pnas.2525268122` |
| `2026_Uhler_VCI.pdf` | `10.1371/journal.pcbi` (truncated) | `10.1371/journal.pcbi.1013194` |
| `2026_Heijman_T-World.pdf` | `10.1161/CIRCRESAHA.125.328073\x08` (stray control char) | `10.1161/CIRCRESAHA.125.328073` |

### 7.3 PDF-derived title unusable as-is (7)

Five have Crossref similarity < 0.6: `2022_Wyss-Coray_TabulaSapiens.pdf` (`biologyatcellular resolution.▪`), `2025_App_TranSiGen_x_21.pdf` (`JournalofAdvancedResearch`), `2024_GSE262419_TempO-Seq.pdf` (`InformingHazardIdentification…`), `2023_App_DLEPS_Dihydroartemisinin_06.pdf` (word-joined), `2025_Li_AIVC-Preclinical.pdf` (truncated at a line break). Two identifier-less arXiv PDFs yield truncated titles: `2022_Theis_chemCPA.pdf` → `"Predicting Cellular Responses to Novel Drug"`, `2023_Karaletsos_SAMS-VAE.pdf` → `"Modelling Cellular Perturbations with the Sparse"`. The manifest recovers the first five from Crossref; the last two would need manual repair if metadata were ever unavailable. (Other PDFs print `HHS Public Access`, `ARTICLE IN PRESS`, `■INTRODUCTION` or a journal name as the largest page-1 line — e.g. `2024_Quake_VirtualCellAI.pdf`, `2026_Teichmann_Celcomen.pdf`, `2023_App_DLEPS_Dihydroartemisinin_06.pdf` — but Crossref supersedes them.)

### 7.4 Abstract not obtainable (12), PMID not obtainable (15)

Missing abstract (12): `2022_Theis_chemCPA.pdf`, `2022_Yao_scBERT.pdf`, `2023_Karaletsos_SAMS-VAE.pdf`, `2025_Graepel_PerturBench.pdf`, `2025_Jin_CrossDomain.pdf`, `2025_Kang_CRADLE-VAE.pdf`, `2026_Born_CMG.pdf`, `2026_Fan_WAVE.pdf`, `2026_Ng_AROMA.pdf`, `2026_Tegner_SmallDataDrug.pdf`, `2026_Yang_XPert.pdf`, `2026_Zhang_Stable-Shift.pdf` (7 of these also lack a DOI; the manifest `has_abstract` flag is authoritative).

Missing PMID (15): the 7 DOI-less papers plus `2022_Yao_scBERT.pdf`, `2023_Hannenhalli_EpiDrugPred.pdf`, `2026_Born_CMG.pdf`, `2026_Fan_WAVE.pdf`, `2026_Leskovec_PerturbHD.pdf`, `2026_Tegner_SmallDataDrug.pdf`, `2026_Xie_MAP.pdf`, `2026_Yang_XPert.pdf` — mostly not-yet-indexed 2026 articles or non-PubMed venues.

### 7.5 Layout / pagination

- 51/174 papers print **no page folio**; the manifest therefore stores PDF page count only, and any citation anchor must be `pdf_page` (+ optional `printed_folio` when detected).
- 27 papers contain ≥1 text-free page (82 pages total). These are full-page figures, not scan failures — e.g. `Nature 2024.pdf` (6/32), `Nature 2022.pdf` (4/47). A chunker must emit an explicit `figure_page` marker instead of a silently empty chunk.
- Word-join artifacts (missing spaces between words) appear on title lines and in a minority of body text; 25/174 papers fall below 120 spaces per 1000 characters (median 129). Retrieval quality will degrade slightly unless a whitespace-repair pass (or PDF `blocks`-level reconstruction) is applied.

### 7.6 Classes that were *not* found

No encrypted PDFs, no scanned/image-only papers, no non-English papers (two PDFs contain CJK author names — `2026_Fan_WAVE.pdf`, `2026_Thomson_D-SPIN.pdf` — but the body is English), and no figure-only files inside the 174.

## 8. Recommended toolchain and ingestion pipeline

**Text layer**
1. PyMuPDF (`fitz`), `page.get_text("text")` for the body; `get_text("dict")` only for page-1 title/authors. Store per-page text so page anchors survive chunking.
2. Keep pdfplumber as an optional side-car for tables (not needed for v1).
3. Do **not** add GROBID, OCR, or poppler.

**Bibliographic layer**
4. Extract candidate DOI with an anchored regex (`doi:`, `https://doi.org/`) on page 1 only; strip trailing punctuation and control characters; reject `10.5281/zenodo*` as article identity; when the match ends mid-token (line-break truncation), take the longest complete DOI that starts at the same offset.
5. Validate the DOI by fetching Crossref (`works/{doi}`) and comparing its title with the PDF title (similarity ≥ 0.6 → accept).
6. If missing/invalid, run Europe PMC `TITLE:"…"` search and accept only ≥ 0.90 title similarity. This recovered 7/174 papers in one pass.
7. Take `year`, `journal`, canonical `title`, full author list, `pmid`, `pmcid`, and abstract from Crossref/Europe PMC, not from the PDF. Cache the responses (Crossref rate-limits at ~350 requests with `429`).
8. Fall back to arXiv ID for the 4 arXiv papers and to ACL Anthology metadata for `2026_Ng_AROMA.pdf`; leave `2025_Jin_CrossDomain.pdf` identifier-less.

**Chunking**
9. Section-split on numbered headings (`1 Introduction`, `2 Methods`, …) and on `Abstract/Introduction/Results/Discussion/Methods/References`; drop the reference list from the retrievable body (it inflates similarity and confuses claim extraction).
10. Anchor every chunk as `{path, pdf_page, printed_folio?, section}`.
11. Flag text-free pages as `figure_page` and exclude them from embedding.

**Quality gate for new PDFs**
12. Reject/queue for manual review when: chars < 2000, no DOI after recovery, title similarity < 0.6, or the file sits under a venv/figures/supplement path. This reproduces the 174-paper set from 362 raw files.

## 9. Risks and open questions

- **Identifier drift**: 8/174 PDFs print a DOI that does not identify the paper. Any downstream dedupe that trusts printed DOIs will merge distinct papers (e.g. a code-archive Zenodo DOI shared by several papers). Always resolve through Crossref before keying.
- **Crossref/Europe PMC availability**: the pipeline depends on two external APIs for year/abstract/PMID. Offline mode degrades to 56 % year accuracy and 53 % abstract coverage. Cache aggressively; consider a one-shot metadata snapshot committed as a fixture.
- **Year semantics**: “online-first year” vs “issue year” differ for 15/161 arc files (e.g. `2025_Liu_BenchGenPert` → issue 2026). The manifest uses the Crossref `issued` year; downstream topic timelines should state which convention they use.
- **Licensing**: 174 publisher PDFs (~1.5 GB) are personal copies. The knowledge base may store derived text/embeddings; redistributing PDFs or long verbatim excerpts is a separate legal question and out of scope here.
- **Growth**: the corpus is heavily 2025–2026 (76/174 papers). Any “recent advances” claim from this KB inherits that skew.
- **Not verified**: whether `2025_Kang_CRADLE-VAE.pdf` and `2025_Jin_CrossDomain.pdf` have published versions outside the corpus; whether the 7 DOI-less preprints have since been published. These need an online check at ingestion time, not now.

## 10. Artifacts

- `fixtures/pdf-manifest.jsonl` — 174 lines, one per unique paper PDF. Required fields: `path`, `title`, `year`, `doi`, `pmid`, `pages`, `text_status`, `category`, `notes`. Extra provenance fields: `title_source`, `pdf_title`, `authors`, `first_author`, `year_source`, `doi_pdf`, `doi_status` (`verified` 156 / `corrected` 8 / `fallback` 3 / `missing` 7), `doi_pdf_kind`, `pmcid`, `journal`, `has_abstract`, `abstract_source`, `chars`, `printed_page_numbers`, `preprint`, `arxiv`, `md5`, `size_bytes`, `mirrored_paths`. Every `path` and every `mirrored_paths` entry was re-checked to exist and to match its `md5` at write time.
- `docs/research/pdf-corpus-inventory.md` — this report.
