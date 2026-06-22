# 2026-06-22 Logo Permission Fix

## Root Cause

Both the login page and sidebar use `/favicon-b.png` for the InterviewBoss logo. The deployed URL returned `403 Forbidden` because the source file `frontend/public/favicon-b.png` had mode `0600`. Vite copied that mode into `dist`, and the nginx image copied it into `/usr/share/nginx/html` as `-rw------- root root`, which nginx workers could not read.

`/favicon.png` still returned 200 because that file had mode `0664`, so the issue was file permissions, not a missing asset or bad path.

## Change

- Changed `frontend/public/favicon-b.png` from `0600` to `0644`.
- Hardened the Docker nginx runtime stage with `RUN chmod -R a+rX /usr/share/nginx/html` after copying frontend `dist`, so full image builds cannot preserve unreadable static asset modes.
- Documented the static asset permission requirement in `deploy/CLAUDE.md`.

## Verification

- RED: `curl http://localhost/favicon-b.png` returned `403`, and `stat` showed source mode `600`.
- Ran `./deploy/docker-deploy.sh update`; build output showed nginx-runtime executing `RUN chmod -R a+rX /usr/share/nginx/html`.
- GREEN: `curl -I http://localhost/favicon-b.png` returned `HTTP/1.1 200 OK` and `Content-Type: image/png`.
- GREEN: nginx container shows `/usr/share/nginx/html/favicon-b.png` as `-rw-r--r--`.
- GREEN: Playwright loaded `/login` and confirmed the `/favicon-b.png` image was complete with `naturalWidth: 256`.
