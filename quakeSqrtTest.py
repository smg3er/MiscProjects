import argparse
import math
import multiprocessing as mp
import os
import struct
from time import perf_counter


def fast_inverse_sqrt(x):
    bits = struct.unpack("<I", struct.pack("<f", x))[0]
    bits = 0x5F3759DF - (bits >> 1)
    y = struct.unpack("<f", struct.pack("<I", bits))[0]
    return y * (1.5 - 0.5 * x * y * y)


def normal_inverse_sqrt(x):
    return 1.0 / math.sqrt(x)


def worker_ready(ready_queue):
    ready_queue.put(None)


def run_batch(args):
    func, x, repeats = args
    start = perf_counter()

    for _ in range(repeats):
        result = func(x)

    return result, perf_counter() - start


def benchmark(pool, func, x, repeats, workers):
    batch_size, remainder = divmod(repeats, workers)
    jobs = [
        (func, x, batch_size + (index < remainder))
        for index in range(workers)
    ]
    start = perf_counter()
    results = pool.map(run_batch, jobs, chunksize=1)
    elapsed = perf_counter() - start
    worker_time = sum(duration for _, duration in results)

    print(f"{func.__name__}:")
    print(f"  Результат: {results[0][0]:.10f}")
    print(f"  Всего вызовов: {repeats:,}")
    print(f"  Общее время: {elapsed:.6f} с")
    print(f"  Производительность: {repeats / elapsed:,.0f} вызовов/с")
    print(f"  Среднее время вызова внутри процесса: {worker_time / repeats * 1e9:.1f} нс")
    return elapsed


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Значение должно быть больше нуля")
    return number


def main():
    parser = argparse.ArgumentParser(description="Многопроцессный тест обратного квадратного корня")
    parser.add_argument("--repeats", type=positive_int, default=1_000_000_000)
    parser.add_argument("--workers", type=positive_int,
                        default=getattr(os, "process_cpu_count", os.cpu_count)() or 1)
    args = parser.parse_args()
    workers = min(args.workers, args.repeats)
    x = 4.0

    print(f"Процессов: {workers}; повторений на каждый тест: {args.repeats:,}")
    context = mp.get_context("spawn")
    ready_queue = context.Queue()
    try:
        with context.Pool(workers, initializer=worker_ready,
                          initargs=(ready_queue,)) as pool:
            # Дожидаемся запуска всех процессов до измерения времени.
            for _ in range(workers):
                ready_queue.get()
            fast_time = benchmark(pool, fast_inverse_sqrt, x, args.repeats, workers)
            normal_time = benchmark(pool, normal_inverse_sqrt, x, args.repeats, workers)
    finally:
        ready_queue.close()
        ready_queue.join_thread()

    print(f"\nОбычный способ быстрее в {fast_time / normal_time:.2f} раза")


if __name__ == "__main__":
    mp.freeze_support()
    main()
