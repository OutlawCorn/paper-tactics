from dataclasses import dataclass, field
from random import randint
from typing import Final, Iterable, cast

from paper_tactics.entities.cell import Cell
from paper_tactics.entities.game_bot import GameBot
from paper_tactics.entities.game_preferences import GamePreferences
from paper_tactics.entities.game_view import GameView
from paper_tactics.entities.player import Player
from paper_tactics.entities.player_view import PlayerView


@dataclass
class Game:
    id: Final[str] = ""
    preferences: Final[GamePreferences] = field(default_factory=GamePreferences)
    turns_left: int = 0
    active_player: Player = field(default_factory=Player)
    passive_player: Player = field(default_factory=Player)
    trenches: frozenset[Cell] = frozenset()

    def init(self) -> None:
        assert self.active_player.id != self.passive_player.id

        self._init_players()
        self.trenches = frozenset(self._generate_trenches())
        self._rebuild_reachable_set(self.active_player, self.passive_player)
        self._rebuild_reachable_set(self.passive_player, self.active_player)
        self.turns_left = self.preferences.turn_count

    def get_view(self, player_id: str) -> GameView:
        assert player_id in (self.active_player.id, self.passive_player.id)

        if player_id == self.active_player.id:
            me = self.active_player
            opponent = self.passive_player
        else:
            me = self.passive_player
            opponent = self.active_player

        if self.preferences.is_visibility_applied and me.can_win and opponent.can_win:
            opponent_units = opponent.units.intersection(me.visible_opponent)
            opponent_walls = opponent.walls.intersection(me.visible_opponent)
            trenches = self.trenches.intersection(me.visible_terrain)

            visible_opponent = Player(
                units=opponent_units,
                walls=opponent_walls,
            )
            self._rebuild_reachable_set(visible_opponent, me)
            opponent_reachable = visible_opponent.reachable
        else:
            opponent_units = opponent.units
            opponent_walls = opponent.walls
            opponent_reachable = opponent.reachable
            trenches = self.trenches

        return GameView(
            id=self.id,
            turns_left=self.turns_left,
            my_turn=(me == self.active_player),
            me=PlayerView(
                units=cast(frozenset[Cell], me.units),
                walls=cast(frozenset[Cell], me.walls),
                reachable=cast(frozenset[Cell], me.reachable),
                view_data=me.view_data.copy(),
                is_gone=me.is_gone,
                is_defeated=me.is_defeated,
            ),
            opponent=PlayerView(
                units=cast(frozenset[Cell], opponent_units),
                walls=cast(frozenset[Cell], opponent_walls),
                reachable=cast(frozenset[Cell], opponent_reachable),
                view_data=opponent.view_data.copy(),
                is_gone=opponent.is_gone,
                is_defeated=opponent.is_defeated,
            ),
            trenches=trenches,
            preferences=self.preferences,
        )

    def make_turn(self, player_id: str, cell: Cell) -> None:
        if (
            player_id != self.active_player.id
            or cell not in self.active_player.reachable
            or not all(
                player.can_win for player in (self.active_player, self.passive_player)
            )
        ):
            raise IllegalTurnException(self.id, player_id, cell)

        self._make_turn(cell, self.active_player, self.passive_player)
        self._decrement_turns()

    def _decrement_turns(self) -> None:
        self.turns_left -= 1
        if not self.turns_left:
            if self.preferences.is_deathmatch:
                self.preferences.turn_count += 1
            self.turns_left = self.preferences.turn_count
            if self.preferences.is_against_bot:
                game_bot = GameBot()
                for _ in range(self.preferences.turn_count):
                    if not self.passive_player.reachable:
                        self.passive_player.is_defeated = True
                        break
                    cell = game_bot.make_turn(self.get_view(self.passive_player.id), self.turns_left)
                    assert cell in self.passive_player.reachable, f"{cell} is an invalid turn"
                    self._make_turn(cell, self.passive_player, self.active_player)
                    self.turns_left -= 1
                if self.preferences.is_deathmatch:
                    self.preferences.turn_count += 1
                self.turns_left = self.preferences.turn_count
            else:
                self.active_player, self.passive_player = (
                    self.passive_player,
                    self.active_player,
                )
        if not self.active_player.reachable and not self.passive_player.is_defeated:
            self.active_player.is_defeated = True

    def _make_turn(self, cell: Cell, player: Player, opponent: Player) -> None:
        if cell in opponent.units:
            opponent.units.remove(cell)
            player.walls.add(cell)
            self._rebuild_reachable_set(opponent, player)
        elif cell in self.trenches:
            player.walls.add(cell)
            opponent.reachable.discard(cell)
        else:
            player.units.add(cell)
        self._rebuild_reachable_set(player, opponent)

    def _rebuild_reachable_set(self, player: Player, opponent: Player) -> None:
        player.reachable.clear()

        if self.preferences.is_visibility_applied:
            player.visible_opponent = {
                cell
                for cell in player.visible_opponent
                if cell in opponent.units or cell in opponent.walls
            }.union(cell for cell in opponent.walls if cell not in self.trenches)

        sources = player.units.copy()

        while True:
            new_sources = set()

            for source in sources:
                for cell in self.preferences.get_adjacent_cells(source):
                    if self.preferences.is_visibility_applied:
                        player.visible_opponent.add(cell)
                        if cell in self.trenches:
                            player.visible_terrain.add(cell)
                            player.visible_terrain.add(
                                self.preferences.get_symmetric_cell(cell)
                            )
                    if cell in sources:
                        continue
                    if cell in player.walls:
                        new_sources.add(cell)
                    elif cell not in opponent.walls and cell not in player.units:
                        player.reachable.add(cell)
            if not new_sources:
                break

            sources.update(new_sources)

    def _init_players(self) -> None:
        edge = self.preferences.size
        first_base_y = (
            randint(1, (edge + 1) // 2) if self.preferences.is_with_random_bases else 1
        )
        second_base_y = (
            randint(edge // 2 + 1, edge) if self.preferences.is_with_random_bases else 1
        )
        self.active_player.units.add((1, first_base_y))
        self.passive_player.units.add((edge, edge - first_base_y + 1))

        if self.preferences.is_double_base:
            self.active_player.units.add((1, second_base_y))
            self.passive_player.units.add((edge, edge - second_base_y + 1))

    def _generate_trenches(self) -> Iterable[Cell]:
        if not self.preferences.trench_density_percent:
            return

        size = self.preferences.size
        half = (size + 1) // 2

        for x in range(size):
            for y in range(half):
                if (
                    (y < half - 1 or x < half)
                    and (x + 1, y + 1) not in self.active_player.units
                    and (x + 1, y + 1) not in self.passive_player.units
                    and randint(1, 100) <= self.preferences.trench_density_percent
                ):
                    yield x + 1, y + 1
                    yield size - x, size - y


class IllegalTurnException(Exception):
    pass
