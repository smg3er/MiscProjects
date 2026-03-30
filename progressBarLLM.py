import sys
import time
import math

# ----------------------------------------------------------- #
# 1. Получаем входные данные от пользователя
# ----------------------------------------------------------- #
def read_int(prompt: str, min_val: int = 1) -> int:
    """Утилита для чтения целого числа > 0."""
    while True:
        try:
            value = int(input(prompt))
            if value < min_val:
                raise ValueError
            return value
        except ValueError:
            print(f"❗ Введите целое число, >= {min_val}.")

file_size_mb = read_int("Введите размер файла (МБ): ")
speed_mbps   = read_int("Введите скорость сети (Мбит/с): ")

# ----------------------------------------------------------- #
# 2. Переводим в байты и вычисляем общее время скачивания
# ----------------------------------------------------------- #
FILE_SIZE_BYTES     = file_size_mb * 1024 * 1024          # 1 MB = 1 048 576 B
SPEED_BYTES_PER_SEC = (speed_mbps * 1_000_000) // 8       # 1 Mbit = 125 000 B/s

total_time_sec = FILE_SIZE_BYTES / SPEED_BYTES_PER_SEC
print(f"\nИтоговое время скачивания ≈ {total_time_sec:.2f} с")

# ----------------------------------------------------------- #
# 3. Имитация скачивания
# ----------------------------------------------------------- #
def progress_bar(percentage: float, bar_length: int = 40) -> str:
    """Возвращает строку вида: [██████░░░░░]  60.00%"""
    filled = int(bar_length * percentage / 100)
    empty  = bar_length - filled
    full_block   = '█'   # можно заменить на '▓'
    empty_block  = '░'
    return f"[{full_block * filled}{empty_block * empty}] {percentage:6.2f}%"

# Какую часть будем «скачивать» за один шаг (чтобы прогресс‑бар обновлялся примерно
# раз в 0.1‑сек. и не тратил память). Делаем 1 % от файла или минимум 1 КБ.
CHUNK_BYTES = max(int(FILE_SIZE_BYTES * 0.01), 1024)

downloaded = 0
start_time = time.time()

while downloaded < FILE_SIZE_BYTES:
    # «Загружаем» один блок
    time_to_sleep = CHUNK_BYTES / SPEED_BYTES_PER_SEC
    time.sleep(time_to_sleep)

    downloaded += CHUNK_BYTES
    if downloaded > FILE_SIZE_BYTES:
        downloaded = FILE_SIZE_BYTES

    # Вычисляем процент
    percent = downloaded / FILE_SIZE_BYTES * 100

    # Обновляем прогресс‑бар в одной строке
    bar = progress_bar(percent)
    elapsed = time.time() - start_time
    # Формируем строку вывода
    sys.stdout.write(f"\r{bar}  {elapsed:6.1f}s")
    sys.stdout.flush()

# Завершаем прогресс‑бар
sys.stdout.write("\n✅ Скачивание завершено!\n")
