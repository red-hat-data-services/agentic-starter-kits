#!/bin/bash
# Creates additional databases needed by services sharing this PostgreSQL instance.
# This script runs automatically on first startup via /docker-entrypoint-initdb.d/

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE langfuse;
EOSQL
