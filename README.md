# Finance App

Personal finance application scaffold built with:

- Next.js 14
- TypeScript
- Prisma
- PostgreSQL
- NextAuth
- Tailwind CSS
- Docker

## Start

```bash
cp .env.example .env
docker compose up -d
npm install
npx prisma generate
npx prisma migrate dev
npm run dev
```

## GitHub push

```bash
git init
git add .
git commit -m "Initial finance app scaffold"

git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/finance-app.git
git push -u origin main
```
