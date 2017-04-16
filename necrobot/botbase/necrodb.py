import mysql.connector

from necrobot.ladder.rating import create_rating
from necrobot.util.config import Config
from necrobot.user.userprefs import UserPrefs


class DBConnect(object):
    db_connection = None

    def __init__(self, commit=False):
        self.cursor = None
        self.commit = commit

    def __enter__(self):
        if DBConnect.db_connection is None:
            DBConnect.db_connection = mysql.connector.connect(
                user=Config.MYSQL_DB_USER,
                password=Config.MYSQL_DB_PASSWD,
                host=Config.MYSQL_DB_HOST,
                database=Config.MYSQL_DB_NAME)
        elif not DBConnect.db_connection.is_connected():
            DBConnect.db_connection.reconnect()

        if not DBConnect.db_connection.is_connected():
            raise RuntimeError('Couldn\'t connect to the MySQL database.')

        self.cursor = DBConnect.db_connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.commit:
            DBConnect.db_connection.commit()
        self.cursor.close()


def get_all_users(discord_id=None, discord_name=None, twitch_name=None, rtmp_name=None):
    with DBConnect(commit=False) as cursor:
        params = tuple()
        if discord_id is not None:
            params += (int(discord_id),)
        if discord_name is not None:
            params += (discord_name,)
        if twitch_name is not None:
            params += (twitch_name,)
        if rtmp_name is not None:
            params += (rtmp_name,)

        if discord_id is None and discord_name is None and twitch_name is None and rtmp_name is None:
            where_query = 'TRUE'
        else:
            where_query = ''
            if discord_id is not None:
                where_query += ' AND discord_id=%s'
            if discord_name is not None:
                where_query += ' AND name=%s'
            if twitch_name is not None:
                where_query += ' AND twitch_name=%s'
            if rtmp_name is not None:
                where_query += ' AND rtmp_name=%s'
            where_query = where_query[5:]

        cursor.execute(
            "SELECT discord_id, name, twitch_name, rtmp_name, timezone, user_info, daily_alert, race_alert "
            "FROM user_data "
            "WHERE {0}".format(where_query),
            params)
        return cursor.fetchall()


def get_discord_id(discord_name):
    with DBConnect(commit=False) as cursor:
        params = (discord_name,)
        cursor.execute(
            "SELECT discord_id "
            "FROM user_data "
            "WHERE name=%s",
            params)
        return int(cursor.fetchone()[0]) if cursor.rowcount else None


def set_prefs(discord_id, user_prefs):
    new_user_prefs = get_prefs(discord_id=discord_id).merge_prefs(user_prefs)

    with DBConnect(commit=True) as cursor:
        params = (discord_id, new_user_prefs.daily_alert, new_user_prefs.race_alert)
        cursor.execute(
            "INSERT INTO user_data "
            "(discord_id, daily_alert, race_alert) "
            "VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE "
            "daily_alert=VALUES(daily_alert), "
            "race_alert=VALUES(race_alert)", params)


def get_prefs(discord_id):
    with DBConnect(commit=False) as cursor:
        params = (discord_id,)
        cursor.execute(
            "SELECT daily_alert, race_alert "
            "FROM user_data "
            "WHERE discord_id=%s",
            params)
        prefs_row = cursor.fetchone()
        cursor.close()
        user_prefs = UserPrefs()
        user_prefs.daily_alert = bool(prefs_row[0])
        user_prefs.race_alert = bool(prefs_row[1])
        return user_prefs


def get_all_ids_matching_prefs(user_prefs):
    if user_prefs.is_empty:
        return []

    where_query = ''
    if user_prefs.daily_alert is not None:
        where_query += ' AND daily_alert={0}'.format('TRUE' if user_prefs.daily_alert else 'FALSE')
    if user_prefs.race_alert is not None:
        where_query += ' AND race_alert={0}'.format('TRUE' if user_prefs.race_alert else 'FALSE')
    where_query = where_query[5:]

    with DBConnect(commit=False) as cursor:
        cursor.execute(
            "SELECT discord_id "
            "FROM user_data "
            "WHERE {0}".format(where_query))
        to_return = []
        for row in cursor.fetchall():
            to_return.append(int(row[0]))
        return to_return


