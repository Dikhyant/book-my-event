"""Inspect the existing database without altering it."""

from sqlalchemy import inspect, text

from app.db.database import engine
from app.models import Booking, Event, User


def main() -> None:
    with engine.connect() as conn:
        one = conn.execute(text("SELECT 1")).scalar()
        print(f"SELECT 1 -> {one}")

        current_db = conn.execute(text("SELECT current_database()")).scalar()
        current_user = conn.execute(text("SELECT current_user")).scalar()
        print(f"database={current_db} user={current_user}")

        enums = conn.execute(
            text(
                """
                SELECT t.typname, e.enumlabel
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public'
                  AND t.typname IN ('user_role', 'booking_status')
                ORDER BY t.typname, e.enumsortorder
                """
            )
        ).all()
        print("enums:")
        for typname, label in enums:
            print(f"  {typname}.{label}")

        auth_users = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'auth' AND table_name = 'users'
                )
                """
            )
        ).scalar()
        print(f"auth.users exists: {auth_users}")

        users_columns = conn.execute(
            text(
                """
                SELECT column_name, data_type, udt_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                ORDER BY ordinal_position
                """
            )
        ).all()
        print("public.users columns:")
        for row in users_columns:
            print(f"  {row.column_name} {row.udt_name} nullable={row.is_nullable} default={row.column_default}")

    inspector = inspect(engine)
    for model in (User, Event, Booking):
        table = model.__table__
        db_columns = {col["name"] for col in inspector.get_columns(table.name, schema="public")}
        mapped_columns = {col.name for col in table.columns}
        missing = mapped_columns - db_columns
        extra = db_columns - mapped_columns
        print(f"mapping {table.schema}.{table.name}: mapped={sorted(mapped_columns)}")
        if missing:
            print(f"  MISSING IN DATABASE: {sorted(missing)}")
        if extra:
            print(f"  present in database but not mapped: {sorted(extra)}")
        if not missing:
            print("  mapped columns exist in database")


if __name__ == "__main__":
    main()
