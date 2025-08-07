from datetime import datetime, timedelta

from astral import LocationInfo
from astral.moon import moonrise, moonset, phase


def _get_next_lunar_event(
    lat: float, lon: float, offset: timedelta, event_type: str
) -> datetime | None:
    """Get the next occurrence of a lunar event (moonrise or moonset) after now.

    This function handles cases where moonrise/moonset may not occur on certain days
    by iterating through dates until a valid future event is found.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        offset: Time offset to apply to the lunar event
        event_type: 'moonrise' or 'moonset'

    Returns:
        The next datetime when the lunar event + offset will occur, or None if invalid
        or no event found within a reasonable time (60 days)
    """
    try:
        location = LocationInfo(latitude=lat, longitude=lon)
        now = datetime.now()
        current_date = now.date()

        # Iterate through dates to find the next valid lunar event
        # Limit to 60 days to prevent infinite loops
        for days_ahead in range(60):
            check_date = current_date + timedelta(days=days_ahead)

            try:
                if event_type == "moonrise":
                    event_time = moonrise(
                        location.observer, date=check_date, tzinfo=location.tzinfo
                    )
                else:  # moonset
                    event_time = moonset(
                        location.observer, date=check_date, tzinfo=location.tzinfo
                    )

                if event_time is None:
                    # No moonrise/moonset on this date
                    continue

                event_time = event_time + offset

                # Make now timezone-aware for comparison
                now_aware = (
                    now.replace(tzinfo=location.tzinfo) if now.tzinfo is None else now
                )

                # Check if this event is in the future
                if event_time > now_aware:
                    return event_time

            except ValueError:
                # astral raises ValueError when moon doesn't rise/set on this date
                # (rare but possible), so continue to next date
                continue

        # No valid event found within 60 days
        return None

    except Exception:
        # Invalid coordinates or other error
        return None


