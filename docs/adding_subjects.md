# Adding subjects

1. **Collect and process as usual.** Run Qualisys, then Theia3D, then the RTP-Assessment V3D pipelines. Each session folder then contains `session_data.xml` and `session.xml`.
2. **Gather the subject folders in one place** on a local or lab drive (not a synced cloud folder):
   ```
   Data/
   ├── <LastName>_RTP_006/
   ├── <LastName>_RTP_007/
   └── ...
   ```
3. **Rebuild the database:**
   ```bash
   python rtp_ingest.py "path\to\Data" --out "path\to\rtp_database.h5"
   ```
   The script prints the trials it found per subject and movement, plus any session it skipped, e.g. a `session.xml` with no subject ID.
4. **Check it:** `python v3d_db.py` prints the summary, or open `streamlit run dashboard.py`.

## What the import reads

From each session folder it reads **only** `session_data.xml` and `session.xml`. Everything else stays on the lab drive as the raw archive and is not needed by the import: video, `.qtm`, `.c3d`, `TheiaFormatData`, `.cmz` workspaces. Keep that archive, because it's what you'd need to re-run V3D.

## Requirements on the Qualisys side

- Every subject needs an **ID** in Qualisys (`session.xml`). Sessions without one are skipped rather than named after the folder, because the folder name contains the last name.
- Trial names follow the Qualisys pattern `<Type name> <number>`, e.g. `Squatting Markerless Left 2`. Words like `Markerless`/`Markered` set the system, and `Left`/`Right` set the variant.

## Mock database

`python make_mock_database.py --subjects 30` builds `database/mock_database.h5` from the first real subject in the database. Every mock subject is labeled `MOCK_###` and the file is flagged `mock=True`, which makes the dashboard show a warning banner.
