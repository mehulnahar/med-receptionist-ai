"""
Multi-location & multi-doctor support.

Allows practices with multiple offices and providers to manage
location assignments and scheduling per location.
"""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class LocationService:
    """Manage practice locations and provider assignments."""

    @staticmethod
    async def create_location(
        db: AsyncSession,
        practice_id: UUID,
        name: str,
        address_line1: str = "",
        address_line2: str = "",
        city: str = "",
        state: str = "",
        zip_code: str = "",
        phone: str = "",
        fax: str = "",
        timezone_str: str = "America/New_York",
        is_primary: bool = False,
    ) -> dict:
        """Create a new practice location."""
        # If marking as primary, unset any existing primary
        if is_primary:
            await db.execute(
                text("""
                    UPDATE practice_locations SET is_primary = FALSE
                    WHERE practice_id = :pid AND is_primary = TRUE
                """),
                {"pid": str(practice_id)},
            )

        result = await db.execute(
            text("""
                INSERT INTO practice_locations
                    (id, practice_id, name, address_line1, address_line2,
                     city, state, zip_code, phone, fax, timezone,
                     is_primary, is_active, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :pid, :name, :addr1, :addr2,
                     :city, :state, :zip, :phone, :fax, :tz,
                     :primary, TRUE, NOW(), NOW())
                RETURNING id, name, is_primary, created_at
            """),
            {
                "pid": str(practice_id),
                "name": name,
                "addr1": address_line1,
                "addr2": address_line2,
                "city": city,
                "state": state,
                "zip": zip_code,
                "phone": phone,
                "fax": fax,
                "tz": timezone_str,
                "primary": is_primary,
            },
        )
        row = result.fetchone()
        await db.commit()

        logger.info("Location created: %s for practice %s", name, practice_id)
        return {
            "id": str(row.id),
            "name": row.name,
            "is_primary": row.is_primary,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    async def update_location(
        db: AsyncSession,
        location_id: str,
        practice_id: UUID,
        **fields,
    ) -> dict:
        """Update a location's fields."""
        allowed = {
            "name", "address_line1", "address_line2", "city", "state",
            "zip_code", "phone", "fax", "timezone", "is_primary",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return {"error": "No valid fields to update"}

        # If setting as primary, unset others first
        if updates.get("is_primary"):
            await db.execute(
                text("""
                    UPDATE practice_locations SET is_primary = FALSE
                    WHERE practice_id = :pid AND is_primary = TRUE
                """),
                {"pid": str(practice_id)},
            )

        set_parts = [f"{k} = :{k}" for k in updates]
        set_parts.append("updated_at = NOW()")
        set_clause = ", ".join(set_parts)

        params = {**updates, "lid": location_id, "pid": str(practice_id)}
        await db.execute(
            text(f"""
                UPDATE practice_locations SET {set_clause}
                WHERE id = :lid AND practice_id = :pid
            """),
            params,
        )
        await db.commit()
        return {"success": True, "updated": list(updates.keys())}

    @staticmethod
    async def list_locations(db: AsyncSession, practice_id: UUID) -> list[dict]:
        """List all locations for a practice."""
        result = await db.execute(
            text("""
                SELECT id, name, address_line1, address_line2, city, state,
                       zip_code, phone, fax, timezone, is_primary, is_active,
                       created_at
                FROM practice_locations
                WHERE practice_id = :pid AND is_active = TRUE
                ORDER BY is_primary DESC, name ASC
            """),
            {"pid": str(practice_id)},
        )
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "address_line1": row.address_line1,
                "address_line2": row.address_line2,
                "city": row.city,
                "state": row.state,
                "zip_code": row.zip_code,
                "phone": row.phone,
                "fax": row.fax,
                "timezone": row.timezone,
                "is_primary": row.is_primary,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.fetchall()
        ]

    @staticmethod
    async def get_location(
        db: AsyncSession, location_id: str, practice_id: UUID
    ) -> Optional[dict]:
        """Get a single location by ID."""
        result = await db.execute(
            text("""
                SELECT id, name, address_line1, address_line2, city, state,
                       zip_code, phone, fax, timezone, is_primary, is_active,
                       created_at, updated_at
                FROM practice_locations
                WHERE id = :lid AND practice_id = :pid
            """),
            {"lid": location_id, "pid": str(practice_id)},
        )
        row = result.fetchone()
        if not row:
            return None

        return {
            "id": str(row.id),
            "name": row.name,
            "address_line1": row.address_line1,
            "address_line2": row.address_line2,
            "city": row.city,
            "state": row.state,
            "zip_code": row.zip_code,
            "phone": row.phone,
            "fax": row.fax,
            "timezone": row.timezone,
            "is_primary": row.is_primary,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    async def deactivate_location(
        db: AsyncSession, location_id: str, practice_id: UUID
    ) -> bool:
        """Soft-delete a location."""
        result = await db.execute(
            text("""
                UPDATE practice_locations
                SET is_active = FALSE, updated_at = NOW()
                WHERE id = :lid AND practice_id = :pid AND is_primary = FALSE
            """),
            {"lid": location_id, "pid": str(practice_id)},
        )
        await db.commit()
        return result.rowcount > 0

    @staticmethod
    async def assign_provider_to_location(
        db: AsyncSession,
        provider_id: str,
        location_id: str,
        practice_id: UUID,
        is_primary: bool = False,
    ) -> bool:
        """Assign a provider to a location."""
        # Verify location belongs to practice
        loc = await db.execute(
            text("""
                SELECT id FROM practice_locations
                WHERE id = :lid AND practice_id = :pid AND is_active = TRUE
            """),
            {"lid": location_id, "pid": str(practice_id)},
        )
        if not loc.fetchone():
            return False

        await db.execute(
            text("""
                INSERT INTO provider_locations (id, provider_id, location_id, is_primary, created_at)
                VALUES (gen_random_uuid(), :prov_id, :loc_id, :primary, NOW())
                ON CONFLICT (provider_id, location_id) DO UPDATE SET
                    is_primary = :primary
            """),
            {
                "prov_id": provider_id,
                "loc_id": location_id,
                "primary": is_primary,
            },
        )
        await db.commit()
        return True

    @staticmethod
    async def get_location_providers(
        db: AsyncSession, location_id: str, practice_id: UUID
    ) -> list[dict]:
        """Get all providers assigned to a location."""
        result = await db.execute(
            text("""
                SELECT u.id, u.first_name, u.last_name, u.email, u.role,
                       pl.is_primary AS is_primary_location
                FROM provider_locations pl
                JOIN users u ON pl.provider_id = u.id
                JOIN practice_locations loc ON pl.location_id = loc.id
                WHERE pl.location_id = :lid AND loc.practice_id = :pid
                ORDER BY pl.is_primary DESC, u.last_name ASC
            """),
            {"lid": location_id, "pid": str(practice_id)},
        )
        return [
            {
                "id": str(row.id),
                "name": f"{row.first_name or ''} {row.last_name or ''}".strip(),
                "email": row.email,
                "role": row.role,
                "is_primary_location": row.is_primary_location,
            }
            for row in result.fetchall()
        ]

    @staticmethod
    async def get_provider_locations(
        db: AsyncSession, provider_id: str, practice_id: UUID
    ) -> list[dict]:
        """Get all locations a provider is assigned to."""
        result = await db.execute(
            text("""
                SELECT loc.id, loc.name, loc.city, loc.state, loc.phone,
                       pl.is_primary
                FROM provider_locations pl
                JOIN practice_locations loc ON pl.location_id = loc.id
                WHERE pl.provider_id = :prov_id AND loc.practice_id = :pid
                  AND loc.is_active = TRUE
                ORDER BY pl.is_primary DESC, loc.name ASC
            """),
            {"prov_id": provider_id, "pid": str(practice_id)},
        )
        return [
            {
                "id": str(row.id),
                "name": row.name,
                "city": row.city,
                "state": row.state,
                "phone": row.phone,
                "is_primary": row.is_primary,
            }
            for row in result.fetchall()
        ]