class LunarUtils:
    """Lunar-specific utilities for creating time providers and phase checks."""

    # Phase constants representing target values in the 0-27.99 range
    NEW_MOON = 3.5  # Center of 0-6.99 range
    FIRST_QUARTER = 10.5  # Center of 7-13.99 range
    FULL_MOON = 17.5  # Center of 14-20.99 range
    LAST_QUARTER = 24.5  # Center of 21-27.99 range

    def at_moonrise(self, lat: float, lon: float, offset: timedelta = timedelta(0)):
        """Create a time provider that triggers at moonrise with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before moonrise, positive for after)

        Returns:
            A time provider function that returns the next moonrise + offset datetime
        """

        def time_provider() -> datetime | None:
            return _get_next_lunar_event(lat, lon, offset, "moonrise")

        return time_provider

    def at_moonset(self, lat: float, lon: float, offset: timedelta = timedelta(0)):
        """Create a time provider that triggers at moonset with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before moonset, positive for after)

        Returns:
            A time provider function that returns the next moonset + offset datetime
        """

        def time_provider() -> datetime | None:
            return _get_next_lunar_event(lat, lon, offset, "moonset")

        return time_provider

    def get_moonrise(
        self, lat: float, lon: float, offset: timedelta = timedelta(0)
    ) -> datetime | None:
        """Get today's moonrise time with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before moonrise, positive for after)

        Returns:
            Today's moonrise + offset datetime, or None if moonrise doesn't occur today
        """
        try:
            location = LocationInfo(latitude=lat, longitude=lon)
            today = datetime.now(tz=location.tzinfo).date()

            moonrise_time = moonrise(
                location.observer, date=today, tzinfo=location.tzinfo
            )
            if moonrise_time is None:
                return None
            return moonrise_time + offset

        except (ValueError, Exception):
            # ValueError if moon doesn't rise today, or other errors
            return None

    def get_moonset(
        self, lat: float, lon: float, offset: timedelta = timedelta(0)
    ) -> datetime | None:
        """Get today's moonset time with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before moonset, positive for after)

        Returns:
            Today's moonset + offset datetime, or None if moonset doesn't occur today
        """
        try:
            location = LocationInfo(latitude=lat, longitude=lon)
            today = datetime.now(tz=location.tzinfo).date()

            moonset_time = moonset(location.observer, date=today, tzinfo=location.tzinfo)
            if moonset_time is None:
                return None
            return moonset_time + offset

        except (ValueError, Exception):
            # ValueError if moon doesn't set today, or other errors
            return None

    def is_moon_up(self, lat: float, lon: float) -> bool:
        """Check if the moon is currently above the horizon.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            True if moon is currently above the horizon
        """
        try:
            moonrise_time = self.get_moonrise(lat, lon)
            moonset_time = self.get_moonset(lat, lon)

            # Handle cases where moonrise/moonset don't occur today
            if moonrise_time is None and moonset_time is None:
                # No moonrise or moonset today - moon is either continuously up or down
                # Check the most recent moonrise vs moonset to determine current state
                location = LocationInfo(latitude=lat, longitude=lon)
                now = datetime.now()

                # Look back up to 30 days for the most recent moonrise and moonset
                last_moonrise = None
                last_moonset = None

                for days_back in range(30):
                    check_date = now.date() - timedelta(days=days_back)
                    try:
                        if last_moonrise is None:
                            mr = moonrise(
                                location.observer, date=check_date, tzinfo=location.tzinfo
                            )
                            if mr is not None:
                                last_moonrise = mr

                        if last_moonset is None:
                            ms = moonset(
                                location.observer, date=check_date, tzinfo=location.tzinfo
                            )
                            if ms is not None:
                                last_moonset = ms

                        # Stop once we have both
                        if last_moonrise is not None and last_moonset is not None:
                            break
                    except ValueError:
                        continue

                # If we found both, the most recent event determines current state
                if last_moonrise is not None and last_moonset is not None:
                    return (
                        last_moonrise > last_moonset
                    )  # Moon is up if rise was more recent
                elif last_moonrise is not None:
                    return True  # Only found moonrise, so moon is up
                elif last_moonset is not None:
                    return False  # Only found moonset, so moon is down
                else:
                    return False  # Couldn't determine, assume moon is down
            elif moonrise_time is not None and moonset_time is None:
                # Moon rises but doesn't set today - moon is up after moonrise
                now = datetime.now(tz=moonrise_time.tzinfo)
                return now >= moonrise_time
            elif moonrise_time is None and moonset_time is not None:
                # Moon sets but doesn't rise today - moon was up before moonset
                now = datetime.now(tz=moonset_time.tzinfo)
                return now <= moonset_time
            else:
                # Both moonrise and moonset occur today
                assert moonrise_time is not None and moonset_time is not None
                now = datetime.now(tz=moonrise_time.tzinfo)

                if moonrise_time <= moonset_time:
                    # Normal case: moonrise before moonset
                    return moonrise_time <= now <= moonset_time
                else:
                    # Moonset before moonrise (moon was up from midnight)
                    return now <= moonset_time or now >= moonrise_time

        except Exception:
            return False

    def is_in_phase(self, target_phase: float) -> bool:
        """Check if the current moon is in the specified phase.

        Args:
            target_phase: Target phase value (0-27.99) or use class constants
                         like LunarUtils.NEW_MOON, LunarUtils.FULL_MOON, etc.

        Returns:
            True if current moon phase is within ±3.5 of the target phase
        """
        try:
            current_phase = phase(datetime.now().date())

            # Calculate difference, handling wraparound at 0/27.99 boundary
            diff = abs(current_phase - target_phase)

            # Handle wraparound (e.g., phase 1 vs phase 26 should be close)
            if diff > 14:  # More than half the cycle
                diff = 28 - diff

            # Check if within ±3.5 range (quarter phase tolerance)
            return diff <= 3.5

        except Exception:
            # Error calculating phase
            return False
