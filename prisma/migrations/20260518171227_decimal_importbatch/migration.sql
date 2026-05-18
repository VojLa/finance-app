/*
  Warnings:

  - You are about to alter the column `amount` on the `BudgetItem` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to alter the column `spent` on the `BudgetItem` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to alter the column `rolloverAmount` on the `BudgetItem` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to alter the column `rate` on the `ExchangeRate` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,8)`.
  - You are about to alter the column `quantity` on the `Holding` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `avgBuyPrice` on the `Holding` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `quantity` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `pricePerUnit` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `totalAmount` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `fee` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to alter the column `exchangeRate` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,8)`.
  - You are about to alter the column `realizedPnl` on the `InvestmentTransaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(28,10)`.
  - You are about to alter the column `amount` on the `Transaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to alter the column `amountCzk` on the `Transaction` table. The data in that column could be lost. The data in that column will be cast from `DoublePrecision` to `Decimal(18,6)`.
  - You are about to drop the `ImportLog` table. If the table is not empty, all the data it contains will be lost.

*/
-- DropForeignKey
ALTER TABLE "ImportLog" DROP CONSTRAINT "ImportLog_accountId_fkey";

-- AlterTable
ALTER TABLE "BudgetItem" ALTER COLUMN "amount" SET DATA TYPE DECIMAL(18,6),
ALTER COLUMN "spent" SET DATA TYPE DECIMAL(18,6),
ALTER COLUMN "rolloverAmount" SET DATA TYPE DECIMAL(18,6);

-- AlterTable
ALTER TABLE "ExchangeRate" ALTER COLUMN "rate" SET DATA TYPE DECIMAL(18,8);

-- AlterTable
ALTER TABLE "Holding" ALTER COLUMN "quantity" SET DATA TYPE DECIMAL(28,10),
ALTER COLUMN "avgBuyPrice" SET DATA TYPE DECIMAL(28,10);

-- AlterTable
ALTER TABLE "InvestmentTransaction" ALTER COLUMN "quantity" SET DATA TYPE DECIMAL(28,10),
ALTER COLUMN "pricePerUnit" SET DATA TYPE DECIMAL(28,10),
ALTER COLUMN "totalAmount" SET DATA TYPE DECIMAL(28,10),
ALTER COLUMN "fee" SET DATA TYPE DECIMAL(18,6),
ALTER COLUMN "exchangeRate" SET DATA TYPE DECIMAL(18,8),
ALTER COLUMN "realizedPnl" SET DATA TYPE DECIMAL(28,10);

-- AlterTable
ALTER TABLE "Transaction" ALTER COLUMN "amount" SET DATA TYPE DECIMAL(18,6),
ALTER COLUMN "amountCzk" SET DATA TYPE DECIMAL(18,6);

-- DropTable
DROP TABLE "ImportLog";

-- CreateTable
CREATE TABLE "ImportBatch" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "source" "ImportSource" NOT NULL,
    "filename" TEXT NOT NULL,
    "checksum" TEXT NOT NULL,
    "rowCount" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ImportBatch_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "ImportBatch_checksum_key" ON "ImportBatch"("checksum");

-- AddForeignKey
ALTER TABLE "ImportBatch" ADD CONSTRAINT "ImportBatch_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ImportBatch" ADD CONSTRAINT "ImportBatch_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "Account"("id") ON DELETE CASCADE ON UPDATE CASCADE;
