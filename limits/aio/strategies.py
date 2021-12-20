"""
Asynchronous rate limiting strategies
"""

from abc import ABC, abstractmethod
from typing import Tuple
from typing import Iterable
import weakref

from limits import RateLimitItem
from limits.aio.storage import Storage


class RateLimiter(ABC):
    def __init__(self, storage: Storage):
        self.storage = weakref.ref(storage)

    @abstractmethod
    async def hit(self, item: RateLimitItem, *identifiers: Iterable[str]) -> bool:
        """
        Consume the rate limit

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        raise NotImplementedError

    @abstractmethod
    async def test(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Check if the rate limit can be consumed

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        raise NotImplementedError

    @abstractmethod
    async def get_window_stats(
        self, item: RateLimitItem, *identifiers
    ) -> Tuple[int, int]:
        """
        Query the reset time and remaining amount for the limit

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        :return: (reset time, remaining))
        """
        raise NotImplementedError

    async def clear(self, item: RateLimitItem, *identifiers):
        return await self.storage().clear(item.key_for(*identifiers))


class MovingWindowRateLimiter(RateLimiter):
    """
    Reference: :ref:`strategies:moving window`
    """

    def __init__(self, storage: Storage) -> None:
        if not (
            hasattr(storage, "acquire_entry") or hasattr(storage, "get_moving_window")
        ):
            raise NotImplementedError(
                "MovingWindowRateLimiting is not implemented for storage "
                "of type %s" % storage.__class__
            )
        super(MovingWindowRateLimiter, self).__init__(storage)

    async def hit(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Consume the rate limit

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        return await self.storage().acquire_entry(  # type: ignore
            item.key_for(*identifiers), item.amount, item.get_expiry()
        )

    async def test(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Check if the rate limit can be consumed

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        res = await self.storage().get_moving_window(  # type: ignore
            item.key_for(*identifiers),
            item.amount,
            item.get_expiry(),
        )
        amount = res[1]
        return amount < item.amount

    async def get_window_stats(
        self, item: RateLimitItem, *identifiers
    ) -> Tuple[int, int]:
        """
        returns the number of requests remaining within this limit.

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        :return: (reset time, remaining)
        """
        window_start, window_items = await self.storage().get_moving_window(  # type: ignore
            item.key_for(*identifiers), item.amount, item.get_expiry()
        )
        reset = window_start + item.get_expiry()
        return (reset, item.amount - window_items)


class FixedWindowRateLimiter(RateLimiter):
    """
    Reference: :ref:`strategies:fixed window`
    """

    async def hit(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Consume the rate limit

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        return (
            await self.storage().incr(item.key_for(*identifiers), item.get_expiry())
            <= item.amount
        )

    async def test(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Check if the rate limit can be consumed

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        return await self.storage().get(item.key_for(*identifiers)) < item.amount

    async def get_window_stats(
        self, item: RateLimitItem, *identifiers
    ) -> Tuple[int, int]:
        """
        Query the reset time and remaining amount for the limit

        :param item: the rate limit item
        :param identifiers: variable list of strings to uniquely identify the
         limit
        :return: reset time, remaining
        """
        remaining = max(
            0,
            item.amount - await self.storage().get(item.key_for(*identifiers)),
        )
        reset = await self.storage().get_expiry(item.key_for(*identifiers))
        return (reset, remaining)


class FixedWindowElasticExpiryRateLimiter(FixedWindowRateLimiter):
    """
    Reference: :ref:`strategies:fixed window with elastic expiry`
    """

    async def hit(self, item: RateLimitItem, *identifiers) -> bool:
        """
        Consume the rate limit

        :param item: a :class:`limits.limits.RateLimitItem` instance
        :param identifiers: variable list of strings to uniquely identify the
         limit
        """
        amount = await self.storage().incr(
            item.key_for(*identifiers), item.get_expiry(), True
        )
        return amount <= item.amount


STRATEGIES = {
    "fixed-window": FixedWindowRateLimiter,
    "fixed-window-elastic-expiry": FixedWindowElasticExpiryRateLimiter,
    "moving-window": MovingWindowRateLimiter,
}