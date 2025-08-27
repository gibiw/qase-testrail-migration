import functools
from concurrent.futures import ThreadPoolExecutor

import asyncio


class Pools:
    def __init__(
            self,
            qase_pool: ThreadPoolExecutor,
            tr_pool: ThreadPoolExecutor,
    ):
        self.qase_pool = qase_pool
        self.tr_pool = tr_pool

    @staticmethod
    async def async_gen(pool: ThreadPoolExecutor, fn, *args, **kwargs):
        def gen_next(gen):
            try:
                return next(gen)
            except StopIteration:
                pass

        gen = await asyncio.wrap_future(pool.submit(fn, *args, **kwargs))
        while True:
            if (i := await asyncio.wrap_future(pool.submit(gen_next, gen))) is None:
                break
            yield i

    @staticmethod
    async def async_gen_all(pool: ThreadPoolExecutor, fn, *args, **kwargs):
        return functools.reduce(lambda x, y: x + y, [_ async for _ in Pools.async_gen(pool, fn, *args, **kwargs)])

    def tr(self, fn, *args, **kwargs):
        # Check if pool is shutdown before submitting
        if self.tr_pool._shutdown:
            raise RuntimeError("ThreadPool is shutdown and cannot accept new tasks")
        return asyncio.wrap_future(self.tr_pool.submit(fn, *args, **kwargs))

    def qs(self, fn, *args, **kwargs):
        # Check if pool is shutdown before submitting
        if self.qase_pool._shutdown:
            raise RuntimeError("QasePool is shutdown and cannot accept new tasks")
        return asyncio.wrap_future(self.qase_pool.submit(fn, *args, **kwargs))

    async def tr_task(self, fn, *args, **kwargs):
        return await asyncio.wrap_future(self.tr_pool.submit(fn, *args, **kwargs))

    async def qs_task(self, fn, *args, **kwargs):
        return await asyncio.wrap_future(self.qase_pool.submit(fn, *args, **kwargs))

    def tr_gen(self, fn, *args, **kwargs):
        return self.async_gen(self.tr_pool, fn, *args, **kwargs)

    def qs_gen(self, fn, *args, **kwargs):
        return self.async_gen(self.qase_pool, fn, *args, **kwargs)

    async def tr_gen_all(self, fn, *args, **kwargs):
        return await self.async_gen_all(self.tr_pool, fn, *args, **kwargs)

    async def qs_gen_all(self, fn, *args, **kwargs):
        return await self.async_gen_all(self.qase_pool, fn, *args, **kwargs)

    def is_tr_pool_available(self) -> bool:
        """Check if TestRail thread pool is available and not shutdown"""
        return not self.tr_pool._shutdown

    def is_qase_pool_available(self) -> bool:
        """Check if Qase thread pool is available and not shutdown"""
        return not self.qase_pool._shutdown
