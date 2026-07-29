#!/bin/sh
set -eu

# Migrations must run BEFORE the app process starts, not after and not instead.
#
# app.main's startup hook calls init_db(), which is Base.metadata.create_all. On
# an empty database that would build every table from the models and leave
# alembic_version empty — after which `alembic upgrade head` fails on the first
# CREATE TABLE ("relation already exists"), and the schema silently diverges from
# the migration chain. Running alembic first means create_all finds the tables
# already present and is a no-op.
#
# Set RUN_MIGRATIONS=0 to skip, e.g. for a second replica that must not race the
# first, or to hold a deploy while migrating out of band.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
else
  echo "[entrypoint] RUN_MIGRATIONS=0 — skipping migrations"
fi

exec "$@"