def record_race(race):
    with DBConnect(commit=True) as cursor:
        cursor.execute(
            "SELECT race_id FROM race_data ORDER BY race_id DESC LIMIT 1")
        new_raceid = 0
        for row in cursor:
            new_raceid = row[0] + 1
            break

        race_params = (new_raceid,
                       race.start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                       race.race_info.character_str,
                       race.race_info.descriptor,
                       race.race_info.flags,
                       race.race_info.seed,
                       race.race_info.seeded,
                       race.race_info.amplified,
                       race.race_info.condor_race,
                       race.race_info.private_race,)

        cursor.execute(
            "INSERT INTO race_data "
            "(race_id, timestamp, character_name, descriptor, flags, seed, seeded, amplified, condor, private) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            race_params)

        racer_list = []
        max_time = 0
        for racer in race.racers:
            racer_list.append(racer)
            if racer.is_finished:
                max_time = max(racer.time, max_time)
        max_time += 1

        racer_list.sort(key=lambda r: r.time if r.is_finished else max_time)

        rank = 1
        for racer in racer_list:
            racer_params = (new_raceid, racer.id, racer.time, rank, racer.igt, racer.comment, racer.level)
            cursor.execute(
                "INSERT INTO racer_data "
                "(race_id, discord_id, time, rank, igt, comment, level) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                racer_params)
            if racer.is_finished:
                rank += 1

            user_params = (racer.id, racer.name)
            cursor.execute(
                'INSERT INTO user_data '
                '(discord_id, name) '
                'VALUES (%s,%s) '
                'ON DUPLICATE KEY UPDATE '
                'discord_id=VALUES(discord_id), '
                'name=VALUES(name)',
                user_params)


def register_all_users(members):
    with DBConnect(commit=True) as cursor:
        for member in members:
            params = (member.id, member.display_name,)
            cursor.execute(
                "INSERT INTO user_data "
                "(discord_id, name) "
                "VALUES (%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "name=VALUES(name)",
                params)


def register_user(member):
    with DBConnect(commit=True) as cursor:
        params = (member.id, member.name,)
        cursor.execute(
            "INSERT INTO user_data "
            "(discord_id, name) "
            "VALUES (%s,%s) "
            "ON DUPLICATE KEY UPDATE "
            "name=VALUES(name)",
            params)


def get_daily_seed(daily_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (daily_id, daily_type,)
        cursor.execute(
            "SELECT seed "
            "FROM daily_data "
            "WHERE daily_id=%s AND type=%s",
            params)
        return cursor.fetchall()


def get_daily_times(daily_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (daily_id, daily_type,)
        cursor.execute(
            "SELECT user_data.name,daily_races.level,daily_races.time "
            "FROM daily_races INNER JOIN user_data ON daily_races.discord_id=user_data.discord_id "
            "WHERE daily_races.daily_id=%s AND daily_races.type=%s "
            "ORDER BY daily_races.level DESC, daily_races.time ASC",
            params)
        return cursor.fetchall()


def has_submitted_daily(discord_id, daily_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (discord_id, daily_id, daily_type,)
        cursor.execute(
            "SELECT discord_id "
            "FROM daily_races "
            "WHERE discord_id=%s AND daily_id=%s AND type=%s AND level != -1",
            params)
        return cursor.rowcount > 0


def has_registered_daily(discord_id, daily_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (discord_id, daily_id, daily_type,)
        cursor.execute(
            "SELECT discord_id "
            "FROM daily_races "
            "WHERE discord_id=%s AND daily_id=%s AND type=%s",
            params)
        return cursor.rowcount > 0


def register_daily(discord_id, daily_id, daily_type, level=-1, time=-1):
    with DBConnect(commit=True) as cursor:
        params = (discord_id, daily_id, daily_type, level, time,)
        cursor.execute(
            "INSERT INTO daily_races "
            "(discord_id, daily_id, type, level, time) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE "
            "discord_id=VALUES(discord_id), "
            "daily_id=VALUES(daily_id), "
            "type=VALUES(type), "
            "level=VALUES(level), "
            "time=VALUES(time)",
            params)


def registered_daily(discord_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (discord_id, daily_type,)
        cursor.execute(
            "SELECT daily_id "
            "FROM daily_races "
            "WHERE discord_id=%s AND type=%s "
            "ORDER BY daily_id DESC "
            "LIMIT 1",
            params)
        return int(cursor.fetchone()[0]) if cursor.rowcount else 0


def submitted_daily(discord_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (discord_id, daily_type,)
        cursor.execute(
            "SELECT daily_id "
            "FROM daily_races "
            "WHERE discord_id=%s AND type=%s AND level != -1"
            "ORDER BY daily_id DESC "
            "LIMIT 1",
            params)
        return int(cursor.fetchone()[0]) if cursor.rowcount else 0


def delete_from_daily(discord_id, daily_id, daily_type):
    with DBConnect(commit=True) as cursor:
        params = (discord_id, daily_id, daily_type,)
        cursor.execute(
            "UPDATE daily_races "
            "SET level=-1 "
            "WHERE discord_id=%s AND daily_id=%s AND type=%s",
            params)


def create_daily(daily_id, daily_type, seed, message_id=0):
    with DBConnect(commit=True) as cursor:
        params = (daily_id, daily_type, seed, message_id)
        cursor.execute(
            "INSERT INTO daily_data "
            "(daily_id, type, seed, msg_id) "
            "VALUES (%s,%s,%s,%s)",
            params)


def register_daily_message(daily_id, daily_type, message_id):
    with DBConnect(commit=True) as cursor:
        params = (message_id, daily_id, daily_type,)
        cursor.execute(
            "UPDATE daily_data "
            "SET msg_id=%s "
            "WHERE daily_id=%s AND type=%s",
            params)


def get_daily_message_id(daily_id, daily_type):
    with DBConnect(commit=False) as cursor:
        params = (daily_id, daily_type,)
        cursor.execute(
            "SELECT msg_id "
            "FROM daily_data "
            "WHERE daily_id=%s AND type=%s",
            params)
        return int(cursor.fetchone()[0]) if cursor.rowcount else 0


def get_allzones_race_numbers(discord_id, amplified):
    with DBConnect(commit=False) as cursor:
        params = (discord_id,)
        cursor.execute(
            "SELECT race_data.character_name, COUNT(*) as num "
            "FROM racer_data "
            "JOIN race_data ON race_data.race_id = racer_data.race_id "
            "WHERE racer_data.discord_id = %s "
            "AND race_data.descriptor = 'All-zones' " +
            ("AND race_data.amplified " if amplified else "AND NOT race_data.amplified ") +
            "AND race_data.seeded AND NOT race_data.private "
            "GROUP BY race_data.character_name, race_data.descriptor, race_data.flags "
            "ORDER BY num DESC",
            params)
        return cursor.fetchall()


def get_all_racedata(discord_id, char_name, amplified):
    with DBConnect(commit=False) as cursor:
        params = (discord_id, char_name)
        cursor.execute(
            "SELECT racer_data.time, racer_data.level "
            "FROM racer_data "
            "JOIN race_data ON race_data.race_id = racer_data.race_id "
            "WHERE racer_data.discord_id = %s "
            "AND race_data.character_name = %s "
            "AND race_data.descriptor = 'All-zones' " +
            ("AND race_data.amplified " if amplified else "AND NOT race_data.amplified ") +
            "AND race_data.seeded AND NOT race_data.private ",
            params)
        return cursor.fetchall()


def get_fastest_times_leaderboard(character_name, amplified, limit):
    with DBConnect(commit=False) as cursor:
        params = (character_name, limit,)
        cursor.execute(
            "SELECT user_data.name, racer_data.time, race_data.seed, race_data.timestamp "
            "FROM racer_data "
            "INNER JOIN "
            "( "
            "    SELECT discord_id, MIN(time) AS min_time "
            "    FROM racer_data INNER JOIN race_data ON race_data.race_id = racer_data.race_id "
            "    WHERE "
            "        time > 0 "
            "        AND level = -2 "
            "        AND race_data.character_name=%s "
            "        AND race_data.descriptor='All-zones' "
            "        AND race_data.seeded " +
            "        AND {0}race_data.amplified ".format('' if amplified else 'NOT ') +
            "        AND NOT race_data.private "
            "    Group By discord_id "
            ") rd1 On rd1.discord_id = racer_data.discord_id "
            "INNER JOIN user_data ON user_data.discord_id = racer_data.discord_id "
            "INNER JOIN race_data ON race_data.race_id = racer_data.race_id "
            "WHERE racer_data.time = rd1.min_time "
            "ORDER BY racer_data.time ASC "
            "LIMIT %s",
            params)
        return cursor.fetchall()


def get_most_races_leaderboard(character_name, limit):
    with DBConnect(commit=False) as cursor:
        params = (character_name, character_name, limit,)
        cursor.execute(
            "SELECT "
            "    user_name, "
            "    num_predlc + num_postdlc as total, "
            "    num_predlc, "
            "    num_postdlc "
            "FROM "
            "( "
            "    SELECT "
            "        user_data.name as user_name, "
            "        SUM( "
            "                IF( "
            "                race_data.character_name=%s "
            "                AND race_data.descriptor='All-zones' "
            "                AND NOT race_data.amplified "
            "                AND NOT race_data.private, "
            "                1, 0 "
            "                ) "
            "        ) as num_predlc, "
            "        SUM( "
            "                IF( "
            "                race_data.character_name=%s "
            "                AND race_data.descriptor='All-zones' "
            "                AND race_data.amplified "
            "                AND NOT race_data.private, "
            "                1, 0 "
            "                ) "
            "        ) as num_postdlc "
            "    FROM racer_data "
            "    JOIN user_data ON user_data.discord_id = racer_data.discord_id "
            "    JOIN race_data ON race_data.race_id = racer_data.race_id "
            "    GROUP BY user_data.name "
            ") tbl1 "
            "ORDER BY total DESC "
            "LIMIT %s",
            params)
        return cursor.fetchall()


def get_largest_race_number(discord_id):
    with DBConnect(commit=False) as cursor:
        params = (discord_id,)
        cursor.execute(
            "SELECT race_id "
            "FROM racer_data "
            "WHERE discord_id = %s "
            "ORDER BY race_id DESC "
            "LIMIT 1",
            params)
        return int(cursor.fetchone()[0]) if cursor.rowcount else 0


def set_timezone(discord_id, timezone):
    with DBConnect(commit=True) as cursor:
        params = (timezone, discord_id,)
        cursor.execute(
            "UPDATE user_data "
            "SET timezone=%s "
            "WHERE discord_id=%s",
            params)


def set_rtmp(discord_id, rtmp_name):
    with DBConnect(commit=True) as cursor:
        params = (rtmp_name, discord_id,)
        cursor.execute(
            "UPDATE user_data "
            "SET rtmp_name=%s "
            "WHERE discord_id=%s",
            params)


def set_twitch(discord_id, twitch_name):
    with DBConnect(commit=True) as cursor:
        params = (twitch_name, discord_id,)
        cursor.execute(
            "UPDATE user_data "
            "SET twitch_name=%s "
            "WHERE discord_id=%s",
            params)


def set_user_info(discord_id, user_info):
    with DBConnect(commit=True) as cursor:
        params = (user_info, discord_id,)
        cursor.execute(
            "UPDATE user_data "
            "SET user_info=%s "
            "WHERE discord_id=%s",
            params)


def set_rating(discord_id, rating):
    with DBConnect(commit=True) as cursor:
        params = (rating.mu, rating.sigma, discord_id,)
        cursor.execute(
            "INSERT INTO ladder_data "
            "(discord_id, trueskill_mu, trueskill_sigma) "
            "VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE "
            "trueskill_mu=VALUES(trueskill_mu), "
            "trueskill_sigma=VALUES(trueskill_sigma)",
            params)


def get_rating(discord_id):
    with DBConnect(commit=False) as cursor:
        params = (discord_id,)
        cursor.execute(
            "SELECT trueskill_mu, trueskill_sigma "
            "FROM ladder_data "
            "WHERE discord_id=%s",
            params)
        row = cursor.fetchone()
        return create_rating(mu=int(row[0]), sigma=int(row[1])) if row is not None else None