-- Backfill listing identity for existing local data after AssetListing became the
-- concrete tradable/priceable identity.

ALTER TABLE "InvestmentMovement" ADD COLUMN IF NOT EXISTS "listingId" TEXT;
ALTER TABLE "Holding" ADD COLUMN IF NOT EXISTS "listingId" TEXT;
ALTER TABLE "AccountSnapshotItem" ADD COLUMN IF NOT EXISTS "listingId" TEXT;

INSERT INTO "AssetListing" (
  "id",
  "assetId",
  "symbol",
  "exchange",
  "currency",
  "provider",
  "providerSymbol",
  "isPrimary",
  "createdAt",
  "updatedAt"
)
SELECT DISTINCT
  'lst_' || md5(m."assetId" || m."sourceSymbol" || COALESCE(m."valueCurrency", m."currency", a."currency") || 'legacy_movement'),
  m."assetId",
  m."sourceSymbol",
  'legacy',
  COALESCE(m."valueCurrency", m."currency", a."currency"),
  'broker'::"PriceSource",
  m."sourceSymbol",
  true,
  now(),
  now()
FROM "InvestmentMovement" m
JOIN "Asset" a ON a."id" = m."assetId"
WHERE m."kind" = 'asset'
  AND m."assetId" IS NOT NULL
  AND m."sourceSymbol" IS NOT NULL
ON CONFLICT ("assetId", "symbol", "exchange", "currency") DO NOTHING;

INSERT INTO "AssetListing" (
  "id",
  "assetId",
  "symbol",
  "exchange",
  "currency",
  "provider",
  "providerSymbol",
  "isPrimary",
  "createdAt",
  "updatedAt"
)
SELECT DISTINCT
  'lst_' || md5(h."assetId" || h."symbol" || h."currency" || 'legacy_holding'),
  h."assetId",
  h."symbol",
  'legacy',
  h."currency",
  'broker'::"PriceSource",
  h."symbol",
  true,
  now(),
  now()
FROM "Holding" h
WHERE h."assetId" IS NOT NULL
ON CONFLICT ("assetId", "symbol", "exchange", "currency") DO NOTHING;

INSERT INTO "AssetListing" (
  "id",
  "assetId",
  "symbol",
  "exchange",
  "currency",
  "provider",
  "providerSymbol",
  "isPrimary",
  "createdAt",
  "updatedAt"
)
SELECT DISTINCT
  'lst_' || md5(i."assetId" || i."symbol" || COALESCE(i."costCurrency", i."priceCurrency", a."currency") || 'legacy_snapshot'),
  i."assetId",
  i."symbol",
  'legacy',
  COALESCE(i."costCurrency", i."priceCurrency", a."currency"),
  'broker'::"PriceSource",
  i."symbol",
  true,
  now(),
  now()
FROM "AccountSnapshotItem" i
JOIN "Asset" a ON a."id" = i."assetId"
WHERE i."assetId" IS NOT NULL
ON CONFLICT ("assetId", "symbol", "exchange", "currency") DO NOTHING;

UPDATE "InvestmentMovement" m
SET "listingId" = (
  SELECT l."id"
  FROM "AssetListing" l
  WHERE l."assetId" = m."assetId"
    AND (l."symbol" = m."sourceSymbol" OR l."providerSymbol" = m."sourceSymbol")
  ORDER BY
    (l."currency" = COALESCE(m."valueCurrency", m."currency")) DESC,
    l."isPrimary" DESC,
    l."updatedAt" DESC
  LIMIT 1
)
WHERE m."listingId" IS NULL
  AND m."kind" = 'asset'
  AND m."assetId" IS NOT NULL
  AND m."sourceSymbol" IS NOT NULL;

UPDATE "Holding" h
SET "listingId" = (
  SELECT l."id"
  FROM "AssetListing" l
  WHERE l."assetId" = h."assetId"
    AND (l."symbol" = h."symbol" OR l."providerSymbol" = h."symbol")
  ORDER BY
    (l."currency" = h."currency") DESC,
    l."isPrimary" DESC,
    l."updatedAt" DESC
  LIMIT 1
)
WHERE h."listingId" IS NULL
  AND h."assetId" IS NOT NULL;

UPDATE "AccountSnapshotItem" i
SET "listingId" = (
  SELECT l."id"
  FROM "AssetListing" l
  WHERE l."assetId" = i."assetId"
    AND (l."symbol" = i."symbol" OR l."providerSymbol" = i."symbol")
  ORDER BY
    (l."currency" = COALESCE(i."costCurrency", i."priceCurrency")) DESC,
    l."isPrimary" DESC,
    l."updatedAt" DESC
  LIMIT 1
)
WHERE i."listingId" IS NULL
  AND i."assetId" IS NOT NULL;

