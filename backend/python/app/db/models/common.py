from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql

TIMESTAMP = postgresql.TIMESTAMP(precision=3, timezone=False)
JSONB = postgresql.JSONB
MONEY = Numeric(18, 6)
QUANTITY = Numeric(28, 10)
RATE = Numeric(18, 8)
PERCENTAGE = Numeric(8, 4)
THRESHOLD = Numeric(5, 4)
