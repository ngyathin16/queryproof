# QueryProof interface direction

The redesign gives QueryProof the character of a SQL analysis instrument. The previous cream surfaces, green accents, rounded cards, and serif display text resembled Relay Desk. QueryProof now uses graphite (`#101416`), lime (`#d7f46b`), square edges, IBM Plex typography, and a compact workbench organized around the query and its evidence.

Three local, runnable studies informed the choice:

| Study | Strength | Decision |
| --- | --- | --- |
| Graphite instrument | Clear separation between query, verdict, and row evidence; a distinct identity for technical work. | Selected as the production direction. |
| Cobalt analyst | Bright, highly legible workspace with a horizontal metric definition and a strong result summary. | Retained as an alternative; graphite creates greater visual separation from Relay Desk. |
| Monochrome ledger | Restrained report-like hierarchy that makes numbers and their explanation prominent. | Retained as an alternative; the instrument direction better supports repeated query editing and inspection. |

These are read-only design studies, not alternate application modes. They use the same fictional join-duplication example: 1,110 original revenue, 400 reference revenue, and 710 excess revenue. Orders 1, 3, and 4 appear four, three, and two times respectively.

## Production layout

Keep the dataset and metric definition compact, then place the SQL editor beside the analysis results when space allows. Put the verdict and numeric comparison ahead of detailed findings. Keep witness rows close to the finding they explain; expose the proposed repair and verification as the next step in that same review. On narrow screens, stack these regions in reading order and contain wide SQL and tables within their own scroll areas.

Preserve the working application flow: choose or upload data, inspect the definition, edit and run SQL, inspect witnesses, verify a repair, export evidence, and reopen history. The redesign changes presentation, not the meaning of a result or the analysis engine. Every visible action must invoke its real behavior; decorative prototype controls must not enter production.

## Typography and access

Use IBM Plex Sans for the interface and IBM Plex Mono for SQL and numeric evidence. Both fonts are bundled locally through Fontsource, without remote font requests. Their original SIL Open Font License notices ship in [IBM-PLEX-SANS-LICENSE.txt](../ui/public/licenses/IBM-PLEX-SANS-LICENSE.txt) and [IBM-PLEX-MONO-LICENSE.txt](../ui/public/licenses/IBM-PLEX-MONO-LICENSE.txt).

Preserve semantic controls, associated field labels, the skip link, keyboard navigation, and visible focus outlines. Communicate verdicts with words and symbols as well as color. Keep disabled and busy states explicit, respect reduced motion, and retain the full workflow on mobile. Browser verification should exercise the live controls, check contrast and keyboard focus, and inspect narrow layouts; the static studies alone do not establish accessibility.
