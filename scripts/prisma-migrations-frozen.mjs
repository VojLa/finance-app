console.error(
  "Prisma migration creation is frozen during Alembic cutover preparation. " +
    "Create future schema changes through reviewed Alembic revisions after ownership activation."
)
process.exit(1)
