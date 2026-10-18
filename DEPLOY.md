# Deploy Stockroom to a free server

The app is ready for **Render**'s free web-service tier. Deployment config lives in `render.yaml` (and `Procfile` for other Python hosts).

> Assumption: the contents of this `stockroom/` folder become the **root of the Git repository**. If you push the whole parent workspace instead, set Render's **Root Directory** to `stockroom`.

## 1. Push the project to GitHub

Create an empty repository on GitHub, then from this folder:

```powershell
git init
git add .
git commit -m "Fibre materials Stockroom"
git branch -M main
git remote add origin https://github.com/<your-username>/fibre-stockroom.git
git push -u origin main
```

`.gitignore` keeps the local `.venv` and the SQLite database out of the repository. The demo database is created automatically on the server.

## 2. Deploy on Render

1. Sign up at <https://render.com> with your GitHub account.
2. Choose **New → Blueprint**.
3. Select the repository you just pushed.
4. Render detects `render.yaml`; click **Apply**.
5. Wait for the build. The service URL will look like:

   `https://fibre-stockroom.onrender.com`

Useful endpoints:

- `/` — app
- `/healthz` — returns `{"status":"ok"}`

### Manual setup instead of a Blueprint

If you prefer to create the service by hand:

| Setting | Value |
| --- | --- |
| Environment | Python 3 |
| Build command | `pip install --upgrade pip && pip install -r requirements.txt` |
| Start command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/healthz` |
| Instance type | Free |
| Environment variable | `PYTHON_VERSION = 3.12.14` |

Keep the start command to **one worker**. SQLite with multiple workers would create race conditions.

## 3. Verify

- Open the service URL after the first deploy. Free instances spin down after inactivity, so the first request can take 30–60 seconds.
- Visit `/healthz`; it should return `{"status":"ok"}`.
- The dashboard should show the seeded fibre catalogue.

## Important: free-tier data persistence

On Render's **free** tier, the filesystem is **ephemeral**. That means:

- The SQLite database resets whenever the service restarts, redeploys, or wakes from sleep.
- Each reset reseeds the demo catalogue.
- This is fine for testing and demos, but **do not enter data you need to keep**.

For persistent test data, you have options:

1. Attach a persistent Render Disk — requires a paid instance type.
2. Move the database to a free hosted Postgres such as Neon and adapt the app from SQLite to Postgres. This is a slightly larger change.
3. Use a host that offers a free persistent volume, such as Railway while you have trial credits.

## Security

The app currently has **no login screen**. Anyone with the public URL can view and change inventory. Treat the free deployment as a private demo and do not put real stock or personal data into it until authentication is added. A simple login or HTTP Basic Auth can be added before sharing the link more widely.

## Updating the deployment

```powershell
git add .
git commit -m "Update Stockroom"
git push
```

Render redeploys automatically. Because the free filesystem is ephemeral, expect a fresh seeded database after each deploy.
