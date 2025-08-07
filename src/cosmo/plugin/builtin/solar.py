from datetime import datetime, timedelta

from astral import LocationInfo
from astral.sun import sun


def _get_next_solar_event(
    lat: float, lon: float, offset: timedelta, event_type: str
) -> datetime | None:
    """Get the next occurrence of a solar event (sunrise or sunset) after now.

    This function handles polar regions where sunrise/sunset may not occur for months
    by iterating through dates until a valid future event is found.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        offset: Time offset to apply to the solar event
        event_type: 'sunrise' or 'sunset'

    Returns:
        The next datetime when the solar event + offset will occur, or None if invalid
        or no event found within a reasonable time (1 year)
    """
    try:
        location = LocationInfo(latitude=lat, longitude=lon)
        now = datetime.now()
        current_date = now.date()

        # Iterate through dates to find the next valid solar event
        # Limit to 1 year to prevent infinite loops in extreme cases
        for days_ahead in range(366):
            check_date = current_date + timedelta(days=days_ahead)

            try:
                # Use local timezone for the calculation
                s = sun(location.observer, date=check_date, tzinfo=location.tzinfo)
                event_time = s[event_type] + offset

                # Make now timezone-aware for comparison
                now_aware = (
                    now.replace(tzinfo=location.tzinfo) if now.tzinfo is None else now
                )

                # Check if this event is in the future
                if event_time > now_aware:
                    return event_time

            except ValueError:
                # astral raises ValueError when sun doesn't rise/set on this date
                # (e.g., polar night/day), so continue to next date
                continue

        # No valid event found within a year
        return None

    except Exception:
        # Invalid coordinates or other error
        return None


class SolarUtils:
    """Solar-specific utilities for creating time providers."""

    def at_sunrise(self, lat: float, lon: float, offset: timedelta = timedelta(0)):
        """Create a time provider that triggers at sunrise with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before sunrise, positive for after)

        Returns:
            A time provider function that returns the next sunrise + offset datetime
        """

        def time_provider() -> datetime | None:
            return _get_next_solar_event(lat, lon, offset, "sunrise")

        return time_provider

    def at_sunset(self, lat: float, lon: float, offset: timedelta = timedelta(0)):
        """Create a time provider that triggers at sunset with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before sunset, positive for after)

        Returns:
            A time provider function that returns the next sunset + offset datetime
        """

        def time_provider() -> datetime | None:
            return _get_next_solar_event(lat, lon, offset, "sunset")

        return time_provider

    def get_sunrise(
        self, lat: float, lon: float, offset: timedelta = timedelta(0)
    ) -> datetime | None:
        """Get today's sunrise time with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before sunrise, positive for after)

        Returns:
            Today's sunrise + offset datetime, or None if sunrise doesn't occur today
        """
        try:
            location = LocationInfo(latitude=lat, longitude=lon)
            today = datetime.now(tz=location.tzinfo).date()

            s = sun(location.observer, date=today, tzinfo=location.tzinfo)
            return s["sunrise"] + offset

        except (ValueError, Exception):
            # ValueError if sun doesn't rise today, or other errors
            return None

    def get_sunset(
        self, lat: float, lon: float, offset: timedelta = timedelta(0)
    ) -> datetime | None:
        """Get today's sunset time with optional offset.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            offset: Time offset (negative for before sunset, positive for after)

        Returns:
            Today's sunset + offset datetime, or None if sunset doesn't occur today
        """
        try:
            location = LocationInfo(latitude=lat, longitude=lon)
            today = datetime.now(tz=location.tzinfo).date()

            s = sun(location.observer, date=today, tzinfo=location.tzinfo)
            return s["sunset"] + offset

        except (ValueError, Exception):
            # ValueError if sun doesn't set today, or other errors
            return None

    def is_daytime(self, lat: float, lon: float) -> bool:
        """Check if it's currently daytime (between sunrise and sunset).

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            True if current time is between today's sunrise and sunset.
            In polar regions: True during midnight sun, False during polar night.
        """
        try:
            sunrise = self.get_sunrise(lat, lon)
            sunset = self.get_sunset(lat, lon)

            # Handle polar conditions
            if sunrise is None and sunset is None:
                # Polar winter (polar night) - no sunrise or sunset
                return False
            elif sunrise is not None and sunset is None:
                # Polar summer (midnight sun) - sunrise but no sunset
                return True
            elif sunrise is None and sunset is not None:
                # Unusual case - shouldn't happen in practice, assume nighttime
                return False
            else:
                # Normal case - both sunrise and sunset exist
                # Type guard: we know both are not None here
                assert sunrise is not None and sunset is not None
                now = datetime.now(tz=sunrise.tzinfo)
                return sunrise <= now <= sunset

        except Exception:
            return False

    def is_nighttime(self, lat: float, lon: float) -> bool:
        """Check if it's currently nighttime (between sunset and sunrise).

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees

        Returns:
            True if current time is between today's sunset and tomorrow's sunrise.
            In polar regions: False during midnight sun, True during polar night.
        """
        return not self.is_daytime(lat, lon)
