# Required Files for Existing Crews

The list of source documents the current `notes_crew`, `quiz_crew`, and `assignment_crew` reference by name.

All 34 files are linked from `docs/FOR DEVELOPER - AI INPUT SHEET 17062025 - B.A., (H) FILMMAKING.xlsx` (curriculum sheet, 100% coverage confirmed). The `scripts/download_curriculum.py` script pulls them into `docs/curriculum-pull/<sheet>/...`.

## How the bucket is laid out

```
curriculum/
├── <whole-book>.txt                        # source of truth, full extracted text
├── <book-slug>__<subtopic-slug>.txt        # per-subtopic excerpt (top-5 chunks via hybrid retrieval)
└── _embeddings/
    └── <book-slug>.json                    # offline pipeline cache: chunks + Gemini embeddings + source SHA-256
```

- The runtime (`app/services/document_store.py:get_document_text`) fetches the per-subtopic excerpt first; on 404 it falls back to the whole-book file. Same shape for both notes/quiz reading materials and assignment evaluation docs.
- The excerpt files are produced by `scripts/build_curriculum_excerpts.py` (run on demand). Install pipeline deps first: `pip install -e ".[pipeline]"`.
- The `_embeddings/` prefix is internal to the pipeline. The runtime never reads it.

Common operations:

```bash
# Full backfill (every book × every subtopic the YAMLs reference):
python scripts/build_curriculum_excerpts.py

# Rebuild excerpts for one book after re-uploading its source .txt:
python scripts/build_curriculum_excerpts.py --book "Bruce-Block-The-Visual-Story-...txt"

# Rebuild every book's excerpt for one subtopic:
python scripts/build_curriculum_excerpts.py --subtopic "blocking and staging"

# Preview without uploading:
python scripts/build_curriculum_excerpts.py --dry-run
```

## Books / PDFs (20 — used by `notes_crew` & `quiz_crew`)

Every reading-material entry is stored in the bucket as a `.txt` file under
the exact filename the YAML references. Originals (PDF/DOCX/Google Doc) are
extracted to `.txt` once at upload time so the runtime fetch is a single hop.

`quiz_crew/data/reading_materials.yaml` keeps the n8n-era PDF basenames (with
`.txt` substituted for `.pdf`):

| # | Filename |
|---|---|
| 1 | `How to Read a Film_ Movies, Media, and Beyond.txt` |
| 2 | `Film Art_ An Introduction 10th Edition ( PDFDrive ).txt` |
| 3 | `Ways of Seeing .txt` |
| 4 | `The Five C's of Cinematography_ Motion Picture Filming Techniques(1).txt` |
| 5 | `Screenplay; The Foundations of Screenwriting, revised & updated - Syd Field.txt` |
| 6 | `Film editing karel reiz.txt` |
| 7 | `Bruce-Block-The-Visual-Story-Creating-the-Visual-Structure-of-Film-TV-And-Digital-Media-2021.txt` |
| 8 | `On Writing_ A Memoir of the Craft - Stephen King.txt` |
| 9 | `Short stories by Guy de Maupassant.txt` |
| 10 | `The Stories of Anton Chekhov (Anton Chekhov).txt` |
| 11 | `the-anatomy-of-story-22-steps-to-becoming-a-master-storyteller_compress.txt` |
| 12 | `Art of Dramatic Writing - Lajos Egri.txt` |
| 13 | `toaz.info-save-the-cat-by-blake-snyder-pr_8defda23000f86ee7b077787303fa715.txt` |
| 14 | `Aristotle_Poetics_Lucas_Kassel_1968_1980.txt` |
| 15 | `Film Directing Shot by shot .txt` |
| 16 | `ilide.info-becoming-an-actorx27s-director-directing-actors-for-film-and-television-regg-pr_2c3d1d2c691c8c718bed0ca1c547c1e1.txt` |
| 17 | `Directing Actors_ Creating Memorable Performances for Film & Television.txt` |
| 18 | `Dialogue_-_Robert_McKee.txt` |
| 19 | `On Dialogue.txt` |
| 20 | `The Writer's Journey.txt` |

> One non-file entry exists: `https://www.celtx.com/` and `https://www.studiovity.com/` are mapped to subtopic "screenwriting softwares". No download needed — they're literal URLs passed through to the prompt.

## Institutional / Parameter docs (13 — used by `assignment_crew`)

Unique parameter files from `assignment_crew/data/evaluation_documents.yaml`
(all stored as `.txt` in the bucket):

| # | Filename (in bucket) | Source |
|---|---|---|
| 1 | `IDS SEM I-Film diary   Assignment - Parameters.txt` | docx |
| 2 | `IDS SEM I-Actuality  Assignment - Parameters.txt` | docx |
| 3 | `IDS SEM I-Film diary A2.txt` | docx |
| 4 | `A1.txt` | docx |
| 5 | `A3.txt` | docx |
| 6 | `A4.txt` | docx |
| 7 | `A5.txt` | docx |
| 8 | `A6.txt` | docx |
| 9 | `Assignment - Parameters.txt` | docx |
| 10 | `SEMESTER I - IDS I - RESEARCH.txt` | Google Doc |
| 11 | `IDS SEM I-SPW.txt` | Google Doc (also used by quiz/notes crews) |
| 12 | `IDS SEM II - parameters_dialogue.txt` | Google Doc (also used by quiz/notes crews) |
| 13 | `IDS SEM II-Blocking and Staging.txt` | Google Doc |

## Activity-flag values (NOT files — no download needed)

`assignment_crew` treats these strings as activity flags that trigger the default rubric path (see `app/crews/assignment_crew/config/tasks.yaml:19-31`). They are not document references:

- `Shoot` / `shoot`
- `theory`
- `Practical class with acting dept`
- `in class exercise`
- `group discussion - culminated three modules above`

## Totals

- **20 PDFs** (books)
- **13 institutional docs** (9 `.docx` + 4 Google Docs)
- **= 33 unique files**
