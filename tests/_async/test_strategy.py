import threading
import time

import pymemcache.client
import pytest
import aredis

# import redis.sentinel
# import rediscluster
import hiro

from limits.limits import RateLimitItemPerSecond, RateLimitItemPerMinute
from limits._async.storage import (
    AsyncMemoryStorage,
    AsyncRedisStorage,
    # AsyncMemcachedStorage,
    # AsyncRedisSentinelStorage,
)
from limits._async.strategies import (
    AsyncMovingWindowRateLimiter,
    AsyncFixedWindowElasticExpiryRateLimiter,
    AsyncFixedWindowRateLimiter,
)
from tests import skip_if_pypy


@pytest.mark.asynchronous
class TestAsyncWindow:
    def setup_method(self, method):
        pymemcache.client.Client(("localhost", 22122)).flush_all()
        # aredis.StrictRedis.from_url("aredis://localhost:7379").flushall()
        # aredis.StrictRedis.from_url(
        # "aredis://:sekret@localhost:7389"
        # ).flushall()
        # aredis.sentinel.Sentinel([("localhost", 26379)]).master_for(
        # "localhost-redis-sentinel"
        # ).flushall()
        # rediscluster.RedisCluster("localhost", 7000).flushall()

    @pytest.mark.asyncio
    async def test_fixed_window(self):
        storage = AsyncMemoryStorage()
        limiter = AsyncFixedWindowRateLimiter(storage)
        with hiro.Timeline().freeze() as timeline:
            start = int(time.time())
            limit = RateLimitItemPerSecond(10, 2)
            assert all([await limiter.hit(limit) for _ in range(0, 10)])
            timeline.forward(1)
            assert not await limiter.hit(limit)
            assert (await limiter.get_window_stats(limit))[1] == 0
            assert (await limiter.get_window_stats(limit))[0] == start + 2
            timeline.forward(1)
            assert (await limiter.get_window_stats(limit))[1] == 10
            assert await limiter.hit(limit)

    @pytest.mark.asyncio
    async def test_fixed_window_with_elastic_expiry_in_memory(self):
        storage = AsyncMemoryStorage()
        limiter = AsyncFixedWindowElasticExpiryRateLimiter(storage)
        with hiro.Timeline().freeze() as timeline:
            start = int(time.time())
            limit = RateLimitItemPerSecond(10, 2)
            assert all([await limiter.hit(limit) for _ in range(0, 10)])
            timeline.forward(1)
            assert not await limiter.hit(limit)
            assert (await limiter.get_window_stats(limit))[1] == 0
            # three extensions to the expiry
            assert (await limiter.get_window_stats(limit))[0] == start + 3
            timeline.forward(1)
            assert not await limiter.hit(limit)
            timeline.forward(3)
            start = int(time.time())
            assert await limiter.hit(limit)
            assert (await limiter.get_window_stats(limit))[1] == 9
            assert (await limiter.get_window_stats(limit))[0] == start + 2

    @pytest.mark.skip("not implemented yet")
    @pytest.mark.asyncio
    async def test_fixed_window_with_elastic_expiry_memcache(self):
        storage = AsyncMemcachedStorage("memcached://localhost:22122")
        limiter = AsyncFixedWindowElasticExpiryRateLimiter(storage)
        limit = RateLimitItemPerSecond(10, 2)
        assert all([await limiter.hit(limit) for _ in range(0, 10)])
        time.sleep(1)
        assert not await limiter.hit(limit)
        time.sleep(1)
        assert not await limiter.hit(limit)

    @pytest.mark.skip("not implemented yet")
    @pytest.mark.asyncio
    async def test_fixed_window_with_elastic_expiry_memcache_concurrency(self):
        storage = AsyncMemcachedStorage("memcached://localhost:22122")
        limiter = AsyncFixedWindowElasticExpiryRateLimiter(storage)
        start = int(time.time())
        limit = RateLimitItemPerSecond(10, 2)

        async def _c():
            for i in range(0, 5):
                await limiter.hit(limit)

        t1, t2 = threading.Thread(target=_c), threading.Thread(target=_c)
        t1.start(), t2.start()
        t1.join(), t2.join()
        assert await limiter.get_window_stats(limit)[1] == 0
        assert (
            start + 2 <= (await limiter.get_window_stats(limit))[0] <= start + 3
        )
        assert storage.get(limit.key_for()) == 10

    @pytest.mark.asyncio
    async def test_fixed_window_with_elastic_expiry_redis(self):
        await aredis.StrictRedis.from_url("aredis://localhost:7379").flushall()
        storage = AsyncRedisStorage("aredis://localhost:7379")
        limiter = AsyncFixedWindowElasticExpiryRateLimiter(storage)
        limit = RateLimitItemPerSecond(10, 2)
        for _ in range(0, 10):
            assert await limiter.hit(limit)
        time.sleep(1)
        assert not await limiter.hit(limit)
        time.sleep(1)
        assert not await limiter.hit(limit)
        assert (await limiter.get_window_stats(limit))[1] == 0

    @pytest.mark.skip("not implemented yet")
    @pytest.mark.asyncio
    async def test_fixed_window_with_elastic_expiry_redis_sentinel(self):
        storage = AsyncRedisSentinelStorage(
            "redis+sentinel://localhost:26379",
            service_name="localhost-redis-sentinel",
        )
        limiter = AsyncFixedWindowElasticExpiryRateLimiter(storage)
        limit = RateLimitItemPerSecond(10, 2)
        assert all([await limiter.hit(limit) for _ in range(0, 10)])
        time.sleep(1)
        assert not await limiter.hit(limit)
        time.sleep(1)
        assert not await limiter.hit(limit)
        assert (await limiter.get_window_stats(limit))[1] == 0

    @pytest.mark.asyncio
    async def test_moving_window_in_memory(self):
        storage = AsyncMemoryStorage()
        limiter = AsyncMovingWindowRateLimiter(storage)
        with hiro.Timeline().freeze() as timeline:
            limit = RateLimitItemPerMinute(10)
            for i in range(0, 5):
                assert await limiter.hit(limit)
                assert await limiter.hit(limit)
                assert (await limiter.get_window_stats(limit))[1] == 10 - (
                    (i + 1) * 2
                )
                timeline.forward(10)
            assert (await limiter.get_window_stats(limit))[1] == 0
            assert not await limiter.hit(limit)
            timeline.forward(20)
            assert (await limiter.get_window_stats(limit))[1] == 2
            assert (await limiter.get_window_stats(limit))[0] == int(
                time.time() + 30
            )
            timeline.forward(31)
            assert (await limiter.get_window_stats(limit))[1] == 10

    @skip_if_pypy
    @pytest.mark.asyncio
    async def test_moving_window_redis(self):
        await aredis.StrictRedis.from_url("aredis://localhost:7379").flushall()
        storage = AsyncRedisStorage("aredis://localhost:7379")
        limiter = AsyncMovingWindowRateLimiter(storage)
        limit = RateLimitItemPerSecond(10, 2)
        for i in range(0, 10):
            assert await limiter.hit(limit)
            assert (await limiter.get_window_stats(limit))[1] == 10 - (i + 1)
            time.sleep(2 * 0.095)
        assert not await limiter.hit(limit)
        time.sleep(0.4)
        assert await limiter.hit(limit)
        assert await limiter.hit(limit)
        assert (await limiter.get_window_stats(limit))[1] == 0

    @pytest.mark.skip("not implemented yet")
    @pytest.mark.asyncio
    async def test_moving_window_memcached(self):
        storage = AsyncMemcachedStorage("memcached://localhost:22122")
        self.assertRaises(
            NotImplementedError, AsyncMovingWindowRateLimiter, storage
        )

    @pytest.mark.asyncio
    async def test_test_fixed_window(self):
        with hiro.Timeline().freeze():
            store = AsyncMemoryStorage()
            limiter = AsyncFixedWindowRateLimiter(store)
            limit = RateLimitItemPerSecond(2, 1)
            assert await limiter.hit(limit)
            assert await limiter.test(limit)
            assert await limiter.hit(limit)
            assert not await limiter.test(limit)
            assert not await limiter.hit(limit)

    @pytest.mark.asyncio
    async def test_test_moving_window(self):
        with hiro.Timeline().freeze():
            store = AsyncMemoryStorage()
            limit = RateLimitItemPerSecond(2, 1)
            limiter = AsyncMovingWindowRateLimiter(store)
            assert await limiter.hit(limit)
            assert await limiter.test(limit)
            assert await limiter.hit(limit)
            assert not await limiter.test(limit)
            assert not await limiter.hit(limit)