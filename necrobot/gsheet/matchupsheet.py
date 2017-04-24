import datetime
import unittest

from necrobot.gsheet.makerequest import make_request
from necrobot.gsheet.matchupsheetindexdata import MatchupSheetIndexData
from necrobot.gsheet.sheetcell import SheetCell
from necrobot.gsheet.sheetrange import SheetRange
from necrobot.gsheet.spreadsheets import Spreadsheets
from necrobot.match import matchutil
from necrobot.match.match import Match
from necrobot.match.matchinfo import MatchInfo
from necrobot.user import userutil
from necrobot.util import console


class MatchupSheet(object):
    """
    Represents a single worksheet with matchup & scheduling data.
    """

    def __init__(self, gsheet_id: str, wks_name: str = None):
        self.gsheet_id = gsheet_id
        self.wks_name = wks_name
        self.column_data = MatchupSheetIndexData(self.gsheet_id, self.wks_name)

    async def initialize(self):
        await self.column_data.initalize()

    async def get_matches(self, **kwargs):
        """Read racer names and match types from the GSheet; create corresponding matches.
        
        Parameters
        ----------
        kwargs:
            Parameters to be passed to matchutil.make_match for every match made.
        
        Returns
        -------
        list[Match]
            The list of created Matches.
        """

        matches = []
        with Spreadsheets() as spreadsheets:
            value_range = await self.column_data.get_values(spreadsheets)

            if 'values' not in value_range:
                return matches

            for row_values in value_range['values']:
                racer_1_name = row_values[self.column_data.racer_1].rstrip(' ')
                racer_2_name = row_values[self.column_data.racer_2].rstrip(' ')
                racer_1 = userutil.get_user(any_name=racer_1_name, register=True)
                racer_2 = userutil.get_user(any_name=racer_2_name, register=True)
                if racer_1 is None or racer_2 is None:
                    console.error('Couldn\'t find racers for match {0}-{1}.'.format(
                        racer_1_name, racer_2_name
                    ))
                    continue

                # type_str = row_values[self.column_data.match_type]  # TODO
                # tier = row_values[self.column_data.tier]  # TODO

                new_match = matchutil.make_match(
                    racer_1_id=racer_1.user_id,
                    racer_2_id=racer_2.user_id,
                    **kwargs
                )
                matches.append(new_match)
        return matches

    async def schedule_match(self, match: Match):
        """Write scheduling data for the match into the GSheet.
        
        Parameters
        ----------
        match: Match

        """
        row = await self._get_match_row(match)
        if row is None:
            return

        if match.suggested_time is None:
            value = ''
        else:
            value = match.suggested_time.strftime('%Y-%m-%d %H:%M:%S')

        await self._update_cell(
            row=row,
            col=self.column_data.date,
            value=value,
            raw_input=False
        )

    async def add_vod(self, match: Match, vod_link: str):
        """Add a vod link to the GSheet.
        
        Parameters
        ----------
        match: Match
            The match to add a link for.
        vod_link: str
            The full URL of the VOD.
        """
        row = await self._get_match_row(match)
        if row is None:
            return
        if self.column_data.vod is None:
            console.error('No Vod column on GSheet.')
            return

        await self._update_cell(
            row=row,
            col=self.column_data.vod,
            value=vod_link,
            raw_input=False
        )

    async def add_cawmentary(self, match: Match):
        """Add a cawmentator to the GSheet.
        
        Parameters
        ----------
        match: Match
            The match to add cawmentary for.
        """
        row = await self._get_match_row(match)
        if row is None:
            return
        if self.column_data.cawmentary is None:
            console.error('No Cawmentary column on GSheet.')
            return

        await self._update_cell(
            row=row,
            col=self.column_data.cawmentary,
            value=match.cawmentator.twitch_name,
            raw_input=False
        )

    async def record_score(self, match: Match, winner: str, winner_wins: int, loser_wins: int):
        """Record the winner and final score of the match.
        
        Parameters
        ----------
        match: Match
        winner: str
        winner_wins: int
        loser_wins: int
        """
        row = await self._get_match_row(match)
        if row is None:
            return
        if self.column_data.winner is None:
            console.error('No "Winner" column on GSheet.')
            return
        if self.column_data.score is None:
            console.error('No "Score" column on GSheet.')
            return
        if self.column_data.score != self.column_data.winner + 1:
            console.error('Can\'t record score; algorithm assumes the score column is one right of the winner column.')
            return

        sheet_range = SheetRange(
            ul_cell=(row, self.column_data.winner,),
            lr_cell=(row, self.column_data.score,),
            wks_name=self.wks_name
        )
        self._update_cells(
            sheet_range=sheet_range,
            values=[[winner, '{0}-{1}'.format(winner_wins, loser_wins)]],
            raw_input=False
        )

    async def _get_match_row(self, match: Match) -> int or None:
        """Get the index of the row containing the Match.
        
        Parameters
        ----------
        match: Match

        Returns
        -------
        Optional[int]
            The row index (from 0) of the Match, or None if nothing found.
        """
        with Spreadsheets() as spreadsheets:
            value_range = await self.column_data.get_values(spreadsheets)
            if 'values' not in value_range:
                return None

            match_names = {match.racer_1.rtmp_name.lower(), match.racer_2.rtmp_name.lower()}

            values = value_range['values']
            for row, row_values in enumerate(values):
                gsheet_names = {
                    row_values[self.column_data.racer_1].lower().rstrip(' '),
                    row_values[self.column_data.racer_2].lower().rstrip(' ')
                }
                if gsheet_names == match_names:
                    return row
            console.error('Couldn\'t find match {0}-{1} on the GSheet.'.format(
                match.racer_1.rtmp_name,
                match.racer_2.rtmp_name
            ))
            return None

    async def _update_cell(self, row: int, col: int, value: str, raw_input: bool = True) -> bool:
        """Update a single cell.
        
        Parameters
        ----------
        row: int
            The row index (begins at 0).
        col: int
            The column index (begins at 0).
        value: str
            The cell value.
        raw_input: bool
            If False, GSheets will auto-format the input.

        Returns
        -------
        bool
            True if the update was successful.
        """
        if not self.column_data.valid:
            raise RuntimeError('Trying to update a cell on an invalid MatchupSheet.')

        row += self.column_data.header_row + 1
        col += self.column_data.min_column
        range_str = str(SheetCell(row, col, wks_name=self.wks_name))
        value_input_option = 'RAW' if raw_input else 'USER_ENTERED'
        value_range_body = {'values': [[value]]}
        with Spreadsheets() as spreadsheets:
            request = spreadsheets.values().update(
                spreadsheetId=self.gsheet_id,
                range=range_str,
                valueInputOption=value_input_option,
                body=value_range_body
            )
            response = await make_request(request)
            return response is not None

    async def _update_cells(self, sheet_range: SheetRange, values: list, raw_input=True) -> bool:
        """Update all cells in a range.
        
        Parameters
        ----------
        sheet_range: SheetRange
            The range to update.
        values: list[list[str]]
            An array of values; one of the inner lists is a row, so values[i][j] is the ith row, jth column value.
        raw_input
            If False, GSheets will auto-format the input.
            
        Returns
        -------
        bool
            True if the update was successful.
        """
        if not self.column_data.valid:
            raise RuntimeError('Trying to update cells on an invalid MatchupSheet.')

        sheet_range = sheet_range.get_offset_by(self.column_data.header_row + 1, self.column_data.min_column)
        range_str = str(sheet_range)
        value_input_option = 'RAW' if raw_input else 'USER_ENTERED'
        value_range_body = {'values': values}
        with Spreadsheets() as spreadsheets:
            request = spreadsheets.values().update(
                spreadsheetId=self.gsheet_id,
                range=range_str,
                valueInputOption=value_input_option,
                body=value_range_body
            )
            response = await make_request(request)
            return response is not None