UPDATE "PriceSnapshot" p
SET "listingId" = (
  SELECT l."id"
  FROM "AssetListing" l
  WHERE l."assetId" = p."assetId"
    AND l."currency" = p."currency"
  ORDER BY
    (l."provider" = p."source") DESC,
    l."isPrimary" DESC,
    l."updatedAt" DESC
  LIMIT 1
)
WHERE p."listingId" IS NULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM "Holding" WHERE "listingId" IS NULL) THEN
    RAISE EXCEPTION 'Cannot make Holding.listingId required; some rows were not backfilled.';
  END IF;

  IF EXISTS (SELECT 1 FROM "AccountSnapshotItem" WHERE "listingId" IS NULL) THEN
    RAISE EXCEPTION 'Cannot make AccountSnapshotItem.listingId required; some rows were not backfilled.';
  END IF;

  IF EXISTS (SELECT 1 FROM "PriceSnapshot" WHERE "listingId" IS NULL) THEN
    RAISE EXCEPTION 'Cannot make PriceSnapshot.listingId required; some rows were not backfilled.';
  END IF;
END $$;

DROP INDEX IF EXISTS "Asset_symbol_key";
CREATE INDEX IF NOT EXISTS "Asset_symbol_idx" ON "Asset"("symbol");

DROP INDEX IF EXISTS "PriceSnapshot_assetId_timestamp_source_key";
CREATE UNIQUE INDEX IF NOT EXISTS "PriceSnapshot_listingId_timestamp_source_key"
  ON "PriceSnapshot"("listingId", "timestamp", "source");

DROP INDEX IF EXISTS "Holding_symbol_accountId_key";
CREATE INDEX IF NOT EXISTS "Holding_listingId_idx" ON "Holding"("listingId");
CREATE UNIQUE INDEX IF NOT EXISTS "Holding_accountId_listingId_key"
  ON "Holding"("accountId", "listingId");

DROP INDEX IF EXISTS "AccountSnapshotItem_snapshotId_symbol_key";
CREATE INDEX IF NOT EXISTS "AccountSnapshotItem_listingId_idx" ON "AccountSnapshotItem"("listingId");
CREATE UNIQUE INDEX IF NOT EXISTS "AccountSnapshotItem_snapshotId_listingId_key"
  ON "AccountSnapshotItem"("snapshotId", "listingId");

CREATE UNIQUE INDEX IF NOT EXISTS "AssetListing_symbol_exchange_currency_key"
  ON "AssetListing"("symbol", "exchange", "currency");
CREATE UNIQUE INDEX IF NOT EXISTS "AssetListing_provider_providerSymbol_currency_key"
  ON "AssetListing"("provider", "providerSymbol", "currency");

CREATE INDEX IF NOT EXISTS "InvestmentMovement_listingId_idx" ON "InvestmentMovement"("listingId");

ALTER TABLE "Holding" ALTER COLUMN "listingId" SET NOT NULL;
ALTER TABLE "AccountSnapshotItem" ALTER COLUMN "listingId" SET NOT NULL;
ALTER TABLE "PriceSnapshot" ALTER COLUMN "listingId" SET NOT NULL;

ALTER TABLE "PriceSnapshot" DROP CONSTRAINT IF EXISTS "PriceSnapshot_listingId_fkey";
ALTER TABLE "PriceSnapshot"
  ADD CONSTRAINT "PriceSnapshot_listingId_fkey"
  FOREIGN KEY ("listingId") REFERENCES "AssetListing"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "InvestmentMovement" DROP CONSTRAINT IF EXISTS "InvestmentMovement_listingId_fkey";
ALTER TABLE "InvestmentMovement"
  ADD CONSTRAINT "InvestmentMovement_listingId_fkey"
  FOREIGN KEY ("listingId") REFERENCES "AssetListing"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "Holding" DROP CONSTRAINT IF EXISTS "Holding_listingId_fkey";
ALTER TABLE "Holding"
  ADD CONSTRAINT "Holding_listingId_fkey"
  FOREIGN KEY ("listingId") REFERENCES "AssetListing"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "AccountSnapshotItem" DROP CONSTRAINT IF EXISTS "AccountSnapshotItem_listingId_fkey";
ALTER TABLE "AccountSnapshotItem"
  ADD CONSTRAINT "AccountSnapshotItem_listingId_fkey"
  FOREIGN KEY ("listingId") REFERENCES "AssetListing"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
