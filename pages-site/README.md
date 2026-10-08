# GitLab Pages Markdown site (shared by luna/docs and cheshire/docs)

`build.py` renders `docs/*.md` → `public/<name>/index.html` plus an index page, copies `docs/assets/**` as-is (images,
linked from a page as `../assets/<file>`), and puts a strict CSP on every page (no scripts). `.gitlab-ci.yml` runs it on
the arm64 runner; `SITE_AUTHOR` sets the footer. luna/docs still carries the earlier copy from `../luna/publish/site/`.