# class TestMatchupSheet(unittest.TestCase):
#     the_gsheet_id = '1JbwqUsX1ibHVVtcRVpOmaFJcfQz2ncBAOwb1nV1PsPA'
#
#     def setUp(self):
#         self.sheet_1 = MatchupSheet(gsheet_id=TestMatchupSheet.the_gsheet_id, wks_name='Sheet1')
#         self.sheet_2 = MatchupSheet(gsheet_id=TestMatchupSheet.the_gsheet_id, wks_name='Sheet2')
#         self.match_1 = self._get_match(
#             r1_name='yjalexis',
#             r2_name='macnd',
#             time=datetime.datetime(year=2069, month=4, day=20, hour=4, minute=20),
#             cawmentator_name='incnone'
#         )
#         self.match_2 = self._get_match(
#             r1_name='elad',
#             r2_name='wilarseny',
#             time=None,
#             cawmentator_name=None
#         )
#
#         self.assertEqual(self.match_1.cawmentator.rtmp_name, 'incnone')
#
#     def test_init(self):
#         col_data = self.sheet_1.column_data
#         self.assertEqual(col_data.tier, 1)
#         self.assertEqual(col_data.racer_1, 2)
#         self.assertEqual(col_data.racer_2, 3)
#         self.assertEqual(col_data.date, 4)
#         self.assertEqual(col_data.cawmentary, 5)
#         self.assertEqual(col_data.winner, 6)
#         self.assertEqual(col_data.score, 7)
#         self.assertEqual(col_data.vod, 10)
#         self.assertEqual(col_data.header_row, 3)
#         self.assertEqual(col_data.footer_row, 6)
#
#         bad_col_data = self.sheet_2.column_data
#         self.assertIsNone(bad_col_data.header_row)
#
#     @unittest.skip('slow')
#     def test_get_matches(self):
#         matches = self.sheet_1.get_matches()
#         self.assertEqual(len(matches), 2)
#         match = matches[0]
#         self.assertEqual(match.racer_1.rtmp_name, 'yjalexis')
#         self.assertEqual(match.racer_2.rtmp_name, 'macnd')
#
#     def test_schedule(self):
#         self.assertRaises(RuntimeError, self.sheet_2._update_cell, 4, 4, 'Test update')
#         self.sheet_1.schedule_match(self.match_1)
#         self.sheet_1.schedule_match(self.match_2)
#
#     def test_record_score(self):
#         self.sheet_1.record_score(self.match_1, 'macnd', 2, 1)
#         self.sheet_1.record_score(self.match_2, 'elad', 3, 1)
#
#     def test_update_cawmentary_and_vod(self):
#         self.sheet_1.add_cawmentary(self.match_1)
#         self.sheet_1.add_vod(self.match_1, 'http://www.youtube.com/')
#
#     def _get_match(self,
#                    r1_name: str,
#                    r2_name: str,
#                    time: datetime.datetime or None,
#                    cawmentator_name: str or None
#                    ) -> Match:
#         racer_1 = userutil.get_user(any_name=r1_name, register=False)
#         racer_2 = userutil.get_user(any_name=r2_name, register=False)
#         cawmentator = userutil.get_user(rtmp_name=cawmentator_name)
#         self.assertIsNotNone(racer_1)
#         self.assertIsNotNone(racer_2)
#         if cawmentator_name is not None:
#             self.assertIsNotNone(cawmentator)
#         cawmentator_id = cawmentator.discord_id if cawmentator is not None else None
#
#         match_info = MatchInfo(ranked=True)
#         return matchutil.make_match(
#             racer_1_id=racer_1.user_id,
#             racer_2_id=racer_2.user_id,
#             match_info=match_info,
#             suggested_time=time,
#             cawmentator_id=cawmentator_id,
#             register=False
#         )
