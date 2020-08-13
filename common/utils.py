from delorean import Delorean


def full_name(user):
    return f"{user.first_name} {user.last_name}"


def start_of_day_in_utc(input_datetime):
    return Delorean(input_datetime, timezone="utc").start_of_day


def end_of_day_in_utc(input_datetime):
    return Delorean(input_datetime, timezone="utc").end_of_day


def end_of_day_in_local_time(input_datetime, local_timezone="Europe/London"):
    # Return localtime end of day in UTC
    end_of_day_utc = end_of_day_in_utc(input_datetime)
    utc_offset_at_input_datetime = Delorean(input_datetime, timezone="utc").shift(local_timezone).datetime.utcoffset()
    return end_of_day_utc - utc_offset_at_input_datetime
